"""Streamable HTTP MCP server for LMS Buddy.

Exposes 5 LMS tools over JSON-RPC 2.0 with HTTP Basic auth (email:password).
Stateless — every tool call logs in fresh against MyDy. Designed to run on
Vercel serverless (BaseHTTPRequestHandler) and the local dev server.

Tools:
  - list_subjects               -> current courses with attendance %
  - list_files(course_id)       -> downloadable materials in a course
  - download_file(activity_url) -> base64 file blob (max ~3 MB)
  - get_hitrates                -> Course Progress % for every current course
  - max_hitrate(course_id, ...) -> visit pending activities to max hit rate
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from client import MydyClient  # noqa: E402


PROTOCOL_VERSION = "2025-06-18"
SERVER_INFO = {"name": "lms-buddy", "version": "0.4.1"}
COURSE_VIEW = "https://mydy.dypatil.edu/rait/course/view.php"
CURRENT_SEM_FALLBACK = 8  # only used when attendance has no subjects (rare)
MAX_DOWNLOAD_BYTES = 3 * 1024 * 1024  # ~3 MB raw -> ~4 MB base64; under Vercel 4.5 MB cap.

CACHE_TTL = {
    "list_subjects": 300,        # 5 min
    "list_files": 300,           # 5 min
    "get_hitrates": 60,          # 1 min
    "download_resolve": 86400,   # 24 h: activity_url -> file URL/source mapping
}


# -- in-process TTL cache (per warm Lambda instance) ----------------------


_CACHE_LOCK = threading.RLock()
_CACHE_STORE: dict[tuple, tuple[float, object]] = {}


def _cache_get(key: tuple):
    with _CACHE_LOCK:
        entry = _CACHE_STORE.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if time.time() > expires_at:
            _CACHE_STORE.pop(key, None)
            return None
        return value


def _cache_set(key: tuple, value, ttl: int) -> None:
    with _CACHE_LOCK:
        _CACHE_STORE[key] = (time.time() + ttl, value)


def _cache_invalidate_prefix(prefix: tuple) -> None:
    with _CACHE_LOCK:
        for key in list(_CACHE_STORE.keys()):
            if key[: len(prefix)] == prefix:
                _CACHE_STORE.pop(key, None)


def _user_key(creds: tuple[str, str]) -> str:
    """Stable per-user cache namespace; password included so cache invalidates on rotation."""
    digest = hashlib.sha256(f"{creds[0].lower().strip()}\x00{creds[1]}".encode()).hexdigest()
    return digest[:16]


# -- attendance name matching (mirrors the web frontend's heuristic) ------


def _normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


def _acronym(value: str) -> str:
    parts = [p for p in re.split(r"[^a-zA-Z0-9]+", value or "") if p]
    return "".join(p[0].lower() for p in parts)


def _attendance_for_course(course_name: str, att_subjects: list) -> dict | None:
    if not course_name or not att_subjects:
        return None
    norm_course = _normalize_name(course_name)
    course_acr = _acronym(course_name)
    for entry in att_subjects:
        if not isinstance(entry, dict):
            continue
        subject = entry.get("subject") or ""
        norm_sub = _normalize_name(subject)
        if not norm_sub:
            continue
        if (
            norm_sub == norm_course
            or norm_sub in norm_course
            or norm_course in norm_sub
            or _acronym(subject) == course_acr
        ):
            return entry
    return None


def _split_current_older(courses: list[dict], att_subjects: list) -> tuple[list[dict], list[dict]]:
    """Use attendance subjects to determine the active semester's courses.

    Mirrors the web UI: iterate attendance subjects, match each to a course by
    normalized name / acronym; the matched courses are "current". Anything else
    is "older". Falls back to the first N courses only when attendance has no
    subjects (e.g. brand-new account).
    """
    if not att_subjects:
        return courses[:CURRENT_SEM_FALLBACK], courses[CURRENT_SEM_FALLBACK:]

    current: list[dict] = []
    seen_ids: set[str] = set()
    for entry in att_subjects:
        if not isinstance(entry, dict):
            continue
        subject = entry.get("subject") or ""
        norm_sub = _normalize_name(subject)
        if not norm_sub:
            continue
        sub_acr = _acronym(subject)
        for course in courses:
            cid = str(course.get("id") or "")
            if cid in seen_ids:
                continue
            cname = course.get("name") or ""
            norm_course = _normalize_name(cname)
            if not norm_course:
                continue
            if (
                norm_sub == norm_course
                or norm_sub in norm_course
                or norm_course in norm_sub
                or _acronym(cname) == sub_acr
            ):
                current.append(course)
                seen_ids.add(cid)
                break

    if not current:
        return courses[:CURRENT_SEM_FALLBACK], courses[CURRENT_SEM_FALLBACK:]

    older = [c for c in courses if str(c.get("id") or "") not in seen_ids]
    return current, older


TOOLS = [
    {
        "name": "list_subjects",
        "description": (
            "List LMS courses (subjects) with attendance percentage. "
            "Returns only the current semester (8 courses) by default. "
            "Pass include_all=true to also return older / archived courses. "
            "Use the returned `id` for other tools that need a course."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "include_all": {
                    "type": "boolean",
                    "description": "Include older / archived courses in addition to the current semester.",
                    "default": False,
                },
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "list_files",
        "description": "List downloadable files for a subject. Pass the course id from list_subjects.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "course_id": {"type": "string", "description": "Course id from list_subjects."},
            },
            "required": ["course_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "download_file",
        "description": (
            "Download a file from an LMS activity URL (use list_files to discover URLs). "
            f"Returns the file as a base64 blob; cap is {MAX_DOWNLOAD_BYTES} bytes. "
            "Pass `save_to` with a folder path to receive an explicit save target — "
            "the MCP server runs remotely so it can't write to your disk; the calling "
            "AI/client is expected to decode the blob and save it there."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "activity_url": {"type": "string", "description": "Activity URL on mydy.dypatil.edu."},
                "save_to": {
                    "type": "string",
                    "description": (
                        "Optional folder path on the calling machine. When provided, the response "
                        "tells the client to save the decoded bytes at <save_to>/<filename>. "
                        "Tilde (~) and relative paths are returned verbatim — interpret them in your client."
                    ),
                },
            },
            "required": ["activity_url"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_hitrates",
        "description": "Read the current Course Progress hit rate (%) for every current course.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    {
        "name": "max_hitrate",
        "description": (
            "Maximize the Course Progress hit rate for a single course by visiting every "
            "pending activity. Returns before/after percentage."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "course_id": {"type": "string"},
                "course_name": {"type": "string", "description": "Optional human-readable name."},
            },
            "required": ["course_id"],
            "additionalProperties": False,
        },
    },
]


def _parse_basic(auth_header: str | None) -> tuple[str, str] | None:
    if not auth_header:
        return None
    parts = auth_header.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "basic":
        return None
    try:
        decoded = base64.b64decode(parts[1].strip()).decode("utf-8")
    except Exception:
        return None
    if ":" not in decoded:
        return None
    email, password = decoded.split(":", 1)
    return email.strip(), password


def _login(creds: tuple[str, str] | None) -> tuple[MydyClient | None, str | None]:
    if not creds:
        return None, "Missing 'Authorization: Basic <base64(email:password)>' header."
    client = MydyClient()
    result = client.login(creds[0], creds[1])
    if not result.get("success"):
        return None, result.get("message") or "Login failed."
    return client, None


def _text_result(text: str, *, structured: dict | None = None, is_error: bool = False) -> dict:
    payload: dict = {
        "content": [{"type": "text", "text": text}],
        "isError": is_error,
    }
    if structured is not None and not is_error:
        payload["structuredContent"] = structured
    return payload


def _course_obj(course_id: str, name: str | None = None) -> dict:
    return {"id": course_id, "name": (name or "").strip(), "url": f"{COURSE_VIEW}?id={course_id}"}


def _build_subject_items(courses: list[dict], att_subjects: list) -> list[dict]:
    items: list[dict] = []
    for course in courses:
        name = course.get("name") or ""
        att = _attendance_for_course(name, att_subjects)
        items.append({
            "id": str(course.get("id") or ""),
            "name": name,
            "url": course.get("url") or "",
            "attendance_percentage": (att or {}).get("percentage"),
            "attendance_subject": (att or {}).get("subject"),
        })
    return items


def _tool_list_subjects(client: MydyClient, args: dict, user: str) -> dict:
    include_all = bool(args.get("include_all"))
    cache_key = (user, "list_subjects", include_all)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    courses = client.list_courses()
    if isinstance(courses, str):
        return _text_result(courses, is_error=True)

    attendance = client.get_attendance()
    att_subjects = attendance.get("subjects", []) if isinstance(attendance, dict) else []

    current, older = _split_current_older(courses, att_subjects)

    current_items = _build_subject_items(current, att_subjects)
    older_items = _build_subject_items(older, att_subjects) if include_all else []

    structured = {
        "include_all": include_all,
        "current_count": len(current_items),
        "subjects": current_items + older_items,
    }
    if include_all:
        structured["older_count"] = len(older_items)

    if not current_items and not older_items:
        result = _text_result("No courses found.", structured=structured)
        _cache_set(cache_key, result, CACHE_TTL["list_subjects"])
        return result

    def _render(label: str, items: list[dict]) -> list[str]:
        out = [label]
        for s in items:
            att = f" — {s['attendance_percentage']}% attendance" if s["attendance_percentage"] is not None else ""
            out.append(f"- [{s['id']}] {s['name']}{att}")
        return out

    lines: list[str] = []
    if current_items:
        lines.extend(_render("Current courses:", current_items))
    if include_all and older_items:
        if lines:
            lines.append("")
        lines.extend(_render(f"Older courses ({len(older_items)}):", older_items))

    result = _text_result("\n".join(lines), structured=structured)
    _cache_set(cache_key, result, CACHE_TTL["list_subjects"])
    return result


def _tool_list_files(client: MydyClient, args: dict, user: str) -> dict:
    course_id = str(args.get("course_id") or "").strip()
    if not course_id:
        return _text_result("course_id is required.", is_error=True)

    cache_key = (user, "list_files", course_id)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    materials = client.list_downloadable_materials(course_id)
    if isinstance(materials, str):
        return _text_result(materials, is_error=True)

    items = materials.get("materials", []) if isinstance(materials, dict) else []
    if not items:
        result = _text_result(
            f"No downloadable files in {materials.get('course_name', course_id)}.",
            structured=materials,
        )
        _cache_set(cache_key, result, CACHE_TTL["list_files"])
        return result

    lines = [f"Files for {materials.get('course_name', course_id)}:"]
    for m in items:
        lines.append(f"- {m['name']} ({m['type']}) → {m['activity_url']}")
    result = _text_result("\n".join(lines), structured=materials)
    _cache_set(cache_key, result, CACHE_TTL["list_files"])
    return result


def _join_save_path(folder: str, filename: str) -> str:
    """Best-effort path join that preserves the literal folder string (incl. ~)."""
    cleaned = folder.rstrip().rstrip("/").rstrip("\\")
    if not cleaned:
        return filename
    sep = "\\" if "\\" in folder and "/" not in folder else "/"
    return f"{cleaned}{sep}{filename}"


def _tool_download_file(client: MydyClient, args: dict, user: str) -> dict:
    activity_url = str(args.get("activity_url") or "").strip()
    if not activity_url:
        return _text_result("activity_url is required.", is_error=True)

    save_to_raw = args.get("save_to")
    save_to = str(save_to_raw).strip() if isinstance(save_to_raw, str) and save_to_raw.strip() else None

    # File contents are always streamed fresh, but the resolve step (parse the
    # activity page to find a downloadable URL) is cached per user+activity.
    resolve_key = (user, "download_resolve", activity_url)
    cached_resolution = _cache_get(resolve_key)
    if cached_resolution is not None and isinstance(cached_resolution, dict):
        try:
            client._rate_limit("download")  # type: ignore[attr-defined]
            response = client.session.get(cached_resolution["file_url"], stream=True)
            if response.status_code == 200:
                stream = {
                    "response": response,
                    "filename": cached_resolution.get("filename")
                    or client._filename_from_response(response, cached_resolution["file_url"]),  # type: ignore[attr-defined]
                    "source": cached_resolution.get("source", "direct"),
                }
            else:
                response.close()
                stream = client.open_material_stream(activity_url)
        except Exception:
            stream = client.open_material_stream(activity_url)
    else:
        stream = client.open_material_stream(activity_url)

    if isinstance(stream, str):
        return _text_result(stream, is_error=True)

    response = stream["response"]
    filename = stream.get("filename") or "material.bin"
    mime = (response.headers.get("content-type") or "application/octet-stream").split(";", 1)[0].strip()

    buffer = bytearray()
    try:
        for chunk in response.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            buffer.extend(chunk)
            if len(buffer) > MAX_DOWNLOAD_BYTES:
                return _text_result(
                    f"File exceeds {MAX_DOWNLOAD_BYTES} bytes (~{MAX_DOWNLOAD_BYTES // (1024 * 1024)} MB) "
                    "and can't be returned over MCP. Use the web app to download.",
                    is_error=True,
                )
    except Exception as exc:
        return _text_result(f"Download stream failed: {exc}", is_error=True)
    finally:
        try:
            response.close()
        except Exception:
            pass

    file_url = stream["response"].url
    _cache_set(
        resolve_key,
        {
            "file_url": file_url,
            "filename": filename,
            "source": stream.get("source"),
        },
        CACHE_TTL["download_resolve"],
    )

    blob = base64.b64encode(bytes(buffer)).decode("ascii")
    target_path = _join_save_path(save_to, filename) if save_to else None

    summary_lines = [
        f"Downloaded {filename} ({len(buffer)} bytes, {mime}).",
    ]
    if target_path:
        summary_lines.append(
            f"Save target: {target_path}. The MCP server runs remotely and "
            "cannot write to your filesystem; decode the base64 below and "
            "write the bytes to that path using your local file-write tool."
        )
    else:
        summary_lines.append(
            "Decode the base64 below to recover the file. The MCP server "
            "runs remotely so it cannot write to your filesystem directly."
        )
    summary_lines.append(f"filename={filename}")
    summary_lines.append(f"mime={mime}")
    summary = "\n".join(summary_lines)

    structured: dict = {
        "filename": filename,
        "mime_type": mime,
        "size_bytes": len(buffer),
        "source": stream.get("source"),
        "content_base64": blob,
    }
    if save_to:
        structured["save_to"] = save_to
        structured["target_path"] = target_path

    # NOTE: We do NOT return an MCP `resource` content block here. The spec
    # supports `resource.blob` for binary attachments, but Claude Desktop's
    # bridge converts it to an `image` block and rejects non-image MIME types
    # ("ClaudeAiToolResultRequest.content.1.image.source.media_type"). Embedding
    # the base64 in plain text + structuredContent works on every client.
    return {
        "content": [
            {"type": "text", "text": summary},
            {"type": "text", "text": f"```base64\n{blob}\n```"},
        ],
        "structuredContent": structured,
        "isError": False,
    }


def _tool_get_hitrates(client: MydyClient, args: dict, user: str) -> dict:
    cache_key = (user, "get_hitrates")
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    courses = client.list_courses()
    if isinstance(courses, str):
        return _text_result(courses, is_error=True)

    attendance = client.get_attendance()
    att_subjects = attendance.get("subjects", []) if isinstance(attendance, dict) else []
    current, _older = _split_current_older(courses, att_subjects)
    if not current:
        return _text_result("No current courses found.", structured={"courses": []})

    batch = client.hit_rate_snapshot_courses([
        _course_obj(str(c["id"]), c.get("name")) for c in current
    ])
    if isinstance(batch, dict) and batch.get("error"):
        return _text_result(batch["error"], is_error=True)

    rows = batch.get("courses", {}) if isinstance(batch, dict) else {}
    items: list[dict] = []
    for course in current:
        cid = str(course.get("id"))
        row = rows.get(cid) or {}
        if "error" in row:
            items.append({"id": cid, "name": course.get("name"), "error": row["error"]})
            continue
        items.append({
            "id": cid,
            "name": course.get("name"),
            "percent": row.get("percent"),
            "viewed": row.get("viewed"),
            "total": row.get("total"),
        })

    lines = ["Hit rates:"]
    for s in items:
        if s.get("error"):
            lines.append(f"- [{s['id']}] {s['name']}: error — {s['error']}")
        elif s.get("total"):
            lines.append(f"- [{s['id']}] {s['name']}: {s['percent']}% ({s['viewed']}/{s['total']})")
        else:
            lines.append(f"- [{s['id']}] {s['name']}: no progress widget")
    result = _text_result("\n".join(lines), structured={"courses": items})
    _cache_set(cache_key, result, CACHE_TTL["get_hitrates"])
    return result


def _tool_max_hitrate(client: MydyClient, args: dict, user: str) -> dict:
    course_id = str(args.get("course_id") or "").strip()
    if not course_id:
        return _text_result("course_id is required.", is_error=True)

    course = _course_obj(course_id, args.get("course_name"))
    result = client.hit_rate_maxx_course(course)
    if isinstance(result, dict) and result.get("error"):
        return _text_result(result["error"], is_error=True)

    # Mutating call: bust hit-rate snapshot cache for this user (next get_hitrates
    # will hit MyDy fresh).
    _cache_invalidate_prefix((user, "get_hitrates"))

    summary = (
        f"{result.get('course_name') or course['name'] or course_id}: "
        f"{result.get('percent_before', '?')}% → {result.get('percent_after', '?')}% "
        f"(marked={result.get('marked', 0)}, "
        f"skipped={result.get('skipped', 0)}, "
        f"failed={result.get('failed', 0)})"
    )
    return _text_result(summary, structured=result)


TOOL_DISPATCH = {
    "list_subjects": _tool_list_subjects,
    "list_files": _tool_list_files,
    "download_file": _tool_download_file,
    "get_hitrates": _tool_get_hitrates,
    "max_hitrate": _tool_max_hitrate,
}


def _call_tool(name: str, args: dict, creds: tuple[str, str] | None) -> dict:
    fn = TOOL_DISPATCH.get(name)
    if fn is None:
        return _text_result(f"Unknown tool: {name}", is_error=True)

    if not creds:
        return _text_result(
            "Missing 'Authorization: Basic <base64(email:password)>' header.",
            is_error=True,
        )
    user_key = _user_key(creds)

    client, err = _login(creds)
    if err:
        return _text_result(err, is_error=True)

    try:
        return fn(client, args or {}, user_key)
    except Exception as exc:
        return _text_result(f"Tool '{name}' failed: {exc}\n{traceback.format_exc()}", is_error=True)


# -- JSON-RPC plumbing ----------------------------------------------------


def _jsonrpc_error(request_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _jsonrpc_result(request_id, result) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _handle_message(message: dict, creds: tuple[str, str] | None) -> dict | None:
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        return _jsonrpc_error(None, -32600, "Invalid JSON-RPC 2.0 request.")
    method = message.get("method")
    request_id = message.get("id")
    params = message.get("params") or {}

    if method is None:
        return _jsonrpc_error(request_id, -32600, "Missing method.")

    if method == "initialize":
        return _jsonrpc_result(request_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": SERVER_INFO,
            "instructions": (
                "LMS Buddy MCP. Authenticate with HTTP Basic auth using your MyDy email:password. "
                "Tools: list_subjects, list_files, download_file, get_hitrates, max_hitrate."
            ),
        })

    if method == "ping":
        return _jsonrpc_result(request_id, {})

    if method == "notifications/initialized":
        return None  # notification, no response

    if isinstance(method, str) and method.startswith("notifications/"):
        return None

    if method == "tools/list":
        return _jsonrpc_result(request_id, {"tools": TOOLS})

    if method == "tools/call":
        tool_name = params.get("name")
        if not isinstance(tool_name, str):
            return _jsonrpc_error(request_id, -32602, "Missing tool name.")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            return _jsonrpc_error(request_id, -32602, "Tool arguments must be an object.")
        result = _call_tool(tool_name, arguments, creds)
        return _jsonrpc_result(request_id, result)

    return _jsonrpc_error(request_id, -32601, f"Method not found: {method}")


# -- HTTP handler ---------------------------------------------------------


def _set_cors_headers(req: BaseHTTPRequestHandler) -> None:
    req.send_header("access-control-allow-origin", "*")
    req.send_header(
        "access-control-allow-methods",
        "GET, POST, OPTIONS, DELETE",
    )
    req.send_header(
        "access-control-allow-headers",
        "authorization, content-type, mcp-session-id, mcp-protocol-version",
    )
    req.send_header(
        "access-control-expose-headers",
        "mcp-session-id, mcp-protocol-version, www-authenticate",
    )


def _send_json(req: BaseHTTPRequestHandler, status: int, payload: dict | list) -> None:
    body = json.dumps(payload).encode("utf-8")
    req.send_response(status)
    req.send_header("content-type", "application/json")
    req.send_header("content-length", str(len(body)))
    _set_cors_headers(req)
    req.end_headers()
    req.wfile.write(body)


def _send_status(req: BaseHTTPRequestHandler, status: int, message: str | None = None) -> None:
    body = (message or "").encode("utf-8")
    req.send_response(status)
    req.send_header("content-type", "text/plain; charset=utf-8")
    req.send_header("content-length", str(len(body)))
    if status == 401:
        req.send_header("www-authenticate", 'Basic realm="lms-buddy"')
    _set_cors_headers(req)
    req.end_headers()
    if body:
        req.wfile.write(body)


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):  # noqa: N802 — Vercel handler convention
        self.send_response(204)
        _set_cors_headers(self)
        self.end_headers()

    def do_GET(self):  # noqa: N802
        # Streamable HTTP optionally supports GET for SSE; we don't.
        _send_status(self, 405, "GET not supported. POST JSON-RPC to /api/mcp.")

    def do_DELETE(self):  # noqa: N802
        # Stateless server: nothing to clean up.
        _send_status(self, 204)

    def do_POST(self):  # noqa: N802
        try:
            length = int(self.headers.get("content-length", "0") or 0)
            raw = self.rfile.read(length).decode("utf-8") if length else ""
            try:
                payload = json.loads(raw or "null")
            except json.JSONDecodeError:
                _send_json(self, 400, _jsonrpc_error(None, -32700, "Parse error."))
                return

            creds = _parse_basic(self.headers.get("authorization"))

            if isinstance(payload, list):
                responses = []
                for msg in payload:
                    if not isinstance(msg, dict):
                        responses.append(_jsonrpc_error(None, -32600, "Invalid request."))
                        continue
                    out = _handle_message(msg, creds)
                    if out is not None:
                        responses.append(out)
                if not responses:
                    _send_status(self, 202)
                    return
                _send_json(self, 200, responses)
                return

            if not isinstance(payload, dict):
                _send_json(self, 400, _jsonrpc_error(None, -32600, "Invalid request."))
                return

            response = _handle_message(payload, creds)
            if response is None:
                _send_status(self, 202)
                return
            _send_json(self, 200, response)
        except Exception as exc:
            _send_json(self, 500, _jsonrpc_error(None, -32603, f"Internal error: {exc}"))
