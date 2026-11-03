// 청약 접수 상태 배지 (2026-11-03) — 예전에는 접수 시작일만 보고 날짜를 세서, 접수 중인 공고도 '지남'으로 보였다 (내 공간·관심 단지).
const DAY = 86400000;
const daysFrom = (s: string) => Math.ceil((new Date(s.slice(0, 10) + "T00:00:00").getTime() - new Date(new Date().toDateString()).getTime()) / DAY);

/** 접수 시작 전이면 D-n, 접수 중이면 '접수 중 · 마감 D-n'(마감일이면 '오늘 마감'), 마감이 지나야 '지남'. 날짜가 없으면 null. */
export function applyBadge(start: string | null | undefined, end: string | null | undefined): { label: string; hot: boolean; past: boolean } | null {
  const s = start ? daysFrom(start) : null;
  const e = end ? daysFrom(end) : null;
  if (s === null && e === null) return null;
  if (s !== null && s > 0) return { label: `D-${s}`, hot: s <= 3, past: false };
  if (e !== null && e < 0) return { label: "지남", hot: false, past: true };
  if (e === null) return s === 0 ? { label: "오늘 접수", hot: true, past: false } : { label: "지남", hot: false, past: true };
  if (e === 0) return { label: "오늘 마감", hot: true, past: false };
  return { label: `접수 중 · 마감 D-${e}`, hot: e <= 3, past: false };
}
