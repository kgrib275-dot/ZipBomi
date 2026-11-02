// 데이터 랩 — 시·도 상세 (영업용, 2026-11-02). GET /api/lab/region?sido=11|41|26|28 (backend/api/routers/lab.py).
// 시군구 표(거래량·3.3㎡가·상승률·전세가율·월세 비중·평형별 중위가, 정렬), 최근 신고가, 거래 활발 단지, 고객 안내 문구 복사·CSV 내려받기.
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { get } from "../api";
import { useLoad } from "../components/ui";
import { man } from "../policy";

type Dist = { lawd: string; name: string; deals: number; pp: number; chg: number | null; jeonse_ratio: number | null; monthly_share: number | null; s: number | null; m: number | null; l: number | null };
type Res = { sido: string; recent: string[]; districts: Dist[];
  hot: { lawd: string; region: string; umd: string; name: string; deals: number; median: number; pp: number }[];
  highs: { lawd: string; region: string; umd: string; name: string; area: number; floor: number | null; amount: number; prev: number; pct: number; date: string }[];
  n_highs: number; source: string };
const SIDOS: [string, string][] = [["11", "서울"], ["41", "경기"], ["26", "부산"], ["28", "인천"]];
const COLS: [keyof Dist, string][] = [["deals", "거래"], ["pp", "3.3㎡ 중위"], ["chg", "상승률"], ["jeonse_ratio", "전세가율"], ["monthly_share", "월세 비중"], ["s", "60㎡↓"], ["m", "60~85㎡"], ["l", "85㎡↑"]];
const ymL = (s: string) => `${s.slice(2, 4)}.${s.slice(4)}`;

export default function LabRegion() {
  const [sido, setSido] = useState(() => { try { return localStorage.getItem("zg-lab-sido") || "11"; } catch { return "11"; } });
  const pickSido = (v: string) => { setSido(v); try { localStorage.setItem("zg-lab-sido", v); } catch { /* 무시 */ } };
  const { data, loading, error } = useLoad(() => get<Res>(`lab/region?sido=${sido}`), [sido]);
  const [sort, setSort] = useState<keyof Dist>("pp");
  const [desc, setDesc] = useState(true);
  const [copied, setCopied] = useState("");
  const rows = useMemo(() => [...(data?.districts || [])].sort((a, b) => (desc ? 1 : -1) * (((b[sort] as number) ?? -1e9) - ((a[sort] as number) ?? -1e9))), [data, sort, desc]);
  const max = (k: keyof Dist) => Math.max(1, ...rows.map((r) => Math.abs((r[k] as number) ?? 0)));
  const fmt = (k: keyof Dist, v: number | null) => v === null || v === undefined ? "-" : k === "deals" ? v.toLocaleString() : k === "chg" ? `${v > 0 ? "+" : ""}${v}%`
    : k === "jeonse_ratio" || k === "monthly_share" ? `${v}%` : man(v);
  const sortBy = (k: keyof Dist) => { if (k === sort) setDesc(!desc); else { setSort(k); setDesc(true); } };
  const period = data ? `${ymL(data.recent[0])}~${ymL(data.recent[data.recent.length - 1])}` : "";
  const copyBrief = async (d: Dist) => {
    const txt = `[${data?.sido} ${d.name} 아파트 시장 요약 · ${period} 실거래 기준]\n` +
      `· 거래 ${d.deals.toLocaleString()}건, 3.3㎡당 중위 ${man(d.pp)}${d.chg !== null ? ` (직전 3개월 대비 ${d.chg > 0 ? "+" : ""}${d.chg}%)` : ""}\n` +
      `· 평형별 중위 매매가: 60㎡ 이하 ${d.s ? man(d.s) : "-"} / 60~85㎡ ${d.m ? man(d.m) : "-"} / 85㎡ 초과 ${d.l ? man(d.l) : "-"}\n` +
      `· 전세가율 ${d.jeonse_ratio ?? "-"}%, 전월세 중 월세 비중 ${d.monthly_share ?? "-"}%\n` +
      `출처: 국토교통부 실거래가 공개 자료 (집보미 정리)`;
    try { await navigator.clipboard.writeText(txt); setCopied(d.lawd); window.setTimeout(() => setCopied(""), 2000); } catch { window.prompt("복사해 쓰세요", txt); }
  };
  const csv = () => {
    const head = ["시군구", ...COLS.map(([, l]) => l)];
    const lines = [head, ...rows.map((r) => [r.name, ...COLS.map(([k]) => String(r[k] ?? ""))])].map((x) => x.map((v) => `"${String(v).replace(/"/g, '""')}"`).join(","));
    const blob = new Blob(["﻿" + lines.join("\n")], { type: "text/csv;charset=utf-8" });
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = `집보미_${data?.sido}_시군구_${period}.csv`; a.click(); URL.revokeObjectURL(a.href);
  };
  return (
    <section className="lm-card lr">
      <div className="lm-h">
        <div><div className="eyebrow">지역 상세 · 영업용</div><h3><span className="grad">{data?.sido || ""}</span> 시군구 한눈에</h3></div>
        <div className="lm-ctl">
          <div className="seg sm">{SIDOS.map(([v, l]) => <button key={v} type="button" className={sido === v ? "on" : ""} onClick={() => pickSido(v)}>{l}</button>)}</div>
          <button type="button" className="pill sm" onClick={csv} disabled={!rows.length}>⬇ CSV</button>
        </div>
      </div>
      {error ? <p className="caption">불러오지 못했어요. 잠시 뒤 새로고침해 주세요.</p> : loading && !data ? <div className="lm-skel sm" /> : data && (
        <>
          <p className="caption" style={{ marginTop: 0 }}>최근 3개월({period}) 아파트 매매·전월세 실거래. 열 이름을 누르면 정렬, 행의 📋는 고객 안내용 요약을 복사해요.</p>
          <div className="table-wrap lr-table">
            <table className="table">
              <thead><tr><th>시군구</th>{COLS.map(([k, l]) => <th key={k} className="num"><button type="button" className={`lr-th${sort === k ? " on" : ""}`} onClick={() => sortBy(k)}>{l}{sort === k ? (desc ? " ↓" : " ↑") : ""}</button></th>)}<th /></tr></thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.lawd}>
                    <td><Link to={`/deals?lawd=${r.lawd}`}><b>{r.name}</b></Link></td>
                    {COLS.map(([k]) => {
                      const v = r[k] as number | null;
                      return (
                        <td key={k} className="num">
                          <span className={`lr-v${k === "chg" && v !== null ? (v > 0 ? " up" : v < 0 ? " down" : "") : ""}`}>{fmt(k, v)}</span>
                          {(k === "pp" || k === "deals" || k === "jeonse_ratio") && v !== null && <span className="lr-bar"><i style={{ width: `${(Math.abs(v) / max(k)) * 100}%` }} /></span>}
                        </td>
                      );
                    })}
                    <td><button type="button" className="lr-copy" onClick={() => copyBrief(r)} title="고객 안내 요약 복사">{copied === r.lawd ? "✓" : "📋"}</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="lm-two" style={{ marginTop: 12 }}>
            <div>
              <h4 className="lr-h">🔥 최근 신고가 <small>{data.n_highs.toLocaleString()}건 중 최근 25건</small></h4>
              <ul className="lr-list">
                {data.highs.map((h, i) => (
                  <li key={i}><Link to={`/deals?lawd=${h.lawd}`} className="nm">{h.name}</Link>
                    <span className="meta">{h.region} {h.umd} · {h.area}㎡{h.floor ? ` ${h.floor}층` : ""} · {h.date.slice(5).replace("-", ".")}</span>
                    <b>{man(h.amount)}</b><span className="up">+{h.pct}%</span></li>
                ))}
              </ul>
              <p className="caption">최근 2개월 거래 중 같은 단지·같은 평형(전용 ±3㎡)의 이전 24개월 최고가를 넘은 거래.</p>
            </div>
            <div>
              <h4 className="lr-h">📈 거래 활발 단지 <small>최근 3개월</small></h4>
              <ol className="lr-list">
                {data.hot.map((h, i) => (
                  <li key={i}><span className="rk">{i + 1}</span><Link to={`/deals?lawd=${h.lawd}`} className="nm">{h.name}</Link>
                    <span className="meta">{h.region} {h.umd} · 3.3㎡ {man(h.pp)}</span><b>{h.deals}건</b><span className="meta">중위 {man(h.median)}</span></li>
                ))}
              </ol>
            </div>
          </div>
          <p className="caption">출처: {data.source}. 해제 신고 제외. 전세가율 = 전세(월세 없는 계약) 3.3㎡ 보증금 중위 ÷ 매매 3.3㎡ 중위.</p>
        </>
      )}
    </section>
  );
}
