/**
 * i18n — R10.5.59 完整中英文切换
 *
 * 默认 zh (中文), 用户可切 en (英文). 专有名词 (Semantic Scholar, OpenAlex,
 * API Key, Author, BibTeX, RIS, kimi, glm, minimax, Anthropic 等) 保留英文.
 *
 * 用法:
 *   import { useT } from '../i18n';
 *   const t = useT();
 *   <p>{t('nav.search')}</p>  // → "查询" (zh) | "Search" (en)
 *   <p>{t('summary.meta', { n: 25, iters: 2, cost: '0.05', tokens: 1000, sec: '12.3' })}</p>
 */
import { useSyncExternalStore } from 'react';
import { useStore, actions, getState } from '../store/useStore';

export type Locale = 'zh' | 'en';

// ===== 字典 =====
type Dict = Record<string, string>;

const dictZh: Dict = {
  // ===== TopNav tabs =====
  'nav.search': '查询',
  'nav.report': '报告',
  'nav.graph': '图谱',
  'nav.history': '历史',
  'nav.about': '关于',

  // ===== TopNav misc =====
  'topbar.nav': '主导航',
  'topbar.viewTabs': '主视图',
  'topbar.running': '运行中',
  'topbar.openSettings': '打开设置',
  'topbar.goSearch': '回到 Search',
  'topbar.goSearch.zh': '回到 Search',

  // ===== Search view (SearchWorkspace) =====
  'search.title': '提出一个研究问题',
  'search.subtitle': '8 节点 LangGraph 流水线 · 实时思考日志 · 可调节论文数 3-30 篇',

  // ===== QueryInput =====
  'query.placeholder': '例如 transformer attention mechanism survey',
  'query.provider': 'provider',
  'query.budget': '预算',
  'query.iter': '迭代',
  'query.papers': '论文',
  'query.papersMin': '最少论文数',
  'query.papersMax': '最多论文数',
  'query.ask': '提问 →',
  'query.signin': '登录 →',
  'query.cancel': '取消',
  'query.recent': '最近 {n} 条',

  // ===== PipelineProgress =====
  'pipeline.title': '8 节点 LangGraph 流水线',
  'pipeline.running': '运行中',
  'pipeline.done': '完成',
  'pipeline.node.query_decompose': '查询分解',
  'pipeline.node.search': '双源检索',
  'pipeline.node.expand_citations': '引文扩展',
  'pipeline.node.rank': '三维排序',
  'pipeline.node.refine': '查询优化',
  'pipeline.node.synthesize': '综述生成',
  'pipeline.node.build_graph': '图谱构建',
  'pipeline.node.track_cost': '成本汇总',
  'pipeline.thinkingTitle': '思考日志',
  'pipeline.thinkingEmpty': '暂无思考日志',
  'pipeline.evolution': '图谱演化 (Evolution)',
  'pipeline.evolutionSnap': 'V{iter}: {n} 节点 · {l} 边',

  // ===== SearchSummary =====
  'summary.meta': '{n} 篇 · {iters} 轮 · ${cost} · {tokens} tokens · {sec}s',
  'summary.cites': '引用 {n}',
  'summary.viewReport': '查看完整报告',

  // ===== ReportView =====
  'report.title': '研究综述',
  'report.empty': '暂无报告 — 先在 Search 跑一次查询.',
  'report.goSearch': '回到 Search',
  'report.backSearch': '回到 Search',
  'report.download': '下载',
  'report.download.bib': '↓ .bib',
  'report.download.ris': '↓ .ris',
  'report.download.md': '↓ .md',
  'report.anchored': '锚定论文 · {n}',

  // ===== GraphPage =====
  'graph.title': '引文图谱',
  'graph.empty': '暂无图谱 — 先在 Search 跑一次查询.',
  'graph.emptyFilter': '当前过滤无匹配节点 · 调整年份 / 作者筛选',
  'graph.noData': '暂无图谱数据',
  'graph.noDataHint': '完成搜索后将自动构建引文关系图',
  'graph.noResults': '未检索到论文关联',
  'graph.noResultsHint': '尝试更换关键词重新搜索',
  'graph.fit': '适配',
  'graph.fullscreen': '全屏',
  'graph.exitFullscreen': '退出',
  'graph.clear': '清除',
  'graph.neighbors': '{n} 邻居',
  'graph.neighborsHint': '2 跳邻居数 (含自身)',
  'graph.zoomLevel': '当前缩放: {k}x (按 f 适配)',
  'graph.filterYear': '年份',
  'graph.filterYearMin': '起始年份',
  'graph.filterYearMax': '结束年份',
  'graph.filterAuthor': '作者',
  'graph.filterAuthorPlaceholder': '子串过滤',
  'graph.filterClear': '清空',
  'graph.filterCount': '{visible} / {total} 节点',
  'graph.exitFullscreenHint': '按下 Esc 退出全屏, 回到原位浏览',
  'graph.exitFullscreenLabel': '退出全屏',
  'graph.fitTooltip': '适配视图 (f)',
  'graph.fullscreenTooltip': '全屏看图 (Shift+F)',
  'graph.fullscreenExitTooltip': '退出全屏 (Esc)',
  'graph.clearTooltip': '清选中 (Esc)',
  'graph.legend': '边类型',
  'graph.legendExpand': '展开图例',
  'graph.legendCollapse': '折叠图例',
  'graph.legend.cites': 'cites',
  'graph.legend.coCited': 'co-cited',
  'graph.legend.sameVenue': 'same venue',
  'graph.legend.authorOverlap': 'author overlap',
  'graph.legendHint': '节点大小 = log(引用数) · 颜色 = 社区',
  'graph.hint.click': '单击 = 高亮 1 跳邻居 · 双击 = 打开论文',
  'graph.hint.drag': '拖动 = 固定位置 · 右键 = 解除固定',
  'graph.hint.zoom': '滚轮 = 缩放 · 空白处拖动 = 平移',
  'graph.tooltip.citations': '引用数',
  'graph.tooltip.score': '评分',
  'graph.tooltip.inOut': '入度 / 出度',
  'graph.tooltip.pr': 'PageRank',

  // ===== HistoryView =====
  'history.title': '历史记录',
  'history.emptyTitle': '暂无历史',
  'history.empty': '回到 Search tab 跑一次试试.',
  'history.rerun': '重跑 →',
  'history.open': '打开',
  'history.sourceReal': '真实 API',
  'history.sourceLocal': '本地 mock',
  'history.sourceUnknown': '未知',

  // ===== AboutView (R10.5.59) =====
  'about.title': '关于',
  'about.project': 'ScholarFlow',
  'about.subtitle': '多 Agent 学术文献综述工具',
  'about.version': '版本',
  'about.author': '作者',
  'about.github': 'GitHub',
  'about.desc': '多 Agent 学术文献综述工具 — 提问, 看 8 节点 LangGraph 流水线工作, 拿到带引用的报告.',
  'about.shortcuts.title': '键盘快捷键',
  'about.shortcuts.cmdK': '打开命令面板',
  'about.shortcuts.cmdEnter': '提交查询',
  'about.shortcuts.esc': '关闭弹窗 / 清选中',
  'about.shortcuts.f': '适配图谱 (Graph tab)',
  'about.shortcuts.shiftF': '切换全屏 (Graph tab)',
  'about.changelog.title': '更新日志',

  // ===== SettingsSidebar (R10.5.59: 常驻左侧可收起) =====
  'sidebar.title': '设置',
  'sidebar.expand': '展开',
  'sidebar.collapse': '收起',
  'sidebar.language': '语言',
  'sidebar.keySet': '已配置 key',
  'sidebar.addKey': '添加 API key',
  'sidebar.manageKeys': '管理 API key',
  'sidebar.save': '保存',
  'sidebar.alias': '代号',
  'sidebar.delete': '删除',
  'sidebar.keysCount': '{n} / 10 已配置',
  'sidebar.fullSlot': '已满',

  // ===== SettingsDrawer (保留兼容) =====
  'settings.title': '设置',
  'settings.theme': '主题色系',
  'settings.runtimeMode': '运行时模式',
  'settings.runtimeModeDesc': 'LLM 检索模式走真实学术 API, 不允许降级到本地 mock.',
  'settings.apiKey': 'API Key',
  'settings.apiKeySet': '●●●●●●●● 已设置',
  'settings.apiKeyEmpty': '○ 未设置',
  'settings.apiKeyDesc': '仅保存在当前标签页. 关闭此窗口即清除.',
  'settings.keyboard': '键盘快捷键',
  'settings.about': '关于',
  'settings.aboutDesc': 'ScholarFlow · R10.5.59 frontend rebuild',
  'settings.changelog': '更新日志',
  'settings.kb.cmdK': '打开命令面板',
  'settings.kb.cmdEnter': '提交查询',
  'settings.kb.esc': '关闭弹窗 / 取消搜索',
  'settings.kb.fit': '适配视图 (fit-to-view)',
  'settings.kb.fullscreen': '全屏图谱',

  // ===== AuthDialog =====
  'auth.title.signin': '登录',
  'auth.title.signup': '注册',
  'auth.title.account': '账户',
  'auth.desc.signin': '已注册? 用邮箱 + 密码登录. 旧 key 失效, 拿新 key.',
  'auth.desc.signup': '首次使用? 邮箱注册即拿 API key. 设密码 (≥8 字符) 保护账户.',
  'auth.email': '邮箱',
  'auth.displayName': '显示名 (可选)',
  'auth.password': '密码 (≥8 字符, 留空走 passwordless)',
  'auth.passwordPlaceholderSignup': '至少 8 字符',
  'auth.passwordPlaceholderSignin': '你的密码',
  'auth.confirmPassword': '确认密码',
  'auth.confirmPlaceholder': '再输入一次',
  'auth.signin': '登录 →',
  'auth.signup': '注册 →',
  'auth.cancel': '取消',
  'auth.close': '关闭',
  'auth.signout': '退出登录 →',
  'auth.rotate': '轮换 API key',
  'auth.tab.signup': '注册',
  'auth.tab.signin': '登录',
  'auth.err.emailNotRegistered': '邮箱未注册, 请先注册.',
  'auth.err.wrongPassword': '密码错误.',
  'auth.err.alreadyRegistered': '该邮箱已注册, 请直接登录.',
  'auth.err.weakPassword': '密码至少 8 字符.',
  'auth.err.openMode': 'OPEN_MODE=true 时不支持注册.',
  'auth.err.emailRequired': '请输入邮箱',
  'auth.err.passwordMismatch': '两次密码输入不一致',
  'auth.err.signupFail': '注册失败',
  'auth.err.signinFail': '登录失败',
  'auth.err.rotateFail': '轮换失败',
  'auth.notice.signup': '注册成功 — API key 已保存到此标签页',
  'auth.notice.signin': '登录成功',
  'auth.notice.rotated': '欢迎回来, API key 已自动轮换.',
  'auth.sessionHint': 'API key 保存在 sessionStorage, 关浏览器即失效.',

  // ===== CommandPalette =====
  'palette.search': '查询 / 流水线 / 报告',
  'palette.report': '阅读报告',
  'palette.graph': '完整 D3 引文图谱 (独立 tab)',
  'palette.history': '最近搜索记录',
  'palette.settings': '左侧抽屉',
  'palette.themeCycle': 'parchment → kraft → midnight → sage',
  'palette.auth': '邮箱注册或重拿 key',
  'palette.changelog': 'release notes',
  'palette.cancel': '停止运行中的查询',
  'palette.goSearch': 'Go to Search',
  'palette.goReport': 'Go to Report',
  'palette.goGraph': 'Go to Graph',
  'palette.goHistory': 'Go to History',
  'palette.goSettings': 'Open Settings',
  'palette.themeCycleTitle': 'Cycle theme',
  'palette.authTitle': 'Sign in / Rotate API key',
  'palette.changelogTitle': 'Show changelog',
  'palette.cancelTitle': 'Cancel current search',

  // ===== ChangelogModal / footer =====
  'footer.history': '← → history',
  'footer.shortcuts': '? shortcuts',

  // ===== Common =====
  'common.theme.parchment': '羊皮纸',
  'common.theme.kraft': '牛皮纸',
  'common.theme.midnight': '午夜',
  'common.theme.sage': '鼠尾草',
  'common.runtime.local': '本地模式',
  'common.runtime.llm': 'LLM 检索',
  'common.cite': '引用',
  'common.close': '关闭',
  'common.cancel': '取消',
  'common.error': '错误',
  'common.signin': 'Sign in',
  'common.signinArrow': 'Sign in →',
  'common.askArrow': 'Ask →',
  'common.recentOpen': 'recent ({n})',
};

const dictEn: Dict = {
  // ===== TopNav tabs =====
  'nav.search': 'Search',
  'nav.report': 'Report',
  'nav.graph': 'Graph',
  'nav.history': 'History',
  'nav.about': 'About',

  // ===== TopNav misc =====
  'topbar.nav': 'Main navigation',
  'topbar.viewTabs': 'Main views',
  'topbar.running': 'Running',
  'topbar.openSettings': 'Open settings',
  'topbar.goSearch': 'Go to Search',

  // ===== Search view =====
  'search.title': 'Ask a research question',
  'search.subtitle': '8-node LangGraph pipeline · real-time thinking logs · adjustable paper count 3-30',

  // ===== QueryInput =====
  'query.placeholder': 'e.g. transformer attention mechanism survey',
  'query.provider': 'provider',
  'query.budget': 'budget',
  'query.iter': 'iter',
  'query.papers': 'papers',
  'query.papersMin': 'min paper count',
  'query.papersMax': 'max paper count',
  'query.ask': 'Ask →',
  'query.signin': 'Sign in →',
  'query.cancel': 'Cancel',
  'query.recent': 'recent ({n})',

  // ===== PipelineProgress =====
  'pipeline.title': '8-node LangGraph pipeline',
  'pipeline.running': 'Running',
  'pipeline.done': 'Done',
  'pipeline.node.query_decompose': 'Query decompose',
  'pipeline.node.search': 'Dual-source search',
  'pipeline.node.expand_citations': 'Citation expand',
  'pipeline.node.rank': '3D rank',
  'pipeline.node.refine': 'Query refine',
  'pipeline.node.synthesize': 'Synthesize',
  'pipeline.node.build_graph': 'Graph build',
  'pipeline.node.track_cost': 'Cost track',
  'pipeline.thinkingTitle': 'thinking log',
  'pipeline.thinkingEmpty': 'No thinking log yet',
  'pipeline.evolution': 'Graph evolution',
  'pipeline.evolutionSnap': 'V{iter}: {n} nodes · {l} edges',

  // ===== SearchSummary =====
  'summary.meta': '{n} papers · {iters} iter · ${cost} · {tokens} tokens · {sec}s',
  'summary.cites': '{n} citations',
  'summary.viewReport': 'View full report',

  // ===== ReportView =====
  'report.title': 'Research report',
  'report.empty': 'No report yet — run a search first.',
  'report.goSearch': 'Back to Search',
  'report.backSearch': 'Back to Search',
  'report.download': 'Download',
  'report.download.bib': '↓ .bib',
  'report.download.ris': '↓ .ris',
  'report.download.md': '↓ .md',
  'report.anchored': 'Anchored papers · {n}',

  // ===== GraphPage =====
  'graph.title': 'Citation graph',
  'graph.empty': 'No graph yet — run a search first.',
  'graph.emptyFilter': 'No nodes match the filter — adjust year / author',
  'graph.noData': 'No graph data',
  'graph.noDataHint': 'Run a search to build the citation graph',
  'graph.noResults': 'No papers linked',
  'graph.noResultsHint': 'Try a different keyword',
  'graph.fit': 'Fit',
  'graph.fullscreen': 'Full',
  'graph.exitFullscreen': 'Exit',
  'graph.clear': 'Clear',
  'graph.neighbors': '{n} neighbors',
  'graph.neighborsHint': '2-hop neighbors (incl. self)',
  'graph.zoomLevel': 'Zoom: {k}x (press f to fit)',
  'graph.filterYear': 'year',
  'graph.filterYearMin': 'start year',
  'graph.filterYearMax': 'end year',
  'graph.filterAuthor': 'author',
  'graph.filterAuthorPlaceholder': 'substring filter',
  'graph.filterClear': 'reset',
  'graph.filterCount': '{visible} / {total} nodes',
  'graph.exitFullscreenHint': 'Press Esc to exit fullscreen',
  'graph.exitFullscreenLabel': 'Exit fullscreen',
  'graph.fitTooltip': 'Fit to view (f)',
  'graph.fullscreenTooltip': 'Fullscreen (Shift+F)',
  'graph.fullscreenExitTooltip': 'Exit fullscreen (Esc)',
  'graph.clearTooltip': 'Clear selection (Esc)',
  'graph.legend': 'edge types',
  'graph.legendExpand': 'Expand legend',
  'graph.legendCollapse': 'Collapse legend',
  'graph.legend.cites': 'cites',
  'graph.legend.coCited': 'co-cited',
  'graph.legend.sameVenue': 'same venue',
  'graph.legend.authorOverlap': 'author overlap',
  'graph.legendHint': 'node size = log(citations) · color = community',
  'graph.hint.click': 'click = highlight 1-hop · dblclick = open paper',
  'graph.hint.drag': 'drag = pin position · right-click = unpin',
  'graph.hint.zoom': 'wheel = zoom · drag bg = pan',
  'graph.tooltip.citations': 'Citations',
  'graph.tooltip.score': 'Score',
  'graph.tooltip.inOut': 'In/Out',
  'graph.tooltip.pr': 'PageRank',

  // ===== HistoryView =====
  'history.title': 'History',
  'history.emptyTitle': 'No history yet',
  'history.empty': 'Run a search from the Search tab to get started.',
  'history.rerun': 'Rerun →',
  'history.open': 'Open',
  'history.sourceReal': 'Real API',
  'history.sourceLocal': 'Local mock',
  'history.sourceUnknown': 'Unknown',

  // ===== SettingsSidebar (R10.5.59) =====
  'sidebar.title': 'Settings',
  'sidebar.expand': 'Expand',
  'sidebar.collapse': 'Collapse',
  'sidebar.language': 'Language',
  'sidebar.keySet': 'keys set',
  'sidebar.addKey': 'Add API key',
  'sidebar.manageKeys': 'Manage API keys',
  'sidebar.save': 'Save',
  'sidebar.alias': 'alias',
  'sidebar.delete': 'Delete',
  'sidebar.keysCount': '{n} / 10 configured',
  'sidebar.fullSlot': 'full',

  // ===== AboutView (R10.5.59) =====
  'about.title': 'About',
  'about.project': 'ScholarFlow',
  'about.subtitle': 'Multi-agent literature survey tool',
  'about.version': 'Version',
  'about.author': 'Author',
  'about.github': 'GitHub',
  'about.desc': 'A multi-agent literature survey tool — ask a research question, watch the 8-node LangGraph pipeline work, get a cited report.',
  'about.shortcuts.title': 'Keyboard shortcuts',
  'about.shortcuts.cmdK': 'Open command palette',
  'about.shortcuts.cmdEnter': 'Submit query',
  'about.shortcuts.esc': 'Close modal / clear selection',
  'about.shortcuts.f': 'Fit graph (in Graph tab)',
  'about.shortcuts.shiftF': 'Toggle fullscreen (in Graph tab)',
  'about.changelog.title': 'Changelog',

  // ===== SettingsDrawer (legacy) =====
  'settings.title': 'Settings',
  'settings.theme': 'Theme',
  'settings.runtimeMode': 'Runtime mode',
  'settings.runtimeModeDesc': 'LLM mode hits real academic APIs and never falls back to mock.',
  'settings.apiKey': 'API Key',
  'settings.apiKeySet': '●●●●●●●● set',
  'settings.apiKeyEmpty': '○ not set',
  'settings.apiKeyDesc': 'Stored for this tab only. Closes when you close this window.',
  'settings.keyboard': 'Keyboard',
  'settings.about': 'About',
  'settings.aboutDesc': 'ScholarFlow · R10.5.59 frontend rebuild',
  'settings.changelog': 'changelog',
  'settings.kb.cmdK': 'Open command palette',
  'settings.kb.cmdEnter': 'Submit query',
  'settings.kb.esc': 'Close modal / cancel search',
  'settings.kb.fit': 'Fit graph to view',
  'settings.kb.fullscreen': 'Toggle fullscreen graph',

  // ===== AuthDialog =====
  'auth.title.signin': 'Sign in',
  'auth.title.signup': 'Sign up',
  'auth.title.account': 'Account',
  'auth.desc.signin': 'Already have an account? Sign in with email + password. Old key invalidated.',
  'auth.desc.signup': 'First time? Sign up with email to get an API key. Set password (≥8 chars) to protect your account.',
  'auth.email': 'Email',
  'auth.displayName': 'Display name (optional)',
  'auth.password': 'Password (≥8 chars, leave blank for passwordless)',
  'auth.passwordPlaceholderSignup': 'at least 8 characters',
  'auth.passwordPlaceholderSignin': 'your password',
  'auth.confirmPassword': 'Confirm password',
  'auth.confirmPlaceholder': 'enter again',
  'auth.signin': 'Sign in →',
  'auth.signup': 'Sign up →',
  'auth.cancel': 'Cancel',
  'auth.close': 'Close',
  'auth.signout': 'Sign out →',
  'auth.rotate': 'Rotate API key',
  'auth.tab.signup': 'Sign up',
  'auth.tab.signin': 'Sign in',
  'auth.err.emailNotRegistered': 'Email not registered. Please sign up first.',
  'auth.err.wrongPassword': 'Wrong password.',
  'auth.err.alreadyRegistered': 'Email already registered. Please sign in.',
  'auth.err.weakPassword': 'Password must be at least 8 characters.',
  'auth.err.openMode': 'OPEN_MODE=true does not allow sign up.',
  'auth.err.emailRequired': 'Email is required',
  'auth.err.passwordMismatch': 'Passwords do not match',
  'auth.err.signupFail': 'Sign up failed',
  'auth.err.signinFail': 'Sign in failed',
  'auth.err.rotateFail': 'Rotate failed',
  'auth.notice.signup': 'Signed up — API key saved to this tab',
  'auth.notice.signin': 'Signed in',
  'auth.notice.rotated': 'Welcome back. API key auto-rotated.',
  'auth.sessionHint': 'API key saved in sessionStorage. Clears when you close the browser.',

  // ===== CommandPalette =====
  'palette.search': 'Query / pipeline / report',
  'palette.report': 'Read report',
  'palette.graph': 'Full D3 citation graph (standalone tab)',
  'palette.history': 'Recent searches',
  'palette.settings': 'Left drawer',
  'palette.themeCycle': 'parchment → kraft → midnight → sage',
  'palette.auth': 'Sign up or rotate key',
  'palette.changelog': 'release notes',
  'palette.cancel': 'Cancel running query',
  'palette.goSearch': 'Go to Search',
  'palette.goReport': 'Go to Report',
  'palette.goGraph': 'Go to Graph',
  'palette.goHistory': 'Go to History',
  'palette.goSettings': 'Open Settings',
  'palette.themeCycleTitle': 'Cycle theme',
  'palette.authTitle': 'Sign in / Rotate API key',
  'palette.changelogTitle': 'Show changelog',
  'palette.cancelTitle': 'Cancel current search',

  // ===== ChangelogModal / footer =====
  'footer.history': '← → history',
  'footer.shortcuts': '? shortcuts',

  // ===== Common =====
  'common.theme.parchment': 'Parchment',
  'common.theme.kraft': 'Kraft',
  'common.theme.midnight': 'Midnight',
  'common.theme.sage': 'Sage',
  'common.runtime.local': 'Local',
  'common.runtime.llm': 'LLM Search',
  'common.cite': 'cite',
  'common.close': 'Close',
  'common.cancel': 'Cancel',
  'common.error': 'Error',
  'common.signin': 'Sign in',
  'common.signinArrow': 'Sign in →',
  'common.askArrow': 'Ask →',
  'common.recentOpen': 'recent ({n})',
};

const DICTS: Record<Locale, Dict> = { zh: dictZh, en: dictEn };

/**
 * 替换 {n} / {iters} 等占位符.
 */
function format(template: string, params?: Record<string, string | number>): string {
  if (!params) return template;
  return template.replace(/\{(\w+)\}/g, (_, k) =>
    String(params[k] ?? `{${k}}`),
  );
}

/**
 * useT — hook 返回 t(key, params?) 函数.
 * 自动从 store 读 locale 并响应 locale 切换.
 */
export function useT() {
  const locale = useStore((s) => s.locale);
  return (key: string, params?: Record<string, string | number>): string => {
    const v = DICTS[locale][key];
    if (v === undefined) {
      // 缺失 key fallback 到 zh, 再 fallback 到 key 本身
      return DICTS.zh[key] ?? key;
    }
    return format(v, params);
  };
}

/**
 * 切换语言: zh ↔ en. 持久化到 localStorage.
 */
export function toggleLocale(): void {
  const current = getState().locale;
  actions.setLocale(current === 'zh' ? 'en' : 'zh');
}

export const LOCALE_OPTIONS: { id: Locale; label: string }[] = [
  { id: 'zh', label: '中文' },
  { id: 'en', label: 'English' },
];