# RAIT Toolkit

MCP server + Claude plugin for D.Y. Patil RAIT students. Connects Claude Desktop and Claude Code to your MyDy LMS and UniClaIRE portal — courses, attendance, GPA, hit-rate maxxer, experiment cover PDFs, evaluation sheets, and lab writeup generation.

---

## Quick setup

### Prerequisites

**macOS**
```sh
# uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# LaTeX (for PDF rendering)
brew install --cask mactex-no-gui
```

**Ubuntu / Debian**
```sh
# uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# LaTeX (for PDF rendering)
sudo apt update && sudo apt install -y texlive-latex-base texlive-fonts-recommended texlive-latex-extra
```

---

### Clone the repo

```sh
git clone https://github.com/kry0sc0pic/rait-toolkit
cd rait-toolkit
```

---

### Claude Desktop

**macOS** — edit `~/Library/Application Support/Claude/claude_desktop_config.json`

**Ubuntu** — edit `~/.config/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "lms-buddy": {
      "command": "uvx",
      "args": ["--from", "/path/to/rait-toolkit", "lms-buddy"],
      "env": {
        "MYDY_EMAIL": "your@dypatil.edu",
        "MYDY_PASSWORD": "***REMOVED***"
      }
    }
  }
}
```

Replace `/path/to/rait-toolkit` with your local clone path. Restart Claude Desktop.

> Credentials can also be omitted from the config and set interactively — Claude will use `AskFollowupQuestion` to prompt you and save them to `~/.lms-buddy/credentials.json`.

---

### Claude Code (CLI)

```sh
/plugin install .
```

Run from inside the cloned repo. Then set credentials in Claude Code settings:
- **macOS**: Cmd+, → Environment
- **Ubuntu**: `claude config` or edit `~/.claude/settings.json`
```json
{
  "MYDY_EMAIL": "your@dypatil.edu",
  "MYDY_PASSWORD": "***REMOVED***"
}
```

Or let Claude prompt you on first use.

---

### Other MCP clients (Cursor, Codex CLI, etc.)

The server runs over stdio via `uvx`. Point your client to:

```json
{
  "command": "uvx",
  "args": ["--from", "/path/to/rait-toolkit", "lms-buddy"],
  "env": {
    "MYDY_EMAIL": "your@dypatil.edu",
    "MYDY_PASSWORD": "***REMOVED***"
  }
}
```

---

## Tools (18 total)

### LMS — MyDy

| Tool | What it does |
|------|-------------|
| `list_subjects` | Current semester courses with attendance %; `include_all=true` for all semesters |
| `list_files` | Downloadable materials in a course |
| `download_file` | Download a file to disk (defaults to `~/Downloads`) |
| `get_hitrates` | Course Progress % for all current courses |
| `max_hitrate` | Visit every pending activity for a course to push it to 100% |
| `get_overall_attendance` | Aggregate attendance + per-subject breakdown with per-class drill-down IDs |
| `get_course_attendance` | Per-class attendance records for a subject (date, time, present/absent) |
| `get_semesters` | Courses grouped by semester label (Semester V, Semester VI, …) |

### GPA — UniClaIRE portal

| Tool | What it does |
|------|-------------|
| `get_gpa` | CGPA + per-semester SGPA + course-level grade breakdown; auto-saves your USN |

### PDF rendering (requires LaTeX)

| Tool | What it does |
|------|-------------|
| `render_cover_pdf` | Render a single experiment cover page to PDF |
| `batch_render_covers_pdf` | Render multiple covers into one multi-page PDF |
| `render_eval_sheet_pdf` | Render a single practical evaluation sheet to PDF |
| `batch_render_eval_sheets_pdf` | Render multiple evaluation sheets into one multi-page PDF |

All PDF tools open the file in your system viewer automatically after rendering.

### Utility

| Tool | What it does |
|------|-------------|
| `get_cached_info` | Show stored email, regno, USN, and which credentials are configured — call at session start |
| `set_mydy_credentials` | Save MyDy email + password to `~/.lms-buddy/credentials.json` |
| `set_portal_credentials` | Save UniClaIRE regno + password (regno = mobile login number, not roll number) |
| `open_pdf` | Open any PDF in the system viewer |
| `self_update` | `git pull` and restart the server process to pick up updates |

---

## Prompts (Claude Desktop prompt picker)

| Prompt | What it does |
|--------|-------------|
| `journal_writeup` | System instructions for writing a formal experiment journal entry — fill in expnum + title, Claude guides the rest |

---

## Credential storage

Credentials are saved to `~/.lms-buddy/credentials.json` on your local machine. They are never sent anywhere except directly to their respective portals (`mydy.dypatil.edu` and `studentportal.universitysolutions.in`).

**Two separate auth domains:**
- **MyDy** — email + password (used by all LMS tools)
- **UniClaIRE portal** — registration/mobile number + password (used by `get_gpa`)

Note: your UniClaIRE login uses your **mobile/registration number**, not your university roll number (USN). The USN (e.g. `23MTCO001`) is fetched automatically when you first call `get_gpa`.

Env vars always take precedence over saved credentials:

| Variable | Purpose |
|----------|---------|
| `MYDY_EMAIL` | MyDy login email |
| `MYDY_PASSWORD` | MyDy password |
| `MYDY_AUTH_MODE` | `scrape` (default) or `token` — token mode extracts MoodleSession + security keys |
| `PORTAL_REGNO` | UniClaIRE registration/mobile number |
| `PORTAL_PASSWORD` | UniClaIRE password |

---

## Response tracking

Every live-data tool saves its last response to `~/.lms-buddy/snapshots/`. On subsequent calls, the response is prefixed with a unified diff showing exactly what changed since the last read — or `[No changes since last read]` if nothing did.

---

## Web app + Vercel deployment

The `api/` and `web/` directories contain a Vercel-hosted React frontend + serverless API (the original remote MCP at `lms-buddy.krishaay.dev`). This is independent of the local MCP package.

```sh
npm install
npx vercel dev   # local full-stack dev
vercel           # deploy
```

---

## Project structure

```
rait-toolkit/
├── lms_buddy/               # uvx-installable MCP package
│   ├── __main__.py          #   FastMCP server — 18 tools + 1 prompt
│   ├── client.py            #   MyDy LMS HTTP client
│   ├── gpa.py               #   UniClaIRE portal GPA fetcher
│   ├── render.py            #   LaTeX PDF rendering
│   ├── tools.py             #   Cached business logic (list_subjects, hitrates, etc.)
│   └── templates/           #   LaTeX templates (cover, general cover, eval sheet)
├── plugin/                  # Claude Code plugin
│   ├── .claude-plugin/
│   │   └── plugin.json      #   MCP server declaration + metadata
│   └── skills/
│       └── lab-writeup/
│           └── SKILL.md     #   /lab-writeup slash command
├── .claude-plugin/
│   └── marketplace.json     #   Marketplace wrapper
├── api/                     # Vercel serverless API (remote MCP + web backend)
├── web/                     # React frontend
├── references/
│   └── preamble-simple.tex  #   LaTeX preamble for lab writeups
├── client.py                # Root client (used by api/ and local_server.py)
├── local_server.py          # Run the full stack locally without vercel dev
├── pyproject.toml           # Python package config (hatchling)
├── requirements.txt         # Vercel-only deps
└── vercel.json
```

---

## Requirements

- Python 3.10+
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- Valid MyDy LMS account (D.Y. Patil RAIT)
- macOS or Ubuntu/Debian (Windows untested)

## License

MIT. Use at your own risk. This project is unofficial and not affiliated with D.Y. Patil or MyDy.
