import { useState } from "react";

type Theme = "system" | "light" | "dark";

const KEY = "theme";

// localStorage can be unavailable (private windows, blocked storage); fall back to "system".
function readTheme(): Theme {
  try {
    const saved = localStorage.getItem(KEY);
    return saved === "light" || saved === "dark" ? saved : "system";
  } catch {
    return "system";
  }
}

function applyTheme(theme: Theme) {
  // index.css reads data-theme; without it, the OS setting decides
  if (theme === "system") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = theme;
  try {
    if (theme === "system") localStorage.removeItem(KEY);
    else localStorage.setItem(KEY, theme);
  } catch {
    // not saved, but the page still switches
  }
}

const OPTIONS: { value: Theme; label: string }[] = [
  { value: "system", label: "Auto" },
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
];

// The saved choice is applied before React loads (inline script in index.html),
// so the page doesn't flash the wrong theme; this only reflects and changes it.
export default function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(readTheme);

  return (
    <div className="theme-toggle" role="group" aria-label="Colour theme">
      {OPTIONS.map((o) => (
        <button
          key={o.value}
          type="button"
          aria-pressed={theme === o.value}
          onClick={() => {
            setTheme(o.value);
            applyTheme(o.value);
          }}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
