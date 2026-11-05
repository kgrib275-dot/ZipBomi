// 내 집 계산기 (/calc) — 대출 한도·월 상환액, 취득세 간이 계산, 청약 가점, 전세가율·갭.
// 전부 브라우저에서 계산한다 (서버·LLM·외부 호출 없음). 입력값은 방문자 상태 calc_inputs(같은 쿠키면 다른 기기에서도)와
// localStorage 에 함께 저장 — 서버 저장이 실패해도 이 브라우저에서는 이어서 쓸 수 있게.
// 세율·규제 비율은 법령·정책으로 자주 바뀌므로 '고급'에서 고칠 수 있게 두고, 화면에 간이 계산임을 밝힌다.
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Tabs } from "../components/ui";
import { useMe } from "../me";
import { Profile, profileOf } from "../profile";
import { useNow } from "../policy";
import "./RealEstate.css";

const TABS = ["대출 한도", "취득세", "청약 가점", "전세가율·갭"];
const LS_TAB = "zipgenie-calc-tab";
const LS_IN = "zipgenie-calc-inputs";

type Loan = { price: number; income: number; debt: number; rate: number; years: number; method: "eq" | "pr"; ltv: number; dsr: number; want: number; cash: number };
type Tax = { price: number; houses: number; adjusted: boolean; big: boolean; temp2: boolean; heavy2: number; heavy3: number; eduRatio: number; eduHeavy: number; agStd: number; ag8: number; ag12: number };
type Sub = { home: number; fam: number; acct: number };
type Gap = { price: number; jeonse: number; houses: number; adjusted: boolean; big: boolean };
type Inputs = { loan: Loan; tax: Tax; sub: Sub; gap: Gap };

// 기본값 — 2026년 흔한 예시일 뿐 규제 확정값이 아니다 (화면에서 고칠 수 있다)
const DEFAULTS: Inputs = {
  loan: { price: 80000, income: 7000, debt: 0, rate: 4.0, years: 30, method: "eq", ltv: 70, dsr: 40, want: 0, cash: 0 },
  tax: { price: 80000, houses: 1, adjusted: false, big: false, temp2: false, heavy2: 8, heavy3: 12, eduRatio: 10, eduHeavy: 0.4, agStd: 0.2, ag8: 0.6, ag12: 1.0 },
  sub: { home: 6, fam: 2, acct: 7 },
  gap: { price: 60000, jeonse: 45000, houses: 1, adjusted: false, big: false },
};

// ---------- 표기 ----------

/** 만원 → '12억 3,400만원' */
function man(v: number): string {
  if (!isFinite(v)) return "-";
  const n = Math.round(v);
  const a = Math.abs(n), eok = Math.floor(a / 10000), rest = a % 10000, sign = n < 0 ? "-" : "";
  if (!eok) return `${sign}${rest.toLocaleString("ko-KR")}만원`;
  return `${sign}${eok}억${rest ? ` ${rest.toLocaleString("ko-KR")}만` : ""}원`;
}
/** 만원 → '2,673,525원' (월 상환액처럼 원 단위가 익숙한 값) */
const won = (v: number) => (isFinite(v) ? `${Math.round(v * 10000).toLocaleString("ko-KR")}원` : "-");
const pct = (v: number, d = 1) => (isFinite(v) ? `${v.toFixed(d)}%` : "-");

// ---------- 계산 (순수 함수) ----------

/** 대출 한도·상환. 금액은 모두 만원.
 * - LTV 한도 = 주택가격 × LTV
 * - DSR 한도: (연소득 × DSR − 기존 부채 연 원리금) 안에서 갚을 수 있는 최대 원금.
 *   원리금균등은 월 상환액 = L·r/(1−(1+r)^−n) 로, 원금균등은 상환액이 가장 큰 첫해 기준(보수적)으로 역산한다.
 *   스트레스 DSR(가산 금리)·만기 제한 같은 세부 규정은 넣지 않았다. */
function calcLoan(p: Loan) {
  const r = p.rate / 100 / 12;
  const n = Math.max(1, Math.round(p.years * 12));
  const ltvMax = Math.max(0, (p.price * p.ltv) / 100);
  const allowance = (p.income * p.dsr) / 100 - p.debt;
  const factor = r > 0 ? r / (1 - Math.pow(1 + r, -n)) : 1 / n; // 원금 1당 월 상환액(원리금균등)
  const k = Math.min(12, n);
  // 원금 1당 첫해 상환액 — 원금균등: 원금 k/n + 이자 r·Σ(1 − j/n) (j=0..k−1) = r·(k − k(k−1)/2n)
  const firstYearPer1 = p.method === "eq" ? k * factor : k / n + r * (k - (k * (k - 1)) / 2 / n);
  const dsrMax = allowance > 0 ? allowance / firstYearPer1 : 0;
  const maxLoan = Math.max(0, Math.min(ltvMax, dsrMax));
  const loan = p.want > 0 ? p.want : maxLoan;
  // 첫 12개월 상환표
  const rows: { m: number; pay: number; principal: number; interest: number; left: number }[] = [];
  let left = loan;
  const eqPay = loan * factor;
  for (let m = 1; m <= Math.min(12, n); m++) {
    const interest = left * r;
    const principal = p.method === "eq" ? eqPay - interest : loan / n;
    left = Math.max(0, left - principal);
    rows.push({ m, pay: principal + interest, principal, interest, left });
  }
  const totalInterest = p.method === "eq" ? eqPay * n - loan : (loan * r * (n + 1)) / 2;
  const firstYear = rows.reduce((s, x) => s + x.pay, 0);
  const dsrUsed = p.income > 0 ? ((firstYear + p.debt) / p.income) * 100 : NaN;
  return { ltvMax, dsrMax, maxLoan, loan, rows, totalInterest, firstYear, dsrUsed, binding: ltvMax <= dsrMax ? "LTV" : "DSR", ownCash: p.price - loan };
}

/** 주택 유상취득 취득세 간이 계산 (지방세법 제11조·제13조의2 표준·중과 구조를 따른 예시).
 * - 표준: 6억 이하 1%, 6~9억 (가액[억] × 2/3 − 3)%, 9억 초과 3%
 * - 중과: 조정대상지역 2주택(일시적 2주택 제외)·비조정 3주택 8%, 조정 3주택·4주택 이상 12% (고급에서 수정)
 * - 지방교육세: 표준이면 취득세율의 10%(=세율×½×20%), 중과면 0.4%
 * - 농어촌특별세: 전용 85㎡ 이하 비과세, 초과면 표준 0.2% / 8% 0.6% / 12% 1.0% */
function calcTax(price: number, houses: number, adjusted: boolean, big: boolean, temp2: boolean, t: Tax) {
  let rate: number;
  let heavy = 0;
  if (houses >= 4 || (houses === 3 && adjusted)) heavy = t.heavy3;
  else if (houses === 3 || (houses === 2 && adjusted && !temp2)) heavy = t.heavy2;
  if (heavy) rate = heavy;
  else if (price <= 60000) rate = 1;
  else if (price <= 90000) rate = Math.round(((price / 10000) * (2 / 3) - 3) * 100) / 100; // 소수점 둘째 자리(%)까지
  else rate = 3;
  const eduRate = heavy ? t.eduHeavy : (rate * t.eduRatio) / 100;
  const agRate = !big ? 0 : heavy ? (heavy >= t.heavy3 ? t.ag12 : t.ag8) : t.agStd;
  const tax = (price * rate) / 100, edu = (price * eduRate) / 100, ag = (price * agRate) / 100;
  return { rate, eduRate, agRate, tax, edu, ag, total: tax + edu + ag, totalRate: rate + eduRate + agRate, heavy: !!heavy };
}

/** 가능 여부 — 모아둔 돈 + 대출(한도 또는 정한 금액)로 집값 + 취득세(1주택 표준)를 낼 수 있는가.
 * 살 수 있는 최고 집값은 이분 탐색 (LTV·DSR·취득세가 모두 집값에 따라 바뀌므로). */
function verdict(p: Loan, t: Tax) {
  const r = calcLoan(p);
  const loan = p.want > 0 ? Math.min(p.want, r.maxLoan) : r.maxLoan;
  const tax = calcTax(p.price, 1, false, false, false, t).total;
  const need = p.price + tax;
  const have = p.cash + loan;
  let lo = 0, hi = 2_000_000;
  for (let i = 0; i < 40; i++) {
    const mid = (lo + hi) / 2;
    const l = calcLoan({ ...p, price: mid, want: 0 }).maxLoan;
    if (p.cash + l >= mid + calcTax(mid, 1, false, false, false, t).total) lo = mid; else hi = mid;
  }
  return { ok: have >= need, need, have, loan, tax, gap: have - need, maxPrice: Math.floor(lo / 100) * 100, binding: r.binding, overLimit: p.want > r.maxLoan };
}

// 청약 가점표 (주택공급에 관한 규칙 별표 1) — 선택지 순서가 곧 점수 구간
const HOME_OPTS = ["해당 없음 (유주택·만30세 미만 미혼)", "1년 미만", ...Array.from({ length: 14 }, (_, i) => `${i + 1}년 이상 ~ ${i + 2}년 미만`), "15년 이상"];
const HOME_SCORE = (i: number) => (i === 0 ? 0 : 2 * i); // 0 / 1년 미만 2점 / 이후 1년마다 +2, 15년 이상 32점
const FAM_OPTS = ["0명", "1명", "2명", "3명", "4명", "5명", "6명 이상"];
const FAM_SCORE = (i: number) => 5 + 5 * i; // 0명 5점 … 6명 이상 35점
const ACCT_OPTS = ["6개월 미만", "6개월 ~ 1년 미만", ...Array.from({ length: 14 }, (_, i) => `${i + 1}년 이상 ~ ${i + 2}년 미만`), "15년 이상"];
const ACCT_SCORE = (i: number) => i + 1; // 6개월 미만 1점 … 15년 이상 17점

// ---------- 내 프로필 → 빈 계산기 채우기 ----------

/** 프로필에 쓸 값이 있으면 채운 입력을 돌려준다 (base 없이 부르면 쓸 값이 있는지만 확인). */
function fromProfile(p: Profile, base: Inputs = DEFAULTS): Inputs | null {
  const loan = { ...base.loan }, sub = { ...base.sub };
  let any = false;
  if (typeof p.income === "number") { loan.income = p.income; any = true; }
  if (typeof p.debt === "number") { loan.debt = p.debt; any = true; }
  if (typeof p.sub_home === "number") { sub.home = p.sub_home; any = true; }
  if (typeof p.sub_fam === "number") { sub.fam = p.sub_fam; any = true; }
  if (typeof p.sub_acct === "number") { sub.acct = p.sub_acct; any = true; }
  return any ? { ...base, loan, sub } : null;
}

// ---------- 저장 ----------

function merge(base: Inputs, v: unknown): Inputs {
  if (!v || typeof v !== "object") return base;
  const o = v as Record<string, unknown>;
  const pick = <T extends object>(b: T, x: unknown): T => {
    if (!x || typeof x !== "object") return b;
    const out = { ...b } as Record<string, unknown>;
    for (const k of Object.keys(b)) {
      const val = (x as Record<string, unknown>)[k];
      if (typeof val === typeof (b as Record<string, unknown>)[k] && (typeof val !== "number" || isFinite(val))) out[k] = val;
    }
    return out as T;
  };
  return { loan: pick(base.loan, o.loan), tax: pick(base.tax, o.tax), sub: pick(base.sub, o.sub), gap: pick(base.gap, o.gap) };
}

function lsGet(k: string): string | null {
  try { return localStorage.getItem(k); } catch { return null; }
}
function lsSet(k: string, v: string) {
  try { localStorage.setItem(k, v); } catch { /* 저장소가 막혀 있으면 기억만 못 한다 */ }
}

export default function Calc() {
  const { me, state, setState } = useMe();
  const [tab, setTab] = useState(() => (TABS.includes(lsGet(LS_TAB) || "") ? (lsGet(LS_TAB) as string) : TABS[0]));
  const [inp, setInp] = useState<Inputs>(() => {
    try { return merge(DEFAULTS, JSON.parse(lsGet(LS_IN) || "null")); } catch { return DEFAULTS; }
  });
  const touched = useRef(false);
  const hydrated = useRef(false);
  const [prefilled, setPrefilled] = useState(false);
  const [fromLink, setFromLink] = useState("");
  const nav = useNavigate();

  // 다른 화면에서 넘어온 값 (/calc?price=…&jeonse=…&tab=loan · 현행 수치의 '계산기에 넣기') — 한 번 넣고 주소는 /calc 로 되돌린다
  useEffect(() => {
    const q = new URLSearchParams(window.location.search);
    if (![...q.keys()].length) return;
    const n = (k: string, max: number) => { const v = Number(q.get(k)); return q.has(k) && isFinite(v) && v > 0 ? Math.min(max, v) : null; };
    const price = n("price", 99_999_999), jeonse = n("jeonse", 99_999_999);
    const ltv = n("ltv", 100), dsr = n("dsr", 100), rate = n("rate", 20), h2 = n("heavy2", 20), h3 = n("heavy3", 20);
    const tabKey = q.get("tab");
    const t = tabKey === "tax" ? TABS[1] : tabKey === "sub" ? TABS[2] : tabKey === "gap" || jeonse ? TABS[3] : tabKey === "loan" || price || ltv || dsr || rate ? TABS[0] : null;
    if (price || jeonse || ltv || dsr || rate || h2 || h3) {
      touched.current = true;
      setInp((cur) => ({
        ...cur,
        loan: { ...cur.loan, ...(price ? { price, want: 0 } : {}), ...(ltv ? { ltv } : {}), ...(dsr ? { dsr } : {}), ...(rate ? { rate } : {}) },
        tax: { ...cur.tax, ...(price ? { price } : {}), ...(h2 ? { heavy2: h2 } : {}), ...(h3 ? { heavy3: h3 } : {}) },
        gap: { ...cur.gap, ...(price ? { price } : {}), ...(jeonse ? { jeonse } : {}) },
      }));
      const what = q.get("label");
      setFromLink(price ? `${what ? `${what.slice(0, 60)} ` : ""}${man(price)}${jeonse ? ` · 전세 ${man(jeonse)}` : ""}을 넣었어요.` : "현행 수치를 넣었어요.");
    }
    if (t) { setTab(t); lsSet(LS_TAB, t); }
    nav("/calc", { replace: true });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // 서버에 저장된 값(다른 기기에서 입력한 값)이 오면 한 번 반영 — 이 브라우저 값보다 새것일 때만(at 비교),
  // 이미 고치기 시작했으면 덮어쓰지 않는다 (서버 저장은 0.8초 늦게 가므로 무조건 덮으면 방금 입력이 되돌아간다)
  useEffect(() => {
    if (!me || hydrated.current) return;
    hydrated.current = true;
    const srv = state.calc_inputs as { at?: number } | undefined;
    const localAt = Number(lsGet(LS_IN + "-at")) || 0;
    if (!touched.current && srv && typeof srv === "object" && (Number(srv.at) || 0) > localAt) setInp((cur) => merge(cur, srv));
    // 계산기를 처음 쓰는 방문자(저장된 입력 없음)는 내 프로필의 연소득·부채·청약 항목으로 빈 칸을 채운다
    else if (!touched.current && !srv && !lsGet(LS_IN)) {
      const p = profileOf(state);
      if (p && fromProfile(p)) { setInp((cur) => fromProfile(p, cur)!); setPrefilled(true); }
    }
  }, [me, state.calc_inputs]); // eslint-disable-line react-hooks/exhaustive-deps

  // 고친 뒤에만 저장 (그냥 둘러본 방문은 서버에 빈 기록을 남기지 않게), 서버 저장은 0.8초 모아서
  useEffect(() => {
    if (!touched.current) return;
    const at = Date.now();
    lsSet(LS_IN, JSON.stringify(inp));
    lsSet(LS_IN + "-at", String(at));
    const t = window.setTimeout(() => setState({ calc_inputs: { ...inp, at } }), 800);
    return () => window.clearTimeout(t);
  }, [inp, setState]);

  const pickTab = (t: string) => { setTab(t); lsSet(LS_TAB, t); };
  function up<K extends keyof Inputs>(k: K, patch: Partial<Inputs[K]>) {
    touched.current = true;
    setInp((cur) => ({ ...cur, [k]: { ...cur[k], ...patch } }));
  }
  const reset = () => { touched.current = true; setInp(DEFAULTS); };

  return (
    <div className="re-page">
      <div>
        <div className="eyebrow">내 집 계산기</div>
        <h2 className="sec-h">숫자로 보는 <span className="grad">집 계산</span></h2>
        <p className="sec-p">대출 한도·취득세·청약 가점·전세가율을 바로 계산합니다. 입력값은 나만 볼 수 있게 저장돼요. <Link className="re-link" to="/deals">실거래가 보기 →</Link></p>
        {fromLink && <p className="caption" style={{ margin: "6px 0 0" }}>{fromLink} 대출 한도·취득세·전세가율 탭에 같은 가격이 들어가 있어요.</p>}
        {prefilled && <p className="caption" style={{ margin: "6px 0 0" }}>연소득·부채·청약 항목을 <Link to="/me">내 프로필</Link> 값으로 채웠어요. 여기서 고쳐도 프로필은 바뀌지 않아요.</p>}
      </div>
      <Tabs items={TABS} value={tab} onChange={pickTab} />
      {tab === TABS[0] && <LoanTab v={inp.loan} tax={inp.tax} on={(p) => up("loan", p)} />}
      {tab === TABS[1] && <TaxTab v={inp.tax} on={(p) => up("tax", p)} />}
      {tab === TABS[2] && <SubTab v={inp.sub} on={(p) => up("sub", p)} />}
      {tab === TABS[3] && <GapTab v={inp.gap} tax={inp.tax} on={(p) => up("gap", p)} />}
      <div className="btn-row"><button type="button" className="btn sm ghost" onClick={reset}>입력값 처음으로</button></div>
    </div>
  );
}

// ---------- 입력 조각 ----------

/** 만원 단위 금액 입력 — 쉼표로 보여 주고, 아래에 '5억 3,000만원'처럼 읽어 준다 */
function Money({ id, label, value, onChange, hint }: { id: string; label: string; value: number; onChange: (v: number) => void; hint?: string }) {
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <div className="calc-unit">
        <input id={id} type="text" inputMode="numeric" value={value ? value.toLocaleString("ko-KR") : ""} placeholder="0"
          onChange={(e) => onChange(Math.min(99_999_999, Number(e.target.value.replace(/[^\d]/g, "")) || 0))} />
        <span>만원</span>
      </div>
      <div className="calc-hint">{value ? man(value) : ""}{hint ? ` ${hint}` : ""}</div>
    </div>
  );
}

function Num({ id, label, value, onChange, unit, step = 0.1, min = 0, max = 100 }: { id: string; label: string; value: number; onChange: (v: number) => void; unit: string; step?: number; min?: number; max?: number }) {
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <div className="calc-unit">
        <input id={id} type="number" inputMode="decimal" step={step} min={min} max={max} value={Number.isFinite(value) ? value : ""}
          onChange={(e) => { const n = Number(e.target.value); onChange(Number.isFinite(n) ? Math.min(max, Math.max(min, n)) : 0); }} />
        <span>{unit}</span>
      </div>
    </div>
  );
}

function Seg<T extends string | number>({ label, value, items, onChange }: { label: string; value: T; items: [T, string][]; onChange: (v: T) => void }) {
  return (
    <div className="field">
      <label>{label}</label>
      <div className="calc-seg" role="radiogroup" aria-label={label}>
        {items.map(([k, t]) => <button key={String(k)} type="button" role="radio" aria-checked={value === k} className={`pill ${value === k ? "on" : ""}`} onClick={() => onChange(k)}>{t}</button>)}
      </div>
    </div>
  );
}

function KV({ k, v, total }: { k: string; v: string; total?: boolean }) {
  return <div className={`calc-kv ${total ? "total" : ""}`}><span>{k}</span><b>{v}</b></div>;
}

// ---------- 탭 ----------

function LoanTab({ v, tax, on }: { v: Loan; tax: Tax; on: (p: Partial<Loan>) => void }) {
  const r = useMemo(() => calcLoan(v), [v]);
  const vd = useMemo(() => verdict(v, tax), [v, tax]);
  const { map } = useNow();
  const nowDsr = map.dsr_bank?.value, nowRate = map.mortgage_rate?.value, nowStress = map.stress_dsr?.value;
  // 금리 기본값은 현행 수치의 평균 주담대 금리로 (2026-11-03) — 예전 기본 4.0% 라 같은 예시가 홈·현행 수치(4.88%)와 다른 한도로 나왔다.
  // 처음 기본값(4.0) 그대로일 때 한 번만 바꾼다 — 직접 고친 금리는 건드리지 않는다.
  const rateSynced = useRef(false);
  useEffect(() => {
    if (rateSynced.current || nowRate === undefined || nowRate === null) return;
    rateSynced.current = true;
    if (v.rate === DEFAULTS.loan.rate && nowRate !== v.rate) on({ rate: nowRate });
  }, [nowRate]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="calc-grid">
      <div className="re-box calc-in">
        <Money id="l-price" label="주택 가격" value={v.price} onChange={(x) => on({ price: x })} />
        <Money id="l-income" label="연소득 (세전)" value={v.income} onChange={(x) => on({ income: x })} />
        <Money id="l-debt" label="기존 부채 연 원리금" value={v.debt} onChange={(x) => on({ debt: x })} hint="(신용대출·자동차 할부 등 1년 상환액)" />
        <div className="row2">
          <Num id="l-rate" label="금리" value={v.rate} onChange={(x) => on({ rate: x })} unit="%" step={0.05} max={20} />
          <Num id="l-years" label="기간" value={v.years} onChange={(x) => on({ years: Math.max(1, Math.round(x)) })} unit="년" step={1} min={1} max={50} />
        </div>
        <Seg label="상환 방식" value={v.method} items={[["eq", "원리금균등"], ["pr", "원금균등"]]} onChange={(x) => on({ method: x })} />
        <div className="row2">
          <Num id="l-ltv" label="LTV" value={v.ltv} onChange={(x) => on({ ltv: x })} unit="%" step={5} />
          <Num id="l-dsr" label="DSR" value={v.dsr} onChange={(x) => on({ dsr: x })} unit="%" step={5} />
        </div>
        <Money id="l-want" label="실제 빌릴 금액 (비우면 최대)" value={v.want} onChange={(x) => on({ want: x })} />
        <Money id="l-cash" label="모아둔 돈 (집 사는 데 쓸 수 있는 현금)" value={v.cash} onChange={(x) => on({ cash: x })} hint="— 넣으면 살 수 있는지 한 줄로 알려 드려요" />
        {(nowDsr || nowRate) && (
          <div className="calc-now">
            <span>현행 수치:</span>
            {nowDsr !== undefined && nowDsr !== null && nowDsr !== v.dsr && <button type="button" className="pill" onClick={() => on({ dsr: nowDsr })}>은행권 DSR {nowDsr}% 쓰기</button>}
            {nowRate !== undefined && nowRate !== null && nowRate !== v.rate && <button type="button" className="pill" onClick={() => on({ rate: nowRate })}>평균 주담대 금리 {nowRate}% 쓰기 <small>({map.mortgage_rate?.effective_on})</small></button>}
            {nowStress !== undefined && nowStress !== null && <span>스트레스 DSR 가산 {nowStress}%p는 DSR 한도 계산에만 붙어요 — 금리 칸에 더해 보면 더 보수적이에요.</span>}
            <Link to="/now">전체 보기 →</Link>
          </div>
        )}
        <p className="calc-note">실제 규제 비율은 지역·주택 수·생애최초 여부·정책에 따라 다르고 스트레스 DSR 가산 금리도 붙을 수 있으니 은행에서 꼭 확인하세요.</p>
      </div>
      <div className="re-box calc-res">
        <SaveCalc label={`대출 한도 · ${man(v.price)}`} summary={`최대 대출 ${man(r.maxLoan)} (${r.binding} 기준)${v.cash ? ` · ${vd.ok ? "살 수 있음" : `${man(-vd.gap)} 부족`}` : ""}`}
          params={{ tab: "loan", price: v.price, income: v.income, rate: v.rate, ltv: v.ltv, dsr: v.dsr, cash: v.cash }} />
        <Verdict v={v} d={vd} />
        <div className="caption">최대 대출 (LTV·DSR 중 작은 쪽, {r.binding} 기준)</div>
        <div className="calc-big">{man(r.maxLoan)}</div>
        <div>
          <KV k={`LTV 한도 (${v.ltv}%)`} v={man(r.ltvMax)} />
          <KV k={`DSR 한도 (${v.dsr}%)`} v={man(r.dsrMax)} />
          <KV k="계산에 쓴 대출액" v={man(r.loan)} />
          <KV k="필요한 내 돈 (주택가격 − 대출)" v={man(r.ownCash)} />
          <KV k={v.method === "eq" ? "월 상환액" : "첫 달 상환액"} v={won(r.rows[0]?.pay ?? 0)} total />
          <KV k="첫해 상환 합계" v={man(r.firstYear)} />
          <KV k="이 대출의 DSR" v={pct(r.dsrUsed)} />
          <KV k={`총 이자 (${v.years}년)`} v={man(r.totalInterest)} />
        </div>
        {v.want > 0 && r.dsrUsed > v.dsr && <div className="alert warn">이 금액은 DSR {v.dsr}%를 넘습니다 ({pct(r.dsrUsed)}).</div>}
        {v.want > 0 && v.want > r.ltvMax && <div className="alert warn">이 금액은 LTV 한도를 넘습니다.</div>}
        <details className="expander">
          <summary>첫해 월별 상환표</summary>
          <div className="body table-wrap">
            <table className="table re-table">
              <thead><tr><th>회차</th><th className="num">상환액</th><th className="num">원금</th><th className="num">이자</th><th className="num">남은 원금</th></tr></thead>
              <tbody>
                {r.rows.map((x) => (
                  <tr key={x.m}><td>{x.m}</td><td className="num">{won(x.pay)}</td><td className="num">{won(x.principal)}</td><td className="num">{won(x.interest)}</td><td className="num">{man(x.left)}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
        {v.method === "pr" && <p className="calc-note">원금균등은 상환액이 가장 큰 첫해 기준으로 DSR 한도를 계산했습니다(보수적).</p>}
      </div>
    </div>
  );
}

/** 지금 계산을 내 공간(calc_saves)에 저장 — 주소 매개변수로 다시 열 수 있게 */
function SaveCalc({ label, summary, params }: { label: string; summary: string; params: Record<string, number | string | undefined> }) {
  const { state, setState } = useMe();
  const [done, setDone] = useState(false);
  const save = () => {
    const q = new URLSearchParams(Object.entries(params).filter(([, x]) => x !== undefined && x !== 0 && x !== "").map(([k, x]) => [k, String(x)]));
    const list = Array.isArray(state.calc_saves) ? (state.calc_saves as unknown[]) : [];
    setState({ calc_saves: [{ label, summary, url: `/calc?${q}`, at: new Date().toISOString().slice(0, 16) }, ...list].slice(0, 30) });
    setDone(true); window.setTimeout(() => setDone(false), 2500);
  };
  return <button type="button" className="btn sm ghost calc-save" onClick={save}>{done ? "✓ 내 공간에 저장했어요" : "☆ 이 계산 저장"}</button>;
}

function Verdict({ v, d }: { v: Loan; d: ReturnType<typeof verdict> }) {
  if (!v.price) return null;
  if (!v.cash) return <div className="calc-verdict">모아둔 돈을 넣으면 이 집을 살 수 있는지 한 줄로 알려 드려요.<small>이 조건에서 대출만으로는 집값의 {pct((d.loan / v.price) * 100, 0)}까지 마련돼요.</small></div>;
  return d.ok ? (
    <div className="calc-verdict ok" role="status">
      살 수 있어요 — 대출 {man(d.loan)} + 내 돈 {man(v.cash)}으로 집값과 취득세(약 {man(d.tax)})를 내고 {man(d.gap)}이 남아요.
      <small>이 조건으로 살 수 있는 집값은 약 {man(d.maxPrice)}까지예요 (1주택 표준세율·{d.binding} 한도 기준).</small>
    </div>
  ) : (
    <div className="calc-verdict no" role="status">
      {man(-d.gap)} 부족해요 — 대출 {man(d.loan)} + 내 돈 {man(v.cash)} &lt; 집값 + 취득세 {man(d.need)}.
      <small>{d.overLimit ? "정한 대출액이 한도를 넘어 한도까지만 셌어요. " : ""}이 조건으로는 약 {man(d.maxPrice)}까지의 집이 가능해요 ({d.binding} 한도 기준).</small>
    </div>
  );
}

function TaxTab({ v, on }: { v: Tax; on: (p: Partial<Tax>) => void }) {
  const r = useMemo(() => calcTax(v.price, v.houses, v.adjusted, v.big, v.temp2, v), [v]);
  return (
    <div className="calc-grid">
      <div className="re-box calc-in">
        <Money id="t-price" label="취득가액" value={v.price} onChange={(x) => on({ price: x })} />
        <Seg label="취득 후 주택 수" value={v.houses} items={[[1, "1주택"], [2, "2주택"], [3, "3주택"], [4, "4주택 이상"]]} onChange={(x) => on({ houses: x })} />
        <label className="check"><input type="checkbox" checked={v.adjusted} onChange={(e) => on({ adjusted: e.target.checked })} /> 조정대상지역의 주택</label>
        <label className="check"><input type="checkbox" checked={v.big} onChange={(e) => on({ big: e.target.checked })} /> 전용 85㎡ 초과 (농어촌특별세 과세)</label>
        {v.houses === 2 && <label className="check"><input type="checkbox" checked={v.temp2} onChange={(e) => on({ temp2: e.target.checked })} /> 일시적 2주택 (기존 집을 기한 안에 처분)</label>}
        <details className="expander" style={{ marginTop: 12 }}>
          <summary>고급 — 세율 고치기</summary>
          <div className="body">
            <div className="row2">
              <Num id="t-h2" label="중과 세율 (조정 2주택·비조정 3주택)" value={v.heavy2} onChange={(x) => on({ heavy2: x })} unit="%" step={0.5} max={20} />
              <Num id="t-h3" label="중과 세율 (조정 3주택·4주택 이상)" value={v.heavy3} onChange={(x) => on({ heavy3: x })} unit="%" step={0.5} max={20} />
              <Num id="t-er" label="지방교육세 (표준: 취득세율의)" value={v.eduRatio} onChange={(x) => on({ eduRatio: x })} unit="%" step={1} />
              <Num id="t-eh" label="지방교육세 (중과)" value={v.eduHeavy} onChange={(x) => on({ eduHeavy: x })} unit="%" step={0.1} max={5} />
              <Num id="t-as" label="농특세 (표준·85㎡ 초과)" value={v.agStd} onChange={(x) => on({ agStd: x })} unit="%" step={0.1} max={5} />
              <Num id="t-a8" label="농특세 (8% 중과)" value={v.ag8} onChange={(x) => on({ ag8: x })} unit="%" step={0.1} max={5} />
              <Num id="t-a12" label="농특세 (12% 중과)" value={v.ag12} onChange={(x) => on({ ag12: x })} unit="%" step={0.1} max={5} />
            </div>
          </div>
        </details>
      </div>
      <div className="re-box calc-res">
        <div className="caption">예상 세금 합계 (실효 {pct(r.totalRate, 2)})</div>
        <div className="calc-big">{man(r.total)}</div>
        <div>
          <KV k={`취득세 (${pct(r.rate, 2)}${r.heavy ? " · 중과" : ""})`} v={won(r.tax)} />
          <KV k={`지방교육세 (${pct(r.eduRate, 2)})`} v={won(r.edu)} />
          <KV k={`농어촌특별세 (${pct(r.agRate, 2)})`} v={won(r.ag)} />
          <KV k="합계" v={won(r.total)} total />
        </div>
        <div className="alert warn">법령 개정으로 바뀔 수 있는 간이 계산입니다. 생애최초 감면·법인·증여·분양권 등은 빠져 있으니 신고 전 위택스나 세무사에게 확인하세요.</div>
        <p className="calc-note">표준세율: 6억 이하 1%, 6~9억 (가액[억]×2/3−3)%, 9억 초과 3%. 지방교육세는 표준이면 취득세율의 10%, 중과면 0.4%.</p>
      </div>
    </div>
  );
}

function SubTab({ v, on }: { v: Sub; on: (p: Partial<Sub>) => void }) {
  const s1 = HOME_SCORE(v.home), s2 = FAM_SCORE(v.fam), s3 = ACCT_SCORE(v.acct);
  const total = s1 + s2 + s3;
  return (
    <div className="calc-grid">
      <div className="re-box calc-in">
        <div className="field">
          <label htmlFor="s-home">무주택 기간 (최대 32점)</label>
          <select id="s-home" value={v.home} onChange={(e) => on({ home: Number(e.target.value) })}>
            {HOME_OPTS.map((t, i) => <option key={t} value={i}>{t} — {HOME_SCORE(i)}점</option>)}
          </select>
          <div className="calc-hint">만 30세부터 센다 (그 전에 혼인했으면 혼인신고일부터)</div>
        </div>
        <div className="field">
          <label htmlFor="s-fam">부양가족 수 (최대 35점)</label>
          <select id="s-fam" value={v.fam} onChange={(e) => on({ fam: Number(e.target.value) })}>
            {FAM_OPTS.map((t, i) => <option key={t} value={i}>{t} — {FAM_SCORE(i)}점</option>)}
          </select>
          <div className="calc-hint">본인은 빼고 센다</div>
        </div>
        <div className="field">
          <label htmlFor="s-acct">청약통장 가입 기간 (최대 17점)</label>
          <select id="s-acct" value={v.acct} onChange={(e) => on({ acct: Number(e.target.value) })}>
            {ACCT_OPTS.map((t, i) => <option key={t} value={i}>{t} — {ACCT_SCORE(i)}점</option>)}
          </select>
        </div>
      </div>
      <div className="re-box calc-res">
        <div className="caption">내 청약 가점 (84점 만점)</div>
        <div className="calc-big">{total}점</div>
        <div className="calc-bar"><i style={{ width: `${(total / 84) * 100}%` }} /></div>
        <div className="calc-score">
          <div className="re-metric"><div className="k">무주택</div><div className="v">{s1}<small className="caption"> / 32</small></div></div>
          <div className="re-metric"><div className="k">부양가족</div><div className="v">{s2}<small className="caption"> / 35</small></div></div>
          <div className="re-metric"><div className="k">통장 가입</div><div className="v">{s3}<small className="caption"> / 17</small></div></div>
        </div>
        <p className="calc-note">점수표는 「주택공급에 관한 규칙」 가점제 기준입니다. 단지마다 당첨 커트라인이 다르니 지난 당첨 가점을 함께 보세요.</p>
        <div className="btn-row"><Link className="btn sm" to="/calendar?tab=scores">최근 당첨 가점과 비교 →</Link><Link className="btn sm ghost" to="/calendar">청약 일정 보기</Link></div>
      </div>
    </div>
  );
}

function GapTab({ v, tax, on }: { v: Gap; tax: Tax; on: (p: Partial<Gap>) => void }) {
  const ratio = v.price > 0 ? (v.jeonse / v.price) * 100 : NaN;
  const gap = v.price - v.jeonse;
  const t = calcTax(v.price, v.houses, v.adjusted, v.big, false, tax); // 세율은 취득세 탭(고급)과 같은 값을 쓴다
  const need = Math.max(0, gap) + t.total;
  return (
    <div className="calc-grid">
      <div className="re-box calc-in">
        <Money id="g-price" label="매매가" value={v.price} onChange={(x) => on({ price: x })} />
        <Money id="g-jeonse" label="전세가" value={v.jeonse} onChange={(x) => on({ jeonse: x })} />
        <Seg label="취득 후 주택 수 (취득세 추정용)" value={v.houses} items={[[1, "1주택"], [2, "2주택"], [3, "3주택"], [4, "4주택 이상"]]} onChange={(x) => on({ houses: x })} />
        <label className="check"><input type="checkbox" checked={v.adjusted} onChange={(e) => on({ adjusted: e.target.checked })} /> 조정대상지역</label>
        <label className="check"><input type="checkbox" checked={v.big} onChange={(e) => on({ big: e.target.checked })} /> 전용 85㎡ 초과</label>
      </div>
      <div className="re-box calc-res">
        <div className="caption">전세가율</div>
        <div className="calc-big">{pct(ratio)}</div>
        <div className={`calc-bar ${ratio >= 80 ? "hot" : ""}`}><i style={{ width: `${Math.min(100, Math.max(0, ratio || 0))}%` }} /></div>
        <div>
          <KV k="갭 (매매가 − 전세가)" v={man(gap)} />
          <KV k={`취득세 등 추정 (${pct(t.totalRate, 2)})`} v={man(t.total)} />
          <KV k="필요 자기자본" v={man(need)} total />
        </div>
        {ratio >= 80 ? (
          <div className="alert err"><b>깡통전세 위험</b> — 전세가율이 80% 이상이면 집값이 조금만 내려도 보증금을 돌려받기 어려울 수 있습니다. 세입자라면 전세보증보험 가입 가능 여부·선순위 채권(등기부등본)을 꼭 확인하세요.</div>
        ) : ratio >= 70 ? (
          <div className="alert warn">전세가율 70% 이상 — 집값 하락기에는 보증금 위험이 커집니다. 등기부등본과 보증보험 가능 여부를 확인하세요.</div>
        ) : null}
        <p className="calc-note">중개보수·이사비·대출 이자는 빠져 있습니다. 취득세는 '취득세' 탭의 세율(고급 포함)로 추정합니다.</p>
      </div>
    </div>
  );
}
