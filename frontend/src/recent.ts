// 최근 본 것 (2026-11-19) — 본 단지·공고·노트를 이 브라우저(localStorage)에만 최대 8개 남긴다. 서버로 보내지 않는다.
export type Recent = { kind: "apt" | "notice" | "note"; title: string; sub?: string; to: string };
const KEY = "zg-recent";
const ICON = { apt: "🏢", notice: "📋", note: "📰" } as const;
export const recentIcon = (k: Recent["kind"]) => ICON[k];

export function getRecent(): Recent[] {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) || "[]");
    return Array.isArray(v) ? v.filter((x) => x && typeof x.title === "string" && typeof x.to === "string" && x.to.startsWith("/") && !x.to.startsWith("//")).slice(0, 8) : [];
  } catch { return []; }
}

export function recordRecent(r: Recent): void {
  if (!r.title || !r.to.startsWith("/")) return;
  try {
    const rest = getRecent().filter((x) => x.to !== r.to);
    localStorage.setItem(KEY, JSON.stringify([{ ...r, title: r.title.slice(0, 60), sub: (r.sub || "").slice(0, 40) }, ...rest].slice(0, 8)));
  } catch { /* 저장이 막힌 브라우저 — 기록만 못 남긴다 */ }
}

export function clearRecent(): void {
  try { localStorage.removeItem(KEY); } catch { /* 무시 */ }
}
