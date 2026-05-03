# LMS Buddy

A clean web app, terminal UI, and MCP server for interacting with the MyDy (Moodle-based) LMS at D.Y. Patil institutions. View attendance, browse courses, check assignments and grades, read announcements, and download course materials.

## Screenshots
<img width="2446" height="1466" alt="MyDy_LMS_Helper_2026-03-21T02_48_44_883104" src="https://github.com/user-attachments/assets/698580e6-2893-40e2-b863-b1b06dd753a7" />
<img width="2446" height="1466" alt="MyDy_LMS_Helper_2026-03-21T02_50_00_030190" src="https://github.com/user-attachments/assets/5295fe80-7b84-43fa-9a4e-83f5d6cdd9b0" />
<img width="2446" height="1466" alt="MyDy_LMS_Helper_2026-03-21T02_50_03_617570" src="https://github.com/user-attachments/assets/df05d709-cff0-47be-90a7-85b439940325" />
<img width="2446" height="1466" alt="MyDy_LMS_Helper_2026-03-21T02_50_07_599421" src="https://github.com/user-attachments/assets/da366e58-5dcc-4b10-a3ca-e7a80ee1c4de" />
<img width="2446" height="1466" alt="MyDy_LMS_Helper_2026-03-21T02_50_21_603458" src="https://github.com/user-attachments/assets/9a474387-ff04-4b87-b787-d2f5545652fe" />
<img width="2446" height="1466" alt="MyDy_LMS_Helper_2026-03-21T02_50_11_961475" src="https://github.com/user-attachments/assets/7495c62f-84ff-4251-85fc-d900c3bff58a" />
<img width="2446" height="1466" alt="MyDy_LMS_Helper_2026-03-21T02_51_47_161948" src="https://github.com/user-attachments/assets/1caedfd3-7b27-459c-b100-866a4e5a23f8" />

## Features

- **LMS Buddy Web App** — Light, responsive browser UI for students. Hosted at [`lms-buddy.krishaay.dev`](https://lms-buddy.krishaay.dev).
- **Courses + attendance** — Current-semester courses surfaced from attendance data, with the rest tucked under an accordion.
- **Course detail** — Browse and download every material in a course; bulk-download with progress and cancel.
- **Hit-rate Maxxer** — Reads each course's Course Progress widget from MyDy and visits every pending activity to bring it to 100%.
- **Lab / Journal utilities** — Stores student profile (name, USN, roll, batch) locally; cover-page and writeup generators (beta).
- **Local credentials only** — Email + password live in `localStorage` after sign-in; the logout button clears them.
- **Remote MCP server** — A `Streamable HTTP` MCP at `/api/mcp` lets Cursor, Claude Desktop, Claude Code, Codex CLI, and ChatGPT Desktop call your LMS.
- **Stdio MCP server** — Legacy local MCP (`mcp_server.py`) for Claude Code-style stdio configs.
- **Terminal UI** — Textual-based TUI for desktop browsing.

## Setup

### Web app

```sh
npm install
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

For local Vercel-style API + frontend development:

```sh
npx vercel dev
```

For a production frontend build:

```sh
npm run build
```

To run the full app locally without the Vercel CLI:

```sh
npm run local
```

The web app stores credentials in browser `localStorage` after login. Use the logout button to clear them. This is convenient for personal use, but do not use it on shared or untrusted machines.

### Deploy to Vercel

This repo includes `vercel.json`. Vercel will build the React app from `web/` and serve Python API functions from `api/`.

`requirements.txt` is intentionally kept minimal for Vercel and contains only the web/API scraper dependencies. Terminal UI and MCP-only packages live in `requirements-tui-mcp.txt` so Vercel does not try to build native packages such as `pydantic-core`.

```sh
vercel
```

Downloads are proxied through the API so users can download from LMS Buddy without separately logging into MyDy in the browser. Large files and bulk usage can consume Vercel bandwidth and may hit serverless limits.

### Terminal app

```sh
git clone https://github.com/kry0sc0pic/mydy-lms-scraper.git
cd mydy-lms-scraper
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows
uv pip install -r requirements.txt
# or: pip install -r requirements.txt
```

For the full terminal UI + MCP tooling, install the optional dependency set:

```sh
uv pip install -r requirements-tui-mcp.txt
# or: pip install -r requirements-tui-mcp.txt
```

### Configure terminal credentials (optional)

Create a `.env` file:
```
MYDY_USERNAME="your_email@dypatil.edu"
MYDY_PASSWORD="***REMOVED***"
```

If no `.env` is present, the app will show a login screen on startup.

### Run the TUI

```sh
python __main__.py
```

### Navigation

| Key / Action | What it does |
|---|---|
| Click sidebar items | Switch between Dashboard, All Courses, Bulk Download |
| Click a course | Open course detail page with tabs |
| `Back` button | Return to previous view |
| `Download Materials` | Download all files from the current course |
| `q` | Quit |

---

## Remote MCP Server (recommended)

The deployed web app exposes a stateless **Streamable HTTP MCP server** at:

```
https://lms-buddy.krishaay.dev/api/mcp
```

Authenticate with HTTP Basic auth using your MyDy email and password — every tool call logs in fresh, so the server holds no session state.

The web app's **MCP** tab (`/mcp`) generates the right config snippet for your client with your token already filled in. Or build the token yourself with:

```sh
printf 'your_email@dypatil.edu:***REMOVED***' | base64
```

### Available tools

| Tool | Args | Returns |
|------|------|---------|
| `list_subjects` | optional `include_all: bool` | Current-semester courses (matched from attendance) with attendance %; `include_all=true` adds older/archived courses |
| `list_files` | `course_id` | Downloadable materials in a course |
| `download_file` | `activity_url`, optional `save_to` | A self-authenticating `download_url` the client fetches via curl/native web tools (the URL embeds `u`/`p`/`a` as base64 query params; no expiry — treat it like the password) |
| `get_hitrates` | – | Course Progress widget percentage for every current course |
| `max_hitrate` | `course_id`, optional `course_name` | Visits every pending activity for a course; returns `percent_before / percent_after` |

Server-side TTL cache (in-process per warm Lambda): 5 min for `list_subjects` / `list_files`, 60 s for `get_hitrates`, 24 h for the download-resolve step. `max_hitrate` busts the user's hit-rate cache.

### Cursor — `~/.cursor/mcp.json`

```json
{
  "mcpServers": {
    "lms-buddy": {
      "url": "https://lms-buddy.krishaay.dev/api/mcp",
      "headers": { "Authorization": "***REMOVED***" }
    }
  }
}
```

### Claude Desktop — `claude_desktop_config.json`

```json
{
  "mcpServers": {
    "lms-buddy": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "https://lms-buddy.krishaay.dev/api/mcp",
               "--header", "Authorization:***REMOVED***"]
    }
  }
}
```

### Claude Code

```sh
claude mcp add --transport http lms-buddy https://lms-buddy.krishaay.dev/api/mcp \
  --header "Authorization: ***REMOVED***"
```

### Codex CLI — `~/.codex/config.toml`

```toml
[mcp_servers.lms-buddy]
url = "https://lms-buddy.krishaay.dev/api/mcp"

[mcp_servers.lms-buddy.headers]
Authorization = "***REMOVED***"
```

### ChatGPT Desktop

Settings → Connectors → **Add custom connector** → choose **Streamable HTTP**, then:

```
Name:           lms-buddy
Server URL:     https://lms-buddy.krishaay.dev/api/mcp
Auth method:    Custom HTTP header
Header name:    Authorization
Header value:   ***REMOVED***
```

### How `download_file` works

Tool calls only return a small JSON payload — the actual file bytes never go through the MCP transport (which dodges Claude Desktop's 1 MB tool-output cap and image-MIME quirks). The structured response looks like:

```json
{
  "download_url": "https://lms-buddy.krishaay.dev/api/download?u=…&p=…&a=…",
  "activity_url": "…",
  "save_to": "~/Downloads"
}
```

The AI agent then fetches that URL with its native HTTP/curl tool and writes the body using its file-write tool. With shell-capable agents, one line:

```sh
curl -L -OJ --output-dir "$save_to" "$download_url"
```

The URL embeds your credentials, so anyone with the URL can fetch the same file as long as the password is valid. Don't paste it in shared logs.

---

## Legacy stdio MCP Server

`mcp_server.py` is the original local stdio server (good for Claude Code if you prefer running things on-machine):

```sh
claude mcp add mydy-lms -e MYDY_USERNAME=your_email@dypatil.edu -e MYDY_PASSWORD=***REMOVED*** -- python /path/to/mcp_server.py
```

Manual config:

```json
{
  "mcpServers": {
    "mydy-lms": {
      "command": "python",
      "args": ["/path/to/mcp_server.py"],
      "env": {
        "MYDY_USERNAME": "your_email@dypatil.edu",
        "MYDY_PASSWORD": "***REMOVED***"
      }
    }
  }
}
```

Tools: `login`, `list_courses`, `get_course_content`, `get_assignments`, `get_grades`, `get_announcements`, `get_attendance`, `download_course_materials`, `hit_rate_maxxer`.

Install the optional dependency set first:

```sh
uv pip install -r requirements-tui-mcp.txt
```

---

## Project Structure

```
mydy-lms-scraper/
├── api/                 # Vercel Python API functions for LMS Buddy
│   ├── _shared.py        #   Per-request client factory + portal-down login retry
│   ├── login.py          #   Test creds
│   ├── dashboard.py      #   Courses + attendance
│   ├── course.py         #   Sections, assignments, grades, announcements, materials
│   ├── download.py       #   Streams a file (POST JSON or GET ?u=&p=&a=)
│   ├── hitrate.py        #   max_hitrate via Course Progress widget
│   ├── hitrate_status.py #   Batched read-only Course Progress snapshot
│   └── mcp.py            #   Streamable HTTP MCP server (5 tools)
├── web/                 # React frontend (incl. /mcp settings page)
├── __main__.py          # TUI entry point
├── app.py               # Textual TUI
├── client.py            # HTTP client (shared by TUI, web API, MCP servers)
├── mcp_server.py        # Legacy stdio MCP server
├── local_server.py      # Run the full stack locally without `vercel dev`
├── requirements.txt     # Vercel-only deps (web/API)
├── requirements-tui-mcp.txt  # TUI + stdio MCP extras
├── package.json         # Web app deps and scripts
└── vercel.json          # Vercel build and routing config
```

## Requirements
- Python 3.10+
- Internet connection
- Valid MyDy LMS account

## License
MIT License. Use at your own risk.

## Disclaimer
This tool is for educational purposes only. Respect your institution's terms of service and use responsibly. Only download content you have legitimate access to. This project is unofficial and made for personal/educational use. DY Patil or MyDY is not associated with this project.

Use responsibly. The author is not responsible for misuse, data loss, or violations of institutional policies.
