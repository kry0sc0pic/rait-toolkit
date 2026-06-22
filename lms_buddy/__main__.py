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

import json
import os
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

_CRED_FILE = Path.home() / ".lms-buddy" / "credentials.json"


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


def _resolve(env_key: str, saved_key: str, saved: dict) -> str:
    return os.getenv(env_key, "") or saved.get(saved_key, "")

mcp = FastMCP(
    "lms-buddy",
    instructions=(
        "LMS Buddy MCP for RAIT/DY Patil students. "
        "Credentials can be set via set_credentials tool or env vars (MYDY_EMAIL, MYDY_PASSWORD, "
        "PORTAL_REGNO, PORTAL_PASSWORD). Saved to ~/.lms-buddy/credentials.json. "
        "LMS tools (MyDy): list_subjects, list_files, download_file, get_hitrates, max_hitrate, "
        "get_overall_attendance, get_course_attendance, get_semesters. "
        "GPA tool (UniClaIRE portal): get_gpa. "
        "PDF tools: render_cover_pdf, batch_render_covers_pdf, render_eval_sheet_pdf, "
        "batch_render_eval_sheets_pdf. "
        "Utility: set_credentials, self_update."
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
        return None, (
            "No MyDy credentials found. Call set_credentials with mydy_email and mydy_password, "
            "or set MYDY_EMAIL and MYDY_PASSWORD environment variables."
        )
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
    return _text(result)


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
    return _text(result)


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
    return _text(result)


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
    return _text(result)


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
    return "\n".join(lines)


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
    return f"{len(result)} classes:\n" + "\n".join(lines)


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
    return "\n".join(lines)


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
    return f"Saved to: {result['path']} ({result.get('page_count', len(documents))} pages)"


@mcp.tool()
def set_credentials(
    mydy_email: str = "",
    mydy_password: str = "",
    portal_regno: str = "",
    portal_password: str = "",
) -> str:
    """Save credentials to ~/.lms-buddy/credentials.json for future use.

    mydy_email + mydy_password: for MyDy LMS (list_subjects, download, hitrates, etc.)
    portal_regno + portal_password: for UniClaIRE student portal (get_gpa)

    Only the fields you provide are updated — omit any you don't want to change.
    Env vars always override saved credentials.
    """
    update: dict = {}
    if mydy_email.strip():
        update["mydy_email"] = mydy_email.strip()
    if mydy_password:
        update["mydy_password"] = mydy_password
    if portal_regno.strip():
        update["portal_regno"] = portal_regno.strip()
    if portal_password:
        update["portal_password"] = portal_password
    if not update:
        raise ValueError("Provide at least one credential field to save.")
    _save_creds(update)
    saved_keys = ", ".join(update.keys())
    return f"Saved to {_CRED_FILE}: {saved_keys}"


@mcp.tool()
def get_gpa() -> str:
    """Fetch semester-wise SGPA and cumulative CGPA from the UniClaIRE student portal.

    Requires portal_regno and portal_password (set via set_credentials or
    PORTAL_REGNO / PORTAL_PASSWORD env vars).
    Returns CGPA, per-semester SGPA, and course-level grade breakdown.
    """
    creds = _get_portal_creds()
    if not creds:
        raise ValueError(
            "No UniClaIRE portal credentials found. "
            "Call set_credentials with portal_regno and portal_password, "
            "or set PORTAL_REGNO and PORTAL_PASSWORD environment variables."
        )
    data = fetch_gpa(creds[0], creds[1])

    lines = [f"USN: {data['usn']}", f"CGPA: {data['cgpa']}", ""]
    for g in data["groups"]:
        lines.append(f"Semester {g['id']} — SGPA: {g['sgpa']}")
        for c in g["courses"]:
            grade_label = c["grade"] or "—"
            lines.append(f"  {c['name']} ({c.get('courseType', '')}) | {c['credits']} cr | {grade_label}")
        lines.append("")
    return "\n".join(lines).rstrip()


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
