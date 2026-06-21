/**
 * Theme tokens — R10.5.54 前端重构
 *
 * Editorial desk reference 视觉语言:
 * - 4 主题 (parchment / kraft / midnight / sage) 用 OKLCH 表达
 * - 所有 --sf-* CSS 变量在这里集中定义
 * - index.css 只读这些值, 不再硬编码颜色
 *
 * 设计原则:
 * - 不创造侧条纹(side-stripe)边框
 * - 不创造渐变文字
 * - 不创造 01/02/03 编号章节标记
 * - 不创造 tracking-[0.18em] 小大写眉头
 */

export type ThemeId = 'parchment' | 'kraft' | 'midnight' | 'sage';

export interface ThemeSpec {
  id: ThemeId;
  label: string;        // Chinese name (default)
  labelEn: string;      // R10.5.59b: English name (for i18n)
  description: string;
  descriptionEn: string; // R10.5.59b: English description
  // OKLCH 三元组: bg / text / accent
  bg: string;
  text: string;
  muted: string;
  accent: string;
  border: string;
  surface: string;     // elevated surface (cards)
  surfaceAlt: string;   // alternative surface (active states)
}

export const THEMES: Record<ThemeId, ThemeSpec> = {
  parchment: {
    id: 'parchment',
    label: '羊皮纸',
    labelEn: 'Parchment',
    description: '暖白 · 烧橙',
    descriptionEn: 'Warm cream · burnt orange',
    bg:       'oklch(96% 0.02 80)',
    text:     'oklch(22% 0.01 60)',
    muted:    'oklch(48% 0.01 60)',
    accent:   'oklch(55% 0.18 40)',
    border:   'oklch(85% 0.02 70)',
    surface:  'oklch(98% 0.01 80)',
    surfaceAlt: 'oklch(92% 0.02 75)',
  },
  kraft: {
    id: 'kraft',
    label: '牛皮纸',
    labelEn: 'Kraft',
    description: '深米 · 橙红',
    descriptionEn: 'Deep tan · red-orange',
    bg:       'oklch(93% 0.03 75)',
    text:     'oklch(22% 0.015 60)',
    muted:    'oklch(46% 0.02 60)',
    accent:   'oklch(50% 0.17 35)',
    border:   'oklch(82% 0.03 70)',
    surface:  'oklch(95% 0.025 78)',
    surfaceAlt: 'oklch(89% 0.03 72)',
  },
  midnight: {
    id: 'midnight',
    label: '午夜',
    labelEn: 'Midnight',
    description: '深蓝 · 亮橙',
    descriptionEn: 'Deep slate · bright orange',
    bg:       'oklch(18% 0.005 60)',
    text:     'oklch(94% 0.01 80)',
    muted:    'oklch(68% 0.01 60)',
    accent:   'oklch(72% 0.18 50)',
    border:   'oklch(28% 0.01 60)',
    surface:  'oklch(22% 0.008 60)',
    surfaceAlt: 'oklch(26% 0.012 60)',
  },
  sage: {
    id: 'sage',
    label: '鼠尾草',
    labelEn: 'Sage',
    description: '绿灰 · 锈',
    descriptionEn: 'Muted green · rust',
    bg:       'oklch(85% 0.02 100)',
    text:     'oklch(22% 0.015 60)',
    muted:    'oklch(46% 0.02 100)',
    accent:   'oklch(48% 0.16 35)',
    border:   'oklch(74% 0.025 100)',
    surface:  'oklch(88% 0.02 100)',
    surfaceAlt: 'oklch(80% 0.025 100)',
  },
};

/**
 * 把主题应用到 document.documentElement 的 data-theme 属性.
 * index.css 用 [data-theme="xxx"] 选择器消费这些值.
 */
export function applyTheme(theme: ThemeId): void {
  if (typeof document === 'undefined') return;
  // R10.5.55: 删独立 isDark. midnight 主题天然是夜间模式,无需叠加.
  document.documentElement.setAttribute('data-theme', theme);
  document.documentElement.removeAttribute('data-dark');
}

// R10.5.55: 删 themeToCssVars + darken — 旧实现仅用于叠加 isDark.
// 当前设计 4 主题天然包含 light/dark 变体, 不需要运行时叠加.

/**
 * 暗黑变体: 翻转 light -> dark, midnight 保持, sage 暗化.
 * 已弃用, 保留 stub 防 import 错误.
 * @deprecated R10.5.55 删独立 isDark
 */
function darken(spec: ThemeSpec): ThemeSpec {
  if (spec.id === 'midnight') return spec;
  return spec;
}