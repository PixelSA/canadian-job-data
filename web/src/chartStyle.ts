// Shared Recharts styling. Colours are CSS variables from index.css, so charts follow
// the light/dark theme without re-rendering. Axes and grid stay recessive; the data
// mark carries the colour.

export const SERIES = "var(--series-1)";

export const axisTick = { fill: "var(--text-3)", fontSize: 12 };
export const axisLine = { stroke: "var(--border)" };
export const gridStroke = "var(--grid)";

export const tooltipStyle = {
  contentStyle: {
    background: "var(--surface)",
    border: "1px solid var(--border)",
    borderRadius: 8,
    boxShadow: "var(--shadow)",
    color: "var(--text)",
    fontSize: 13,
  },
  labelStyle: { color: "var(--text)", fontWeight: 600 },
  itemStyle: { color: "var(--text-2)" },
};

// The highlight behind the hovered bar
export const barCursor = { fill: "var(--surface-2)" };
