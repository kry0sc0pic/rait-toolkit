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
from pathlib import Path
from typing import Any

_TEMPLATES_DIR = Path(__file__).parent / "templates"

TEMPLATE_PATH         = _TEMPLATES_DIR / "template.tex"
GENERAL_TEMPLATE_PATH = _TEMPLATES_DIR / "template_general.tex"
EVAL_TEMPLATE_PATH    = _TEMPLATES_DIR / "eval_template.tex"

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
    serial: str = "", general: bool = True, out: str = "cover.pdf",
) -> dict:
    tmpl = GENERAL_TEMPLATE_PATH if general else TEMPLATE_PATH
    if not tmpl.exists():
        return {"success": False, "error": f"Template not found: {tmpl}"}
    tex = _fill(tmpl.read_text(encoding="utf-8"),
                {"expnum": expnum, "expname": expname, "name": name,
                 "division": division, "roll": roll, "serial": serial},
                COVER_PLACEHOLDERS)
    return _compile(tex, out)


def batch_render_covers(
    documents: list[dict], general: bool = True, out: str = "covers_batch.pdf",
) -> dict:
    tmpl = GENERAL_TEMPLATE_PATH if general else TEMPLATE_PATH
    if not tmpl.exists():
        return {"success": False, "error": f"Template not found: {tmpl}"}
    raw = tmpl.read_text(encoding="utf-8")
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


def render_eval_sheet(
    expnum: str, title: str, name: str, roll: str,
    serial: str = "", batch: str = "", cos: str = "", pomap: str = "",
    psomap: str = "", dateperf: str = "", dateeval: str = "",
    detailed: bool = False, out: str = "evaluation.pdf",
) -> dict:
    if not EVAL_TEMPLATE_PATH.exists():
        return {"success": False, "error": f"Template not found: {EVAL_TEMPLATE_PATH}"}
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
