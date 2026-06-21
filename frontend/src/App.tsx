/**
 * App.tsx — R10.5.54 frontend rebuild
 *
 * Phase 1 壳子: Provider + TopNav + 4-tab 路由 + 命令面板 + 认证对话框.
 * 目标 ~120 LOC. 取代之前 877 行的巨文件.
 *
 * Phase 2-4 接入: SearchWorkspace 真实 SSE, GraphView (改写), CompareDrawer, HistoryView.
 */
import { useEffect, useCallback } from 'react';
import { useStore, actions, getState } from './store/useStore';
import type { ThemeId } from './lib/tokens';
import { TopNav } from './components/TopNav';
import { SearchWorkspace } from './components/SearchWorkspace';
import { ReportView } from './components/ReportView';
import { GraphPage } from './components/GraphPage';
import { HistoryView } from './components/HistoryView';
import { CommandPalette } from './components/CommandPalette';
import { AuthDialog } from './components/AuthDialog';
import { ChangelogModal } from './components/ChangelogModal';
import { CompareDrawer } from './components/CompareDrawer';
import { SettingsDrawer } from './components/SettingsDrawer';
import { useT } from './i18n';

export default function App() {
  const currentView = useStore((s) => s.currentView);
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
        if (s.settingsDrawerOpen) { actions.closeSettingsDrawer(); return; }
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

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
        {/* R10.5.59: 'settings' tab 已删除. 4 个 tab 渲染如上. */}
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

      <CommandPalette cycleTheme={cycleTheme} cancelSearch={cancelSearch} />
      <AuthDialog />
      <ChangelogModal />
      <CompareDrawer />
      <SettingsDrawer />
    </div>
  );
}