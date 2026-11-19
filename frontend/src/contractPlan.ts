// 계약 날짜 → 챙길 날짜 계산 (2026-11-19). 브라우저에서만 계산한다 — 서버·LLM 없음.
// 기한은 법령에 정해진 일수(기준 2026-11, 개정될 수 있음). 증여·상속·법인·분양권 같은 예외는 반영하지 않으므로 화면에 간이 안내임을 밝힌다.
export type PlanEvent = { date: string; title: string; memo: string };
export type Kind = "buy" | "lease" | "renew";

const pad = (n: number) => String(n).padStart(2, "0");
const iso = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const parse = (s: string) => { const [y, m, d] = s.split("-").map(Number); return new Date(y, m - 1, d); };
export const valid = (s: string) => /^\d{4}-\d{2}-\d{2}$/.test(s) && iso(parse(s)) === s;
export const addDays = (s: string, n: number) => { const d = parse(s); d.setDate(d.getDate() + n); return iso(d); };
/** 달 더하기 — 말일을 넘으면 그 달 말일로 (8/31 + 6개월 = 2/28) */
export const addMonths = (s: string, n: number) => {
  const d = parse(s), day = d.getDate();
  d.setDate(1); d.setMonth(d.getMonth() + n);
  d.setDate(Math.min(day, new Date(d.getFullYear(), d.getMonth() + 1, 0).getDate()));
  return iso(d);
};

export function planBuy(contract: string, balance: string): PlanEvent[] {
  const out: PlanEvent[] = [];
  if (valid(contract)) out.push({ date: addDays(contract, 30), title: "[매매] 거래 신고 마감", memo: "계약일부터 30일 이내 (부동산 거래신고법). 중개사가 대신 신고하는 경우가 많아요." });
  if (valid(balance)) {
    out.push({ date: balance, title: "[매매] 잔금일", memo: "잔금 지급·열쇠 받는 날" });
    out.push({ date: addDays(balance, 14), title: "[매매] 전입신고 마감", memo: "이사한 날부터 14일 이내 (주민등록법) — 거주할 집일 때" });
    out.push({ date: addDays(balance, 60), title: "[매매] 취득세 신고·납부 마감", memo: "유상 취득일(잔금일과 등기일 중 빠른 날)부터 60일 이내 (지방세법). 증여·상속은 기한이 달라요." });
    out.push({ date: addDays(balance, 60), title: "[매매] 소유권 이전 등기 마감", memo: "잔금일부터 60일 이내 (부동산등기 특별조치법)" });
  }
  return out;
}

export function planLeaseEnd(end: string): PlanEvent[] {
  if (!valid(end)) return [];
  return [
    { date: addMonths(end, -6), title: "[전세 만기] 계약갱신 요구 시작", memo: "만기 6개월 전부터 2개월 전까지 갱신을 요구할 수 있어요 (주택임대차보호법 제6조의3). 세입자는 1회만, 최대 2년." },
    { date: addMonths(end, -2), title: "[전세 만기] 계약갱신 요구 마감", memo: "이날까지 갱신을 요구하지 않으면 요구권을 쓸 수 없어요. 집주인의 갱신 거절 통지도 만기 6개월~2개월 전이에요." },
    { date: addDays(end, -7), title: "[전세 만기] 보증금 반환 확인", memo: "이사 날짜·반환 계좌·새 집 잔금 일정을 한 번 더 확인해요" },
    { date: end, title: "[전세 만기] 계약 만기일", memo: "보증금을 돌려받는 날. 못 받으면 임차권등기명령 같은 절차를 알아봐야 해요." },
  ];
}

export function planLease(movein: string, end: string): PlanEvent[] {
  const out: PlanEvent[] = [];
  if (valid(movein)) {
    out.push({ date: movein, title: "[입주] 전입신고·확정일자 받기", memo: "이사 당일 주민센터(또는 온라인)에서 둘 다 받으면 보증금을 지키는 힘(대항력·우선변제권)이 생겨요" });
    out.push({ date: addDays(movein, 14), title: "[입주] 전입신고 마감", memo: "이사한 날부터 14일 이내 (주민등록법)" });
  }
  const finish = valid(end) ? end : valid(movein) ? addMonths(movein, 24) : "";
  return [...out, ...planLeaseEnd(finish)];
}
