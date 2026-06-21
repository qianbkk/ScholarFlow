/**
 * TopNav — R10.5.59 编辑参考书视觉
 *
 * 单行 56px sticky: wordmark + 5 tab + 右侧 cluster (用户徽章).
 * active tab 在整行下方居中显示 2px 烧橙 tick (不在文字下).
 * 不再用 emoji 图标 + tracking eyebrow.
 *
 * R10.5.59: 删除 ☰ hamburger 按钮 (Settings 改左侧常驻). 删除中/EN 切换 (移入 SettingsSidebar).
 *           TABS 5 个: 查询 / 报告 / 图谱 / 历史 / 关于.
 */
import { useStore, actions, type ViewId } from '../store/useStore';
import { useT } from '../i18n';

const TABS: { id: ViewId }[] = [
  { id: 'search' },
  { id: 'report' },
  { id: 'graph' },
  { id: 'history' },
  { id: 'about' },
];

export function TopNav() {
  const currentView = useStore((s) => s.currentView);
  const user = useStore((s) => s.user);
  const hasApiKey = useStore((s) => s.hasApiKey);
  const loading = useStore((s) => s.loading);
  const t = useT();

  return (
    <nav
      role="navigation"
      aria-label={t('topbar.nav')}
      style={{
        position: 'sticky',
        top: 0,
        zIndex: 50,
        backgroundColor: 'var(--sf-bg)',
        borderBottom: '1px solid var(--sf-border)',
        height: 56,
      }}
    >
      <div
        style={{
          height: '100%',
          maxWidth: 1180,
          margin: '0 auto',
          padding: '0 24px',
          display: 'flex',
          alignItems: 'center',
          gap: 24,
        }}
      >
        {/* Wordmark */}
        <button
          onClick={() => actions.setView('search')}
          aria-label={t('topbar.goSearch')}
          style={{
            background: 'none',
            border: 'none',
            padding: 0,
            cursor: 'pointer',
            color: 'var(--sf-text)',
          }}
        >
          <span
            className="font-display"
            style={{ fontSize: 22, letterSpacing: '-0.02em' }}
          >
            ScholarFlow
          </span>
        </button>

        {/* Tabs (centered area) */}
        <div
          role="tablist"
          aria-label={t('topbar.viewTabs')}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 4,
            flex: 1,
            marginLeft: 24,
          }}
        >
          {TABS.map((tab, i) => {
            const active = currentView === tab.id;
            const label = t(`nav.${tab.id}` as const);
            return (
              <div key={tab.id} style={{ display: 'flex', alignItems: 'center' }}>
                <button
                  role="tab"
                  aria-selected={active}
                  aria-controls={`view-${tab.id}`}
                  data-testid={`tab-${tab.id}`}
                  onClick={() => actions.setView(tab.id)}
                  className="font-ui"
                  style={{
                    position: 'relative',
                    background: 'none',
                    border: 'none',
                    padding: '8px 14px',
                    cursor: 'pointer',
                    color: active ? 'var(--sf-text)' : 'var(--sf-muted)',
                    fontSize: 14,
                    fontWeight: active ? 600 : 400,
                    transition: 'color 100ms ease',
                  }}
                  onMouseEnter={(e) => {
                    if (!active) e.currentTarget.style.color = 'var(--sf-text)';
                  }}
                  onMouseLeave={(e) => {
                    if (!active) e.currentTarget.style.color = 'var(--sf-muted)';
                  }}
                >
                  {label}
                  {/* Active tab: 2px tick under entire row, centered */}
                  {active && (
                    <span
                      aria-hidden
                      style={{
                        position: 'absolute',
                        bottom: -1,
                        left: '50%',
                        transform: 'translateX(-50%)',
                        width: 24,
                        height: 2,
                        backgroundColor: 'var(--sf-accent)',
                      }}
                    />
                  )}
                  {/* Running indicator: small pulsing dot */}
                  {active && loading && (
                    <span
                      aria-label={t('topbar.running')}
                      style={{
                        display: 'inline-block',
                        marginLeft: 8,
                        width: 6,
                        height: 6,
                        borderRadius: '50%',
                        backgroundColor: 'var(--sf-accent)',
                        verticalAlign: 'middle',
                      }}
                      className="sf-pulse"
                    />
                  )}
                </button>
                {i < TABS.length - 1 && (
                  <span
                    aria-hidden
                    style={{
                      color: 'var(--sf-border)',
                      fontSize: 14,
                      userSelect: 'none',
                    }}
                  >
                    ·
                  </span>
                )}
              </div>
            );
          })}
        </div>

        {/* Right cluster: 用户徽章 (语言切换 + 主题在 SettingsSidebar 里) */}
        <UserBadge user={user} hasApiKey={hasApiKey} />
      </div>
    </nav>
  );
}

function UserBadge({
  user,
  hasApiKey,
}: {
  user: { display_name: string } | null;
  hasApiKey: boolean;
}) {
  if (!user && !hasApiKey) {
    return (
      <button
        type="button"
        onClick={actions.openAuthDialog}
        className="sf-btn font-ui"
        style={{ padding: '6px 12px', fontSize: 13 }}
        data-testid="user-signin"
      >
        Sign in
      </button>
    );
  }
  const initials = (user?.display_name || 'Guest').slice(0, 1).toUpperCase();
  return (
    <button
      type="button"
      onClick={actions.openAuthDialog}
      aria-label="用户菜单"
      className="font-mono"
      style={{
        width: 32,
        height: 32,
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'var(--sf-surface-alt)',
        border: '1px solid var(--sf-border)',
        borderRadius: 2,
        cursor: 'pointer',
        color: 'var(--sf-text)',
        fontSize: 13,
      }}
      title={user?.display_name || 'Guest'}
    >
      {initials}
    </button>
  );
}