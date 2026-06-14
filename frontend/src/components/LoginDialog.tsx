/**
 * LoginDialog — R10.5.3 缺失的认证 UI 组件
 *
 * 背景: R10.5 README 承诺『首次访问会弹出注册/登录对话框』, 但前端实际只
 * 实现了 auth API 封装 (services/api.ts 里的 registerOrLogin / fetchMe),
 * 没有任何 UI 组件调用它们. 后端 OPEN_MODE=false 模式下 401 错误, 用户
 * 看不到登录入口, 完全卡死.
 *
 * 设计:
 *  - 单个端点 /auth/login (后端实现是 register-or-login 合一: 已注册返新
 *    key, 未注册自动注册).  本组件用两个 tab (注册 / 登录) 只是为了
 *    UX 上的明确感, 内部都调同一个 API.
 *  - 模态对话框: backdrop + 居中卡片, 与 ThemeSwitcher dropdown 一致的
 *    颜色 token (var(--sf-bg) / var(--sf-text) / var(--sf-border)).
 *  - Esc 关闭 / 点击 backdrop 关闭 — 但 OPEN_MODE=false 时不允许关闭
 *    (用户必须登录), 关闭按钮也禁用.
 *  - 提交期间禁用按钮, 防止双击重复请求触发后端 5/min 限流.
 */
import { useEffect, useRef, useState } from 'react';
import { registerOrLogin } from '../services/api';

type Mode = 'login' | 'register';

interface Props {
  /** OPEN_MODE=false 模式下, 关闭按钮禁用 (强制用户必须登录). */
  requireAuth: boolean;
  /** 登录成功回调 (父组件更新 auth 状态). */
  onSuccess: () => void;
  /** 用户主动关闭对话框 (仅在 !requireAuth 时触发). */
  onClose?: () => void;
}

export function LoginDialog({ requireAuth, onSuccess, onClose }: Props) {
  const [mode, setMode] = useState<Mode>('register');
  const [email, setEmail] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const emailRef = useRef<HTMLInputElement>(null);

  // 打开时自动 focus email 输入框
  useEffect(() => {
    emailRef.current?.focus();
  }, []);

  // Esc 关闭 (仅在 !requireAuth 时)
  useEffect(() => {
    if (requireAuth) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && onClose) onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [requireAuth, onClose]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!email.trim()) {
      setError('请输入邮箱');
      return;
    }
    if (!email.includes('@') || email.length < 3) {
      setError('邮箱格式无效');
      return;
    }
    setSubmitting(true);
    try {
      // 后端 /auth/login 是 register-or-login 合一: 同 email 重复调会
      // 拿新 key (旧 key 失效). 这里两个 tab 都用同一端点.
      await registerOrLogin(
        email.trim(),
        mode === 'register' ? (displayName.trim() || email.trim()) : ''
      );
      onSuccess();
    } catch (err: any) {
      // 后端 detail 字段已经是中文友好提示, 直接透传
      setError(err?.message || '登录失败, 请重试');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 sf-fade"
      style={{ backgroundColor: 'rgba(13, 13, 13, 0.55)' }}
      role="dialog"
      aria-modal="true"
      aria-labelledby="login-dialog-title"
    >
      {/* backdrop: OPEN_MODE=true 时点击关闭, 否则禁用 */}
      <div
        className="absolute inset-0"
        onClick={() => {
          if (!requireAuth && onClose) onClose();
        }}
        aria-hidden="true"
      />

      {/* R10.5.4 Editorial: 无圆角, 双线包边, 像期刊订阅卡 */}
      <div
        className="relative w-full max-w-md p-7 sf-rise"
        style={{
          backgroundColor: 'var(--sf-bg)',
          color: 'var(--sf-text)',
          border: '1px solid var(--sf-border)',
          boxShadow: '0 1px 2px rgba(0,0,0,0.04), 0 16px 48px rgba(0,0,0,0.10)',
        }}
      >
        {/* 顶部细线 (报头"装订线") */}
        <div
          className="absolute top-0 left-0 right-0 h-1"
          style={{ backgroundColor: 'var(--sf-accent)' }}
        />

        {/* 标题 + 关闭按钮 (仅在 !requireAuth 时显示) */}
        <div className="flex items-start justify-between mb-5">
          <div>
            <div
              className="font-mono text-[9px] uppercase tracking-[0.25em] mb-1"
              style={{ color: 'var(--sf-accent)' }}
            >
              § 订阅 · Subscription
            </div>
            <h2
              id="login-dialog-title"
              className="font-display italic font-semibold text-2xl leading-tight"
              style={{ color: 'var(--sf-text)' }}
            >
              登录 <span style={{ color: 'var(--sf-accent)' }}>ScholarFlow</span>
            </h2>
            <p
              className="font-body text-[13px] italic mt-1.5"
              style={{ color: 'var(--sf-muted)' }}
            >
              学术邮箱即身份, 无需密码
            </p>
          </div>
          {!requireAuth && onClose && (
            <button
              type="button"
              onClick={onClose}
              aria-label="关闭"
              className="font-display italic text-2xl leading-none transition-colors px-1"
              style={{ color: 'var(--sf-muted)' }}
            >
              ×
            </button>
          )}
        </div>

        {/* Tabs: 注册 / 登录 (后端是同一端点, 这里只是 UX 区分) */}
        <div
          className="flex border-b mb-5"
          style={{ borderColor: 'var(--sf-border)' }}
        >
          {(['register', 'login'] as Mode[]).map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => {
                setMode(m);
                setError(null);
              }}
              className={`flex-1 py-2.5 text-xs font-mono uppercase tracking-[0.15em] transition-colors -mb-px border-b-2 ${
                mode === m
                  ? 'font-semibold'
                  : 'opacity-50 hover:opacity-100'
              }`}
              style={{
                color: mode === m ? 'var(--sf-accent)' : 'var(--sf-muted)',
                borderColor: mode === m ? 'var(--sf-accent)' : 'transparent',
              }}
            >
              {m === 'register' ? '新用户注册' : '已有账号登录'}
            </button>
          ))}
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label
              htmlFor="login-email"
              className="block text-[10px] font-mono uppercase tracking-[0.15em] mb-1.5"
              style={{ color: 'var(--sf-muted)' }}
            >
              学术邮箱
            </label>
            <input
              ref={emailRef}
              id="login-email"
              type="email"
              required
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@university.edu"
              disabled={submitting}
              className="w-full px-3 py-2.5 font-body text-[15px] italic border-0 border-b transition-colors focus:outline-none disabled:opacity-50"
              style={{
                backgroundColor: 'transparent',
                color: 'var(--sf-text)',
                borderColor: 'var(--sf-border)',
              }}
            />
          </div>

          {mode === 'register' && (
            <div>
              <label
                htmlFor="login-displayname"
                className="block text-[10px] font-mono uppercase tracking-[0.15em] mb-1.5"
                style={{ color: 'var(--sf-muted)' }}
              >
                显示名 <span style={{ opacity: 0.6 }}>(可选)</span>
              </label>
              <input
                id="login-displayname"
                type="text"
                maxLength={64}
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                placeholder="张三 / Dr. Smith"
                disabled={submitting}
                className="w-full px-3 py-2.5 font-body text-[15px] italic border-0 border-b transition-colors focus:outline-none disabled:opacity-50"
                style={{
                  backgroundColor: 'transparent',
                  color: 'var(--sf-text)',
                  borderColor: 'var(--sf-border)',
                }}
              />
            </div>
          )}

          {error && (
            <div
              role="alert"
              className="text-xs font-body px-3 py-2.5"
              style={{
                backgroundColor: 'var(--sf-bg-elev)',
                color: 'var(--sf-accent)',
                borderLeft: '3px solid var(--sf-accent)',
              }}
            >
              <span className="font-display italic font-semibold">⚠</span> {error}
            </div>
          )}

          <button
            type="submit"
            disabled={submitting || !email.trim()}
            className="w-full py-2.5 px-4 text-sm font-display italic font-semibold transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            style={{
              backgroundColor: 'var(--sf-accent)',
              color: 'var(--sf-bg)',
            }}
          >
            {submitting
              ? '处理中…'
              : mode === 'register'
              ? '注册并进入 →'
              : '登录并进入 →'}
          </button>

          {/* 期刊页脚式小字 — 3 条说明 */}
          <div
            className="text-[10px] font-ui leading-relaxed pt-4 mt-2 border-t space-y-1.5"
            style={{
              color: 'var(--sf-muted)',
              borderColor: 'var(--sf-border)',
            }}
          >
            <p>
              <span className="font-mono" style={{ color: 'var(--sf-accent)' }}>注 ·</span>{' '}
              系统会生成 API Key 存到 localStorage,
              后续请求自动带 <code className="font-mono text-[10px] px-1 py-0.5" style={{ backgroundColor: 'var(--sf-bg-elev)' }}>X-API-Key</code> header.
            </p>
            <p
              className="text-[10px] mt-1"
              style={{ color: 'var(--sf-muted)' }}
              title="R10.5.24 深度审计: localStorage 任何 XSS 都能读走. R11+ 计划改 HttpOnly+SameSite=Strict cookie (后端 set-cookie) + CSRF token 头."
            >
              ⚠️ localStorage 任何 XSS 都能读走 API Key, 公共电脑请退出登录.
            </p>
            <p>
              <span className="font-mono" style={{ color: 'var(--sf-accent)' }}>注 ·</span>{' '}
              邮箱作 user_id, 同邮箱重登生成新 key (旧 key 失效).
            </p>
            <p>
              <span className="font-mono" style={{ color: 'var(--sf-accent)' }}>注 ·</span>{' '}
              限流 5/min · 20/hour (防字典攻击).
            </p>
          </div>
        </form>
      </div>
    </div>
  );
}
