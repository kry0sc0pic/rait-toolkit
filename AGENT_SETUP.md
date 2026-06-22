# Agent Setup Guide

This file is for the AI agent. Read it at the start of every session.

---

## Who you are helping

A D.Y. Patil RAIT student. You have access to two separate systems via this MCP server:

1. **MyDy LMS** (`mydy.dypatil.edu`) — courses, attendance, files, hit-rate maxxer
2. **UniClaIRE student portal** (`studentportal.universitysolutions.in`) — GPA, SGPA, marksheets

---

## First thing to do every session

Call `get_cached_info` immediately. It returns:
- MyDy email (if set)
- UniClaIRE portal regno (mobile login number)
- USN / roll number (e.g. `23MTCO001`) — auto-populated after first `get_gpa` call
- Which credential sets are configured

Use this to avoid asking the user for information you already have.

---

## Credential rules

Credentials are stored locally at `~/.lms-buddy/credentials.json`. They never leave the machine except as authentication to their respective portals.

**Two separate domains — do not mix them up:**

| Domain | Login field | What it's for |
|--------|------------|---------------|
| MyDy LMS | Email (`your@dypatil.edu`) | All LMS tools |
| UniClaIRE portal | Mobile/registration number | `get_gpa` only |

**The UniClaIRE login is a mobile number, NOT the roll number.** The roll number (USN like `23MTCO001`) is fetched from the portal after login — it is a different value.

**If credentials are missing:**
- Use `AskFollowupQuestion` to ask for them — never just print a text instruction
- Tell the user their credentials are stored locally and never sent anywhere except the respective portal
- Call `set_mydy_credentials` or `set_portal_credentials` immediately after receiving the answer

---

## Response tracking (diffs)

Live-data tools (`list_subjects`, `get_overall_attendance`, `get_hitrates`, `get_gpa`, etc.) automatically compare each response to the previous one and prepend:

- `[Changes since last read]` + a unified diff — when data has changed
- `[No changes since last read]` — when nothing changed

Use this to tell the user what has changed without re-reading everything.

---

## PDF rendering

Tools: `render_cover_pdf`, `batch_render_covers_pdf`, `render_eval_sheet_pdf`, `batch_render_eval_sheets_pdf`

- All require `pdflatex` / `lualatex` / `xelatex` on PATH
- All **automatically open the PDF** in the system viewer after saving — no need to call `open_pdf` manually unless opening a file at a custom path
- Default output is the current directory; pass `out=` to control the path

Student info needed for cover pages:
- `name` — full name
- `division` — e.g. `MBA Tech`
- `roll` — roll number (the USN from `get_cached_info`)
- `expnum` — experiment number
- `expname` — experiment title

If any of these are in `get_cached_info`, use them directly without asking.

---

## Lab writeup

Use the `journal_writeup` MCP prompt (available in Claude Desktop's prompt picker) or the `/lab-writeup` skill (Claude Code).

The prompt returns detailed writing instructions. Key rules it enforces:
- Two prose paragraphs for Theory — no bullets, no code
- 4–7 imperative steps for Procedure
- Do not invent technical facts — ask if anything is unclear
- LaTeX output uses `references/preamble-simple.tex`

---

## Updating the server

Call `self_update` to `git pull` and restart the server process. Claude Code/Desktop will reconnect automatically on the next tool call.

---

## Assignment submission

### Workflow (strict order)

1. Call `get_assignments(course_id)` — lists all assignments with due date, submission status, and grade. This also **registers the URLs as seen** so the submit guardrail allows them.
2. Call `submit_assignment(assign_url, file_path)` — uploads and finalises.

**Never call `submit_assignment` without a prior `get_assignments` call** — it will raise an error if the URL hasn't been registered.

### `force` parameter

`submit_assignment` has a `force=False` default. When `force=False`:
- If the assignment is already submitted, the call returns `already_submitted` and does nothing.

When `force=True`:
- The existing submission is overwritten with the new file.
- **You must NEVER set `force=True` on your own initiative.** Only use it when the user has explicitly said they want to replace/overwrite their submission (e.g. "replace my submission", "re-submit with the new file", "force submit").
- Setting `force=True` without explicit user consent is a violation that could cause unrecoverable data loss.

### Blank placeholder PDF

A blank placeholder PDF is kept at `~/.lms-buddy/blank_submission.pdf` (auto-generated on first use). When `max_hitrate` detects pending assignment activities with no submission, it will prompt you to ask the user whether they want a blank PDF submitted to fulfil the completion requirement. Use `AskFollowupQuestion` for this — do not submit automatically.

---

## Tool reference summary

| Category | Tools |
|----------|-------|
| LMS | `list_subjects`, `list_files`, `download_file`, `get_hitrates`, `max_hitrate`, `get_overall_attendance`, `get_course_attendance`, `get_semesters` |
| Assignments | `get_assignments`, `submit_assignment` |
| GPA | `get_gpa` |
| PDF | `render_cover_pdf`, `batch_render_covers_pdf`, `render_eval_sheet_pdf`, `batch_render_eval_sheets_pdf` |
| Utility | `get_cached_info`, `set_mydy_credentials`, `set_portal_credentials`, `open_pdf`, `self_update` |
