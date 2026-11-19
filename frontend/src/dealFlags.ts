// 특이 거래 표시 (2026-11-19) — 같은 달 같은 단지·같은 평형(전용면적 반올림)의 중위가에서 ±15% 넘게 벗어난 거래에 참고 표시만 한다.
// 층·향·동·직거래 차이일 수 있어 '이상 거래'라고 단정하지 않는다. 한 묶음에 5건 이상일 때만. 브라우저 계산, AI 없음.
export type Flag = { pct: number; dir: "high" | "low"; median: number };
type R = { apt: string; dong: string; area: number; amount: number; cancelled?: boolean | number | null };

const median = (v: number[]) => { const s = [...v].sort((a, b) => a - b); const m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; };

export function flagDeals<T extends R>(rows: T[], minN = 5, limit = 0.15): Map<T, Flag> {
  const groups = new Map<string, T[]>();
  for (const r of rows) {
    if (r.cancelled || !(r.amount > 0) || !(r.area > 0)) continue;
    const k = `${r.apt}|${r.dong}|${Math.round(r.area)}`;
    (groups.get(k) || groups.set(k, []).get(k)!).push(r);
  }
  const out = new Map<T, Flag>();
  for (const g of groups.values()) {
    if (g.length < minN) continue;
    const m = median(g.map((r) => r.amount));
    for (const r of g) {
      const d = (r.amount - m) / m;
      if (Math.abs(d) >= limit) out.set(r, { pct: Math.round(d * 100), dir: d > 0 ? "high" : "low", median: m });
    }
  }
  return out;
}
