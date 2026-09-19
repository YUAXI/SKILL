# SKILL

A collection of Agent Skills (opencode / Claude-compatible `SKILL.md` folders).
Each skill is self-contained: it has a `SKILL.md` spec, an executable script, and
its own `README.md` with install and usage instructions.

## Repository layout

```text
SKILL/
└── music-downloader/
    ├── SKILL.md          # skill spec: description, triggers, inputs/outputs
    ├── README.md         # install + usage for agents
    ├── download.py       # executable implementation
    └── requirements.txt
```

## Install a skill (agent instructions)

To install a skill from this repo into opencode:

1. **Get the skill folder.** Either `git clone https://github.com/YUAXI/SKILL.git`
   and copy the skill folder, or copy just that folder into place.
2. **Put it on a skill path.** opencode scans `**/SKILL.md` inside these dirs:

   ```text
   .opencode/skills/<skill-name>/SKILL.md            # project-local
   ~/.config/opencode/skills/<skill-name>/SKILL.md   # global
   ```

   Or register an arbitrary path in `opencode.json` (no move needed):

   ```json
   {
     "$schema": "https://opencode.ai/config.json",
     "skills": { "paths": ["./SKILL/music-downloader"] }
   }
   ```

3. **Install dependencies** listed in the skill's `requirements.txt`
   (e.g. `pip install requests`).
4. **Restart opencode** — skills are loaded at startup and not hot-reloaded.
5. **Read the skill's `README.md` and `SKILL.md`** before first use; follow any
   first-run steps (e.g. asking the user for a download folder).

## Skills in this repo

### music-downloader

Search and download music, LRC lyrics and cover art via the GD音乐台 API.

- **Triggers**: "下载歌曲", "帮我下这首歌", "搜索并下载音乐", "找歌", "下载歌词",
  "music download", "GD音乐台".
- **Runtime**: Python 3.8+, only dependency is `requests`.
- **Install**: copy `music-downloader/` to a skill path, `pip install requests`,
  restart opencode.
- **First run**: ask the user where to save music, then
  `python download.py --set-dir "<folder>"` (remembered afterwards).
- **Typical call**: `python download.py "<keyword>" --search-only` to list
  results, then `python download.py "<keyword>" --select <n>` to download.
- **Output**: `歌手 - 歌名.flac` / `.mp3`, plus `.lrc` (and optional `.jpg`) in the
  chosen folder. Prefers lossless (`999`), degrades `740 -> 320 -> 192 -> 128`;
  rate-limited to 50 requests / 5 min.
- **Docs**: [music-downloader/README.md](./music-downloader/README.md),
  [music-downloader/SKILL.md](./music-downloader/SKILL.md).

## Adding a new skill

Create `SKILL/<name>/` containing at minimum a `SKILL.md` with frontmatter
(`name`, `description`), plus a `README.md`, the executable code, and a
`requirements.txt` if it has dependencies. Then add an entry under
"Skills in this repo" above.
