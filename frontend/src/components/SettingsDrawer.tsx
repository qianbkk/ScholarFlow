/**
 * SettingsDrawer — R10.5.55 左侧滑出设置抽屉
 *
 * 取代旧的 Settings tab (SettingsView). 取代 TopNav 的 ◐ 暗黑按钮:
 * 4 主题 (parchment/kraft/midnight/sage) 直接选, midnight 主题天然暗色,
 * 无需独立暗黑模式开关. Settings 入口移到这里 + TopNav 齿轮按钮.
 */
import { useStore, actions } from '../store/useStore';
import { THEMES } from '../lib/tokens';
import { useT } from '../i18n';

export function SettingsDrawer() {
  const open = useStore((s) => s.settingsDrawerOpen);
  const theme = useStore((s) => s.theme);
  const runtimeMode = useStore((s) => s.runtimeMode);
  const hasApiKey = useStore((s) => s.hasApiKey);
  const t = useT();

  if (!open) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="设置"
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 80,
        display: 'flex',
        justifyContent: 'flex-start',
      }}
    >
      <div
        onClick={actions.closeSettingsDrawer}
        style={{
          position: 'absolute',
          inset: 0,
          backgroundColor: 'rgba(0, 0, 0, 0.3)',
        }}
      />
      <aside
        className="sf-fade-in"
        style={{
          position: 'relative',
          width: 360,
          maxWidth: '100vw',
          height: '100vh',
          backgroundColor: 'var(--sf-bg)',
          borderRight: '1px solid var(--sf-border)',
          overflowY: 'auto',
          padding: 32,
        }}
      >
        <header
          style={{
            display: 'flex',
            alignItems: 'baseline',
            justifyContent: 'space-between',
            marginBottom: 32,
            paddingBottom: 12,
            borderBottom: '1px solid var(--sf-border)',
          }}
        >
          <h1
            className="font-display"
            style={{
              fontSize: 26,
              letterSpacing: '-0.02em',
              margin: 0,
            }}
          >
            {t('settings.title')}
          </h1>
          <button
            type="button"
            onClick={actions.closeSettingsDrawer}
            className="sf-btn font-ui"
            style={{ padding: '4px 10px', fontSize: 12 }}
            aria-label="关闭"
          >
            ✕
          </button>
        </header>

        {/* Theme — R10.5.59: 删除 'midnight 主题天然是夜间模式' 说明文案 */}
        <section style={{ marginBottom: 32 }}>
          <h2
            className="font-ui"
            style={{ fontSize: 13, fontWeight: 600, margin: '0 0 12px' }}
          >
            {t('settings.theme')}
          </h2>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 8 }}>
            {(Object.values(THEMES)).map((t) => {
              const active = t.id === theme;
              return (
                <button
                  key={t.id}
                  type="button"
                  aria-label={`Theme: ${t.label}`}
                  aria-pressed={active}
                  onClick={() => actions.setTheme(t.id)}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 10,
                    padding: '10px 12px',
                    border: active ? '2px solid var(--sf-accent)' : '1px solid var(--sf-border)',
                    borderRadius: 2,
                    background: 'var(--sf-bg)',
                    cursor: 'pointer',
                    textAlign: 'left',
                    transition: 'border-color 100ms ease',
                  }}
                  data-testid={`theme-${t.id}`}
                >
                  <span
                    aria-hidden
                    style={{
                      width: 24,
                      height: 24,
                      borderRadius: 2,
                      background: t.bg,
                      border: '1px solid var(--sf-border)',
                      flexShrink: 0,
                    }}
                  />
                  <span style={{ display: 'flex', flexDirection: 'column' }}>
                    <span
                      className="font-ui"
                      style={{
                        fontSize: 12,
                        fontWeight: active ? 600 : 500,
                        color: 'var(--sf-text)',
                      }}
                    >
                      {t.label}
                    </span>
                    <span
                      className="font-mono"
                      style={{ fontSize: 10, color: 'var(--sf-muted)' }}
                    >
                      {t.description}
                    </span>
                  </span>
                </button>
              );
            })}
          </div>
        </section>

        <hr className="sf-hr" style={{ margin: '24px 0' }} />

        {/* Runtime mode */}
        <section style={{ marginBottom: 32 }}>
          <h2
            className="font-ui"
            style={{ fontSize: 13, fontWeight: 600, margin: '0 0 4px' }}
          >
            {t('settings.runtimeMode')}
          </h2>
          <p
            className="font-body"
            style={{ fontSize: 12, color: 'var(--sf-muted)', margin: '0 0 12px' }}
          >
            {t('settings.runtimeModeDesc')}
          </p>
          <div style={{ display: 'flex', gap: 8 }}>
            <button
              type="button"
              onClick={() => actions.setRuntimeMode('local')}
              aria-pressed={runtimeMode === 'local'}
              className="sf-btn font-ui"
              data-testid="runtime-local"
              style={{ flex: 1 }}
            >
              {runtimeMode === 'local' ? '●' : '○'} {t('common.runtime.local')}
            </button>
            <button
              type="button"
              onClick={() => actions.setRuntimeMode('llm')}
              aria-pressed={runtimeMode === 'llm'}
              className="sf-btn font-ui"
              data-testid="runtime-llm"
              style={{ flex: 1 }}
            >
              {runtimeMode === 'llm' ? '●' : '○'} {t('common.runtime.llm')}
            </button>
          </div>
        </section>

        <hr className="sf-hr" style={{ margin: '24px 0' }} />

        {/* API key */}
        <section style={{ marginBottom: 32 }}>
          <h2
            className="font-ui"
            style={{ fontSize: 13, fontWeight: 600, margin: '0 0 12px' }}
          >
            API Key
          </h2>
          <p
            className="font-mono"
            style={{
              fontSize: 12,
              color: hasApiKey ? 'var(--sf-text)' : 'var(--sf-muted)',
              margin: '0 0 8px',
            }}
          >
            {hasApiKey ? t('settings.apiKeySet') : t('settings.apiKeyEmpty')}
          </p>
          <p
            className="font-body"
            style={{ fontSize: 12, color: 'var(--sf-muted)', margin: 0 }}
          >
            {t('settings.apiKeyDesc')}
          </p>
        </section>

        <hr className="sf-hr" style={{ margin: '24px 0' }} />

        {/* Keyboard */}
        <section style={{ marginBottom: 32 }}>
          <h2
            className="font-ui"
            style={{ fontSize: 13, fontWeight: 600, margin: '0 0 12px' }}
          >
            {t('settings.keyboard')}
          </h2>
          <table className="sf-table" style={{ fontSize: 13 }}>
            <tbody>
              <tr>
                <td><kbd className="font-mono">⌘ K</kbd> / <kbd className="font-mono">Ctrl K</kbd></td>
                <td>{t('settings.kb.cmdK')}</td>
              </tr>
              <tr>
                <td><kbd className="font-mono">⌘ ↵</kbd> / <kbd className="font-mono">Ctrl ↵</kbd></td>
                <td>{t('settings.kb.cmdEnter')}</td>
              </tr>
              <tr>
                <td><kbd className="font-mono">Esc</kbd></td>
                <td>{t('settings.kb.esc')}</td>
              </tr>
              <tr>
                <td><kbd className="font-mono">f</kbd> (in Graph)</td>
                <td>{t('settings.kb.fit')}</td>
              </tr>
              <tr>
                <td><kbd className="font-mono">Shift+F</kbd> (in Graph)</td>
                <td>{t('settings.kb.fullscreen')}</td>
              </tr>
            </tbody>
          </table>
        </section>

        <hr className="sf-hr" style={{ margin: '24px 0' }} />

        {/* About */}
        <section>
          <h2
            className="font-ui"
            style={{ fontSize: 13, fontWeight: 600, margin: '0 0 12px' }}
          >
            {t('settings.about')}
          </h2>
          <p
            className="font-body"
            style={{ fontSize: 13, color: 'var(--sf-muted)', margin: 0 }}
          >
            {t('settings.aboutDesc')} ·{' '}
            <button
              type="button"
              onClick={actions.openChangelog}
              className="font-ui"
              style={{
                background: 'none',
                border: 'none',
                padding: 0,
                color: 'var(--sf-accent)',
                cursor: 'pointer',
                textDecoration: 'underline',
                textUnderlineOffset: 2,
              }}
            >
              {t('settings.changelog')}
            </button>
          </p>
        </section>
      </aside>
    </div>
  );
}