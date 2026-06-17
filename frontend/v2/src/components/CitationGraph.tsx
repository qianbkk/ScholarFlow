// CitationGraph — D3 force-directed graph.
// Viridis color scale on year (perceptually uniform, color-blind safe).
// Nodes have <title> for screen readers.
// Hover highlights node + 1-hop neighbors, dims non-neighbors to 0.2 opacity.

import { useEffect, useRef } from 'react';
import * as d3 from 'd3';
import type { CitationGraph, SimNode } from '../types/domain';

interface Props {
  graph: CitationGraph;
  hoveredId: string | null;
  onHoverNode?: (id: string | null) => void;
  selectedIds?: string[];
}

const WIDTH = 380;
const HEIGHT = 520;
const VIRIDIS = ['#fde725', '#b5de2b', '#6ece58', '#35b779', '#1f9e89', '#26828e', '#31688e', '#3e4989', '#482878', '#440154'];

function viridis(t: number): string {
  const idx = Math.max(0, Math.min(VIRIDIS.length - 1, Math.round(t * (VIRIDIS.length - 1))));
  return VIRIDIS[idx];
}

export function CitationGraph({ graph, hoveredId, onHoverNode, selectedIds = [] }: Props) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const simRef = useRef<d3.Simulation<SimNode, undefined> | null>(null);

  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;
    const sel = d3.select(svg);
    sel.selectAll('*').remove();

    if (graph.nodes.length === 0) {
      sel
        .append('text')
        .attr('x', WIDTH / 2)
        .attr('y', HEIGHT / 2)
        .attr('text-anchor', 'middle')
        .attr('font-family', '"JetBrains Mono", monospace')
        .attr('font-size', 11)
        .attr('fill', 'var(--ink-3)')
        .text('No citation graph yet.');
      return;
    }

    const years = graph.nodes.map((n) => n.year).filter((y) => y > 0);
    const yearExtent: [number, number] = years.length
      ? [Math.min(...years), Math.max(...years)]
      : [2000, 2025];
    const colorScale = d3.scaleLinear<string>().domain(yearExtent).range(['#1f9e89', '#440154']).clamp(true);

    const nodes: SimNode[] = graph.nodes.map((n) => ({ ...n }));
    const idSet = new Set(nodes.map((n) => n.id));
    const links = graph.links
      .filter((l) => idSet.has(typeof l.source === 'string' ? l.source : (l.source as SimNode).id) && idSet.has(typeof l.target === 'string' ? l.target : (l.target as SimNode).id))
      .map((l) => ({ ...l }));

    const root = sel.append('g');

    // Zoom & pan
    const zoom = d3
      .zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.3, 4])
      .on('zoom', (event) => {
        root.attr('transform', event.transform.toString());
      });
    sel.call(zoom);

    const sim = d3
      .forceSimulation<SimNode>(nodes)
      .force(
        'link',
        d3
          .forceLink<SimNode, d3.SimulationLinkDatum<SimNode>>(links as d3.SimulationLinkDatum<SimNode>[])
          .id((d) => d.id)
          .distance(60)
          .strength(0.5),
      )
      .force('charge', d3.forceManyBody().strength(-90))
      .force('center', d3.forceCenter(WIDTH / 2, HEIGHT / 2))
      .force('collide', d3.forceCollide<SimNode>().radius((d) => d.size + 4))
      .alphaDecay(0.08);

    simRef.current = sim;

    const link = root
      .append('g')
      .attr('stroke', 'var(--rule-strong)')
      .attr('stroke-opacity', 0.6)
      .selectAll<SVGLineElement, d3.SimulationLinkDatum<SimNode>>('line')
      .data(links)
      .join('line')
      .attr('stroke-width', 0.8);

    const node = root
      .append('g')
      .selectAll<SVGCircleElement, SimNode>('circle')
      .data(nodes)
      .join('circle')
      .attr('r', (d) => Math.max(4, d.size))
      .attr('fill', (d) => (d.year ? colorScale(d.year) : viridis(0.5)))
      .attr('stroke', (d) => (selectedIds.includes(d.id) ? 'var(--accent)' : 'var(--paper)'))
      .attr('stroke-width', (d) => (selectedIds.includes(d.id) ? 2.5 : 1))
      .style('cursor', 'pointer')
      .on('mouseenter', (_event, d) => onHoverNode?.(d.id))
      .on('mouseleave', () => onHoverNode?.(null))
      .call(
        d3
          .drag<SVGCircleElement, SimNode>()
          .on('start', (event, d) => {
            if (!event.active) sim.alphaTarget(0.3).restart();
            d.fx = d.x ?? 0;
            d.fy = d.y ?? 0;
          })
          .on('drag', (event, d) => {
            d.fx = event.x;
            d.fy = event.y;
          })
          .on('end', (event, d) => {
            if (!event.active) sim.alphaTarget(0);
            d.fx = null;
            d.fy = null;
          }),
      );

    // Accessible <title>
    node.append('title').text((d) => `${d.title} (${d.year})`);

    const label = root
      .append('g')
      .attr('font-family', '"JetBrains Mono", monospace')
      .attr('font-size', 9)
      .attr('fill', 'var(--ink-2)')
      .attr('pointer-events', 'none')
      .selectAll<SVGTextElement, SimNode>('text')
      .data(nodes.filter((n) => n.size >= 6))
      .join('text')
      .attr('dy', -8)
      .attr('text-anchor', 'middle')
      .text((d) => (d.title.length > 30 ? d.title.slice(0, 28) + '…' : d.title));

    sim.on('tick', () => {
      link
        .attr('x1', (d) => (d.source as unknown as SimNode).x ?? 0)
        .attr('y1', (d) => (d.source as unknown as SimNode).y ?? 0)
        .attr('x2', (d) => (d.target as unknown as SimNode).x ?? 0)
        .attr('y2', (d) => (d.target as unknown as SimNode).y ?? 0);
      node.attr('cx', (d) => d.x ?? 0).attr('cy', (d) => d.y ?? 0);
      label.attr('x', (d) => d.x ?? 0).attr('y', (d) => d.y ?? 0);
    });

    // Hover highlight: 1-hop neighborhood
    const neighborOf = (id: string) => {
      const s = new Set<string>([id]);
      for (const l of links) {
        const sid = typeof l.source === 'string' ? l.source : (l.source as SimNode).id;
        const tid = typeof l.target === 'string' ? l.target : (l.target as SimNode).id;
        if (sid === id) s.add(tid);
        if (tid === id) s.add(sid);
      }
      return s;
    };

    const applyHover = (id: string | null) => {
      if (!id) {
        node.attr('opacity', 1);
        link.attr('stroke-opacity', 0.6);
        return;
      }
      const neighbors = neighborOf(id);
      node.attr('opacity', (d) => (neighbors.has(d.id) ? 1 : 0.2));
      link.attr('stroke-opacity', (l) => {
        const sid = typeof l.source === 'string' ? l.source : (l.source as SimNode).id;
        const tid = typeof l.target === 'string' ? l.target : (l.target as SimNode).id;
        return sid === id || tid === id ? 0.9 : 0.1;
      });
    };
    applyHover(hoveredId);

    // Re-apply on hoverId change.
    (simRef.current as unknown as { _applyHover?: (id: string | null) => void })._applyHover = applyHover;

    return () => {
      sim.stop();
    };
  }, [graph, onHoverNode]);

  // React to external hover changes.
  useEffect(() => {
    const sim = simRef.current as unknown as { _applyHover?: (id: string | null) => void } | null;
    sim?._applyHover?.(hoveredId);
  }, [hoveredId, selectedIds]);

  return (
    <div className="relative w-full" style={{ background: 'var(--paper-elev)' }}>
      <svg
        ref={svgRef}
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        width="100%"
        height={HEIGHT}
        role="img"
        aria-label="Citation graph"
        style={{ display: 'block' }}
      />
      <div
        className="absolute bottom-2 left-2 mono text-[10px] flex items-center gap-2"
        style={{ color: 'var(--ink-3)' }}
      >
        <span>{graph.metadata.total_papers} nodes</span>
        <span style={{ color: 'var(--rule-strong)' }}>·</span>
        <span>{graph.metadata.total_links} edges</span>
        {graph.metadata.year_range && (
          <>
            <span style={{ color: 'var(--rule-strong)' }}>·</span>
            <span>
              {graph.metadata.year_range[0]}–{graph.metadata.year_range[1]}
            </span>
          </>
        )}
      </div>
      <div
        className="absolute bottom-2 right-2 mono text-[9px] flex items-center gap-1.5"
        style={{ color: 'var(--ink-3)' }}
      >
        <span>year</span>
        <span
          aria-hidden
          style={{
            display: 'inline-block',
            width: 60,
            height: 6,
            background: 'linear-gradient(to right, #1f9e89, #26828e, #3e4989, #440154)',
          }}
        />
      </div>
    </div>
  );
}
