#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""歌单批量下载器 —— 支持 网易云歌单 与 QQ音乐歌单。

两条链路：
  netease 歌单：GD音乐台 `types=playlist` 接口取曲目表，逐首 `types=url` 取直链
  QQ 歌单    ：QQ 官方接口取曲目表，官方 vkey 接口取直链；VIP/受限曲目可按
                「歌手 + 歌名」到 GD 支持的源（netease/kuwo/joox）补齐，
                并用 ffprobe 时长核对是否同一版本（避免下到翻唱）

音频、歌词、封面下载逻辑与单曲脚本 download.py 同源（复用其 MusicClient /
try_download_item / 命名与限流），歌单相关逻辑是本脚本新增。

用法：
  python3 playlist_dl.py <歌单链接或ID> [选项]

示例：
  python3 playlist_dl.py https://music.163.com/playlist?id=19723756 --list
  python3 playlist_dl.py 19723756 --limit 20
  python3 playlist_dl.py https://i2.y.qq.com/n3/other/pages/details/playlist.html?...&id=2303919454 --list
  python3 playlist_dl.py 2303919454 --platform qq --limit 10
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys
import time
from urllib.parse import urlparse, parse_qs

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from download import (  # noqa: E402
    MusicAPIError, MusicClient, RateLimiter, QUALITY_CHAIN, QUALITY_LABEL,
    RATE_LIMIT_MAX, RATE_LIMIT_WINDOW, artists_to_str, load_config,
    sanitize_filename, try_download_item,
)

try:
    import requests
except ImportError:  # pragma: no cover
    sys.exit("需要 requests：pip install requests")

AUDIO_EXTS = (".mp3", ".flac", ".m4a", ".aac", ".wav", ".ogg", ".wma", ".ape")
DEFAULT_OWNER = "yuaxi:Users"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
# 实测 GD音乐台只支持这几个源（tencent/tidal/qobuz/spotify/apple/ytmusic/... 一律 400）
GD_SOURCES = ("netease", "kuwo", "joox")
QQ_HEADERS = {"User-Agent": UA, "Referer": "https://y.qq.com/"}
QQ_DISS_URL = ("https://c.y.qq.com/qzone/fcg-bin/fcg_ucc_getcdinfo_byids_cp.fcg"
               "?type=1&json=1&utf8=1&onlysong=0&new_format=1&disstid={pid}&format=json")
QQ_VKEY_URL = "https://u.y.qq.com/cgi-bin/musicu.fcg"
# 实测：一次请求多个音质档（F000/M800/C400）时，服务端会按"需要会员"的那一档回复，
# 反而把本可直连的曲目判成 104007。所以只请求 C400（无会员时服务端实际给的档位）。
QQ_FILENAMES = ["C400"]
QQ_VKEY_BATCH = 50          # 实测单次请求超过 50 个 mid 会被截断
QQ_VIP_CODES = {"104003", "104007"}


# ============ 平台识别 ============
def detect_platform(raw, forced="auto"):
    """返回 (platform, id)。纯数字 ID 无法区分平台，默认按 netease 处理并提示。"""
    text = (raw or "").strip()
    host = ""
    if text.startswith("http"):
        try:
            host = urlparse(text).netloc.lower()
        except ValueError:
            host = ""
    if forced == "auto":
        if any(k in host for k in ("y.qq.com", "c6.y.qq.com", "i2.y.qq.com", "qq.com")):
            platform = "qq"
        elif any(k in host for k in ("music.163.com", "163cn.tv", "y.music.163.com")):
            platform = "netease"
        elif text.isdigit():
            print("[提示] 只给了数字 ID，无法区分平台；默认按 netease 处理"
                  "（QQ 歌单请加 --platform qq）。")
            platform = "netease"
        else:
            platform = "netease"
    else:
        platform = forced

    if text.isdigit():
        return platform, text
    m = re.search(r"[?&]id=(\d+)", text) or re.search(r"/playlist/(\d+)", text)
    if m:
        return platform, m.group(1)
    if text.startswith("http"):
        try:
            resp = requests.get(text, timeout=20, allow_redirects=True,
                                headers={"User-Agent": UA})
            for candidate in (resp.url, resp.text[:40000]):
                m = (re.search(r"[?&]id=(\d+)", candidate or "")
                     or re.search(r"/playlist/(\d+)", candidate or "")
                     or re.search(r'"playlistId"\s*:\s*"?(\d+)', candidate or "")
                     or re.search(r'disstid["\']?\s*[:=]\s*["\']?(\d+)', candidate or ""))
                if m:
                    return platform, m.group(1)
        except Exception as exc:  # noqa: BLE001
            print("[歌单] 链接解析失败：%s" % exc)
    return platform, None


# ============ 网易云歌单（GD音乐台） ============
def fetch_netease_playlist(client, playlist_id):
    data = client._request({"types": "playlist", "source": "netease", "id": playlist_id})
    if not isinstance(data, dict) or data.get("detail"):
        raise MusicAPIError("歌单接口返回异常：%s" % str(data)[:200])
    pl = data.get("playlist")
    if not isinstance(pl, dict):
        raise MusicAPIError("歌单数据结构异常：%s" % str(data)[:200])
    items = []
    for track in (pl.get("tracks") or []):
        if not isinstance(track, dict):
            continue
        artists = [a.get("name") for a in (track.get("ar") or []) if isinstance(a, dict)]
        album = track.get("al") or {}
        if not isinstance(album, dict):
            album = {}
        items.append({
            "id": track.get("id"),
            "name": track.get("name") or "未知曲目",
            "artist": [a for a in artists if a] or ["未知歌手"],
            "album": album.get("name") or "未知专辑",
            "pic_id": album.get("picId"),
            "lyric_id": track.get("id"),
            "duration": round((track.get("dt") or 0) / 1000) or None,
            "source": "netease",
            "raw": track,
        })
    meta = {"name": pl.get("name"), "total": pl.get("trackCount"),
            "ids": pl.get("trackIds") or []}
    return meta, items


# ============ QQ 音乐歌单 ============
def _qq_json(url, params=None, data=None):
    headers = dict(QQ_HEADERS)
    if data is not None:
        headers["Content-Type"] = "application/json"
        resp = requests.post(url, headers=headers, data=data, timeout=30)
    else:
        resp = requests.get(url, headers=headers, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def fetch_qq_playlist(playlist_id):
    """先走 fcg 接口，失败再走 musicu.fcg 的 DissInfo 模块。"""
    raw = None
    try:
        raw = _qq_json(QQ_DISS_URL.format(pid=playlist_id))
    except Exception as exc:  # noqa: BLE001
        print("[歌单] QQ fcg 接口失败（%s），改用 musicu 接口。" % exc)
    cd = {}
    if isinstance(raw, dict):
        cdlist = raw.get("cdlist") or []
        if cdlist:
            cd = cdlist[0]
    if not cd:
        body = json.dumps({
            "comm": {"ct": 24, "cv": 0, "format": "json"},
            "req_0": {"module": "music.srfDissInfo.DissInfo",
                      "method": "CgiGetDiss",
                      "param": {"disstid": int(playlist_id), "dirid": 0,
                                "tag": 1, "song_begin": 0, "song_num": 1000,
                                "userinfo": 1, "pic_dpi": 800, "enc_host_uin": ""}},
        })
        resp = _qq_json(QQ_VKEY_URL, data=body)
        cd = (resp.get("req_0", {}).get("data") or {})
        if cd:
            cd = {"dissname": cd.get("dirinfo", {}).get("title"),
                  "songlist": cd.get("songlist") or [],
                  "total_song_num": cd.get("total") or cd.get("dirinfo", {}).get("songnum")}
    songs = cd.get("songlist") or []
    if not songs:
        raise MusicAPIError("QQ 歌单曲目为空（歌单可能被删除或需要登录）")

    items = []
    for s in songs:
        if not isinstance(s, dict):
            continue
        mid = s.get("mid") or s.get("songmid")
        if not mid:
            continue
        singer = s.get("singer") or []
        artists = [x.get("name") for x in singer if isinstance(x, dict) and x.get("name")]
        if not artists and s.get("singername"):
            artists = [x for x in re.split(r"[、/&,]", s["singername"]) if x]
        album = s.get("album") or {}
        if isinstance(album, dict):
            album_name = album.get("name")
        else:
            album_name = s.get("albumname")
        pay = s.get("pay") or {}
        items.append({
            "id": mid,
            "name": s.get("name") or s.get("songname") or "未知曲目",
            "artist": artists or ["未知歌手"],
            "album": album_name or "未知专辑",
            "pic_id": None,
            "album_mid": (album or {}).get("mid") if isinstance(album, dict) else None,
            "lyric_id": None,
            "duration": s.get("interval") or None,
            "source": "qq",
            "pay_play": pay.get("pay_play") if isinstance(pay, dict) else None,
            "raw": s,
        })
    meta = {"name": cd.get("dissname") or cd.get("dirinfo", {}).get("title"),
            "total": cd.get("total_song_num") or cd.get("songnum") or len(items),
            "ids": []}
    return meta, items


def qq_resolve_urls(mids):
    """官方 vkey 接口批量换直链，返回 (sip, {mid: (purl, filename, result)})。"""
    out, sip = {}, ""
    for i in range(0, len(mids), QQ_VKEY_BATCH):
        chunk = mids[i:i + QQ_VKEY_BATCH]
        body = json.dumps({
            "comm": {"uin": 0, "format": "json", "ct": 24, "cv": 0},
            "req_0": {"module": "vkey.GetVkeyServer", "method": "CgiGetVkey",
                      "param": {"guid": "10000", "songmid": chunk,
                                "songtype": [0] * len(chunk),
                                "filename": list(QQ_FILENAMES),
                                "uin": "0", "loginflag": 1, "platform": "20"}},
        })
        try:
            resp = _qq_json(QQ_VKEY_URL, data=body)
        except Exception as exc:  # noqa: BLE001
            print("[QQ] vkey 请求失败：%s" % exc)
            continue
        data = (resp.get("req_0") or {}).get("data") or {}
        sip = sip or ((data.get("sip") or [""])[0])
        for it in (data.get("midurlinfo") or []):
            out.setdefault(it.get("songmid"), (
                (it.get("purl") or "").strip(), it.get("filename") or "", it.get("result")))
        time.sleep(0.3)
    return sip, out


def qq_download(url, dest_path, referer="https://y.qq.com/"):
    headers = {"User-Agent": UA, "Referer": referer}
    tmp = dest_path + ".part"
    with requests.get(url, headers=headers, stream=True, timeout=60) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        with open(tmp, "wb") as fh:
            for chunk in resp.iter_content(262144):
                fh.write(chunk)
                done += len(chunk)
                if total:
                    print("\r  下载中 %5.1f%%  %.1f MB / %.1f MB" %
                          (done * 100.0 / total, done / 1048576.0, total / 1048576.0),
                          end="", flush=True)
    print()
    os.replace(tmp, dest_path)
    return os.path.getsize(dest_path)


# ============ 时长校验 / 歌词匹配（QQ 缺口补齐用） ============
def probe_duration(path):
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=60)
        return float((out.stdout or "0").strip() or 0)
    except Exception:  # noqa: BLE001
        return 0.0


def normalize_title(text):
    return re.sub(r"[\s\-_（）()\[\]【】·,.，、!！?？'\"“”‘’&+/]" , "",
                  (text or "").lower())


def search_exact(client, item, source, artists=None, fuzzy=True):
    """在指定源里找「歌名相同/互相包含 + 歌手有交集」的最佳候选。

    多轮关键词：歌手1+歌名 → 全部歌手+歌名 → 只搜歌名。
    fuzzy=True 时允许标题互相包含（用于长标题带英文副标题的情况）；
    歌手必须有一项相同，避免匹配到翻唱。
    """
    titles = [normalize_title(item["name"])]
    want_artists = [normalize_title(a) for a in (artists or item["artist"])]
    first = (artists or item["artist"])[:1] or [""]
    keywords = ["%s %s" % (first[0], item["name"]),
                "%s %s" % (" ".join(artists or item["artist"]), item["name"]),
                item["name"]]
    seen_keywords, results = set(), []
    for kw in keywords:
        kw = kw.strip()
        if not kw or kw in seen_keywords:
            continue
        seen_keywords.add(kw)
        try:
            results = client.search(kw, source=source, count=20)
        except Exception:  # noqa: BLE001
            results = []
        if results:
            break
    best = None
    for cand in results:
        cand_title = normalize_title(cand.get("name"))
        if not cand_title:
            continue
        if cand_title == titles[0]:
            title_score = 2
        elif fuzzy and (titles[0] in cand_title or cand_title in titles[0]):
            title_score = 1
        else:
            continue
        cand_artists = [normalize_title(a) for a in (cand.get("artist") or [])]
        overlap = any(a in cand_artists for a in want_artists if a)
        if not overlap:
            continue
        score = title_score * 2 + (1 if cand.get("id") else 0)
        if best is None or score > best[0]:
            best = (score, cand)
    return best[1] if best else None


def save_lyric_for(client, lyric_id, source, base_path):
    """直接用 GD 歌词接口写 .lrc（复用单曲脚本的返回结构）。"""
    try:
        import download as dl
        item = {"id": lyric_id, "lyric_id": lyric_id, "name": ""}
        return dl.save_lyric(client, item, source, base_path)
    except Exception as exc:  # noqa: BLE001
        print("  [歌词] 保存失败：%s" % exc)
        return None


# ============ 权限修正 ============
def fix_ownership(paths, owner=DEFAULT_OWNER):
    import grp
    import pwd
    if not paths or not owner or owner == "-":
        return 0
    try:
        user, group = owner.split(":", 1)
        uid, gid = pwd.getpwnam(user).pw_uid, grp.getgrnam(group).gr_gid
    except (ValueError, KeyError) as exc:
        print("[权限] 跳过（找不到 %s：%s）" % (owner, exc))
        return 0
    fixed = 0
    for audio_path in paths:
        stem = os.path.splitext(audio_path)[0]
        for path in sorted(glob.glob(glob.escape(stem) + ".*")):
            if os.path.isfile(path):
                try:
                    os.chown(path, uid, gid)
                    os.chmod(path, 0o644)
                    fixed += 1
                except OSError as exc:
                    print("[权限] %s 修正失败：%s" % (path, exc))
    return fixed


def existing_file(output_dir, stem):
    for path in glob.glob(os.path.join(glob.escape(output_dir), stem + ".*")):
        if os.path.splitext(path)[1].lower() in AUDIO_EXTS:
            return path
    return None


# ============ 主流程 ============
def build_parser():
    p = argparse.ArgumentParser(description="歌单批量下载（网易云 / QQ音乐）")
    p.add_argument("playlist", help="歌单 ID 或链接")
    p.add_argument("--platform", choices=["auto", "netease", "qq"], default="auto",
                   help="平台，默认按链接自动判断（纯数字 ID 默认 netease）")
    p.add_argument("--source", default="netease", choices=list(GD_SOURCES),
                   help="QQ 歌单补齐时用的源，默认 netease")
    p.add_argument("--br", type=int, default=None, help="音质，默认读配置")
    p.add_argument("--output", default=None, help="输出目录，默认读配置")
    p.add_argument("--list", action="store_true", help="只列曲目，不下载")
    p.add_argument("--limit", type=int, default=0, help="只处理前 N 首")
    p.add_argument("--start", type=int, default=1, help="从第 N 首开始（1 起）")
    p.add_argument("--sleep", type=float, default=0.5, help="每首间隔秒数")
    p.add_argument("--rate", default=None,
                   help="GD 限流 max/window 秒，默认 %s/%s" % (RATE_LIMIT_MAX, RATE_LIMIT_WINDOW))
    p.add_argument("--overwrite", action="store_true", help="已存在也重新下载")
    p.add_argument("--cover", action="store_true", help="同时下载封面（netease 源有效）")
    p.add_argument("--no-lyric", action="store_true", help="不下载歌词")
    p.add_argument("--no-translation", action="store_true", help="不保存翻译歌词")
    p.add_argument("--no-fallback", action="store_true",
                   help="QQ 歌单：VIP/受限曲目不补齐，只下能直连的")
    p.add_argument("--no-verify-duration", action="store_true",
                   help="QQ 补齐时不校验时长（默认校验，防止下成翻唱）")
    p.add_argument("--owner", default=DEFAULT_OWNER,
                   help="下载后修正属主，默认 %s，- 表示不改" % DEFAULT_OWNER)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    platform, playlist_id = detect_platform(args.playlist, args.platform)
    if not playlist_id:
        print("无法从 %r 解析出歌单 ID。" % args.playlist)
        return 2

    config = load_config()
    quality = args.br or config.get("quality") or 999
    if quality not in QUALITY_CHAIN:
        print("错误：音质必须是 %s 之一。" % "/".join(str(b) for b in QUALITY_CHAIN))
        return 2
    output_dir = args.output or config.get("download_dir")
    if not args.list and not output_dir:
        print("没有下载目录：请用 --output 指定，或先跑 download.py --set-dir。")
        return 2
    if output_dir:
        output_dir = os.path.abspath(os.path.expanduser(output_dir))

    limiter = None
    if args.rate:
        try:
            max_calls, window = args.rate.split("/")
            limiter = RateLimiter(max_calls=int(max_calls), window=float(window))
        except ValueError:
            print("--rate 格式应为 max/window，例如 120/300")
            return 2
    client = MusicClient(limiter=limiter)

    print("[歌单] 平台 %s ｜ ID %s ｜ 取曲目表..." % (platform, playlist_id))
    try:
        if platform == "qq":
            meta, items = fetch_qq_playlist(playlist_id)
        else:
            meta, items = fetch_netease_playlist(client, playlist_id)
    except MusicAPIError as exc:
        print("[歌单] 获取失败：%s" % exc)
        return 1

    print("[歌单] 《%s》｜ 官方曲目数 %s ｜ 本次拿到 %d 首"
          % (meta.get("name") or "未命名", meta.get("total"), len(items)))
    ids = meta.get("ids") or []
    if ids and len(items) < len(ids):
        print("[歌单] 注意：接口只返回 %d/%d 首（平台对超长歌单有截断）" % (len(items), len(ids)))

    start = max(1, args.start)
    end = len(items)
    if args.limit:
        end = min(end, start - 1 + args.limit)
    selected = list(enumerate(items, 1))[start - 1:end]

    if args.list:
        for idx, item in selected:
            extra = ""
            if item.get("duration"):
                extra += " 时长 %ss" % item["duration"]
            if item.get("pay_play"):
                extra += " (VIP)"
            print("%3d. %s - %s 《%s》%s  [%s]"
                  % (idx, artists_to_str(item["artist"]), item["name"],
                     item["album"], extra, item["id"]))
        print("[歌单] 共 %d 首，本次列出 %d 首" % (len(items), len(selected)))
        return 0

    os.makedirs(output_dir, exist_ok=True)

    # QQ 歌单：先批量换直链（一次拿到全部，避免边下边过期）
    qq_urls, qq_sip = {}, ""
    if platform == "qq":
        print("[歌单] 请求 QQ 官方直链（%d 首，分批 %d）..." % (len(items), QQ_VKEY_BATCH))
        qq_sip, qq_urls = qq_resolve_urls([it["id"] for it in items])
        direct = sum(1 for v in qq_urls.values() if v[0])
        print("[歌单] QQ 直链可用 %d/%d 首（其余为 VIP/受限，"
              "%s）" % (direct, len(items),
                        "将用 %s 源补齐" % args.source if not args.no_fallback else "跳过"))

    print("[歌单] 目录 %s ｜ 音质 %s (%s) ｜ 待处理 %d 首"
          % (output_dir, quality, QUALITY_LABEL.get(quality, quality), len(selected)))

    ok, skipped, failed, new_paths = 0, 0, [], []
    for n, (idx, item) in enumerate(selected, 1):
        artist = artists_to_str(item["artist"])
        stem = sanitize_filename("%s - %s" % (artist, item["name"]))
        print("\n[%d/%d] %s - %s 《%s》"
              % (n, len(selected), artist, item["name"], item["album"]))
        if not args.overwrite and existing_file(output_dir, stem):
            print("  已存在，跳过")
            skipped += 1
            continue

        if platform != "qq":
            try:
                path = try_download_item(
                    client, item, item["source"], quality, output_dir,
                    want_lyric=not args.no_lyric,
                    want_translation=not args.no_translation,
                    want_cover=args.cover)
            except KeyboardInterrupt:
                print("\n已中断（可用 --start 续传）。")
                break
            except Exception as exc:  # noqa: BLE001
                print("  异常：%s" % exc)
                path = None
            if path:
                ok += 1
                new_paths.append(path)
            else:
                failed.append("%s - %s (id=%s)" % (artist, item["name"], item["id"]))
            if args.sleep and n < len(selected):
                time.sleep(args.sleep)
            continue

        # ---- QQ 歌单：直链优先，VIP 走补齐 ----
        purl, fname, result = qq_urls.get(item["id"], ("", "", None))
        path = None
        if purl:
            ext = ".m4a" if ".m4a" in fname.lower() else ".mp3"
            dest = os.path.join(output_dir, stem + ext)
            try:
                size = qq_download(qq_sip + purl, dest)
                print("  QQ 官方直链保存：%s (%.1f MB, %s)"
                      % (os.path.basename(dest), size / 1048576.0,
                         "AAC" if ext == ".m4a" else "mp3"))
                path = dest
            except Exception as exc:  # noqa: BLE001
                print("  QQ 直链下载失败：%s" % exc)
                path = None
            if path and not args.no_lyric:
                # QQ 没有歌词接口，用 GD 支持的源按「歌名完全相同 + 歌手有交集」取歌词
                cand = search_exact(client, item, args.source)
                if cand and (cand.get("lyric_id") or cand.get("id")):
                    save_lyric_for(client, cand.get("lyric_id") or cand.get("id"),
                                   args.source, os.path.splitext(dest)[0])
                    print("  [歌词] 取自 %s 匹配：%s - %s"
                          % (args.source, "/".join(cand.get("artist") or []),
                             cand.get("name")))
                else:
                    print("  [歌词] %s 源无匹配版本，跳过歌词" % args.source)
        elif args.no_fallback:
            reason = "VIP" if str(result) in QQ_VIP_CODES else ("code=%s" % result)
            print("  跳过（%s，未开启补齐）" % reason)
            failed.append("%s - %s (QQ %s)" % (artist, item["name"], reason))
            continue
        else:
            print("  QQ 直链不可用（result=%s），到 %s 源补齐..." % (result, args.source))

        if path is None and not args.no_fallback:
            for src in ([args.source] if args.no_fallback else [args.source]):
                cand = search_exact(client, item, src)
                if not cand:
                    print("  [%s] 没有歌名完全匹配的候选" % src)
                    continue
                print("  [%s] 候选：%s - %s (id=%s)"
                      % (src, "/".join(cand.get("artist") or []), cand.get("name"), cand.get("id")))
                tmp_stem = stem + ".__probe"
                probe_dir = output_dir
                cand_item = dict(cand)
                cand_item["lyric_id"] = cand.get("lyric_id") or cand.get("id")
                try:
                    got = try_download_item(
                        client, cand_item, src, quality, probe_dir,
                        want_lyric=False, want_translation=False, want_cover=False)
                except Exception as exc:  # noqa: BLE001
                    print("  [%s] 下载异常：%s" % (src, exc))
                    got = None
                if not got:
                    print("  [%s] 下载失败" % src)
                    continue
                # 时长核对：QQ 侧 interval vs 实际文件时长
                want = item.get("duration") or 0
                real = probe_duration(got)
                if args.no_verify_duration or not want or not real:
                    print("  [%s] 已补齐（未校验时长：QQ=%ss 实际=%.1fs）" % (src, want, real))
                elif abs(real - want) <= 3:
                    print("  [%s] 时长校验通过：QQ %ss vs 实际 %.1fs" % (src, want, real))
                else:
                    print("  [%s] 时长不符（QQ %ss vs 实际 %.1fs），判定为不同版本，删除"
                          % (src, want, real))
                    for extra in glob.glob(glob.escape(os.path.splitext(got)[0]) + ".*"):
                        os.remove(extra)
                    cand = None
                    continue
                path = got
                if not args.no_lyric and cand.get("lyric_id"):
                    save_lyric_for(client, cand["lyric_id"], src,
                                   os.path.splitext(got)[0])
                break

        if path:
            ok += 1
            new_paths.append(path)
        else:
            failed.append("%s - %s (id=%s)" % (artist, item["name"], item["id"]))
        if args.sleep and n < len(selected):
            time.sleep(args.sleep)

    if new_paths and args.owner and args.owner != "-":
        fixed = fix_ownership(new_paths, owner=args.owner)
        print("\n[权限] 已把 %d 个文件修正为 %s 644" % (fixed, args.owner))

    print("\n===== 汇总 =====")
    print("成功 %d ｜ 跳过 %d ｜ 失败 %d ｜ 目录 %s"
          % (ok, skipped, len(failed), output_dir))
    if failed:
        print("失败清单（可重跑续传）：")
        for line in failed:
            print("  - %s" % line)
    return 0 if not failed else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n已中断。")
        sys.exit(130)
