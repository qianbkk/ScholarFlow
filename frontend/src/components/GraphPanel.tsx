import { useEffect, useRef, useState, useCallback, useMemo } from 'react';
import * as d3 from 'd3';
import type { CitationGraph, GraphNode, SimNode, GraphLink } from '../types';

interface Props {
  graph: CitationGraph | null;
  // R10.5.5: 跨组件论文聚焦 — 外部 controlled selected + callback
  selectedPaperId?: string | null;
  onSelectPaper?: (paperId: string | null) => void;
}

// M-18: 4 类边的视觉颜色 (cites 实箭头 / co_cited 虚线 / same_venue 点线 / author_overlap 双向)
// R10.5.7 P1-3: 改用 ColorBrewer Set1 色盲友好配色 (4 类高对比度不同色).
// R10.5.9 落地: 颜色提到 CSS 变量 --sf-edge-* (index.css 4 主题各设一遍),
// midnight 黑底 + sage 绿底不再 invisible. stroke 走 getComputedStyle 读
// 当前主题值, 避免 d3 hardcode 写死.
const LINK_STYLES: Record<string, { cssVar: string; dasharray?: string; marker?: string }> = {
  cites: { cssVar: '--sf-edge-cites', marker: 'url(#arrow)' },
  co_cited: { cssVar: '--sf-edge-co-cited', dasharray: '4,3' },
  same_venue: { cssVar: '--sf-edge-same-venue', dasharray: '2,2' },
  author_overlap: { cssVar: '--sf-edge-author-overlap', marker: 'url(#arrow-both)' },
};

// 读 CSS 变量当前值 (一次, effect 内复用)
function readEdgeColors(): Record<string, string> {
  if (typeof window === 'undefined') return {};
  const style = getComputedStyle(document.documentElement);
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(LINK_STYLES)) {
    out[k] = style.getPropertyValue(v.cssVar).trim() || '#94a3b8';
  }
  return out;
}


const INTERACTION_HINTS = [
  '单击 = 高亮 1 跳邻居 · 双击 = 打开论文',
  '拖动 = 固定位置 · 右键 = 解除固定',
  '滚轮 = 缩放 · 空白处拖动 = 平移',
];

// M-18: 社区色 (R10.5.4 Editorial: 8 套"墨水 + 单一强调" 配色, 去掉红/紫/粉的糖果色)
// 走"水彩印章" 渐变序列, 学术地图常用配色.
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

export function GraphPanel({ graph, selectedPaperId = null, onSelectPaper }: Props) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const zoomRef = useRef<d3.ZoomBehavior<SVGSVGElement, unknown> | null>(null);
  const rootRef = useRef<d3.Selection<SVGGElement, unknown, null, undefined> | null>(null);
  const [hovered, setHovered] = useState<GraphNode | null>(null);
  // R10.5.5: 内部 selected 让位给外部 controlled selectedPaperId (受控优先)
  // 点击节点 → 通知 App.tsx, App 通过 prop 回流. 保持单一数据源.
  const [tooltipPos, setTooltipPos] = useState({ x: 0, y: 0 });
  // R10.5.5: 当前可见节点 / 总节点 (供工具栏显示)
  const [neighborCount, setNeighborCount] = useState<number | null>(null);

  const selected = selectedPaperId;

  // R10.5.8 code-review 优化: 邻居集合 (1 跳) — 两个 effect 都依赖, 提到 useMemo
  // 避免每次 selected/graph 变化重算 2 次 (旧实现: useEffect 算 count + useEffect
  // 算 opacity, 各自独立遍历 graph.links 一遍). 50k links 大图节省 50%.
  const neighborSet = useMemo(() => {
    if (!graph || !selected) return null;
    const ns = new Set<string>([selected]);
    for (const l of graph.links) {
      const sAny = l.source as unknown as string | { id: string };
      const tAny = l.target as unknown as string | { id: string };
      const sId = typeof sAny === 'string' ? sAny : sAny.id;
      const tId = typeof tAny === 'string' ? tAny : tAny.id;
      if (sId === selected) ns.add(tId);
      if (tId === selected) ns.add(sId);
    }
    return ns;
  }, [graph, selected]);

  // R10.5.5: 当前选中节点的 1 跳邻居数 (含自身) — 工具栏显示
  useEffect(() => {
    setNeighborCount(neighborSet ? neighborSet.size : null);
  }, [neighborSet]);

  // R10.5 Fix-P0-MemoryLeak: 追踪已绑定的事件处理器引用, 以便在 cleanup 中精确移除.
  const keyHandlerRef = useRef<((e: KeyboardEvent) => void) | null>(null);

  // R10.5.5: fit-to-view — 计算所有节点的 bbox, 平滑缩放 + 平移到刚好覆盖
  // 用户滚轮缩放过大/过小/拖偏后, 一键回正.
  const fitToView = useCallback(() => {
    if (!svgRef.current || !zoomRef.current) return;
    const svg = d3.select(svgRef.current);
    // 取 root <g> 实际渲染的 bbox (含 zoom transform)
    const rootNode = rootRef.current?.node();
    if (!rootNode) return;
    const bbox = rootNode.getBBox();
    if (bbox.width === 0 || bbox.height === 0) return;
    const width = svgRef.current.clientWidth || 400;
    const height = svgRef.current.clientHeight || 600;
    // 加 20% 边距防边缘裁切
    const padding = 1.2;
    const scale = Math.min(
      (width * padding) / bbox.width,
      (height * padding) / bbox.height,
      4  // 上限 4x, 跟 scaleExtent 一致
    );
    const tx = width / 2 - (bbox.x + bbox.width / 2) * scale;
    const ty = height / 2 - (bbox.y + bbox.height / 2) * scale;
    const transform = d3.zoomIdentity.translate(tx, ty).scale(scale);
    // 750ms 平滑过渡 (普通 zoom 行为不带 transition, 用 selection.interrupt + transition)
    svg.transition().duration(750).call(zoomRef.current.transform, transform);
  }, []);

  // R10.5 Fix-P0-MemoryLeak: 键盘事件 — 通过 ref 保存处理器引用, 组件卸载时精确移除.
  useEffect(() => {
    const el = svgRef.current;
    if (!el) return;
    // 移除旧处理器 (如果存在)
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

  useEffect(() => {
    if (!svgRef.current) return;
    const svg = d3.select(svgRef.current);
    svg.selectAll('*').remove();

    if (!graph) return;

    const width = svgRef.current.clientWidth || 400;
    const height = svgRef.current.clientHeight || 600;
    const nodes: SimNode[] = graph.nodes.map((n) => ({ ...n }));
    const links: { source: string; target: string; type: string }[] = graph.links.map((l) => ({ ...l }));
    // R10.5.9: 读 CSS 变量当前主题值 — 切换主题时图谱边色自动跟 (ThemeSwitcher 改 <html> class)
    const edgeColors = readEdgeColors();

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

    // R10.5 Fix-Zoom: d3.zoom() 加到 svg, 滚轮缩放 + 拖动空白处平移.
    // 旧版 svg 没 zoom 行为, 节点一多就挤一起看不见, 用户无法缩放/平移.
    // 关键: zoom 必须作用在 root <g> 上, simulation 的 node 也在这个 <g> 里,
    // 才能随 zoom transform 一起缩放/平移.
    const root = svg.append('g').attr('class', 'zoom-root');
    const zoom = d3
      .zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.3, 4])  // 缩放范围 0.3x ~ 4x, 防缩太小看不见/太大溢出
      // R10.5 Fix-Audit-Zoom-Drag: zoom.filter 排除 .node 元素, 节点上的 mousedown
      // 不触发 zoom pan. 旧版 svg 全局监听 mousedown 启动 pan, 跟节点 d3.drag
      // 同时触发, 节点被拖到 pan 偏移后的位置, 体感"卡住". 加 filter: 事件
      // target 在 .node 内时返回 false → zoom 忽略这个事件, 节点 drag 独占.
      .filter((event: MouseEvent) => {
        const target = event.target as Element | null;
        // mousedown 在 .node / .node 后代上 → 让给 drag, 不 pan
        if (target && target.closest('.node')) return false;
        return true;
      })
      .on('zoom', (event) => {
        // event.transform 是 d3 计算好的 translate + scale, 直接 apply 到 root <g>
        root.attr('transform', event.transform.toString());
      });
    // R10.5 Fix-P0-MemoryLeak: zoom 绑定到 svg, 需要在 cleanup 中精确移除.
    // 旧实现只清 simulation.stop(), zoom 事件处理器持续累积 → 内存泄漏.
    svg.call(zoom);
    // R10.5.5: 保存 zoom + root 引用, 工具栏 fit-to-view / 重置缩放 用
    zoomRef.current = zoom;
    rootRef.current = root;

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
    // M-18: 双向 marker (author_overlap) — Editorial: 用 burnt orange 强调
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
      .attr('fill', '#c2410c');
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
      .attr('fill', '#c2410c');

    // Color scale: M-18 优先用 community 颜色 (如果 multi-decade), 否则用 relevance 颜色
    // R10.5.8 code-review 修复: 旧 Set1 3 色 (红/蓝/绿) 是 categorical palette,
    // 不适合 0-1 连续相关度 (低=红=警示, 高=绿=安全, 跟数据直觉反向).
    // 改 ColorBrewer 顺序 YlGn (黄→深绿) — 低相关淡黄, 高相关深绿, 符合
    // "relevance 越高越显眼" 的用户预期, 同时仍色盲友好 (黄→绿单色梯度).
    const communityCount = graph.metadata.community_count ?? 1;
    const useCommunityColor = communityCount > 1;
    const colorScale = useCommunityColor
      ? (communityId: number) => COMMUNITY_COLORS[communityId % COMMUNITY_COLORS.length]
      : d3
          .scaleLinear<string>()
          .domain([0, 0.5, 1])
          .range(['#ffffcc', '#78c679', '#006837']);

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

    // M-18: 4 类边颜色 + dasharray (R10.5 Fix-Zoom: append 到 root <g>, 跟随缩放)
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
        if (d.type === 'author_overlap') return 'url(#arrow-both-end)';
        return null;
      })
      .attr('marker-start', (d: any) =>
        d.type === 'author_overlap' ? 'url(#arrow-both-start)' : null
      );

    // Nodes (R10.5 Fix-Zoom: append 到 root <g>, 跟随缩放)
    const node = root
      .append('g')
      .selectAll('g')
      .data(nodes)
      .join('g')
      .attr('class', 'node')  // Fix-H: 标签 class 让独立 selected effect 能 selectAll 选中
      // cursor: move 提示节点可拖动 (d3.drag 已实现但旧版 cursor: pointer 让用户以为
      // 只能点开链接), click 仍触发 1 跳邻居高亮 + 打开 URL (d3 drag 不会误触 click)
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
        // R10.5 Fix-Click-Conflict: 单击**只高亮**, 不跳 URL.
        // R10.5.5: 高亮状态改为外部受控 — 通知 App.tsx 改 selectedPaperId.
        // App.tsx 单一数据源, 论文列表 / 图谱节点 / 报告引用表 三者共享同一高亮.
        if (onSelectPaper) {
          onSelectPaper(selected === d.id ? null : d.id);
        }
      })
      .call(
        d3
          .drag<any, SimNode>()
          // clickDistance 阈值 5px: 拖动距离 < 5px 算 click, 触发单击高亮;
          // > 5px 算 drag, 走拖动布局逻辑. 防"想点结果拖了"误触.
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
            // 旧版这里把 fx/fy 设 null, 节点松手后立刻被 simulation 推回去,
            // 用户感觉"拖不动" — 实际是 d3 drag 工作了, 但视觉上没停留.
            // 新版: 保留 fx/fy, 节点固定在拖放位置. 右键节点可解除固定.
            // 注: simulation 不会动 fx/fy != null 的节点, 拖过的位置会"粘"住.
          })
      )
      // 双击节点: 打开原始 URL (符合图形交互约定: 单击=选中, 双击=打开)
      .on('dblclick', (_, d) => {
        if (d.url && /^https?:\/\//i.test(d.url)) {
          window.open(d.url, '_blank', 'noopener,noreferrer');
        }
      })
      // 右键节点: 解除固定 (fx/fy = null), 节点重新加入 simulation 自由布局.
      // 之前这里用 dblclick, 但 dblclick 已被跳 URL 占用. 右键是更地道的"解除"操作.
      .on('contextmenu', (event: MouseEvent, d) => {
        event.preventDefault();
        d.fx = null;
        d.fy = null;
        simulation.alpha(0.5).restart();
      });

    // M-18: 社区填色 (按 community_id) OR 相关性颜色
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
      // 节点标签显示: 论文标题 (前 14 字, 截断 + …) + 年份 (副)
      // 之前只显示年份, 10+ 节点全是一串数字, 不点开 tooltip 根本认不出
      // 哪篇是哪篇; 改双行: 主行短标题, 副行小字年份.
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
      // R10.5 Fix-P0-MemoryLeak: 必须先移除 zoom 行为再停止 simulation,
      // 否则 zoom 事件处理器残留在 DOM 上 → 内存泄漏.
      if (zoomRef.current) {
        try {
          // D3 的 zoom 是通过 selection.on() 绑定的, 用 .on('.zoom', null) 移除
          svg.on('.zoom', null);
        } catch { /* ignore */ }
      }
      simulation.stop();
    };
    // Fix-H (R10.5): deps 只 [graph], 删 [selected].  selected 触发的样式更新
    // 走下方独立 effect, 不再因点击节点重建 simulation (用户拖拽布局会丢失 + CPU 峰值).
  }, [graph]);

  // Fix-H (R10.5): 独立 selected effect — 改透明度/边 opacity, 不重建 simulation.
  // 旧版: deps=[graph, selected], 用户点击节点 → effect 重跑 → svg.selectAll('*').remove()
  //   + 重建 force simulation + 节点位置重置 + 100+ tick 重新收敛, 视觉抖动.
  // 新版: simulation 走上面 [graph] effect, 此 effect 仅用 d3.select(svgRef.current) 改样式.
  // R10.5.8: 邻居集合用上面 useMemo 算的 neighborSet, 去掉 effect 内重复计算.
  useEffect(() => {
    if (!svgRef.current || !graph) return;
    const svg = d3.select(svgRef.current);
    const ns = neighborSet;

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
    // R10.5 Fix-Audit-Selected-Stroke: stroke 也在这里 apply, 不在 [graph] effect 闭包里.
    // 旧版 stroke 在 [graph] effect 里用 closure 捕获的 selected 算 (effect 跑一次就定死),
    // 用户点击节点时 [selected] effect 改 opacity 但 stroke 还是旧值, 红圈看不见.
    // 现在 stroke/stroke-width 也跟随 selected 实时更新.
    svg
      .selectAll<SVGGElement, SimNode>('g.node')
      .select('circle')
      .attr('stroke', (d: any) => (d.id === selected ? '#c2410c' : '#1c1917'))
      .attr('stroke-width', (d: any) => (d.id === selected ? 3 : 1.2));
  }, [selected, graph, neighborSet]);

  return (
    // R10.5.4 Editorial: 左侧分隔线 (跟 QueryPanel 右侧对齐), 无圆角, 无 border-r
    <aside
      className="w-full lg:w-[30%] lg:min-w-[320px] h-auto lg:h-full flex flex-col"
      style={{
        backgroundColor: 'var(--sf-bg)',
        borderLeft: '1px solid var(--sf-border)',
      }}
    >
      <div
        className="px-4 py-2.5 flex items-center justify-between border-b gap-2"
        style={{ borderColor: 'var(--sf-border)' }}
      >
        <div className="flex items-baseline gap-2 min-w-0">
          <span
            className="font-mono text-[10px] uppercase tracking-[0.18em] shrink-0"
            style={{ color: 'var(--sf-accent)' }}
          >
            § 4
          </span>
          <h2
            className="font-display text-sm italic font-semibold shrink-0"
            style={{ color: 'var(--sf-text)' }}
          >
            引文图谱
          </h2>
          {/* R10.5.5: 选中节点时显示"邻居数" — 让用户感知 1 跳聚焦范围 */}
          {selected && neighborCount !== null && (
            <span
              className="font-mono text-[9px] uppercase tracking-[0.12em] truncate"
              style={{ color: 'var(--sf-accent)' }}
              title="1 跳邻居数 (含自身)"
            >
              · {neighborCount} 邻居
            </span>
          )}
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          {graph && (
            <span
              className="text-[10px] font-mono uppercase tracking-[0.12em] tabular-nums"
              style={{ color: 'var(--sf-muted)' }}
            >
              {graph.metadata.total_papers}n · {graph.metadata.total_links}l
              {graph.metadata.community_count && graph.metadata.community_count > 1 && (
                <> · {graph.metadata.community_count} 簇</>
              )}
            </span>
          )}
          {/* R10.5.5: 图谱工具栏 — fit-to-view + 重置缩放 + 清选中 */}
          {graph && (
            <>
              <button
                type="button"
                onClick={fitToView}
                title="适配视图 (f)"
                aria-label="适配视图"
                className="font-mono text-[10px] uppercase tracking-[0.1em] px-1.5 py-0.5 transition-colors border"
                style={{
                  color: 'var(--sf-muted)',
                  borderColor: 'var(--sf-border)',
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
                ⊡
              </button>
              {selected && onSelectPaper && (
                <button
                  type="button"
                  onClick={() => onSelectPaper(null)}
                  title="清选中 (Esc)"
                  aria-label="清选中"
                  className="font-mono text-[10px] uppercase tracking-[0.1em] px-1.5 py-0.5 transition-colors border"
                  style={{
                    color: 'var(--sf-accent)',
                    borderColor: 'var(--sf-accent)',
                  }}
                >
                  ✕
                </button>
              )}
            </>
          )}
        </div>
      </div>
      <div className="flex-1 relative min-h-[400px] lg:min-h-0">
        <svg
          ref={svgRef}
          className="w-full h-full"
          tabIndex={0}
          role="img"
          aria-label="引文关系图谱 (按 f 适配视图, Esc 清选中)"
        />

        {/* R10.5 Fix-P0-EmptyState: 优雅的空状态 — 无数据时显示引导, 而非空白 */}
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
              暂无图谱数据
            </p>
            <p className="font-body text-[11px]" style={{ color: 'var(--sf-muted)' }}>
              完成搜索后将自动构建引文关系图
            </p>
          </div>
        )}

        {graph && graph.nodes.length === 0 && (
          <div className="absolute inset-0 flex flex-col items-center justify-center text-center p-6 pointer-events-none">
            <p
              className="font-display italic text-lg mb-1"
              style={{ color: 'var(--sf-muted)' }}
            >
              未检索到论文关联
            </p>
            <p className="font-body text-[11px]" style={{ color: 'var(--sf-muted)' }}>
              尝试更换关键词重新搜索
            </p>
          </div>
        )}

        {hovered && (
          <div
            className="absolute pointer-events-none px-3 py-2 text-xs max-w-xs z-10 font-ui"
            style={{
              left: Math.min(
                tooltipPos.x + 12,
                (svgRef.current?.clientWidth || 400) - 280
              ),
              top: Math.min(tooltipPos.y + 12, (svgRef.current?.clientHeight || 600) - 140),
              backgroundColor: 'var(--sf-text)',
              color: 'var(--sf-bg)',
              boxShadow: '0 4px 14px rgba(0,0,0,0.2)',
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
              Citations: {hovered.citation_count.toLocaleString()} · Score:{' '}
              {hovered.final_score?.toFixed(1) ?? '—'}
            </p>
            {hovered.in_degree !== undefined && (
              <p className="text-[10px] mt-1 opacity-80">
                入度 {hovered.in_degree} · 出度 {hovered.out_degree} · PR{' '}
                {hovered.pagerank?.toFixed(2) ?? '—'}
                {hovered.community_id !== undefined && (
                  <> · 簇 {hovered.community_id}</>
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

        {/* M-18: 4 类边图例 + community 颜色 — Editorial 极简风 */}
        <div
          className="absolute bottom-2 left-2 p-2 text-[10px] space-y-0.5 font-mono"
          style={{
            backgroundColor: 'var(--sf-bg)',
            border: '1px solid var(--sf-border)',
            color: 'var(--sf-muted)',
          }}
        >
          <div
            className="font-semibold uppercase tracking-[0.15em] text-[9px]"
            style={{ color: 'var(--sf-text)' }}
          >
            边类型
          </div>
          {/* R10.5.7 P1-3: 色盲友好图例 — 4 类边用 ColorBrewer Set1 (红/蓝/绿/紫)
              旧版 3 类边都 ink 黑, 只靠 dasharray 区分 → 色盲用户无法辨识
              R10.5.9 落地: 颜色用 CSS 变量 — 主题切换时图例色自动跟随 */}
          <div className="flex items-center gap-1.5">
            <span
              className="inline-block w-3 h-px"
              style={{ background: 'var(--sf-edge-cites)' }}
            />
            <span>cites</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span
              className="inline-block w-3 h-px"
              style={{
                background: 'transparent',
                borderTop: '1px dashed var(--sf-edge-co-cited)',
              }}
            />
            <span>co-cited</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span
              className="inline-block w-3 h-px"
              style={{
                background: 'transparent',
                borderTop: '1px dotted var(--sf-edge-same-venue)',
              }}
            />
            <span>same venue</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span
              className="inline-block w-3 h-px"
              style={{ background: 'var(--sf-edge-author-overlap)' }}
            />
            <span>author overlap</span>
          </div>
          <div
            className="pt-0.5 mt-1 border-t"
            style={{ borderColor: 'var(--sf-border)' }}
          >
            节点大小 = log(引用数) · 颜色 = 社区
          </div>
          {INTERACTION_HINTS.map((h) => (
            <div key={h}>{h}</div>
          ))}
        </div>
      </div>
    </aside>
  );
}
