# Product

## Register

product

## Users

Academic researchers, PhD students, and R&D engineers who run iterative literature surveys on a topic. They arrive with a question, expect 3-12 minutes of compute, and need to trust the system to be honest about what it knows vs. hallucinated. Power users care about keyboard speed, comparing 2-3 papers side-by-side, and the citation graph; light users care about getting a usable report on the first try. Both share the same screen during a session.

## Product Purpose

ScholarFlow is a multi-agent research assistant that turns a natural-language question into a cited survey report and a citation-graph visualization. An 8-node LangGraph pipeline decomposes the question, retrieves papers from Semantic Scholar and OpenAlex, scores relevance, extracts evidence, and synthesizes a Markdown report with claim-level citations. The user sees the work in progress (real-time cost, token, status, papers retrieved) and gets a finished artifact (Markdown + BibTeX + RIS + D3 graph) they can save or re-query.

Success means: the report cites real papers with real DOIs, the graph shows the actual citation relationships the agent found, and the cost/token telemetry is honest enough that the user trusts it on the second query.

## Brand Personality

- **Scholarly restraint.** Type-led, ink-on-paper, citation-first. No marketing flourish; the report is the hero.
- **Methodical transparency.** Every claim, every cost, every node status is visible. The system shows its work the way a careful researcher would.
- **Quiet confidence.** Anticipate what an academic would want next (cite, export, compare) and place it one keystroke away. No upsell, no celebration animations.

Three words: **scholarly, methodical, candid**.

## Anti-references

- **Not a SaaS dashboard.** No "purple-to-blue gradients", no glassmorphism cards, no SaaS hero-metric tiles, no identical card grids, no gradient text.
- **Not a chatbot.** No chat bubble metaphor, no "How can I help you today?" greeting, no avatar mascots. The query input is a search bar, not a conversation.
- **Not a marketing landing page.** No eyebrow text above every section, no "01/02/03" numbered scaffolding, no "Get started free" CTA buttons. This is a tool, not a pitch.
- **Not a typical Jupyter / IDE clone.** Don't borrow code-editor chrome. The D3 graph is a graph, not a file tree.
- **Not generic AI slop.** No Inter, no Space Grotesk, no system-font fallback as the only font. No gray-on-near-white body text. No hover scales on images.

## Design Principles

1. **Citation as first-class content.** A citation isn't decoration at the bottom of a paragraph — it's the anchor. Show DOIs, paper IDs, year, and authors inline and at first-class font size.
2. **Show the work, not the result.** Real-time node status, token cost, papers retrieved, elapsed time. The user trusts the system because they watched it work.
3. **Density without clutter.** Academic interfaces must hold 30+ papers, an 8-node graph, and a 5-page report on one screen without losing hierarchy. Spacing, type, and weight carry the load; dividers are a last resort.
4. **Keyboard-first for power users.** Every paper action (select, compare, cite, export) is one or two keystrokes. The mouse is for the report, the keyboard is for the work.
5. **The graph is the system, not a chart.** D3 force layout is the agent's reasoning made visible. Nodes are papers, edges are citations the agent actually followed. The graph earns its screen real estate by being inspectable, not decorative.

## Accessibility & Inclusion

- **WCAG 2.1 AA** baseline. Body text ≥4.5:1 contrast. Large text ≥3:1. Placeholder text gets the same 4.5:1, not the muted-gray default.
- **Color-blind safe palette.** Use Viridis or a perceptually-uniform ramp for the citation graph (avoid red/green only distinctions). D3 graph nodes must be distinguishable without color (use shape or label).
- **Reduced motion.** `prefers-reduced-motion: reduce` honored. No bounce, no elastic, no entrance animations on graph forces; crossfade only.
- **Keyboard navigable.** Cmd+K palette, Tab order through query input → paper list → report, arrow keys for paper selection, Shift+click for compare.
- **Screen reader labels** for graph nodes (`<title>` element inside SVG) and report headings.
- **No flashing content.** Citation-graph force simulation is steady-state, not pulsing.
