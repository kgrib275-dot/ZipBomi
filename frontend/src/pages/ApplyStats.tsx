// 청약 통계 (2026-11-02) — GET /api/re/apply-stats (청약홈 신청·당첨자 통계). /calendar?tab=scores 위쪽.
// ① 지역별 가점 당첨선 추이(최저~최고 띠 + 평균 선 + 내 가점 선) ② 지역별 경쟁률 순위 ③ 연령대별 신청·당첨과 당첨 비율.
import { useMemo, useState } from "react";
import { get } from "../api";
import { useLoad } from "../components/ui";
import { useProfile } from "../profile";
import { subScore } from "./Calendar";

type Pt = { ym: string; low: number | null; med: number | null; avg: number | null; top: number | null };
type Age = { ym: string; a30: number; a40: number; a50: number; a60: number };
type Stats = { score: Record<string, Pt[]>; cmpet_rank: { area: string; req: number; hh: number; rate: number }[];
  cmpet_month: { ym: string; rate: number | null }[]; ages: { req_age: Age[]; win_age: Age[] }; period: string; source: string };
const ORDER = ["서울", "경기", "인천", "부산", "대구", "광주", "대전", "울산", "세종", "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주"];
const AGES: [keyof Omit<Age, "ym">, string][] = [["a30", "30대 이하"], ["a40", "40대"], ["a50", "50대"], ["a60", "60대 이상"]];

export default function ApplyStats() {
  const { data, error } = useLoad(() => get<Stats>("re/apply-stats"), []);
  if (error) return null;
  const { profile } = useProfile();
  const mine = subScore(profile);
  if (!data) return <div className="lm-skel sm" aria-hidden="true" />;
  if (!Object.keys(data.score).length) return null;
  return (
    <div className="as">
      <ScoreTrend d={data} mine={mine} />
      <div className="lm-two">
        <CmpetRank d={data} />
        <AgeBox d={data} />
      </div>
      <p className="caption">출처: {data.source}. 해당지역 1순위 가점제 당첨자 기준, 월별 집계.</p>
    </div>
  );
}

function ScoreTrend({ d, mine }: { d: Stats; mine: number | null }) {
  const areas = ORDER.filter((a) => d.score[a]?.length);
  const [area, setArea] = useState(areas.includes("서울") ? "서울" : areas[0]);
  const [hov, setHov] = useState<number | null>(null);
  const pts = (d.score[area] || []).filter((p) => p.avg !== null);
  const W = 760, H = 240, L = 34, R = 12, T = 14, B = 24;
  const n = pts.length;
  const x = (i: number) => L + ((W - L - R) * i) / Math.max(1, n - 1);
  const y = (v: number) => T + (1 - v / 84) * (H - T - B);
  const band = pts.length ? `M${pts.map((p, i) => `${x(i)},${y(p.top ?? p.avg ?? 0)}`).join("L")}L${[...pts].reverse().map((p, i) => `${x(n - 1 - i)},${y(p.low ?? p.avg ?? 0)}`).join("L")}Z` : "";
  const line = pts.map((p, i) => `${i ? "L" : "M"}${x(i)},${y(p.avg ?? 0)}`).join("");
  const last = pts[n - 1];
  const h = hov !== null ? pts[hov] : null;
  return (
    <section className="lm-card">
      <div className="lm-h">
        <div><div className="eyebrow">가점 당첨선</div><h3><span className="grad">{area}</span> 당첨자 가점, 몇 점이었나</h3></div>
        <select className="lm-sel" value={area} onChange={(e) => setArea(e.target.value)} aria-label="지역">{areas.map((a) => <option key={a}>{a}</option>)}</select>
      </div>
      {last && (
        <p className="as-sum">최근({last.ym.slice(0, 4)}.{last.ym.slice(4)}) 평균 <b>{last.avg}점</b> · 최저 {last.low}점 · 최고 {last.top}점
          {mine !== null && <> — 내 가점 <b className={mine >= (last.low ?? 99) ? "ok" : "no"}>{mine}점</b>{mine >= (last.avg ?? 99) ? " (평균 이상)" : mine >= (last.low ?? 99) ? " (최저선 이상)" : " (최저선 아래)"}</>}</p>
      )}
      {n > 1 && (
        <div className="lm-chart">
          <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${area} 가점 당첨선 추이`}>
            {[20, 40, 60, 80].map((v) => <g key={v}><line className="lm-grid" x1={L} x2={W - R} y1={y(v)} y2={y(v)} /><text x={L - 6} y={y(v) + 4} textAnchor="end">{v}</text></g>)}
            <path d={band} className="as-band" />
            <path d={line} className="lm-line" />
            {mine !== null && <><line className="as-mine" x1={L} x2={W - R} y1={y(mine)} y2={y(mine)} /><text x={W - R} y={y(mine) - 5} textAnchor="end" className="as-mine-t">내 가점 {mine}</text></>}
            {pts.map((p, i) => <circle key={p.ym} className="lm-dot" cx={x(i)} cy={y(p.avg ?? 0)} r={hov === i ? 5 : 3} />)}
            {pts.map((p, i) => (i % 3 === 0 || (i === n - 1 && i % 3 >= 2)) && <text key={"t" + p.ym} x={x(i)} y={H - 6} textAnchor="middle">{p.ym.slice(2, 4)}.{p.ym.slice(4)}</text>)}
            {hov !== null && <line className="lm-cross" x1={x(hov)} x2={x(hov)} y1={T} y2={H - B} />}
            {pts.map((p, i) => <rect key={"h" + p.ym} className="hit" x={x(i) - (W - L - R) / n / 2} width={(W - L - R) / n} y={0} height={H - B}
              onMouseEnter={() => setHov(i)} onMouseLeave={() => setHov(null)} onTouchStart={() => setHov(i)} />)}
          </svg>
          {h && hov !== null && (
            <div className={`lm-tip${hov > n * 0.6 ? " r" : ""}`} style={{ left: `${(x(hov) / 760) * 100}%` }}>
              <b>{h.ym.slice(0, 4)}년 {Number(h.ym.slice(4))}월</b><span>평균 {h.avg}점 · 중위 {h.med}점</span><span>최저 {h.low}점 · 최고 {h.top}점</span>
            </div>
          )}
        </div>
      )}
      <p className="caption">띠 = 그달 당첨자 최저~최고 점수, 선 = 평균. 84점 만점. 내 가점은 <a href="/me">내 프로필</a>의 청약 항목으로 계산해요.</p>
    </section>
  );
}

function CmpetRank({ d }: { d: Stats }) {
  const rows = d.cmpet_rank.slice(0, 12);
  const max = Math.max(1, ...rows.map((r) => r.rate));
  return (
    <section className="lm-card">
      <div className="eyebrow">경쟁률</div>
      <h3>최근 1년 <span className="grad">경쟁이 센 곳</span></h3>
      <ol className="lm-rank">
        {rows.map((r, i) => (
          <li key={r.area} title={`신청 ${r.req.toLocaleString()}명 / 공급 ${r.hh.toLocaleString()}세대`}>
            <span className="rk">{i + 1}</span><span className="nm">{r.area}</span>
            <span className="bar"><i style={{ width: `${(r.rate / max) * 100}%` }} /></span><b>{r.rate} : 1</b>
          </li>
        ))}
      </ol>
      <p className="caption">{d.period} 일반공급 신청자 ÷ 공급 세대 (공급 50세대 미만 지역 제외).</p>
    </section>
  );
}

function AgeBox({ d }: { d: Stats }) {
  const sum = (rows: Age[]) => {
    const last = rows.slice(-12);
    return AGES.map(([k]) => last.reduce((a, r) => a + (r[k] || 0), 0));
  };
  const req = useMemo(() => sum(d.ages.req_age), [d]);
  const win = useMemo(() => sum(d.ages.win_age), [d]);
  const tw = win.reduce((a, b) => a + b, 0) || 1;
  return (
    <section className="lm-card">
      <div className="eyebrow">연령대</div>
      <h3>당첨자 <span className="grad">나이대</span>는?</h3>
      <div className="as-ages">
        {AGES.map(([, label], i) => (
          <div key={label} className="as-age">
            <span className="lbl">{label}</span>
            <span className="bar"><i style={{ width: `${(win[i] / tw) * 100}%` }} /></span>
            <b>{Math.round((win[i] / tw) * 100)}%</b>
            <small>신청 {req[i].toLocaleString()} · 당첨 {win[i].toLocaleString()}{req[i] ? ` · 당첨 비율 ${((win[i] / req[i]) * 100).toFixed(1)}%` : ""}</small>
          </div>
        ))}
      </div>
      <p className="caption">최근 12개월 전국 아파트 청약 신청자·당첨자 수 (연령대별).</p>
    </section>
  );
}
