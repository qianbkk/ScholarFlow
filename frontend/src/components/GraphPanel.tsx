import { useEffect, useRef, useState } from 'react';
import * as d3 from 'd3';
import type { CitationGraph, GraphNode, SimNode } from '../types';

interface Props {
  graph: CitationGraph | null;
}

export function GraphPanel({ graph }: Props) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const [hovered, setHovered] = useState<GraphNode | null>(null);
  const [tooltipPos, setTooltipPos] = useState({ x: 0, y: 0 });

  useEffect(() => {
    if (!svgRef.current) return;
    const svg = d3.select(svgRef.current);
    svg.selectAll('*').remove();

    if (!graph) return;

    const width = svgRef.current.clientWidth || 400;
    const height = svgRef.current.clientHeight || 600;
    const nodes: SimNode[] = graph.nodes.map((n) => ({ ...n }));
    const links: { source: string; target: string; type: string }[] = graph.links.map((l) => ({ ...l }));

    if (nodes.length === 0) {
      svg
        .append('text')
        .attr('x', width / 2)
        .attr('y', height / 2)
        .attr('text-anchor', 'middle')
        .attr('fill', '#94a3b8')
        .attr('font-size', '13px')
        .text('暂无图谱数据');
      return;
    }

    // Arrow marker
    const defs = svg.append('defs');
    defs
      .append('marker')
      .attr('id', 'arrow')
      .attr('viewBox', '0 -5 10 10')
      .attr('refX', 18)
      .attr('refY', 0)
      .attr('markerWidth', 6)
      .attr('markerHeight', 6)
      .attr('orient', 'auto')
      .append('path')
      .attr('d', 'M0,-5L10,0L0,5')
      .attr('fill', '#cbd5e1');

    // Color scale
    const colorScale = d3
      .scaleLinear<string>()
      .domain([0, 0.5, 1])
      .range(['#93c5fd', '#60a5fa', '#22c55e']);

    // Simulation
    // Round 5 S-8: D3 simulation alphaDecay 0.0228→0.05 + velocityDecay 0.4→0.6, 加快收敛 1 倍, 拖拽更平滑
    // 默认 alphaDecay 0.0228 对中等图谱 (~80 节点) 要 200+ tick 才稳; 提到 0.05 后 ~100 tick 即收敛
    // velocityDecay 0.4 → 0.6 让拖拽后节点停止更平滑, 不会来回震荡
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
      .alphaDecay(0.05)
      .velocityDecay(0.6)
      .alphaMin(0.001);

    // Links
    const link = svg
      .append('g')
      .selectAll('line')
      .data(links)
      .join('line')
      .attr('stroke', '#cbd5e1')
      .attr('stroke-width', 1)
      .attr('stroke-opacity', 0.6)
      .attr('marker-end', 'url(#arrow)');

    // Nodes
    const node = svg
      .append('g')
      .selectAll('g')
      .data(nodes)
      .join('g')
      .style('cursor', 'pointer')
      .on('mouseover', (event, d) => {
        setHovered(d);
        setTooltipPos({ x: event.offsetX, y: event.offsetY });
      })
      .on('mousemove', (event) => {
        setTooltipPos({ x: event.offsetX, y: event.offsetY });
      })
      .on('mouseout', () => setHovered(null))
      .on('click', (_, d) => {
        // BUG-003 / VULN-004 修复：URL 协议白名单 + noopener/noreferrer
        // 拒绝 javascript: / data: 等伪协议；防止 window.opener 反向访问
        if (d.url && /^https?:\/\//i.test(d.url)) {
          window.open(d.url, '_blank', 'noopener,noreferrer');
        }
      })
      .call(
        d3
          .drag<any, SimNode>()
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
            d.fx = null;
            d.fy = null;
          })
      );

    node
      .append('circle')
      .attr('r', (d) => d.size)
      .attr('fill', (d) => colorScale(d.color_value))
      .attr('stroke', '#1e293b')
      .attr('stroke-width', 1.2)
      .attr('stroke-opacity', 0.5);

    node
      .append('text')
      .text((d) => (d.year ? String(d.year) : ''))
      .attr('font-size', 9)
      .attr('text-anchor', 'middle')
      .attr('dy', 3)
      .attr('fill', '#0f172a')
      .attr('pointer-events', 'none');

    node
      .append('title')
      .text((d) => `${d.title}\n[${d.year}] citations: ${d.citation_count}`);

    simulation.on('tick', () => {
      link
        .attr('x1', (d: any) => d.source.x)
        .attr('y1', (d: any) => d.source.y)
        .attr('x2', (d: any) => d.target.x)
        .attr('y2', (d: any) => d.target.y);
      node.attr('transform', (d) => `translate(${d.x ?? 0},${d.y ?? 0})`);
    });

    return () => {
      simulation.stop();
    };
  }, [graph]);

  return (
    <aside className="w-[30%] min-w-[320px] bg-white border-l border-slate-200 flex flex-col h-full">
      <div className="px-4 py-2.5 border-b border-slate-100 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-slate-700">引文关系图谱</h2>
        {graph && (
          <span className="text-[10px] text-slate-500 font-mono">
            {graph.metadata.total_papers}n / {graph.metadata.total_links}l
          </span>
        )}
      </div>
      <div className="flex-1 relative">
        <svg ref={svgRef} className="w-full h-full" />

        {hovered && (
          <div
            className="absolute pointer-events-none bg-slate-900/95 text-white rounded-md px-3 py-2 text-xs max-w-xs shadow-xl z-10"
            style={{
              // 动态读取 SVG 宽度（避免硬编码 300 导致大屏右侧节点 tooltip 被压到左边）
              left: Math.min(
                tooltipPos.x + 12,
                (svgRef.current?.clientWidth || 400) - 280
              ),
              top: Math.min(tooltipPos.y + 12, (svgRef.current?.clientHeight || 600) - 140),
            }}
          >
            <p className="font-semibold mb-1 line-clamp-2">{hovered.title}</p>
            <p className="text-slate-300 text-[10px]">
              {hovered.year} · {hovered.venue || hovered.source}
            </p>
            <p className="text-slate-300 text-[10px] mt-1">
              Citations: {hovered.citation_count.toLocaleString()} · Score:{' '}
              {hovered.final_score?.toFixed(1) ?? '—'}
            </p>
            {hovered.abstract && (
              <p className="text-slate-400 text-[10px] mt-1.5 line-clamp-3 leading-relaxed">
                {hovered.abstract}
              </p>
            )}
          </div>
        )}

        <div className="absolute bottom-2 left-2 bg-white/90 backdrop-blur rounded p-2 text-[10px] text-slate-500 space-y-0.5">
          <div className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-full" style={{ background: '#93c5fd' }} />
            <span>低相关性</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-full" style={{ background: '#22c55e' }} />
            <span>高相关性</span>
          </div>
          <div className="text-slate-400 pt-0.5">节点大小 = log(引用数)</div>
        </div>
      </div>
    </aside>
  );
}
