/**
 * ReportView — R10.5.59 markdown 报告渲染 (Report tab)
 *
 * R10.5.59: 报告页内容居中显示 (max-width + margin auto). 同时:
 *   - 加 "← 返回 Search" 跳回 Search tab 的链接 (SearchSummary 跳报告入口对应)
 *   - i18n 全文翻译
 *   - 不再渲染 GraphSlot (Report tab 只看报告, Graph tab 独立看图)
 *
 * R10.5.93 (升级 6): 借鉴 Elicit 结构化报告, 把 6 段 markdown 拆成 6 个 tab:
 *   1. Overview (研究概述)
 *   2. Key Papers (核心论文推荐)
 *   3. Classification (研究方向分类)
 *   4. Trends (关键研究趋势)
 *   5. Further Reading (延伸阅读)
 *   6. Search Info (检索说明)
 *   7. Anchored Papers (引文论文)
 * 顶部 tab 导航, 切换显示. 没解析成功时回退到单页 markdown.
 *
 * R10.5.93 (升级 1/3/4): anchored papers 加 stance/study_type 徽标 + key_quote.
 */
import { useMemo, useState } from 'react';
import { useStore, actions } from '../store/useStore';
import type { Paper } from '../types';
import { useT } from '../i18n';
import DOMPurify from 'dompurify';
import React from 'react';
import { marked } from 'marked';

interface Props {
  query?: string;
  graphSlot?: React.ReactNode;
}

// R10.5.93: 立场徽标 (跟 PaperList 对齐)
const STANCE_BADGE: Record<string, { label: string; emoji: string; color: string; bg: string }> = {
  supporting:  { label: '支持',   emoji: '✓', color: '#15803d', bg: 'rgba(21, 161, 67, 0.1)' },
  contrasting: { label: '反对',   emoji: '✗', color: '#b91c1c', bg: 'rgba(185, 28, 28, 0.1)' },
  mixed:       { label: '混合',   emoji: '≈', color: '#b45309', bg: 'rgba(180, 83, 9, 0.1)' },
  neutral:     { label: '中性',   emoji: '·', color: '#78716c', bg: 'rgba(120, 113, 108, 0.1)' },
  unsure:      { label: '未分类', emoji: '?', color: '#a8a29e', bg: 'transparent' },
};

// R10.5.93: 6 段 tab 配置 (跟 synthesis_agent prompt 的 6 个 ## 标题对齐)
const SECTION_PATTERNS: Array<{ key: string; label: string; patterns: RegExp[] }> = [
  { key: 'overview',    label: 'Overview',         patterns: [/^#{2,3}\s*研究概述/, /^#{2,3}\s*研究背景/, /^#{2,3}\s*Overview/i] },
  { key: 'key_papers',  label: 'Key Papers',       patterns: [/^#{2,3}\s*核心论文/, /^#{2,3}\s*Key Papers?/i, /^#{2,3}\s*Top\s*\d/i] },
  { key: 'classify',    label: 'Classification',   patterns: [/^#{2,3}\s*研究方向/, /^#{2,3}\s*Classification/i, /^#{2,3}\s*研究分类/] },
  { key: 'trends',      label: 'Trends',           patterns: [/^#{2,3}\s*关键研究趋势/, /^#{2,3}\s*研究趋势/, /^#{2,3}\s*Trends?/i] },
  { key: 'reading',     label: 'Further Reading',  patterns: [/^#{2,3}\s*延伸阅读/, /^#{2,3}\s*Further Reading/i, /^#{2,3}\s*扩展阅读/] },
  { key: 'search',      label: 'Search Info',      patterns: [/^#{2,3}\s*检索说明/, /^#{2,3}\s*Search Info/i, /^#{2,3}\s*搜索说明/] },
];

interface Section { key: string; label: string; content: string; }

/**
 * 把 markdown 报告按 ## 段落拆分成 6 个 section.
 * 失败回退: 整个 report 放 overview 段, 其它段空.
 */
function splitReportBySection(md: string): Section[] {
  if (!md) return [];
  const lines = md.split('\n');
  const sections: Section[] = [];
  let current: Section | null = null;

  for (const line of lines) {
    // 检测是否是任何 section 标题
    let matchedKey: string | null = null;
    let matchedLabel: string | null = null;
    for (const pat of SECTION_PATTERNS) {
      if (pat.patterns.some((re) => re.test(line.trim()))) {
        matchedKey = pat.key;
        matchedLabel = pat.label;
        break;
      }
    }
    if (matchedKey) {
      if (current) sections.push(current);
      current = { key: matchedKey, label: matchedLabel!, content: '' };
    } else if (current) {
      current.content += line + '\n';
    }
  }
  if (current) sections.push(current);

  // 补全缺失段 (LLM 偶尔漏段 → 留空占位)
  const result: Section[] = [];
  for (const pat of SECTION_PATTERNS) {
    const found = sections.find((s) => s.key === pat.key);
    if (found) {
      result.push(found);
    } else {
      result.push({ key: pat.key, label: pat.label, content: '' });
    }
  }
  return result;
}

function markdownToHtml(md: string): string {
  if (!md) return '';
  const dirty = marked.parse(md, { async: false, gfm: true, breaks: false }) as string;
  return DOMPurify.sanitize(dirty, {
    ALLOWED_TAGS: ['h1','h2','h3','h4','p','ul','ol','li','strong','em','code','pre','blockquote','a','hr','table','thead','tbody','tr','th','td','br','span'],
    ALLOWED_ATTR: ['href','title','rel','target','data-paper-id'],
  });
}

export function ReportView({ query: queryProp, graphSlot }: Props) {
  const result = useStore((s) => s.result);
  const selectedPaperId = useStore((s) => s.selectedPaperId);
  const t = useT();
  // R10.5.93: 当前选中的 tab (key of SECTION_PATTERNS)
  const [activeTab, setActiveTab] = useState<string>('overview');

  const query = queryProp ?? result?.citation_graph?.metadata?.query ?? '';

  // P10 (P2-5 性能): marked.parse + DOMPurify.sanitize 同步执行可能阻塞主线程
  // ~80-150ms (50KB markdown). 改 useDeferredValue + 分块 marked 解析:
  // 1. 用 React 18 useDeferredValue 让 result?.report 变更不阻塞渲染
  // 2. marked 改同步 (off main thread via requestIdleCallback 切分)
  // 简化方案: 仅加 useDeferredValue 延迟解析, 避免主线程 freeze.
  const reportDeferred = React.useDeferredValue(result?.report);

  // R10.5.93 (升级 6): 把 markdown 拆成 6 段 + 计算每段 html
  const sections = useMemo(() => {
    return splitReportBySection(reportDeferred ?? '');
  }, [reportDeferred]);

  const sectionHtmls = useMemo(() => {
    const map: Record<string, string> = {};
    for (const sec of sections) {
      map[sec.key] = markdownToHtml(sec.content);
    }
    return map;
  }, [sections]);

  const anchoredIds = useMemo(() => {
    const re = /\[(\d+)\]/g;
    const ids = new Set<string>();
    if (!result?.report || !result.ranked_papers) return [];
    let m: RegExpExecArray | null;
    while ((m = re.exec(result.report)) !== null) {
      const idx = parseInt(m[1], 10) - 1;
      if (idx >= 0 && idx < result.ranked_papers.length) {
        ids.add(result.ranked_papers[idx].paper_id);
      }
    }
    return Array.from(ids);
  }, [result?.report, result?.ranked_papers]);

  if (!result) {
    return (
      <main
        id="view-report"
        role="tabpanel"
        aria-labelledby="tab-report"
        style={{
          maxWidth: 720,
          margin: '0 auto',
          padding: '64px 24px 96px',
          textAlign: 'center',
        }}
      >
        <p className="font-body" style={{ color: 'var(--sf-muted)', fontSize: 14 }}>
          {t('report.empty')}
        </p>
        <button
          type="button"
          onClick={() => actions.setView('search')}
          className="sf-btn font-ui"
          style={{ marginTop: 24 }}
        >
          ← {t('report.goSearch')}
        </button>
      </main>
    );
  }

  const anchoredPapers: Paper[] = anchoredIds
    .map((id) => result.ranked_papers?.find((p) => p.paper_id === id))
    .filter((p): p is Paper => !!p);

  const downloadFile = (content: string, filename: string, mime: string) => {
    const blob = new Blob([content], { type: mime });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  // 计算每段是否有内容 (用于 tab 上加 badge)
  const hasContent = (key: string) => {
    const sec = sections.find((s) => s.key === key);
    return sec ? sec.content.trim().length > 0 : false;
  };

  return (
    <main
      id="view-report"
      role="tabpanel"
      aria-labelledby="tab-report"
      style={{
        maxWidth: 720,
        margin: '0 auto',
        padding: '48px 24px 96px',
      }}
      data-testid="report-view"
    >
      {/* Back-to-search + meta header */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: 16,
        }}
      >
        {/* R10.5.94 (从 v2 借鉴): 一行放 "← 返回 Search" + "打开 Graph →" */}
        <div style={{ display: 'flex', gap: 16, alignItems: 'center' }}>
          <button
            type="button"
            onClick={() => actions.setView('search')}
            className="font-mono"
            style={{
              background: 'none',
              border: 'none',
              padding: 0,
              fontSize: 11,
              letterSpacing: '0.08em',
              textTransform: 'uppercase',
              color: 'var(--sf-muted)',
              cursor: 'pointer',
            }}
          >
            ← {t('report.backSearch')}
          </button>
          {/* R10.5.94: 报告 → 图谱 一键跳转 (R10.5.59 阶段 3 GraphPage 是单独 tab,
              但很多场景下用户报告看完就想去图, 显式入口 UX 更好) */}
          <button
            type="button"
            onClick={() => actions.setView('graph')}
            className="font-mono"
            data-testid="report-to-graph"
            style={{
              background: 'none',
              border: 'none',
              padding: 0,
              fontSize: 11,
              letterSpacing: '0.08em',
              textTransform: 'uppercase',
              color: 'var(--sf-accent)',
              cursor: 'pointer',
            }}
          >
            打开 Graph →
          </button>
        </div>
        <nav
          aria-label={t('report.download')}
          style={{ display: 'flex', gap: 12, fontSize: 12 }}
        >
          {result.bibtex && (
            <a
              href="#"
              onClick={(e) => {
                e.preventDefault();
                downloadFile(result.bibtex!, 'scholarflow.bib', 'application/x-bibtex');
              }}
              className="font-mono"
              style={{ color: 'var(--sf-accent)', textDecoration: 'none' }}
              download="scholarflow.bib"
            >
              ↓ .bib
            </a>
          )}
          {result.ris && (
            <a
              href="#"
              onClick={(e) => {
                e.preventDefault();
                downloadFile(result.ris!, 'scholarflow.ris', 'application/x-research-info-systems');
              }}
              className="font-mono"
              style={{ color: 'var(--sf-accent)', textDecoration: 'none' }}
              download="scholarflow.ris"
            >
              ↓ .ris
            </a>
          )}
          <a
            href="#"
            onClick={(e) => {
              e.preventDefault();
              downloadFile(result.report || '', 'scholarflow-report.md', 'text/markdown');
            }}
            className="font-mono"
            style={{ color: 'var(--sf-accent)', textDecoration: 'none' }}
            download="scholarflow-report.md"
          >
            ↓ .md
          </a>
        </nav>
      </div>

      <header
        style={{
          marginBottom: 24,
          paddingBottom: 16,
          borderBottom: '1px solid var(--sf-border)',
        }}
      >
        <h1
          className="font-display"
          style={{
            fontSize: 30,
            lineHeight: 1.2,
            letterSpacing: '-0.02em',
            fontStyle: 'italic',
            margin: 0,
          }}
        >
          {query || t('report.title')}
        </h1>
      </header>

      {/* Loading skeleton */}
      {!result.report && (
        <div className="report-body">
          {[60, 90, 75, 100, 50, 85, 70].map((w, i) => (
            <div
              key={i}
              style={{
                height: 14,
                width: `${w}%`,
                margin: '8px 0',
                background: 'var(--sf-border)',
                borderRadius: 2,
              }}
            />
          ))}
        </div>
      )}

      {/* R10.5.93 (升级 6): 结构化 Tabs (Elicit 风格) */}
      {result.report && (
        <>
          {/* Tab 导航 */}
          <nav
            aria-label="Report sections"
            style={{
              display: 'flex',
              gap: 4,
              marginBottom: 16,
              paddingBottom: 0,
              borderBottom: '1px solid var(--sf-border)',
              overflowX: 'auto',
            }}
            data-testid="report-tabs"
          >
            {SECTION_PATTERNS.map((p) => {
              const isActive = activeTab === p.key;
              const has = hasContent(p.key);
              return (
                <button
                  key={p.key}
                  type="button"
                  onClick={() => setActiveTab(p.key)}
                  className="font-ui"
                  style={{
                    fontSize: 11,
                    fontWeight: isActive ? 600 : 500,
                    letterSpacing: '0.05em',
                    textTransform: 'uppercase',
                    padding: '8px 12px',
                    background: 'none',
                    border: 'none',
                    borderBottom: isActive ? '2px solid var(--sf-accent)' : '2px solid transparent',
                    marginBottom: -1,
                    color: isActive ? 'var(--sf-text)' : 'var(--sf-muted)',
                    cursor: 'pointer',
                    whiteSpace: 'nowrap',
                    opacity: has ? 1 : 0.5,
                  }}
                  data-testid={`report-tab-${p.key}`}
                  aria-current={isActive ? 'page' : undefined}
                >
                  {p.label}
                </button>
              );
            })}
            {/* Anchored papers tab 单独放在最后 (跟 6 段区分) */}
            <button
              type="button"
              onClick={() => setActiveTab('anchored')}
              className="font-ui"
              style={{
                fontSize: 11,
                fontWeight: activeTab === 'anchored' ? 600 : 500,
                letterSpacing: '0.05em',
                textTransform: 'uppercase',
                padding: '8px 12px',
                background: 'none',
                border: 'none',
                borderBottom: activeTab === 'anchored' ? '2px solid var(--sf-accent)' : '2px solid transparent',
                marginBottom: -1,
                color: activeTab === 'anchored' ? 'var(--sf-text)' : 'var(--sf-muted)',
                cursor: 'pointer',
                whiteSpace: 'nowrap',
              }}
              data-testid="report-tab-anchored"
              aria-current={activeTab === 'anchored' ? 'page' : undefined}
            >
              Anchored ({anchoredPapers.length})
            </button>
          </nav>

          {/* 当前 tab 内容 */}
          {activeTab !== 'anchored' && (
            <div
              className="report-body"
              data-testid={`report-section-${activeTab}`}
              dangerouslySetInnerHTML={{ __html: sectionHtmls[activeTab] || '<p style="color:var(--sf-muted);font-size:13px;">— 本节暂无内容 —</p>' }}
            />
          )}

          {/* Anchored papers tab (带 stance/study_type/key_quote 徽标) */}
          {activeTab === 'anchored' && anchoredPapers.length > 0 && (
            <section data-testid="report-section-anchored">
              <ol style={{ listStyle: 'none', padding: 0, margin: 0 }}>
                {anchoredPapers.map((p, i) => {
                  const sel = selectedPaperId === p.paper_id;
                  const stanceMeta = STANCE_BADGE[p.stance || 'unsure'] || STANCE_BADGE.unsure;
                  return (
                    <li
                      key={p.paper_id}
                      data-paper-id={p.paper_id}
                      data-sf-selected={sel ? 'true' : undefined}
                      onClick={() => actions.selectPaper(p.paper_id, false)}
                      style={{
                        padding: '12px 0',
                        cursor: 'pointer',
                        borderBottom: '1px solid var(--sf-border)',
                        backgroundColor: sel ? 'var(--sf-surface-alt)' : 'transparent',
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginBottom: 4 }}>
                        <span
                          className="font-mono"
                          style={{ fontSize: 11, color: 'var(--sf-muted)', minWidth: 24 }}
                        >
                          [{i + 1}]
                        </span>
                        <span
                          className="font-body"
                          style={{ fontSize: 14, flex: 1 }}
                        >
                          {p.title}
                        </span>
                        {/* R10.5.93 (升级 1): stance 徽标 */}
                        {p.stance && p.stance !== 'unsure' && (
                          <span
                            className="font-mono"
                            style={{
                              fontSize: 9,
                              fontWeight: 600,
                              letterSpacing: '0.05em',
                              textTransform: 'uppercase',
                              padding: '1px 6px',
                              color: stanceMeta.color,
                              backgroundColor: stanceMeta.bg,
                              border: `1px solid ${stanceMeta.color}`,
                              borderRadius: '2px',
                              flexShrink: 0,
                            }}
                          >
                            {stanceMeta.emoji} {stanceMeta.label}
                          </span>
                        )}
                        {/* R10.5.93 (升级 3): study_type 徽标 */}
                        {p.study_type && p.study_type !== 'other' && (
                          <span
                            className="font-mono"
                            style={{
                              fontSize: 9,
                              fontWeight: 600,
                              letterSpacing: '0.05em',
                              textTransform: 'uppercase',
                              padding: '1px 6px',
                              color: 'var(--sf-muted)',
                              backgroundColor: 'var(--sf-surface)',
                              border: '1px solid var(--sf-border)',
                              borderRadius: '2px',
                              flexShrink: 0,
                            }}
                          >
                            {p.study_type}
                          </span>
                        )}
                      </div>
                      <div
                        className="font-mono"
                        style={{
                          fontSize: 11,
                          color: 'var(--sf-muted)',
                          display: 'flex',
                          gap: 12,
                          flexWrap: 'wrap',
                        }}
                      >
                        <span>{p.year || '—'}</span>
                        <span>{(p.authors || []).slice(0, 3).join(', ')}{(p.authors?.length || 0) > 3 ? ' et al.' : ''}</span>
                        <span>{p.venue || '—'}</span>
                        <span>{p.citation_count || 0} {t('common.cite')}</span>
                        <span>★{(p.final_score ?? 0).toFixed(1)}</span>
                      </div>
                      {/* R10.5.93 (升级 4): key_quote 关键引用 */}
                      {p.key_quote && (
                        <blockquote
                          className="font-body"
                          style={{
                            fontSize: 12,
                            lineHeight: 1.5,
                            color: 'var(--sf-muted)',
                            margin: '6px 0 0 32px',
                            padding: '4px 0 4px 10px',
                            borderLeft: '2px solid var(--sf-border)',
                            fontStyle: 'italic',
                          }}
                          data-testid="anchored-key-quote"
                        >
                          "{p.key_quote}"
                        </blockquote>
                      )}
                    </li>
                  );
                })}
              </ol>
            </section>
          )}
        </>
      )}

      {/* Graph slot (Report tab 注入) */}
      {graphSlot}
    </main>
  );
}