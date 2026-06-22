"""lms-buddy MCP server — stdio transport for uvx.

Reads credentials from environment variables:
  MYDY_EMAIL    (or MYDY_USERNAME for backwards compatibility)
  MYDY_PASSWORD

Exposes the same 5 tools as the Vercel HTTP server (api/mcp.py), adapted for
local use. download_file performs the download inline and saves to disk instead
of returning a redirect URL.

Usage (Claude Desktop config):
  {
    "mcpServers": {
      "lms-buddy": {
        "command": "uvx",
        "args": ["--from", "/path/to/rait-toolkit", "lms-buddy"],
        "env": {"MYDY_EMAIL": "you@dypatil.edu", "MYDY_PASSWORD": "secret"}
      }
    }
  }
"""
from __future__ import annotations

import difflib
import hashlib
import json
import os
import time
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from .client import MydyClient
from .gpa import fetch_gpa
from .render import (
    batch_render_covers,
    batch_render_eval_sheets,
    render_cover,
    render_eval_sheet,
)
from .tools import (
    _cache_invalidate_prefix,
    _tool_get_hitrates,
    _tool_list_files,
    _tool_list_subjects,
    _tool_max_hitrate,
    _user_key,
)

# -- credential store ---------------------------------------------------------
# Saved to ~/.lms-buddy/credentials.json so the user only has to enter them once.
# Env vars (MYDY_EMAIL, MYDY_PASSWORD, etc.) always take precedence over saved creds.

_LMS_DIR   = Path.home() / ".lms-buddy"
_CRED_FILE = _LMS_DIR / "credentials.json"
_SNAP_DIR  = _LMS_DIR / "snapshots"


# -- snapshot store -----------------------------------------------------------
# Each tool response is saved to ~/.lms-buddy/snapshots/<tool>/<key>.json
# where key = sha256(canonical args). On subsequent calls the previous snapshot
# is diffed against the new response so the LLM can see what changed.

def _snap_key(args: dict) -> str:
    canon = json.dumps(args, sort_keys=True)
    return hashlib.sha256(canon.encode()).hexdigest()[:16]


def _snap_path(tool: str, key: str) -> Path:
    p = _SNAP_DIR / tool
    p.mkdir(parents=True, exist_ok=True)
    return p / f"{key}.json"


def _load_snapshot(tool: str, key: str) -> dict | None:
    try:
        return json.loads(_snap_path(tool, key).read_text())
    except Exception:
        return None


def _save_snapshot(tool: str, key: str, text: str) -> None:
    _snap_path(tool, key).write_text(
        json.dumps({"ts": time.time(), "text": text}, indent=2)
    )


def _diff_text(old: str, new: str) -> str | None:
    """Return a unified diff string if old != new, else None."""
    if old == new:
        return None
    diff = list(difflib.unified_diff(
        old.splitlines(keepends=True),
        new.splitlines(keepends=True),
        fromfile="previous",
        tofile="current",
        lineterm="",
    ))
    return "".join(diff) if diff else None


def _with_diff(tool: str, args: dict, new_text: str) -> str:
    """Save snapshot and prepend a diff block if anything changed."""
    key = _snap_key(args)
    prev = _load_snapshot(tool, key)
    _save_snapshot(tool, key, new_text)
    if prev is None:
        return new_text
    diff = _diff_text(prev["text"], new_text)
    if diff is None:
        return f"[No changes since last read]\n\n{new_text}"
    return f"[Changes since last read]\n```diff\n{diff}\n```\n\n{new_text}"


def _load_saved_creds() -> dict:
    try:
        return json.loads(_CRED_FILE.read_text())
    except Exception:
        return {}


def _save_creds(update: dict) -> None:
    _CRED_FILE.parent.mkdir(parents=True, exist_ok=True)
    existing = _load_saved_creds()
    existing.update(update)
    _CRED_FILE.write_text(json.dumps(existing, indent=2))


_MYDY_NOT_SET = (
    "MyDy credentials are not set. "
    "Use the AskFollowupQuestion tool to ask the user: "
    "'What is your MyDy email and password? "
    "(Credentials are stored locally on your machine in ~/.lms-buddy/credentials.json — "
    "they are never sent anywhere except directly to mydy.dypatil.edu.)' "
    "Then call set_mydy_credentials(email, password) with their response."
)

_PORTAL_NOT_SET = (
    "UniClaIRE portal credentials are not set. "
    "Use the AskFollowupQuestion tool to ask the user: "
    "'What is your UniClaIRE registration number and password? "
    "(Credentials are stored locally on your machine in ~/.lms-buddy/credentials.json — "
    "they are never sent anywhere except directly to studentportal.universitysolutions.in.)' "
    "Then call set_portal_credentials(regno, password) with their response."
)

mcp = FastMCP(
    "lms-buddy",
    instructions=(
        "LMS Buddy MCP for RAIT/DY Patil students. "
        "READ AGENT_SETUP.md IN THE REPO ROOT AT THE START OF EVERY SESSION — it has full operating instructions. "
        "Credentials are stored locally at ~/.lms-buddy/credentials.json and never leave the machine "
        "except as auth to their respective portals. "
        "When credentials are missing, ALWAYS use AskFollowupQuestion to prompt the user — "
        "never just print a text instruction. "
        "LMS tools (MyDy): list_subjects, list_files, download_file, get_hitrates, max_hitrate, "
        "get_overall_attendance, get_course_attendance, get_semesters. "
        "GPA tool (UniClaIRE portal): get_gpa. "
        "PDF tools: render_cover_pdf, batch_render_covers_pdf, render_eval_sheet_pdf, "
        "batch_render_eval_sheets_pdf — each automatically opens the PDF after saving. "
        "Utility: set_mydy_credentials, set_portal_credentials, get_cached_info, open_pdf, self_update. "
        "IMPORTANT: Call get_cached_info at the start of any session to load the user's known "
        "identifiers (email, USN, roll number). Note: the UniClaIRE login uses a mobile/regno, "
        "NOT the student's roll number — these are different identifiers."
    ),
)


def _get_creds() -> tuple[str, str] | None:
    saved = _load_saved_creds()
    email = os.getenv("MYDY_EMAIL") or os.getenv("MYDY_USERNAME") or saved.get("mydy_email", "")
    password = os.getenv("MYDY_PASSWORD") or saved.get("mydy_password", "")
    return (email.strip(), password) if email and password else None


def _get_portal_creds() -> tuple[str, str] | None:
    saved = _load_saved_creds()
    regno = os.getenv("PORTAL_REGNO") or saved.get("portal_regno", "")
    passwd = os.getenv("PORTAL_PASSWORD") or saved.get("portal_password", "")
    return (regno.strip(), passwd) if regno and passwd else None


def _login() -> tuple[MydyClient | None, str | None]:
    creds = _get_creds()
    if not creds:
        return None, _MYDY_NOT_SET
    client = MydyClient()
    result = client.login(creds[0], creds[1])
    return (client, None) if result.get("success") else (None, result.get("message") or "Login failed.")


def _text(result: dict) -> str:
    return result["content"][0]["text"]


@mcp.tool()
def list_subjects(include_all: bool = False) -> str:
    """List LMS courses (subjects) with attendance percentage.

    Returns only the current semester by default. Pass include_all=True to also
    return older / archived courses. Use the returned id for other tools.
    """
    client, err = _login()
    if err:
        raise ValueError(err)
    creds = _get_creds()
    user = _user_key(creds)
    result = _tool_list_subjects(client, {"include_all": include_all}, user)
    if result.get("isError"):
        raise ValueError(_text(result))
    return _with_diff("list_subjects", {"include_all": include_all}, _text(result))


@mcp.tool()
def list_files(course_id: str) -> str:
    """List downloadable files for a subject.

    Pass the course id from list_subjects.
    """
    client, err = _login()
    if err:
        raise ValueError(err)
    creds = _get_creds()
    user = _user_key(creds)
    result = _tool_list_files(client, {"course_id": course_id}, user)
    if result.get("isError"):
        raise ValueError(_text(result))
    return _with_diff("list_files", {"course_id": course_id}, _text(result))


@mcp.tool()
def download_file(activity_url: str, save_to: str = "") -> str:
    """Download a file from the LMS and save it to disk.

    activity_url: activity URL on mydy.dypatil.edu (from list_files).
    save_to: optional folder path; defaults to ~/Downloads.
    Returns the path of the saved file.
    """
    client, err = _login()
    if err:
        raise ValueError(err)

    stream = client.open_material_stream(activity_url)
    if isinstance(stream, str):
        raise ValueError(f"Download failed: {stream}")

    folder = Path(save_to.strip() if save_to.strip() else "~/Downloads").expanduser()
    folder.mkdir(parents=True, exist_ok=True)
    filepath = folder / stream["filename"]

    with open(filepath, "wb") as f:
        for chunk in stream["response"].iter_content(chunk_size=65536):
            if chunk:
                f.write(chunk)

    return f"Saved to: {filepath}"


@mcp.tool()
def get_hitrates() -> str:
    """Read the current Course Progress hit rate (%) for every current course."""
    client, err = _login()
    if err:
        raise ValueError(err)
    creds = _get_creds()
    user = _user_key(creds)
    result = _tool_get_hitrates(client, {}, user)
    if result.get("isError"):
        raise ValueError(_text(result))
    return _with_diff("get_hitrates", {}, _text(result))


@mcp.tool()
def max_hitrate(course_id: str, course_name: str = "") -> str:
    """Maximize the Course Progress hit rate for a single course.

    Visits every pending activity and returns before/after percentage.
    """
    client, err = _login()
    if err:
        raise ValueError(err)
    creds = _get_creds()
    user = _user_key(creds)
    args = {"course_id": course_id}
    if course_name:
        args["course_name"] = course_name
    result = _tool_max_hitrate(client, args, user)
    if result.get("isError"):
        raise ValueError(_text(result))
    return _with_diff("max_hitrate", {"course_id": course_id}, _text(result))


@mcp.tool()
def get_overall_attendance() -> str:
    """Return attendance for all subjects plus an overall aggregate total.

    Each subject includes total classes, present, absent, percentage, and an
    altid you can pass to get_course_attendance for per-class drill-down.
    """
    client, err = _login()
    if err:
        raise ValueError(err)
    result = client.get_attendance()
    if isinstance(result, str):
        raise ValueError(result)
    subjects = result.get("subjects", [])
    lines = [
        f"Overall: {result['overall_present']}/{result['overall_total_classes']} "
        f"= {result['overall_percentage']}%",
        "",
    ]
    for s in subjects:
        altid_str = f" (altid={s['altid']})" if s.get("altid") else ""
        lines.append(f"- {s['subject']}: {s['percentage']}% "
                     f"({s['present']}/{s['total_classes']}){altid_str}")
    text = "\n".join(lines)
    return _with_diff("get_overall_attendance", {}, text)


@mcp.tool()
def get_course_attendance(altid: int) -> str:
    """Per-class attendance drill-down for a single subject.

    altid comes from list_subjects — each subject in the response has an 'altid'
    field. Returns every class with date, time, and present/absent status.
    """
    client, err = _login()
    if err:
        raise ValueError(err)
    result = client.get_course_attendance(altid)
    if isinstance(result, str):
        raise ValueError(result)
    if not result:
        return "No attendance records found."
    lines = [f"- {r['date']} {r['time']} | {r['status']}" for r in result]
    text = f"{len(result)} classes:\n" + "\n".join(lines)
    return _with_diff("get_course_attendance", {"altid": altid}, text)


@mcp.tool()
def get_semesters() -> str:
    """List all semesters with their courses, grouped by semester label.

    Returns a structured view of 'Semester V', 'Semester VI', etc. with the
    course ids and names within each. More structured than list_subjects.
    """
    client, err = _login()
    if err:
        raise ValueError(err)
    result = client.get_semesters()
    if isinstance(result, str):
        raise ValueError(result)
    if not result:
        return "No semester data found."
    lines = []
    for sem in result:
        lines.append(sem["semester"] + ":")
        for s in sem["subjects"]:
            lines.append(f"  - [{s['id']}] {s['name']}")
    text = "\n".join(lines)
    return _with_diff("get_semesters", {}, text)


@mcp.tool()
def render_cover_pdf(
    expnum: str,
    expname: str,
    name: str,
    division: str,
    roll: str,
    serial: str = "",
    general: bool = True,
    out: str = "cover.pdf",
) -> str:
    """Render a single experiment cover page to PDF.

    expnum: experiment number. expname: experiment title. name: student full name.
    division: division or course. roll: roll number. serial: serial number (optional).
    general: use general template (True) or detailed (False). out: output PDF path.
    Returns the saved PDF path or raises on failure.
    """
    result = render_cover(expnum=expnum, expname=expname, name=name,
                          division=division, roll=roll, serial=serial,
                          general=general, out=out)
    if not result.get("success"):
        raise ValueError(result.get("error", "Render failed"))
    open_pdf(result["path"])
    return result["path"]


@mcp.tool()
def batch_render_covers_pdf(
    documents: list[dict],
    general: bool = True,
    out: str = "covers_batch.pdf",
) -> str:
    """Render multiple experiment covers into a single multi-page PDF.

    documents: list of objects each with expnum, expname, name, division, roll
               (and optional serial). general: use general template. out: output path.
    Returns the saved PDF path and page count.
    """
    result = batch_render_covers(documents=documents, general=general, out=out)
    if not result.get("success"):
        raise ValueError(result.get("error", "Batch render failed"))
    open_pdf(result["path"])
    return f"Saved to: {result['path']} ({result.get('page_count', len(documents))} pages)"


@mcp.tool()
def render_eval_sheet_pdf(
    expnum: str,
    title: str,
    name: str,
    roll: str,
    serial: str = "",
    batch: str = "",
    cos: str = "",
    pomap: str = "",
    psomap: str = "",
    dateperf: str = "",
    dateeval: str = "",
    detailed: bool = False,
    out: str = "evaluation.pdf",
) -> str:
    """Render a single practical evaluation sheet to PDF.

    expnum: experiment number. title: experiment title. name: student full name.
    roll: roll number. serial/batch/cos/pomap/psomap/dateperf/dateeval: all optional.
    detailed: use detailed template with CO mapping. out: output PDF path.
    Returns the saved PDF path or raises on failure.
    """
    result = render_eval_sheet(expnum=expnum, title=title, name=name, roll=roll,
                               serial=serial, batch=batch, cos=cos, pomap=pomap,
                               psomap=psomap, dateperf=dateperf, dateeval=dateeval,
                               detailed=detailed, out=out)
    if not result.get("success"):
        raise ValueError(result.get("error", "Render failed"))
    open_pdf(result["path"])
    return result["path"]


@mcp.tool()
def batch_render_eval_sheets_pdf(
    documents: list[dict],
    detailed: bool = False,
    out: str = "evaluations_batch.pdf",
) -> str:
    """Render multiple evaluation sheets into a single multi-page PDF.

    documents: list of objects each with expnum, title, name, roll (required)
               and optional serial, batch, cos, pomap, psomap, dateperf, dateeval.
    detailed: use detailed template. out: output PDF path.
    Returns the saved PDF path and page count.
    """
    result = batch_render_eval_sheets(documents=documents, detailed=detailed, out=out)
    if not result.get("success"):
        raise ValueError(result.get("error", "Batch render failed"))
    open_pdf(result["path"])
    return f"Saved to: {result['path']} ({result.get('page_count', len(documents))} pages)"


@mcp.tool()
def open_pdf(path: str) -> str:
    """Open a PDF file in the system's default viewer.

    Call this automatically after any successful render_*_pdf tool call so the
    user can immediately see the output without having to navigate to the file.
    path: absolute or ~-relative path to the PDF file.
    """
    import subprocess
    import sys

    resolved = str(Path(path).expanduser().resolve())
    if not resolved.endswith(".pdf"):
        raise ValueError(f"Not a PDF file: {resolved}")
    if not Path(resolved).exists():
        raise ValueError(f"File not found: {resolved}")

    if sys.platform == "darwin":
        subprocess.Popen(["open", resolved])
    elif sys.platform.startswith("linux"):
        subprocess.Popen(["xdg-open", resolved])
    else:
        subprocess.Popen(["start", "", resolved], shell=True)

    return f"Opened: {resolved}"


@mcp.tool()
def get_cached_info() -> str:
    """Return all locally cached user profile data — call this at the start of a session.

    Returns known identifiers: MyDy email, UniClaIRE regno, USN (roll number from portal),
    and which credential sets are configured. Useful so the LLM doesn't need to ask the user
    for details it already has.

    Note: portal regno (mobile number used to log in) and USN (university roll number, e.g.
    23MTCO001) are different. Both are stored separately.
    """
    saved = _load_saved_creds()
    lines = ["Cached profile data:"]

    mydy_email = saved.get("mydy_email") or os.getenv("MYDY_EMAIL") or os.getenv("MYDY_USERNAME")
    lines.append(f"  MyDy email:       {mydy_email or '(not set)'}")
    lines.append(f"  MyDy password:    {'(set)' if saved.get('mydy_password') or os.getenv('MYDY_PASSWORD') else '(not set)'}")

    portal_regno = saved.get("portal_regno") or os.getenv("PORTAL_REGNO")
    lines.append(f"  Portal regno:     {portal_regno or '(not set)'}  ← mobile/login number for UniClaIRE")
    lines.append(f"  Portal password:  {'(set)' if saved.get('portal_password') or os.getenv('PORTAL_PASSWORD') else '(not set)'}")

    usn = saved.get("usn")
    lines.append(f"  USN (roll no):    {usn or '(not yet fetched — call get_gpa to populate)'}  ← university roll number")

    return "\n".join(lines)


@mcp.tool()
def set_mydy_credentials(email: str, password: str) -> str:
    """Save MyDy LMS credentials to ~/.lms-buddy/credentials.json.

    These are used by all LMS tools: list_subjects, list_files, download_file,
    get_hitrates, max_hitrate, get_overall_attendance, get_course_attendance, get_semesters.
    Env vars MYDY_EMAIL and MYDY_PASSWORD always take precedence if set.
    """
    if not email.strip() or not password:
        raise ValueError("Both email and password are required.")
    _save_creds({"mydy_email": email.strip(), "mydy_password": password})
    return f"MyDy credentials saved to {_CRED_FILE}."


@mcp.tool()
def set_portal_credentials(regno: str, password: str) -> str:
    """Save UniClaIRE student portal credentials to ~/.lms-buddy/credentials.json.

    regno is the mobile/registration number used to log in to the UniClaIRE portal —
    NOT the university roll number (USN). The USN (e.g. 23MTCO001) is auto-saved
    after a successful get_gpa call.
    Env vars PORTAL_REGNO and PORTAL_PASSWORD always take precedence if set.
    """
    if not regno.strip() or not password:
        raise ValueError("Both regno and password are required.")
    _save_creds({"portal_regno": regno.strip(), "portal_password": password})
    return f"UniClaIRE portal credentials saved to {_CRED_FILE}."


@mcp.tool()
def get_gpa() -> str:
    """Fetch semester-wise SGPA and cumulative CGPA from the UniClaIRE student portal.

    Requires portal credentials — call set_portal_credentials first if not already set,
    or set PORTAL_REGNO and PORTAL_PASSWORD environment variables.
    Returns CGPA, per-semester SGPA, and course-level grade breakdown.
    """
    creds = _get_portal_creds()
    if not creds:
        raise ValueError(_PORTAL_NOT_SET)
    data = fetch_gpa(creds[0], creds[1])

    # Persist USN so the LLM can retrieve it without re-fetching
    if data.get("usn"):
        _save_creds({"usn": data["usn"]})

    lines = [f"USN: {data['usn']}", f"CGPA: {data['cgpa']}", ""]
    for g in data["groups"]:
        lines.append(f"Semester {g['id']} — SGPA: {g['sgpa']}")
        for c in g["courses"]:
            grade_label = c["grade"] or "—"
            lines.append(f"  {c['name']} ({c.get('courseType', '')}) | {c['credits']} cr | {grade_label}")
        lines.append("")
    text = "\n".join(lines).rstrip()
    return _with_diff("get_gpa", {}, text)


@mcp.tool()
def self_update() -> str:
    """Pull the latest code from git and restart the MCP server process.

    Runs `git pull` in the repo root, then replaces the current process with a
    fresh instance so the updated code is loaded immediately. The MCP host will
    reconnect automatically on the next tool call.
    """
    import subprocess
    import sys

    repo = Path(__file__).resolve().parents[1]
    pull = subprocess.run(["git", "pull"], cwd=repo, capture_output=True, text=True)
    if pull.returncode != 0:
        raise ValueError(f"git pull failed:\n{pull.stderr.strip()}")
    summary = pull.stdout.strip() or "Already up to date."
    os.execv(sys.executable, [sys.executable, "-m", "lms_buddy"])
    return summary  # unreachable after execv


# -- prompts ------------------------------------------------------------------


@mcp.prompt()
def journal_writeup(expnum: str, title: str) -> str:
    """Write a complete experiment journal entry.

    Provide the experiment number and title. Claude will ask for any details
    it needs and produce a properly structured journal writeup.
    """
    return f"""\
You are helping a student at D.Y. Patil RAIT write a formal experiment journal entry.

Experiment: {expnum} — {title}

Write a complete, well-structured journal writeup with the following sections:

1. **Aim** — one or two sentences stating the objective clearly.
2. **Theory** — concise technical background (3–6 sentences). Explain the core concept, relevant definitions, and why the experiment is meaningful. Use precise technical language appropriate for an engineering student.
3. **Apparatus / Requirements** — bullet list of tools, software, hardware, or materials used.
4. **Procedure** — numbered step-by-step instructions written in the imperative (e.g. "Open the terminal and run…"). Be specific enough that another student could reproduce the experiment exactly.
5. **Observations / Output** — describe what was observed or paste the expected program output. If the experiment involves code, include a representative code snippet.
6. **Conclusion** — 2–4 sentences summarising what was demonstrated, what was learnt, and whether the aim was achieved.

Tone: formal academic English. Avoid first-person ("I did…"). Use passive or imperative voice throughout.

If you need any missing details (e.g. programming language, specific steps, observed output), ask the student before writing — do not invent facts.
"""


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
