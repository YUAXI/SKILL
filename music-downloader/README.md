# music-downloader

Download songs, LRC lyrics and cover art through the GD音乐台 API.

> Full specification (triggers, parameters, workflow, API mapping): [SKILL.md](./SKILL.md).

## Install

1. Place this folder on one of opencode's skill paths:

   ```text
   .opencode/skills/music-downloader/SKILL.md          # project-local
   ~/.config/opencode/skills/music-downloader/SKILL.md # global
   ```

   Or register the folder explicitly in `opencode.json`:

   ```json
   {
     "$schema": "https://opencode.ai/config.json",
     "skills": { "paths": ["./music-downloader"] }
   }
   ```

2. Install the one dependency:

   ```bash
   pip install requests
   ```

3. Restart opencode so the skill is scanned.

## First run — ask the user for folder and quality

**On first use, ask the user (a) which folder to save music into and (b) their
audio quality preference**, then persist both:

```bash
python download.py --set-dir "D:\Music"
python download.py --set-quality 999   # 999 / 740 / 320 / 192 / 128
```

Both answers are stored in `.music-downloader.json` and reused automatically, so
they are only asked once. If run interactively without these flags, the script
prompts for folder and quality itself. Never pick values for the user without
asking. Non-interactive runs fall back to defaults (`./downloads/`, `999`)
instead of blocking.

## Usage

```bash
# search only, let the user pick a row
python download.py "练习" --search-only

# download the row the user chose
python download.py "练习" --select 2

# artist + title, take the first match
python download.py "周杰伦 晴天" --first

# only search, machine-readable
python download.py "海屿你" --search-only --json

# set folder + quality once, then download with cover, no lyrics
python download.py --set-dir "D:\Music"
python download.py --set-quality 320
python download.py "稻香" --cover --no-lyric
```

Output is `歌手 - 歌名.flac` / `.mp3` (plus `.lrc` and optional `.jpg`) inside the
chosen folder.

## Cross-source fallback

If a source cannot find the track or the download fails, the script automatically
tries the next source in this fixed order:

```text
netease → tencent → kuwo → tidal → qobuz → joox → bilibili → apple → ytmusic → spotify
```

- Search phase: empty results or an error moves to the next source.
- Download phase: link/transfer failure re-searches the same keyword on the next source.
- Disable with `--no-fallback` to use only `--source`.
- Fallbacks print `[回退] 尝试音乐源：xxx`.

Quality is preferred at `999` (lossless), degrading `740 -> 320 -> 192 -> 128`.
Requests are rate-limited to 50 per 5 minutes.

## Notes for the agent

- Always ask for the folder **and** quality on first use (`--set-dir`,
  `--set-quality`), then reuse them.
- Prefer `--search-only` first when the query is ambiguous, present the numbered
  list, and pass the user's choice through `--select`.
- Rely on the automatic cross-source fallback; only add `--no-fallback` if the
  user explicitly wants a single source.
- Use `--output` / `--br` only for a one-off override; they also remember the value.
- `.music-downloader.json`, `downloads/` and `__pycache__/` are gitignored.
- Personal/study use only; do not use commercially.
