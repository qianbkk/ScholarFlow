/**
 * GraphPage — 引文图谱 (R10.5.59 Phase C)
 *
 * D3 force-directed citation graph for ScholarFlow. Full reproduction of the
 * OLD GraphPanel.tsx feature set, repackaged as a standalone tab component:
 *
 * - Filter bar (year min/max + author substring + visible/total count)
 * - 2-hop neighbor highlight (1-hop solid ring, 2-hop dashed amber outer ring)
 * - Community color scale (8-color editorial palette + Viridis fallback)
 * - SVG <defs> with 3 arrow markers (cites, author_overlap both-ends)
 * - Link dasharray per type (cites solid / co_cited 4,3 / same_venue 2,2 / author_overlap solid)
 * - Link stroke-width per type (cites 1.2 / others 0.8)
 * - Drag to fix (d3.drag + right-click contextmenu to clear fx/fy)
 * - Pan/zoom (d3.zoom with scaleExtent [0.3, 4], zoom.filter excludes .node descendants)
 * - Zoom-adaptive labels (3 thresholds: <0.8 hide / 0.8-1.5 / 1.5-2.5 / >2.5)
 * - Keyboard shortcuts: f=fit / Shift+F=fullscreen / Esc=exit fullscreen
 * - Fit-to-view button (bbox computation + 750ms smooth transition)
 * - Clear selection button
 * - Neighbor count display (2-hop, including selected node itself)
 * - Collapsible legend + interaction hints
 * - Rich tooltip (title + year + venue + citations + score + in/out + pagerank + community + abstract)
 * - Responsive SVG (ResizeObserver re-fits on container resize)
 * - Double-click to open paper URL
 * - MAX_FRONTEND_NODES = 200 hardcap (defense in depth over backend cap=100)
 * - Header metadata (total_papers · total_links · community_count · zoom_level)
 * - Background click to deselect
 * - High-zoom edge dimming (>1.5x zoom + selection)
 *
 * Reads result.citation_graph + selectedPaperId from useStore. Renders a friendly
 * empty state when graph is null. This is the standalone Graph tab, separate
 * from the Report tab.
 */
import { useEffect, useRef, useState, useCallback, useMemo } from 'react';
// R10.5.49 (P2 defense-in-depth): selective D3 imports — full d3 import is ~500KB.
// Manual chunks + tree-shaking should cut bundle 50%+.
import {
  select,
  drag,
  zoom,
  zoomIdentity,
  forceSimulation,
  forceLink,
  forceManyBody,
  forceCenter,
  forceCollide,
  scaleLinear,
} from 'd3';
import type { ZoomBehavior, Selection } from 'd3';
// d3 alias keeps the imperative `d3.select(...)` / `d3.zoom(...)` call style
// from the legacy GraphPanel without re-importing the full namespace.
const d3 = {
  select, drag, zoom, zoomIdentity,
  forceSimulation, forceLink, forceManyBody, forceCenter, forceCollide, scaleLinear,
};
import type { CitationGraph, GraphNode, SimNode, GraphLink } from '../types';
import { useStore, actions } from '../store/useStore';
import { useT } from '../i18n';

// R10.5.49 (P2 defense-in-depth): frontend hardcap on visible nodes.
// Backend graph_builder.py caps at MAX_GRAPH_NODES=100, but we cannot trust the
// backend forever. 200 = 2x current cap, so even if backend cap doubles
// overnight the browser will still render. Sort by relevance_score desc so
// the highest-value nodes stay visible when truncated.
const MAX_FRONTEND_NODES = 200;

// M-18: 4 edge types -> visual style. Colors come from CSS variables
// (--sf-edge-*) defined in index.css so theme switching propagates automatically.
// Stroke / dasharray / marker assignments here drive both rendering and legend.
const LINK_STYLES: Record<string, { cssVar: string; dasharray?: string; marker?: string }> = {
  cites: { cssVar: '--sf-edge-cites', marker: 'url(#graphpage-arrow)' },
  co_cited: { cssVar: '--sf-edge-co-cited', dasharray: '4,3' },
  same_venue: { cssVar: '--sf-edge-same-venue', dasharray: '2,2' },
  author_overlap: { cssVar: '--sf-edge-author-overlap', marker: 'url(#graphpage-arrow-both-end)' },
};

// Read CSS variable values once per theme. getComputedStyle is cheap enough
// to re-run on every simulation rebuild; the alternative (memoizing across
// theme changes) is fiddly and unnecessary at our call frequency.
function readEdgeColors(): Record<string, string> {
  if (typeof window === 'undefined') return {};
  const style = getComputedStyle(document.documentElement);
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(LINK_STYLES)) {
    out[k] = style.getPropertyValue(v.cssVar).trim() || '#94a3b8';
  }
  return out;
}

// Interaction hints shown inside the collapsible legend. Plain ASCII to keep
// the editorial / typewriter tone (no emoji icons per design constraints).
const INTERACTION_HINTS = [
  '单击 = 高亮 1 跳邻居 · 双击 = 打开论文',
  '拖动 = 固定位置 · 右键 = 解除固定',
  '滚轮 = 缩放 · 空白处拖动 = 平移',
];

// M-18: community palette — 8 "ink + single accent" tones. Editorial direction
// (R10.5.4) dropped candy red/purple/pink in favor of muted academic colors.
// All values are sRGB hex; switching to OKLCH would break the d3 color scale
// which expects a string.
const COMMUNITY_COLORS = [
  '#c2410c', // burnt orange
  '#44403c', // ink soft
  '#78716c', // ink faded
  '#7c2d12', // rust
  '#9a3412', // terracotta
  '#a8a29e', // stone
  '#57534e', // ink muted
  '#1c1917', // ink
];

export function GraphPage() {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const zoomRef = useRef<ZoomBehavior<SVGSVGElement, unknown> | null>(null);
  const rootRef = useRef<Selection<SVGGElement, unknown, null, undefined> | null>(null);
  const t = useT();

  // Store wiring: graph + selection are the only cross-component contracts.
  const graph = useStore((s) => s.result?.citation_graph ?? null);
  const selectedPaperId = useStore((s) => s.selectedPaperId);
  // Actions live on the exported `actions` object, not on state, so we can't
  // select them via useStore. Pulling actions.selectPaper directly works
  // because it's a stable function reference (defined once at module load).
  const { selectPaper } = actions;

  const [hovered, setHovered] = useState<GraphNode | null>(null);
  const [tooltipPos, setTooltipPos] = useState({ x: 0, y: 0 });
  const [neighborCount, setNeighborCount] = useState<number | null>(null);
  const [isFullscreen, setIsFullscreen] = useState<boolean>(false);
  const [legendExpanded, setLegendExpanded] = useState<boolean>(false);
  const [zoomLevel, setZoomLevel] = useState<number>(1);

  // R10.5.59 jitter fix: hoveredRef 镜像 hovered state. 主 D3 effect 不再依赖
  // hovered (避免每次鼠标移动都重建 simulation + 重置节点位置导致颤动),
  // zoom.on 内部读 hoveredRef.current 取最新值. tooltip 用 state 仍可重渲染.
  const hoveredRef = useRef<GraphNode | null>(null);
  useEffect(() => { hoveredRef.current = hovered; }, [hovered]);

  // R10.5.40 Phase 5: filter state — year range + author substring.
  // Default to graph.metadata.year_range (full dataset). User input narrows.
  const yearBounds = useMemo<[number, number]>(() => {
    if (!graph || graph.nodes.length === 0) return [0, 0];
    if (graph.metadata.year_range) return graph.metadata.year_range;
    // Fallback: scan nodes for year span. Some legacy graphs omit metadata.
    let lo = Infinity, hi = -Infinity;
    for (const n of graph.nodes) {
      const y = n.year || 0;
      if (y <= 0) continue;
      if (y < lo) lo = y;
      if (y > hi) hi = y;
    }
    if (!isFinite(lo) || !isFinite(hi)) return [0, 0];
    return [lo, hi];
  }, [graph]);

  const [yearMin, setYearMin] = useState<number | null>(null);
  const [yearMax, setYearMax] = useState<number | null>(null);
  const [authorFilter, setAuthorFilter] = useState<string>('');

  // Reset filter inputs when a new graph arrives. The ref guards against
  // resetting whenever the graph reference changes (e.g. parent re-render)
  // but the underlying query hasn't — otherwise we'd clobber the user's
  // typed values on every store update.
  const filterInitRef = useRef<string | null>(null);
  useEffect(() => {
    if (!graph) return;
    if (filterInitRef.current === graph.metadata.query) return;
    filterInitRef.current = graph.metadata.query;
    setYearMin(yearBounds[0]);
    setYearMax(yearBounds[1]);
    setAuthorFilter('');
  }, [graph, yearBounds]);

  const selected = selectedPaperId;

  // Filtered node set. Author match is case-insensitive substring against any
  // author in the authors[] array. Hard filter — non-matching nodes drop out
  // of the simulation entirely (and 1-hop/2-hop calculations skip them).
  const filteredNodes = useMemo<GraphNode[]>(() => {
    if (!graph) return [];
    const lo = yearMin ?? yearBounds[0];
    const hi = yearMax ?? yearBounds[1];
    const authorQ = authorFilter.trim().toLowerCase();
    const filtered = graph.nodes.filter((n) => {
      const y = n.year || 0;
      if (y > 0 && (y < lo || y > hi)) return false;
      if (authorQ) {
        const hit = (n.authors || []).some((a) => a.toLowerCase().includes(authorQ));
        if (!hit) return false;
      }
      return true;
    });
    // Truncate by relevance_score desc. Backend already sorts by score, but
    // we re-sort defensively in case upstream order drifts.
    if (filtered.length > MAX_FRONTEND_NODES) {
      return [...filtered]
        .sort((a, b) => (b.final_score || 0) - (a.final_score || 0))
        .slice(0, MAX_FRONTEND_NODES);
    }
    return filtered;
  }, [graph, yearMin, yearMax, authorFilter, yearBounds]);

  const visibleIdSet = useMemo(() => new Set(filteredNodes.map((n) => n.id)), [filteredNodes]);

  // Links filtered by visibleIdSet — both endpoints must survive the filter
  // for the link to remain in the simulation.
  const filteredLinks = useMemo(() => {
    if (!graph) return [];
    return graph.links.filter((l) => {
      const sAny = l.source as unknown as string | { id: string };
      const tAny = l.target as unknown as string | { id: string };
      const sId = typeof sAny === 'string' ? sAny : sAny.id;
      const tId = typeof tAny === 'string' ? tAny : tAny.id;
      return visibleIdSet.has(sId) && visibleIdSet.has(tId);
    });
  }, [graph, visibleIdSet]);

  // 1-hop neighbor set. Used for stroke color/width on neighbors + dimming
  // the rest. Kept separate from 2-hop so the inner ring (1-hop) is always
  // distinguishable from the outer ring (2-hop).
  const neighborSet1 = useMemo(() => {
    if (!graph || !selected) return null;
    const ns = new Set<string>([selected]);
    for (const l of filteredLinks) {
      const sAny = l.source as unknown as string | { id: string };
      const tAny = l.target as unknown as string | { id: string };
      const sId = typeof sAny === 'string' ? sAny : sAny.id;
      const tId = typeof tAny === 'string' ? tAny : tAny.id;
      if (sId === selected) ns.add(tId);
      if (tId === selected) ns.add(sId);
    }
    return ns;
  }, [graph, selected, filteredLinks]);

  // 2-hop neighbor set — extends 1-hop by one more edge traversal. Drives the
  // outer dashed amber ring + opacity dimming of non-neighbors. Recomputes
  // whenever the 1-hop set changes (which already depends on selected +
  // filteredLinks).
  const neighborSet2 = useMemo(() => {
    if (!neighborSet1) return null;
    const ns = new Set<string>(neighborSet1);
    for (const l of filteredLinks) {
      const sAny = l.source as unknown as string | { id: string };
      const tAny = l.target as unknown as string | { id: string };
      const sId = typeof sAny === 'string' ? sAny : sAny.id;
      const tId = typeof tAny === 'string' ? tAny : tAny.id;
      if (ns.has(sId) || ns.has(tId)) {
        ns.add(sId);
        ns.add(tId);
      }
    }
    return ns;
  }, [neighborSet1, filteredLinks]);

  // Mirror 2-hop size into state for the toolbar badge. setState in effect
  // is fine here because it only fires when neighborSet2 actually changes.
  useEffect(() => {
    setNeighborCount(neighborSet2 ? neighborSet2.size : null);
  }, [neighborSet2]);

  // R10.5 Fix-P0-MemoryLeak: track keydown handler ref so we can detach on
  // cleanup. The SVG element re-binds when fitToView changes (which only
  // happens on mount in practice, but TS strict mode requires the dep).
  const keyHandlerRef = useRef<((e: KeyboardEvent) => void) | null>(null);

  // Fit-to-view: compute bbox of root <g>, scale + translate to cover viewport
  // with 20% padding, animate over 750ms. Capped at 4x to match zoom.scaleExtent.
  const fitToView = useCallback(() => {
    if (!svgRef.current || !zoomRef.current) return;
    const svg = d3.select(svgRef.current);
    const rootNode = rootRef.current?.node();
    if (!rootNode) return;
    const bbox = rootNode.getBBox();
    if (bbox.width === 0 || bbox.height === 0) return;
    const width = svgRef.current.clientWidth || 400;
    const height = svgRef.current.clientHeight || 600;
    const padding = 1.2;
    const scale = Math.min(
      (width * padding) / bbox.width,
      (height * padding) / bbox.height,
      4
    );
    const tx = width / 2 - (bbox.x + bbox.width / 2) * scale;
    const ty = height / 2 - (bbox.y + bbox.height / 2) * scale;
    const transform = d3.zoomIdentity.translate(tx, ty).scale(scale);
    svg.transition().duration(750).call(zoomRef.current.transform, transform);
  }, []);

  // Fullscreen toggle: flips state then schedules fit-to-view on next frame
  // (after React commits the layout change). Using a ref to access the
  // latest fitToView avoids a stale-closure dependency cycle.
  const toggleFullscreen = useCallback(() => {
    setIsFullscreen((s) => !s);
    requestAnimationFrame(() => fitToViewRef.current?.());
  }, []);
  const fitToViewRef = useRef<(() => void) | null>(null);
  fitToViewRef.current = fitToView;

  // Window-level key handler: Esc exits fullscreen, Shift+F toggles fullscreen.
  // Bare f is handled at the SVG level (below) so it only fires when the user
  // is focused on the graph, not when typing in the filter inputs.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isFullscreen) {
        setIsFullscreen(false);
        requestAnimationFrame(() => fitToViewRef.current?.());
      } else if ((e.key === 'F' || e.key === 'f') && e.shiftKey && !e.metaKey && !e.ctrlKey) {
        e.preventDefault();
        setIsFullscreen((s) => !s);
        requestAnimationFrame(() => fitToViewRef.current?.());
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [isFullscreen]);

  // SVG-level key handler: bare f = fit-to-view. Scoped to the SVG element
  // (which has tabIndex={0}) so it doesn't fire while typing in inputs.
  useEffect(() => {
    const el = svgRef.current;
    if (!el) return;
    if (keyHandlerRef.current) {
      el.removeEventListener('keydown', keyHandlerRef.current);
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'f' || e.key === 'F') {
        e.preventDefault();
        fitToView();
      }
    };
    keyHandlerRef.current = onKey;
    el.addEventListener('keydown', onKey);
    return () => {
      if (keyHandlerRef.current) {
        el.removeEventListener('keydown', keyHandlerRef.current);
        keyHandlerRef.current = null;
      }
    };
  }, [fitToView]);

  // Main D3 effect: builds simulation, links, nodes, markers, zoom. Runs on
  // graph change OR filtered set change. Does NOT depend on `selected` —
  // selection styling is handled by the smaller effect below to avoid
  // rebuilding the simulation (and resetting node positions) on every click.
  useEffect(() => {
    if (!svgRef.current) return;
    const svg = d3.select(svgRef.current);
    svg.selectAll('*').remove();

    if (!graph) return;

    const width = svgRef.current.clientWidth || 400;
    const height = svgRef.current.clientHeight || 600;
    const nodes: SimNode[] = filteredNodes.map((n) => ({ ...n }));
    const links: { source: string; target: string; type: string }[] = filteredLinks.map((l) => ({ ...l }));
    const edgeColors = readEdgeColors();

    if (nodes.length === 0) {
      svg
        .append('text')
        .attr('x', width / 2)
        .attr('y', height / 2)
        .attr('text-anchor', 'middle')
        .attr('fill', '#94a3b8')
        .attr('font-size', '13px')
        .text(
          graph.nodes.length === 0
            ? t('graph.noData')
            : t('graph.emptyFilter')
        );
      return;
    }

    // Root <g> holds every drawn element so a single zoom transform applies
    // uniformly. Adding zoom to a flat SVG would only scale the viewport.
    const root = svg.append('g').attr('class', 'zoom-root');
    const zoom = d3
      .zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.3, 4])
      // zoom.filter: mousedown on .node / .node descendant → let drag handle it,
      // don't also pan. Without this filter, dragging a node would simultaneously
      // pan the canvas (both gestures compete, node ends up at the wrong spot).
      .filter((event: MouseEvent) => {
        const target = event.target as Element | null;
        if (target && target.closest('.node')) return false;
        return true;
      })
      .on('zoom', (event) => {
        root.attr('transform', event.transform.toString());
        const k = event.transform.k;
        setZoomLevel(k);
        // Label font size + char limit adapt to zoom depth. Below 0.8x labels
        // are noise — hide them entirely. Above 2.5x give them room to breathe.
        let labelFontSize: number;
        let labelCharLimit: number;
        if (k < 0.8) {
          labelFontSize = 0;
          labelCharLimit = 0;
        } else if (k < 1.5) {
          labelFontSize = 9;
          labelCharLimit = 14;
        } else if (k < 2.5) {
          labelFontSize = 12;
          labelCharLimit = 24;
        } else {
          labelFontSize = 14;
          labelCharLimit = 40;
        }
        node.selectAll<SVGTextElement, SimNode>('text')
          .style('font-size', `${labelFontSize}px`)
          .style('display', labelFontSize === 0 ? 'none' : (null as unknown as string))
          .text((d: SimNode) => {
            if (labelCharLimit === 0) return '';
            const t = d.title || '';
            return t.length > labelCharLimit ? t.slice(0, labelCharLimit - 1) + '…' : t;
          });
        // High-zoom edge dimming: when focused on a node AND zoomed in past
        // 1.5x, non-adjacent edges fade to near-invisible so the focus graph
        // reads cleanly. At low/mid zoom, keep them at 0.5 for context.
        // R10.5.59 jitter fix: read hovered from hoveredRef.current instead of
        // hovered state (which would require effect to re-run on every hover).
        const focusId = selected || hoveredRef.current?.id;
        if (focusId) {
          link.style('stroke-opacity', (l: any) => {
            const sId = typeof l.source === 'string' ? l.source : l.source.id;
            const tId = typeof l.target === 'string' ? l.target : l.target.id;
            if (sId === focusId || tId === focusId) return 0.85;
            return k > 1.5 ? 0.04 : 0.5;
          });
        }
      });
    // R10.5 Fix-P0-MemoryLeak: explicitly remove zoom handler on cleanup.
    svg.call(zoom);
    // Background rect: click target for "deselect by clicking empty space".
    // Inserted as first child so nodes/links paint over it; pointer-events=all
    // means it captures the click before any node handler.
    const bgRect = svg
      .insert('rect', ':first-child')
      .attr('class', 'graph-bg')
      .attr('width', width)
      .attr('height', height)
      .attr('fill', 'transparent')
      .attr('pointer-events', 'all');
    bgRect.on('click', () => {
      if (selected) selectPaper(null);
    });
    zoomRef.current = zoom;
    rootRef.current = root;

    // Helper used inside click/styling handlers — recomputed each effect run.
    const neighborSet = (id: string) => {
      const s = new Set<string>([id]);
      for (const l of links) {
        const sId = typeof l.source === 'string' ? l.source : (l.source as any).id;
        const tId = typeof l.target === 'string' ? l.target : (l.target as any).id;
        if (sId === id) s.add(tId);
        if (tId === id) s.add(sId);
      }
      return s;
    };

    // ===== Arrow markers =====
    // 3 markers: arrow (cites, single end), arrow-both-end + arrow-both-start
    // (author_overlap, both ends). Marker IDs are namespaced with
    // "graphpage-" so they don't collide if a future page also defines arrows.
    const defs = svg.append('defs');
    defs
      .append('marker')
      .attr('id', 'graphpage-arrow')
      .attr('viewBox', '0 -5 10 10')
      .attr('refX', 18)
      .attr('refY', 0)
      .attr('markerWidth', 6)
      .attr('markerHeight', 6)
      .attr('orient', 'auto')
      .append('path')
      .attr('d', 'M0,-5L10,0L0,5')
      .attr('fill', '#64748b');
    defs
      .append('marker')
      .attr('id', 'graphpage-arrow-both-end')
      .attr('viewBox', '0 -5 10 10')
      .attr('refX', 18)
      .attr('refY', 0)
      .attr('markerWidth', 6)
      .attr('markerHeight', 6)
      .attr('orient', 'auto')
      .append('path')
      .attr('d', 'M0,-5L10,0L0,5')
      .attr('fill', '#c2410c');
    defs
      .append('marker')
      .attr('id', 'graphpage-arrow-both-start')
      .attr('viewBox', '0 -5 10 10')
      .attr('refX', 2)
      .attr('refY', 0)
      .attr('markerWidth', 6)
      .attr('markerHeight', 6)
      .attr('orient', 'auto')
      .append('path')
      .attr('d', 'M10,-5L0,0L10,5')
      .attr('fill', '#c2410c');

    // Color scale: community palette when multi-community, Viridis gradient
    // for single-community (acts as relevance signal: low → pale yellow,
    // high → deep purple).
    const communityCount = graph.metadata.community_count ?? 1;
    const useCommunityColor = communityCount > 1;
    const colorScale = useCommunityColor
      ? (communityId: number) => COMMUNITY_COLORS[communityId % COMMUNITY_COLORS.length]
      : d3
          .scaleLinear<string>()
          .domain([0, 0.5, 1])
          .range(['#fde725', '#21918c', '#440154']);

    // Force simulation. alphaDecay 0.08 (vs D3 default 0.0228) makes 50+
    // node graphs converge in 3-4s instead of 6-8s without visible instability.
    const simulation = d3
      .forceSimulation<SimNode>(nodes)
      .force(
        'link',
        d3
          .forceLink<SimNode, any>(links)
          .id((d: any) => d.id)
          .distance(80)
          .strength(0.4)
      )
      .force('charge', d3.forceManyBody().strength(-200))
      .force('center', d3.forceCenter(width / 2, height / 2))
      .force(
        'collision',
        d3.forceCollide<SimNode>().radius((d) => d.size + 4)
      )
      .alphaDecay(0.08)
      .velocityDecay(0.6)
      .alphaMin(0.001);

    // Links: stroke color from edgeColors, dasharray per type, marker per type.
    // cites gets thicker stroke (1.2) to emphasize the primary relationship.
    const link = root
      .append('g')
      .selectAll('line')
      .data(links)
      .join('line')
      .attr('stroke', (d: any) => edgeColors[d.type] ?? '#94a3b8')
      .attr('stroke-dasharray', (d: any) => LINK_STYLES[d.type]?.dasharray ?? null)
      .attr('stroke-width', (d: any) => (d.type === 'cites' ? 1.2 : 0.8))
      .attr('stroke-opacity', 0.5)
      .attr('marker-end', (d: any) => {
        const s = LINK_STYLES[d.type];
        if (s.marker) return s.marker;
        if (d.type === 'author_overlap') return 'url(#graphpage-arrow-both-end)';
        return null;
      })
      .attr('marker-start', (d: any) =>
        d.type === 'author_overlap' ? 'url(#graphpage-arrow-both-start)' : null
      );

    // Nodes: each is a <g class="node"> containing circle + 2 text labels +
    // <title> for browser tooltips. The .node class is load-bearing: zoom.filter
    // and the selection effect both use it to find node groups.
    const node = root
      .append('g')
      .selectAll('g')
      .data(nodes)
      .join('g')
      .attr('class', 'node')
      .style('cursor', 'move')
      .on('mouseover', (event, d) => {
        setHovered(d);
        setTooltipPos({ x: event.offsetX, y: event.offsetY });
      })
      .on('mousemove', (event) => {
        setTooltipPos({ x: event.offsetX, y: event.offsetY });
      })
      .on('mouseout', () => setHovered(null))
      .on('click', (_, d) => {
        // Single click toggles selection. URL opens on dblclick only — keeps
        // the two intents separate so accidental double-clicks don't navigate
        // away mid-analysis.
        selectPaper(selected === d.id ? null : d.id);
      })
      .call(
        d3
          .drag<any, SimNode>()
          // clickDistance 5px: a drag shorter than this counts as a click and
          // dispatches the click handler; longer counts as drag and skips it.
          .clickDistance(5)
          .on('start', (event, d) => {
            if (!event.active) simulation.alphaTarget(0.3).restart();
            d.fx = d.x;
            d.fy = d.y;
          })
          .on('drag', (event, d) => {
            d.fx = event.x;
            d.fy = event.y;
          })
          .on('end', (event, d) => {
            if (!event.active) simulation.alphaTarget(0);
            // Keep fx/fy set so the node stays pinned. Right-click clears.
          })
      )
      .on('dblclick', (_, d) => {
        if (d.url && /^https?:\/\//i.test(d.url)) {
          window.open(d.url, '_blank', 'noopener,noreferrer');
        }
      })
      .on('contextmenu', (event: MouseEvent, d) => {
        event.preventDefault();
        d.fx = null;
        d.fy = null;
        simulation.alpha(0.5).restart();
      });

    // Circle: filled with community color (or viridis relevance), stroked
    // dark ink (or burnt orange when selected). Stroke width bumps on select.
    node
      .append('circle')
      .attr('r', (d) => d.size)
      .attr('fill', (d) =>
        useCommunityColor ? colorScale(d.community_id ?? 0) : colorScale(d.color_value)
      )
      .attr('stroke', (d) => (d.id === selected ? '#c2410c' : '#1c1917'))
      .attr('stroke-width', (d) => (d.id === selected ? 3 : 1.2))
      .attr('stroke-opacity', (d) => {
        if (!selected) return 0.5;
        const ns = neighborSet(selected);
        return ns.has(d.id) ? 1 : 0.15;
      });

    if (selected) {
      node.style('opacity', (d) => (neighborSet(selected).has(d.id) ? 1 : 0.25));
      link.style('opacity', (d: any) => {
        const sId = typeof d.source === 'string' ? d.source : d.source.id;
        const tId = typeof d.target === 'string' ? d.target : d.target.id;
        return sId === selected || tId === selected ? 0.9 : 0.05;
      });
    }

    // Two-line label: bold title above, dim year below. pointer-events:none
    // so labels don't intercept clicks meant for the parent node group.
    node
      .append('text')
      .attr('font-size', 9)
      .attr('text-anchor', 'middle')
      .attr('dy', (d) => (d.size > 0 ? -d.size - 6 : -10))
      .attr('fill', '#0f172a')
      .attr('font-weight', 600)
      .attr('pointer-events', 'none')
      .text((d) => {
        const t = d.title || '';
        return t.length > 14 ? t.slice(0, 13) + '…' : t;
      });

    node
      .append('text')
      .text((d) => (d.year ? String(d.year) : ''))
      .attr('font-size', 8)
      .attr('text-anchor', 'middle')
      .attr('dy', (d) => (d.size > 0 ? -d.size + 3 : -2))
      .attr('fill', '#57534e')
      .attr('pointer-events', 'none');

    // Native SVG <title> for OS-level browser tooltips on touch devices where
    // our React tooltip never appears.
    node
      .append('title')
      .text(
        (d) =>
          `${d.title}\n[${d.year}] ${d.venue}\ncites: ${d.citation_count} ` +
          `· in/out: ${d.in_degree ?? 0}/${d.out_degree ?? 0} ` +
          `· pagerank: ${d.pagerank ?? 0} · community: ${d.community_id ?? 0}`
      );

    simulation.on('tick', () => {
      link
        .attr('x1', (d: any) => d.source.x)
        .attr('y1', (d: any) => d.source.y)
        .attr('x2', (d: any) => d.target.x)
        .attr('y2', (d: any) => d.target.y);
      node.attr('transform', (d) => `translate(${d.x ?? 0},${d.y ?? 0})`);
    });

    return () => {
      // R10.5 Fix-P0-MemoryLeak: detach zoom handlers BEFORE stopping the
      // simulation, otherwise the event listeners stay bound to the SVG and
      // leak across renders.
      if (zoomRef.current) {
        try {
          svg.on('.zoom', null);
        } catch {
          /* ignore — zoom handler may already be gone */
        }
      }
      simulation.stop();
    };
    // R10.5.59 jitter fix: 移除 hovered deps. hover 只更新 hoveredRef + state,
    // 不重建 simulation. 节点位置稳定, 鼠标滑动不再颤动.
  }, [graph, filteredNodes, filteredLinks, selected]);

  // Independent selected effect: only updates opacity/stroke. Does NOT rebuild
  // the simulation, so clicking a node doesn't reset node positions or spike
  // the CPU. The graph/filteredNodes deps ensure the effect re-runs when the
  // underlying DOM groups are rebuilt (and our selectAll calls would otherwise
  // find empty selections).
  useEffect(() => {
    if (!svgRef.current || !graph) return;
    const svg = d3.select(svgRef.current);
    const ns = neighborSet2;
    const ns1 = neighborSet1;

    svg
      .selectAll<SVGGElement, SimNode>('g.node')
      .style('opacity', (d) => (ns ? (ns.has(d.id) ? 1 : 0.25) : null));
    svg
      .selectAll<SVGLineElement, any>('line')
      .style('opacity', (d: any) => {
        if (!ns) return null;
        const sId = typeof d.source === 'string' ? d.source : d.source.id;
        const tId = typeof d.target === 'string' ? d.target : d.target.id;
        // 2-hop highlight: a link is "lit" only when both endpoints are in
        // the 2-hop set. Otherwise it dims to 0.05.
        return ns.has(sId) && ns.has(tId) ? 0.9 : 0.05;
      });
    // Stroke: selected node = thick burnt orange. 1-hop neighbor = same color
    // thinner. Everyone else = dark ink. Real-time update on click.
    svg
      .selectAll<SVGGElement, SimNode>('g.node')
      .select('circle')
      .attr('stroke', (d: any) => {
        if (d.id === selected) return '#c2410c';
        if (ns1?.has(d.id)) return '#c2410c';
        return '#1c1917';
      })
      .attr('stroke-width', (d: any) => {
        if (d.id === selected) return 3;
        if (ns1?.has(d.id)) return 2.2;
        return 1.2;
      });
    // 2-hop outer ring: dashed amber. We append the ring lazily once, then
    // toggle visibility per-node. The amber is intentionally different from
    // the burnt-orange 1-hop ring so users can tell the two levels apart.
    let ring2 = svg.selectAll<SVGCircleElement, SimNode>('g.node circle.ring-2');
    if (ring2.empty()) {
      ring2 = svg
        .selectAll<SVGGElement, SimNode>('g.node')
        .append('circle')
        .attr('class', 'ring-2')
        .attr('fill', 'none')
        .attr('stroke', '#f59e0b')
        .attr('stroke-width', 1)
        .attr('stroke-dasharray', '2,2')
        .attr('pointer-events', 'none');
    }
    ring2
      .attr('r', (d: any) => d.size + 3)
      .attr('visibility', (d: any) =>
        ns && ns.has(d.id) && !ns1?.has(d.id) ? 'visible' : 'hidden'
      );
  }, [selected, graph, neighborSet1, neighborSet2]);

  // ResizeObserver: when the container resizes (sidebar collapse, window
  // resize, fullscreen toggle), re-fit so the graph stays in view.
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => {
      // Defer to next frame so the SVG has its new clientWidth/Height.
      requestAnimationFrame(() => fitToViewRef.current?.());
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  return (
    // Fullscreen mode = fixed full-viewport overlay. Inline mode = full-width
    // column. Single aside so the toolbar/legend/tooltip code paths are
    // shared between the two states.
    <aside
      className={
        isFullscreen
          ? 'fixed inset-0 z-50 flex flex-col'
          : 'w-full h-full flex flex-col'
      }
      style={{
        backgroundColor: 'var(--sf-bg)',
        borderLeft: isFullscreen ? 'none' : '1px solid var(--sf-border)',
        boxShadow: isFullscreen ? '0 0 0 1px var(--sf-border)' : undefined,
      }}
      data-testid={isFullscreen ? 'graph-fullscreen' : 'graph-page'}
      role={isFullscreen ? 'dialog' : undefined}
      aria-label={isFullscreen ? '引文图谱 全屏模式' : '引文图谱'}
    >
      <div
        className="px-4 py-2.5 flex items-center justify-between border-b gap-2"
        style={{ borderColor: 'var(--sf-border)' }}
      >
        <div className="flex items-baseline gap-2 min-w-0">
          {/* R10.5.59: 删除 '§ 4' 章节前缀符号 */}
          <h2
            className="font-display text-sm italic font-semibold shrink-0"
            style={{ color: 'var(--sf-text)' }}
          >
            {t('graph.title')}
          </h2>
          {selected && neighborCount !== null && (
            <span
              className="font-mono text-[9px] uppercase tracking-[0.12em] truncate"
              style={{ color: 'var(--sf-accent)' }}
              title={t('graph.neighborsHint')}
            >
              · {t('graph.neighbors', { n: neighborCount })}
            </span>
          )}
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          {graph && (
            <span
              className="text-[10px] font-mono uppercase tracking-[0.12em] tabular-nums flex items-center gap-1.5"
              style={{ color: 'var(--sf-muted)' }}
            >
              <span>
                {graph.metadata.total_papers}n · {graph.metadata.total_links}l
              </span>
              {graph.metadata.community_count && graph.metadata.community_count > 1 && (
                <span>· {graph.metadata.community_count} 簇</span>
              )}
              {Math.abs(zoomLevel - 1) > 0.05 && (
                <span
                  style={{ color: 'var(--sf-accent)', fontWeight: 600 }}
                  title={t('graph.zoomLevel', { k: zoomLevel.toFixed(2) })}
                >
                  · {zoomLevel.toFixed(2)}x
                </span>
              )}
            </span>
          )}
          {graph && (
            <>
              <button
                type="button"
                onClick={fitToView}
                title={t('graph.fitTooltip')}
                aria-label="适配视图"
                className="font-mono text-[10px] uppercase tracking-[0.1em] px-1.5 py-0.5 transition-colors border"
                style={{
                  color: 'var(--sf-muted)',
                  borderColor: 'var(--sf-border)',
                  borderRadius: '2px',
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.color = 'var(--sf-accent)';
                  e.currentTarget.style.borderColor = 'var(--sf-accent)';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.color = 'var(--sf-muted)';
                  e.currentTarget.style.borderColor = 'var(--sf-border)';
                }}
              >
                Fit
              </button>
              <button
                type="button"
                onClick={toggleFullscreen}
                title={isFullscreen ? t('graph.fullscreenExitTooltip') : t('graph.fullscreenTooltip')}
                aria-label={isFullscreen ? '退出全屏' : '全屏看图'}
                className="font-mono text-[10px] uppercase tracking-[0.1em] px-1.5 py-0.5 transition-colors border"
                style={{
                  color: isFullscreen ? 'var(--sf-accent)' : 'var(--sf-muted)',
                  borderColor: isFullscreen ? 'var(--sf-accent)' : 'var(--sf-border)',
                  borderRadius: '2px',
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.color = 'var(--sf-accent)';
                  e.currentTarget.style.borderColor = 'var(--sf-accent)';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.color = isFullscreen
                    ? 'var(--sf-accent)'
                    : 'var(--sf-muted)';
                  e.currentTarget.style.borderColor = isFullscreen
                    ? 'var(--sf-accent)'
                    : 'var(--sf-border)';
                }}
              >
                {isFullscreen ? 'Exit' : 'Full'}
              </button>
              {selected && (
                <button
                  type="button"
                  onClick={() => selectPaper(null)}
                  title={t('graph.clearTooltip')}
                  aria-label="清选中"
                  className="font-mono text-[10px] uppercase tracking-[0.1em] px-1.5 py-0.5 transition-colors border"
                  style={{
                    color: 'var(--sf-accent)',
                    borderColor: 'var(--sf-accent)',
                    borderRadius: '2px',
                  }}
                >
                  Clear
                </button>
              )}
            </>
          )}
        </div>
      </div>

      {/* Filter bar: year min/max + author substring + visible count. Only
          shows when the graph has at least one node — otherwise it's just
          noise against the empty state. */}
      {graph && graph.nodes.length > 0 && (
        <div
          className="px-4 py-1.5 flex items-center gap-2 border-b flex-wrap"
          style={{ borderColor: 'var(--sf-border)' }}
          data-testid="graph-filter-bar"
        >
          <span
            className="font-mono text-[11px] uppercase tracking-[0.12em] shrink-0"
            style={{ color: 'var(--sf-muted)' }}
          >
            {t('graph.filterYear')}
          </span>
          <input
            type="number"
            value={yearMin ?? ''}
            placeholder={String(yearBounds[0])}
            min={yearBounds[0]}
            max={yearBounds[1]}
            onChange={(e) => {
              const v = e.target.value === '' ? null : Number(e.target.value);
              setYearMin(v);
            }}
            className="font-mono text-[11px] px-1.5 py-0.5 w-16 outline-none"
            style={{
              backgroundColor: 'var(--sf-bg)',
              color: 'var(--sf-text)',
              border: '1px solid var(--sf-border)',
              borderRadius: '2px',
            }}
            aria-label={t('graph.filterYearMin')}
            data-testid="graph-filter-year-min"
          />
          <span className="font-mono text-[11px]" style={{ color: 'var(--sf-muted)' }}>
            —
          </span>
          <input
            type="number"
            value={yearMax ?? ''}
            placeholder={String(yearBounds[1])}
            min={yearBounds[0]}
            max={yearBounds[1]}
            onChange={(e) => {
              const v = e.target.value === '' ? null : Number(e.target.value);
              setYearMax(v);
            }}
            className="font-mono text-[11px] px-1.5 py-0.5 w-16 outline-none"
            style={{
              backgroundColor: 'var(--sf-bg)',
              color: 'var(--sf-text)',
              border: '1px solid var(--sf-border)',
              borderRadius: '2px',
            }}
            aria-label={t('graph.filterYearMax')}
            data-testid="graph-filter-year-max"
          />
          <span
            className="font-mono text-[11px] uppercase tracking-[0.12em] shrink-0 ml-2"
            style={{ color: 'var(--sf-muted)' }}
          >
            {t('graph.filterAuthor')}
          </span>
          <input
            type="text"
            value={authorFilter}
            placeholder={t('graph.filterAuthorPlaceholder')}
            onChange={(e) => setAuthorFilter(e.target.value)}
            className="font-mono text-[11px] px-1.5 py-0.5 flex-1 min-w-[80px] outline-none"
            style={{
              backgroundColor: 'var(--sf-bg)',
              color: 'var(--sf-text)',
              border: '1px solid var(--sf-border)',
              borderRadius: '2px',
            }}
            aria-label={t('graph.filterAuthor')}
            data-testid="graph-filter-author"
          />
          {filteredNodes.length !== graph.nodes.length && (
            <button
              type="button"
              onClick={() => {
                setYearMin(yearBounds[0]);
                setYearMax(yearBounds[1]);
                setAuthorFilter('');
              }}
              className="font-mono text-[10px] uppercase tracking-[0.12em] px-1.5 py-0.5 border shrink-0 transition-colors"
              style={{
                color: 'var(--sf-accent)',
                borderColor: 'var(--sf-accent)',
                borderRadius: '2px',
              }}
              title="清空过滤"
              aria-label="清空过滤"
            >
              {t('graph.filterClear')}
            </button>
          )}
          <span
            className="font-mono text-[10px] uppercase tracking-[0.12em] shrink-0 tabular-nums"
            style={{ color: 'var(--sf-muted)' }}
            data-testid="graph-filter-count"
          >
            {t('graph.filterCount', { visible: filteredNodes.length, total: graph.nodes.length })}
          </span>
        </div>
      )}

      <div
        ref={containerRef}
        className="flex-1 relative min-h-[400px] lg:min-h-0"
      >
        <svg
          ref={svgRef}
          className="w-full h-full"
          tabIndex={0}
          role="img"
          aria-label="引文关系图谱 (按 f 适配视图, Esc 清选中)"
        />

        {/* Empty states: friendly placeholder when no graph data exists, or
            when the search produced zero results (different copy because the
            recovery action differs). pointer-events:none so they don't block
            clicks that should fall through to the SVG. */}
        {!graph && (
          <div className="absolute inset-0 flex flex-col items-center justify-center text-center p-6 pointer-events-none">
            <div
              className="w-16 h-16 mb-4 flex items-center justify-center"
              style={{ border: '1px solid var(--sf-border)' }}
            >
              <svg
                width="32"
                height="32"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="1"
                style={{ color: 'var(--sf-muted)' }}
              >
                <circle cx="12" cy="5" r="2.5" />
                <circle cx="5" cy="19" r="2.5" />
                <circle cx="19" cy="19" r="2.5" />
                <line x1="12" y1="7.5" x2="5" y2="16.5" />
                <line x1="12" y1="7.5" x2="19" y2="16.5" />
                <line x1="5" y1="16.5" x2="19" y2="16.5" />
              </svg>
            </div>
            <p
              className="font-display italic text-lg mb-1"
              style={{ color: 'var(--sf-muted)' }}
            >
              {t('graph.noData')}
            </p>
            <p className="font-body text-[11px]" style={{ color: 'var(--sf-muted)' }}>
              {t('graph.noDataHint')}
            </p>
          </div>
        )}

        {graph && graph.nodes.length === 0 && (
          <div className="absolute inset-0 flex flex-col items-center justify-center text-center p-6 pointer-events-none">
            <p
              className="font-display italic text-lg mb-1"
              style={{ color: 'var(--sf-muted)' }}
            >
              {t('graph.noResults')}
            </p>
            <p className="font-body text-[11px]" style={{ color: 'var(--sf-muted)' }}>
              {t('graph.noResultsHint')}
            </p>
          </div>
        )}

        {/* Fullscreen Esc hint: bottom-left so it doesn't collide with the
            legend at the very corner. Only shows in fullscreen where the
            regular UI is replaced. */}
        {graph && graph.nodes.length > 0 && isFullscreen && (
          <div
            className="absolute bottom-3 left-3 pointer-events-none"
            data-testid="graph-fullscreen-esc-hint"
          >
            <div
              className="font-mono text-[10px] uppercase tracking-[0.15em] px-2.5 py-1.5 flex items-center gap-2 pointer-events-auto"
              style={{
                backgroundColor: 'oklch(20% 0 0)',
                color: 'var(--sf-bg)',
                border: '1px solid var(--sf-border)',
                boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
              }}
              title={t('graph.exitFullscreenHint')}
            >
              <kbd
                className="px-1.5 py-0.5 font-mono font-semibold"
                style={{
                  backgroundColor: 'var(--sf-bg)',
                  color: 'var(--sf-text)',
                  border: '1px solid var(--sf-accent)',
                  borderRadius: '2px',
                }}
              >
                Esc
              </kbd>
              <span>{t('graph.exitFullscreenLabel')}</span>
            </div>
          </div>
        )}

        {/* Rich tooltip: positioned in container coords (event.offsetX/Y
            are relative to the SVG). Clamped to the right/bottom edges
            so the card doesn't run off-screen on narrow viewports. */}
        {hovered && (
          <div
            className="absolute pointer-events-none px-3 py-2 text-xs max-w-xs z-10 font-ui"
            style={{
              left: Math.min(
                tooltipPos.x + 12,
                (svgRef.current?.clientWidth || 400) - 280
              ),
              top: Math.min(
                tooltipPos.y + 12,
                (svgRef.current?.clientHeight || 600) - 140
              ),
              backgroundColor: 'var(--sf-text)',
              color: 'var(--sf-bg)',
              boxShadow: '0 4px 14px rgba(0,0,0,0.2)',
              borderRadius: '4px',
            }}
          >
            <p className="font-display italic font-semibold mb-1 line-clamp-2 text-[13px]">
              {hovered.title}
            </p>
            <p
              className="font-mono text-[10px] uppercase tracking-wider"
              style={{ color: 'var(--sf-accent-soft)' }}
            >
              {hovered.year} · {hovered.venue || hovered.source}
            </p>
            <p className="text-[10px] mt-1 opacity-80">
              {t('graph.tooltip.citations')}: {hovered.citation_count.toLocaleString()} · {t('graph.tooltip.score')}:{' '}
              {hovered.final_score?.toFixed(1) ?? '—'}
            </p>
            {hovered.in_degree !== undefined && (
              <p className="text-[10px] mt-1 opacity-80">
                {t('graph.tooltip.inOut')} {hovered.in_degree}/{hovered.out_degree} · {t('graph.tooltip.pr')}{' '}
                {hovered.pagerank?.toFixed(2) ?? '—'}
                {hovered.community_id !== undefined && (
                  <> · c{hovered.community_id}</>
                )}
              </p>
            )}
            {hovered.abstract && (
              <p
                className="text-[10px] mt-1.5 line-clamp-3 leading-relaxed"
                style={{ color: 'var(--sf-accent-soft)' }}
              >
                {hovered.abstract}
              </p>
            )}
          </div>
        )}

        {/* Collapsible legend: 4 edge types + community hint + interaction
            shortcuts. Default collapsed (small footprint in corner); expand
            to see full key. Auto-expanded in fullscreen where real estate
            is plentiful. */}
        <div
          className="absolute bottom-2 left-2 text-[10px] font-mono transition-shadow"
          style={{
            backgroundColor: 'var(--sf-bg)',
            border: '1px solid var(--sf-border)',
            color: 'var(--sf-muted)',
            minWidth: legendExpanded || isFullscreen ? '180px' : '88px',
            boxShadow: legendExpanded
              ? '0 2px 10px rgba(0,0,0,0.08)'
              : '0 1px 3px rgba(0,0,0,0.04)',
            borderRadius: '4px',
          }}
          data-testid="edge-legend"
        >
          <button
            type="button"
            onClick={() => setLegendExpanded((s) => !s)}
            aria-expanded={legendExpanded}
            className="w-full flex items-center justify-between gap-2 px-2 py-1 transition-colors"
            style={{ color: 'var(--sf-text)' }}
            title={legendExpanded ? t('graph.legendCollapse') : t('graph.legendExpand')}
          >
            <span className="font-semibold uppercase tracking-[0.15em] text-[9px]">
              {t('graph.legend')}
            </span>
            <span
              className="font-display italic text-[10px] leading-none transition-transform"
              style={{ transform: legendExpanded ? 'rotate(0deg)' : 'rotate(-90deg)' }}
            >
              ▾
            </span>
          </button>
          {(legendExpanded || isFullscreen) && (
            <div className="px-2 pb-1.5 space-y-0.5">
              <div className="flex items-center gap-1.5">
                <span
                  className="inline-block w-3 h-px"
                  style={{ background: 'var(--sf-edge-cites)' }}
                />
                <span>{t('graph.legend.cites')}</span>
              </div>
              <div className="flex items-center gap-1.5">
                <span
                  className="inline-block w-3 h-px"
                  style={{
                    background: 'transparent',
                    borderTop: '1px dashed var(--sf-edge-co-cited)',
                  }}
                />
                <span>{t('graph.legend.coCited')}</span>
              </div>
              <div className="flex items-center gap-1.5">
                <span
                  className="inline-block w-3 h-px"
                  style={{
                    background: 'transparent',
                    borderTop: '1px dotted var(--sf-edge-same-venue)',
                  }}
                />
                <span>{t('graph.legend.sameVenue')}</span>
              </div>
              <div className="flex items-center gap-1.5">
                <span
                  className="inline-block w-3 h-px"
                  style={{ background: 'var(--sf-edge-author-overlap)' }}
                />
                <span>{t('graph.legend.authorOverlap')}</span>
              </div>
              <div
                className="pt-0.5 mt-1 border-t"
                style={{ borderColor: 'var(--sf-border)' }}
              >
                {t('graph.legendHint')}
              </div>
              {[t('graph.hint.click'), t('graph.hint.drag'), t('graph.hint.zoom')].map((h) => (
                <div key={h}>{h}</div>
              ))}
            </div>
          )}
        </div>
      </div>
    </aside>
  );
}