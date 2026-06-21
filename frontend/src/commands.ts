/**
 * commands.ts — R10.5.54 命令注册表
 *
 * CommandPalette 通过这个 registry 渲染可用命令.
 * App.tsx 注入 registry, palette 保持 dumb.
 */

export interface Command {
  id: string;
  label: string;
  hint?: string;
  group?: string;
  keywords?: string[];
  run: () => void;
}

export function buildCommands(opts: {
  goToView: (v: 'search' | 'report' | 'graph' | 'history') => void;
  cycleTheme: () => void;
  cancelSearch: () => void;
  openAuth: () => void;
  openChangelog: () => void;
  openSettings: () => void;
  isLoading: boolean;
  t: (k: string) => string;
}): Command[] {
  const tr = opts.t;
  const cmds: Command[] = [
    {
      id: 'view.search',
      label: tr('palette.goSearch'),
      hint: tr('palette.search'),
      group: 'View',
      keywords: ['search', 'query', 'home'],
      run: () => opts.goToView('search'),
    },
    {
      id: 'view.report',
      label: tr('palette.goReport'),
      hint: tr('palette.report'),
      group: 'View',
      keywords: ['report', 'read'],
      run: () => opts.goToView('report'),
    },
    {
      id: 'view.graph',
      label: tr('palette.goGraph'),
      hint: tr('palette.graph'),
      group: 'View',
      keywords: ['graph', 'd3', 'citation'],
      run: () => opts.goToView('graph'),
    },
    {
      id: 'view.history',
      label: tr('palette.goHistory'),
      hint: tr('palette.history'),
      group: 'View',
      keywords: ['history', 'recent'],
      run: () => opts.goToView('history'),
    },
    {
      id: 'view.settings',
      label: tr('palette.goSettings'),
      hint: tr('palette.settings'),
      group: 'View',
      keywords: ['settings', 'config', 'preferences'],
      run: () => opts.openSettings(),
    },
    {
      id: 'theme.cycle',
      label: tr('palette.themeCycle'),
      hint: tr('palette.themeCycle'),
      group: 'Theme',
      keywords: ['theme', 'color', 'cycle'],
      run: () => opts.cycleTheme(),
    },
    {
      id: 'auth.open',
      label: tr('palette.authTitle'),
      hint: tr('palette.auth'),
      group: 'Account',
      keywords: ['login', 'signin', 'register', 'auth', 'key'],
      run: () => opts.openAuth(),
    },
    {
      id: 'changelog.open',
      label: tr('palette.changelogTitle'),
      hint: tr('palette.changelog'),
      group: 'Help',
      keywords: ['changelog', 'release', 'version'],
      run: () => opts.openChangelog(),
    },
  ];
  if (opts.isLoading) {
    cmds.push({
      id: 'search.cancel',
      label: tr('palette.cancelTitle'),
      hint: tr('palette.cancel'),
      group: 'Search',
      keywords: ['cancel', 'stop'],
      run: () => opts.cancelSearch(),
    });
  }
  return cmds;
}