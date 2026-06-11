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
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ backgroundColor: 'rgba(15, 23, 42, 0.55)' }}
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

      <div
        className="relative w-full max-w-md rounded-lg shadow-xl border p-6"
        style={{
          backgroundColor: 'var(--sf-bg, #ffffff)',
          color: 'var(--sf-text, #0f172a)',
          borderColor: 'var(--sf-border, #e2e8f0)',
        }}
      >
        {/* 标题 + 关闭按钮 (仅在 !requireAuth 时显示) */}
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2
              id="login-dialog-title"
              className="text-lg font-semibold"
              style={{ color: 'var(--sf-text, #0f172a)' }}
            >
              🔐 登录 ScholarFlow
            </h2>
            <p className="text-xs mt-1 opacity-70">
              学术邮箱即身份, 无需密码 (高校信任模型)
            </p>
          </div>
          {!requireAuth && onClose && (
            <button
              type="button"
              onClick={onClose}
              aria-label="关闭"
              className="text-xl opacity-60 hover:opacity-100 transition px-2"
            >
              ×
            </button>
          )}
        </div>

        {/* Tabs: 注册 / 登录 (后端是同一端点, 这里只是 UX 区分) */}
        <div className="flex border-b mb-4" style={{ borderColor: 'var(--sf-border, #e2e8f0)' }}>
          {(['register', 'login'] as Mode[]).map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => {
                setMode(m);
                setError(null);
              }}
              className={`flex-1 py-2 text-sm font-medium transition border-b-2 -mb-px ${
                mode === m
                  ? 'border-brand-500 text-brand-600'
                  : 'border-transparent opacity-60 hover:opacity-100'
              }`}
            >
              {m === 'register' ? '新用户注册' : '已有账号登录'}
            </button>
          ))}
        </div>

        <form onSubmit={handleSubmit} className="space-y-3">
          <div>
            <label
              htmlFor="login-email"
              className="block text-xs font-medium mb-1 opacity-80"
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
              className="w-full px-3 py-2 text-sm border rounded-md focus:outline-none focus:ring-2 focus:ring-brand-500 disabled:opacity-50"
              style={{
                backgroundColor: 'var(--sf-bg, #ffffff)',
                color: 'var(--sf-text, #0f172a)',
                borderColor: 'var(--sf-border, #e2e8f0)',
              }}
            />
          </div>

          {mode === 'register' && (
            <div>
              <label
                htmlFor="login-displayname"
                className="block text-xs font-medium mb-1 opacity-80"
              >
                显示名 <span className="opacity-60">(可选, 默认用邮箱)</span>
              </label>
              <input
                id="login-displayname"
                type="text"
                maxLength={64}
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                placeholder="张三 / Dr. Smith"
                disabled={submitting}
                className="w-full px-3 py-2 text-sm border rounded-md focus:outline-none focus:ring-2 focus:ring-brand-500 disabled:opacity-50"
                style={{
                  backgroundColor: 'var(--sf-bg, #ffffff)',
                  color: 'var(--sf-text, #0f172a)',
                  borderColor: 'var(--sf-border, #e2e8f0)',
                }}
              />
            </div>
          )}

          {error && (
            <div
              role="alert"
              className="text-xs px-3 py-2 rounded border"
              style={{
                backgroundColor: '#fef2f2',
                borderColor: '#fecaca',
                color: '#b91c1c',
              }}
            >
              ⚠️ {error}
            </div>
          )}

          <button
            type="submit"
            disabled={submitting || !email.trim()}
            className="w-full py-2 px-4 text-sm font-medium rounded-md transition disabled:opacity-50 disabled:cursor-not-allowed"
            style={{
              backgroundColor: submitting ? '#94a3b8' : '#2563eb',
              color: '#ffffff',
            }}
          >
            {submitting
              ? '处理中…'
              : mode === 'register'
              ? '注册并进入'
              : '登录并进入'}
          </button>

          <div className="text-[11px] opacity-60 leading-relaxed pt-2 border-t" style={{ borderColor: 'var(--sf-border, #e2e8f0)' }}>
            <p>
              📌 <strong>说明</strong>: 注册后系统会生成 API Key 并存到 localStorage,
              后续请求自动带 <code className="font-mono">X-API-Key</code> header.
            </p>
            <p className="mt-1">
              ⚠️ 邮箱被用作 user_id, 同一邮箱重复登录会生成新 key (旧 key 失效).
            </p>
            <p className="mt-1">
              🔒 限流: 每 IP 每分钟 5 次 / 每小时 20 次 (防字典攻击).
            </p>
          </div>
        </form>
      </div>
    </div>
  );
}
