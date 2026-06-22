"""GPA fetcher for the DY Patil UniClaIRE student portal.

Ported from gpa-calculator/netlify/functions/portal-import.mjs.
Portal: https://studentportal.universitysolutions.in
Auth:   regno (registration/mobile number) + passwd
"""
from __future__ import annotations

import time
import re
import requests

PORTAL_BASE = "https://studentportal.universitysolutions.in"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
)

LETTER_GRADE_MAP = {
    "O": "10", "A": "9", "B": "8", "C": "7",
    "D": "6", "E": "5", "P": "4", "F": "0", "AB": "0",
}
VALID_GRADES = {"10", "9", "8", "7", "6", "5", "4", "0"}


def _normalize_grade(raw: str) -> str:
    upper = raw.strip().upper()
    if upper in LETTER_GRADE_MAP:
        return LETTER_GRADE_MAP[upper]
    try:
        n = round(float(raw))
        s = str(n)
        return s if s in VALID_GRADES else ""
    except ValueError:
        return ""


def _calculate_sgpa(courses: list[dict]) -> float:
    total_points = total_credits = 0.0
    for c in courses:
        try:
            credits = float(c.get("credits") or 0)
            grade = float(c.get("grade") or 0)
            total_points += credits * grade
            total_credits += credits
        except (ValueError, TypeError):
            pass
    return round(total_points / total_credits, 2) if total_credits else 0.0


def fetch_gpa(regno: str, passwd: str) -> dict:
    """Login to UniClaIRE portal and return semester groups + CGPA.

    Returns:
        {
          "usn": str,
          "groups": [
            {
              "id": "1",
              "sgpa": 8.5,
              "courses": [{"name", "credits", "grade", "courseType", "iaMarks", "uniMarks", "totalMarks"}, ...]
            },
            ...
          ],
          "cgpa": 8.3
        }
    Or raises ValueError with an error message on failure.
    """
    session = requests.Session()
    session.headers.update({
        "User-Agent": UA,
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "*/*",
    })

    # 1. Login
    login_res = session.post(
        f"{PORTAL_BASE}/signin.php",
        data={"regno": regno, "passwd": passwd},
        headers={"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"},
        timeout=15,
    )
    login_ok = login_res.status_code < 400
    login_msg = ""
    try:
        j = login_res.json()
        if "error_code" in j:
            login_ok = str(j["error_code"]) == "0"
        login_msg = j.get("msg", "")
    except Exception:
        if re.search(r"invalid|incorrect|failed|wrong", login_res.text, re.IGNORECASE):
            login_ok = False
    if not login_ok:
        raise ValueError(login_msg or "Login rejected — check your UniClaIRE credentials.")

    # 2. Get USN
    profile_res = session.post(f"{PORTAL_BASE}/src/profile.php", timeout=10)
    profile = profile_res.json()
    usn = str(
        profile.get("strRegno") or profile.get("fregno") or
        profile.get("FREGNO") or profile.get("regno") or ""
    ).strip()
    if not usn:
        raise ValueError("Could not read USN from portal profile.")

    # 3. List exams (portal returns newest-first; reverse to oldest-first)
    list_res = session.get(
        f"{PORTAL_BASE}/src/results_new.php",
        params={"a": "getResAll", "_": int(time.time() * 1000)},
        timeout=10,
    )
    list_data = list_res.json()
    exams = [
        {"yearCode": str(r["year"]), "examName": str(r["examname"])}
        for r in (list_data.get("data") or [])
    ][::-1]  # oldest first

    # 4. Fetch each exam's marksheet
    raw_groups: list[list[dict]] = []
    for exam in exams:
        exam_res = session.get(
            f"{PORTAL_BASE}/src/results_new.php",
            params={"a": "getResults", "examno": exam["yearCode"], "regno": usn},
            timeout=15,
        )
        exam_data = exam_res.json()
        courses = [
            {
                "name": str(c.get("subject") or "").strip(),
                "credits": str(c.get("FCREDITS") or ""),
                "grade": _normalize_grade(str(c.get("remarks") or "")),
                "courseType": str(c.get("mthprue") or "").strip(),
                "iaMarks": str(c.get("ia_exam") or "").strip(),
                "uniMarks": str(c.get("uni_exam") or "").strip(),
                "totalMarks": str(c.get("thtot") or "").strip(),
            }
            for c in (exam_data.get("body") or [])
            if c.get("subject")
        ]
        raw_groups.append(courses)

    # 5. Cross-exam dedup: keep each subject only in its latest exam
    def subject_key(name: str) -> str:
        return re.sub(r"\s+", " ", name.lower())

    latest_exam: dict[str, int] = {}
    for i, courses in enumerate(raw_groups):
        for c in courses:
            latest_exam[subject_key(c["name"])] = i

    deduped = [
        [c for c in courses if latest_exam.get(subject_key(c["name"])) == i]
        for i, courses in enumerate(raw_groups)
    ]
    deduped = [g for g in deduped if g]

    # 6. Build result with per-semester SGPA and overall CGPA
    groups = []
    total_points = total_credits = 0.0
    for i, courses in enumerate(deduped):
        sgpa = _calculate_sgpa(courses)
        groups.append({"id": str(i + 1), "sgpa": sgpa, "courses": courses})
        for c in courses:
            try:
                cr = float(c.get("credits") or 0)
                gr = float(c.get("grade") or 0)
                total_points += cr * gr
                total_credits += cr
            except (ValueError, TypeError):
                pass

    cgpa = round(total_points / total_credits, 2) if total_credits else 0.0
    return {"usn": usn, "groups": groups, "cgpa": cgpa}
