---
name: music-downloader
description: 使用 GD音乐台 API 搜索并下载音乐、歌词与专辑封面，并支持整张歌单批量下载（网易云歌单 + QQ音乐歌单）。Use when the user wants to find and download a song, search music by 歌名/歌手/关键字, fetch LRC lyrics from 网易云(netease)/酷我/joox, or download a whole playlist/歌单 (music.163.com、y.qq.com). Triggers include "下载歌曲", "帮我下这首歌", "搜索并下载音乐", "找歌", "下载歌词", "下载整个歌单", "下载这个歌单", "QQ音乐歌单", "music download", "GD音乐台".
---

# Music Downloader（GD音乐台 + 歌单批量下载）

通过 GD音乐台 API 完成「搜索 → 选择 → 获取直链 → 下载音频/歌词/封面」的完整流程；
另有 `playlist_dl.py` 支持**整张歌单批量下载**（网易云歌单 / QQ音乐歌单两条链路）。

- **接口 Base URL**：`https://music-api.gdstudio.xyz/api.php`
- **请求方式**：全部为 `GET`
- **频率限制**：5 分钟内最多 50 次请求（脚本内置滑动窗口限流，自动等待）
- **默认音乐源**：`netease`
- **可用音乐源**：仅 `netease` / `kuwo` / `joox`（见下方「音乐源支持矩阵」）
- **音质**：默认 `999`（24bit 无损），失败自动降级 `740 → 320 → 192 → 128`

> 免责声明：本 Skill 仅供个人学习交流使用，请勿用于商业用途。音乐版权归各音乐平台所有。

## 触发条件（Triggers）

当用户出现以下意图时使用本 Skill：

- 想下载某首歌 / 某个歌手的歌曲，或给出「歌名 + 歌手」要求下载
- 想搜索歌曲、查看搜索结果列表后再下载
- 想获取歌词（`.lrc`）或专辑封面
- **想下载整张歌单**（给出 `music.163.com/playlist?id=...` 或 `y.qq.com` 歌单链接/ID）
- 明确提到「GD音乐台」「音乐下载」「下载音乐」「歌单」等关键词

## 前置依赖

```bash
pip install -r requirements.txt   # 仅需 requests；ffprobe 用于 QQ 歌单的时长校验
```

脚本路径：
- `music-downloader/download.py`（单曲，Python 3.8+）
- `music-downloader/playlist_dl.py`（歌单批量，复用 download.py 的函数）

---

## 音乐源支持矩阵（2026-09-19 实测）

| 源 | GD音乐台 API | 说明 |
| :--- | :--- | :--- |
| `netease` | ✅ 可用 | 默认源，曲库最全，歌词/翻译/封面齐全 |
| `kuwo` | ✅ 可用 | 常有独家/原唱版本 |
| `joox` | ✅ 可用 | 华语/港台老歌较全 |
| `bilibili` | ⚠️ 返回空 | 不报错但无结果 |
| `tencent` | ❌ 400 | `Value of \`source\` is not supported` |
| `tidal` / `qobuz` / `spotify` / `apple` / `ytmusic` / `migu` / `kugou` / `baidu` | ❌ 400 | 同上 |

**因此：跨源回退只在前三个源之间进行**（`netease → kuwo → joox`）。

> ⚠️ **QQ音乐歌单 ≠ 可用 `source=tencent`**。`source=tencent` 不被 API 支持，
> QQ 歌单必须走 `playlist_dl.py --platform qq` 的官方接口链路（见下）。
>
> ⚠️ **数字 ID 会跨平台撞车**：`types=playlist` 不指定 `source` 时默认查网易云，
> 把 QQ 歌单的纯数字 ID 丢进去会**静默返回网易云上一张同 ID 的歌单**（完全不同的一张）。
> 纯数字 ID 请务必显式指定平台（`--platform qq`）。

---

## A. 单曲下载（download.py）

### 入参（Inputs）

| 参数 | 类型 | 必填 | 默认 | 说明 |
| :--- | :--- | :--- | :--- | :--- |
| `keyword` | String | 是 | - | 搜索关键字：歌曲名 / 歌手 / 专辑 |
| `--source` | String | 否 | `netease` | 首选音乐源；搜索/下载失败时按回退顺序自动尝试其它源 |
| `--select` | Int | 否 | - | 直接选择第 N 条搜索结果（1 开始），用于非交互场景 |
| `--first` | Flag | 否 | - | 多条结果时自动选第 1 条，不交互 |
| `--count` | Int | 否 | `20` | 单页返回条数 |
| `--pages` | Int | 否 | `1` | 页码 |
| `--br` | Int | 否 | 配置值/`999` | 首选音质，失败自动降级 `740 -> 320 -> 192 -> 128`；显式传入会记住 |
| `--output` | String | 否 | 首次询问 | 下载目录；指定后会保存为默认位置 |
| `--set-dir` | String | 否 | - | 仅设置并保存默认下载目录后退出 |
| `--set-quality` | Int | 否 | - | 仅设置并保存默认音质（`999/740/320/192/128`）后退出 |
| `--no-fallback` | Flag | 否 | - | 关闭跨源回退，只用 `--source` 指定的源 |
| `--search-only` | Flag | 否 | - | 仅搜索并展示结果，不下载 |
| `--json` | Flag | 否 | - | 配合 `--search-only`，以 JSON 输出结果 |
| `--no-lyric` | Flag | 否 | - | 不下载歌词（默认会下载 `.lrc`） |
| `--no-translation` | Flag | 否 | - | 不保存翻译歌词（`.trans.lrc`） |
| `--cover` | Flag | 否 | - | 同时下载 500px 专辑封面 |

### 出参（Outputs）

- 音频文件：`<下载目录>/歌手 - 歌名.flac`（无损）或 `歌手 - 歌名.mp3`
- 歌词文件（默认）：`<下载目录>/歌手 - 歌名.lrc`，有翻译时附加 `.trans.lrc`
- 封面文件（可选）：`<下载目录>/歌手 - 歌名.jpg`
- 控制台：搜索结果列表、实际音质、下载进度与最终文件路径

### 首次使用：询问下载位置与音质

**第一次使用本 Skill 时，必须先询问用户「音乐保存到哪里」和「音质偏好」**，不要自行替用户决定。

- 首次（本地无配置且未显式传参）会依次交互式询问下载目录与音质偏好，答案记入
  `music-downloader/.music-downloader.json`，之后不再询问。
- Agent 代跑且不希望交互时，先问用户，再用 `--set-dir`、`--set-quality` 写入，或单次用 `--output` / `--br`。
- 非交互环境（管道 / 无 stdin）不会阻塞，自动使用默认目录与默认音质。
- 配置文件 `.music-downloader.json` 属于本机个人设置，不要提交。

### 标准工作流（单曲）

**第 1 步 · 搜索**（用户未指定具体某一条时，先列出结果让用户选择）：

```bash
python download.py "<关键字>" --source netease --search-only
```

**第 2 步 · 下载**（把用户选择的序号传给 `--select`）：

```bash
python download.py "<关键字>" --source netease --select 2
```

用户已给出精确信息、或明确说「下载第一首」时可直接 `--first`。

---

## B. 歌单批量下载（playlist_dl.py）

### 用法

```bash
python playlist_dl.py <歌单链接或ID> [选项]
```

| 参数 | 默认 | 说明 |
| :--- | :--- | :--- |
| `playlist` | - | 歌单链接或 ID（`music.163.com/playlist?id=`、`163cn.tv` 短链、`y.qq.com` / `i2.y.qq.com` 歌单链接） |
| `--platform` | `auto` | `auto` / `netease` / `qq`。auto 按域名判断；**纯数字 ID 默认 netease**，QQ 歌单必须显式 `--platform qq` |
| `--source` | `netease` | QQ 歌单 VIP 缺口的补齐源，见源支持矩阵 |
| `--list` | - | 只列曲目（含时长、VIP 标记），不下载。**建议先跑这个给用户确认** |
| `--limit` / `--start` | - / `1` | 只处理前 N 首 / 从第 N 首开始（可断点续传） |
| `--br` / `--output` | 配置值 | 音质 / 输出目录，同单曲脚本 |
| `--sleep` | `0.5` | 每首间隔秒数 |
| `--rate` | `50/300` | GD 限流 `max/window`，如 `--rate 120/300` |
| `--overwrite` | - | 已存在也重新下载（默认跳过，天然支持续传） |
| `--cover` | - | 下载封面（netease 歌单有效） |
| `--no-lyric` / `--no-translation` | - | 不下载歌词 / 翻译 |
| `--no-fallback` | - | QQ 歌单：VIP/受限曲目**不补齐**，只下能直连的 |
| `--no-verify-duration` | - | QQ 补齐时跳过时长校验（默认校验，防止下成翻唱） |
| `--owner` | `yuaxi:Users` | 下载后 `chown`+`chmod 644` 修正属主；`-` 表示不改 |

### 链路 1 · 网易云歌单

`types=playlist&source=netease&id=<id>` 直接返回网易云歌单原始 JSON
（`playlist.name / trackCount / tracks[].id, name, ar[], al.picId, dt`），
再逐首走单曲脚本的「获取直链 → 下载 → 歌词/封面」。

- 接口对超长歌单可能只返回前若干首（脚本会提示「本次拿到 X/Y 首」）。
- 歌单内曲目 ID 固定为网易云 ID，**不做跨源重搜**（避免下到同名翻唱）；
  某首无直链就只能在网易云内降音质，仍拿不到则列进失败清单。

### 链路 2 · QQ音乐歌单

QQ 没有可直接消费的 `source`，走**官方接口三段式**：

1. **曲目表**：`GET https://c.y.qq.com/qzone/fcg-bin/fcg_ucc_getcdinfo_byids_cp.fcg?type=1&json=1&utf8=1&onlysong=0&new_format=1&disstid=<id>&format=json`
   （需 `Referer: https://y.qq.com/`；失败自动回退 `musicu.fcg` 的 `music.srfDissInfo.DissInfo/CgiGetDiss`）
   → `cdlist[0].songlist[]`，每首含 `mid / name / singer[].name / album / interval / pay`
2. **直链**：`POST https://u.y.qq.com/cgi-bin/musicu.fcg`，模块 `vkey.GetVkeyServer/CgiGetVkey`
   （`songmid[]` 分批 50，`filename: ["C400"]`）→ `midurlinfo[].purl` + `sip[0]` 拼成
   `sip[0] + purl` 播放地址（下载需带 `Referer`）
3. **VIP 缺口补齐**：`purl` 为空（`result=104003/104007`）时，按「歌手 + 歌名」在
   `--source` 指定的源搜索，候选需**歌名相同或互相包含 + 歌手有交集**，
   下载后 **ffprobe 时长与 QQ 侧 `interval` 比对（±3 秒）**，一致才保留，否则删除并计入失败。

**QQ 链路的硬限制（务必如实告知用户）**：

- 未登录会员时服务端只给 `C400`（**AAC ~96–128k**，`.m4a`），**拿不到 320K/FLAC**。
  本脚本不做 QQ 账号登录，因此这个上限无法绕过。
- 实测一张 132 首的私人歌单：**直链可用 71 首**，其余 61 首为 VIP/受限（104003 / 104007）。
- ⚠️ **不要一次请求多个音质档**：`filename: ["F000","M800","C400"]` 会让服务端按
  「需要会员」的那一档回复，把本可直连的曲目判成 `104007`（实测可用数 71 → 66）。
  只请求 `C400`。
- QQ 无歌词接口：直链下来的曲目用「歌名+歌手」匹配 netease 源取其歌词，
  匹配不到就跳过歌词（不阻塞下载）。
- 单次 vkey 请求超过 50 个 `mid` 会被截断，脚本按 50 分批。

### 歌单下载标准工作流

```bash
# 1. 先列出曲目给用户确认（含时长 / VIP 标记）
python playlist_dl.py "<歌单链接>" --list

# 2. 确认后开跑（先小批量试）
python playlist_dl.py "<歌单链接>" --limit 10

# 3. 全量（大歌单建议放宽限流并加长间隔）
python playlist_dl.py "<歌单链接>" --rate 120/300 --sleep 0.5
```

> 132 首量级大约 10–20 分钟（含补齐搜索）。中断后重跑同一命令即可续传（已存在自动跳过）。

---

## 常用命令示例

```bash
# 首次设置下载位置与音质（只需一次，之后自动记住）
python download.py --set-dir "/vol2/1000/music"
python download.py --set-quality 320

# 指定歌手 + 歌名，直接下第 1 条
python download.py "周杰伦 晴天" --first

# 使用 joox 源、不下载歌词
python download.py "Hello Adele" --source joox --no-lyric

# 仅搜索并输出 JSON（供程序解析）
python download.py "海屿你" --search-only --json

# 歌单：列曲目 / 试下 5 首 / 全量
python playlist_dl.py "https://music.163.com/playlist?id=19723756" --list
python playlist_dl.py "19723756" --limit 5
python playlist_dl.py "2303919454" --platform qq --rate 120/300
```

## 接口映射（API 速查）

| 功能 | 请求参数 | 关键返回 |
| :--- | :--- | :--- |
| 搜索 | `types=search&source=..&name=..&count=..&pages=..` | `[{id, name, artist[], album, pic_id, lyric_id, source}]` |
| 获取音频 | `types=url&source=..&id=<track_id>&br=<128/192/320/740/999>` | `{url, br, size}` |
| 获取歌词 | `types=lyric&source=..&id=<lyric_id>` | `{lyric, tlyric}` |
| 获取封面 | `types=pic&source=..&id=<pic_id>&size=<300/500>` | `{url}` |
| **获取歌单** | `types=playlist&source=netease&id=<playlist_id>` | 网易云歌单原始 JSON（`playlist.tracks[]`） |

- `br=999` 为 24bit 无损，`br=740` 为 16bit 无损，`br` 缺省为 `999`。
- 下载直链使用曲目 `id`（track_id）；歌词用 `lyric_id`，封面用 `pic_id`（通常与 track_id 相同）。
- 返回中的 `br` 是**实际**返回音质，可能与请求值不同，脚本会如实展示。
- `size` 文档标注为 KB，但**实测其值等于文件字节数**（与 `Content-Length` 一致）。
- `types=playlist` **只吃网易云歌单 ID**；QQ 歌单走上面的官方接口。
- QQ 侧接口：歌单 `c.y.qq.com/qzone/fcg-bin/fcg_ucc_getcdinfo_byids_cp.fcg`、
  直链 `u.y.qq.com/cgi-bin/musicu.fcg`（`vkey.GetVkeyServer/CgiGetVkey`）。

## 错误处理与限制

- **限流**：脚本用滑动窗口追踪请求时间戳，5 分钟满 50 次会自动休眠至窗口释放
  （实测连发 12 次无 429，平均约 2.4 秒/请求）。
- **重试**：网络错误 / 5xx 默认重试 3 次，指数退避；`429` 单独识别。
  歌词接口偶发 `503`，脚本自动退避重试，个别曲目歌词仍可能缺失（不影响音频）。
- **音质降级**：从首选音质开始，依次尝试 `740 → 320 → 192 → 128`，返回空 `url` 视为无该音质。
- **跨源回退**：搜索无结果或下载失败时按 `netease → kuwo → joox` 切换（可用 `--no-fallback` 关闭）。
- **文件名**：自动过滤 `\ / : * ? " < > |` 等非法字符，重名时追加 `(1)`、`(2)` 序号。
- **下载后权限**：下载到 NAS/Samba 共享目录时，root 创建的文件默认其他用户读不到，
  脚本默认 `chown yuaxi:Users` + `chmod 644`（用 `--owner` 改，`--owner -` 关闭）。
- 若所有源都失败，提示用户更换关键字；`netease` 通常最稳。

## 与上游仓库的差异（本地维护记录）

| 文件 | 状态 |
| :--- | :--- |
| `download.py` | 上游文件，**仅一处改动**：`SOURCE_ORDER` 从 10 个源改为实测可用的 `netease/kuwo/joox/bilibili` |
| `playlist_dl.py` | **本地新增**：歌单批量下载（网易云 + QQ音乐两条链路） |
| `SKILL.md` | 补歌单章节、源支持矩阵、QQ 链路实测限制；修正上游凭推测写的回退顺序 |
| `README.md` | 同步歌单用法 |
| `NOTES.local.md` | 本机环境备注（路径/属主/本机实测坑），**不随仓库分发** |

## 安装为 opencode Skill（可选）

本目录若不在默认扫描路径下，可在 `opencode.json` 中注册：

```json
{
  "$schema": "https://opencode.ai/config.json",
  "skills": { "paths": ["./music-downloader"] }
}
```

或把 `music-downloader/` 移动到 `.opencode/skills/` 或 `~/.config/opencode/skills/` 下，重启 opencode 后生效。
