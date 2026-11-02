// 홈 보강 (2026-11-02) — 노트가 적어도 첫 화면이 비지 않게, 이미 모은 자료로 '지금 시장'을 보여 준다.
// AffordHero: '내 연소득으로 살 수 있는 집 가격은?' 즉시 계산 (브라우저 계산, 서버 저장 없음)
// MarketBoard: /api/home/market — 지표·지난달 거래·거래 많은 지역·최고가·다가오는 청약·오늘 읽은 기사
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { get, track } from "../api";
import { useDialogs } from "../components/Dialogs";
import { useLoad } from "../components/ui";
import { type Param, dsrLoan, fmtValue, man, useNow } from "../policy";
import { useProfile } from "../profile";

type Market = {
  indicators: Param[];
  kb_seoul: { label: string; value: number; period: string; mom: number; source: string } | null;
  trades: {
    ym: string; label: string; count: number; median: number; reporting: boolean; source: string;
    prev: { label: string; count: number; median: number } | null;
    regions: { lawd: string; name: string; count: number; median: number }[];
    top: { lawd: string; region: string; umd: string; name: string; area: number; floor: number | null; amount: number; date: string }[];
  } | null;
  apply: { date: string; label: string; name: string; region: string; id: string; url: string }[];
  articles: { title: string; source: string; url: string; at: string }[];
  at: string;
};

/** 1주택 표준세율 취득세 + 지방교육세(세율의 10%) — 만원 */
function acqTax(price: number): number {
  const rate = price <= 60000 ? 1 : price <= 90000 ? Math.round(((price / 10000) * (2 / 3) - 3) * 100) / 100 : 3;
  return (price * rate * 1.1) / 100;
}

export function AffordHero() {
  const { profile } = useProfile();
  const { map } = useNow();
  const { openSubscribe } = useDialogs();
  const [income, setIncome] = useState<number>(0);
  const [cash, setCash] = useState<number>(0);
  useEffect(() => { if (profile?.income && !income) setIncome(profile.income); }, [profile?.income]); // eslint-disable-line react-hooks/exhaustive-deps
  const rate = map.mortgage_rate?.value ?? 4.0;
  const dsr = map.dsr_bank?.value ?? 40;
  const ltv = 70;
  const r = useMemo(() => {
    if (!income) return null;
    const loanCap = dsrLoan(income, dsr, rate);
    let lo = 0, hi = 3_000_000;
    for (let i = 0; i < 40; i++) {
      const mid = (lo + hi) / 2;
      const loan = Math.min(loanCap, (mid * ltv) / 100);
      if (cash + loan >= mid + acqTax(mid)) lo = mid; else hi = mid;
    }
    const price = Math.floor(lo / 100) * 100;
    return { price, loan: Math.min(loanCap, (price * ltv) / 100), loanCap };
  }, [income, cash, rate, dsr]);
  const num = (v: string) => Math.min(9_999_999, Number(v.replace(/[^\d]/g, "")) || 0);
  return (
    <div className="afford" aria-label="살 수 있는 집 가격 계산">
      <div className="afford-q">내 연소득으로 살 수 있는 집 가격은?</div>
      <div className="afford-in">
        <label>연소득 (세전)<span><input inputMode="numeric" value={income ? income.toLocaleString("ko-KR") : ""} placeholder="7,000" onChange={(e) => setIncome(num(e.target.value))} />만원</span></label>
        <label>모아둔 돈<span><input inputMode="numeric" value={cash ? cash.toLocaleString("ko-KR") : ""} placeholder="20,000" onChange={(e) => setCash(num(e.target.value))} />만원</span></label>
      </div>
      {r ? (
        <div className="afford-out" role="status">
          <b>약 {man(r.price)}</b>까지
          <small>대출 {man(r.loan)} + 내 돈 {man(cash)} · 취득세 포함 · 금리 {rate}%·DSR {dsr}%·LTV {ltv}%·30년 가정</small>
          <div className="afford-btns">
            <Link className="btn sm" to={`/calc?price=${r.price}&label=${encodeURIComponent("홈 계산 결과")}`} onClick={() => track("click", "afford_calc")}>자세히 계산 →</Link>
            <Link className="btn sm ghost" to="/deals">이 가격대 실거래 보기</Link>
            <button type="button" className="btn sm ghost" onClick={() => openSubscribe("home_afford")}>내 조건 브리핑 받기</button>
          </div>
        </div>
      ) : <div className="afford-out muted">연소득을 넣으면 바로 계산해요. 입력값은 저장하지 않아요.</div>}
    </div>
  );
}

const pctTxt = (a: number, b: number) => { const v = (a / b - 1) * 100; return `${v > 0 ? "+" : ""}${v.toFixed(1)}%`; };
const dir = (a: number, b: number) => (a > b ? "up" : a < b ? "down" : "");

export function MarketBoard() {
  const { data } = useLoad(() => get<Market>("home/market"), []);
  if (!data) return <div className="mkt-skel" aria-hidden="true" />;
  const t = data.trades;
  return (
    <section className="mkt" aria-label="지금 시장">
      <div className="eyebrow">지금 시장</div>
      <h2 className="sec-h">숫자로 보는 <span className="grad">이번 달 부동산</span></h2>
      <div className="mkt-ind">
        {data.indicators.map((p) => {
          const d = p.prev_value !== null && p.value !== null ? p.value - p.prev_value : null;
          return (
            <Link key={p.key} to="/now" className="mkt-kpi">
              <span className="k">{p.label.replace(" (소비자동향조사)", "").replace(" (신규취급액)", "")}</span>
              <span className="v">{fmtValue(p.value, p.value_text, p.unit)}</span>
              <span className={`d ${d ? (d > 0 ? "up" : "down") : ""}`}>{d ? `${d > 0 ? "▲" : "▼"} ${Math.abs(d).toLocaleString("ko-KR", { maximumFractionDigits: 2 })}${p.unit === "%" ? "%p" : p.unit} ` : ""}{p.effective_on} 기준</span>
            </Link>
          );
        })}
        {data.kb_seoul && (
          <Link to="/now" className="mkt-kpi">
            <span className="k">{data.kb_seoul.label}</span>
            <span className="v">{data.kb_seoul.value.toFixed(1)}</span>
            <span className={`d ${data.kb_seoul.mom > 0 ? "up" : data.kb_seoul.mom < 0 ? "down" : ""}`}>전월 대비 {data.kb_seoul.mom > 0 ? "+" : ""}{data.kb_seoul.mom}% · {data.kb_seoul.period}</span>
          </Link>
        )}
      </div>
      {t && (
        <div className="mkt-grid">
          <div className="mkt-box">
            <h3>{t.label} 전국 아파트 매매{t.reporting && <span className="re-tag">신고 진행 중</span>}</h3>
            <div className="mkt-big">
              <div><span className="k">거래</span><b>{t.count.toLocaleString()}건</b>{t.prev && <span className={`d ${dir(t.count, t.prev.count)}`}>{t.prev.label} {t.prev.count.toLocaleString()}건 대비 {pctTxt(t.count, t.prev.count)}</span>}</div>
              <div><span className="k">중위 거래가</span><b>{man(t.median)}</b>{t.prev && <span className={`d ${dir(t.median, t.prev.median)}`}>{pctTxt(t.median, t.prev.median)}</span>}</div>
            </div>
            <div className="caption" style={{ marginTop: 8 }}>거래가 많은 지역</div>
            <ol className="mkt-list">
              {t.regions.map((r) => <li key={r.lawd}><Link to={`/deals?lawd=${r.lawd}&ymd=${t.ym}`}>{r.name}</Link><span>{r.count.toLocaleString()}건 · 중위 {man(r.median)}</span></li>)}
            </ol>
            {t.reporting && <p className="caption" style={{ margin: "6px 0 0" }}>계약 후 30일 안에 신고하므로 이 달 숫자는 더 늘어납니다.</p>}
          </div>
          <div className="mkt-box">
            <h3>{t.label} 가장 비싼 거래</h3>
            <ol className="mkt-list">
              {t.top.map((x, i) => (
                <li key={i}><Link to={`/deals?lawd=${x.lawd}&ymd=${t.ym}`}>{x.name}</Link><span>{man(x.amount)} · {x.area?.toFixed(0)}㎡{x.floor ? ` ${x.floor}층` : ""} · {x.region.split(" ").slice(-1)[0]} {x.umd}</span></li>
              ))}
            </ol>
            <p className="caption" style={{ margin: "6px 0 0" }}>출처: {t.source} (해제 신고 제외)</p>
          </div>
          <div className="mkt-box">
            <h3>앞으로 2주 청약 일정</h3>
            {data.apply.length ? (
              <ol className="mkt-list">
                {data.apply.map((a, i) => (
                  <li key={i}><span className="mkt-date">{a.date.slice(5).replace("-", ".")} {a.label}</span>
                    {a.url ? <a href={a.url} target="_blank" rel="noopener">{a.name}</a> : a.name} <span>{a.region}</span></li>
                ))}
              </ol>
            ) : <p className="caption">앞으로 2주 안에 잡힌 일정이 없어요.</p>}
            <Link className="more" to="/calendar">분양 일정 전체 →</Link>
          </div>
          <div className="mkt-box">
            <h3>오늘 읽은 기사</h3>
            <ul className="mkt-news">
              {data.articles.map((a) => (
                <li key={a.url}><a href={a.url} target="_blank" rel="noopener">{a.title}</a><span>{a.source} · {a.at.slice(5, 16).replace("T", " ")}</span></li>
              ))}
            </ul>
            <p className="caption" style={{ margin: "6px 0 0" }}>여러 매체에서 부동산 관련도가 높은 기사만 골랐어요. 제목을 누르면 원문으로 가요.</p>
          </div>
        </div>
      )}
    </section>
  );
}
