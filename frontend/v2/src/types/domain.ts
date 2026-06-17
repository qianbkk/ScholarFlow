// Domain types — mirror backend's response shape (see backend/models/paper.py + search.py).
// R10.5.x baseline. Used by services/api.ts and components.

export interface Paper {
  paper_id: string;
  title: string;
  abstract: string;
  year: number;
  authors: string[];
  citation_count: number;
  venue: string;
  url: string;
  doi?: string;
  source: string;
  is_expanded: boolean;
  relevance_score: number;
  authority_score: number;
  consistency_score: number;
  final_score: number;
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
  in_degree?: number;
  out_degree?: number;
  pagerank?: number;
  community_id?: number;
}

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
    year_range?: [number, number];
    link_type_counts?: {
      cites: number;
      co_cited: number;
      same_venue: number;
      author_overlap: number;
    };
    community_count?: number;
  };
}

export interface SearchResult {
  report: string;
  ranked_papers: Paper[];
  citation_graph: CitationGraph;
  total_cost_usd: number;
  total_tokens_used: number;
  model_usage_summary: Record<string, { tokens: number; cost: number }>;
  model_usage?: Record<string, { tokens: number; cost: number }>;
  iteration: number;
  status: string;
  elapsed_seconds: number;
  is_degraded_response?: boolean;
  fallback_paper_count?: number;
  bibtex?: string;
  ris?: string;
}

export interface StreamEvent {
  event: string;
  data: Record<string, unknown>;
  ts: number;
}

// Pipeline node status for the live status row
export type NodeStatus = 'pending' | 'running' | 'done' | 'error';

export interface NodeProgress {
  node_id: string;
  label: string;
  status: NodeStatus;
  started_at?: number;
  finished_at?: number;
  hint?: string;
}
