// 현행 수치 (/api/now) — /now 페이지·계산기·노트 상세가 함께 쓴다 (Phase 3).
// 예시 숫자는 전부 브라우저에서 계산한다 (서버·외부 호출 없음). 규제 판단이 아니라 '이 숫자가 바뀌면 얼마나 달라지나'를 보여 주는 용도.
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { get } from "./api";

export type Param = {
  key: string; grp: string; label: string; value: number | null; value_text: string; unit: string; scope: string;
  effective_on: string; source_name: string; source_url: string; source_kind: string; note: string; calc: string;
  prev_value: number | null; prev_text: string | null; changed_on: string | null; checked_on: string | null; changed: boolean;
  notes?: { id: number; title: string; published: string }[];
};
export type NowRes = { groups: { name: string; items: Param[] }[]; changed_days: number };

let cache: Promise<NowRes> | null = null;
/** 한 화면 안에서 여러 번 불러도 요청은 한 번 */
export function loadNow(): Promise<NowRes> {
  if (!cache) cache = get<NowRes>("now").catch((e) => { cache = null; throw e; });
  return cache;
}
export function useNow(): { data: NowRes | null; map: Record<string, Param> } {
  const [data, setData] = useState<NowRes | null>(null);
  useEffect(() => { let on = true; loadNow().then((d) => on && setData(d)).catch(() => undefined); return () => { on = false; }; }, []);
  const map: Record<string, Param> = {};
  for (const g of data?.groups || []) for (const p of g.items) map[p.key] = p;
  return { data, map };
}

const num = (v: number) => (Number.isInteger(v) ? v.toLocaleString("ko-KR") : v.toLocaleString("ko-KR", { maximumFractionDigits: 2 }));
export function fmtValue(v: number | null, text: string | null | undefined, unit: string): string {
  if (v === null || v === undefined) return text || "-";
  if (unit === "만원") return man(v);
  return `${num(v)}${unit}`;
}
export function man(v: number): string {
  if (!isFinite(v)) return "-";
  const n = Math.round(v), a = Math.abs(n), eok = Math.floor(a / 10000), rest = a % 10000, sign = n < 0 ? "-" : "";
  if (!eok) return `${sign}${rest.toLocaleString("ko-KR")}만원`;
  return `${sign}${eok}억${rest ? ` ${rest.toLocaleString("ko-KR")}만` : ""}원`;
}
const dateLabel = (d: string) => (d ? d.replace(/-/g, ".") : "");

/** 원리금균등 월 상환액 (만원) */
export function monthlyPay(loan: number, ratePct: number, years = 30): number {
  const r = ratePct / 100 / 12, n = years * 12;
  return r > 0 ? (loan * r) / (1 - Math.pow(1 + r, -n)) : loan / n;
}
/** DSR 한도 안에서 빌릴 수 있는 최대 원금 (원리금균등·만원) */
export function dsrLoan(income: number, dsrPct: number, ratePct: number, years = 30): number {
  const yearly = (income * dsrPct) / 100;
  const perOne = monthlyPay(1, ratePct, years) * 12;
  return perOne > 0 ? yearly / perOne : 0;
}

export type Basis = { price: number; income: number; mine: boolean };
/** 예시 기준 — 내 프로필(예산 상한·연소득)이 있으면 그것, 없으면 8억 집·연소득 7,000만원 */
export function basisOf(p?: { budget_max?: number; income?: number } | null): Basis {
  const price = p?.budget_max && p.budget_max > 0 ? p.budget_max : 80000;
  const income = p?.income && p.income > 0 ? p.income : 7000;
  return { price, income, mine: !!(p?.budget_max || p?.income) };
}

/** 이 항목이 '내 돈'에 주는 영향 한 줄 — 직전 값이 있으면 전→후 */
export function example(p: Param, b: Basis, map: Record<string, Param>): string | null {
  const v = p.value, prev = p.prev_value;
  if (v === null) return null;
  const rate = map.mortgage_rate?.value ?? 4.0;
  const both = (f: (x: number) => number, fmt: (x: number) => string) => (prev !== null && prev !== undefined && prev !== v ? `${fmt(f(prev))} → ${fmt(f(v))}` : fmt(f(v)));
  if (p.key.startsWith("ltv_")) return `${man(b.price)} 집이면 담보로 빌릴 수 있는 한도 ${both((x) => (b.price * x) / 100, man)}`;
  if (p.key === "mortgage_cap_capital") return `한도 계산 결과가 이보다 커도 대출은 ${man(v)}까지`;
  if (p.key === "dsr_bank" || p.key === "dsr_nonbank") return `연소득 ${man(b.income)}·금리 ${rate}%·30년이면 최대 약 ${both((x) => dsrLoan(b.income, x, rate), man)}`;
  if (p.key === "stress_dsr") {
    const base = map.dsr_bank?.value ?? 40;
    return `연소득 ${man(b.income)}이면 DSR 한도가 약 ${man(dsrLoan(b.income, base, rate))} → ${man(dsrLoan(b.income, base, rate + v))}로 줄어요 (금리 ${rate}% + ${v}%p로 계산)`;
  }
  if (p.key === "mortgage_rate") return `3억원을 30년 원리금균등으로 빌리면 월 ${both((x) => monthlyPay(30000, x) * 10000, (w) => `${Math.round(w).toLocaleString("ko-KR")}원`)}`;
  if (p.key === "base_rate" && prev !== null && prev !== undefined && prev !== v) {
    const d = v - prev;
    const diff = (monthlyPay(30000, rate + d) - monthlyPay(30000, rate)) * 10000;
    return `대출 금리가 같은 폭(${d > 0 ? "+" : ""}${d.toFixed(2)}%p)으로 움직이면 3억원 30년 대출 월 상환이 약 ${diff > 0 ? "+" : ""}${Math.round(diff).toLocaleString("ko-KR")}원`;
  }
  if (p.key.startsWith("acq_") && p.unit === "%") return `${man(b.price)}에 이 세율이면 취득세 ${both((x) => (b.price * x) / 100, man)} (지방교육세·농특세 별도)`;
  return null;
}

/** 계산기로 보내는 주소 — 이 항목 값을 계산기 입력에 넣는다 */
export function calcLink(p: Param): string | null {
  if (p.value === null) return null;
  if (p.calc === "ltv") return `/calc?tab=loan&ltv=${p.value}`;
  if (p.calc === "dsr") return `/calc?tab=loan&dsr=${p.value}`;
  if (p.calc === "rate") return `/calc?tab=loan&rate=${p.value}`;
  if (p.calc === "heavy2") return `/calc?tab=tax&heavy2=${p.value}`;
  if (p.calc === "heavy3") return `/calc?tab=tax&heavy3=${p.value}`;
  return null;
}

/** 수치 카드 하나 — /now 와 노트 상세가 같이 쓴다 */
export function ParamCard({ p, basis, map, compact }: { p: Param; basis: Basis; map: Record<string, Param>; compact?: boolean }) {
  const ex = example(p, basis, map);
  const link = calcLink(p);
  const delta = p.source_kind === "auto" && p.prev_value !== null && p.value !== null ? p.value - p.prev_value : null;
  return (
    <div className="now-card">
      <div className="now-top">
        <span className="now-label">{p.label}</span>
        {p.changed && <span className="re-tag warn" title={`${p.changed_on} 변경`}>변경됨</span>}
      </div>
      <div className="now-val">
        {fmtValue(p.value, p.value_text, p.unit)}
        {p.changed && p.prev_value !== null && <small className="now-prev">이전 {fmtValue(p.prev_value, p.prev_text, p.unit)}</small>}
        {delta !== null && Math.abs(delta) > 1e-9 && (
          <small className={`now-prev ${delta > 0 ? "up" : "down"}`}>{p.key === "base_rate" ? "직전" : "전월"} 대비 {delta > 0 ? "+" : ""}{p.unit === "%" ? `${delta.toFixed(2)}%p` : `${Number(delta.toFixed(1)).toLocaleString("ko-KR")}${p.unit || "p"}`}</small>
        )}
      </div>
      {p.scope && <div className="caption">{p.scope}</div>}
      {ex && <div className="now-ex">{ex}</div>}
      {!compact && p.note && <div className="caption">{p.note}</div>}
      <div className="now-src">
        {p.effective_on && <span>기준일 {dateLabel(p.effective_on)}</span>}
        {p.source_url ? <a href={p.source_url} target="_blank" rel="noopener">{p.source_name || "근거"} ↗</a> : <span>{p.source_name}</span>}
        {link && <Link to={link}>계산기에 넣기 →</Link>}
      </div>
      {!compact && !!p.notes?.length && (
        <ul className="now-notes">{p.notes.map((n) => <li key={n.id}><Link to={`/notes?id=${n.id}`}>{n.title}</Link></li>)}</ul>
      )}
    </div>
  );
}
