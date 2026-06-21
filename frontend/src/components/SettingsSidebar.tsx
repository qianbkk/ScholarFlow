/**
 * SettingsSidebar — R10.5.59 左侧常驻可收起菜单
 *
 * 取代旧的 SettingsDrawer (弹窗). 现在固定在屏幕左侧,可点击 ☰ 按钮收起/展开.
 * 包含 4 个分组: 语言 / 主题色系 / 运行时模式 / API Key.
 * 关于 / 快捷键 / 更新日志移到 AboutView (独立 tab).
 */
import { useState, useEffect } from 'react';
import { useStore, actions, type RuntimeMode } from '../store/useStore';
import { THEMES } from '../lib/tokens';
import { useT, toggleLocale, type Locale } from '../i18n';

const LOCALES: { id: Locale; label: string; short: string }[] = [
  { id: 'zh', label: '中文', short: '中' },
  { id: 'en', label: 'English', short: 'EN' },
];

export function SettingsSidebar() {
  const collapsed = useStore((s) => s.settingsCollapsed);
  const theme = useStore((s) => s.theme);
  const locale = useStore((s) => s.locale);
  const runtimeMode = useStore((s) => s.runtimeMode);
  const hasApiKey = useStore((s) => s.hasApiKey);
  const t = useT();

  const width = collapsed ? 48 : 220;

  return (
    <aside
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        bottom: 0,
        width,
        backgroundColor: 'var(--sf-bg)',
        borderRight: '1px solid var(--sf-border)',
        zIndex: 60,
        display: 'flex',
        flexDirection: 'column',
        transition: 'width 180ms ease',
        overflowY: 'auto',
        overflowX: 'hidden',
      }}
      data-testid="settings-sidebar"
      data-collapsed={collapsed ? 'true' : 'false'}
    >
      {/* Toggle header */}
      <button
        type="button"
        onClick={actions.toggleSettingsCollapsed}
        aria-label={collapsed ? t('sidebar.expand') : t('sidebar.collapse')}
        title={collapsed ? t('sidebar.expand') : t('sidebar.collapse')}
        className="font-ui"
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: collapsed ? 'center' : 'space-between',
          padding: collapsed ? '12px 0' : '14px 16px',
          background: 'none',
          border: 'none',
          borderBottom: '1px solid var(--sf-border)',
          cursor: 'pointer',
          color: 'var(--sf-text)',
          gap: 8,
          width: '100%',
        }}
        data-testid="toggle-sidebar"
      >
        {!collapsed && (
          <span className="font-display" style={{ fontSize: 14, fontWeight: 600 }}>
            {t('sidebar.title')}
          </span>
        )}
        <span aria-hidden style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
          <span style={{ display: 'block', width: 14, height: 1.5, backgroundColor: 'currentColor' }} />
          <span style={{ display: 'block', width: 14, height: 1.5, backgroundColor: 'currentColor' }} />
          <span style={{ display: 'block', width: 14, height: 1.5, backgroundColor: 'currentColor' }} />
        </span>
      </button>

      {/* Sections */}
      {!collapsed && (
        <div style={{ padding: '12px 12px 24px', display: 'flex', flexDirection: 'column', gap: 16 }}>
          {/* Language */}
          <Section title={t('sidebar.language')}>
            <div style={{ display: 'flex', gap: 4 }}>
              {LOCALES.map((l) => {
                const active = locale === l.id;
                return (
                  <button
                    key={l.id}
                    type="button"
                    onClick={() => actions.setLocale(l.id)}
                    aria-pressed={active}
                    className="font-ui"
                    style={{
                      flex: 1,
                      padding: '6px 0',
                      background: active ? 'var(--sf-surface-alt)' : 'transparent',
                      border: `1px solid ${active ? 'var(--sf-accent)' : 'var(--sf-border)'}`,
                      borderRadius: 2,
                      color: active ? 'var(--sf-text)' : 'var(--sf-muted)',
                      fontSize: 12,
                      fontWeight: active ? 600 : 400,
                      cursor: 'pointer',
                    }}
                    data-testid={`lang-${l.id}`}
                  >
                    {l.short}
                  </button>
                );
              })}
            </div>
          </Section>

          {/* Theme */}
          <Section title={t('settings.theme')}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 6 }}>
              {(Object.values(THEMES)).map((th) => {
                const active = th.id === theme;
                return (
                  <button
                    key={th.id}
                    type="button"
                    aria-label={`Theme: ${th.label}`}
                    aria-pressed={active}
                    onClick={() => actions.setTheme(th.id)}
                    title={th.label}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 8,
                      padding: '6px 8px',
                      border: active ? '2px solid var(--sf-accent)' : '1px solid var(--sf-border)',
                      borderRadius: 2,
                      background: 'var(--sf-bg)',
                      cursor: 'pointer',
                      transition: 'border-color 100ms ease',
                    }}
                    data-testid={`theme-${th.id}`}
                  >
                    <span
                      aria-hidden
                      style={{
                        width: 16,
                        height: 16,
                        borderRadius: 2,
                        background: th.bg,
                        border: '1px solid var(--sf-border)',
                        flexShrink: 0,
                      }}
                    />
                    <span style={{ fontSize: 11, color: 'var(--sf-text)' }}>{th.label}</span>
                  </button>
                );
              })}
            </div>
          </Section>

          {/* Runtime mode */}
          <Section title={t('settings.runtimeMode')}>
            <div style={{ display: 'flex', gap: 4 }}>
              {(['local', 'llm'] as RuntimeMode[]).map((m) => {
                const active = runtimeMode === m;
                const label = m === 'local' ? t('common.runtime.local') : t('common.runtime.llm');
                return (
                  <button
                    key={m}
                    type="button"
                    onClick={() => actions.setRuntimeMode(m)}
                    aria-pressed={active}
                    className="font-ui"
                    style={{
                      flex: 1,
                      padding: '6px 0',
                      background: active ? 'var(--sf-surface-alt)' : 'transparent',
                      border: `1px solid ${active ? 'var(--sf-accent)' : 'var(--sf-border)'}`,
                      borderRadius: 2,
                      color: active ? 'var(--sf-text)' : 'var(--sf-muted)',
                      fontSize: 12,
                      fontWeight: active ? 600 : 400,
                      cursor: 'pointer',
                    }}
                    data-testid={`runtime-${m}`}
                  >
                    {active ? '● ' : '○ '}{label}
                  </button>
                );
              })}
            </div>
          </Section>

          {/* API Key */}
          <Section title="API Key">
            <ApiKeySection />
          </Section>
        </div>
      )}

      {/* Collapsed: just show vertical icon rail */}
      {collapsed && (
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 16, padding: '16px 0' }}>
          <button
            type="button"
            onClick={toggleLocale}
            title={locale === 'zh' ? 'EN' : '中'}
            className="font-ui"
            style={{
              width: 32, height: 32,
              border: '1px solid var(--sf-border)',
              borderRadius: 2,
              background: 'none',
              color: 'var(--sf-text)',
              fontSize: 11, fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            {locale === 'zh' ? '中' : 'EN'}
          </button>
          <div
            aria-hidden
            style={{
              width: 24, height: 24, borderRadius: '50%',
              background: THEMES[theme].bg,
              border: '1px solid var(--sf-border)',
            }}
            title={THEMES[theme].label}
          />
          <span
            className="font-mono"
            style={{
              fontSize: 9, color: 'var(--sf-muted)',
              letterSpacing: '0.1em', textTransform: 'uppercase',
            }}
            title={runtimeMode}
          >
            {runtimeMode === 'llm' ? 'AI' : 'LO'}
          </span>
          <span
            aria-hidden
            title={hasApiKey ? 'API key set' : 'No API key'}
            style={{
              width: 8, height: 8, borderRadius: '50%',
              backgroundColor: hasApiKey ? 'var(--sf-accent)' : 'var(--sf-border)',
            }}
          />
        </div>
      )}
    </aside>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h3
        className="font-ui"
        style={{
          fontSize: 11,
          fontWeight: 600,
          textTransform: 'uppercase',
          letterSpacing: '0.08em',
          color: 'var(--sf-muted)',
          margin: '0 0 6px',
        }}
      >
        {title}
      </h3>
      {children}
    </section>
  );
}

/**
 * API Key section — 显示当前 key 状态 + 编辑/添加按钮 (调用后端 /api/v1/config/env 端点)
 */
function ApiKeySection() {
  const t = useT();
  const hasApiKey = useStore((s) => s.hasApiKey);
  const [editing, setEditing] = useState(false);
  const [providers, setProviders] = useState<Array<{ id: string; label: string; has_key: boolean }>>([]);
  const [selectedProvider, setSelectedProvider] = useState('minimax');
  const [keyInput, setKeyInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<string | null>(null);

  useEffect(() => {
    fetch('/api/v1/providers')
      .then((r) => r.json())
      .then((res) => {
        if (res?.providers) {
          setProviders(
            res.providers.map((p: any) => ({
              id: p.id,
              label: p.label || p.id,
              has_key: !!p.has_key,
            })),
          );
        }
      })
      .catch(() => { /* ignore */ });
  }, []);

  const save = async () => {
    if (!keyInput.trim()) return;
    setBusy(true);
    setStatus(null);
    try {
      const r = await fetch('/api/v1/config/env', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ provider: selectedProvider, api_key: keyInput.trim() }),
      });
      if (!r.ok) {
        const detail = (await r.json().catch(() => ({}))).detail || '保存失败';
        setStatus(`✗ ${detail}`);
      } else {
        setStatus(`✓ ${selectedProvider} key 已保存到 .env`);
        setKeyInput('');
        const res = await fetch('/api/v1/providers').then((r) => r.json());
        if (res?.providers) {
          setProviders(
            res.providers.map((p: any) => ({
              id: p.id,
              label: p.label || p.id,
              has_key: !!p.has_key,
            })),
          );
        }
      }
    } catch (e: any) {
      setStatus(`✗ ${e?.message || '网络错误'}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <p
        className="font-mono"
        style={{
          fontSize: 11,
          color: 'var(--sf-muted)',
          margin: 0,
        }}
      >
        {providers.filter((p) => p.has_key).length} / {providers.length} {t('sidebar.keySet')}
      </p>
      {!editing ? (
        <button
          type="button"
          onClick={() => setEditing(true)}
          className="sf-btn font-ui"
          style={{ padding: '4px 8px', fontSize: 11 }}
          data-testid="apikey-edit-btn"
        >
          {hasApiKey ? t('sidebar.manageKeys') : t('sidebar.addKey')}
        </button>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <select
            value={selectedProvider}
            onChange={(e) => setSelectedProvider(e.target.value)}
            className="font-ui"
            style={{
              padding: '4px 6px',
              fontSize: 11,
              border: '1px solid var(--sf-border)',
              borderRadius: 2,
              background: 'var(--sf-bg)',
              color: 'var(--sf-text)',
            }}
          >
            {providers.map((p) => (
              <option key={p.id} value={p.id}>
                {p.label}{p.has_key ? ' ✓' : ''}
              </option>
            ))}
          </select>
          <input
            type="password"
            value={keyInput}
            onChange={(e) => setKeyInput(e.target.value)}
            placeholder="sk-..."
            className="font-mono"
            style={{
              padding: '4px 6px',
              fontSize: 11,
              border: '1px solid var(--sf-border)',
              borderRadius: 2,
              background: 'var(--sf-bg)',
              color: 'var(--sf-text)',
            }}
          />
          <div style={{ display: 'flex', gap: 4 }}>
            <button
              type="button"
              onClick={save}
              disabled={busy || !keyInput.trim()}
              className="sf-btn sf-btn-primary font-ui"
              style={{ flex: 1, padding: '4px 8px', fontSize: 11 }}
            >
              {busy ? '...' : t('sidebar.save')}
            </button>
            <button
              type="button"
              onClick={() => { setEditing(false); setKeyInput(''); setStatus(null); }}
              className="sf-btn font-ui"
              style={{ padding: '4px 8px', fontSize: 11 }}
            >
              ✕
            </button>
          </div>
          {status && (
            <p className="font-mono" style={{ fontSize: 10, color: 'var(--sf-accent)', margin: 0 }}>
              {status}
            </p>
          )}
        </div>
      )}
    </div>
  );
}