/**
 * UserBadge — 工具栏右上角当前用户徽标 + 退出下拉 (R10.5.3)
 *
 * 显示:
 *  - 正常用户: 👤 张三 ▼  (点击展开 dropdown 含退出)
 *  - OPEN_MODE: 🔓 开发模式 (灰色, 不可点击, 鼠标悬停提示)
 */
import { useEffect, useRef, useState } from 'react';
import type { UserInfo } from '../services/api';

interface Props {
  user: UserInfo | null;
  openMode: boolean;
  onLogout: () => void;
  loading?: boolean;
}

export function UserBadge({ user, openMode, onLogout, loading }: Props) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  // 点击外部关闭 dropdown
  useEffect(() => {
    if (!open) return;
    const onClickOutside = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', onClickOutside);
    return () => document.removeEventListener('mousedown', onClickOutside);
  }, [open]);

  // 启动检测中: 不闪烁, 显示微 spinner
  if (loading) {
    return (
      <div
        className="flex items-center gap-1.5 px-2 py-1 text-[11px] font-mono uppercase tracking-[0.12em]"
        title="正在检查登录态…"
        style={{ color: 'var(--sf-muted)' }}
      >
        <span
          className="inline-block w-2.5 h-2.5 border-2 border-t-transparent rounded-full animate-spin"
          style={{ borderColor: 'var(--sf-border)', borderTopColor: 'transparent' }}
        />
        <span>载入</span>
      </div>
    );
  }

  // OPEN_MODE=true: Editorial 风格 "open access" 标记
  if (openMode) {
    return (
      <div
        className="flex items-center gap-1.5 px-2 py-1 text-[10px] font-mono uppercase tracking-[0.18em]"
        title="OPEN_MODE=true: 后端跳过认证, 所有用户共享 dev-user 账户"
        style={{
          color: 'var(--sf-muted)',
        }}
      >
        <span style={{ color: 'var(--sf-accent)' }}>○</span>
        <span>开发模式</span>
      </div>
    );
  }

  // 正常用户徽标
  if (!user) return null;

  return (
    <div ref={ref} className="relative inline-block">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-label="用户菜单"
        aria-expanded={open}
        title={`用户: ${user.display_name}`}
        className="flex items-center gap-1.5 px-2 py-1 text-[11px] font-mono uppercase tracking-[0.12em] transition-colors"
        style={{
          backgroundColor: 'var(--sf-bg)',
          color: 'var(--sf-text)',
          border: '1px solid var(--sf-border)',
        }}
      >
        <span style={{ color: 'var(--sf-accent)' }}>●</span>
        <span
          className="font-display italic font-semibold normal-case tracking-normal text-[12px] max-w-[120px] truncate"
          style={{ color: 'var(--sf-text)' }}
        >
          {user.display_name}
        </span>
        <span className="text-[9px] opacity-60">▾</span>
      </button>

      {open && (
        <div
          className="absolute right-0 mt-1 z-20 min-w-[220px] overflow-hidden font-ui"
          style={{
            backgroundColor: 'var(--sf-bg-elev)',
            border: '1px solid var(--sf-border)',
            boxShadow: 'var(--sf-shadow)',
            color: 'var(--sf-text)',
          }}
          role="menu"
        >
          <div
            className="px-3 py-2.5 text-[10px] border-b"
            style={{
              borderColor: 'var(--sf-border)',
              color: 'var(--sf-muted)',
            }}
          >
            <div
              className="font-mono text-[9px] uppercase tracking-[0.15em] mb-1"
              style={{ color: 'var(--sf-accent)' }}
            >
              Subscriber
            </div>
            <div className="font-mono text-[10px] opacity-80">{user.user_id}</div>
            <div className="font-mono text-[10px] mt-0.5 tabular-nums">
              注册: {new Date(user.created_at * 1000).toLocaleDateString('zh-CN')}
            </div>
          </div>
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              setOpen(false);
              onLogout();
            }}
            className="w-full text-left px-3 py-2 text-xs transition-colors flex items-center gap-2"
            style={{ color: 'var(--sf-accent)' }}
            onMouseEnter={(e) => {
              e.currentTarget.style.backgroundColor = 'var(--sf-bg)';
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.backgroundColor = 'transparent';
            }}
          >
            <span>⏻</span>
            <span>退出登录</span>
          </button>
        </div>
      )}
    </div>
  );
}
