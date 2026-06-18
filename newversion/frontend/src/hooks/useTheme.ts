// Theme hook — dark by default. Stored in localStorage.
import { useEffect, useState } from 'react';

type Theme = 'dark' | 'light';
const KEY = 'sfv4-theme';

function read(): Theme {
  if (typeof localStorage === 'undefined') return 'dark';
  const v = localStorage.getItem(KEY);
  return v === 'light' ? 'light' : 'dark';
}

export function useTheme(): { theme: Theme; setTheme: (t: Theme) => void } {
  const [theme, setThemeState] = useState<Theme>(read);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  const setTheme = (t: Theme) => {
    setThemeState(t);
    try {
      localStorage.setItem(KEY, t);
    } catch {
      // ignore
    }
  };

  return { theme, setTheme };
}
