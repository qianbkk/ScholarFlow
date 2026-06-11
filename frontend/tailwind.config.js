/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      // R10.5.4 Editorial Knowledge: 4 套字体族
      fontFamily: {
        display: ['Fraunces', 'Newsreader', 'Georgia', 'serif'],
        body: ['Newsreader', 'Fraunces', 'Georgia', 'serif'],
        ui: ['IBM Plex Sans', '-apple-system', 'BlinkMacSystemFont', 'sans-serif'],
        mono: ['JetBrains Mono', 'Menlo', 'Consolas', 'monospace'],
      },
      // 保留 brand 蓝用于少量"链接 / 行动" 元素, 学术工具不激进
      colors: {
        brand: {
          50: '#fff7ed',
          100: '#ffedd5',
          500: '#c2410c',   // burnt orange (跟 parchment 主题 accent 同色)
          600: '#9a3412',   // terracotta (kraft 主题 accent)
          700: '#7c2d12',   // rust (sage 主题 accent)
        },
        ink: {
          DEFAULT: '#1c1917',
          soft: '#44403c',
          muted: '#57534e',
          faded: '#a8a29e',
        },
        paper: {
          DEFAULT: '#faf6ed',
          warm: '#f4ecd8',
          dark: '#0d0d0d',
          sage: '#e8e4d4',
          elev: '#f3ecdb',
        },
      },
      // 4 套背景色主题 (用 CSS 变量, 跟 index.css 联动)
      backgroundColor: {
        'theme-parchment': '#faf6ed',
        'theme-kraft': '#f4ecd8',
        'theme-midnight': '#0d0d0d',
        'theme-sage': '#e8e4d4',
      },
      textColor: {
        'theme-parchment': '#1c1917',
        'theme-kraft': '#1c1917',
        'theme-midnight': '#f5efe4',
        'theme-sage': '#1c1917',
      },
      // 报头阴影 — 学术期刊浮层
      boxShadow: {
        'editorial': '0 1px 2px rgba(28, 25, 23, 0.04), 0 4px 12px rgba(28, 25, 23, 0.06)',
        'editorial-lg': '0 2px 4px rgba(28, 25, 23, 0.05), 0 12px 32px rgba(28, 25, 23, 0.10)',
      },
    },
  },
  plugins: [],
};
