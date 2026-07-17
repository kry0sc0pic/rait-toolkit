"""LaTeX-based PDF rendering for experiment cover pages and evaluation sheets.

Ported from https://github.com/kry0sc0pic/experiment-cover.
Templates live in lms_buddy/templates/.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

_TEMPLATES_DIR = Path(__file__).parent / "templates"

COVER_TEMPLATE_PATH   = _TEMPLATES_DIR / "template_general.tex"
EVAL_TEMPLATE_PATH    = _TEMPLATES_DIR / "eval_template.tex"
CONFERENCE_LETTER_TEMPLATE_PATH = _TEMPLATES_DIR / "conference_letter_template.tex"

COVER_PLACEHOLDERS = {
    "__EXPNUM__":      "expnum",
    "__EXPNAME__":     "expname",
    "__STUDENTNAME__": "name",
    "__DIVISION__":    "division",
    "__ROLLNUMBER__":  "roll",
}

EVAL_PLACEHOLDERS = {
    "__EXPNUM__":      "expnum",
    "__EXPTITLE__":    "title",
    "__STUDENTNAME__": "name",
    "__ROLLNO__":      "roll",
    "__DIVBATCH__":    "batch",
    "__COS__":         "cos",
    "__POMAP__":       "pomap",
    "__PSOMAP__":      "psomap",
    "__DATEPERF__":    "dateperf",
    "__DATEEVAL__":    "dateeval",
}

CONFERENCE_LETTER_PLACEHOLDERS = {
    "__LETTERDATE__": "letter_date",
    "__INSTITUTE__": "institute",
    "__ADDRESSEE__": "addressee",
    "__SUBJECT__": "subject",
    "__APPLICANTNAME__": "applicant_name",
    "__STUDENTYEAR__": "student_year",
    "__BRANCH__": "branch",
    "__DEPARTMENT__": "department",
    "__PAPERTITLE__": "paper_title",
    "__COAUTHORS__": "coauthors",
    "__CONFERENCENAME__": "conference_name",
    "__PUBLISHER__": "publisher",
    "__CONFERENCEDATE__": "conference_date",
    "__VENUE__": "venue",
    "__SENDERNAME__": "sender_name",
    "__SENDERDEPT__": "sender_dept",
    "__FORWARDEDBYONE__": "forwarded_by_one",
    "__FORWARDEDBYONEROLE__": "forwarded_by_one_role",
    "__FORWARDEDBYTWO__": "forwarded_by_two",
    "__FORWARDEDBYTWOROLE__": "forwarded_by_two_role",
    "__RECOMMENDEDBY__": "recommended_by",
    "__RECOMMENDEDBYROLE__": "recommended_by_role",
    "__APPROVEDBY__": "approved_by",
    "__APPROVEDBYROLE__": "approved_by_role",
}

CONFERENCE_LETTER_DEFAULTS = {
    "institute": "RAIT, Nerul",
    "addressee": "The Principal",
    "subject": "Application for the submission of conference paper",
    "applicant_name": "Mr. Krishaay Jois",
    "student_year": "BE",
    "branch": "MBA Tech",
    "department": "Department of Computer Science and Engineering",
    "sender_dept": "Department of Computer Science and Engineering, RAIT",
    "forwarded_by_one": "Prof. Gajanan K. Birajdar",
    "forwarded_by_one_role": "R&D In-charge, Dept. of Computer Science and Engg.",
    "forwarded_by_two": "Prof. Sangita Chaudhari",
    "forwarded_by_two_role": "Head of Department, Computer Science and Engg.",
    "recommended_by": "Prof. Vishwesh Vyawahare",
    "recommended_by_role": "Dean (R&D), RAIT",
    "approved_by": "Prof. Mukesh D. Patil",
    "approved_by_role": "Principal, RAIT",
}

_LATEX_SPECIAL = {
    "\\": r"\textbackslash{}",
    "&":  r"\&",
    "%":  r"\%",
    "$":  r"\$",
    "#":  r"\#",
    "_":  r"\_",
    "{":  r"\{",
    "}":  r"\}",
    "~":  r"\textasciitilde{}",
    "^":  r"\textasciicircum{}",
}


def latex_escape(text: str) -> str:
    return "".join(_LATEX_SPECIAL.get(ch, ch) for ch in text)


def _fill(template: str, values: dict, placeholders: dict) -> str:
    result = template
    for token, key in placeholders.items():
        result = result.replace(token, latex_escape(values.get(key, "")))
    return result


def _today_str() -> str:
    return datetime.now().strftime("%d/%m/%Y")


def _find_engine() -> str:
    for engine in ("pdflatex", "lualatex", "xelatex"):
        if shutil.which(engine):
            return engine
    raise RuntimeError("No LaTeX engine found (need pdflatex, lualatex, or xelatex).")


def _compile(tex_source: str, out_path: str) -> dict:
    try:
        engine = _find_engine()
        with tempfile.TemporaryDirectory() as tmp:
            tex_file = os.path.join(tmp, "document.tex")
            with open(tex_file, "w", encoding="utf-8") as f:
                f.write(tex_source)
            proc = subprocess.run(
                [engine, "-interaction=nonstopmode", "-halt-on-error", "document.tex"],
                cwd=tmp, capture_output=True, text=True, timeout=60,
            )
            pdf = os.path.join(tmp, "document.pdf")
            if not os.path.exists(pdf):
                return {"success": False, "error": "LaTeX compilation failed",
                        "details": proc.stdout[-1000:]}
            os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
            shutil.copy(pdf, out_path)
        return {"success": True, "path": out_path}
    except RuntimeError as e:
        return {"success": False, "error": str(e)}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Compilation timed out (60 s)."}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _split_latex_document(doc: str) -> tuple[str, str]:
    """Split a complete LaTeX document into preamble and document body."""
    begin = doc.find(r"\begin{document}")
    end = doc.rfind(r"\end{document}")
    if begin < 0 or end <= begin:
        raise ValueError("Document missing \\begin{document} / \\end{document}.")
    preamble = doc[:begin]
    body = doc[begin + len(r"\begin{document}"):end].strip()
    return preamble, body


def _extract_macro_lines(preamble: str) -> list[str]:
    return re.findall(r"^\\newcommand\{[^\n]+$", preamble, flags=re.MULTILINE)


def _strip_macro_lines(preamble: str) -> str:
    return re.sub(r"^\\newcommand\{[^\n]+\n?", "", preamble, flags=re.MULTILINE)


def _as_renewcommand(lines: list[str]) -> list[str]:
    return [line.replace(r"\newcommand", r"\renewcommand", 1) for line in lines]


def _multi_page(documents: list[str]) -> str:
    """Merge complete LaTeX documents into one valid multi-page document."""
    if not documents:
        raise ValueError("Need at least one document to build a batch PDF.")

    preamble, first_body = _split_latex_document(documents[0])
    first_macros = _extract_macro_lines(preamble)
    common_preamble = _strip_macro_lines(preamble)

    page_chunks = []
    if first_macros:
        page_chunks.append("\n".join(first_macros + [first_body]))
    else:
        page_chunks.append(first_body)

    for doc in documents[1:]:
        page_preamble, body = _split_latex_document(doc)
        macros = _extract_macro_lines(page_preamble)
        chunk_parts = _as_renewcommand(macros) if macros else []
        chunk_parts.append(body)
        page_chunks.append("\n".join(chunk_parts))

    merged_body = "\n\\newpage\n".join(page_chunks)
    return f"{common_preamble}\\begin{{document}}\n{merged_body}\n\\end{{document}}\n"


# -- public API ---------------------------------------------------------------

def render_cover(
    expnum: str, expname: str, name: str, division: str, roll: str,
    serial: str = "", out: str = "cover.pdf",
) -> dict:
    if not COVER_TEMPLATE_PATH.exists():
        return {"success": False, "error": f"Template not found: {COVER_TEMPLATE_PATH}"}
    tex = _fill(COVER_TEMPLATE_PATH.read_text(encoding="utf-8"),
                {"expnum": expnum, "expname": expname, "name": name,
                 "division": division, "roll": roll, "serial": serial},
                COVER_PLACEHOLDERS)
    return _compile(tex, out)


def batch_render_covers(
    documents: list[dict], out: str = "covers_batch.pdf",
) -> dict:
    if not COVER_TEMPLATE_PATH.exists():
        return {"success": False, "error": f"Template not found: {COVER_TEMPLATE_PATH}"}
    raw = COVER_TEMPLATE_PATH.read_text(encoding="utf-8")
    pages = [
        _fill(raw, {"expnum": d.get("expnum",""), "expname": d.get("expname",""),
                    "name": d.get("name",""), "division": d.get("division",""),
                    "roll": d.get("roll",""), "serial": d.get("serial","")},
               COVER_PLACEHOLDERS)
        for d in documents
    ]
    result = _compile(_multi_page(pages), out)
    if result.get("success"):
        result["page_count"] = len(documents)
    return result


def _co_count(cos: str) -> int:
    return len([t for t in re.split(r"[,\s]+", cos.strip()) if t])


def render_eval_sheet(
    expnum: str, title: str, name: str, roll: str,
    serial: str = "", batch: str = "", cos: str = "", pomap: str = "",
    psomap: str = "", dateperf: str = "", dateeval: str = "",
    detailed: bool = False, out: str = "evaluation.pdf",
) -> dict:
    if not EVAL_TEMPLATE_PATH.exists():
        return {"success": False, "error": f"Template not found: {EVAL_TEMPLATE_PATH}"}
    if _co_count(cos) > 1:
        return {"success": False, "error": "Only a single CO is supported (got multiple)."}
    tex = _fill(EVAL_TEMPLATE_PATH.read_text(encoding="utf-8"),
                {"expnum": expnum, "title": title, "name": name, "roll": roll,
                 "serial": serial, "batch": batch, "cos": cos, "pomap": pomap,
                 "psomap": psomap, "dateperf": dateperf, "dateeval": dateeval},
                EVAL_PLACEHOLDERS)
    return _compile(tex, out)


def batch_render_eval_sheets(
    documents: list[dict], detailed: bool = False,
    out: str = "evaluations_batch.pdf",
) -> dict:
    if not EVAL_TEMPLATE_PATH.exists():
        return {"success": False, "error": f"Template not found: {EVAL_TEMPLATE_PATH}"}
    for i, d in enumerate(documents):
        if _co_count(d.get("cos", "")) > 1:
            return {"success": False, "error": f"Only a single CO is supported (document {i} has multiple)."}
    raw = EVAL_TEMPLATE_PATH.read_text(encoding="utf-8")
    pages = [
        _fill(raw, {"expnum": d.get("expnum",""), "title": d.get("title",""),
                    "name": d.get("name",""), "roll": d.get("roll",""),
                    "serial": d.get("serial",""), "batch": d.get("batch",""),
                    "cos": d.get("cos",""), "pomap": d.get("pomap",""),
                    "psomap": d.get("psomap",""), "dateperf": d.get("dateperf",""),
                    "dateeval": d.get("dateeval","")},
               EVAL_PLACEHOLDERS)
        for d in documents
    ]
    result = _compile(_multi_page(pages), out)
    if result.get("success"):
        result["page_count"] = len(documents)
    return result


def render_conference_letter(
    paper_title: str,
    coauthors: str,
    conference_name: str,
    publisher: str,
    conference_date: str,
    venue: str,
    sender_name: str,
    sender_dept: str = "",
    applicant_name: str = "",
    student_year: str = "",
    branch: str = "",
    department: str = "",
    institute: str = "",
    addressee: str = "",
    subject: str = "",
    letter_date: str = "",
    forwarded_by_one: str = "",
    forwarded_by_one_role: str = "",
    forwarded_by_two: str = "",
    forwarded_by_two_role: str = "",
    recommended_by: str = "",
    recommended_by_role: str = "",
    approved_by: str = "",
    approved_by_role: str = "",
    out: str = "conference_letter.pdf",
) -> dict:
    if not CONFERENCE_LETTER_TEMPLATE_PATH.exists():
        return {"success": False, "error": f"Template not found: {CONFERENCE_LETTER_TEMPLATE_PATH}"}

    values = {
        **CONFERENCE_LETTER_DEFAULTS,
        "paper_title": paper_title,
        "coauthors": coauthors,
        "conference_name": conference_name,
        "publisher": publisher,
        "conference_date": conference_date,
        "venue": venue,
        "sender_name": sender_name,
        "sender_dept": sender_dept or CONFERENCE_LETTER_DEFAULTS["sender_dept"],
        "applicant_name": applicant_name or CONFERENCE_LETTER_DEFAULTS["applicant_name"],
        "student_year": student_year or CONFERENCE_LETTER_DEFAULTS["student_year"],
        "branch": branch or CONFERENCE_LETTER_DEFAULTS["branch"],
        "department": department or CONFERENCE_LETTER_DEFAULTS["department"],
        "institute": institute or CONFERENCE_LETTER_DEFAULTS["institute"],
        "addressee": addressee or CONFERENCE_LETTER_DEFAULTS["addressee"],
        "subject": subject or CONFERENCE_LETTER_DEFAULTS["subject"],
        "letter_date": letter_date or _today_str(),
        "forwarded_by_one": forwarded_by_one or CONFERENCE_LETTER_DEFAULTS["forwarded_by_one"],
        "forwarded_by_one_role": forwarded_by_one_role or CONFERENCE_LETTER_DEFAULTS["forwarded_by_one_role"],
        "forwarded_by_two": forwarded_by_two or CONFERENCE_LETTER_DEFAULTS["forwarded_by_two"],
        "forwarded_by_two_role": forwarded_by_two_role or CONFERENCE_LETTER_DEFAULTS["forwarded_by_two_role"],
        "recommended_by": recommended_by or CONFERENCE_LETTER_DEFAULTS["recommended_by"],
        "recommended_by_role": recommended_by_role or CONFERENCE_LETTER_DEFAULTS["recommended_by_role"],
        "approved_by": approved_by or CONFERENCE_LETTER_DEFAULTS["approved_by"],
        "approved_by_role": approved_by_role or CONFERENCE_LETTER_DEFAULTS["approved_by_role"],
    }
    tex = _fill(
        CONFERENCE_LETTER_TEMPLATE_PATH.read_text(encoding="utf-8"),
        values,
        CONFERENCE_LETTER_PLACEHOLDERS,
    )
    return _compile(tex, out)


def batch_render_conference_letters(
    documents: list[dict],
    out: str = "conference_letters_batch.pdf",
) -> dict:
    if not CONFERENCE_LETTER_TEMPLATE_PATH.exists():
        return {"success": False, "error": f"Template not found: {CONFERENCE_LETTER_TEMPLATE_PATH}"}

    raw = CONFERENCE_LETTER_TEMPLATE_PATH.read_text(encoding="utf-8")
    pages = []
    for d in documents:
        values = {
            **CONFERENCE_LETTER_DEFAULTS,
            "paper_title": d.get("paper_title", ""),
            "coauthors": d.get("coauthors", ""),
            "conference_name": d.get("conference_name", ""),
            "publisher": d.get("publisher", ""),
            "conference_date": d.get("conference_date", ""),
            "venue": d.get("venue", ""),
            "sender_name": d.get("sender_name", ""),
            "sender_dept": d.get("sender_dept") or CONFERENCE_LETTER_DEFAULTS["sender_dept"],
            "applicant_name": d.get("applicant_name") or CONFERENCE_LETTER_DEFAULTS["applicant_name"],
            "student_year": d.get("student_year") or CONFERENCE_LETTER_DEFAULTS["student_year"],
            "branch": d.get("branch") or CONFERENCE_LETTER_DEFAULTS["branch"],
            "department": d.get("department") or CONFERENCE_LETTER_DEFAULTS["department"],
            "institute": d.get("institute") or CONFERENCE_LETTER_DEFAULTS["institute"],
            "addressee": d.get("addressee") or CONFERENCE_LETTER_DEFAULTS["addressee"],
            "subject": d.get("subject") or CONFERENCE_LETTER_DEFAULTS["subject"],
            "letter_date": d.get("letter_date") or _today_str(),
            "forwarded_by_one": d.get("forwarded_by_one") or CONFERENCE_LETTER_DEFAULTS["forwarded_by_one"],
            "forwarded_by_one_role": d.get("forwarded_by_one_role") or CONFERENCE_LETTER_DEFAULTS["forwarded_by_one_role"],
            "forwarded_by_two": d.get("forwarded_by_two") or CONFERENCE_LETTER_DEFAULTS["forwarded_by_two"],
            "forwarded_by_two_role": d.get("forwarded_by_two_role") or CONFERENCE_LETTER_DEFAULTS["forwarded_by_two_role"],
            "recommended_by": d.get("recommended_by") or CONFERENCE_LETTER_DEFAULTS["recommended_by"],
            "recommended_by_role": d.get("recommended_by_role") or CONFERENCE_LETTER_DEFAULTS["recommended_by_role"],
            "approved_by": d.get("approved_by") or CONFERENCE_LETTER_DEFAULTS["approved_by"],
            "approved_by_role": d.get("approved_by_role") or CONFERENCE_LETTER_DEFAULTS["approved_by_role"],
        }
        pages.append(_fill(raw, values, CONFERENCE_LETTER_PLACEHOLDERS))

    result = _compile(_multi_page(pages), out)
    if result.get("success"):
        result["page_count"] = len(documents)
    return result
