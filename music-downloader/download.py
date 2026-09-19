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

用法示例：
  python download.py "练习"                        # 搜索并交互选择后下载
  python download.py "周杰伦 晴天" --select 1       # 直接下载第 1 条
  python download.py "Hello" --search-only --json   # 仅搜索，输出 JSON
  python download.py "Hello" --source joox --no-lyric

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
QUALITY_CHAIN = [999, 740, 320, 192, 128]
QUALITY_LABEL = {999: "24bit无损", 740: "16bit无损", 320: "320K", 192: "192K", 128: "128K"}
SUPPORTED_SOURCES = [
    "netease", "joox", "bilibili", "tencent", "kuwo",
    "tidal", "qobuz", "apple", "ytmusic", "spotify",
]
RATE_LIMIT_MAX = 50
RATE_LIMIT_WINDOW = 300  # 秒
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


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
def sanitize_filename(name):
    name = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", str(name))
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name[:120] or "unknown"


def artists_to_str(artist):
    if isinstance(artist, (list, tuple)):
        return ", ".join(str(a).strip() for a in artist if str(a).strip()) or "未知歌手"
    if artist is None:
        return "未知歌手"
    return str(artist).strip() or "未知歌手"


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
    parser.add_argument("--output", default=None, help="下载目录，默认脚本所在目录的 downloads/")
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
    if not args.keyword:
        parser.print_help()
        return 2

    if args.source not in SUPPORTED_SOURCES and not args.source.endswith("_album"):
        print("[警告] 未知音乐源 %s，仍将尝试请求。" % args.source)

    client = MusicClient()

    # 1. 搜索
    print("正在 [%s] 源搜索：%s ..." % (args.source, args.keyword))
    try:
        results = client.search(args.keyword, source=args.source,
                                count=args.count, pages=args.pages)
    except MusicAPIError as exc:
        print("搜索失败：%s" % exc)
        return 1
    if not results:
        print("未搜索到任何结果。")
        return 1

    if args.search_only:
        if args.json:
            print(json.dumps(results, ensure_ascii=False, indent=2))
        else:
            print_results(results, args.source)
        return 0

    print_results(results, args.source)

    # 2. 选择曲目
    if args.select is not None or args.first or len(results) == 1:
        select = args.select if args.select is not None else 1
        item = choose_result(results, select)
    else:
        item = choose_result(results, None)

    name = item.get("name") or "未知曲目"
    artist = artists_to_str(item.get("artist"))
    album = item.get("album") or "未知专辑"
    track_id = item.get("id")
    if not track_id:
        print("错误：该结果缺少曲目 ID，无法下载。")
        return 1
    print("\n已选择：%s - %s 《%s》 (id=%s)" % (name, artist, album, track_id))

    # 3. 解析音质链
    chain = [args.br] + [b for b in QUALITY_CHAIN if b != args.br]
    print("正在获取下载链接（音质优先级：%s）..." % " -> ".join(str(b) for b in chain))
    try:
        url, actual_br, size_bytes = client.resolve_audio(track_id, source=args.source, chain=chain)
    except MusicAPIError as exc:
        print("获取下载链接失败：%s" % exc)
        return 1
    label = QUALITY_LABEL.get(actual_br, str(actual_br))
    print("已获取链接：音质 %s (%s)，大小约 %s"
          % (actual_br, label, format_size(size_bytes) if size_bytes else "未知"))

    # 4. 下载音频
    output_dir = args.output or os.path.join(os.path.dirname(os.path.abspath(__file__)), "downloads")
    os.makedirs(output_dir, exist_ok=True)
    ext = guess_extension(url, actual_br)
    stem = sanitize_filename("%s - %s" % (artist, name))
    audio_path = unique_path(output_dir, stem, ext)
    try:
        size = download_file(url, audio_path, expected_size_bytes=size_bytes)
    except Exception as exc:  # noqa: BLE001
        print("下载失败：%s" % exc)
        return 1
    print("音频已保存：%s (%s)" % (audio_path, format_size(size)))

    base_path = os.path.splitext(audio_path)[0]
    if not args.no_lyric:
        save_lyric(client, item, args.source, base_path,
                   want_translation=not args.no_translation)
    if args.cover:
        save_cover(client, item, args.source, base_path)

    print("\n完成！文件位于：%s" % output_dir)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n已中断。")
        sys.exit(130)
