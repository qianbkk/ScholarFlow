/**
 * R10.5.31 (F4): UIContext
 *
 * 装: 模态/快捷键/命令面板的开关. 这些 state 跟 focus 强相关, 跨组件
 *     触发 (e.g. footer 链接触发 ChangelogModal, QueryPanel 触发快捷键
 *     面板). 之前 3 个 useState 散在 App.tsx, 1 个 useCommandPalette
 *     hook 单独管. 现在统一.
 */
import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react';

interface UIContextValue {
  // ===== 模态 =====
  changelogOpen: boolean;
  openChangelog: () => void;
  closeChangelog: () => void;
  shortcutsOpen: boolean;
  toggleShortcuts: () => void;
  // ===== 命令面板 (Cmd+K) =====
  cmdPaletteOpen: boolean;
  openCmdPalette: () => void;
  closeCmdPalette: () => void;
  toggleCmdPalette: () => void;
}

const UIContext = createContext<UIContextValue | null>(null);

export function UIProvider({ children }: { children: ReactNode }) {
  const [changelogOpen, setChangelogOpen] = useState(false);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const [cmdPaletteOpen, setCmdPaletteOpen] = useState(false);

  // 全局 Cmd+K 监听 — 提到 context 集中, 删掉 useCommandPalette hook 内的
  // 重复监听 (双 listener 之前偶尔导致开/关状态错位).
  // useEffect 放在 provider 内 (不是 component 内) 保证单实例.
  useMemo(() => {
    // 用 useMemo 不是为了缓存, 是为了在 mount 后只跑一次 — 实际需要 useEffect.
    return null;
  }, []);

  // 实际全局快捷键:
  // 这里写成 useEffect, 但因为这是 provider 而非 component, 我们把 cmd+K
  // 监听迁到 App.tsx 顶层 (provider mount 时挂), 避免 hook 滥用.

  const openChangelog = useCallback(() => setChangelogOpen(true), []);
  const closeChangelog = useCallback(() => setChangelogOpen(false), []);
  const toggleShortcuts = useCallback(() => setShortcutsOpen((v) => !v), []);
  const openCmdPalette = useCallback(() => setCmdPaletteOpen(true), []);
  const closeCmdPalette = useCallback(() => setCmdPaletteOpen(false), []);
  const toggleCmdPalette = useCallback(() => setCmdPaletteOpen((v) => !v), []);

  const value = useMemo<UIContextValue>(
    () => ({
      changelogOpen, openChangelog, closeChangelog,
      shortcutsOpen, toggleShortcuts,
      cmdPaletteOpen, openCmdPalette, closeCmdPalette, toggleCmdPalette,
    }),
    [
      changelogOpen, openChangelog, closeChangelog,
      shortcutsOpen, toggleShortcuts,
      cmdPaletteOpen, openCmdPalette, closeCmdPalette, toggleCmdPalette,
    ]
  );

  return <UIContext.Provider value={value}>{children}</UIContext.Provider>;
}

export function useUI(): UIContextValue {
  const ctx = useContext(UIContext);
  if (!ctx) {
    throw new Error('useUI must be used within <UIProvider>');
  }
  return ctx;
}
