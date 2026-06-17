# Design

## Theme

**Restrained, dark-leaning, paper-ink contrast.** Light-mode default with a true ink-on-paper feel: very high contrast text on a slightly off-white surface (NOT a cream/sand tinted body — that is the 2026 AI default). Dark mode as an option, not the default. Mid-tone neutrals (not the gray-ramp default) tinted very slightly toward the brand's own hue.

The visual register is closer to a JSTOR PDF reader or a Tufte book margin than to a SaaS dashboard. We use a strong display serif for headings, a humanist sans for body, and a monospace for IDs/citations/code.

## Color Palette

Built around a deep ink (`--ink`) and a near-white paper (`--paper`). Single accent: a saturated **library red** (think classic leather-bound book spine or a Princeton crimson — NOT a generic SaaS blue or purple).

| Token | Light | Dark | Purpose |
|---|---|---|---|
| `--paper` | `oklch(98% 0.005 80)` | `oklch(14% 0.008 80)` | App background. Slight chroma toward the ink hue, not toward warm/cool by reflex. |
| `--ink` | `oklch(18% 0.01 280)` | `oklch(94% 0.005 80)` | Primary text. Body, headings. |
| `--ink-2` | `oklch(38% 0.012 280)` | `oklch(75% 0.008 80)` | Secondary text. Captions, metadata. |
| `--rule` | `oklch(82% 0.005 80)` | `oklch(28% 0.008 80)` | Hairline rules, borders. 1px max. |
| `--accent` | `oklch(48% 0.18 22)` | `oklch(64% 0.18 22)` | Library red. Citations, primary action, focus ring. |
| `--accent-soft` | `oklch(95% 0.04 22)` | `oklch(22% 0.06 22)` | Tinted background for selected paper / active node. |
| `--signal-ok` | `oklch(55% 0.12 145)` | `oklch(70% 0.12 145)` | Status: paper retrieved, node complete. |
| `--signal-warn` | `oklch(60% 0.15 65)` | `oklch(75% 0.15 65)` | Status: cost warning, rate-limited. |
| `--signal-err` | `oklch(50% 0.20 25)` | `oklch(70% 0.20 25)` | Status: 4xx/5xx, node failed. |

**Forbidden**: any cream/sand/paper/parchment body bg in the warm-neutral band (OKLCH L 0.84-0.97, C < 0.06, hue 40-100). The "warm white" reflex is the 2026 AI default; pick a different move.

## Typography

- **Display** — `Source Serif 4` (or `Crimson Pro` fallback). Strong serif, used for H1, paper titles, report H2. Pairing axis: serif display + sans body = high contrast.
- **Body** — `Inter Tight` (or `IBM Plex Sans` fallback). Humanist sans, slightly condensed. Used for everything from H3 down, UI labels, buttons.
- **Mono** — `JetBrains Mono` (or `IBM Plex Mono` fallback). For paper IDs, DOIs, BibTeX exports, cost/token numbers, node status.
- **Body line length** capped at 65–75ch.
- **Display letter-spacing** ≥ −0.04em. −0.02 to −0.03em is the sweet spot for tight grotesque display.
- **H1–H3** use `text-wrap: balance`; long prose uses `text-wrap: pretty`.
- **No** `Inter`, `Roboto`, `Arial`, `system-ui`, `Space Grotesk` as the only font. Always pair.

## Motion

- **Easing**: `cubic-bezier(0.16, 1, 0.3, 1)` (ease-out-expo) as the default for entrances and transitions. No bounce, no elastic, no spring overshoot.
- **Duration**: 180–280ms for micro-interactions, 400–600ms for deliberate reveals.
- **Force simulation**: D3 alpha decay tuned for steady state by t=2s, not perpetual motion. `alphaDecay = 0.08` minimum.
- **No `transition: all`**; declare specific properties.
- **Reduced motion**: every animation must have a `@media (prefers-reduced-motion: reduce)` crossfade alternative.
- **No staggered-reveal reflex** (one identical entrance applied to every section). Each reveal fits what it reveals.
- **No `transform: scale` on images** on hover. Card hover = background/border/shadow shift, not image zoom.

## Layout

- **App shell**: top status bar (cost / token / status / elapsed) full-width, then a three-region body.
- **Three regions, NOT a fixed three-column grid**: the layout shifts by focus context — Query (left rail collapsed when reading), Report (full width when comparing), Graph (right rail collapsed during long-form reading). Single-region dominance with side rails that recede.
- **Query rail** (left, `min-w-[280px]`, `max-w-[360px]`, `flex-basis: 28%`): query input, parameter controls, paper list. Sticky scroll inside.
- **Report region** (center, `flex: 1`, `min-w-[640px]`): Markdown report, max-width 75ch, reading-first.
- **Graph rail** (right, `min-w-[320px]`, `flex-basis: 32%`): D3 force-directed citation graph. Sticky inside its container.
- **Grid breakpoints**: 1280px (three-region default), 1024px (graph moves below report as a section), 768px (single column, paper list accordion).
- **No nested cards**. A paper row is a row, not a card inside a card. Use hairline rules and leading numbers (1, 2, 3) instead.
- **No eyebrow text** ("ABOUT", "PROCESS", "PRICING") above sections. Section identity comes from H2 weight and the content itself.

## Components

- **StatusBar** (top): one row, mono font, shows `Papers: 12 · Tokens: 4,231 · Cost: $0.18 · Status: synthesizing · Elapsed: 02:14`. No progress bar of indeterminate length.
- **QueryInput**: large serif-style text input (NOT a textarea chat bubble), single-line by default, expands to 3 lines on focus. Placeholder in mono italic.
- **PaperRow**: number, title (serif), authors (sans condensed), year + venue + citations (mono). Hairline bottom rule, no card chrome. Selected row gets `--accent-soft` background and a 2px left rule in `--accent`.
- **CompareDrawer**: slides in from the right when 2 papers are selected, shows side-by-side metadata + abstract. No celebratory animation; it just appears.
- **CommandPalette** (Cmd+K): centered modal, not full-screen. List of commands, fuzzy search, mono font for shortcut hints, sans for command labels.
- **ReportView**: rendered Markdown with H1 serif, H2 serif, body sans, code mono. Inline citations are `<sup>` numbers in `--accent` linking to footnotes; footnote text is mono.
- **GraphCanvas** (D3): SVG with `<title>` on every node, force layout, Viridis color scale on year (perceptually uniform, color-blind safe), edges are curved paths with low opacity, hover highlights the node + 1-hop neighbors, dim non-neighbors to 0.2 opacity.
- **ChangelogModal**: modal overlay, list of release notes with leading emoji + tag pill. Mono upper-tracked tag, sans body. (The R10.5.30 version of this is close to spec — re-use the pattern.)
- **CostDashboard**: small numerals (NOT a hero-metric tile), no gradient accent. Tabular figures.

## Anti-patterns (hard bans)

- ❌ Side-stripe borders (`border-left: 4px solid var(--accent)` on a list row). Use a 2px left rule on selected state only, and only with a tinted background — never as decoration.
- ❌ Gradient text (`background-clip: text`).
- ❌ Glassmorphism as a default card style.
- ❌ Hero-metric tiles (big number + small label + supporting stats + gradient accent).
- ❌ Identical card grids. Use rows.
- ❌ Eyebrow text on every section.
- ❌ Numbered section markers (01/02/03) above sections.
- ❌ `border: 1px solid X` + `box-shadow: 0 Npx 16px+` on the same element (ghost-card).
- ❌ `border-radius: 32px+` on cards. Cards cap at 12px. Pills OK.
- ❌ Sketchy SVG illustrations.
- ❌ `repeating-linear-gradient` stripe backgrounds.
- ❌ Hover scale on images.
- ❌ Cream / sand / paper / parchment body background.
- ❌ Inter as the only font.
- ❌ Gray text on a colored background.

## Accessibility

- Body text ≥ 4.5:1 against its background.
- Large text (≥18px or bold ≥14px) ≥ 3:1.
- Focus ring: 2px solid `--accent` outline, 2px offset, never removed.
- `prefers-reduced-motion: reduce` honored: crossfade or instant.
- Keyboard: every action reachable; no `tabindex="-1"` to hide controls from AT.
- Color is never the only signal: status icons accompany status colors.

## File / Token Conventions

- All colors via CSS variables in `frontend/src-v2/styles/tokens.css`.
- Tailwind config maps utility classes to variables (e.g. `text-ink`, `bg-paper`, `border-rule`, `text-accent`).
- No raw `oklch()` or `#hex` in component files.
- Component-level font choices: `<Display>` component for serif headings, `<Body>` for sans, `<Mono>` for monospace.
- Default to 8px spacing grid (`gap-2 = 8px`, `gap-4 = 16px`, etc).
