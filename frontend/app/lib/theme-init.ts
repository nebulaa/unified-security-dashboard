const STORAGE_KEY = "secdb.theme";

/**
 * Inline script for `<head>` so the correct theme class is applied before paint.
 * Kept in a server-safe module (not `theme.tsx`) for root layout import.
 */
export const themeInitScript = `
(function () {
  try {
    var stored = window.localStorage.getItem(${JSON.stringify(STORAGE_KEY)});
    var theme = stored === 'light' || stored === 'dark' ? stored : 'dark';
    var root = document.documentElement;
    if (theme === 'dark') {
      root.classList.add('dark');
    } else {
      root.classList.remove('dark');
    }
    root.style.colorScheme = theme;
  } catch (_) {
    document.documentElement.classList.add('dark');
    document.documentElement.style.colorScheme = 'dark';
  }
})();
`;
