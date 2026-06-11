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
        className="flex items-center gap-1 px-2 py-1 text-xs opacity-60"
        title="正在检查登录态…"
      >
        <span className="inline-block w-3 h-3 border-2 border-slate-300 border-t-brand-500 rounded-full animate-spin" />
      </div>
    );
  }

  // OPEN_MODE=true: 灰色 badge, 不可点击 (说明当前是开发模式)
  if (openMode) {
    return (
      <div
        className="flex items-center gap-1 px-2 py-1 text-xs rounded-md border"
        title="OPEN_MODE=true: 后端跳过认证, 所有用户共享 dev-user 账户"
        style={{
          backgroundColor: 'var(--sf-bg, #ffffff)',
          color: 'var(--sf-text, #0f172a)',
          borderColor: 'var(--sf-border, #e2e8f0)',
          opacity: 0.7,
        }}
      >
        <span>🔓</span>
        <span className="font-medium">开发模式</span>
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
        className="flex items-center gap-1 px-2 py-1 text-xs border border-slate-300 rounded-md hover:bg-slate-100 transition"
        style={{
          backgroundColor: 'var(--sf-bg, #ffffff)',
          color: 'var(--sf-text, #0f172a)',
        }}
      >
        <span>👤</span>
        <span className="font-medium max-w-[120px] truncate">
          {user.display_name}
        </span>
        <span className="text-[10px] opacity-60">▼</span>
      </button>

      {open && (
        <div
          className="absolute right-0 mt-1 z-20 min-w-[200px] border rounded-md shadow-lg overflow-hidden"
          style={{
            backgroundColor: 'var(--sf-bg, #ffffff)',
            borderColor: 'var(--sf-border, #e2e8f0)',
            color: 'var(--sf-text, #0f172a)',
          }}
          role="menu"
        >
          <div className="px-3 py-2 text-[11px] opacity-70 border-b" style={{ borderColor: 'var(--sf-border, #e2e8f0)' }}>
            <div className="font-mono text-[10px] opacity-60">{user.user_id}</div>
            <div className="mt-0.5">
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
            className="w-full text-left px-3 py-2 text-xs hover:bg-rose-50 transition flex items-center gap-1.5"
            style={{ color: '#b91c1c' }}
          >
            <span>🚪</span>
            <span>退出登录</span>
          </button>
        </div>
      )}
    </div>
  );
}
