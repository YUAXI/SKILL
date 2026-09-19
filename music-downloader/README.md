# Music Downloader

基于 **GD音乐台 API** 的音乐下载脚本：搜索、下载音频（无损 / 320K / 128K）、歌词（`.lrc` + 翻译）、专辑封面，
并支持**整张歌单批量下载**——网易云歌单走 GD 接口，QQ音乐歌单走 QQ 官方接口（VIP 曲目自动到其它源补齐）。

> 仅供个人学习交流使用，请勿用于商业用途。音乐版权归各音乐平台所有。

## 安装

```bash
pip install -r requirements.txt     # 仅需 requests
# 可选：QQ 歌单的时长校验依赖 ffprobe（ffmpeg 自带）
```

## 快速开始 · 单曲

```bash
# 首次：设置下载目录与音质（会记住，之后不再询问）
python download.py --set-dir "/vol2/1000/music"
python download.py --set-quality 320

# 搜索后交互选择
python download.py "晴天"

# 指定「歌手 歌名」，直接下第 1 条
python download.py "周杰伦 晴天" --first

# 只搜索、输出 JSON
python download.py "海屿你" --search-only --json
```

输出文件：

```
<下载目录>/歌手 - 歌名.flac        音频（无损）或 .mp3
<下载目录>/歌手 - 歌名.lrc         歌词（有翻译时附加 .trans.lrc）
<下载目录>/歌手 - 歌名.jpg         封面（加 --cover）
```

## 快速开始 · 歌单

```bash
python playlist_dl.py <歌单链接或ID> [选项]

# 先看曲目（含时长、VIP 标记），确认无误再下
python playlist_dl.py "https://music.163.com/playlist?id=19723756" --list

# 网易云歌单：试下前 5 首
python playlist_dl.py "19723756" --limit 5

# QQ 音乐歌单：纯数字 ID 必须显式指定平台
python playlist_dl.py "2303919454" --platform qq --list
python playlist_dl.py "2303919454" --platform qq --rate 120/300
```

常用选项：`--list` `--limit N` `--start N` `--sleep S` `--rate max/window` `--overwrite`
`--no-lyric` `--no-fallback` `--no-verify-duration` `--owner user:group`（完整表见 `SKILL.md`）。
已存在的曲目自动跳过，中断后重跑同一命令即可续传。

### 两个平台的差别

| | 网易云歌单 | QQ音乐歌单 |
| :--- | :--- | :--- |
| 曲目表来源 | GD音乐台 `types=playlist`（网易云原始 JSON） | QQ 官方 `fcg_ucc_getcdinfo_byids_cp.fcg`（失败回退 `musicu.fcg`） |
| 音频来源 | GD音乐台 `types=url`，可到 320K / 无损 | QQ 官方 `vkey.GetVkeyServer` 直链 |
| 音质 | 按 `--br`，实测可拿 320K/无损 | **只有 AAC ~96–128k（`.m4a`）**：未登录会员时服务端只给 `C400` |
| VIP / 受限曲目 | 无直链则该曲失败（不换源，避免下到翻唱） | `result=104003/104007` → 到 `--source` 指定源按「歌名+歌手」补齐，**ffprobe 时长核对（±3s）** 通过才保留 |
| 歌词 | 直接取 | QQ 无歌词接口 → 用匹配到的其它源歌词；匹配不到则跳过 |
| 实测样本（132 首） | 100/100 可列，逐首可下 | 直链可用 **71/132**，其余 61 首需补齐 |

## 音乐源支持矩阵（2026-09-19 实测）

| 源 | 可用 | 备注 |
| :--- | :--- | :--- |
| `netease` | ✅ | 默认源，曲库最全，歌词/翻译/封面齐全 |
| `kuwo` | ✅ | 常有原唱版本 |
| `joox` | ✅ | 港台老歌较全 |
| `bilibili` | ⚠️ | 不报错但无结果 |
| `tencent` / `tidal` / `qobuz` / `spotify` / `apple` / `ytmusic` / `migu` / `kugou` / `baidu` | ❌ | 一律 `400 Value of \`source\` is not supported` |

⚠️ **`source=tencent` 不可用，QQ 歌单请走 `--platform qq`。**
⚠️ **数字 ID 会跨平台撞车**：把 QQ 歌单 ID 直接喂给 GD 接口会静默返回网易云上同 ID 的另一张歌单。

## 跨源回退

搜索无结果或下载失败时，脚本按 `netease → kuwo → joox` 切换（`--no-fallback` 可关闭）。
回退时会打印 `[回退] 尝试音乐源：xxx`，最终文件仍按 `歌手 - 歌名` 命名。

## 常见问题

- **下载到 NAS/Samba 目录后别人读不到**：root 创建的文件默认权限受限，脚本默认会
  `chown yuaxi:Users` + `chmod 644`；用 `--owner 用户:组` 改，`--owner -` 关闭。
- **QQ 歌单只有 128k**：未做账号登录，无会员档位；要 320K/无损只能用其它源补齐。
- **歌词偶尔缺失**：上游歌词接口偶发 `503`，脚本已自动退避重试，个别曲目仍可能没有（不影响音频）。
- **错误码**：`104003` = VIP/需购买，`104007` = 受限（服务端按最高请求档位判定）。

## 许可与致谢

接口来自 [GD音乐台](https://music.gdstudio.xyz)；本仓库仅为个人使用的封装脚本。
