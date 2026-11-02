// 데이터 랩 — 시장 숫자 놀이터 (2026-11-02). GET /api/lab/market (backend/api/routers/lab.py).
// ① 2년 흐름(거래량 막대 + 금리·심리 선, 고르고 올려 보기) ② 내 예산으로 갈 수 있는 동네(슬라이더)
// ③ 지역 순위(3.3㎡가·상승률·거래량, 시·도 거르기) ④ 지역 비교(최대 3곳, 24개월 3.3㎡ 선).
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { get } from "../api";
import { useLoad } from "../components/ui";
import { man } from "../policy";
import LabRegion from "./LabRegion";

type Rank = { lawd: string; name: string; sido: string; pp: number; price: number; deals: number; chg: number | null };
type Market = {
  monthly: { ym: string; count: number; pp: number; seoul_count: number; seoul_pp: number | null }[];
  econ: Record<string, { name: string; unit: string; points: { p: string; v: number }[] }>;
  ranks: Rank[]; recent: string[]; source: string;
};
const ymL = (s: string) => `${s.slice(2, 4)}.${s.slice(4)}`;
const SIDO_ORDER = ["서울", "경기", "인천", "부산", "대구", "광주", "대전", "울산", "세종", "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주"];

export default function LabMarket() {
  const { data, error } = useLoad(() => get<Market>("lab/market"), []);
  if (error) return <p className="caption lm-err">시장 숫자를 불러오지 못했어요. 잠시 뒤 새로고침해 주세요.</p>;
  if (!data) return <div className="lm-skel" aria-hidden="true" />;
  return (
    <div className="lm">
      <Flow d={data} />
      <div className="lm-two">
        <Budget ranks={data.ranks} />
        <Ranking ranks={data.ranks} recent={data.recent} />
      </div>
      <LabRegion />
      <Compare ranks={data.ranks} />
      <p className="caption">출처: {data.source}. 3.3㎡당 가격은 전용면적 기준 중위값, 해제 신고 제외. 최근 3개월 = {data.recent.map(ymL).join("·")}.</p>
    </div>
  );
}

/** ① 2년 흐름 — 거래량 막대(전국/서울) + 고른 선(주담대 금리·주택가격전망·소비자심리·KB 지수) */
function Flow({ d }: { d: Market }) {
  const [area, setArea] = useState<"all" | "seoul">("all");
  const [line, setLine] = useState("mortgage_new");
  const [hov, setHov] = useState<number | null>(null);
  const W = 760, H = 260, L = 44, R = 44, T = 18, B = 26;
  const ms = d.monthly;
  const cnt = ms.map((m) => (area === "all" ? m.count : m.seoul_count));
  const cmax = Math.max(1, ...cnt);
  const step = (W - L - R) / ms.length;
  const x = (i: number) => L + step * (i + 0.5);
  const ser = d.econ[line];
  const pts = ms.map((m) => ser?.points.find((p) => p.p === m.ym)?.v ?? null);
  const vs = pts.filter((v): v is number => v !== null);
  const lo = Math.min(...vs), hi = Math.max(...vs), pad = (hi - lo) * 0.15 || 1;
  const y = (v: number) => T + (1 - (v - (lo - pad)) / (hi - lo + 2 * pad)) * (H - T - B);
  let path = "";
  pts.forEach((v, i) => { if (v !== null) path += `${path ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`; });
  const h = hov !== null ? ms[hov] : null;
  const LINES: [string, string][] = [["mortgage_new", "주담대 금리"], ["house_outlook_csi", "주택가격전망"], ["consumer_csi", "소비자심리"], ["kb_sale_apt", "KB 매매지수"], ["kb_sale_apt_seoul", "KB 서울"], ["kb_jeonse_apt", "KB 전세지수"]];
  return (
    <section className="lm-card">
      <div className="lm-h">
        <div><div className="eyebrow">2년 흐름</div><h3>거래량과 <span className="grad">{LINES.find((l) => l[0] === line)?.[1]}</span>, 같이 움직일까?</h3></div>
        <div className="lm-ctl">
          <div className="seg sm">{([["all", "전국"], ["seoul", "서울"]] as const).map(([k, l]) => <button key={k} type="button" className={area === k ? "on" : ""} onClick={() => setArea(k)}>{l}</button>)}</div>
          <div className="seg sm">{LINES.filter(([k]) => d.econ[k]).map(([k, l]) => <button key={k} type="button" className={line === k ? "on" : ""} onClick={() => setLine(k)}>{l}</button>)}</div>
        </div>
      </div>
      <div className="lm-chart">
        <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="월별 거래량과 지표">
          {ms.map((m, i) => {
            const bh = (cnt[i] / cmax) * (H - T - B);
            return <rect key={m.ym} className={`lm-bar${hov === i ? " on" : ""}`} x={x(i) - step * 0.34} width={step * 0.68} y={H - B - bh} height={bh} rx={3} />;
          })}
          <path className="lm-line" d={path} />
          {pts.map((v, i) => v !== null && <circle key={i} className="lm-dot" cx={x(i)} cy={y(v)} r={hov === i ? 5 : 3} />)}
          {ms.map((m, i) => (i % 3 === 0 || (i === ms.length - 1 && i % 3 >= 2)) && <text key={"t" + m.ym} x={x(i)} y={H - 8} textAnchor="middle">{ymL(m.ym)}</text>)}
          <text x={4} y={T + 4} className="ax">건</text><text x={W - 4} y={T + 4} textAnchor="end" className="ax">{ser?.unit}</text>
          {hov !== null && <line className="lm-cross" x1={x(hov)} x2={x(hov)} y1={T} y2={H - B} />}
          {ms.map((m, i) => <rect key={"h" + m.ym} className="hit" x={L + step * i} width={step} y={0} height={H - B}
            onMouseEnter={() => setHov(i)} onMouseLeave={() => setHov(null)} onClick={() => setHov(i)} onTouchStart={() => setHov(i)} />)}
        </svg>
        {h && hov !== null && (
          <div className={`lm-tip${hov > ms.length * 0.6 ? " r" : ""}`} style={{ left: `${(x(hov) / W) * 100}%` }}>
            <b>{h.ym.slice(0, 4)}년 {Number(h.ym.slice(4))}월</b>
            <span>거래 {(area === "all" ? h.count : h.seoul_count).toLocaleString()}건</span>
            <span>3.3㎡ 중위 {man(area === "all" ? h.pp : h.seoul_pp ?? 0)}</span>
            {pts[hov] !== null && <span>{LINES.find((l) => l[0] === line)?.[1]} {pts[hov]}</span>}
          </div>
        )}
      </div>
      <p className="caption">막대 = 아파트 매매 건수 · 선 = 고른 지표. 최근 1~2개월은 신고 기한(30일) 안이라 건수가 더 늘 수 있어요.</p>
    </section>
  );
}

/** ② 내 예산으로 갈 수 있는 동네 */
function Budget({ ranks }: { ranks: Rank[] }) {
  const [b, setB] = useState(60000); // 만원
  const [sido, setSido] = useState("");
  const ok = useMemo(() => ranks.filter((r) => r.price <= b && (!sido || r.sido === sido)).sort((a, z) => z.price - a.price), [ranks, b, sido]);
  return (
    <section className="lm-card">
      <div className="eyebrow">내 예산 지도</div>
      <h3>예산 <span className="grad">{man(b)}</span>이면 갈 수 있는 동네</h3>
      <input type="range" className="lm-range" min={10000} max={300000} step={5000} value={b} onChange={(e) => setB(Number(e.target.value))} aria-label="예산" />
      <div className="lm-scale"><span>1억</span><span>10억</span><span>20억</span><span>30억</span></div>
      <select className="lm-sel" value={sido} onChange={(e) => setSido(e.target.value)} aria-label="시·도">
        <option value="">전국</option>{SIDO_ORDER.map((s) => <option key={s}>{s}</option>)}
      </select>
      <p className="lm-big"><b>{ok.length}</b>곳 <small>/ {ranks.filter((r) => !sido || r.sido === sido).length}곳의 아파트 중위 매매가가 예산 안</small></p>
      <div className="lm-chips">
        {ok.slice(0, 24).map((r) => <Link key={r.lawd} to={`/deals?lawd=${r.lawd}`} className="lm-chip" title={`중위 ${man(r.price)} · 3.3㎡ ${man(r.pp)}`}>{r.name.replace(/^\S+ /, "")}<small>{man(r.price)}</small></Link>)}
        {ok.length > 24 && <span className="caption">외 {ok.length - 24}곳</span>}
        {!ok.length && <span className="caption">예산을 올려 보세요.</span>}
      </div>
      <p className="caption">최근 3개월 시군구 아파트 매매 중위가 기준 — 실제로는 단지·평형마다 차이가 커요. 이름을 누르면 실거래가로.</p>
    </section>
  );
}

/** ③ 지역 순위 */
function Ranking({ ranks, recent }: { ranks: Rank[]; recent: string[] }) {
  const [by, setBy] = useState<"pp" | "chg" | "deals">("chg");
  const [sido, setSido] = useState("");
  const [desc, setDesc] = useState(true);
  const rows = useMemo(() => {
    const rs = ranks.filter((r) => (!sido || r.sido === sido) && (by !== "chg" || r.chg !== null));
    return rs.sort((a, z) => ((desc ? 1 : -1) * (((z[by] as number) ?? 0) - ((a[by] as number) ?? 0)))).slice(0, 12);
  }, [ranks, by, sido, desc]);
  const max = Math.max(1, ...rows.map((r) => Math.abs((r[by] as number) ?? 0)));
  const fmt = (r: Rank) => (by === "pp" ? man(r.pp) : by === "deals" ? `${r.deals.toLocaleString()}건` : `${(r.chg ?? 0) > 0 ? "+" : ""}${r.chg}%`);
  return (
    <section className="lm-card">
      <div className="eyebrow">지역 순위</div>
      <h3>{by === "chg" ? (desc ? "많이 오른" : "많이 내린") : by === "pp" ? (desc ? "비싼" : "싼") : (desc ? "거래 많은" : "거래 적은")} <span className="grad">시군구</span> 12</h3>
      <div className="lm-ctl">
        <div className="seg sm">{([["chg", "상승률"], ["pp", "3.3㎡가"], ["deals", "거래량"]] as const).map(([k, l]) => <button key={k} type="button" className={by === k ? "on" : ""} onClick={() => setBy(k)}>{l}</button>)}</div>
        <button type="button" className="pill sm" onClick={() => setDesc(!desc)}>{desc ? "↓ 높은 순" : "↑ 낮은 순"}</button>
        <select className="lm-sel" value={sido} onChange={(e) => setSido(e.target.value)} aria-label="시·도"><option value="">전국</option>{SIDO_ORDER.map((s) => <option key={s}>{s}</option>)}</select>
      </div>
      <ol className="lm-rank">
        {rows.map((r, i) => {
          const v = (r[by] as number) ?? 0;
          return (
            <li key={r.lawd}>
              <span className="rk">{i + 1}</span>
              <Link to={`/deals?lawd=${r.lawd}`} className="nm">{r.name}</Link>
              <span className="bar"><i className={by === "chg" && v < 0 ? "neg" : ""} style={{ width: `${(Math.abs(v) / max) * 100}%` }} /></span>
              <b className={by === "chg" ? (v > 0 ? "up" : v < 0 ? "down" : "") : ""}>{fmt(r)}</b>
            </li>
          );
        })}
      </ol>
      <p className="caption">상승률 = 최근 3개월({recent.map(ymL).join("·")}) 3.3㎡ 중위가 ÷ 그 전 3개월 − 1. 거래 10건 미만 지역은 뺐어요.</p>
    </section>
  );
}

/** ④ 지역 비교 — 최대 3곳의 24개월 3.3㎡ 평균가 */
function Compare({ ranks }: { ranks: Rank[] }) {
  const byName = useMemo(() => [...ranks].sort((a, z) => a.name.localeCompare(z.name, "ko")), [ranks]);
  const [pick, setPick] = useState<string[]>(() => ["11680", "11215", "41135"].filter((c) => ranks.some((r) => r.lawd === c)));
  const [hov, setHov] = useState<number | null>(null);
  const series = useLoad(() => Promise.all(pick.map((l) => get<{ points: { ymd: string; avg_pyeong: number | null; missing?: boolean }[] }>(`re/region/trend?lawd=${l}&months=24`))), [pick.join(",")]);
  const COLORS = ["var(--accent)", "#5AB2FF", "#FF7A7A"];
  const W = 760, H = 240, L = 50, R = 12, T = 14, B = 24;
  const pts = series.data || [];
  const n = pts[0]?.points.length || 0;
  const all = pts.flatMap((s) => s.points.map((p) => p.avg_pyeong).filter((v): v is number => v !== null));
  const lo = Math.min(...all), hi = Math.max(...all), pad = (hi - lo) * 0.1 || 1;
  const x = (i: number) => L + ((W - L - R) * i) / Math.max(1, n - 1);
  const y = (v: number) => T + (1 - (v - (lo - pad)) / (hi - lo + 2 * pad)) * (H - T - B);
  const toggle = (c: string) => setPick((p) => (p.includes(c) ? p.filter((x) => x !== c) : p.length >= 3 ? [...p.slice(1), c] : [...p, c]));
  return (
    <section className="lm-card">
      <div className="eyebrow">지역 비교</div>
      <h3>세 동네, <span className="grad">2년 동안 어떻게</span> 달라졌을까</h3>
      <div className="lm-ctl">
        {pick.map((c, i) => <button key={c} type="button" className="lm-pick" style={{ borderColor: COLORS[i] }} onClick={() => toggle(c)}>
          <i style={{ background: COLORS[i] }} />{ranks.find((r) => r.lawd === c)?.name || c} ×</button>)}
        <select className="lm-sel" value="" onChange={(e) => e.target.value && toggle(e.target.value)} aria-label="비교할 시군구 추가">
          <option value="">+ 시군구 추가 (최대 3곳)</option>{byName.map((r) => <option key={r.lawd} value={r.lawd}>{r.name}</option>)}
        </select>
      </div>
      {!n ? <div className="lm-skel sm" /> : (
        <div className="lm-chart">
          <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="지역별 3.3㎡ 평균가 비교">
            {[0.2, 0.5, 0.8].map((f) => { const v = lo - pad + (hi - lo + 2 * pad) * (1 - f); return <g key={f}><line className="lm-grid" x1={L} x2={W - R} y1={y(v)} y2={y(v)} /><text x={L - 6} y={y(v) + 4} textAnchor="end">{Math.round(v / 100) / 100}억</text></g>; })}
            {pts.map((s, k) => {
              let d = "";
              s.points.forEach((p, i) => { if (p.avg_pyeong !== null && !p.missing) d += `${d && s.points[i - 1]?.avg_pyeong !== null ? "L" : "M"}${x(i).toFixed(1)},${y(p.avg_pyeong).toFixed(1)}`; });
              return <path key={k} d={d} fill="none" stroke={COLORS[k]} strokeWidth={2.4} strokeLinejoin="round" />;
            })}
            {pts[0]?.points.map((p, i) => (i % 3 === 0 || (i === n - 1 && i % 3 >= 2)) && <text key={p.ymd} x={x(i)} y={H - 6} textAnchor="middle">{ymL(p.ymd)}</text>)}
            {hov !== null && <line className="lm-cross" x1={x(hov)} x2={x(hov)} y1={T} y2={H - B} />}
            {pts[0]?.points.map((p, i) => <rect key={"h" + p.ymd} className="hit" x={x(i) - (W - L - R) / n / 2} width={(W - L - R) / n} y={0} height={H - B}
              onMouseEnter={() => setHov(i)} onMouseLeave={() => setHov(null)} onTouchStart={() => setHov(i)} />)}
          </svg>
          {hov !== null && pts[0] && (
            <div className={`lm-tip${hov > n * 0.6 ? " r" : ""}`} style={{ left: `${(x(hov) / W) * 100}%` }}>
              <b>{pts[0].points[hov].ymd.slice(0, 4)}년 {Number(pts[0].points[hov].ymd.slice(4))}월</b>
              {pts.map((s, k) => <span key={k}><i style={{ background: COLORS[k] }} />{ranks.find((r) => r.lawd === pick[k])?.name.replace(/^\S+ /, "")} {s.points[hov]?.avg_pyeong ? man(s.points[hov].avg_pyeong as number) : "자료 없음"}</span>)}
            </div>
          )}
        </div>
      )}
      <p className="caption">시군구 아파트 매매 3.3㎡당 평균가(월별). 칩을 누르면 빼고, 목록에서 고르면 더해요.</p>
    </section>
  );
}
