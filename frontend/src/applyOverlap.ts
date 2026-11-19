// 청약 접수 기간 겹침 찾기 (2026-11-19) — 내가 알림·관심으로 담은 공고끼리 접수 기간이 겹치면 알려 준다. 판정은 '날짜가 겹친다'까지만.
// 마감까지 120일 넘는 상시·선착순 공고는 제외(항상 겹치는 것처럼 보이므로). 브라우저 계산, AI 없음.
export type Notice = { notice_id: string; name: string; receipt_start: string | null; receipt_end: string | null };
export type Overlap = { a: Notice; b: Notice; from: string; to: string };

const day = (s: string) => Date.parse(s.slice(0, 10) + "T00:00:00Z");

export function findOverlaps(list: Notice[], maxSpanDays = 120): Overlap[] {
  const ok = list.filter((n) => n.receipt_start && day(n.receipt_start) >= 0 && (!n.receipt_end || (day(n.receipt_end) - day(n.receipt_start)) / 864e5 <= maxSpanDays));
  const out: Overlap[] = [];
  for (let i = 0; i < ok.length; i++) {
    for (let j = i + 1; j < ok.length; j++) {
      const a = ok[i], b = ok[j];
      const aEnd = a.receipt_end || a.receipt_start!, bEnd = b.receipt_end || b.receipt_start!;
      const from = a.receipt_start! > b.receipt_start! ? a.receipt_start! : b.receipt_start!;
      const to = aEnd < bEnd ? aEnd : bEnd;
      if (from.slice(0, 10) <= to.slice(0, 10)) out.push({ a, b, from: from.slice(0, 10), to: to.slice(0, 10) });
    }
  }
  return out.sort((x, y) => x.from.localeCompare(y.from)).slice(0, 5);
}
