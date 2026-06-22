---
name: lab-writeup
description: Generate a LaTeX lab-record / experiment write-up in the user's established academic format. Use whenever the user gives details, code, an aim, or a topic for one or more lab experiments / practicals and wants a formal write-up, lab manual entry, or record-book page — phrases like "write up this experiment", "make a lab record for X", "add an experiment on Y", "format this as a practical", or when they paste experiment code/notes and ask for the LaTeX. Produces a standalone compilable .tex file following the fixed section pattern (Aim, Software/Hardware Required, Theory, Algorithm/Procedure, Conclusion). Use even if the user doesn't say the word "LaTeX" but clearly wants a structured experiment writeup.
---

# Lab Write-up Generator

Generates LaTeX experiment write-ups in a consistent academic lab-record format. The user supplies a topic, aim, code, or rough notes for an experiment; you produce a polished, compilable `.tex` write-up that matches the established pattern.

## The pattern (every experiment follows this)

Each experiment is a self-contained block with these sections **in this order**:

1. **Title** — a centered, bold experiment heading (the experiment name, not "Experiment N:" inside the title text unless the user wants numbering).
2. **Aim** — one sentence. What the experiment does. Often just restates the title.
3. **Software Required** / **Hardware / Software Required** — a comma-separated list of tools (languages, libraries, environments, datasets). Pick the label that fits the domain.
4. **Theory** — **exactly two prose paragraphs.** First paragraph: the core concept and how it works. Second paragraph: mechanism details, variants, metrics, or where it's used in practice. Plain explanatory prose. No bullet lists here. No code. Optionally include one display-math equation if the topic is mathematical (loss functions, distances, objectives).
5. **Algorithm / Procedure** — a short numbered list (4–7 steps), each step one imperative line. May be preceded by an `\textbf{Algorithm:}` display equation and/or followed by `\textbf{Design:}` / `\textbf{Analysis:}` notes when the topic warrants (architecture choices, what to watch for).
6. **Conclusion** / **Conclusions** — one or two sentences restating what the experiment demonstrated.

Between experiments: `\newpage`.

### Style rules
- Theory paragraphs are genuinely explanatory and self-contained — write fresh prose for the actual topic, never boilerplate. Two paragraphs, no more.
- Procedure steps are terse and imperative ("Load the dataset.", "Compute similarity between users.").
- Keep `noitemsep` lists tight.
- Do NOT include filled-in results tables. Keep Results/Output Analysis sections **commented out** as empty templates for the student to fill by hand. Only include a results table (commented out) if the user asks for one or the experiment clearly produces tabulated metrics.
- Use `\texttt{}` for code identifiers, function names, and weighting syntax inline.

## Preamble (one fixed style)

Always use `references/preamble-simple.tex`. One format only:
- `titlerule` section headings, with the experiment title as `\section*{Experiment N: ...}`.
- Field labels (Aim, Software Required, Theory, etc.) are **bold inline labels** (`\textbf{...}\\`), not separate headings.
- No `fancyhdr`, no running headers, no `\expheader` macro.

Equations are still fine when a topic needs them — `amsmath` can be added to the preamble if an experiment uses display math — but the page/heading style stays this single simple format.

## Workflow

1. Read the preamble file from `references/`.
2. For each experiment the user describes, write the block following the pattern above. Generate real Theory prose for the specific topic — this is the main value-add. Don't pad; two solid paragraphs.
3. Assemble: preamble + experiment blocks separated by `\newpage` + `\end{document}`.
4. Write the `.tex` to `/mnt/user-data/outputs/` and present it.
5. If the user has multiple experiments, number them consistently and keep one continuous document unless they ask for separate files.

## Handling user input

- **They give code**: derive the Aim, infer the Software Required from imports/libraries, and write Theory explaining the technique the code implements. Don't paste the code into Theory. If they want the code shown, add a `\section*{Code}` block using `listings` (add `\usepackage{listings}` to the preamble) — but only when asked.
- **They give just a topic/title**: write the whole thing from domain knowledge.
- **They give rough notes**: structure them into the pattern, expanding Theory into two proper paragraphs.
- **Multiple experiments at once**: do them all in one document.

Match the user's domain register. Keep it formal and academic. The goal is a write-up that looks like it belongs in the same lab manual as everything else.
