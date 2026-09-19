# Music Downloader

Download songs, lyrics and cover art through the GD音乐台 API.

See [SKILL.md](./SKILL.md) for the full specification (description, triggers,
parameters, outputs and workflow).

## Quick start

```bash
pip install -r requirements.txt
python download.py "练习" --first
```

Files are written to `./downloads/` as `歌手 - 歌名.flac` / `.mp3`, with an
optional `.lrc` lyrics file and `.jpg` cover.
