/**
 * AuthDialog — R10.5.59 完整认证 UI + i18n
 *
 * - 自动检测已登录状态 (cookie session)
 * - 区分 Register / Login 两个按钮 + 错误信息
 * - Password 字段 (>=8 字符)
 * - "Rotate API key" 按钮 (已登录时) 调 /auth/revoke
 * - 登出调 /auth/logout 后端 (旧版只清 sessionStorage)
 */
import { useState, useEffect } from 'react';
import { useStore, actions } from '../store/useStore';
import { register, login, logout, revokeKey, fetchMe, AuthError } from '../services/api';
import { useT } from '../i18n';

export function AuthDialog() {
  const open = useStore((s) => s.authDialogOpen);
  const user = useStore((s) => s.user);
  const hasApiKey = useStore((s) => s.hasApiKey);
  const t = useT();

  const [mode, setMode] = useState<'register' | 'login'>('register');
  const [email, setEmail] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    if (!open) {
      // 关闭时重置
      setEmail('');
      setDisplayName('');
      setPassword('');
      setConfirmPassword('');
      setError(null);
      setNotice(null);
      setMode('register');
    }
  }, [open]);

  if (!open) return null;

  const submit = async () => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      if (!email.trim()) throw new Error(t('auth.err.emailRequired'));
      if (mode === 'register') {
        if (password && password.length < 8) {
          throw new AuthError(t('auth.err.weakPassword'), 400, 'weak_password');
        }
        if (password && password !== confirmPassword) {
          throw new Error(t('auth.err.passwordMismatch'));
        }
        const resp = await register(email.trim(), password, displayName.trim());
        const me = await fetchMe();
        actions.setUser({
          user_id: resp.user_id,
          display_name: resp.display_name || displayName.trim() || email.trim(),
          email: email.trim(),
          created_at: me?.created_at ? String(me.created_at) : undefined,
        });
        setNotice(t('auth.notice.signup'));
      } else {
        const resp = await login(email.trim(), password, displayName.trim());
        const me = await fetchMe();
        actions.setUser({
          user_id: resp.user_id,
          display_name: resp.display_name || email.trim(),
          email: email.trim(),
          created_at: me?.created_at ? String(me.created_at) : undefined,
        });
        if (resp.key_rotated) {
          setNotice(t('auth.notice.rotated'));
        } else {
          setNotice(t('auth.notice.signin'));
        }
      }
      actions.closeAuthDialog();
    } catch (e: any) {
      setError(e?.message || (mode === 'register' ? t('auth.err.signupFail') : t('auth.err.signinFail')));
    } finally {
      setBusy(false);
    }
  };

  const handleLogout = async () => {
    setBusy(true);
    try {
      await logout();
      actions.setUser(null);
      actions.closeAuthDialog();
    } finally {
      setBusy(false);
    }
  };

  const handleRotate = async () => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const resp = await revokeKey();
      setNotice(`${t('auth.notice.rotated')} · ${resp.api_key.slice(0, 10)}…${resp.api_key.slice(-4)}`);
    } catch (e: any) {
      setError(e?.message || t('auth.err.rotateFail'));
    } finally {
      setBusy(false);
    }
  };

  const isSignedIn = !!user || hasApiKey;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={isSignedIn ? t('auth.title.account') : 'Sign in / Register'}
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 100,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        backgroundColor: 'rgba(0, 0, 0, 0.4)',
      }}
      onClick={actions.closeAuthDialog}
    >
      <div
        className="sf-fade-in"
        onClick={(e) => e.stopPropagation()}
        style={{
          width: 420,
          maxWidth: 'calc(100vw - 48px)',
          backgroundColor: 'var(--sf-bg)',
          border: '1px solid var(--sf-border)',
          borderRadius: 4,
          padding: 32,
        }}
      >
        {/* 已登录视图 */}
        {isSignedIn && (
          <>
            <h1 className="font-display" style={{ fontSize: 24, letterSpacing: '-0.02em', margin: '0 0 4px' }}>
              Hi, {user?.display_name || 'Guest'}
            </h1>
            <p className="font-body" style={{ fontSize: 13, color: 'var(--sf-muted)', margin: '0 0 24px' }}>
              {user?.email ? `${user.email} · ` : ''}{t('auth.sessionHint')}
            </p>
            {notice && (
              <p
                className="font-mono"
                style={{
                  fontSize: 11,
                  color: 'var(--sf-accent)',
                  backgroundColor: 'var(--sf-surface-alt)',
                  padding: 8,
                  borderRadius: 2,
                  margin: '0 0 16px',
                  wordBreak: 'break-all',
                }}
              >
                {notice}
              </p>
            )}
            {error && (
              <p className="font-body" style={{ fontSize: 13, color: 'var(--sf-accent)', margin: '0 0 16px' }}>
                {error}
              </p>
            )}
            <div style={{ display: 'flex', gap: 8, justifyContent: 'space-between' }}>
              <button
                type="button"
                onClick={handleRotate}
                disabled={busy}
                className="sf-btn font-ui"
                data-testid="rotate-key-btn"
              >
                {busy ? '…' : t('auth.rotate')}
              </button>
              <div style={{ display: 'flex', gap: 8 }}>
                <button type="button" onClick={actions.closeAuthDialog} className="sf-btn font-ui" disabled={busy}>
                  {t('auth.close')}
                </button>
                <button
                  type="button"
                  onClick={handleLogout}
                  className="sf-btn sf-btn-primary font-ui"
                  disabled={busy}
                  data-testid="signout-btn"
                >
                  {t('auth.signout')}
                </button>
              </div>
            </div>
          </>
        )}

        {/* 未登录视图 */}
        {!isSignedIn && (
          <>
            <h1 className="font-display" style={{ fontSize: 24, letterSpacing: '-0.02em', margin: '0 0 4px' }}>
              {mode === 'register' ? t('auth.title.signup') : t('auth.title.signin')}
            </h1>
            <p className="font-body" style={{ fontSize: 13, color: 'var(--sf-muted)', margin: '0 0 24px' }}>
              {mode === 'register' ? t('auth.desc.signup') : t('auth.desc.signin')}
            </p>

            {/* Register / Login tabs */}
            <div
              role="tablist"
              style={{
                display: 'flex',
                gap: 4,
                marginBottom: 16,
                borderBottom: '1px solid var(--sf-border)',
              }}
            >
              {(['register', 'login'] as const).map((m) => {
                const active = mode === m;
                return (
                  <button
                    key={m}
                    type="button"
                    role="tab"
                    aria-selected={active}
                    onClick={() => { setMode(m); setError(null); setNotice(null); }}
                    className="font-ui"
                    style={{
                      background: 'none',
                      border: 'none',
                      padding: '8px 12px',
                      cursor: 'pointer',
                      color: active ? 'var(--sf-text)' : 'var(--sf-muted)',
                      fontSize: 13,
                      fontWeight: active ? 600 : 400,
                      borderBottom: active ? '2px solid var(--sf-accent)' : '2px solid transparent',
                      marginBottom: -1,
                    }}
                  >
                    {m === 'register' ? t('auth.tab.signup') : t('auth.tab.signin')}
                  </button>
                );
              })}
            </div>

            <label className="font-ui" style={{ display: 'block', fontSize: 12, color: 'var(--sf-muted)', marginBottom: 4 }}>
              {t('auth.email')}
            </label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              disabled={busy}
              className="sf-input"
              placeholder="you@example.com"
              style={{ marginBottom: 12 }}
              autoFocus
            />

            <label className="font-ui" style={{ display: 'block', fontSize: 12, color: 'var(--sf-muted)', marginBottom: 4 }}>
              {t('auth.displayName')}
            </label>
            <input
              type="text"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              disabled={busy}
              className="sf-input"
              placeholder={t('auth.displayName')}
              style={{ marginBottom: 12 }}
            />

            <label className="font-ui" style={{ display: 'block', fontSize: 12, color: 'var(--sf-muted)', marginBottom: 4 }}>
              {t('auth.password')}
            </label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={busy}
              className="sf-input"
              placeholder={mode === 'register' ? t('auth.passwordPlaceholderSignup') : t('auth.passwordPlaceholderSignin')}
              style={{ marginBottom: 12 }}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && mode === 'login') submit();
              }}
            />

            {mode === 'register' && password && (
              <>
                <label className="font-ui" style={{ display: 'block', fontSize: 12, color: 'var(--sf-muted)', marginBottom: 4 }}>
                  {t('auth.confirmPassword')}
                </label>
                <input
                  type="password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  disabled={busy}
                  className="sf-input"
                  placeholder={t('auth.confirmPlaceholder')}
                  style={{ marginBottom: 12 }}
                  onKeyDown={(e) => { if (e.key === 'Enter') submit(); }}
                />
              </>
            )}

            {error && (
              <p className="font-body" style={{ fontSize: 13, color: 'var(--sf-accent)', margin: '0 0 12px' }}>
                {error}
              </p>
            )}

            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <button
                type="button"
                onClick={actions.closeAuthDialog}
                className="sf-btn font-ui"
                disabled={busy}
              >
                {t('auth.cancel')}
              </button>
              <button
                type="button"
                onClick={submit}
                className="sf-btn sf-btn-primary font-ui"
                disabled={busy || !email.trim()}
                data-testid={mode === 'register' ? 'register-btn' : 'login-btn'}
              >
                {busy ? '…' : mode === 'register' ? t('auth.signup') : t('auth.signin')}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}