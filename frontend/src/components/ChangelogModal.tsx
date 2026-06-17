/**
 * R10.5.30 (D6 P1-3): 升级日志 modal
 *
 * 永久可见的"本次升级"链接 (在 footer), 打开后展示 R10.5.28 → R10.5.30
 * 累积的所有升级条目. 取代 R10.5.29 的一次性 R10_5_28Banner (该 banner
 * sessionStorage 记录已阅, 关闭就看不到).
 *
 * 设计:
 *  - modal 风格统一 (跟 LoginDialog / CommandPalette 一致)
 *  - 8 个升级条目的数据驱动 (CHANGELOG_NOTES)
 *  - ESC 关闭 / 点遮罩关闭
 *  - sessionStorage 'sf-changelog-dismissed-30' 记录 'dismissed' 状态,
 *    升级到 R10.5.31 时改 key 重置
 */
import { useEffect } from 'react';

interface ChangelogNote {
  emoji: string;
  title: string;
  body: string;
  tag: string;
  tagColor: string;
}

const CHANGELOG_NOTES: ChangelogNote[] = [
  {
    emoji: '🧠',
    title: '前端架构 4-Context 拆分 (CD.txt §7 illusion of sophistication)',
    body: 'F4: App.tsx 13 个 useState 散落 → 4 个 Context (App / Selection / UI / Search), useReducer 管选中态, useMemo 防重渲染. 删双 Cmd+K 监听器冲突. App.tsx -71 行, 子组件 import { useApp } 即可.',
    tag: 'F4',
    tagColor: 'var(--sf-accent)',
  },
  {
    emoji: '🌊',
    title: '优雅 shutdown + /health version 联动 (R10.5.32 wave 7)',
    body: 'lifespan shutdown 等 in-flight 搜索 (≤30s) + 跑 cache GC. /health + /health/detailed + / 三处 version 字段从 VERSION 文件读, 跟 pyproject.toml + CHANGELOG 同步. K8s 滚动更新 0 报错.',
    tag: 'wave 7',
    tagColor: 'var(--sf-accent)',
  },
  {
    emoji: '🦠',
    title: 'CD.txt §3.1 缓解 — 9 agent 节点 0 单测 → 10 个',
    body: 'R10.5.33: critic_review_node (空 / 多论文 / LLM 异常 / 切片 [:10]) + query_decomposer._fallback_decompose + _fallback_constraints + _sanitize_str_list 共 10 个 case. 后续扩到 7 个剩余 agent.',
    tag: 'R10.5.33',
    tagColor: 'var(--sf-accent)',
  },
  {
    emoji: '🎯',
    title: 'CommandPalette 13 命令接真 (F5)',
    body: '11 真 handler (export 3 + filter 3 + theme 循环 + reset + focus + 2 view) + 2 stub (summarize/critique 等后端 agent endpoint). Cmd+K 走 UIContext 集中.',
    tag: 'F5',
    tagColor: 'rgb(168, 85, 247)',
  },
  {
    emoji: '🗃',
    title: 'DB migration 框架 (F6)',
    body: 'apply_migration(name, fn) helper + _schema_migrations 表, 4 条历史迁移 (H8 query 删列 / R10.5.28 password 3 列 / stream_tokens / sessions) 全部接入, 幂等可重跑.',
    tag: 'F6',
    tagColor: 'rgb(168, 85, 247)',
  },
  {
    emoji: '⏱',
    title: 'e2e / perf 阈值 env-driven (F3)',
    body: 'mock 模式 8 节点实测 30-180s, 30s 阈值是健康检查上限不是流水线 SLA. 改 PIPELINE_E2E_TIMEOUT=300 / PERF_PER_QUERY_TIMEOUT=60 / PERF_TOTAL_TIMEOUT=300 env-driven, CI 默认值保持向后兼容.',
    tag: 'F3',
    tagColor: 'var(--sf-accent)',
  },
  {
    emoji: '🔌',
    title: 'force_mock_api + circuit breaker + critic tuple unpack (F2)',
    body: 'F2: critic_agent call_llm 返 (text, usage) tuple 没 unpack → 10 次评审 AttributeError. force_mock_api 改 _runtime_mode_override["mode"]="mock" 让所有 caller 走 mock. conftest autouse 加 circuit breaker reset.',
    tag: 'F2',
    tagColor: 'var(--sf-accent)',
  },
  {
    emoji: '🧹',
    title: 'D3 state pollution 根治 (F1)',
    body: 'F1: conftest _reset_global_state 加 4 项 (OPEN_MODE 双 module / cache._DB / circuit breaker / runtime_mode override), test_auth_api_key 4 case 加 _stub_request 满足 D3 新签名, 11 个 d3_session_cookies test 跨文件不再污染.',
    tag: 'F1',
    tagColor: 'var(--sf-accent)',
  },
  {
    emoji: '🔐',
    title: 'API Key → HttpOnly Cookie (CG.txt P0 #1 真修)',
    body: 'D3: 长期 API Key 从前端 localStorage 改走后端 HttpOnly cookie session, 双重提交 cookie 防 CSRF. XSS 偷走后攻击窗口缩到 session 24h 过期. 前端 fetch credentials: "include" 即可.',
    tag: 'D3 P0-1',
    tagColor: 'var(--sf-accent)',
  },
  {
    emoji: '🧪',
    title: '本地论文库真接入 (CD.txt 隐性问题)',
    body: 'D4: 50+ 篇 mock 论文改走 local_papers_db 包装, Paper.source="local_demo" 真实标签. QueryPanel "本地演示" badge 亮起, 用户能区分演示 / 真实数据.',
    tag: 'D4 P1-1',
    tagColor: 'rgb(168, 85, 247)',
  },
  {
    emoji: '🗂',
    title: '多选论文 + CompareDrawer 触发 (D5)',
    body: 'Shift+click 论文凑齐 2 篇 → CompareDrawer 自动显示. 紫色左边框标记多选状态.',
    tag: 'D5 P1-2',
    tagColor: 'rgb(168, 85, 247)',
  },
  {
    emoji: '🧹',
    title: 'main.py 拆 1115 → 547 行 (CG.txt P1 #5)',
    body: 'D2: search/search_stream/cancel_search 抽到 backend/api/routes/search.py, main.py 只剩 lifespan + middleware + router 挂载. 翻转了 R10.5.24 静态 guard 锁死的反模式.',
    tag: 'D2 P0-2',
    tagColor: 'var(--sf-accent)',
  },
  {
    emoji: '🛡',
    title: 'critic_agent kwargs 修复 + 7 项审计修复 (D1)',
    body: 'D1 + code-review R10.5.29: critic_agent 旧版传 model=/temperature= (call_llm 不接受) 触发 10 次重试, 8 节点流水线撞 60s 超时. 改用 model_override= + task_type="fast" + json_mode=True.',
    tag: 'D1 P0-3',
    tagColor: 'var(--sf-accent)',
  },
  {
    emoji: '⚡',
    title: '/simplify 8 项 cleanup + 1 项真 bug',
    body: 'R10.5.29: semantic_cache LRU key 加 runtime_mode 修跨模式污染. api.ts getApiKey module-scope 缓存 (省 50 次 storage read/min). 删 FilterPanel 死代码 (-454 行).',
    tag: 'R10.5.29',
    tagColor: 'var(--sf-muted)',
  },
  {
    emoji: '🎨',
    title: 'Holographic 5 组件集成 (R10.5.28)',
    body: 'CockpitDashboard / EvolutionSlider / CompareDrawer / CommandPalette / R10_5_28Banner 进 UI. useSearch 累积 events[] + graphSnapshots[] 喂新组件.',
    tag: 'R10.5.28',
    tagColor: 'var(--sf-muted)',
  },
  {
    emoji: '🛡',
    title: 'Admin 后门修复 + stream_token SQLite (R10.5.28)',
    body: 'CG.txt P0 #2: 删 admin bootstrap 后门, ADMIN_USER_IDS 必须显式配置或 CLI 工具 add. stream_token 进程内 dict 改 SQLite 跨 worker 共享.',
    tag: 'R10.5.28',
    tagColor: 'var(--sf-muted)',
  },
];

const DISMISSED_KEY = 'sf-changelog-dismissed-30';

export function ChangelogModal({
  isOpen,
  onClose,
}: {
  isOpen: boolean;
  onClose: () => void;
}) {
  // ESC 关闭
  useEffect(() => {
    if (!isOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center px-4 py-8"
      style={{ backgroundColor: 'rgba(0, 0, 0, 0.55)' }}
      onClick={onClose}
      data-testid="changelog-modal-overlay"
    >
      <div
        className="max-w-2xl w-full max-h-[80vh] overflow-y-auto p-5 font-ui"
        style={{
          backgroundColor: 'var(--sf-bg-elev)',
          border: '1px solid var(--sf-border)',
          borderTop: '3px solid var(--sf-accent)',
        }}
        onClick={(e) => e.stopPropagation()}
        data-testid="changelog-modal"
      >
        <div className="flex items-baseline justify-between mb-3">
          <div>
            <h2
              className="font-display text-xl"
              style={{ color: 'var(--sf-text)' }}
            >
              ScholarFlow R10.5.30 升级日志
            </h2>
            <p
              className="text-[11px] font-mono uppercase tracking-[0.15em] mt-1"
              style={{ color: 'var(--sf-muted)' }}
            >
              22 项 deferred + 已交付 8 项
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="font-display italic text-2xl leading-none opacity-50 hover:opacity-100 transition"
            style={{ color: 'var(--sf-muted)' }}
            aria-label="关闭"
            data-testid="changelog-modal-close"
          >
            ×
          </button>
        </div>
        <p
          className="text-[12px] mb-4 font-body"
          style={{ color: 'var(--sf-muted)' }}
        >
          R10.5.30 + R10.5.31 修复了 <strong>CG.txt / CD.txt / R10.5.28-29 审计</strong> 累计 22 项 deferred, 已交付 14 项.
          完整 22 项待办见{' '}
          <code
            className="font-mono text-[10px] px-1"
            style={{ backgroundColor: 'var(--sf-bg)' }}
          >
            docs/HANDOFF.md
          </code>.
        </p>
        <div className="space-y-3">
          {CHANGELOG_NOTES.map((n, i) => (
            <div
              key={i}
              className="p-3 border-l-2"
              style={{
                backgroundColor: 'var(--sf-bg)',
                borderLeftColor: n.tagColor,
              }}
              data-testid={`changelog-note-${i}`}
            >
              <div className="flex items-baseline gap-2 flex-wrap">
                <span className="text-base leading-none">{n.emoji}</span>
                <span
                  className="font-display text-[13px] flex-1 min-w-0"
                  style={{ color: 'var(--sf-text)' }}
                >
                  {n.title}
                </span>
                <span
                  className="font-mono text-[9px] uppercase tracking-[0.12em] px-1.5 py-0.5 shrink-0"
                  style={{
                    border: `1px solid ${n.tagColor}`,
                    color: n.tagColor,
                  }}
                >
                  {n.tag}
                </span>
              </div>
              <p
                className="font-body text-[12px] leading-snug mt-1"
                style={{ color: 'var(--sf-muted)' }}
              >
                {n.body}
              </p>
            </div>
          ))}
        </div>
        <div className="mt-4 pt-3 border-t flex items-center justify-between"
          style={{ borderColor: 'var(--sf-border)' }}
        >
          <span
            className="text-[10px] font-mono uppercase tracking-[0.15em]"
            style={{ color: 'var(--sf-muted)' }}
          >
            ❦ ScholarFlow v1.0.x (R10.5.31) ❦
          </span>
          <button
            type="button"
            onClick={() => {
              try {
                sessionStorage.setItem(DISMISSED_KEY, '1');
              } catch { /* ignore */ }
              onClose();
            }}
            className="text-[10px] font-mono uppercase tracking-[0.15em] opacity-70 hover:opacity-100 transition"
            style={{ color: 'var(--sf-muted)' }}
          >
            关闭 (本会话不再显示)
          </button>
        </div>
      </div>
    </div>
  );
}
