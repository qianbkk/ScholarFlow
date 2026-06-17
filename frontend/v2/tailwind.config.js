/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        display: ['"Source Serif 4"', 'Georgia', 'serif'],
        body: ['"Inter Tight"', 'system-ui', 'sans-serif'],
        sans: ['"Inter Tight"', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'Menlo', 'Consolas', 'monospace'],
      },
      colors: {
        paper: 'var(--paper)',
        ink: 'var(--ink)',
        'ink-2': 'var(--ink-2)',
        rule: 'var(--rule)',
        accent: 'var(--accent)',
        'accent-soft': 'var(--accent-soft)',
        'signal-ok': 'var(--signal-ok)',
        'signal-warn': 'var(--signal-warn)',
        'signal-err': 'var(--signal-err)',
      },
      maxWidth: {
        prose: '68ch',
      },
      transitionTimingFunction: {
        'out-expo': 'cubic-bezier(0.16, 1, 0.3, 1)',
      },
    },
  },
  plugins: [],
};
