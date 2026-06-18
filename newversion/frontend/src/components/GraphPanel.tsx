// GraphPanel — D3 force-directed graph. Viridis by year, color-blind safe.
// Hover highlights 1-hop neighborhood. ~320px wide.

import { useEffect, useRef } from 'react';
import * as d3 from 'd3';
import { useStore } from '../hooks/useStore';
import { store } from '../state/store';
import type { CitationGraph, SimNode } from '../types';

const W = 320;
const H = 380;
const VIRIDIS = ['#fde725', '#b5de2b', '#6ece58', '#35b779', '#1f9e89', '#26828e', '#31688e', '#3e4989', '#482878', '#440154'];

function viridis(t: number): string {
  const i = Math.max(0, Math.min(VIRIDIS.length - 1, Math.round(t * (VIRIDIS.length - 1))));
  return VIRIDIS[i];
}

interface Props {
  graph: CitationGraph;
}

export function GraphPanel({ graph }: Props) {
  const ref = useRef<SVGSVGElement | null>(null);
  const simRef = useRef<d3.Simulation<SimNode, undefined> | null>(null);
  const state = useStore();
  const hoveredId = state.hovered;
  const selected = state.selected;

  useEffect(() => {
    const svg = ref.current;
    if (!svg) return;
    const sel = d3.select(svg);
    sel.selectAll('*').remove();

    if (graph.nodes.length === 0) {
      sel
        .append('text')
        .attr('x', W / 2)
        .attr('y', H / 2)
        .attr('text-anchor', 'middle')
        .attr('font-family', '"JetBrains Mono", monospace')
        .attr('font-size', 11)
        .attr('fill', 'var(--ink-3)')
        .text('graph empty');
      return;
    }

    const years = graph.nodes.map((n) => n.year).filter((y) => y > 0);
    const yearExtent: [number, number] = years.length
      ? [Math.min(...years), Math.max(...years)]
      : [2017, 2026];
    const color = d3.scaleLinear<string>().domain(yearExtent).range(['#1f9e89', '#440154']).clamp(true);

    const nodes: SimNode[] = graph.nodes.map((n) => ({ ...n }));
    const idSet = new Set(nodes.map((n) => n.id));
    const links = graph.links
      .filter((l) => idSet.has(l.source) && idSet.has(l.target))
      .map((l) => ({ ...l }));

    const root = sel.append('g');
    const zoom = d3
      .zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.3, 4])
      .on('zoom', (event) => root.attr('transform', event.transform.toString()));
    sel.call(zoom);

    const sim = d3
      .forceSimulation<SimNode>(nodes)
      .force(
        'link',
        d3
          .forceLink<SimNode, d3.SimulationLinkDatum<SimNode>>(links as d3.SimulationLinkDatum<SimNode>[])
          .id((d) => d.id)
          .distance(50)
          .strength(0.6),
      )
      .force('charge', d3.forceManyBody().strength(-80))
      .force('center', d3.forceCenter(W / 2, H / 2))
      .force('collide', d3.forceCollide<SimNode>().radius((d) => d.size + 3))
      .alphaDecay(0.1);
    simRef.current = sim;

    const link = root
      .append('g')
      .attr('stroke', 'var(--rule-strong)')
      .attr('stroke-opacity', 0.7)
      .selectAll<SVGLineElement, d3.SimulationLinkDatum<SimNode>>('line')
      .data(links)
      .join('line')
      .attr('stroke-width', 0.8);

    const node = root
      .append('g')
      .selectAll<SVGCircleElement, SimNode>('circle')
      .data(nodes)
      .join('circle')
      .attr('r', (d) => Math.max(3, d.size))
      .attr('fill', (d) => (d.year ? color(d.year) : viridis(0.5)))
      .attr('stroke', (d) => (selected.includes(d.id) ? 'var(--accent)' : 'var(--base)'))
      .attr('stroke-width', (d) => (selected.includes(d.id) ? 2 : 1))
      .style('cursor', 'pointer')
      .on('mouseenter', (_e, d) => store.setHover(d.id))
      .on('mouseleave', () => store.setHover(null))
      .call(
        d3
          .drag<SVGCircleElement, SimNode>()
          .on('start', (event, d) => {
            if (!event.active) sim.alphaTarget(0.3).restart();
            d.fx = d.x;
            d.fy = d.y;
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

    node.append('title').text((d) => `${d.title} (${d.year})`);

    sim.on('tick', () => {
      link
        .attr('x1', (d) => (d.source as unknown as SimNode).x ?? 0)
        .attr('y1', (d) => (d.source as unknown as SimNode).y ?? 0)
        .attr('x2', (d) => (d.target as unknown as SimNode).x ?? 0)
        .attr('y2', (d) => (d.target as unknown as SimNode).y ?? 0);
      node.attr('cx', (d) => d.x ?? 0).attr('cy', (d) => d.y ?? 0);
    });

    const neighbors = (id: string) => {
      const s = new Set<string>([id]);
      for (const l of links) {
        if (l.source === id) s.add(l.target);
        if (l.target === id) s.add(l.source);
      }
      return s;
    };

    const apply = (id: string | null) => {
      if (!id) {
        node.attr('opacity', 1);
        link.attr('stroke-opacity', 0.7);
        return;
      }
      const n = neighbors(id);
      node.attr('opacity', (d) => (n.has(d.id) ? 1 : 0.2));
      link.attr('stroke-opacity', (l) => (l.source === id || l.target === id ? 0.95 : 0.1));
    };
    apply(hoveredId);
    (sim as unknown as { _apply?: (id: string | null) => void })._apply = apply;

    return () => {
      sim.stop();
    };
  }, [graph, selected]);

  useEffect(() => {
    const sim = simRef.current as unknown as { _apply?: (id: string | null) => void } | null;
    sim?._apply?.(hoveredId);
  }, [hoveredId]);

  return (
    <div className="relative" style={{ background: 'var(--surface-1)' }}>
      <svg
        ref={ref}
        viewBox={`0 0 ${W} ${H}`}
        width="100%"
        height={H}
        role="img"
        aria-label="Citation graph"
        style={{ display: 'block' }}
      />
      <div
        className="absolute bottom-1.5 left-2 mono text-[9px]"
        style={{ color: 'var(--ink-3)' }}
      >
        {graph.metadata.total_papers} nodes · {graph.metadata.total_links} edges
      </div>
      <div
        className="absolute bottom-1.5 right-2 flex items-center gap-1.5"
        style={{ color: 'var(--ink-3)' }}
      >
        <span className="mono text-[9px]">year</span>
        <span
          aria-hidden
          style={{
            display: 'inline-block',
            width: 50,
            height: 5,
            background: 'linear-gradient(to right, #1f9e89, #26828e, #3e4989, #440154)',
          }}
        />
      </div>
    </div>
  );
}
