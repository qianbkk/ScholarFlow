# ScholarFlow v4 — Design

> v3 had a three-column "control-room" layout. The user said it was cluttered,
> no hierarchy, no design feel. This v4 redesigns the layout entirely.
>
> **The principle**: focus-first. The screen shows ONE thing at a time.
> Everything else is a drawer, a footnote, or a keystroke away.

## Theme

Dark by default. Light as an option. Cool chroma on the base, electric cyan
as the only saturated color. Same palette as v3 — the visual system wasn't
the problem, the layout was.

## The screen is one thing at a time

Not a workspace. Not a dashboard. A single page that asks: **what are you
looking at right now?**

- **State 0 — empty.** A large centered input field, a single hint line, the
  brand. Nothing else. This is the home.
- **State 1 — running.** The input collapses to a thin progress line. The
  8-node pipeline animates inline. No papers, no report yet.
- **State 2 — done.** A reading-first Markdown report fills the page. Papers
  are inline footnotes (you read them where the citation is). The citation
  graph is a single-line summary; pressing `⌘G` opens it fullscreen.
- **State 3 — compare.** Two papers side-by-side, fullscreen, dark stage.
  Pressed from the paper footnote card.

The transition between states is animated but quiet — opacity + 4px translate,
220ms ease-out-expo, no bounce.

## Layout

```
┌────────────────────────────────────────────────────────────┐
│  ⌐ ScholarFlow                       [1]→[2]→[3]→[4]→[5]…  │ ← top: 36px, hairline bottom
├────────────────────────────────────────────────────────────┤
│                                                            │
│                                                            │
│                                                            │
│                       ┌──────────────┐                     │  State 0: empty
│                       │              │                     │  Center: 720px column
│                       │   ▶ query    │                     │  96px tall input
│                       │              │                     │
│                       └──────────────┘                     │
│                                                            │
│                       ⌘↵ run  ·  8 nodes  ·  ~30s          │
│                                                            │
│                                                            │
│                                                            │
├────────────────────────────────────────────────────────────┤
│  $0.0024  ·  1,820 tok  ·  00:03  ·  iter 1          idle  │  bottom: 32px footer
└────────────────────────────────────────────────────────────┘
```

The whole page is **one centered column, max-width 720px, generous padding**.
Nothing on the left, nothing on the right. Hairline rules at the top and
bottom for navigation and telemetry.

## State 2 — report view (the heart of the product)

The report is the focus. The screen becomes reading-first:

- Page title (your query) at the top, in `display` (Space Grotesk), 28px.
- Body text in `body` (Inter Tight), 15px, line-height 1.7, max-width 65ch.
- Inline citations as `<sup>` numbers in `--accent`. Hover shows paper title.
- A footnote at the bottom of the report (real `<sup>↩` back-link).
- A `references` section at the end — same mono dense format as v3.
- **The paper card lives inline in the report**, not in a side panel. Each
  citation `[1]` is clickable; clicking expands a small card right there
  in the flow, showing title / authors / abstract preview / open link.
  One card open at a time. Click outside to collapse.

```
┌────────────────────────────────────────────────────────────┐
│  ⌐ ScholarFlow                       [1]✓[2]✓[3]✓[4]✓[5]…  │
├────────────────────────────────────────────────────────────┤
│                                                            │
│                                                            │
│   # Retrieval-Augmented Generation                         │
│                                                            │
│   body body body [¹] body body body body body              │
│   body body body body body body body [²] body              │
│                                                            │
│   ┌─ [1] Lewis et al. 2020 ─────────────────────┐         │  inline paper card
│   │  Retrieval-Augmented Generation for         │         │  click citation
│   │  Knowledge-Intensive NLP Tasks              │         │  to expand
│   │                                             │         │
│   │  NeurIPS · 12,000 cites · final 0.88        │         │
│   │  We develop a general-purpose fine-tuning   │         │
│   │  recipe for RAG — models which combine a    │         │
│   │  pre-trained parametric memory with a       │         │
│   │  non-parametric memory accessed via a       │         │
│   │  dense retriever.                          │         │
│   │                                             │         │
│   │  [open ↗]  [⌘G see in graph]               │         │
│   └─────────────────────────────────────────────┘         │
│                                                            │
│   body body body body body body body body body             │
│   body body body [³] body                                  │
│                                                            │
│   ── references ──                                         │
│   [1] Lewis et al. ...                                     │
│   [2] Schick et al. ...                                    │
│   [3] Bommasani et al. ...                                 │
│                                                            │
│                                                            │
├────────────────────────────────────────────────────────────┤
│  ⌘G graph (12 nodes)  ·  ⌘P papers  ·  ⌘E export  ·  $0.0024  │
└────────────────────────────────────────────────────────────┘
```

This is the **v1/v2/v3 mistake** corrected: papers aren't a side panel you
look away from. They live where you read them.

## State 3 — graph fullscreen

Press `⌘G` (or click the footer link). The page fades out, the graph
fades in, fullscreen. Same dark base, no panel chrome. Title at the
top: the query, the paper count, the edge count. The graph centered.
Press `Esc` to return to the report.

This is **v3's "right rail" promoted to a fullscreen mode** — and made
optional, so the report doesn't compete with it for visual attention.

## State 2 alternative — papers drawer

Press `⌘P`. A 360px right-edge drawer slides in over the report (not
push, not overlay, but a thin underlay shadow), showing the full ranked
list with paper metadata. Click a paper to scroll the report to that
citation. Click outside or press `Esc` to close.

## Empty state design

The empty state is the home. It should feel like opening a beautiful
notebook:

- Centered, 720px column.
- Logo / brand mark at the top (small, mono caps).
- A 96px tall input field with no border, just a 1px bottom hairline.
  Inset `▶` glyph in `--accent` at the left.
- One hint line below: `⌘↵ run · 8 nodes · ~30s`.
- That's it. No tagline, no "what is this", no marketing copy. The
  tool is the product.

## What v4 removes from v3

- ✗ Three-column layout (left / center / right panels).
- ✗ Always-visible 8-node pipeline strip.
- ✗ Side-by-side compare as a 2-column bottom panel.
- ✗ Tabular-figures-everywhere.

## What v4 keeps from v3

- ✓ Dark by default, electric cyan accent.
- ✓ Mono + sans only (no serif).
- ✓ Single module-scope reactive store.
- ✓ The 8-node pipeline shape and the API contract.
- ✓ The bottom telemetry footer (cost / tokens / elapsed / iter).

## Anti-patterns (repeated for emphasis)

- ❌ No three-column workspace. No left rail. No right rail.
- ❌ No "show all the things" mode. One thing at a time.
- ❌ No side-stripe borders, gradient text, glassmorphism, hero-metric tiles,
  identical card grids, eyebrow text on every section, "01/02/03" scaffolding.
- ❌ No `border: 1px solid X` + box-shadow ghost cards.
- ❌ No `border-radius: 24px+`. Caps at 4px on inputs, 8px on cards.
- ❌ No hover scale on images.
- ❌ No cream / sand / paper / parchment body bg.
- ❌ No serif display font.
- ❌ No library red / terracotta / oxblood accent.
- ❌ No purple-to-blue gradients.
- ❌ No gray text on a colored background.

## Accessibility

- WCAG 2.1 AA. Body text ≥ 4.5:1.
- Color-blind safe viridis on the citation graph.
- Every status indicator pairs color with an icon or text label.
- Keyboard navigable end-to-end: Tab through, Enter to expand, Esc to
  close, `⌘K` to focus input, `⌘G` for graph, `⌘P` for papers, `⌘E` for
  export.
- `prefers-reduced-motion: reduce` honored.
- Light theme available.
