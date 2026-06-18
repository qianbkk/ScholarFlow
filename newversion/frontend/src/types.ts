// v3 domain types — mirror newversion/backend/scholarflow_v3/models.py

export type PaperSource = 'semantic_scholar' | 'openalex' | 'local_demo' | 'synthesis';

export interface Paper {
  paper_id: string;
  title: string;
  abstract: string;
  year: number;
  authors: string[];
  citation_count: number;
  venue: string;
  url: string;
  doi: string | null;
  source: PaperSource;
  relevance_score: number;
  final_score: number;
  is_expanded: boolean;
  is_fallback: boolean;
}

export interface GraphNode {
  id: string;
  index: number;
  title: string;
  year: number;
  citation_count: number;
  relevance_score: number;
  final_score: number;
  size: number;
  color_value: number;
  venue: string;
  authors: string[];
  in_degree: number;
  out_degree: number;
  community_id: number;
}

export interface SimNode extends GraphNode {
  x?: number;
  y?: number;
  fx?: number | null;
  fy?: number | null;
  vx?: number;
  vy?: number;
}

export type LinkType = 'cites' | 'co_cited' | 'same_venue' | 'author_overlap';

export interface GraphLink {
  source: string;
  target: string;
  type: LinkType;
}

export interface CitationGraph {
  nodes: GraphNode[];
  links: GraphLink[];
  metadata: {
    total_papers: number;
    total_links: number;
    query: string;
    year_range: [number, number] | null;
    community_count: number;
    link_type_counts: Record<string, number>;
  };
}

export interface SearchResult {
  search_id: string;
  query: string;
  report: string;
  ranked_papers: Paper[];
  citation_graph: CitationGraph;
  total_cost_usd: number;
  total_tokens: number;
  iteration: number;
  status: 'complete' | 'partial' | 'error';
  elapsed_seconds: number;
  is_degraded: boolean;
  fallback_paper_count: number;
}

export type NodeStatus = 'pending' | 'running' | 'done' | 'error';

export interface NodeProgress {
  node_id: string;
  label: string;
  status: NodeStatus;
  started_at: number | null;
  finished_at: number | null;
}

export interface LiveEvent {
  event: string;
  data: Record<string, unknown>;
  ts: number;
  search_id: string | null;
}
