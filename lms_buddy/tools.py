"""Pure business logic for the lms-buddy MCP tools.

Extracted from api/mcp.py (which stays as the Vercel HTTP handler).
The only change from that source: the MydyClient import is relative.
"""
from __future__ import annotations

import hashlib
import re
import threading
import time

from .client import MydyClient  # noqa: F401 — re-exported for __main__


PROTOCOL_VERSION = "2025-06-18"
COURSE_VIEW = "https://mydy.dypatil.edu/rait/course/view.php"
CURRENT_SEM_FALLBACK = 8

CACHE_TTL = {
    "list_subjects": 300,
    "list_files": 300,
    "get_hitrates": 60,
    "download_resolve": 86400,
}


# -- in-process TTL cache -----------------------------------------------------

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
    digest = hashlib.sha256(f"{creds[0].lower().strip()}\x00{creds[1]}".encode()).hexdigest()
    return digest[:16]


# -- attendance name matching -------------------------------------------------

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


# -- result helpers -----------------------------------------------------------

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


def _join_save_path(folder: str, filename: str) -> str:
    cleaned = folder.rstrip().rstrip("/").rstrip("\\")
    if not cleaned:
        return filename
    sep = "\\" if "\\" in folder and "/" not in folder else "/"
    return f"{cleaned}{sep}{filename}"


# -- tool implementations -----------------------------------------------------

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

    _cache_invalidate_prefix((user, "get_hitrates"))

    summary = (
        f"{result.get('course_name') or course['name'] or course_id}: "
        f"{result.get('percent_before', '?')}% → {result.get('percent_after', '?')}% "
        f"(marked={result.get('marked', 0)}, "
        f"skipped={result.get('skipped', 0)}, "
        f"failed={result.get('failed', 0)})"
    )
    return _text_result(summary, structured=result)
