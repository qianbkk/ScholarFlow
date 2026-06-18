/**
 * P0: 智能过滤器面板 (Smart Filter Panel)
 * 灵感来自 FanBox 的文件过滤功能
 * 
 * 功能:
 * - 时间范围直方图 (近 1 年/3 年/5 年)
 * - 方法论文本云 (RCT/Meta-analysis/Review)
 * - 置信度滑块 (>0.7 / >0.9)
 * - 本地前端快速过滤，避免重复请求后端
 */
import { useMemo, useState, useCallback } from 'react';

export interface PaperFilters {
  yearRange: 'all' | '1' | '3' | '5';
  methods: string[];
  minConfidence: number;
  minQualityScore: number;
}

interface Paper {
  paper_id: string;
  title: string;
  abstract?: string;
  year?: number;
  confidence_score?: number;
  quality_score?: number;
  methods?: string[];
  citation_count?: number;
}

interface Props {
  papers: Paper[];
  filters: PaperFilters;
  onFiltersChange: (filters: PaperFilters) => void;
}

const COMMON_METHODS = [
  'RCT', 'Meta-analysis', 'Systematic Review', 'Qualitative',
  'Quantitative', 'Longitudinal', 'Cross-sectional', 'Case Study',
  'Experimental', 'Observational', 'Simulation', 'Theoretical'
];

export function FilterPanel({ papers, filters, onFiltersChange }: Props) {
  const [expandedSection, setExpandedSection] = useState<string | null>('year');

  // 计算年份分布
  const yearDistribution = useMemo(() => {
    const dist: Record<number, number> = {};
    papers.forEach(paper => {
      const year = paper.year || new Date().getFullYear();
      dist[year] = (dist[year] || 0) + 1;
    });
    return Object.entries(dist)
      .map(([year, count]) => ({ year: parseInt(year), count }))
      .sort((a, b) => b.year - a.year);
  }, [papers]);

  // 计算方法词频
  const methodFrequency = useMemo(() => {
    const freq: Record<string, number> = {};
    papers.forEach(paper => {
      const methods = paper.methods || [];
      methods.forEach(method => {
        freq[method] = (freq[method] || 0) + 1;
      });
    });
    return Object.entries(freq)
      .filter(([_, count]) => count >= 1)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 20);
  }, [papers]);

  // 计算质量分数分布
  const qualityStats = useMemo(() => {
    if (papers.length === 0) return { min: 0, max: 10, avg: 0 };
    const scores = papers.map(p => p.quality_score || 0).filter(s => s > 0);
    if (scores.length === 0) return { min: 0, max: 10, avg: 0 };
    return {
      min: Math.min(...scores),
      max: Math.max(...scores),
      avg: scores.reduce((a, b) => a + b, 0) / scores.length,
    };
  }, [papers]);

  const handleYearRangeChange = useCallback((range: PaperFilters['yearRange']) => {
    onFiltersChange({ ...filters, yearRange: range });
  }, [filters, onFiltersChange]);

  const handleMethodToggle = useCallback((method: string) => {
    const current = filters.methods;
    const updated = current.includes(method)
      ? current.filter(m => m !== method)
      : [...current, method];
    onFiltersChange({ ...filters, methods: updated });
  }, [filters, onFiltersChange]);

  const handleConfidenceChange = useCallback((value: number) => {
    onFiltersChange({ ...filters, minConfidence: value });
  }, [filters, onFiltersChange]);

  const handleQualityScoreChange = useCallback((value: number) => {
    onFiltersChange({ ...filters, minQualityScore: value });
  }, [filters, onFiltersChange]);

  const toggleSection = useCallback((section: string) => {
    setExpandedSection(expandedSection === section ? null : section);
  }, [expandedSection]);

  return (
    <div className="smart-filter-panel" style={{
      width: '260px',
      backgroundColor: 'var(--sf-bg-elev)',
      borderRight: '1px solid var(--sf-border)',
      padding: '16px 12px',
      overflowY: 'auto',
      display: 'flex',
      flexDirection: 'column',
      gap: '16px',
    }}>
      {/* 面板标题 */}
      <div className="filter-header" style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        paddingBottom: '8px',
        borderBottom: '1px solid var(--sf-border)',
      }}>
        <h3 style={{
          fontSize: '13px',
          fontWeight: '600',
          color: 'var(--sf-text)',
          margin: 0,
        }}>
          🔍 智能过滤器
        </h3>
        <span style={{
          fontSize: '10px',
          color: 'var(--sf-muted)',
          fontFamily: 'monospace',
        }}>
          {papers.length} 篇文献
        </span>
      </div>

      {/* 年份过滤器 */}
      <div className="filter-section">
        <button
          onClick={() => toggleSection('year')}
          style={{
            width: '100%',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            padding: '8px',
            background: 'none',
            border: 'none',
            cursor: 'pointer',
            color: 'var(--sf-text)',
            fontSize: '12px',
            fontWeight: '600',
          }}
        >
          <span>📅 发表年份</span>
          <span style={{ fontSize: '10px' }}>{expandedSection === 'year' ? '▼' : '▶'}</span>
        </button>
        
        {expandedSection === 'year' && (
          <div className="year-filters" style={{
            display: 'flex',
            flexDirection: 'column',
            gap: '6px',
            marginTop: '8px',
          }}>
            {(['all', '1', '3', '5'] as const).map(range => (
              <button
                key={range}
                onClick={() => handleYearRangeChange(range)}
                style={{
                  padding: '6px 10px',
                  borderRadius: '4px',
                  border: `1px solid ${filters.yearRange === range ? 'var(--sf-accent)' : 'var(--sf-border)'}`,
                  backgroundColor: filters.yearRange === range ? 'var(--sf-accent)' : 'transparent',
                  color: filters.yearRange === range ? 'white' : 'var(--sf-text)',
                  fontSize: '11px',
                  cursor: 'pointer',
                  textAlign: 'left',
                }}
              >
                {range === 'all' ? '全部年份' : `近${range}年`}
                {range !== 'all' && (
                  <span style={{
                    float: 'right',
                    opacity: 0.7,
                    fontSize: '10px',
                  }}>
                    {yearDistribution.filter(d => d.year >= new Date().getFullYear() - parseInt(range)).reduce((sum, d) => sum + d.count, 0)}
                  </span>
                )}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* 方法论过滤器 */}
      <div className="filter-section">
        <button
          onClick={() => toggleSection('methods')}
          style={{
            width: '100%',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            padding: '8px',
            background: 'none',
            border: 'none',
            cursor: 'pointer',
            color: 'var(--sf-text)',
            fontSize: '12px',
            fontWeight: '600',
          }}
        >
          <span>🔬 研究方法</span>
          <span style={{ fontSize: '10px' }}>{expandedSection === 'methods' ? '▼' : '▶'}</span>
        </button>
        
        {expandedSection === 'methods' && (
          <div className="method-cloud" style={{
            display: 'flex',
            flexWrap: 'wrap',
            gap: '6px',
            marginTop: '8px',
          }}>
            {methodFrequency.length > 0 ? (
              methodFrequency.map(([method, count]) => (
                <button
                  key={method}
                  onClick={() => handleMethodToggle(method)}
                  style={{
                    padding: '4px 8px',
                    borderRadius: '12px',
                    border: `1px solid ${filters.methods.includes(method) ? 'var(--sf-accent)' : 'var(--sf-border)'}`,
                    backgroundColor: filters.methods.includes(method) ? 'var(--sf-accent)' : 'transparent',
                    color: filters.methods.includes(method) ? 'white' : 'var(--sf-text)',
                    fontSize: '10px',
                    cursor: 'pointer',
                    transition: 'all 0.15s ease',
                  }}
                >
                  {method}
                  <span style={{
                    marginLeft: '4px',
                    opacity: 0.7,
                    fontSize: '9px',
                  }}>
                    ({count})
                  </span>
                </button>
              ))
            ) : (
              <div style={{
                width: '100%',
                padding: '8px',
                textAlign: 'center',
                color: 'var(--sf-muted)',
                fontSize: '11px',
              }}>
                暂无方法论标签
              </div>
            )}
          </div>
        )}
      </div>

      {/* 置信度过滤器 */}
      <div className="filter-section">
        <button
          onClick={() => toggleSection('confidence')}
          style={{
            width: '100%',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            padding: '8px',
            background: 'none',
            border: 'none',
            cursor: 'pointer',
            color: 'var(--sf-text)',
            fontSize: '12px',
            fontWeight: '600',
          }}
        >
          <span>🎯 置信度阈值</span>
          <span style={{ fontSize: '10px' }}>{expandedSection === 'confidence' ? '▼' : '▶'}</span>
        </button>
        
        {expandedSection === 'confidence' && (
          <div className="confidence-slider" style={{
            marginTop: '8px',
            padding: '0 4px',
          }}>
            <input
              type="range"
              min="0"
              max="1"
              step="0.05"
              value={filters.minConfidence}
              onChange={(e) => handleConfidenceChange(parseFloat(e.target.value))}
              style={{
                width: '100%',
                height: '4px',
                appearance: 'none',
                background: 'linear-gradient(to right, var(--sf-accent) 0%, var(--sf-accent) ' + 
                            (filters.minConfidence * 100) + '%, var(--sf-border) ' +
                            (filters.minConfidence * 100) + '%, var(--sf-border) 100%)',
                borderRadius: '2px',
                outline: 'none',
                cursor: 'pointer',
              }}
            />
            <div style={{
              display: 'flex',
              justifyContent: 'space-between',
              marginTop: '6px',
              fontSize: '10px',
              color: 'var(--sf-muted)',
              fontFamily: 'monospace',
            }}>
              <span>0.0</span>
              <span style={{ color: 'var(--sf-accent)', fontWeight: '600' }}>
                ≥{filters.minConfidence.toFixed(2)}
              </span>
              <span>1.0</span>
            </div>
            <div style={{
              marginTop: '8px',
              padding: '6px',
              backgroundColor: 'var(--sf-bg)',
              borderRadius: '4px',
              fontSize: '10px',
              color: 'var(--sf-muted)',
            }}>
              过滤后：{papers.filter(p => (p.confidence_score || 0) >= filters.minConfidence).length} 篇
            </div>
          </div>
        )}
      </div>

      {/* 质量分数过滤器 */}
      <div className="filter-section">
        <button
          onClick={() => toggleSection('quality')}
          style={{
            width: '100%',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            padding: '8px',
            background: 'none',
            border: 'none',
            cursor: 'pointer',
            color: 'var(--sf-text)',
            fontSize: '12px',
            fontWeight: '600',
          }}
        >
          <span>⭐ Critic 质量评分</span>
          <span style={{ fontSize: '10px' }}>{expandedSection === 'quality' ? '▼' : '▶'}</span>
        </button>
        
        {expandedSection === 'quality' && (
          <div className="quality-slider" style={{
            marginTop: '8px',
            padding: '0 4px',
          }}>
            <input
              type="range"
              min="0"
              max="10"
              step="1"
              value={filters.minQualityScore}
              onChange={(e) => handleQualityScoreChange(parseInt(e.target.value))}
              style={{
                width: '100%',
                height: '4px',
                appearance: 'none',
                background: 'linear-gradient(to right, #ef4444 0%, #f97316 50%, #22c55e 100%)',
                borderRadius: '2px',
                outline: 'none',
                cursor: 'pointer',
              }}
            />
            <div style={{
              display: 'flex',
              justifyContent: 'space-between',
              marginTop: '6px',
              fontSize: '10px',
              color: 'var(--sf-muted)',
              fontFamily: 'monospace',
            }}>
              <span>0</span>
              <span style={{ color: 'var(--sf-accent)', fontWeight: '600' }}>
                ≥{filters.minQualityScore}/10
              </span>
              <span>10</span>
            </div>
            <div style={{
              marginTop: '8px',
              padding: '6px',
              backgroundColor: 'var(--sf-bg)',
              borderRadius: '4px',
              fontSize: '10px',
              color: 'var(--sf-muted)',
            }}>
              平均分：{qualityStats.avg.toFixed(1)} | 过滤后：{papers.filter(p => (p.quality_score || 0) >= filters.minQualityScore).length} 篇
            </div>
          </div>
        )}
      </div>

      {/* 重置按钮 */}
      <button
        onClick={() => onFiltersChange({
          yearRange: 'all',
          methods: [],
          minConfidence: 0,
          minQualityScore: 0,
        })}
        style={{
          marginTop: 'auto',
          padding: '8px',
          borderRadius: '4px',
          border: '1px solid var(--sf-border)',
          backgroundColor: 'transparent',
          color: 'var(--sf-muted)',
          fontSize: '11px',
          cursor: 'pointer',
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
        🔄 重置所有过滤器
      </button>
    </div>
  );
}
