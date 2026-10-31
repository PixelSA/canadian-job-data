// Display helpers shared by the components.
// API dates are "YYYY-MM-DD"; parse them at noon, because new Date("2026-10-30") is midnight
// UTC, which displays as Oct 29 in Alberta.

export function formatDay(day: string): string {
  return new Date(day + "T12:00").toLocaleDateString("en-CA", {
    month: "short", day: "numeric", year: "numeric",
  });
}

// "2025-07-01" -> "Jul 2025"
export function formatMonth(month: string): string {
  return new Date(month + "T12:00").toLocaleDateString("en-CA", { month: "short", year: "numeric" });
}

// 94575 -> "$94,575"
export function formatMoney(value: number): string {
  return value.toLocaleString("en-CA", { style: "currency", currency: "CAD", maximumFractionDigits: 0 });
}

// Pipeline source ids -> names as the services write them
const SOURCE_NAMES: Record<string, string> = {
  jsearch: "JSearch", jobven: "Jobven", jobbank: "Job Bank", adzuna: "Adzuna",
  jooble: "Jooble", greenhouse: "Greenhouse", lever: "Lever", ashby: "Ashby",
  smartrecruiters: "SmartRecruiters",
};

export function sourceName(source: string): string {
  return SOURCE_NAMES[source] ?? capitalize(source);
}

// "data analyst" -> "Data analyst"
export function capitalize(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}
