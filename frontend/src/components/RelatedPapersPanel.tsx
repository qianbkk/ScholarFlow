/**
 * RelatedPapersPanel — R10.5.93 (升级 5) 借鉴 Research Rabbit / Connected Papers
 *
 * 4 大分类 (跟 Research Rabbit "Earlier/Later/Similar/Co-authored" 概念一致):
 * - Earlier works: 选中论文引用的 (cites 边, source=this → target=earlier)
 * - Later works: 引用选中论文的 (cites 边, source=later → target=this)
 * - Co-cited: 跟选中论文一起被引用的 (co_cited 边)
 * - Co-authored: 跟选中论文共享作者的 (author_overlap 边)
 *
 * 设计:
 * - 选中论文时: 按 4 分类聚合
 * - 没选中时: 展示 "Most connected" (按 pagerank/in_degree 排 Top 5)
 * - 可点击切换选中, 触发 selectPaper 联动到 GraphPage
 */
import { useMemo } from 'react';
import { useStore, actions } from '../store/useStore';
import type { CitationGraph, GraphNode } from '../types';

interface Props {
  graph: CitationGraph | null;
  selectedPaperId: string | null;
  onSelect?: (paperId: string) => void;
}

// 4 大分类的视觉配置
const CATEGORIES: Array<{
  key: 'earlier' | 'later' | 'co_cited' | 'co_authored';
  label: string;
  description: string;
  edge: string;       // 边类型
  direction: 'out' | 'in' | 'either';  // source/target 关系
}> = [
  {
    key: 'earlier',
    label: 'Earlier works',
    description: '本研究的前置工作 (本文引用的)',
    edge: 'cites',
    direction: 'out',  // source=this → target=earlier
  },
  {
    key: 'later',
    label: 'Later works',
    description: '本文的后续工作 (引用本文的)',
    edge: 'cites',
    direction: 'in',  // source=later → target=this
  },
  {
    key: 'co_cited',
    label: 'Co-cited',
    description: '经常跟本文一起被引用的论文',
    edge: 'co_cited',
    direction: 'either',
  },
  {
    key: 'co_authored',
    label: 'Co-authored',
    description: '跟本文有共同作者的论文',
    edge: 'author_overlap',
    direction: 'either',
  },
];

export function RelatedPapersPanel({ graph, selectedPaperId, onSelect }: Props) {
  if (!graph || graph.nodes.length === 0) return null;

  // 选中论文时按 4 分类聚合
  const categorized = useMemo(() => {
    if (!selectedPaperId) return null;
    const result: Record<string, Array<{ id: string; node: GraphNode }>> = {
      earlier: [],
      later: [],
      co_cited: [],
      co_authored: [],
    };
    for (const link of graph.links) {
      const sId = typeof link.source === 'string' ? link.source : (link.source as any).id;
      const tId = typeof link.target === 'string' ? link.target : (link.target as any).id;
      const cat = CATEGORIES.find((c) => c.edge === link.type);
      if (!cat) continue;
      let connectedId: string | null = null;
      if (cat.direction === 'out' && sId === selectedPaperId) connectedId = tId;
      else if (cat.direction === 'in' && tId === selectedPaperId) connectedId = sId;
      else if (cat.direction === 'either' && (sId === selectedPaperId || tId === selectedPaperId)) {
        connectedId = sId === selectedPaperId ? tId : sId;
      }
      if (!connectedId) continue;
      // 避免重复
      if (result[cat.key].some((p) => p.id === connectedId)) continue;
      const node = graph.nodes.find((n) => n.id === connectedId);
      if (node) {
        result[cat.key].push({ id: connectedId, node });
      }
    }
    return result;
  }, [graph, selectedPaperId]);

  // 没选中: Top by pagerank
  const topByPagerank = useMemo(() => {
    if (selectedPaperId) return null;
    return [...graph.nodes]
      .sort((a, b) => (b.pagerank ?? 0) - (a.pagerank ?? 0) || (b.in_degree ?? 0) - (a.in_degree ?? 0))
      .slice(0, 5);
  }, [graph, selectedPaperId]);

  const selectedNode = useMemo(() => {
    if (!selectedPaperId) return null;
    return graph.nodes.find((n) => n.id === selectedPaperId) || null;
  }, [graph, selectedPaperId]);

  const handleSelect = (id: string) => {
    actions.selectPaper(id, false);
    onSelect?.(id);
  };

  // 计算每个分类计数
  const counts = useMemo(() => {
    if (!categorized) return null;
    return {
      earlier: categorized.earlier.length,
      later: categorized.later.length,
      co_cited: categorized.co_cited.length,
      co_authored: categorized.co_authored.length,
    };
  }, [categorized]);

  return (
    <section
      style={{
        marginTop: 32,
        padding: '16px 0',
        borderTop: '1px solid var(--sf-border)',
      }}
      data-testid="related-papers-panel"
    >
      {/* Header */}
      <div style={{ marginBottom: 12 }}>
        <h3
          className="font-ui"
          style={{
            fontSize: 13,
            fontWeight: 600,
            color: 'var(--sf-muted)',
            margin: '0 0 4px',
            paddingBottom: 6,
            borderBottom: '1px solid var(--sf-border)',
          }}
        >
          Related papers
        </h3>
        {selectedNode ? (
          <p
            className="font-mono"
            style={{
              fontSize: 10,
              color: 'var(--sf-muted)',
              margin: 0,
            }}
          >
            · 以「{selectedNode.title.slice(0, 60)}{selectedNode.title.length > 60 ? '…' : ''}」为锚点
          </p>
        ) : (
          <p
            className="font-mono"
            style={{
              fontSize: 10,
              color: 'var(--sf-muted)',
              margin: 0,
            }}
          >
            · 未选中论文 — 显示 Top 5 (按 pagerank)
          </p>
        )}
      </div>

      {/* 选中: 4 分类 */}
      {categorized && counts && (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
            gap: 12,
          }}
        >
          {CATEGORIES.map((cat) => {
            const papers = categorized[cat.key] || [];
            return (
              <div
                key={cat.key}
                style={{
                  padding: '8px 10px',
                  border: '1px solid var(--sf-border)',
                  backgroundColor: 'var(--sf-surface)',
                  borderRadius: 2,
                }}
                data-testid={`related-cat-${cat.key}`}
              >
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'baseline',
                    justifyContent: 'space-between',
                    marginBottom: 6,
                  }}
                >
                  <h4
                    className="font-ui"
                    style={{
                      fontSize: 11,
                      fontWeight: 600,
                      letterSpacing: '0.05em',
                      textTransform: 'uppercase',
                      color: 'var(--sf-text)',
                      margin: 0,
                    }}
                  >
                    {cat.label}
                  </h4>
                  <span
                    className="font-mono"
                    style={{
                      fontSize: 10,
                      color: 'var(--sf-muted)',
                    }}
                  >
                    ×{papers.length}
                  </span>
                </div>
                <p
                  className="font-body"
                  style={{
                    fontSize: 10,
                    color: 'var(--sf-muted)',
                    margin: '0 0 6px',
                    lineHeight: 1.3,
                  }}
                >
                  {cat.description}
                </p>
                {papers.length === 0 ? (
                  <p
                    className="font-mono"
                    style={{
                      fontSize: 10,
                      color: 'var(--sf-muted)',
                      margin: 0,
                      fontStyle: 'italic',
                    }}
                  >
                    — 无连接 —
                  </p>
                ) : (
                  <ol
                    style={{
                      listStyle: 'none',
                      padding: 0,
                      margin: 0,
                    }}
                  >
                    {papers.slice(0, 5).map((p, i) => (
                      <li
                        key={p.id}
                        onClick={() => handleSelect(p.id)}
                        style={{
                          fontSize: 11,
                          lineHeight: 1.4,
                          color: 'var(--sf-text)',
                          padding: '3px 0',
                          cursor: 'pointer',
                          borderTop: i > 0 ? '1px dashed var(--sf-border)' : 'none',
                        }}
                        data-testid={`related-paper-${cat.key}-${i}`}
                      >
                        <span
                          className="font-mono"
                          style={{ color: 'var(--sf-accent)', marginRight: 4 }}
                        >
                          →
                        </span>
                        {p.node.title.length > 50
                          ? p.node.title.slice(0, 49) + '…'
                          : p.node.title}
                        {p.node.year && (
                          <span
                            className="font-mono"
                            style={{
                              color: 'var(--sf-muted)',
                              marginLeft: 4,
                              fontSize: 10,
                            }}
                          >
                            [{p.node.year}]
                          </span>
                        )}
                      </li>
                    ))}
                    {papers.length > 5 && (
                      <li
                        className="font-mono"
                        style={{
                          fontSize: 10,
                          color: 'var(--sf-muted)',
                          padding: '2px 0 0',
                          fontStyle: 'italic',
                        }}
                      >
                        ...还有 {papers.length - 5} 篇
                      </li>
                    )}
                  </ol>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* 没选中: Top by pagerank */}
      {topByPagerank && (
        <ol
          style={{
            listStyle: 'none',
            padding: 0,
            margin: 0,
          }}
        >
          {topByPagerank.map((n, i) => (
            <li
              key={n.id}
              onClick={() => handleSelect(n.id)}
              style={{
                fontSize: 12,
                lineHeight: 1.4,
                color: 'var(--sf-text)',
                padding: '6px 0',
                cursor: 'pointer',
                borderTop: i > 0 ? '1px solid var(--sf-border)' : 'none',
                display: 'flex',
                alignItems: 'baseline',
                gap: 8,
              }}
              data-testid={`related-top-${i}`}
            >
              <span
                className="font-mono"
                style={{
                  fontSize: 10,
                  color: 'var(--sf-accent)',
                  minWidth: 20,
                }}
              >
                #{i + 1}
              </span>
              <span style={{ flex: 1 }}>
                {n.title}
                {n.year && (
                  <span
                    className="font-mono"
                    style={{ color: 'var(--sf-muted)', marginLeft: 6, fontSize: 10 }}
                  >
                    [{n.year}]
                  </span>
                )}
              </span>
              <span
                className="font-mono"
                style={{
                  fontSize: 10,
                  color: 'var(--sf-muted)',
                }}
              >
                pr {((n.pagerank ?? 0) * 100).toFixed(0)}
              </span>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
