# ScholarFlow v3 — Product

> A complete rewrite. Not an iteration on v1/v2.
> The first version tried to look like a JSTOR reader. That was a category reflex.
> This one looks like a control room.

## Register

product

## Users

Same audience: academic researchers running iterative literature surveys. But framed differently: they're not readers, they're **operators**. They run a query, watch the pipeline light up, and grab what they need. The job isn't contemplation — it's triage.

## Product Purpose

A multi-agent research tool. You ask a question. Eight nodes light up in sequence: decompose, refine, search, score, extract, gap, critique, synthesize. The output is a cited report and a citation graph you can read, export, and act on.

Success means: a researcher runs 6-10 queries in a session without fatigue, can compare papers without leaving the page, and trusts the cost counter because the system shows every cent.

## Brand Personality

- **Operational.** This is a tool, not a book. The visual register is closer to Linear / Raycast / a flight deck than to a library.
- **Dense without clutter.** Information first, decoration never. Heavy use of tabular figures and mono.
- **Dark by default.** Long sessions, late nights, ambient-light reduction. Dark isn't a theme — it's the home.
- **Honest telemetry.** Cost, tokens, latency, node status. Visible by default, not buried in a panel.

Three words: **operational, dense, candid**.

## Anti-references

- **Not v1 / Not v2.** v1 was a 13-useState three-column scholar-workbench. v2 was the same thing with a serif font. v3 is neither.
- **Not a "scholar's library".** No parchment, no leather, no cream backgrounds, no Source Serif display fonts, no library red.
- **Not a SaaS dashboard.** No purple-to-blue gradients, no glassmorphism, no hero-metric tiles, no "01 / 02 / 03" numbered eyebrows.
- **Not a chatbot.** No chat bubbles, no avatars, no greeting copy. The input is a command bar, not a conversation.
- **Not Notion.** No emoji decoration, no "click to add", no card-everything.
- **Not a typical IDE.** No file tree, no tabs across the top, no code-chrome.

## Design Principles

1. **One screen, one job.** The page IS the workspace. No home page, no project list, no settings drawer. You arrive, you query, you leave with a report.
2. **The pipeline is the system.** Eight nodes are visible at all times as a status strip. The user watches the system work — that's the product's differentiator, not a hidden feature.
3. **Tabular figures everywhere.** Token counts, costs, latencies, IDs — all tabular-nums mono. The eye should be able to scan a column without recalibrating.
4. **Single saturated accent.** One color, used sparingly. Not a rainbow. Not semantic red/green only. The accent is the only color that isn't grayscale or a viridis ramp.
5. **Keyboard-first, mouse-optional.** Every action reachable. The mouse is for reading the report; the keyboard is for running the work.
6. **Density is honesty.** Showing 12 papers on a screen with no chrome is more honest than padding 3 with card backgrounds.

## Accessibility & Inclusion

- WCAG 2.1 AA. Body text ≥ 4.5:1 on the dark base.
- Color-blind safe for the citation graph (Viridis ramp, never red/green only).
- Every status indicator pairs color with an icon or text label.
- Keyboard navigable end-to-end. No hover-only affordances.
- `prefers-reduced-motion: reduce` honored.
- Light theme available as an option, not the default.
