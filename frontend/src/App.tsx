/**
 * App.tsx — R10.5.59 frontend shell
 *
 * 5 tabs (查询/报告/图谱/历史/关于) + 左侧 SettingsSidebar (常驻可收起)
 * + 命令面板 + 认证对话框 + 更新日志 modal + 对比 drawer.
 */
import { useEffect, useCallback } from 'react';
import { useStore, actions, getState } from './store/useStore';
import type { ThemeId } from './lib/tokens';
import { TopNav } from './components/TopNav';
import { SearchWorkspace } from './components/SearchWorkspace';
import { ReportView } from './components/ReportView';
import { GraphPage } from './components/GraphPage';
import { HistoryView } from './components/HistoryView';
import { AboutView } from './components/AboutView';
import { CommandPalette } from './components/CommandPalette';
import { AuthDialog } from './components/AuthDialog';
import { ChangelogModal } from './components/ChangelogModal';
import { CompareDrawer } from './components/CompareDrawer';
import { SettingsSidebar } from './components/SettingsSidebar';
import { useT } from './i18n';

export default function App() {
  const currentView = useStore((s) => s.currentView);
  const settingsCollapsed = useStore((s) => s.settingsCollapsed);
  const t = useT();

  // Cycle theme helper
  const cycleTheme = useCallback(() => {
    const order: ThemeId[] = ['parchment', 'kraft', 'midnight', 'sage'];
    const current = getState().theme;
    const idx = order.indexOf(current);
    actions.setTheme(order[(idx + 1) % order.length]);
  }, []);

  // Cancel search — Phase 1 placeholder
  const cancelSearch = useCallback(() => {
    actions.setState({ loading: false });
  }, []);

  // Global keybindings
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const cmd = e.metaKey || e.ctrlKey;
      const s = getState();
      // Cmd+K / Ctrl+K → command palette
      if (cmd && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        if (s.commandPaletteOpen) {
          actions.closeCommandPalette();
        } else {
          actions.openCommandPalette();
        }
        return;
      }
      // Esc → close modals
      if (e.key === 'Escape') {
        if (s.commandPaletteOpen) { actions.closeCommandPalette(); return; }
        if (s.authDialogOpen) { actions.closeAuthDialog(); return; }
        if (s.changelogOpen) { actions.closeChangelog(); return; }
        if (s.compareDrawerOpen) { actions.closeCompareDrawer(); return; }
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  // Layout: 左侧 SettingsSidebar (220 / 48 wide) + 主体内容 (marginLeft 偏移)
  const sidebarWidth = settingsCollapsed ? 48 : 220;

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        flexDirection: 'column',
        backgroundColor: 'var(--sf-bg)',
        color: 'var(--sf-text)',
      }}
    >
      <SettingsSidebar />

      {/* 主内容区, 左边距让出 SettingsSidebar */}
      <div
        style={{
          marginLeft: sidebarWidth,
          transition: 'margin-left 180ms ease',
          display: 'flex',
          flexDirection: 'column',
          minHeight: '100vh',
        }}
      >
        <TopNav />

        <main
          style={{
            flex: 1,
            minHeight: 0,
            overflowY: 'auto',
          }}
        >
          {currentView === 'search' && <SearchWorkspace />}
          {currentView === 'report' && <ReportView />}
          {currentView === 'graph' && <GraphPage />}
          {currentView === 'history' && <HistoryView />}
          {currentView === 'about' && <AboutView />}
        </main>

        <footer
          style={{
            borderTop: '1px solid var(--sf-border)',
            padding: '8px 24px',
            display: 'flex',
            gap: 16,
            alignItems: 'center',
            backgroundColor: 'var(--sf-bg)',
          }}
        >
          <span className="font-mono" style={{ fontSize: 11, color: 'var(--sf-muted)' }}>
            {t('footer.history')}
          </span>
          <span className="font-mono" style={{ fontSize: 11, color: 'var(--sf-muted)' }}>
            {t('footer.shortcuts')}
          </span>
          <button
            type="button"
            onClick={actions.openChangelog}
            className="font-mono"
            style={{
              marginLeft: 'auto',
              fontSize: 11,
              color: 'var(--sf-muted)',
              background: 'none',
              border: 'none',
              padding: 0,
              cursor: 'pointer',
            }}
          >
            R10.5.59 changelog
          </button>
        </footer>
      </div>

      <CommandPalette cycleTheme={cycleTheme} cancelSearch={cancelSearch} />
      <AuthDialog />
      <ChangelogModal />
      <CompareDrawer />
    </div>
  );
}