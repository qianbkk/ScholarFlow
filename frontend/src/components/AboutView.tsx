/**
 * AboutView — R10.5.59 第 5 个 tab
 *
 * 关于 / 快捷键 / 更新日志 / 其他静态内容. 不依赖 SettingsSidebar (后者是常驻).
 */
import { useStore, actions } from '../store/useStore';
import { useT } from '../i18n';

export function AboutView() {
  const t = useT();

  return (
    <main
      id="view-about"
      role="tabpanel"
      aria-labelledby="tab-about"
      style={{
        maxWidth: 760,
        margin: '0 auto',
        padding: '56px 32px 96px',
      }}
      data-testid="about-view"
    >
      <header style={{ marginBottom: 40, paddingBottom: 16, borderBottom: '1px solid var(--sf-border)' }}>
        <h1
          className="font-display"
          style={{
            fontSize: 36,
            letterSpacing: '-0.025em',
            fontStyle: 'italic',
            margin: '0 0 6px',
          }}
        >
          {t('about.title')}
        </h1>
        <p className="font-body" style={{ fontSize: 15, color: 'var(--sf-muted)', margin: 0 }}>
          {t('about.subtitle')}
        </p>
      </header>

      {/* Project info */}
      <section style={{ marginBottom: 32 }}>
        <h2
          className="font-ui"
          style={{ fontSize: 13, fontWeight: 600, margin: '0 0 12px', color: 'var(--sf-muted)' }}
        >
          {t('about.project')}
        </h2>
        <p className="font-body" style={{ fontSize: 14, color: 'var(--sf-text)', margin: '0 0 12px' }}>
          {t('about.desc')}
        </p>
        <table className="sf-table" style={{ fontSize: 13, width: '100%' }}>
          <tbody>
            <tr>
              <td style={{ width: 100, color: 'var(--sf-muted)' }}>{t('about.version')}</td>
              <td>
                <span className="font-mono">R10.5.59</span>
              </td>
            </tr>
            <tr>
              <td style={{ color: 'var(--sf-muted)' }}>{t('about.author')}</td>
              <td>qianbkk</td>
            </tr>
            <tr>
              <td style={{ color: 'var(--sf-muted)' }}>{t('about.github')}</td>
              <td>
                <a
                  href="https://github.com/qianbkk/ScholarFlow"
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{ color: 'var(--sf-accent)', textDecoration: 'none' }}
                >
                  github.com/qianbkk/ScholarFlow
                </a>
              </td>
            </tr>
          </tbody>
        </table>
      </section>

      <hr className="sf-hr" style={{ margin: '24px 0' }} />

      {/* Keyboard shortcuts */}
      <section style={{ marginBottom: 32 }}>
        <h2
          className="font-ui"
          style={{ fontSize: 13, fontWeight: 600, margin: '0 0 12px', color: 'var(--sf-muted)' }}
        >
          {t('about.shortcuts.title')}
        </h2>
        <table className="sf-table" style={{ fontSize: 13, width: '100%' }}>
          <tbody>
            <tr>
              <td style={{ width: 180 }}>
                <kbd className="font-mono">⌘ K</kbd> / <kbd className="font-mono">Ctrl K</kbd>
              </td>
              <td>{t('about.shortcuts.cmdK')}</td>
            </tr>
            <tr>
              <td>
                <kbd className="font-mono">⌘ ↵</kbd> / <kbd className="font-mono">Ctrl ↵</kbd>
              </td>
              <td>{t('about.shortcuts.cmdEnter')}</td>
            </tr>
            <tr>
              <td>
                <kbd className="font-mono">Esc</kbd>
              </td>
              <td>{t('about.shortcuts.esc')}</td>
            </tr>
            <tr>
              <td>
                <kbd className="font-mono">f</kbd>
              </td>
              <td>{t('about.shortcuts.f')}</td>
            </tr>
            <tr>
              <td>
                <kbd className="font-mono">Shift+F</kbd>
              </td>
              <td>{t('about.shortcuts.shiftF')}</td>
            </tr>
          </tbody>
        </table>
      </section>

      <hr className="sf-hr" style={{ margin: '24px 0' }} />

      {/* Changelog */}
      <section>
        <h2
          className="font-ui"
          style={{ fontSize: 13, fontWeight: 600, margin: '0 0 12px', color: 'var(--sf-muted)' }}
        >
          {t('about.changelog.title')}
        </h2>
        <p className="font-body" style={{ fontSize: 13, color: 'var(--sf-text)', margin: 0 }}>
          <button
            type="button"
            onClick={actions.openChangelog}
            style={{
              background: 'none',
              border: 'none',
              padding: 0,
              color: 'var(--sf-accent)',
              cursor: 'pointer',
              textDecoration: 'underline',
              textUnderlineOffset: 2,
              fontSize: 13,
            }}
          >
            R10.5.59 changelog →
          </button>
        </p>
      </section>
    </main>
  );
}