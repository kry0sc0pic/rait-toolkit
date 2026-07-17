---
name: latex-academic-notes
description: Turns lecture slides, course PPTs, textbook notes, or a question bank into a polished LaTeX PDF study document (exam-answer key, prep notes, revision guide) with a consistent style — colored title page, real TikZ diagrams (never image placeholders), longtable tables, key-point call-out boxes. Use whenever the user wants course material turned into a formatted study PDF, "prep notes"/"revision notes," an answer key for a question bank, or asks that slides/notes be "converted," "written up," or "compiled" into a document — especially when they mention modules, units, lectures, diagrams, or want "everything"/"all topics" covered, not just a subset. Also trigger for a condensed or full variant of the same material. Equally about a verification workflow (cross-checking every topic in the source so nothing is silently dropped) as it is about LaTeX styling — use it whenever thoroughness against source material matters, not only for formatting.
---

# LaTeX Academic Notes

Two things make this kind of document hard to get right, and both matter more than the LaTeX syntax itself:

1. **Coverage** — course PPTs and question banks are long and easy to skim past. A document that silently drops a lecture's worth of content (or answers the question bank but ignores everything else in the slides) looks complete but isn't. Most of the effort in this skill goes into *proving* coverage, not assuming it.
2. **Diagrams that are actually diagrams** — when a user asks for "diagrams," a dashed box that says "insert diagram here" is not a diagram. Draw the real thing in TikZ. It compiles, it's free, and it's usually faster than describing what a placeholder should contain.

Follow the phases below in order. Don't jump to writing LaTeX before the research phase is done — a beautifully styled document built on an incomplete outline just means redoing the work later.

## Phase 1: Research and build a topic checklist

If the user attached or references source material (PDFs of slides, notes, a syllabus), your job before writing a single line of LaTeX is to turn that material into an explicit list of topics that must appear in the output.

1. **Extract full text, not a skim.** Use `pdftotext -layout file.pdf -` (via bash) on every source file. Don't rely on a quick glance at the first page — course slide decks routinely bundle multiple lecture ranges into one PDF, and later sections are easy to miss entirely if you stop reading early. If a file is large (like an 80-page deck), read it in chunks (`sed -n 'START,ENDp'`) until you've actually seen all of it, not just the first third.
2. **Look for the deck's own index.** Most course slides open with an "Index" or table-of-contents slide listing lecture numbers and titles — treat this as the ground-truth checklist for that file, not a suggestion. Note that a single PDF sometimes contains more than one lecture range concatenated together (e.g. a file titled for Lectures 5–6 may continue on into Lectures 7–8 partway through) — always check the *end* of a file for a second index/section, don't assume the file matches only its opening title.
3. **Pull every slide title systematically** as a second check, in case the index is incomplete. Slide decks converted to text usually leave a predictable footer pattern like a page number followed by "Lecture N: ..." or "Module N: ...". Grep for that footer pattern and take the non-blank line immediately before each match — that's an approximate slide title. Dedupe the list. This surfaces sections an index slide might have compressed into one line (e.g. "Lecture 15" covering five separate operations).
4. **Ground specific claims in the source, not general knowledge.** Courses often use a specific named framework that differs from the generic textbook version (e.g. a specific instructor's "4 business drivers" may be Volume/Velocity/Variability/Agility, not the generic list you'd produce from training knowledge). When source material is provided, prefer what it says over what you'd otherwise write from memory, and use general/textbook knowledge only to fill in gaps the source doesn't cover.
5. **Build the outline against the checklist**, not the other way around — draft section headers from the lecture/topic list first, so it's visually obvious if something has no home yet.

If the user gave you a specific question bank (a fixed list of questions to answer) *and* the underlying slides/notes, treat these as two different deliverables unless told otherwise: answering the question bank is necessary but not sufficient for "cover everything." After drafting, do a second pass across the full source material (not just the question bank) to check for anything not yet reflected — new sections, extra worked examples, named frameworks, diagrams the deck itself drew. Don't assume the question bank is a complete proxy for the source material.

## Phase 2: Gap-check before showing the result

Before treating the document as done, re-derive the topic list one more time and diff it against what you actually wrote:

- Re-grep the source for domain keywords that should appear somewhere (e.g. for a databases course: "shard", "replication", "consistent hashing"; for a networking course: whatever the deck's own vocabulary is) and confirm each either appears in your draft or was a deliberate, general-knowledge supplement clearly outside the source.
- If you find a gap, don't just append a paragraph — find where it belongs structurally (it usually corresponds to a specific lecture/section you can now name) and insert it there, in sequence, matching the source's own lecture ordering.
- It's fine, and expected, to tell the user candidly if a first pass missed something once you find it during this check — that's the point of doing the check.

## Phase 3: Write the LaTeX

Use `assets/preamble.tex` as the starting point for every new document — it's the exact reusable preamble (packages, colors, TikZ styles, table column types, title page skeleton) developed and battle-tested across this style. Don't rewrite it from scratch each time.

**Structure conventions:**
- Title page (course/topic name, subtitle, date, one-paragraph scope description) + `\tableofcontents` + `\newpage`.
- One `\section{}` per module/unit, `\subsection{}` per lecture/topic/question. Section headings get a colored "Module N" style prefix; see the preamble.
- Prose in bullet-point/definition style for notes (dense, scannable) vs. fuller paragraph style for formal Q&A answers — match whichever the user asked for.
- **End the document with the last content section — nothing after it.** The one-paragraph scope description belongs only on the title page. Do not add a closing "Summary," "Conclusion," "What This Document Covers," or similar meta/recap page at the end restating what topics were included — the user asked for notes/an answer key, not a report about the notes. If a wrap-up genuinely feels necessary, that's a sign a topic's coverage should be made clearer within its own section instead, not addressed after the fact in a trailing page.

**Tables:** use `longtable` (not `tabular`) so tables can break across pages, `booktabs` (`\toprule`/`\midrule`/`\bottomrule`, never plain `\hline`), and the custom `L{width}` / `C{width}` column types from the preamble for readable wrapped text instead of cramped default columns. Use `\multirow` when several rows share one grouped value (e.g. a multi-step worked example where one final answer spans several input rows).

**Diagrams — always real TikZ, never placeholders:** read `references/diagram-patterns.tex` for ready-to-adapt code covering the recurring archetypes: a linear pipeline (input → stage → stage → output), a hub-and-spoke map (one core node with satellites around it), a master/slave or client/server architecture, side-by-side comparison panels, a triangle/trade-off diagram (e.g. CAP theorem style "pick 2 of 3"), and a ring/cycle diagram (e.g. consistent hashing). Pick the closest archetype and adapt labels/counts rather than inventing new TikZ from a blank page each time. Every diagram gets a caption via `\diagramcap{...}` (defined in the preamble) directly underneath it, phrased as "Fig.: <description>".

**Common mistakes to avoid** (each of these caused a real compile failure or visual bug while developing this style — save yourself the round trip):
- `tcolorbox` does not have a `dashed` or `dash pattern` key in this configuration — for a dashed-border box, draw it manually with plain TikZ (`\draw[dashed, ...] rectangle`) instead of reaching for tcolorbox options.
- A `\\` line break only works inside a TikZ node's text if that node style sets `align=center` (or similar) — without it, LaTeX throws a confusing "missing \item" error that has nothing to do with what you actually got wrong.
- Long unbroken inline `\texttt{...}` (a SQL query, a JSON blob, a long identifier) will not wrap and causes an overfull line that visibly pokes into the margin — manually insert line breaks inside the `\texttt{}`/`quote` block for anything longer than roughly half the text width.
- When laying out multiple small boxes with TikZ's `positioning` library (`above=of x`, `right=of x`, etc.), two adjacent groups placed too close together will make their labels overlap — when in doubt, give explicit absolute coordinates (`node ... at (x,y)`) rather than chained relative positioning once a diagram has more than about 6 nodes, since it's much easier to reason about actual spacing that way.
- Keep an eye on total row width in `longtable`: three columns wider than roughly `\textwidth` minus a small margin for cell padding will overfull by a few points — err on the narrow side (leave a few mm of slack) rather than maximizing column width.

## Phase 4: Compile and verify

1. Run `pdflatex -interaction=nonstopmode -halt-on-error file.tex` **twice** (the second pass resolves the table of contents and cross-references) via the bash tool.
2. Grep the log for `Error`, `Overfull`, and `Underfull`. A handful of sub-5pt overfull warnings on inline code/acronyms is normal and invisible in practice; anything larger, or any actual `Error`, needs fixing before moving on.
3. Don't just trust that a diagram-heavy page "probably looks fine." Render suspect pages to PNG (`pdftoppm -png -r 130 -f <page> -l <page> file.pdf out`) and actually look at them with the image-reading tool, especially any page with more than 2–3 TikZ nodes or two diagrams close together. This is how overlapping labels and clipped text actually get caught — logs don't report visual overlap.
4. Clean up scratch files (`.aux`, `.log`, `.out`, `.toc`, rendered PNGs) once the PDF is confirmed good, keeping only the final `.tex` and `.pdf`.
5. Share both the compiled PDF and the `.tex` source with the user so they can tweak it further themselves if needed.

## Reference files

- `assets/preamble.tex` — the full reusable LaTeX preamble: packages, brand colors, section/header styling, the `diagramcap` macro, the `keybox` tcolorbox environment, and the TikZ node/arrow styles (`core`, `box`, `sbox`, `tag`, `arr`, `darr`) referenced throughout this file. Copy this in wholesale and build the document body below it.
- `references/diagram-patterns.tex` — worked, compilable TikZ snippets for each recurring diagram archetype described above, ready to copy and relabel.
