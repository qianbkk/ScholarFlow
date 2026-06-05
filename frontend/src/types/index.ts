export interface Paper {
  paper_id: string;
  title: string;
  abstract: string;
  year: number;
  authors: string[];
  citation_count: number;
  venue: string;
  url: string;
  source: string;
  is_expanded: boolean;
  relevance_score: number;
  authority_score: number;
  consistency_score: number;   // BUG-005 修复：补齐三维评分字段
  final_score: number;
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
  };
}

export interface SearchResult {
  report: string;
  ranked_papers: Paper[];
  citation_graph: CitationGraph;
  total_cost_usd: number;
  total_tokens_used: number;
  model_usage: Record<string, { tokens: number; cost: number }>;
  iteration: number;
  status: string;
  elapsed_seconds: number;
}

export interface SearchState {
  loading: boolean;
  error: string | null;
  result: SearchResult | null;
  query: string;
}
