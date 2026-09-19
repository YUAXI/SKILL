---
name: music-downloader
description: 使用 GD音乐台 API 搜索并下载音乐、歌词与专辑封面。Use when the user wants to find and download a song, search music by 歌名/歌手/关键字, or fetch LRC lyrics from 网易云(netease)/QQ音乐/酷我/joox/bilibili 等音乐源. Triggers include "下载歌曲", "帮我下这首歌", "搜索并下载音乐", "找歌", "下载歌词", "music download", "GD音乐台".
---

# Music Downloader（GD音乐台）

通过 GD音乐台 API 完成「搜索 → 选择 → 获取直链 → 下载音频/歌词/封面」的完整流程。

- **接口 Base URL**：`https://music-api.gdstudio.xyz/api.php`
- **请求方式**：全部为 `GET`
- **频率限制**：5 分钟内最多 50 次请求（脚本内置滑动窗口限流，自动等待）
- **默认音乐源**：`netease`；稳定源还有 `joox`、`bilibili`

> 免责声明：本 Skill 仅供个人学习交流使用，请勿用于商业用途。音乐版权归各音乐平台所有。

## 触发条件（Triggers）

当用户出现以下意图时使用本 Skill：

- 想下载某首歌 / 某个歌手的歌曲，或给出「歌名 + 歌手」要求下载
- 想搜索歌曲、查看搜索结果列表后再下载
- 想获取歌词（`.lrc`）或专辑封面
- 明确提到「GD音乐台」「音乐下载」「下载音乐」等关键词

## 前置依赖

```bash
pip install -r requirements.txt   # 仅需 requests
```

脚本路径：`music-downloader/download.py`（Python 3.8+）。

## 入参（Inputs）

| 参数 | 类型 | 必填 | 默认 | 说明 |
| :--- | :--- | :--- | :--- | :--- |
| `keyword` | String | 是 | - | 搜索关键字：歌曲名 / 歌手 / 专辑 |
| `--source` | String | 否 | `netease` | 音乐源：`netease`、`joox`、`bilibili`、`tencent`、`kuwo`、`tidal`、`qobuz`、`apple`、`ytmusic`、`spotify` |
| `--select` | Int | 否 | - | 直接选择第 N 条搜索结果（1 开始），用于非交互场景 |
| `--first` | Flag | 否 | - | 多条结果时自动选第 1 条，不交互 |
| `--count` | Int | 否 | `20` | 单页返回条数 |
| `--pages` | Int | 否 | `1` | 页码 |
| `--br` | Int | 否 | `999` | 首选音质，失败自动降级 `740 -> 320 -> 192 -> 128` |
| `--output` | String | 否 | `./downloads/` | 下载目录 |
| `--search-only` | Flag | 否 | - | 仅搜索并展示结果，不下载 |
| `--json` | Flag | 否 | - | 配合 `--search-only`，以 JSON 输出结果 |
| `--no-lyric` | Flag | 否 | - | 不下载歌词（默认会下载 `.lrc`） |
| `--no-translation` | Flag | 否 | - | 不保存翻译歌词（`.trans.lrc`） |
| `--cover` | Flag | 否 | - | 同时下载 500px 专辑封面 |

## 出参（Outputs）

- 音频文件：`./downloads/歌手 - 歌名.flac`（无损）或 `歌手 - 歌名.mp3`
- 歌词文件（默认）：`./downloads/歌手 - 歌名.lrc`，有翻译时附加 `.trans.lrc`
- 封面文件（可选）：`./downloads/歌手 - 歌名.jpg`
- 控制台：搜索结果列表、实际音质、下载进度与最终文件路径
- `--search-only --json`：标准 JSON 数组，字段为接口原始返回（`id/name/artist/album/pic_id/lyric_id/source`）

## 标准工作流

**第 1 步 · 搜索**（当用户未指定具体某一条时，先列出结果让用户选择）：

```bash
python music-downloader/download.py "<关键字>" --source netease --search-only
```

向用户展示序号、歌名、歌手、专辑，并询问「要下载第几首（默认第 1 首）」。

**第 2 步 · 下载**（把用户选择的序号传给 `--select`）：

```bash
python music-downloader/download.py "<关键字>" --source netease --select 2
```

如果用户已给出足够精确的信息、或明确说「下载第一首」，可直接：

```bash
python music-downloader/download.py "<关键字>" --first
```

## 常用命令示例

```bash
# 交互式搜索并选择下载
python download.py "练习"

# 指定歌手 + 歌名，直接下第 1 条
python download.py "周杰伦 晴天" --first

# 使用 joox 源、不下载歌词
python download.py "Hello Adele" --source joox --no-lyric

# 仅搜索并输出 JSON（供程序解析）
python download.py "海屿你" --search-only --json

# 下载到指定目录并保存封面
python download.py "稻香" --output D:\Music --cover
```

## 接口映射（API 速查）

| 功能 | 请求参数 | 关键返回 |
| :--- | :--- | :--- |
| 搜索 | `types=search&source=..&name=..&count=..&pages=..` | `[{id, name, artist[], album, pic_id, lyric_id, source}]` |
| 获取音频 | `types=url&source=..&id=<track_id>&br=<128/192/320/740/999>` | `{url, br, size(KB)}` |
| 获取歌词 | `types=lyric&source=..&id=<lyric_id>` | `{lyric, tlyric}` |
| 获取封面 | `types=pic&source=..&id=<pic_id>&size=<300/500>` | `{url}` |

- `br=999` 为 24bit 无损，`br=740` 为 16bit 无损，`br` 缺省为 `999`。
- 下载直链使用曲目 `id`（track_id）；歌词用 `lyric_id`，封面用 `pic_id`（通常与 track_id 相同）。
- 返回中的 `br` 是**实际**返回音质，可能与请求值不同，脚本会如实展示。

## 错误处理与限制

- **限流**：脚本用滑动窗口追踪请求时间戳，5 分钟满 50 次会自动休眠至窗口释放。
- **重试**：网络错误 / 5xx 默认重试 3 次，指数退避；`429` 单独识别。
- **音质降级**：从 `--br` 指定值开始，依次尝试 `740 → 320 → 192 → 128`，返回空 `url` 视为无该音质。
- **文件名**：自动过滤 `\ / : * ? " < > |` 等非法字符，重名时追加 `(1)`、`(2)` 序号。
- 若搜索无结果，可提示用户更换关键字或切换音乐源（推荐 `netease`、`joox`、`bilibili`）。

## 安装为 opencode Skill（可选）

本目录若不在默认扫描路径下，可在 `opencode.json` 中注册：

```json
{
  "$schema": "https://opencode.ai/config.json",
  "skills": { "paths": ["./music-downloader"] }
}
```

或把 `music-downloader/` 移动到 `.opencode/skills/` 或 `~/.config/opencode/skills/` 下，重启 opencode 后生效。
