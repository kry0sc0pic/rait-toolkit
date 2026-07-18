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
UNIV_CODE = "051"  # DY Patil univcode used across app.php endpoints (RV forms, service status, dropdowns)
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
)

# Legacy scheme: O=10, A=9, B=8, C=7, D=6, E=5, P=4, F/AB=0
LEGACY_LETTER_GRADE_MAP = {
    "O": "10", "A": "9", "B": "8", "C": "7",
    "D": "6", "E": "5", "P": "4", "F": "0", "AB": "0",
}
# New scheme (DY24+ batch): O=10, A+=9, A=8, B+=7, B=6, C=5, P=4, F/AB=0
NEW_LETTER_GRADE_MAP = {
    "O": "10", "A+": "9", "A": "8", "B+": "7",
    "B": "6", "C": "5", "P": "4", "F": "0", "AB": "0",
}
VALID_GRADES = {"10", "9", "8", "7", "6", "5", "4", "0"}

_EXAM_CODE_RE = re.compile(r"^([A-Za-z])-(\d{4})-(\d+)$")


def _detect_scheme(usn: str) -> str:
    """DY24+ batch USNs use the new grade scheme; everything else is legacy."""
    m = re.match(r"^DY(\d{2})", usn, re.IGNORECASE)
    return "new" if m and int(m.group(1)) >= 24 else "legacy"


def _normalize_grade(raw: str, scheme: str = "legacy") -> str:
    upper = raw.strip().upper()
    grade_map = NEW_LETTER_GRADE_MAP if scheme == "new" else LEGACY_LETTER_GRADE_MAP
    if upper in grade_map:
        return grade_map[upper]
    try:
        n = round(float(raw))
        s = str(n)
        return s if s in VALID_GRADES else ""
    except ValueError:
        return ""


def _build_exam_list(list_data: dict) -> list[dict]:
    """Dedup exams by trimester letter, keeping only the latest year/attempt.

    Exam codes look like "A-2023-1" (letter-year-attempt); a re-attempt (ATKT)
    shows up as a second entry for the same letter with a higher attempt
    number, and a stale one must not be double-counted. Codes that don't match
    this shape are passed through keyed on themselves. Result is sorted
    oldest-to-newest by trimester letter.
    """
    exam_map: dict[str, dict] = {}
    for r in (list_data.get("data") or []):
        code = str(r["year"])
        m = _EXAM_CODE_RE.match(code)
        if m:
            letter, year, attempt = m.group(1), m.group(2), m.group(3)
            prev = exam_map.get(letter)
            if not prev or year > prev["year"] or (year == prev["year"] and int(attempt) > int(prev["attempt"])):
                exam_map[letter] = {
                    "year": year, "attempt": attempt,
                    "yearCode": code, "examName": str(r.get("examname", "")),
                }
        else:
            exam_map[code] = {"year": "", "attempt": "0", "yearCode": code, "examName": str(r.get("examname", ""))}

    return [
        {"yearCode": e["yearCode"], "examName": e["examName"]}
        for _, e in sorted(exam_map.items(), key=lambda kv: kv[0])
    ]


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


def _portal_login(regno: str, passwd: str) -> tuple[requests.Session, str, str]:
    """Login to the UniClaIRE portal. Returns (session, usn, scheme).

    Raises ValueError with a user-facing message on failure.
    """
    session = requests.Session()
    session.headers.update({
        "User-Agent": UA,
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "*/*",
    })

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

    profile_res = session.post(f"{PORTAL_BASE}/src/profile.php", timeout=10)
    profile = profile_res.json()
    usn = str(
        profile.get("strRegno") or profile.get("fregno") or
        profile.get("FREGNO") or profile.get("regno") or ""
    ).strip()
    if not usn:
        raise ValueError("Could not read USN from portal profile.")
    return session, usn, _detect_scheme(usn)


def fetch_gpa(regno: str, passwd: str) -> dict:
    """Login to UniClaIRE portal and return semester groups + CGPA.

    Returns:
        {
          "usn": str,
          "scheme": "legacy" | "new",
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
    session, usn, scheme = _portal_login(regno, passwd)

    # 3. List exams, deduped by trimester (keeps only the latest attempt)
    list_res = session.get(
        f"{PORTAL_BASE}/src/results_new.php",
        params={"a": "getResAll", "_": int(time.time() * 1000)},
        timeout=10,
    )
    exams = _build_exam_list(list_res.json())

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
                "grade": _normalize_grade(str(c.get("remarks") or ""), scheme),
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
    return {"usn": usn, "scheme": scheme, "groups": groups, "cgpa": cgpa}


def list_revaluation_windows(regno: str, passwd: str) -> dict:
    """List every exam and whether its revaluation/re-totalling/photocopy window is open now.

    Returns {"usn": str, "exams": [{"yearCode", "examName", "examDate", "resultDate",
              "open": bool, "windowDates": str}, ...]}
    """
    session, usn, _ = _portal_login(regno, passwd)
    res = session.get(
        f"{PORTAL_BASE}/src/results_new.php",
        params={"a": "getRvAll", "_": int(time.time() * 1000)},
        timeout=10,
    )
    exams = [
        {
            "yearCode": str(r.get("year", "")),
            "examName": str(r.get("examname", "")),
            "examDate": str(r.get("examdate", "")),
            "resultDate": str(r.get("resultdate", "")),
            "open": str(r.get("rvenable", "0")) == "1",
            "windowDates": re.sub(r"<br\s*/?>", " | ", str(r.get("rvdates", ""))),
        }
        for r in (res.json().get("data") or [])
    ]
    return {"usn": usn, "exams": exams}


def list_revaluation_applications(regno: str, passwd: str) -> dict:
    """List the student's submitted revaluation/re-totalling/photocopy applications.

    Returns {"usn": str, "applications": [{"appNo", "appliedDate", "amount", "paymentDate",
              "paymentType", "status"}, ...]}
    """
    session, usn, _ = _portal_login(regno, passwd)
    res = session.get(
        f"{PORTAL_BASE}/src/yourAppsRVRT.php",
        params={"a": "getYourAppsRVRT", "regno": usn, "_": int(time.time() * 1000)},
        timeout=10,
    )
    apps = [
        {
            "appNo": str(r.get("APPNO", "")),
            "appliedDate": str(r.get("FAPPDATE", "")),
            "amount": str(r.get("FTOTAL", "")),
            "paymentDate": str(r.get("FACKDATE", "")),
            "paymentType": str(r.get("FPAYMENTTYPE", "")),
            "status": str(r.get("status", "")),
        }
        for r in (res.json().get("tableData") or [])
    ]
    return {"usn": usn, "applications": apps}


def get_revaluation_application_status(regno: str, passwd: str, app_no: str) -> dict:
    """Get the per-subject status of a specific revaluation/re-totalling/photocopy application.

    Returns {"usn": str, "appNo": str, "items": [{"subjectCode", "subjectName", "examName",
              "examDate", "correctionType", "correctionLabel", "processed": bool}, ...]}
    """
    session, usn, _ = _portal_login(regno, passwd)
    res = session.post(
        f"{PORTAL_BASE}/src/rvappstatus.php",
        data={"app_no": app_no},
        headers={"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"},
        timeout=15,
    )
    items = [
        {
            "subjectCode": str(r.get("fsubcode", "")),
            "subjectName": str(r.get("fsubname", "")).strip(),
            "examName": str(r.get("fexamname", "")),
            "examDate": str(r.get("fexamdate", "")),
            "correctionType": str(r.get("fcorrtype", "")),
            "correctionLabel": str(r.get("fcorrdescpn", "")),
            "processed": str(r.get("frvstatus", "")) == "T",
        }
        for r in (res.json().get("data") or [])
    ]
    return {"usn": usn, "appNo": str(app_no), "items": items}


def fetch_revaluation_application_pdf(regno: str, passwd: str, app_no: str) -> bytes:
    """Download the printable PDF for a revaluation/re-totalling/photocopy application."""
    session, _, _ = _portal_login(regno, passwd)
    res = session.get(
        f"{PORTAL_BASE}/app.php",
        params={"a": "PrintRevaluationApplicationForm", "app_no": app_no, "univcode": UNIV_CODE},
        timeout=20,
    )
    if not res.content.startswith(b"%PDF"):
        raise ValueError("Portal did not return a PDF — check the application number.")
    return res.content
