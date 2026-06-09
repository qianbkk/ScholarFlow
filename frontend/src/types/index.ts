export interface Paper {
  paper_id: string;
  title: string;
  abstract: string;
  year: number;
  authors: string[];
  citation_count: number;
  venue: string;
  url: string;
  // R10.5 Fix-P1-Audit-diff: 后端 OpenAlex 返回 doi, 之前前端类型缺失导致
  // BibTeX 导出拿不到 DOI. 改 ?string optional 防老 mock 数据无 doi 字段.
  doi?: string;
  source: string;
  is_expanded: boolean;
  relevance_score: number;
  authority_score: number;
  consistency_score: number;   // BUG-005 修复：补齐三维评分字段
  final_score: number;
  // Round 2 MEDIUM-001+PERF-005: 标识此论文是否来自 mock fallback 数据.
  // 之前 backend 已写入但前端类型没声明, paper.is_fallback 永远是 undefined.
  is_fallback?: boolean;
}

export interface GraphNode {
  id: string;
  index: number;
  title: string;
  year: number;
  citation_count: number;
  relevance_score: number;
  final_score: number;
  url: string;
  abstract: string;
  source: string;
  is_expanded: boolean;
  venue: string;
  authors: string[];
  size: number;
  color_value: number;
  // M-18 引文图谱重构 (P0 节点 metadata)
  in_degree?: number;       // 入度 (在 ranked 子图内被引次数)
  out_degree?: number;      // 出度 (在 ranked 子图内引用次数)
  pagerank?: number;        // 中心度近似 (归一化 in_degree, R11 用 NetworkX 真实 PageRank)
  community_id?: number;    // 社区标签 (decade 分组: 0=最老 decade, 1=下一个, ...)
}

// D3 模拟节点：在 GraphNode 基础上加 x/y/fx/fy/vx/vy
export interface SimNode extends GraphNode {
  x?: number;
  y?: number;
  fx?: number | null;
  fy?: number | null;
  vx?: number;
  vy?: number;
}

export interface GraphLink {
  source: string;
  target: string;
  type: string;
}

export interface CitationGraph {
  nodes: GraphNode[];
  links: GraphLink[];
  metadata: {
    total_papers: number;
    total_links: number;
    query: string;
    search_iterations: number;
    // M-18 引文图谱重构 (P0 metadata)
    year_range?: [number, number];
    link_type_counts?: { cites: number; co_cited: number; same_venue: number; author_overlap: number };
    community_count?: number;
  };
}

export interface SearchResult {
  report: string;
  ranked_papers: Paper[];
  citation_graph: CitationGraph;
  total_cost_usd: number;
  total_tokens_used: number;
  // R8 修复 (reviewer feedback 3.3 - 前后端 schema 漂移): 后端 SearchResponse 已经
  // 升级到 model_usage_summary, 前端 SearchResult 同步对齐, 避免 UI 静默退化。
  // 旧名 model_usage 仍兼容保留为可选字段, 给可能从老 cache 读到的数据兜底。
  model_usage_summary: Record<string, { tokens: number; cost: number }>;
  model_usage?: Record<string, { tokens: number; cost: number }>;
  iteration: number;
  status: string;
  elapsed_seconds: number;
  // Round 2 MEDIUM-001+PERF-005: 整体响应是否包含 fallback 论文 (顶层聚合).
  // QueryPanel 据此显示警告 banner. 老 cache 数据可能缺这俩字段, 故 optional.
  is_degraded_response?: boolean;
  fallback_paper_count?: number;
  // R10.5 P0: BibTeX / RIS 导出字符串, 一键导入 Zotero / Mendeley / EndNote
  bibtex?: string;
  ris?: string;
}

export interface SearchState {
  loading: boolean;
  error: string | null;
  result: SearchResult | null;
  query: string;
}
