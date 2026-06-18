# ScholarFlow v3 — Design

> Different from v1/v2 by intent. Where v1 was a parchment-and-serif workbench,
> v3 is a dark graphite control room. The aesthetic is "what a senior engineer
> would build for themselves on a Friday night", not "what a design agency
> thinks a research tool should look like."

## Theme

**Dark default, light optional.** Dark mode isn't a theme — it's the canonical surface. The light theme is a thoughtful alternative, not the starting point.

Base surface: deep graphite (`oklch(15% 0.005 240)`) — not pure black, not warm gray. Slight cool chroma away from neutral to avoid the "after-hours surveillance" feel of `#0a0a0a`. Surface is layered: the page sits on a slightly lighter card, panels sit on the page.

The accent: **electric cyan** (`oklch(78% 0.16 200)`) — used as the only saturated color in the UI. Not a brand blue, not a SaaS purple. Functional, high-contrast, color-blind safe. Used for: focus, primary action, current node, citation marker.

## Color

OKLCH throughout. No hex anywhere outside this file.

### Dark (default)

| Token | Value | Purpose |
|---|---|---|
| `--base` | `oklch(15% 0.005 240)` | Page background |
| `--surface-1` | `oklch(19% 0.005 240)` | Panels, sidebars |
| `--surface-2` | `oklch(23% 0.005 240)` | Hover, active row, paper card |
| `--ink-1` | `oklch(94% 0.005 240)` | Primary text |
| `--ink-2` | `oklch(70% 0.005 240)` | Secondary text, labels |
| `--ink-3` | `oklch(50% 0.005 240)` | Muted text, hints |
| `--rule` | `oklch(28% 0.005 240)` | Hairlines, dividers |
| `--rule-strong` | `oklch(38% 0.005 240)` | Active borders, focus rings |
| `--accent` | `oklch(78% 0.16 200)` | Electric cyan. The only saturated color. |
| `--accent-soft` | `oklch(28% 0.10 200)` | Tinted background for active states |
| `--signal-ok` | `oklch(70% 0.13 145)` | Done, healthy |
| `--signal-warn` | `oklch(78% 0.13 75)` | Rate-limited, cost warning |
| `--signal-err` | `oklch(68% 0.18 25)` | Failed, error |

### Light (alternative)

| Token | Value | Purpose |
|---|---|---|
| `--base` | `oklch(98% 0.002 240)` | Page |
| `--surface-1` | `oklch(96% 0.002 240)` | Panels |
| `--surface-2` | `oklch(92% 0.002 240)` | Hover, active |
| `--ink-1` | `oklch(20% 0.005 240)` | Primary |
| `--ink-2` | `oklch(40% 0.005 240)` | Secondary |
| `--ink-3` | `oklch(55% 0.005 240)` | Muted |
| `--rule` | `oklch(86% 0.002 240)` | Hairlines |
| `--accent` | `oklch(45% 0.16 200)` | Deeper cyan for light bg |
| `--accent-soft` | `oklch(94% 0.04 200)` | Active bg |

### Forbidden

- Cream / sand / paper / parchment body backgrounds (the v1 trap).
- Library red, terracotta, oxblood, leather-bound colors (the v2 trap).
- Purple-to-blue gradients. Glassmorphism. Identical card grids.
- Side-stripe borders (the previous "selected" indicator). Use 1px top + bottom hairline + a 2px left bracket in `--accent` for active, never a decorative stripe.
- Gradient text. Hero-metric tiles. Eyebrow text on every section. "01/02/03" scaffolding.

## Typography

- **Display / Headings**: `Space Grotesk` (variable weight). Geometric, technical, distinct from any prior v1/v2. Used sparingly: page title, panel headers, paper titles in the report.
- **Body / UI**: `Inter Tight` (variable weight). Tight, dense, scannable. Used for everything else: controls, labels, paragraphs.
- **Mono / Data**: `JetBrains Mono` (variable weight). Used for IDs, tokens, costs, latencies, code, BibTeX. Tabular figures on by default.
- **NO serif**. v1/v2 used Source Serif 4 as a category reflex ("academic = serif"). v3 is mono + sans only.

Sizes are denser than v1/v2: body 14px, label 12px, micro 11px. Heading scale stops at 28px — no hero text.

## Motion

- **Default easing**: `cubic-bezier(0.16, 1, 0.3, 1)` (ease-out-expo).
- **Duration**: 120-180ms for micro (button press, hover), 240ms for panel transitions, 0ms for the citation graph (D3 handles its own physics).
- **No bounce. No elastic. No spring overshoot.**
- **No "stagger reveal" on every section.** One well-orchestrated entrance on the first load; subsequent updates are instant.
- **Reduced motion**: crossfade only, or instant.

## Layout

Single-page workspace. No home, no project list, no settings drawer.

```
┌──────────────────────────────────────────────────────────────────┐
│  ⌐ ScholarFlow                                  [P] [L] [·]      │ ← top: app + theme + status
├──────────────────────────────────────────────────────────────────┤
│  ▎  query_decomposer  →  query_refiner  →  …  →  synthesis       │ ← pipeline strip (always)
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ▶ Run a query. . .  [⌘↵]                                       │ ← command bar (large)
│                                                                  │
├────────────────┬──────────────────────────────┬─────────────────┤
│  RESULTS  12   │  REPORT                      │  GRAPH          │
│                │                              │                 │
│  [01] paper a  │  #  Report Title             │  (force layout) │
│  [02] paper b  │  body body body. [1]         │                 │
│  [03] paper c  │                              │                 │
│  ...           │  References                  │  12 nodes · 18  │
│                │  [1] paper a                 │  edges          │
│                │  [2] paper b                 │                 │
├────────────────┴──────────────────────────────┴─────────────────┤
│  $0.0241  ·  4,231 tok  ·  00:42  ·  iter 1                     │ ← footer: live cost
└──────────────────────────────────────────────────────────────────┘
```

Three regions, but **denser than v1/v2**: panels are tightly packed, no internal padding bloat, panel headers are one row of small mono caps, panel content goes edge-to-edge.

## Components

- **TopBar**: app name + theme toggle + connection dot. ~36px tall.
- **PipelineStrip**: always-visible row of 8 nodes. Active node is `--accent` text + a left bracket. Done node is a checkmark glyph in `--signal-ok`. Pending is `--ink-3` text. Connector arrows between nodes. This is the differentiator — the user always sees the system working.
- **CommandBar**: the largest interactive element. Wide, with a single-line input, a "▶" submit affordance, and a `⌘↵` hint. On focus, expands 4px to show a thin `--rule-strong` underline.
- **ResultsPanel**: dense list of papers. Each row: index `01-99` in mono, title in sans, authors in mono, year + venue + cites in mono. Hairline between rows. No card. Selected row: 2px left bracket in `--accent` + `--surface-2` bg.
- **ReportPanel**: rendered Markdown. Body 14px. Headings in Space Grotesk (no serif). Inline citations as `<sup>` numbers in `--accent` linking to a references section at the bottom. References in mono, dense, no card padding.
- **GraphPanel**: D3 force layout. Viridis ramp on year. Node hover highlights 1-hop neighborhood. ~320px wide.
- **Footer**: live cost counter, token count, elapsed time, iteration. Tabular figures. 32px tall. Always visible.
- **CompareBar**: when 2 papers are selected, a 240px-tall panel slides up from the footer (push, not overlay) showing side-by-side metadata + abstract. Esc or click outside closes.

## Anti-patterns (hard bans, repeated from v2 with additions)

- ❌ Side-stripe borders (`border-left: 4px solid`).
- ❌ Gradient text.
- ❌ Glassmorphism as a default card style.
- ❌ Hero-metric tiles.
- ❌ Identical card grids.
- ❌ Eyebrow text on every section.
- ❌ Numbered section markers (01/02/03) above sections.
- ❌ `border: 1px solid X` + `box-shadow: 0 Npx 16px+` on the same element.
- ❌ `border-radius: 24px+` on cards. Max 6px on panels.
- ❌ Sketchy SVG illustrations.
- ❌ `repeating-linear-gradient` stripe backgrounds.
- ❌ Hover scale on images.
- ❌ Cream / sand / paper / parchment body bg.
- ❌ Serif display font (the v1/v2 trap).
- ❌ Library red / terracotta / oxblood accent (the v2 trap).
- ❌ Purple-to-blue gradients (the SaaS trap).
- ❌ Gray text on a colored background.
