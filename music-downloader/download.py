#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GD音乐台 音乐搜索 / 下载器
============================
基于 GD音乐台 API（https://music-api.gdstudio.xyz/api.php）：

  * search : types=search&source=..&name=..&count=..&pages=..
  * url    : types=url&source=..&id=..&br=[128/192/320/740/999]
  * lyric  : types=lyric&source=..&id=..        (lyric_id)
  * pic    : types=pic&source=..&id=..&size=300/500 (pic_id)

音质降级策略：999(24bit无损) -> 740(16bit无损) -> 320 -> 192 -> 128
跨源回退：netease -> tencent -> kuwo -> tidal -> qobuz -> joox -> bilibili -> apple -> ytmusic -> spotify

首次使用会询问下载目录与音质偏好，并记入 .music-downloader.json。

用法示例：
  python download.py "练习"                        # 搜索并交互选择后下载
  python download.py "周杰伦 晴天" --select 1       # 直接下载第 1 条
  python download.py "Hello" --search-only --json   # 仅搜索，输出 JSON
  python download.py --set-dir "D:\\Music"         # 设置默认下载目录
  python download.py --set-quality 320             # 设置默认音质
  python download.py "Hello" --source joox --no-lyric
  python download.py "冷门歌" --no-fallback         # 只在指定源尝试

仅供个人学习交流使用，请勿用于商业用途。音乐版权归各音乐平台所有。
"""

import argparse
import json
import os
import re
import sys
import time
from collections import deque
from urllib.parse import urlparse

try:
    import requests
except ImportError:  # pragma: no cover
    sys.stderr.write("缺少依赖 requests，请先运行：pip install requests\n")
    sys.exit(1)

# Windows 控制台中文输出兼容
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
API_BASE = "https://music-api.gdstudio.xyz/api.php"
DEFAULT_SOURCE = "netease"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, ".music-downloader.json")

try:
    _INPUT = input
except NameError:  # pragma: no cover - 非交互环境
    def _INPUT(prompt=""):
        raise EOFError("no stdin")

QUALITY_CHAIN = [999, 740, 320, 192, 128]
QUALITY_LABEL = {999: "24bit无损", 740: "16bit无损", 320: "320K", 192: "192K", 128: "128K"}
SOURCE_ORDER = [
    "netease", "tencent", "kuwo", "tidal", "qobuz",
    "joox", "bilibili", "apple", "ytmusic", "spotify",
]
SUPPORTED_SOURCES = list(SOURCE_ORDER)
RATE_LIMIT_MAX = 50
RATE_LIMIT_WINDOW = 300  # 秒
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def order_sources(preferred, all_sources=SOURCE_ORDER):
    """把 preferred 提到最前，其余按默认顺序跟随，得到尝试顺序。"""
    rest = [s for s in all_sources if s != preferred]
    return [preferred] + rest


class MusicAPIError(Exception):
    """接口返回异常或网络请求失败。"""


class RateLimiter:
    """滑动窗口限流：window 秒内最多 max_calls 次请求。"""

    def __init__(self, max_calls=RATE_LIMIT_MAX, window=RATE_LIMIT_WINDOW):
        self.max_calls = max_calls
        self.window = window
        self.calls = deque()

    def wait(self):
        now = time.time()
        while self.calls and now - self.calls[0] > self.window:
            self.calls.popleft()
        if len(self.calls) >= self.max_calls:
            sleep_for = self.window - (now - self.calls[0]) + 1
            if sleep_for > 0:
                print("[限流] 5 分钟内已达 %d 次请求，等待 %.0f 秒 ..." % (self.max_calls, sleep_for))
                time.sleep(sleep_for)
            return self.wait()
        self.calls.append(time.time())


class MusicClient:
    def __init__(self, base=API_BASE, timeout=15, retries=3, backoff=1.5, limiter=None):
        self.base = base
        self.timeout = timeout
        self.retries = retries
        self.backoff = backoff
        self.limiter = limiter or RateLimiter()
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://music.gdstudio.xyz/",
        })

    # ---------- 底层请求 ----------
    def _request(self, params):
        last_err = None
        for attempt in range(1, self.retries + 1):
            try:
                self.limiter.wait()
                resp = self.session.get(self.base, params=params, timeout=self.timeout)
                if resp.status_code == 429:
                    raise MusicAPIError("HTTP 429：请求过于频繁")
                resp.raise_for_status()
                try:
                    return resp.json()
                except ValueError:
                    return json.loads(resp.text)
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                if attempt < self.retries:
                    sleep_for = self.backoff * attempt
                    print("[重试] 第 %d/%d 次请求失败：%s，%.1fs 后重试 ..."
                          % (attempt, self.retries, exc, sleep_for))
                    time.sleep(sleep_for)
        raise MusicAPIError("请求失败：%s" % last_err)

    # ---------- 业务接口 ----------
    def search(self, name, source=DEFAULT_SOURCE, count=20, pages=1):
        data = self._request({
            "types": "search", "source": source,
            "name": name, "count": count, "pages": pages,
        })
        if isinstance(data, dict):
            if data.get("error"):
                raise MusicAPIError(str(data["error"]))
            data = data.get("data") or data.get("result") or []
        if not isinstance(data, list):
            raise MusicAPIError("搜索返回格式异常：%s" % data)
        return data

    def get_url(self, track_id, source=DEFAULT_SOURCE, br=999):
        return self._request({
            "types": "url", "source": source, "id": track_id, "br": br,
        })

    def get_lyric(self, lyric_id, source=DEFAULT_SOURCE):
        return self._request({
            "types": "lyric", "source": source, "id": lyric_id,
        })

    def get_pic(self, pic_id, source=DEFAULT_SOURCE, size=500):
        return self._request({
            "types": "pic", "source": source, "id": pic_id, "size": size,
        })

    def resolve_audio(self, track_id, source=DEFAULT_SOURCE, chain=None):
        """按音质链依次尝试，返回 (url, actual_br, size_bytes)。

        注意：接口文档称 size 单位为 KB，实测其值等于文件 Content-Length（字节）。
        """
        chain = chain or QUALITY_CHAIN
        last_error = None
        for br in chain:
            try:
                data = self.get_url(track_id, source=source, br=br)
            except MusicAPIError as exc:
                last_error = exc
                continue
            if not isinstance(data, dict):
                last_error = MusicAPIError("url 接口返回格式异常：%s" % data)
                continue
            if data.get("error"):
                last_error = MusicAPIError(str(data["error"]))
                continue
            url = data.get("url")
            if url and str(url).strip() and str(url).lower() != "null":
                actual = data.get("br") or br
                try:
                    actual = int(actual)
                except (TypeError, ValueError):
                    pass
                size = data.get("size") or 0
                try:
                    size = int(float(size))
                except (TypeError, ValueError):
                    size = 0
                return url, actual, size
            last_error = MusicAPIError("br=%s 无可用链接" % br)
        raise MusicAPIError("未获取到任何可用音质：%s" % last_error)


# ---------- 工具函数 ----------
def artists_to_str(artist):
    if isinstance(artist, (list, tuple)):
        return ", ".join(str(a).strip() for a in artist if str(a).strip()) or "未知歌手"
    if artist is None:
        return "未知歌手"
    return str(artist).strip() or "未知歌手"


def name_matches(query, item):
    """粗略判断搜索结果是否与关键字相关（用于跨源回退时筛选）。"""
    name = str(item.get("name") or "")
    artist = artists_to_str(item.get("artist"))
    album = str(item.get("album") or "")
    haystack = ("%s %s %s" % (name, artist, album)).lower()
    tokens = [t for t in re.split(r"\s+", str(query).lower().strip()) if t]
    if not tokens:
        return True
    return any(t in haystack for t in tokens)


# ---------- 配置（下载位置 / 音质记忆） ----------
def load_config():
    if not os.path.exists(CONFIG_PATH):
        return {}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_config(config):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
            json.dump(config, fh, ensure_ascii=False, indent=2)
        return True
    except OSError as exc:
        print("[配置] 保存失败：%s" % exc)
        return False


def is_interactive():
    try:
        return sys.stdin is not None and sys.stdin.isatty()
    except (AttributeError, ValueError):
        return False


def resolve_output_dir(args):
    """决定下载目录：--output > 已保存的配置 > 询问用户。

    首次使用（无 --output 且无配置）时会询问用户把音乐放在哪里，
    并把答案记住，之后不再询问。
    """
    if args.output:
        return os.path.abspath(os.path.expanduser(args.output))

    config = load_config()
    saved = config.get("download_dir")
    if saved:
        return os.path.abspath(os.path.expanduser(saved))

    default_dir = os.path.join(SCRIPT_DIR, "downloads")
    if args.search_only or not is_interactive():
        return default_dir

    print("\n首次使用，请设置音乐下载位置（直接回车使用默认目录）。")
    try:
        raw = _INPUT("下载目录 [%s]：" % default_dir).strip().strip('"')
    except (EOFError, KeyboardInterrupt):
        print()
        return default_dir
    chosen = os.path.abspath(os.path.expanduser(raw)) if raw else default_dir
    config["download_dir"] = chosen
    save_config(config)
    print("已记住下载目录：%s（下次将不再询问）\n" % chosen)
    return chosen


def parse_quality(raw, default=999):
    """把用户输入的画质选项解析为 br 值。接受序号或直接数值。"""
    raw = str(raw).strip().lower()
    if raw in ("", "d", "default"):
        return default
    menu = {"1": 999, "2": 320, "3": 128, "999": 999, "320": 320, "128": 128}
    if raw in menu:
        return menu[raw]
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value in QUALITY_CHAIN else default


def resolve_quality(args):
    """决定首选音质：--br > 已保存的配置 > 询问用户。

    首次使用（未显式指定 --br 且无配置）时询问音质偏好，并记住答案；
    下载失败时会自动降级。
    """
    config = load_config()
    if args.br_explicit:
        config["quality"] = args.br
        save_config(config)
        return args.br

    saved = config.get("quality")
    if saved in QUALITY_CHAIN:
        return saved

    if not is_interactive():
        return args.br

    print("\n首次使用，请选择音频音质（直接回车默认 1）。")
    print("  1. 24bit 无损 999（默认，失败自动降级）")
    print("  2. 320K")
    print("  3. 128K")
    try:
        raw = _INPUT("请选择 [1]：")
    except (EOFError, KeyboardInterrupt):
        print()
        return args.br
    quality = parse_quality(raw, default=args.br)
    config["quality"] = quality
    save_config(config)
    print("已记住音质偏好：%s (%s)（下次将不再询问）\n"
          % (quality, QUALITY_LABEL.get(quality, quality)))
    return quality


def resolve_output_dir_and_quality(args):
    """首次运行时一次性询问下载目录与音质，均写入配置。"""
    output_dir = resolve_output_dir(args)
    quality = resolve_quality(args)
    return output_dir, quality


def sanitize_filename(name):
    name = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", str(name))
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name[:120] or "unknown"


def guess_extension(url, br):
    ext = os.path.splitext(urlparse(url).path)[1].lower()
    if ext in (".mp3", ".flac", ".m4a", ".aac", ".ogg", ".wav", ".ape", ".wma"):
        return ext
    return ".flac" if br in (999, 740) else ".mp3"


def unique_path(directory, stem, ext):
    path = os.path.join(directory, stem + ext)
    index = 1
    while os.path.exists(path):
        path = os.path.join(directory, "%s (%d)%s" % (stem, index, ext))
        index += 1
    return path


def format_size(num_bytes):
    for unit in ("B", "KB", "MB", "GB"):
        if num_bytes < 1024 or unit == "GB":
            return "%.1f %s" % (num_bytes, unit)
        num_bytes /= 1024.0


def print_results(results, source):
    print("\n在 [%s] 源搜索到 %d 条结果：\n" % (source, len(results)))
    for idx, item in enumerate(results, start=1):
        name = item.get("name") or "未知曲目"
        artist = artists_to_str(item.get("artist"))
        album = item.get("album") or "未知专辑"
        print("  %2d. %s - %s  《%s》  [id=%s]"
              % (idx, name, artist, album, item.get("id")))


def choose_result(results, select):
    if select is not None:
        if not 1 <= select <= len(results):
            raise SystemExit("错误：--select 取值范围为 1 ~ %d" % len(results))
        return results[select - 1]
    if len(results) == 1:
        return results[0]
    while True:
        raw = input("请选择要下载的序号（默认 1，输入 q 退出）：").strip()
        if raw.lower() in ("q", "quit", "exit"):
            raise SystemExit("已取消下载。")
        if raw == "":
            return results[0]
        if raw.isdigit() and 1 <= int(raw) <= len(results):
            return results[int(raw) - 1]
        print("输入无效，请输入 1 ~ %d 之间的序号。" % len(results))


def download_file(url, dest_path, expected_size_bytes=0):
    headers = {"User-Agent": USER_AGENT, "Referer": "https://music.gdstudio.xyz/"}
    with requests.get(url, headers=headers, stream=True, timeout=30) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("Content-Length") or 0)
        if total <= 0 and expected_size_bytes:
            total = expected_size_bytes
        downloaded = 0
        start = time.time()
        with open(dest_path, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                fh.write(chunk)
                downloaded += len(chunk)
                if total > 0:
                    percent = downloaded * 100.0 / total
                    speed = downloaded / max(time.time() - start, 0.001)
                    sys.stdout.write(
                        "\r  下载中 %5.1f%%  %s / %s  (%s/s)   "
                        % (percent, format_size(downloaded), format_size(total), format_size(speed))
                    )
                else:
                    sys.stdout.write("\r  下载中 %s   " % format_size(downloaded))
                sys.stdout.flush()
        sys.stdout.write("\n")
    return downloaded


def save_lyric(client, item, source, base_path, want_translation=True):
    lyric_id = item.get("lyric_id") or item.get("id")
    if not lyric_id:
        return None
    try:
        data = client.get_lyric(lyric_id, source=source)
    except MusicAPIError as exc:
        print("[歌词] 获取失败：%s" % exc)
        return None
    if not isinstance(data, dict):
        return None
    lyric = data.get("lyric")
    tlyric = data.get("tlyric") if want_translation else None
    if not lyric or str(lyric).strip().lower() in ("null", "none", ""):
        print("[歌词] 该曲目无歌词。")
        return None
    lrc_path = base_path + ".lrc"
    with open(lrc_path, "w", encoding="utf-8") as fh:
        fh.write(str(lyric))
    print("[歌词] 已保存：%s" % lrc_path)
    if tlyric and str(tlyric).strip().lower() not in ("null", "none", ""):
        trans_path = base_path + ".trans.lrc"
        with open(trans_path, "w", encoding="utf-8") as fh:
            fh.write(str(tlyric))
        print("[歌词] 已保存翻译：%s" % trans_path)
    return lrc_path


def save_cover(client, item, source, base_path):
    pic_id = item.get("pic_id")
    if not pic_id:
        return None
    try:
        data = client.get_pic(pic_id, source=source, size=500)
    except MusicAPIError as exc:
        print("[封面] 获取失败：%s" % exc)
        return None
    url = (data or {}).get("url") if isinstance(data, dict) else None
    if not url:
        print("[封面] 无可用封面。")
        return None
    ext = os.path.splitext(urlparse(url).path)[1].lower()
    if ext not in (".jpg", ".jpeg", ".png", ".webp", ".bmp"):
        ext = ".jpg"
    cover_path = base_path + ext
    try:
        download_file(url, cover_path)
    except Exception as exc:  # noqa: BLE001
        print("[封面] 下载失败：%s" % exc)
        return None
    print("[封面] 已保存：%s" % cover_path)
    return cover_path


def try_download_item(client, item, source, quality, output_dir,
                      want_lyric=True, want_translation=True, want_cover=False):
    """尝试下载给定搜索结果；成功返回音频路径，失败返回 None。

    会按音质链尝试获取直链并下载。歌词/封面在该源下载成功后附带保存。
    """
    name = item.get("name") or "未知曲目"
    artist = artists_to_str(item.get("artist"))
    track_id = item.get("id")
    if not track_id:
        print("[跳过] 结果缺少曲目 ID。")
        return None

    chain = [quality] + [b for b in QUALITY_CHAIN if b != quality]
    try:
        url, actual_br, size_bytes = client.resolve_audio(track_id, source=source, chain=chain)
    except MusicAPIError as exc:
        print("[%s] 获取下载链接失败：%s" % (source, exc))
        return None
    label = QUALITY_LABEL.get(actual_br, str(actual_br))
    print("[%s] 已获取链接：音质 %s (%s)，大小约 %s"
          % (source, actual_br, label, format_size(size_bytes) if size_bytes else "未知"))

    ext = guess_extension(url, actual_br)
    stem = sanitize_filename("%s - %s" % (artist, name))
    audio_path = unique_path(output_dir, stem, ext)
    try:
        size = download_file(url, audio_path, expected_size_bytes=size_bytes)
    except Exception as exc:  # noqa: BLE001
        print("[%s] 下载失败：%s" % (source, exc))
        try:
            if os.path.exists(audio_path):
                os.remove(audio_path)
        except OSError:
            pass
        return None
    print("[%s] 音频已保存：%s (%s)" % (source, audio_path, format_size(size)))

    base_path = os.path.splitext(audio_path)[0]
    if want_lyric:
        save_lyric(client, item, source, base_path, want_translation=want_translation)
    if want_cover:
        save_cover(client, item, source, base_path)
    return audio_path


def pick_candidate(results, query):
    """从搜索结果中挑一条与关键字最相关的曲目（优先精确匹配歌名）。"""
    if not results:
        return None
    query_l = str(query).lower().strip()
    for item in results:
        if str(item.get("name") or "").lower().strip() == query_l:
            return item
    for item in results:
        if name_matches(query, item):
            return item
    return results[0]


def search_with_fallback(client, keyword, preferred_source, count, pages,
                         fallback=True, source_order=SOURCE_ORDER):
    """搜索：优先源失败/无结果时依次尝试其他源。

    返回 (results, actual_source)；全部失败返回 ([], None)。
    """
    sources = order_sources(preferred_source, source_order) if fallback else [preferred_source]
    for idx, source in enumerate(sources):
        if idx > 0:
            print("  [回退] 尝试音乐源：%s ..." % source)
        print("正在 [%s] 源搜索：%s ..." % (source, keyword))
        try:
            results = client.search(keyword, source=source, count=count, pages=pages)
        except MusicAPIError as exc:
            print("  [%s] 搜索失败：%s" % (source, exc))
            results = []
        if results:
            return results, source
        print("  [%s] 未搜索到结果。" % source)
    return [], None


def build_parser():
    parser = argparse.ArgumentParser(
        description="GD音乐台 音乐搜索与下载器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="仅供个人学习交流使用，请勿用于商业用途。",
    )
    parser.add_argument("keyword", nargs="?", help="搜索关键字：歌曲名 / 歌手 / 专辑")
    parser.add_argument("--source", default=DEFAULT_SOURCE,
                        help="音乐源，默认 netease；可选 %s" % "/".join(SUPPORTED_SOURCES))
    parser.add_argument("--select", type=int, default=None,
                        help="直接选择搜索结果的第 N 条（1 开始）")
    parser.add_argument("--count", type=int, default=20, help="搜索返回条数，默认 20")
    parser.add_argument("--pages", type=int, default=1, help="搜索页码，默认 1")
    parser.add_argument("--br", type=int, default=999,
                        help="首选音质，默认 999；失败时自动降级 740->320->192->128")
    parser.add_argument("--output", default=None,
                        help="下载目录，覆盖并记住该位置；首次使用未指定时会询问")
    parser.add_argument("--set-dir", default=None,
                        help="仅设置并保存默认下载目录，然后退出")
    parser.add_argument("--set-quality", type=int, default=None,
                        help="仅设置并保存默认音质（999/740/320/192/128），然后退出")
    parser.add_argument("--no-fallback", action="store_true",
                        help="搜索/下载失败时不尝试其他音乐源，仅用 --source")
    parser.add_argument("--search-only", action="store_true", help="仅搜索并展示结果，不下载")
    parser.add_argument("--json", action="store_true", help="配合 --search-only，以 JSON 输出结果")
    parser.add_argument("--first", action="store_true", help="多条结果时自动选择第 1 条，不交互")
    parser.add_argument("--no-lyric", action="store_true", help="不下载歌词")
    parser.add_argument("--no-translation", action="store_true", help="不保存翻译歌词")
    parser.add_argument("--cover", action="store_true", help="同时下载专辑封面")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    args.br_explicit = any(a == "--br" or a.startswith("--br=") for a in (argv if argv is not None else sys.argv[1:]))

    if args.set_dir:
        chosen = os.path.abspath(os.path.expanduser(args.set_dir))
        config = load_config()
        config["download_dir"] = chosen
        if save_config(config):
            print("已设置默认下载目录：%s" % chosen)
            return 0
        return 1

    if args.set_quality is not None:
        if args.set_quality not in QUALITY_CHAIN:
            print("错误：音质必须是 %s 之一。" % "/".join(str(b) for b in QUALITY_CHAIN))
            return 2
        config = load_config()
        config["quality"] = args.set_quality
        if save_config(config):
            print("已设置默认音质：%s (%s)"
                  % (args.set_quality, QUALITY_LABEL.get(args.set_quality, args.set_quality)))
            return 0
        return 1

    if not args.keyword:
        parser.print_help()
        return 2

    if args.source not in SUPPORTED_SOURCES and not args.source.endswith("_album"):
        print("[警告] 未知音乐源 %s，仍将尝试请求。" % args.source)

    client = MusicClient()
    fallback = not args.no_fallback

    # 0. 首次使用：询问下载目录与音质偏好（非 search-only 时）
    if args.search_only:
        quality = args.br
    else:
        _, quality = resolve_output_dir_and_quality(args)

    # 1. 搜索（带跨源回退）
    results, actual_source = search_with_fallback(
        client, args.keyword, args.source, args.count, args.pages, fallback=fallback)
    if not results:
        print("所有音乐源均未搜索到结果。")
        return 1

    if args.search_only:
        if args.json:
            print(json.dumps(results, ensure_ascii=False, indent=2))
        else:
            print_results(results, actual_source)
        return 0

    print_results(results, actual_source)

    # 2. 选择曲目
    if args.select is not None or args.first or len(results) == 1:
        select = args.select if args.select is not None else 1
        item = choose_result(results, select)
    else:
        item = choose_result(results, None)

    name = item.get("name") or "未知曲目"
    artist = artists_to_str(item.get("artist"))
    album = item.get("album") or "未知专辑"
    if not item.get("id"):
        print("错误：该结果缺少曲目 ID，无法下载。")
        return 1
    print("\n已选择：%s - %s 《%s》 (id=%s)"
          % (name, artist, album, item.get("id")))

    output_dir = resolve_output_dir(args)
    os.makedirs(output_dir, exist_ok=True)

    print("音质优先级：%s -> %s" % (quality, " -> ".join(
        str(b) for b in QUALITY_CHAIN if b != quality)))

    # 3. 下载：先在当前源尝试，失败则用同一关键词在其他源重新搜索并下载
    sources = order_sources(actual_source, SOURCE_ORDER) if fallback else [actual_source]
    audio_path = None
    for idx, source in enumerate(sources):
        if idx > 0:
            print("\n[回退] 在 [%s] 源重新搜索并下载 ..." % source)
            try:
                alt_results = client.search(args.keyword, source=source,
                                            count=args.count, pages=args.pages)
            except MusicAPIError as exc:
                print("  [%s] 搜索失败：%s" % (source, exc))
                continue
            if not alt_results:
                print("  [%s] 未搜索到结果。" % source)
                continue
            alt = pick_candidate(alt_results, name if args.first else args.keyword)
            if not alt or not alt.get("id"):
                continue
            print("  [%s] 找到：%s - %s 《%s》"
                  % (source, alt.get("name"), artists_to_str(alt.get("artist")),
                     alt.get("album") or "未知专辑"))
            item, actual_source = alt, source
        audio_path = try_download_item(
            client, item, source, quality, output_dir,
            want_lyric=not args.no_lyric,
            want_translation=not args.no_translation,
            want_cover=args.cover,
        )
        if audio_path:
            break
        if fallback:
            print("  [%s] 下载未成功，继续尝试下一音乐源。" % source)

    if not audio_path:
        print("\n所有音乐源均下载失败。")
        return 1

    print("\n完成！文件位于：%s" % output_dir)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n已中断。")
        sys.exit(130)
