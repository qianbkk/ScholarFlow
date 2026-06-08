import { useEffect, useRef, useState } from 'react';
import * as d3 from 'd3';
import type { CitationGraph, GraphNode, SimNode, GraphLink } from '../types';

interface Props {
  graph: CitationGraph | null;
}

// M-18: 4 类边的视觉颜色 (cites 实箭头 / co_cited 虚线 / same_venue 点线 / author_overlap 双向)
const LINK_STYLES: Record<string, { stroke: string; dasharray?: string; marker?: string }> = {
  cites: { stroke: '#64748b', marker: 'url(#arrow)' },                // slate-500
  co_cited: { stroke: '#a855f7', dasharray: '4,3' },                    // purple-500, 虚线
  same_venue: { stroke: '#10b981', dasharray: '2,2' },                  // emerald-500, 点线
  author_overlap: { stroke: '#f59e0b', marker: 'url(#arrow-both)' },    // amber-500, 双向
};

// M-18: 社区色 (按 decade 区分)
const COMMUNITY_COLORS = [
  '#3b82f6', // blue-500
  '#8b5cf6', // violet-500
  '#ec4899', // pink-500
  '#f43f5e', // rose-500
  '#ef4444', // red-500
  '#f97316', // orange-500
  '#eab308', // yellow-500
  '#84cc16', // lime-500
];

export function GraphPanel({ graph }: Props) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const [hovered, setHovered] = useState<GraphNode | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
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

    // M-18: 计算邻居集合 (用于 click 高亮 1 跳邻居)
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

    // ===== Arrow markers (M-18: 4 类边对应 4 种 marker) =====
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
      .attr('fill', '#64748b');
    // M-18: 双向 marker (author_overlap)
    defs
      .append('marker')
      .attr('id', 'arrow-both-end')
      .attr('viewBox', '0 -5 10 10')
      .attr('refX', 18)
      .attr('refY', 0)
      .attr('markerWidth', 6)
      .attr('markerHeight', 6)
      .attr('orient', 'auto')
      .append('path')
      .attr('d', 'M0,-5L10,0L0,5')
      .attr('fill', '#f59e0b');
    defs
      .append('marker')
      .attr('id', 'arrow-both-start')
      .attr('viewBox', '0 -5 10 10')
      .attr('refX', 2)
      .attr('refY', 0)
      .attr('markerWidth', 6)
      .attr('markerHeight', 6)
      .attr('orient', 'auto')
      .append('path')
      .attr('d', 'M10,-5L0,0L10,5')
      .attr('fill', '#f59e0b');

    // Color scale: M-18 优先用 community 颜色 (如果 multi-decade), 否则用 relevance 颜色
    const communityCount = graph.metadata.community_count ?? 1;
    const useCommunityColor = communityCount > 1;
    const colorScale = useCommunityColor
      ? (communityId: number) => COMMUNITY_COLORS[communityId % COMMUNITY_COLORS.length]
      : d3
          .scaleLinear<string>()
          .domain([0, 0.5, 1])
          .range(['#93c5fd', '#60a5fa', '#22c55e']);

    // Simulation
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

    // M-18: 4 类边颜色 + dasharray
    const link = svg
      .append('g')
      .selectAll('line')
      .data(links)
      .join('line')
      .attr('stroke', (d: any) => LINK_STYLES[d.type]?.stroke ?? '#94a3b8')
      .attr('stroke-dasharray', (d: any) => LINK_STYLES[d.type]?.dasharray ?? null)
      .attr('stroke-width', (d: any) => (d.type === 'cites' ? 1.2 : 0.8))
      .attr('stroke-opacity', 0.5)
      .attr('marker-end', (d: any) => {
        const s = LINK_STYLES[d.type];
        if (s.marker) return s.marker;
        if (d.type === 'author_overlap') return 'url(#arrow-both-end)';
        return null;
      })
      .attr('marker-start', (d: any) =>
        d.type === 'author_overlap' ? 'url(#arrow-both-start)' : null
      );

    // Nodes
    const node = svg
      .append('g')
      .selectAll('g')
      .data(nodes)
      .join('g')
      .attr('class', 'node')  // Fix-H: 标签 class 让独立 selected effect 能 selectAll 选中
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
        // M-18: click 节点高亮 1 跳邻居 (其余 dim)
        setSelected((prev) => (prev === d.id ? null : d.id));
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

    // M-18: 社区填色 (按 community_id) OR 相关性颜色
    node
      .append('circle')
      .attr('r', (d) => d.size)
      .attr('fill', (d) =>
        useCommunityColor ? colorScale(d.community_id ?? 0) : colorScale(d.color_value)
      )
      .attr('stroke', (d) => (d.id === selected ? '#ef4444' : '#1e293b'))
      .attr('stroke-width', (d) => (d.id === selected ? 3 : 1.2))
      .attr('stroke-opacity', (d) => {
        if (!selected) return 0.5;
        const ns = neighborSet(selected);
        return ns.has(d.id) ? 1 : 0.15;
      });

    // M-18: 高亮邻居时其余节点透明度降低 (Fix-H 改由 selected 独立 effect 处理,
    // 不再触发 simulation 重建 — 避免点击节点时位置重置 + CPU 峰值)
    if (selected) {
      node.style('opacity', (d) => (neighborSet(selected).has(d.id) ? 1 : 0.25));
      link.style('opacity', (d: any) => {
        const sId = typeof d.source === 'string' ? d.source : d.source.id;
        const tId = typeof d.target === 'string' ? d.target : d.target.id;
        return sId === selected || tId === selected ? 0.9 : 0.05;
      });
    }

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
      simulation.stop();
    };
    // Fix-H (R10.5): deps 只 [graph], 删 [selected].  selected 触发的样式更新
    // 走下方独立 effect, 不再因点击节点重建 simulation (用户拖拽布局会丢失 + CPU 峰值).
  }, [graph]);

  // Fix-H (R10.5): 独立 selected effect — 改透明度/边 opacity, 不重建 simulation.
  // 旧版: deps=[graph, selected], 用户点击节点 → effect 重跑 → svg.selectAll('*').remove()
  //   + 重建 force simulation + 节点位置重置 + 100+ tick 重新收敛, 视觉抖动.
  // 新版: simulation 走上面 [graph] effect, 此 effect 仅用 d3.select(svgRef.current) 改样式.
  useEffect(() => {
    if (!svgRef.current || !graph) return;
    const svg = d3.select(svgRef.current);
    // 邻居集合 (与 simulation effect 同样逻辑, 这里独立计算避免 ref 传复杂度)
    // 注: 用 as unknown cast 绕过 TS narrowing (TS 看到 l.source: string 后,
    //     else 分支 'l.source.id' 推导成 'never', 实际无意义 — 我们安全 guard).
    const neighborOfSelected = (id: string) => {
      const s = new Set<string>([id]);
      for (const l of graph.links) {
        const lAny = l as unknown as { source: string | { id: string }; target: string | { id: string } };
        const sId = typeof lAny.source === 'string' ? lAny.source : lAny.source.id;
        const tId = typeof lAny.target === 'string' ? lAny.target : lAny.target.id;
        if (sId === id) s.add(tId);
        if (tId === id) s.add(sId);
      }
      return s;
    };
    const ns = selected ? neighborOfSelected(selected) : null;

    // 节点 + 边 opacity 仅在 selected 存在时改; selected=null 时还原 baseline
    svg
      .selectAll<SVGGElement, SimNode>('g.node') // 节点 group 加 .node class 标记 (见 simulation effect)
      .style('opacity', (d) => (ns ? (ns.has(d.id) ? 1 : 0.25) : null));
    svg
      .selectAll<SVGLineElement, any>('line')
      .style('opacity', (d: any) => {
        if (!ns) return null;
        const sId = typeof d.source === 'string' ? d.source : d.source.id;
        const tId = typeof d.target === 'string' ? d.target : d.target.id;
        return sId === selected || tId === selected ? 0.9 : 0.05;
      });
  }, [selected, graph]);

  return (
    <aside className="w-full lg:w-[30%] lg:min-w-[320px] h-auto lg:h-full bg-[var(--sf-bg)] border-r lg:border-r-0 lg:border-l border-slate-200 dark:border-slate-700 flex flex-col">
      <div className="px-4 py-2.5 border-b border-slate-100 dark:border-slate-800 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-slate-700 dark:text-slate-200">引文关系图谱</h2>
        {graph && (
          <span className="text-[10px] text-slate-500 dark:text-slate-400 font-mono">
            {graph.metadata.total_papers}n / {graph.metadata.total_links}l
            {graph.metadata.community_count && graph.metadata.community_count > 1 && (
              <> · {graph.metadata.community_count} 社区</>
            )}
          </span>
        )}
      </div>
      <div className="flex-1 relative min-h-[400px] lg:min-h-0">
        <svg ref={svgRef} className="w-full h-full" />

        {hovered && (
          <div
            className="absolute pointer-events-none bg-slate-900/95 text-white rounded-md px-3 py-2 text-xs max-w-xs shadow-xl z-10"
            style={{
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
            {/* M-18: 4 类边元信息 + 中心度 + 社区标签 */}
            {hovered.in_degree !== undefined && (
              <p className="text-slate-300 text-[10px] mt-1">
                入度: {hovered.in_degree} · 出度: {hovered.out_degree} · PR:{' '}
                {hovered.pagerank?.toFixed(2) ?? '—'}
                {hovered.community_id !== undefined && (
                  <> · Decade-{hovered.community_id}</>
                )}
              </p>
            )}
            {hovered.abstract && (
              <p className="text-slate-400 text-[10px] mt-1.5 line-clamp-3 leading-relaxed">
                {hovered.abstract}
              </p>
            )}
          </div>
        )}

        {/* M-18: 4 类边图例 + community 颜色 */}
        <div className="absolute bottom-2 left-2 bg-white/90 dark:bg-slate-800/90 backdrop-blur rounded p-2 text-[10px] text-slate-500 dark:text-slate-300 space-y-0.5">
          <div className="font-medium text-slate-600 dark:text-slate-200">边类型 (M-18 4 类)</div>
          <div className="flex items-center gap-1.5">
            <span className="inline-block w-3 h-px" style={{ background: '#64748b' }} />
            <span>cites 直接引用</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span
              className="inline-block w-3 h-px"
              style={{ background: '#a855f7', borderTop: '1px dashed #a855f7' }}
            />
            <span>co_cited 共同引用</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span
              className="inline-block w-3 h-px"
              style={{ background: '#10b981', borderTop: '1px dotted #10b981' }}
            />
            <span>same_venue 同会议</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span
              className="inline-block w-3 h-px"
              style={{ background: '#f59e0b' }}
            />
            <span>author_overlap 共同作者</span>
          </div>
          <div className="text-slate-400 pt-0.5">节点大小 = log(引用数) · 颜色 = 社区</div>
          <div className="text-slate-400">click 节点 = 高亮 1 跳邻居</div>
        </div>
      </div>
    </aside>
  );
}
