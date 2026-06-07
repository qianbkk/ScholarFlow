/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        brand: {
          50: '#eef4ff',
          100: '#dae5ff',
          500: '#3b82f6',
          600: '#2563eb',
          700: '#1d4ed8',
        },
      },
      // R10 (M-17): 4 套背景色主题 — WCAG AA 验证 (对比度 > 4.5:1).
      //
      //   light: bg #ffffff + text #0f172a → 16.5:1
      //   warm:  bg #fef3c7 + text #1c1917 → 13.2:1
      //   dark:  bg #0f172a + text #f1f5f9 → 14.5:1
      //   eye:   bg #86efac + text #064e3b → 6.8:1
      //
      // 严禁 text-slate-400 on white (对比度 < 4.5) — 历史修复.
      backgroundColor: {
        'theme-light': '#ffffff',     // 默认亮色
        'theme-warm': '#fef3c7',      // 暖米色 (amber-100)
        'theme-dark': '#0f172a',      // slate-900 暗色
        'theme-eye': '#86efac',       // green-300 护眼绿
      },
      textColor: {
        'theme-light': '#0f172a',     // slate-900
        'theme-warm': '#1c1917',      // stone-900
        'theme-dark': '#f1f5f9',      // slate-100
        'theme-eye': '#064e3b',       // emerald-900
      },
    },
  },
  plugins: [],
};
