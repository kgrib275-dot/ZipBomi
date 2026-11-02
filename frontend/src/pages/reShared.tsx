// 관심 단지·지역 드릴다운 공용 조각 (Phase 2) — 관심 목록 저장(re_watch), 금액 표기, 월별 추이 차트(가격 선 + 거래량 막대 + 노트 표시).
// 차트는 축을 하나만 쓴다: 위 칸 = 가격(선), 아래 칸 = 거래량(막대), 가로축(월)만 같이 쓴다.
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useMe } from "../me";

export type Watch = { lawd: string; region: string; dong?: string; apt: string; jibun?: string; area_band?: string; note: string; added: string };
export type NoteBrief = { id: number; title: string; summary: string; category: string; kind: string; published: string; scope: "region" | "national" };
export type Marker = { ymd: string; kind: "volume" | "policy"; change_pct?: number; note: NoteBrief | null };
export type TrendPoint = { ymd: string; count: number; avg_pyeong: number | null; median: number | null; partial?: boolean; missing?: boolean };
export type TrendRes = {
  lawd: string; region: string; dong: string; apt: string; level: "sigungu" | "dong" | "apt";
  points: TrendPoint[]; children: { name: string; count: number; avg_pyeong: number | null; dong: string; jibun: string }[];
  markers: Marker[]; total: number; as_of: string | null; fetched_at: string | null; source: string; rule: string;
};

export const SOURCE_FALLBACK = "국토교통부 실거래가 신고 자료";

/** 만원 → '12억 3,400만원' */
export function man(v: number | null | undefined): string {
  if (v === null || v === undefined || !isFinite(v)) return "-";
  const n = Math.round(v);
  const eok = Math.floor(Math.abs(n) / 10000);
  const rest = Math.abs(n) % 10000;
  const sign = n < 0 ? "-" : "";
  if (!eok) return `${sign}${rest.toLocaleString("ko-KR")}만원`;
  return `${sign}${eok}억${rest ? ` ${rest.toLocaleString("ko-KR")}만` : ""}원`;
}
/** 짧은 억 표기 (차트 눈금) */
export const eokShort = (v: number) => (v >= 10000 ? `${(v / 10000).toFixed(v >= 100000 ? 0 : 1)}억` : `${Math.round(v).toLocaleString("ko-KR")}만`);
export const ymLabel = (ymd: string) => `${ymd.slice(0, 4)}.${ymd.slice(4)}`;
export const pctText = (v: number | null | undefined) => (v === null || v === undefined ? "-" : `${v > 0 ? "+" : ""}${v.toFixed(1)}%`);

/** 기준일 줄 — "국토교통부 실거래가 신고 자료 · 2026-11-01 계약분까지 · 2026-11-02 기준" */
export function SourceLine({ source, asOf, fetchedAt }: { source?: string; asOf?: string | null; fetchedAt?: string | null }) {
  return (
    <p className="calc-note re-src">
      출처: {source || SOURCE_FALLBACK}
      {asOf ? ` · ${asOf} 계약분까지` : ""}
      {fetchedAt ? ` · ${fetchedAt.slice(0, 10)} 기준` : ""}
    </p>
  );
}

/** 관심 단지 목록 — 방문자 상태 re_watch (구독자와 이어진 브라우저면 서버가 구독자 사본에도 맞춘다). */
export function useWatch() {
  const { state, setState } = useMe();
  const watch: Watch[] = useMemo(() => (Array.isArray(state.re_watch) ? (state.re_watch as Watch[]) : []), [state.re_watch]);
  const same = (w: Watch, lawd: string, apt: string, dong = "") => w.lawd === lawd && w.apt === apt && (!apt || !dong || !w.dong || w.dong === dong);
  const has = (lawd: string, apt: string, dong = "") => watch.some((w) => same(w, lawd, apt, dong));
  const toggle = (x: { lawd: string; region: string; apt: string; dong?: string; jibun?: string }) => {
    const next = has(x.lawd, x.apt, x.dong)
      ? watch.filter((w) => !same(w, x.lawd, x.apt, x.dong))
      : [...watch, { lawd: x.lawd, region: x.region, dong: x.dong || "", apt: x.apt, ...(x.jibun ? { jibun: x.jibun } : {}), note: "", added: new Date().toLocaleDateString("sv-SE") }].slice(-50);
    setState({ re_watch: next });
  };
  const update = (i: number, patch: Partial<Watch>) => setState({ re_watch: watch.map((w, j) => (j === i ? { ...w, ...patch } : w)) });
  const remove = (i: number) => setState({ re_watch: watch.filter((_, j) => j !== i) });
  return { watch, has, toggle, update, remove };
}

const SIZES = [10, 20, 50, 100];
const lsGet = (k: string) => { try { return localStorage.getItem(k); } catch { return null; } };
const lsSet = (k: string, v: string) => { try { localStorage.setItem(k, v); } catch { /* 저장 못 해도 동작 */ } };

/** 목록 표시 개수 — 화면마다 따로, 이 브라우저에 기억 (2026-11-02) */
export function usePageSize(key: string, def = 20): [number, (n: number) => void] {
  const [n, setN] = useState<number>(() => { const v = Number(lsGet(`zg-size-${key}`)); return SIZES.includes(v) ? v : def; });
  return [n, (v: number) => { setN(v); lsSet(`zg-size-${key}`, String(v)); }];
}

/** 목록 위쪽 — 건수 옆 표시 개수 고르기 */
export function SizeSel({ size, setSize, setPage }: { size: number; setSize: (n: number) => void; setPage: (p: number) => void }) {
  return (
    <select className="size-sel" value={size} onChange={(e) => { setSize(Number(e.target.value)); setPage(0); }} aria-label="한 쪽에 보일 개수">
      {SIZES.map((n) => <option key={n} value={n}>{n}개씩</option>)}
    </select>
  );
}

/** 목록 아래쪽 — 쪽 넘기기 (한 쪽뿐이면 그리지 않는다) */
export function Pager({ page, pages, setPage }: { page: number; pages: number; setPage: (p: number) => void }) {
  if (pages <= 1) return null;
  return (
    <div className="re-pager">
      {<>
        <button type="button" className="btn sm" disabled={page === 0} onClick={() => setPage(0)} aria-label="처음">«</button>
        <button type="button" className="btn sm" disabled={page === 0} onClick={() => setPage(page - 1)}>이전</button>
        <span className="caption">{page + 1} / {pages}</span>
        <button type="button" className="btn sm" disabled={page >= pages - 1} onClick={() => setPage(page + 1)}>다음</button>
        <button type="button" className="btn sm" disabled={page >= pages - 1} onClick={() => setPage(pages - 1)} aria-label="끝">»</button>
      </>}
    </div>
  );
}

/** 관심 공고 — 방문자 상태 apply_fav (로그인하면 기기 사이 공유). 예전 브라우저 저장분은 처음 한 번 옮긴다 */
export function useApplyFav(): { has: (id: string) => boolean; toggle: (id: string) => void; size: number } {
  const { me, state, setState } = useMe();
  const ids = useMemo(() => (Array.isArray(state.apply_fav) ? (state.apply_fav as unknown[]).filter((x): x is string => typeof x === "string") : []), [state.apply_fav]);
  useEffect(() => {
    if (!me) return;
    try {
      const old = JSON.parse(lsGet("zg-apply-fav") || "[]");
      if (Array.isArray(old) && old.length) { setState({ apply_fav: [...new Set([...ids, ...old.filter((x) => typeof x === "string")])].slice(0, 100) }); localStorage.removeItem("zg-apply-fav"); }
    } catch { /* 무시 */ }
  }, [me]); // eslint-disable-line react-hooks/exhaustive-deps
  return {
    has: (id) => ids.includes(id),
    toggle: (id) => setState({ apply_fav: ids.includes(id) ? ids.filter((x) => x !== id) : [id, ...ids].slice(0, 100) }),
    size: ids.length,
  };
}

export function Star({ on, label, onClick }: { on: boolean; label: string; onClick: () => void }) {
  return (
    <button type="button" className={`re-star ${on ? "on" : ""}`} aria-label={label} aria-pressed={on} title={on ? "관심 목록에서 빼기" : "관심 목록에 저장"} onClick={onClick}>
      {on ? "★" : "☆"}
    </button>
  );
}

/** 그래프 위 값 표시 — SVG 안에는 세로선·점만, 글자 상자(TipBox)는 HTML 로 띄워 휴대폰에서 그래프가 줄어도 글자 크기가 그대로다. */
export function ChartTip({ x, y, top, bottom }: { x: number; y: number | null; top: number; bottom: number }) {
  return (
    <g className="ctip" pointerEvents="none">
      <line x1={x} x2={x} y1={top} y2={bottom} />
      {y !== null && <circle cx={x} cy={y} r={6} />}
    </g>
  );
}

/** ChartTip 의 글자 상자 — 그래프를 감싼 position:relative 상자 안에서 SVG 좌표(x/W, y/H)를 % 로 바꿔 둔다. */
export function TipBox({ x, y, W, H, lines }: { x: number; y: number | null; W: number; H: number; lines: string[] }) {
  const left = (x / W) * 100;
  const top = ((y ?? H * 0.3) / H) * 100;
  return (
    <div className={`ctip-box${left > 60 ? " r" : left < 40 ? " l" : ""}`} style={{ left: `${left}%`, top: `${top}%` }} aria-hidden="true">
      {lines.map((l, i) => <div key={i} className={i ? "" : "b"}>{l}</div>)}
    </div>
  );
}

/** 월별 추이 — 위: 가격 선(value), 아래: 거래량 막대, 노트 표시(세로 점선 + 동그라미, 누르면 노트 요약). */
export function TrendChart({ points, markers, value, valueLabel, title }: {
  points: TrendPoint[]; markers: Marker[]; value: "avg_pyeong" | "median"; valueLabel: string; title: string;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const W = 680, L = 46, R = 14, T = 22, PH = 150, GAP = 22, VH = 70, B = 24;
  const H = T + PH + GAP + VH + B;
  const n = points.length;
  const vals = points.map((p) => p[value]).filter((v): v is number => v !== null);
  if (n < 2 || !vals.length) return <div className="re-empty">추이를 그릴 만큼 거래가 쌓이지 않았습니다.</div>;
  const lo = Math.min(...vals), hi = Math.max(...vals);
  const pad = (hi - lo) * 0.12 || hi * 0.05 || 1;
  const vlo = lo - pad, vhi = hi + pad;
  const cmax = Math.max(1, ...points.map((p) => p.count));
  const step = (W - L - R) / n;
  const cx = (i: number) => L + step * (i + 0.5);
  const y = (v: number) => T + (1 - (v - vlo) / (vhi - vlo)) * PH;
  const vy0 = T + PH + GAP + VH;
  const bh = (c: number) => (c / cmax) * VH;
  const segs: string[] = [];
  let cur = "";
  points.forEach((p, i) => {
    const v = p[value];
    if (v === null) { if (cur) segs.push(cur); cur = ""; return; }
    cur += `${cur ? "L" : "M"}${cx(i).toFixed(1)},${y(v).toFixed(1)}`;
  });
  if (cur) segs.push(cur);
  const idxOf = (ymd: string) => points.findIndex((p) => p.ymd === ymd);
  const shown = markers.filter((m) => idxOf(m.ymd) >= 0);
  const openM = shown.find((m) => m.ymd === open) || null;
  const hp = hover !== null ? points[hover] : null;
  const ticks = [vlo + (vhi - vlo) * 0.15, (vlo + vhi) / 2, vhi - (vhi - vlo) * 0.15];
  return (
    <div className="re-chart">
      <div className="re-chart-head">
        <b>{title}</b>
        <span className="caption" aria-live="polite">
          {hp ? `${ymLabel(hp.ymd)} · ${valueLabel} ${man(hp[value])} · 거래 ${hp.count}건${hp.partial ? " (신고 진행 중)" : ""}` : "막대·점에 올리면 달별 값이 보입니다"}
        </span>
      </div>
      <div className="re-chart-wrap">
        <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${title}: ${ymLabel(points[0].ymd)}부터 ${ymLabel(points[n - 1].ymd)}까지 월별 ${valueLabel}와 거래량`}>
          {ticks.map((t) => (
            <g key={t}>
              <line className="grid" x1={L} x2={W - R} y1={y(t)} y2={y(t)} />
              <text x={L - 6} y={y(t) + 4} textAnchor="end">{eokShort(t)}</text>
            </g>
          ))}
          <text x={L} y={12} className="axis-t">{valueLabel}</text>
          <text x={L} y={T + PH + GAP - 6} className="axis-t">거래량(건)</text>
          <line className="base" x1={L} x2={W - R} y1={vy0} y2={vy0} />
          {shown.map((m) => {
            const x = cx(idxOf(m.ymd));
            return <line key={"ml" + m.ymd} className="mk-line" x1={x} x2={x} y1={T} y2={vy0} />;
          })}
          {/* 아직 받지 못한 달 — 옅은 띠로 '자료 없음' 표시 (거래 0건과 구분) */}
          {points.map((p, i) => p.missing && <rect key={"m" + p.ymd} className="miss" x={L + step * i} width={step} y={T} height={vy0 - T} />)}
          {points.map((p, i) => (
            <rect key={"b" + p.ymd} className={`bar${p.partial ? " partial" : ""}${hover === i ? " on" : ""}`} x={cx(i) - Math.min(step * 0.32, 12)} width={Math.min(step * 0.64, 24)}
              y={vy0 - bh(p.count)} height={Math.max(bh(p.count), p.count ? 2 : 0)} rx={3} />
          ))}
          {segs.map((d, i) => <path key={i} className="ln" d={d} />)}
          {points.map((p, i) => p[value] !== null && <circle key={"d" + p.ymd} className="dot" cx={cx(i)} cy={y(p[value] as number)} r={hover === i ? 5 : 3.5} />)}
          {points.map((p, i) => (i === 0 || i === n - 1 || i % 3 === 0) && (
            <text key={"x" + p.ymd} x={cx(i)} y={H - 6} textAnchor="middle">{`${p.ymd.slice(2, 4)}.${p.ymd.slice(4)}`}</text>
          ))}
          {/* 달마다 넓은 투명 칸 — 마우스·터치 대상이 막대보다 크게 */}
          {points.map((p, i) => (
            <rect key={"h" + p.ymd} className="hit" x={L + step * i} width={step} y={T} height={vy0 - T}
              onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)} onClick={() => setHover(i)} onTouchStart={() => setHover(i)}>
              <title>{`${ymLabel(p.ymd)} ${valueLabel} ${man(p[value])} · 거래 ${p.count}건`}</title>
            </rect>
          ))}
          {hp && hover !== null && (
            <ChartTip x={cx(hover)} y={hp[value] !== null ? y(hp[value] as number) : null} top={T} bottom={vy0} />
          )}
          {shown.map((m) => {
            const x = cx(idxOf(m.ymd));
            return (
              <g key={"m" + m.ymd} className={`mk${open === m.ymd ? " on" : ""}${m.note ? "" : " empty"}`} role="button" tabIndex={0}
                aria-label={`${ymLabel(m.ymd)} 노트 표시${m.note ? `: ${m.note.title}` : ""}`}
                onClick={() => setOpen(open === m.ymd ? null : m.ymd)} onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && setOpen(open === m.ymd ? null : m.ymd)}>
                <circle cx={x} cy={T - 4} r={9} />
                <text x={x} y={T} textAnchor="middle">{m.kind === "policy" ? "정" : m.change_pct && m.change_pct > 0 ? "▲" : "▼"}</text>
              </g>
            );
          })}
        </svg>
        {hp && hover !== null && (
          <TipBox x={cx(hover)} y={hp[value] !== null ? y(hp[value] as number) : null} W={W} H={H}
            lines={hp.missing ? [ymLabel(hp.ymd), "아직 받지 못한 달", "자료를 채우는 중이에요"] : [ymLabel(hp.ymd), `${valueLabel} ${man(hp[value])}`, `거래 ${hp.count}건${hp.partial ? " (신고 중)" : ""}`]} />
        )}
        {openM && (
          <div className="re-pop" role="dialog" aria-label={`${ymLabel(openM.ymd)} 노트`}
            style={{ left: `${Math.min(Math.max((cx(idxOf(openM.ymd)) / W) * 100, 18), 82)}%` }}>
            <button type="button" className="x" aria-label="닫기" onClick={() => setOpen(null)}>×</button>
            <div className="k">
              {ymLabel(openM.ymd)}
              {openM.kind === "volume" && openM.change_pct !== undefined ? ` · 거래량 전월 대비 ${pctText(openM.change_pct)}` : " · 정책 노트"}
            </div>
            {openM.note ? (
              <>
                <b>{openM.note.title}</b>
                <p>{openM.note.summary}</p>
                <div className="caption">{openM.note.published} · {openM.note.category} · {openM.note.scope === "region" ? "이 지역 노트" : "전국 정책 노트"}</div>
                <Link className="re-link" to={`/notes?id=${openM.note.id}`}>노트 읽기 →</Link>
              </>
            ) : <p className="caption">이 달에 이 지역을 다룬 노트나 전국 정책 노트가 아직 없습니다.</p>}
          </div>
        )}
      </div>
      <div className="re-legend caption">
        <span><i className="sw ln" />{valueLabel}</span>
        <span><i className="sw bar" />거래량</span>
        <span><i className="sw bar partial" />신고 진행 중(계약 후 30일 안)</span>
        {!!shown.length && <span><i className="sw mk" />노트 표시 — 눌러서 보기</span>}
      </div>
    </div>
  );
}
