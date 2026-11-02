// 홈 보강 (2026-11-02) — 노트가 적어도 첫 화면이 비지 않게, 이미 모은 자료로 '지금 시장'을 보여 준다.
// AffordHero: '대출까지 받으면 살 수 있는 집 가격은?' 즉시 계산 (브라우저 계산, 서버 저장 없음)
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
  extra?: { label: string; value: string; sub: string; dir: string; href: string }[];
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

/** 공고 제목에서 [정정공고]·[OO지역본부] 같은 머리말을 떼어 칩으로 — 제목은 짧고 읽기 쉽게 */
function cleanApply(name: string): { title: string; tags: string[] } {
  const tags: string[] = [];
  let t = name.trim();
  for (let m = /^\[([^\]]{1,20})\]\s*/.exec(t); m; m = /^\[([^\]]{1,20})\]\s*/.exec(t)) {
    const w = m[1].replace(/지역본부$/, "");
    if (/정정/.test(w)) tags.push("정정");
    else if (w.length <= 8) tags.push(w);
    t = t.slice(m[0].length);
  }
  if (/임대|전세|매입/.test(t) && !tags.includes("임대")) tags.push("임대");
  return { title: t.replace(/\s*(입주자\s*)?모집\s*공고\s*$/, "").trim() || t, tags: tags.slice(0, 2) };
}

const dday = (d: string) => Math.round((new Date(d + "T00:00:00").getTime() - new Date(new Date().toDateString()).getTime()) / 86_400_000);

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
  // 비어 있으면 예시 값(연소득 7,000만원·모아둔 돈 2억)으로 계산해 흐리게 보여 준다 — 무엇을 알려 주는 칸인지 바로 보이게
  const example = !income;
  const inc = income || 7000, own = income ? cash : 20000;
  const r = useMemo(() => {
    const loanCap = dsrLoan(inc, dsr, rate);
    let lo = 0, hi = 3_000_000;
    for (let i = 0; i < 40; i++) {
      const mid = (lo + hi) / 2;
      const loan = Math.min(loanCap, (mid * ltv) / 100);
      if (own + loan >= mid + acqTax(mid)) lo = mid; else hi = mid;
    }
    const price = Math.floor(lo / 100) * 100;
    return { price, loan: Math.min(loanCap, (price * ltv) / 100), loanCap };
  }, [inc, own, rate, dsr]);
  const num = (v: string) => Math.min(9_999_999, Number(v.replace(/[^\d]/g, "")) || 0);
  return (
    <div className="afford" aria-label="살 수 있는 집 가격 계산">
      <div className="afford-q">대출까지 받으면 살 수 있는 집 가격은?</div>
      <div className="afford-in">
        <label>연소득 (세전)<span><input inputMode="numeric" value={income ? income.toLocaleString("ko-KR") : ""} placeholder="예) 7,000" onChange={(e) => setIncome(num(e.target.value))} />만원</span></label>
        <label>모아둔 돈<span><input inputMode="numeric" value={cash ? cash.toLocaleString("ko-KR") : ""} placeholder="예) 20,000" onChange={(e) => setCash(num(e.target.value))} />만원</span></label>
      </div>
      {example ? (
        <div className="afford-out ex" role="status">
          <span className="afford-tag">예시 · 연소득 7,000만원 · 모아둔 돈 2억원이면</span>
          <b>약 {man(r.price)}</b>까지
          <small>은행 대출 {man(r.loan)} 포함 · 내 숫자를 넣으면 바로 바뀌어요. 입력값은 저장하지 않아요.</small>
        </div>
      ) : (
        <div className="afford-out" role="status">
          <span className="afford-tag">내가 살 수 있는 집값</span>
          <b>약 {man(r.price)}</b>까지
          <small>은행 대출 {man(r.loan)} + 내 돈 {man(cash)} = 집값 + 취득세 {man(Math.round(acqTax(r.price)))} · 금리 {rate}%·DSR {dsr}%·LTV {ltv}%·30년 가정</small>
          <div className="afford-btns">
            <Link className="btn sm" to={`/calc?price=${r.price}&label=${encodeURIComponent("홈 계산 결과")}`} onClick={() => track("click", "afford_calc")}>자세히 계산 →</Link>
            <Link className="btn sm ghost" to="/deals">이 가격대 실거래 보기</Link>
            <button type="button" className="btn sm ghost" onClick={() => openSubscribe("home_afford")}>내 조건 브리핑 받기</button>
          </div>
        </div>
      )}
    </div>
  );
}

const pctTxt = (a: number, b: number) => { const v = (a / b - 1) * 100; return `${v > 0 ? "+" : ""}${v.toFixed(1)}%`; };
const dir = (a: number, b: number) => (a > b ? "up" : a < b ? "down" : "");

type TopRes = { ym: string | null; label: string; kind: string; source?: string;
  rows: { lawd: string; region: string; umd: string; name: string; area: number | null; floor: number | null; amount: number; date: string }[] };
const TOP_SIDO: [string, string][] = [["all", "전국"], ["11", "서울"], ["41", "경기"], ["26", "부산"]];
const TOP_KIND: [string, string][] = [["apt", "아파트"], ["offi", "오피스텔"], ["nrg", "상가·업무"]];

type VolRes = { ym: string | null; label: string; kind: string; count: number; median: number | null; reporting?: boolean; source?: string;
  prev: { label: string; count: number; median: number } | null; regions: { lawd: string; name: string; count: number; median: number }[] };
const SIDO_LABEL: Record<string, string> = { all: "전국", "11": "서울", "41": "경기", "26": "부산" };

/** 지난달 거래 요약 + 거래 많은 지역 10곳 — 지역·종류를 골라 본다 (가장 비싼 거래와 같은 고르기, 2026-11-02) */
function VolumeBox() {
  const ls = (k: string, d: string) => { try { return localStorage.getItem(k) || d; } catch { return d; } };
  const [sido, setSido] = useState(() => ls("zg-vol-sido", "all"));
  const [kind, setKind] = useState(() => ls("zg-vol-kind", "apt"));
  const pick = (k: string, v: string, set: (v: string) => void) => { set(v); try { localStorage.setItem(k, v); } catch { /* 무시 */ } };
  const { data: t, loading } = useLoad(() => get<VolRes>(`home/volume?kind=${kind}&sido=${sido}`), [kind, sido]);
  return (
    <div className="mkt-box top-box">
      <h3>{t?.label || "지난달"} {SIDO_LABEL[sido]} {t?.kind || ""} 매매{t?.reporting && <span className="re-tag">신고 진행 중</span>}</h3>
      <div className="top-filters">
        <div className="seg sm" role="group" aria-label="지역">
          {TOP_SIDO.map(([v, l]) => <button key={v} type="button" className={sido === v ? "on" : ""} onClick={() => pick("zg-vol-sido", v, setSido)}>{l}</button>)}
        </div>
        <div className="seg sm" role="group" aria-label="종류">
          {TOP_KIND.map(([v, l]) => <button key={v} type="button" className={kind === v ? "on" : ""} onClick={() => pick("zg-vol-kind", v, setKind)}>{l}</button>)}
        </div>
      </div>
      {loading && !t ? <p className="caption">불러오는 중…</p> : !t?.count ? <p className="caption">이 조건의 거래 자료가 아직 없어요.</p> : (
        <>
          <div className="mkt-big">
            <div><span className="k">거래</span><b>{t.count.toLocaleString()}건</b>{t.prev && <span className={`d ${dir(t.count, t.prev.count)}`}>{t.prev.label} {t.prev.count.toLocaleString()}건 대비 {pctTxt(t.count, t.prev.count)}</span>}</div>
            <div><span className="k">중위 거래가</span><b>{man(t.median ?? 0)}</b>{t.prev && t.median && <span className={`d ${dir(t.median, t.prev.median)}`}>{pctTxt(t.median, t.prev.median)}</span>}</div>
          </div>
          <div className="caption" style={{ marginTop: 8 }}>거래가 많은 지역 10곳</div>
          <ol className="top-list">
            {t.regions.map((r, i) => (
              <li key={r.lawd} className={i < 3 ? "top3" : ""}>
                <span className="rk">{i + 1}</span>
                <Link to={`/deals?lawd=${r.lawd}&ymd=${t.ym}`} className="nm">{sido === "all" ? r.name : r.name.replace(/^\S+ /, "")}</Link>
                <b className="amt">{r.count.toLocaleString()}건</b>
                <span className="meta">중위 {man(r.median)}</span>
              </li>
            ))}
          </ol>
          {t.reporting && <p className="caption" style={{ margin: "6px 0 0" }}>계약 후 30일 안에 신고하므로 이 달 숫자는 더 늘어납니다.</p>}
        </>
      )}
    </div>
  );
}

/** 지난달 가장 비싼 거래 10건 — 지역·종류를 골라 본다 (고른 값은 이 브라우저에 기억) */
function TopDeals() {
  const ls = (k: string, d: string) => { try { return localStorage.getItem(k) || d; } catch { return d; } };
  const [sido, setSido] = useState(() => ls("zg-top-sido", "all"));
  const [kind, setKind] = useState(() => ls("zg-top-kind", "apt"));
  const pick = (k: string, v: string, set: (v: string) => void) => { set(v); try { localStorage.setItem(k, v); } catch { /* 무시 */ } };
  const { data, loading } = useLoad(() => get<TopRes>(`home/top?kind=${kind}&sido=${sido}&limit=10`), [kind, sido]);
  return (
    <div className="mkt-box top-box">
      <h3>{data?.label || "지난달"} 가장 비싼 거래</h3>
      <div className="top-filters">
        <div className="seg sm" role="group" aria-label="지역">
          {TOP_SIDO.map(([v, l]) => <button key={v} type="button" className={sido === v ? "on" : ""} onClick={() => pick("zg-top-sido", v, setSido)}>{l}</button>)}
        </div>
        <div className="seg sm" role="group" aria-label="종류">
          {TOP_KIND.map(([v, l]) => <button key={v} type="button" className={kind === v ? "on" : ""} onClick={() => pick("zg-top-kind", v, setKind)}>{l}</button>)}
        </div>
      </div>
      {loading && !data ? <p className="caption">불러오는 중…</p> : !data?.rows.length ? <p className="caption">이 조건의 거래 자료가 아직 없어요.</p> : (
        <>
        {/* 왼쪽 거래 요약 칸과 높이를 맞추는 요약 2칸 (2026-11-02) */}
        {(() => {
          const top = data.rows[0];
          const avg = data.rows.reduce((a, r) => a + r.amount, 0) / data.rows.length;
          const pps = data.rows.filter((r) => r.area).map((r) => (r.amount / (r.area as number)) * 3.305785);
          const pp = pps.length ? pps.reduce((a, v) => a + v, 0) / pps.length : null;
          return (
            <div className="mkt-big" style={{ marginBottom: 8 }}>
              <div><span className="k">최고 거래가</span><b>{man(top.amount)}</b><span className="d">{top.name} · {top.region.split(" ").slice(-1)[0]}</span></div>
              <div><span className="k">상위 {data.rows.length}건 평균</span><b>{man(Math.round(avg))}</b><span className="d">{pp ? `3.3㎡당 평균 ${man(Math.round(pp))}` : `${data.kind} 매매`}</span></div>
            </div>
          );
        })()}
        <ol className="top-list">
          {data.rows.map((x, i) => (
            <li key={i} className={i < 3 ? "top3" : ""}>
              <span className="rk">{i + 1}</span>
              <Link to={`/deals?lawd=${x.lawd}&ymd=${data.ym}`} className="nm">{x.name}</Link>
              <b className="amt">{man(x.amount)}</b>
              <span className="meta">{x.region.split(" ").slice(-1)[0]} {x.umd}{x.area ? ` · ${x.area.toFixed(0)}㎡` : ""}{x.floor ? ` · ${x.floor}층` : ""}</span>
            </li>
          ))}
        </ol>
        </>
      )}
      {data?.source && <p className="caption" style={{ margin: "6px 0 0" }}>출처: {data.source} (해제 신고 제외)</p>}
    </div>
  );
}

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
        {(data.extra || []).map((x) => (
          <Link key={x.label} to={x.href} className="mkt-kpi">
            <span className="k">{x.label}</span><span className="v">{x.value}</span><span className={`d ${x.dir}`}>{x.sub}</span>
          </Link>
        ))}
      </div>
      {t && (
        <div className="mkt-grid">
          <VolumeBox />
          <TopDeals />
          <div className="mkt-box">
            <h3>앞으로 2주 청약 일정</h3>
            {data.apply.length ? (
              <ul className="ap-list">
                {data.apply.map((a, i) => {
                  const { title, tags: raw } = cleanApply(a.name);
                  const tags = raw.filter((t) => t !== a.region && !(a.region && t.startsWith(a.region)));
                  const dd = dday(a.date);
                  const body = (
                    <>
                      <div className={`ap-date${dd <= 1 ? " hot" : ""}`}>
                        <span className="m">{Number(a.date.slice(5, 7))}월</span><b>{Number(a.date.slice(8, 10))}</b>
                        <span className="dd">{dd <= 0 ? "오늘" : `D-${dd}`}</span>
                      </div>
                      <div className="ap-body">
                        <div className="ap-title">{title}</div>
                        <div className="ap-meta">
                          <span className="ap-chip k">{a.label}</span>
                          {a.region && <span className="ap-chip">{a.region}</span>}
                          {tags.map((t) => <span key={t} className="ap-chip t">{t}</span>)}
                        </div>
                      </div>
                    </>
                  );
                  return <li key={i}>{a.url ? <a className="ap-row" href={a.url} target="_blank" rel="noopener">{body}</a> : <div className="ap-row">{body}</div>}</li>;
                })}
              </ul>
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
