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

## First run — ask the user where music should go

**On first use, ask the user which folder to save music into**, then persist it:

```bash
python download.py --set-dir "D:\Music"
```

The answer is stored in `.music-downloader.json` and reused automatically, so it
is only asked once. If the user wants the default, skip this (music goes to
`./downloads/`). Never pick a folder for the user without asking.

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

# set the folder once, download with cover, no lyrics
python download.py --set-dir "D:\Music"
python download.py "稻香" --source joox --cover --no-lyric
```

Output is `歌手 - 歌名.flac` / `.mp3` (plus `.lrc` and optional `.jpg`) inside the
chosen folder. Lossless is preferred (`999`), degrading to `740 -> 320 -> 192 -> 128`.
Requests are rate-limited to 50 per 5 minutes.

## Notes for the agent

- Always ask for the download folder on first use (`--set-dir`), then reuse it.
- Prefer `--search-only` first when the query is ambiguous, present the numbered
  list, and pass the user's choice through `--select`.
- Use `--output` only when the user names a folder for a single run; it also
  remembers that folder.
- `.music-downloader.json`, `downloads/` and `__pycache__/` are gitignored.
- Personal/study use only; do not use commercially.
