# RAIT Toolkit — Claude Code Guide

## Build & run

```sh
# Run the MCP server directly (for testing)
uv run python -m lms_buddy

# Run a one-off script against the client
uv run python -c "from client import MydyClient; ..."
```

No separate install step — `uv` handles deps from `pyproject.toml`.

---

## Project layout

```
rait-toolkit/
├── client.py               # Root MydyClient — source of truth, keep in sync with lms_buddy/client.py
├── lms_buddy/
│   ├── __main__.py         # FastMCP server (all MCP tools live here)
│   ├── client.py           # Mirror of root client.py — must stay in sync
│   ├── tools.py            # Cached business logic (list_subjects, hitrates, etc.)
│   ├── gpa.py              # UniClaIRE GPA fetcher
│   ├── render.py           # LaTeX PDF rendering
│   └── templates/          # LaTeX source templates
├── plugin/                 # Claude Code plugin wrapper
├── api/                    # Vercel serverless (remote MCP)
└── web/                    # React frontend
```

**`client.py` is duplicated.** `root/client.py` is used by `api/` and direct scripts. `lms_buddy/client.py` is the copy bundled in the wheel. Any change to one must be applied to the other.

---

## Adding an MCP tool

1. Add the method to **both** `client.py` and `lms_buddy/client.py`
2. Add the `@mcp.tool()` decorated function in `lms_buddy/__main__.py`
3. Update the `instructions=` string in the `FastMCP(...)` call so the agent knows the tool exists
4. Update `AGENT_SETUP.md` tool reference table
5. Update `README.md` tools table and total count

---

## MydyClient conventions

- All methods return `dict | str` — a string means an error message, dict means success
- Use `self._rate_limit("activity")` before any outbound HTTP call
- Auth check at the top: `if not self.logged_in: return {"error": "Not logged in."}`
- Parse HTML with `BeautifulSoup(resp.text, "html.parser")`
- Session cookies are maintained by `self.session` (a `requests.Session`)

---

## MCP tool conventions

- `_login()` returns `(client, error_str)` — always check `if err: raise ValueError(err)`
- `_with_diff(tool_name, args_dict, text)` — wraps live-data tool responses with snapshot diffs; use for any tool that reads from the LMS
- Cache via `_cache_get` / `_cache_set` from `tools.py`; use `(user, tool_name, ...)` tuples as keys
- Always `raise ValueError(msg)` for errors — FastMCP surfaces these as tool errors to the client
- Credentials: `_get_creds()` → MyDy, `_get_portal_creds()` → UniClaIRE

---

## Assignment submission

### Client method: `MydyClient.submit_assignment(assign_url, file_path, force=False)`

Three-step flow:
1. GET `mod/assign/view.php?id=N&action=editsubmission` → scrape `sesskey`, `files_filemanager` (itemid), `userid`, `ctx_id`, `author`
2. POST `repository/repository_ajax.php` — multipart upload with `action=upload`, `repo_id=4`
3. POST `mod/assign/view.php` — form fields: `action=savesubmission`, `files_filemanager=<itemid>`

Pre-check: GETs the view page first to detect existing submission. Returns `{"status": "already_submitted"}` if already submitted and `force=False`.

### MCP guardrail

`submit_assignment` MCP tool requires a prior `get_assignments` call for the same course. URLs are registered in an in-process cache under `(user, "assignments_seen")` with a 1-hour TTL.

`force=True` bypasses the already-submitted check. It must **never** be set autonomously by the LLM — only on explicit user instruction.

### Blank placeholder PDF

`_ensure_blank_pdf()` writes a minimal valid PDF to `~/.lms-buddy/blank_submission.pdf` on first call. `max_hitrate` calls this and instructs the agent to ask the user before submitting it.

---

## Snapshot / diff system

Every live-data tool response is saved to `~/.lms-buddy/snapshots/<tool>/<sha256(args)[:16]>.json`. On subsequent calls the old text is diffed against the new; the result is prepended as a unified diff block (or `[No changes since last read]`). Implemented in `_with_diff()` in `__main__.py`.

---

## Credentials

Stored at `~/.lms-buddy/credentials.json`. Keys: `mydy_email`, `mydy_password`, `portal_regno`, `portal_password`, `usn`. Env vars always take precedence. Two separate auth domains — do not mix them.
