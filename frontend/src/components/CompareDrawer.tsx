/**
 * P1: 分屏对比模式 (Split-Screen Compare Mode)
 * 灵感来自 FanBox 的文件 diff 功能
 * 
 * 功能:
 * - 多选模式下右侧抽屉变为左右分栏
 * - 显示两篇论文的对比视图
 * - 触发 compare_agent 生成方法论/数据集/结论差异摘要
 */
import { useState, useMemo, useCallback } from 'react';

interface Paper {
  paper_id: string;
  title: string;
  abstract?: string;
  authors?: string[];
  year?: number;
  venue?: string;
  citation_count?: number;
  confidence_score?: number;
  quality_score?: number;
  methods?: string[];
  doi?: string;
  url?: string;
}

interface CriticReview {
  paper_id: string;
  quality_score: number;
  strengths: string[];
  weaknesses: string[];
  methodology_issues: string[];
  recommendation: 'adopt' | 'cautious' | 'reject';
  confidence: number;
  reasoning: string;
}

interface Props {
  papers: Paper[];
  selectedPaperIds: string[];
  reviews: Record<string, CriticReview>;
  onClose: () => void;
}

export function CompareDrawer({ papers, selectedPaperIds, reviews, onClose }: Props) {
  const [activeTab, setActiveTab] = useState<'overview' | 'methods' | 'quality'>('overview');

  // 获取选中的两篇论文
  const comparisonPapers = useMemo(() => {
    return selectedPaperIds
      .map(id => papers.find(p => p.paper_id === id))
      .filter((p): p is Paper => !!p)
      .slice(0, 2); // 最多对比 2 篇
  }, [papers, selectedPaperIds]);

  if (comparisonPapers.length < 2) {
    return null;
  }

  const [paperA, paperB] = comparisonPapers;
  const reviewA = reviews[paperA.paper_id];
  const reviewB = reviews[paperB.paper_id];

  // 计算对比维度
  const comparisons = useMemo(() => {
    const methodsA = new Set(paperA.methods || []);
    const methodsB = new Set(paperB.methods || []);
    
    const commonMethods = [...methodsA].filter(m => methodsB.has(m));
    const uniqueToA = [...methodsA].filter(m => !methodsB.has(m));
    const uniqueToB = [...methodsB].filter(m => !methodsA.has(m));

    const citationDiff = (paperB.citation_count || 0) - (paperA.citation_count || 0);
    const qualityDiff = (reviewB?.quality_score || 0) - (reviewA?.quality_score || 0);
    const confidenceDiff = (paperB.confidence_score || 0) - (paperA.confidence_score || 0);

    return {
      commonMethods,
      uniqueToA,
      uniqueToB,
      citationDiff,
      qualityDiff,
      confidenceDiff,
      yearDiff: (paperB.year || 0) - (paperA.year || 0),
    };
  }, [paperA, paperB, reviewA, reviewB]);

  return (
    <div className="compare-drawer" style={{
      position: 'fixed',
      right: 0,
      top: 0,
      bottom: 0,
      width: '800px',
      backgroundColor: 'var(--sf-bg-elev)',
      borderLeft: '2px solid var(--sf-border)',
      zIndex: 1000,
      display: 'flex',
      flexDirection: 'column',
      boxShadow: '-4px 0 24px rgba(0,0,0,0.3)',
    }}>
      {/* 顶部标题栏 */}
      <div className="drawer-header" style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        padding: '16px 20px',
        borderBottom: '2px solid var(--sf-border)',
        backgroundColor: 'var(--sf-bg)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <span style={{
            fontSize: '14px',
            fontWeight: '700',
            color: 'var(--sf-text)',
          }}>
            ⚖️ 论文对比模式
          </span>
          <span style={{
            fontSize: '11px',
            color: 'var(--sf-muted)',
            fontFamily: 'monospace',
          }}>
            {paperA.title.slice(0, 30)}... vs {paperB.title.slice(0, 30)}...
          </span>
        </div>
        <button
          onClick={onClose}
          style={{
            background: 'none',
            border: 'none',
            color: 'var(--sf-muted)',
            fontSize: '20px',
            cursor: 'pointer',
            padding: '4px 8px',
            borderRadius: '4px',
            transition: 'all 0.2s ease',
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.backgroundColor = 'var(--sf-border)';
            e.currentTarget.style.color = 'var(--sf-text)';
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.backgroundColor = 'transparent';
            e.currentTarget.style.color = 'var(--sf-muted)';
          }}
        >
          ✕
        </button>
      </div>

      {/* Tab 导航 */}
      <div className="tabs" style={{
        display: 'flex',
        borderBottom: '1px solid var(--sf-border)',
        backgroundColor: 'var(--sf-bg)',
      }}>
        {(['overview', 'methods', 'quality'] as const).map(tab => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            style={{
              flex: 1,
              padding: '12px',
              background: 'none',
              border: 'none',
              borderBottom: activeTab === tab ? '2px solid var(--sf-accent)' : '2px solid transparent',
              color: activeTab === tab ? 'var(--sf-accent)' : 'var(--sf-muted)',
              fontSize: '12px',
              fontWeight: activeTab === tab ? '600' : '500',
              cursor: 'pointer',
              transition: 'all 0.2s ease',
            }}
          >
            {tab === 'overview' && '📊 总览对比'}
            {tab === 'methods' && '🔬 方法论对比'}
            {tab === 'quality' && '⭐ 质量评估对比'}
          </button>
        ))}
      </div>

      {/* 内容区域 - 左右分栏 */}
      <div className="content-split" style={{
        flex: 1,
        display: 'grid',
        gridTemplateColumns: '1fr 1fr',
        overflowY: 'auto',
      }}>
        {/* 左侧：Paper A */}
        <div className="paper-column paper-a" style={{
          padding: '20px',
          borderRight: '1px solid var(--sf-border)',
          overflowY: 'auto',
        }}>
          <div className="paper-header" style={{
            marginBottom: '16px',
            paddingBottom: '12px',
            borderBottom: '1px solid var(--sf-border)',
          }}>
            <h3 style={{
              fontSize: '13px',
              fontWeight: '600',
              color: 'var(--sf-accent)',
              margin: '0 0 8px 0',
            }}>
              🅰️ 论文 A
            </h3>
            <h4 style={{
              fontSize: '14px',
              fontWeight: '600',
              color: 'var(--sf-text)',
              margin: 0,
              lineHeight: '1.4',
            }}>
              {paperA.title}
            </h4>
            {paperA.year && (
              <div style={{
                marginTop: '8px',
                fontSize: '11px',
                color: 'var(--sf-muted)',
              }}>
                {paperA.year} · {paperA.venue || 'Unknown Venue'}
              </div>
            )}
          </div>

          {activeTab === 'overview' && (
            <div className="overview-content" style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              <div>
                <div style={{ fontSize: '11px', color: 'var(--sf-muted)', marginBottom: '4px' }}>摘要</div>
                <p style={{
                  fontSize: '12px',
                  color: 'var(--sf-text)',
                  lineHeight: '1.6',
                  margin: 0,
                }}>
                  {paperA.abstract || '无摘要'}
                </p>
              </div>
              <div style={{
                display: 'grid',
                gridTemplateColumns: '1fr 1fr',
                gap: '8px',
                marginTop: '8px',
              }}>
                <StatCard label="引用数" value={paperA.citation_count?.toString() || '0'} />
                <StatCard label="置信度" value={(paperA.confidence_score || 0).toFixed(2)} />
                {reviewA && (
                  <>
                    <StatCard label="质量评分" value={`${reviewA.quality_score}/10`} />
                    <StatCard 
                      label="评审建议" 
                      value={reviewA.recommendation.toUpperCase()}
                      color={reviewA.recommendation === 'adopt' ? '#22c55e' : reviewA.recommendation === 'cautious' ? '#eab308' : '#ef4444'}
                    />
                  </>
                )}
              </div>
            </div>
          )}

          {activeTab === 'methods' && (
            <div className="methods-content">
              <div style={{ fontSize: '11px', color: 'var(--sf-muted)', marginBottom: '8px' }}>研究方法</div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                {(paperA.methods || []).length > 0 ? (
                  paperA.methods!.map(method => (
                    <span key={method} style={{
                      padding: '4px 10px',
                      backgroundColor: 'var(--sf-accent)',
                      color: 'white',
                      borderRadius: '12px',
                      fontSize: '10px',
                      fontWeight: '500',
                    }}>
                      {method}
                    </span>
                  ))
                ) : (
                  <span style={{ fontSize: '11px', color: 'var(--sf-muted)' }}>暂无方法论标签</span>
                )}
              </div>
              {reviewA && reviewA.methodology_issues.length > 0 && (
                <div style={{ marginTop: '16px' }}>
                  <div style={{ fontSize: '11px', color: '#ef4444', marginBottom: '6px', fontWeight: '600' }}>
                    ⚠️ 方法论问题
                  </div>
                  <ul style={{
                    margin: 0,
                    paddingLeft: '16px',
                    fontSize: '11px',
                    color: 'var(--sf-text)',
                    lineHeight: '1.6',
                  }}>
                    {reviewA.methodology_issues.map((issue, i) => (
                      <li key={i}>{issue}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}

          {activeTab === 'quality' && reviewA && (
            <div className="quality-content" style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              <div>
                <div style={{ fontSize: '11px', color: 'var(--sf-muted)', marginBottom: '6px' }}>优点</div>
                <ul style={{
                  margin: 0,
                  paddingLeft: '16px',
                  fontSize: '11px',
                  color: '#22c55e',
                  lineHeight: '1.6',
                }}>
                  {reviewA.strengths.map((item, i) => (
                    <li key={i}>{item}</li>
                  ))}
                </ul>
              </div>
              <div>
                <div style={{ fontSize: '11px', color: 'var(--sf-muted)', marginBottom: '6px' }}>缺陷</div>
                <ul style={{
                  margin: 0,
                  paddingLeft: '16px',
                  fontSize: '11px',
                  color: '#ef4444',
                  lineHeight: '1.6',
                }}>
                  {reviewA.weaknesses.map((item, i) => (
                    <li key={i}>{item}</li>
                  ))}
                </ul>
              </div>
              <div style={{
                marginTop: '8px',
                padding: '10px',
                backgroundColor: 'var(--sf-bg)',
                borderRadius: '6px',
                border: '1px solid var(--sf-border)',
              }}>
                <div style={{ fontSize: '11px', color: 'var(--sf-muted)', marginBottom: '4px' }}>评审理由</div>
                <p style={{
                  fontSize: '11px',
                  color: 'var(--sf-text)',
                  lineHeight: '1.5',
                  margin: 0,
                }}>
                  {reviewA.reasoning}
                </p>
              </div>
            </div>
          )}
        </div>

        {/* 右侧：Paper B */}
        <div className="paper-column paper-b" style={{
          padding: '20px',
          overflowY: 'auto',
        }}>
          <div className="paper-header" style={{
            marginBottom: '16px',
            paddingBottom: '12px',
            borderBottom: '1px solid var(--sf-border)',
          }}>
            <h3 style={{
              fontSize: '13px',
              fontWeight: '600',
              color: '#3b82f6',
              margin: '0 0 8px 0',
            }}>
              🅱️ 论文 B
            </h3>
            <h4 style={{
              fontSize: '14px',
              fontWeight: '600',
              color: 'var(--sf-text)',
              margin: 0,
              lineHeight: '1.4',
            }}>
              {paperB.title}
            </h4>
            {paperB.year && (
              <div style={{
                marginTop: '8px',
                fontSize: '11px',
                color: 'var(--sf-muted)',
              }}>
                {paperB.year} · {paperB.venue || 'Unknown Venue'}
              </div>
            )}
          </div>

          {activeTab === 'overview' && (
            <div className="overview-content" style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              <div>
                <div style={{ fontSize: '11px', color: 'var(--sf-muted)', marginBottom: '4px' }}>摘要</div>
                <p style={{
                  fontSize: '12px',
                  color: 'var(--sf-text)',
                  lineHeight: '1.6',
                  margin: 0,
                }}>
                  {paperB.abstract || '无摘要'}
                </p>
              </div>
              <div style={{
                display: 'grid',
                gridTemplateColumns: '1fr 1fr',
                gap: '8px',
                marginTop: '8px',
              }}>
                <StatCard label="引用数" value={paperB.citation_count?.toString() || '0'} />
                <StatCard label="置信度" value={(paperB.confidence_score || 0).toFixed(2)} />
                {reviewB && (
                  <>
                    <StatCard label="质量评分" value={`${reviewB.quality_score}/10`} />
                    <StatCard 
                      label="评审建议" 
                      value={reviewB.recommendation.toUpperCase()}
                      color={reviewB.recommendation === 'adopt' ? '#22c55e' : reviewB.recommendation === 'cautious' ? '#eab308' : '#ef4444'}
                    />
                  </>
                )}
              </div>
              
              {/* 对比差异指示器 */}
              <div style={{
                marginTop: '16px',
                padding: '10px',
                backgroundColor: 'var(--sf-bg)',
                borderRadius: '6px',
                border: '1px dashed var(--sf-border)',
              }}>
                <div style={{ fontSize: '11px', color: 'var(--sf-accent)', fontWeight: '600', marginBottom: '8px' }}>
                  📈 关键差异 (B vs A)
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', fontSize: '11px' }}>
                  <DiffRow label="引用数" diff={comparisons.citationDiff} />
                  <DiffRow label="质量评分" diff={comparisons.qualityDiff} format="fixed-1" />
                  <DiffRow label="置信度" diff={comparisons.confidenceDiff} format="fixed-2" />
                  <DiffRow label="年份差" diff={comparisons.yearDiff} suffix="年" />
                </div>
              </div>
            </div>
          )}

          {activeTab === 'methods' && (
            <div className="methods-content">
              <div style={{ fontSize: '11px', color: 'var(--sf-muted)', marginBottom: '8px' }}>研究方法</div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                {(paperB.methods || []).length > 0 ? (
                  paperB.methods!.map(method => (
                    <span key={method} style={{
                      padding: '4px 10px',
                      backgroundColor: '#3b82f6',
                      color: 'white',
                      borderRadius: '12px',
                      fontSize: '10px',
                      fontWeight: '500',
                    }}>
                      {method}
                    </span>
                  ))
                ) : (
                  <span style={{ fontSize: '11px', color: 'var(--sf-muted)' }}>暂无方法论标签</span>
                )}
              </div>
              
              {/* 方法论对比 */}
              {comparisons.commonMethods.length > 0 && (
                <div style={{ marginTop: '12px', padding: '8px', backgroundColor: 'var(--sf-bg)', borderRadius: '4px' }}>
                  <div style={{ fontSize: '10px', color: 'var(--sf-muted)', marginBottom: '4px' }}>共同方法</div>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px' }}>
                    {comparisons.commonMethods.map(method => (
                      <span key={method} style={{
                        padding: '2px 8px',
                        backgroundColor: '#22c55e',
                        color: 'white',
                        borderRadius: '8px',
                        fontSize: '9px',
                      }}>
                        {method}
                      </span>
                    ))}
                  </div>
                </div>
              )}
              
              {reviewB && reviewB.methodology_issues.length > 0 && (
                <div style={{ marginTop: '16px' }}>
                  <div style={{ fontSize: '11px', color: '#ef4444', marginBottom: '6px', fontWeight: '600' }}>
                    ⚠️ 方法论问题
                  </div>
                  <ul style={{
                    margin: 0,
                    paddingLeft: '16px',
                    fontSize: '11px',
                    color: 'var(--sf-text)',
                    lineHeight: '1.6',
                  }}>
                    {reviewB.methodology_issues.map((issue, i) => (
                      <li key={i}>{issue}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}

          {activeTab === 'quality' && reviewB && (
            <div className="quality-content" style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              <div>
                <div style={{ fontSize: '11px', color: 'var(--sf-muted)', marginBottom: '6px' }}>优点</div>
                <ul style={{
                  margin: 0,
                  paddingLeft: '16px',
                  fontSize: '11px',
                  color: '#22c55e',
                  lineHeight: '1.6',
                }}>
                  {reviewB.strengths.map((item, i) => (
                    <li key={i}>{item}</li>
                  ))}
                </ul>
              </div>
              <div>
                <div style={{ fontSize: '11px', color: 'var(--sf-muted)', marginBottom: '6px' }}>缺陷</div>
                <ul style={{
                  margin: 0,
                  paddingLeft: '16px',
                  fontSize: '11px',
                  color: '#ef4444',
                  lineHeight: '1.6',
                }}>
                  {reviewB.weaknesses.map((item, i) => (
                    <li key={i}>{item}</li>
                  ))}
                </ul>
              </div>
              <div style={{
                marginTop: '8px',
                padding: '10px',
                backgroundColor: 'var(--sf-bg)',
                borderRadius: '6px',
                border: '1px solid var(--sf-border)',
              }}>
                <div style={{ fontSize: '11px', color: 'var(--sf-muted)', marginBottom: '4px' }}>评审理由</div>
                <p style={{
                  fontSize: '11px',
                  color: 'var(--sf-text)',
                  lineHeight: '1.5',
                  margin: 0,
                }}>
                  {reviewB.reasoning}
                </p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// 辅助组件：统计卡片
function StatCard({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div style={{
      padding: '8px',
      backgroundColor: 'var(--sf-bg)',
      borderRadius: '4px',
      border: '1px solid var(--sf-border)',
      textAlign: 'center',
    }}>
      <div style={{ fontSize: '9px', color: 'var(--sf-muted)', marginBottom: '2px' }}>{label}</div>
      <div style={{ 
        fontSize: '13px', 
        fontWeight: '700', 
        color: color || 'var(--sf-text)',
        fontFamily: 'monospace',
      }}>
        {value}
      </div>
    </div>
  );
}

// 辅助组件：差异行
function DiffRow({ label, diff, format = 'integer', suffix = '' }: { 
  label: string; 
  diff: number; 
  format?: 'integer' | 'fixed-1' | 'fixed-2';
  suffix?: string;
}) {
  const formattedValue = format === 'integer' 
    ? (diff > 0 ? `+${diff}` : diff.toString())
    : format === 'fixed-1'
    ? (diff > 0 ? `+${diff.toFixed(1)}` : diff.toFixed(1))
    : (diff > 0 ? `+${diff.toFixed(2)}` : diff.toFixed(2));

  const color = diff > 0 ? '#22c55e' : diff < 0 ? '#ef4444' : 'var(--sf-muted)';

  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
      <span style={{ color: 'var(--sf-muted)' }}>{label}</span>
      <span style={{ 
        color, 
        fontWeight: '600', 
        fontFamily: 'monospace',
        fontSize: '12px',
      }}>
        {formattedValue}{suffix}
      </span>
    </div>
  );
}
