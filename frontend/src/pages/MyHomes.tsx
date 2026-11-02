// 관심 단지 (/my-homes) — 실거래가 화면에서 ☆로 담은 단지를 카드로 본다 (Phase 2, 2026-11-02).
// 카드: 최근 3개월 평형별 최고·최저·최근가, 직전 3개월 대비 중위가 변동률, 전세가율(같은 단지 전세 중위 ÷ 매매 중위), 관련 노트 3편.
// 단지 상세(?lawd=&dong=&apt=): 월별 중위가·거래량 차트 + 그 시군구·전국 정책 노트 표시. 자료는 저장된 실거래 표만 (/api/re/apt/summary · /re/region/trend).
// 관심 목록은 방문자 상태 re_watch — 이 브라우저에만, 구독자와 이어져 있으면 맞춤 메일에도 쓰인다. 색인하지 않는다(og_meta.NOINDEX).
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { get } from "../api";
import { Alert, useLoad } from "../components/ui";
import { useMe } from "../me";
import { type NoteBrief, type TrendRes, type Watch, SourceLine, Star, TrendChart, man, pctText, useApplyFav, useWatch, ymLabel } from "./reShared";
import "./RealEstate.css";

type Ext = { amount: number; date: string; area: number; floor: number | null };
type Band = {
  band: string; label: string; count: number; prev_count: number; max?: Ext; min?: Ext; latest?: Ext;
  median: number | null; prev_median: number | null; change_pct: number | null; jeonse_median: number | null; jeonse_count: number; jeonse_ratio: number | null;
};
type Summary = {
  lawd: string; region: string; dong: string; apt: string; bands: Band[]; main_band: string | null; change_pct: number | null; jeonse_ratio: number | null;
  recent_count: number; year_count: number; last_trade: { amount: number; date: string; area: number } | null;
  window: { recent: [string, string]; prev: [string, string] }; notes: NoteBrief[]; as_of: string | null; fetched_at: string | null; source: string;
};

const sumUrl = (w: { lawd: string; dong?: string; apt: string; jibun?: string }) =>
  `re/apt/summary?lawd=${w.lawd}&dong=${encodeURIComponent(w.dong || "")}&apt=${encodeURIComponent(w.apt)}${w.jibun ? `&jibun=${encodeURIComponent(w.jibun)}` : ""}`;
/** 카드 안 짧은 표기 — 12.41억 (정확한 값은 마우스를 올리면) */
const eok = (v: number | null | undefined) => (v === null || v === undefined ? "-" : v >= 10000 ? `${(v / 10000).toFixed(2).replace(/\.?0+$/, "")}억` : `${v.toLocaleString("ko-KR")}만`);
const Amt = ({ v }: { v: number | null | undefined }) => <span title={man(v)}>{eok(v)}</span>;
const dir = (v: number | null) => (v === null ? "" : v > 0 ? "up" : v < 0 ? "down" : "");

export default function MyHomes() {
  const { watch, update, remove } = useWatch();
  const { me } = useMe();
  const [sp, setSp] = useSearchParams();
  const sel = sp.get("apt") && /^\d{5}$/.test(sp.get("lawd") || "") ? { lawd: sp.get("lawd")!, dong: sp.get("dong") || "", apt: sp.get("apt")! } : null;
  const apts = watch.map((w, i) => [w, i] as const).filter(([w]) => w.apt);
  const regions = watch.filter((w) => !w.apt);
  const open = (w: Watch) => setSp({ lawd: w.lawd, dong: w.dong || "", apt: w.apt });

  if (!me) return <div className="page-loading">불러오는 중…</div>;
  return (
    <div className="re-page">
      <div>
        <div className="eyebrow">관심 단지</div>
        <h2 className="sec-h">내 <span className="grad">관심 단지</span></h2>
        <p className="sec-p">실거래가에서 ☆로 담은 단지의 최근 거래를 평형별로, 청약 공고에서 ☆로 담은 공고는 일정과 함께 모았습니다. 로그인하면 기기 사이에 이어지고, 맞춤 브리핑을 구독하면 월요일 메일에도 실립니다.</p>
      </div>

      <FavNotices />

      {sel && <Detail sel={sel} watched={watch.some((w) => w.lawd === sel.lawd && w.apt === sel.apt)} onClose={() => setSp({})} />}

      {!apts.length ? (
        <div className="re-box">
          <h3>아직 담아 둔 단지가 없습니다</h3>
          <p className="sec-p">실거래가 화면의 거래 목록이나 '지역 흐름'에서 단지 이름 앞의 <b>☆</b>를 누르면 여기에 카드로 모입니다. 카드에는 최근 3개월 평형별 최고·최저·최근가, 직전 3개월 대비 변동률, 전세가율, 그 단지·지역을 다룬 노트가 붙습니다.</p>
          <div className="btn-row" style={{ marginTop: 10 }}>
            <Link className="btn primary" to="/deals">실거래가에서 ☆로 담기 →</Link>
            <Link className="btn" to="/me">내 프로필 정하기</Link>
          </div>
        </div>
      ) : (
        <div className="mh-grid">
          {apts.map(([w, i]) => <Card key={`${w.lawd}-${w.dong}-${w.apt}`} w={w} onOpen={() => open(w)} onNote={(v) => update(i, { note: v })} onRemove={() => remove(i)} />)}
        </div>
      )}

      {!!regions.length && (
        <div className="re-box">
          <h3>관심 지역</h3>
          <div className="btn-row">
            {regions.map((w) => <Link key={w.lawd} className="pill" to={`/deals?lawd=${w.lawd}`}>{w.region}</Link>)}
          </div>
        </div>
      )}
    </div>
  );
}

function Card({ w, onOpen, onNote, onRemove }: { w: Watch; onOpen: () => void; onNote: (v: string) => void; onRemove: () => void }) {
  const r = useLoad(() => get<Summary>(sumUrl(w)), [w.lawd, w.dong, w.apt, w.jibun]);
  const s = r.data;
  return (
    <div className="mh-card">
      <h3>
        <Star on label={`${w.apt} 관심 단지에서 빼기`} onClick={onRemove} />
        <span>{w.apt}<small>{w.region}{w.dong ? ` ${w.dong}` : ""} · {w.added} 담음</small></span>
      </h3>
      {r.loading && !s ? <div className="caption">불러오는 중…</div> : r.error ? <Alert kind="warn">{r.error}</Alert> : s && (
        <>
          <div className="mh-kpis">
            <div className="mh-kpi"><div className="k">최근가</div><div className="v"><Amt v={s.last_trade?.amount} /></div><div className="caption">{s.last_trade ? `${s.last_trade.date.slice(2).replace(/-/g, ".")} · ${s.last_trade.area.toFixed(0)}㎡` : "거래 없음"}</div></div>
            <div className="mh-kpi"><div className="k">직전 분기 대비</div><div className={`v ${dir(s.change_pct)}`}>{pctText(s.change_pct)}</div><div className="caption">중위가 · {s.bands.find((b) => b.band === s.main_band)?.label || "-"}</div></div>
            <div className="mh-kpi"><div className="k">전세가율</div><div className="v">{s.jeonse_ratio !== null ? `${s.jeonse_ratio.toFixed(0)}%` : "-"}</div><div className="caption">{s.jeonse_ratio !== null ? "전세 중위 ÷ 매매 중위" : "전세 자료 없음"}</div></div>
          </div>
          {s.bands.length ? (
            <div className="mh-bands-wrap"><table className="mh-bands">
              <thead><tr><th>최근 3개월 평형</th><th>건수</th><th>최고</th><th>최저</th><th>최근</th><th>변동</th></tr></thead>
              <tbody>
                {s.bands.map((b) => (
                  <tr key={b.band}>
                    <td>{b.label}</td><td>{b.count}</td><td><Amt v={b.max?.amount} /></td><td><Amt v={b.min?.amount} /></td><td><Amt v={b.latest?.amount} /></td>
                    <td className={dir(b.change_pct)}>{pctText(b.change_pct)}</td>
                  </tr>
                ))}
              </tbody>
            </table></div>
          ) : <div className="re-empty">최근 6개월 거래가 없습니다.</div>}
          {!!s.notes.length && (
            <div>
              <div className="caption">이 단지·지역을 다룬 노트</div>
              <ul className="mh-notes">{s.notes.map((n) => <li key={n.id}><Link to={`/notes?id=${n.id}`}>{n.title}</Link> <span className="caption">{n.published}</span></li>)}</ul>
            </div>
          )}
          <SourceLine source={s.source} asOf={s.as_of} fetchedAt={s.fetched_at} />
        </>
      )}
      <NoteField value={w.note} onSave={onNote} />
      <div className="mh-actions">
        <button type="button" className="btn sm primary" onClick={onOpen}>추이 보기</button>
        <Link className="btn sm" to={`/deals?lawd=${w.lawd}`}>지역 실거래가</Link>
        {s?.last_trade && <Link className="btn sm" to={`/calc?price=${s.last_trade.amount}&label=${encodeURIComponent(`${w.apt} 최근가`)}`}>이 가격으로 계산하기</Link>}
      </div>
    </div>
  );
}

function NoteField({ value, onSave }: { value: string; onSave: (v: string) => void }) {
  return (
    <input type="text" defaultValue={value} maxLength={200} placeholder="메모 (예: 84㎡ 15억 이하면 검토)" aria-label="메모"
      onBlur={(e) => e.target.value !== value && onSave(e.target.value)} onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()} />
  );
}

function Detail({ sel, watched, onClose }: { sel: { lawd: string; dong: string; apt: string }; watched: boolean; onClose: () => void }) {
  const { toggle } = useWatch();
  // 평형 구간을 나눠 그린다 (59형·84형 가격이 한 선에 섞이면 오르내림이 평형 차이로 보인다) — 기본은 최근 거래가 가장 많은 평형
  const sm = useLoad(() => get<Summary>(sumUrl(sel)), [sel.lawd, sel.dong, sel.apt]);
  const [pick, setPick] = useState<string | null>(null);
  const band = pick ?? sm.data?.main_band ?? "";
  const t = useLoad(() => (sm.loading && !sm.data ? Promise.resolve(null as unknown as TrendRes) : get<TrendRes>(`re/region/trend?lawd=${sel.lawd}&dong=${encodeURIComponent(sel.dong)}&apt=${encodeURIComponent(sel.apt)}&months=24&markers=policy&band=${band}`)), [sel.lawd, sel.dong, sel.apt, band, sm.loading]);
  const bands = sm.data?.bands || [];
  const d = t.data;
  return (
    <section className="mh-detail" aria-label={`${sel.apt} 상세`}>
      <div className="re-region-h" style={{ justifyContent: "space-between" }}>
        <h3 style={{ margin: 0 }}>
          <Star on={watched} label={watched ? "관심 단지에서 빼기" : "관심 단지에 담기"} onClick={() => toggle({ lawd: sel.lawd, region: d?.region || "", dong: sel.dong, apt: sel.apt })} />
          {sel.apt} <span className="caption">{d?.region} {sel.dong}</span>
        </h3>
        <button type="button" className="btn sm ghost" onClick={onClose}>닫기</button>
      </div>
      {t.loading && !d ? <div className="page-loading">불러오는 중…</div> : t.error ? <Alert kind="err">{t.error}</Alert> : d && (
        d.total === 0 ? <div className="re-empty">최근 24개월 이 단지의 거래가 저장돼 있지 않습니다. 실거래 자료가 갱신되면 채워집니다.</div> : (
          <>
            {bands.length > 1 && (
              <div className="btn-row" role="group" aria-label="평형">
                {bands.map((b) => <button key={b.band} type="button" className={`pill ${band === b.band ? "on" : ""}`} onClick={() => setPick(b.band)}>{b.label}</button>)}
                <button type="button" className={`pill ${band === "" ? "on" : ""}`} onClick={() => setPick("")}>전체 평형</button>
              </div>
            )}
            <TrendChart points={d.points} markers={d.markers} value="median" valueLabel="중위 거래가"
              title={`${bands.find((b) => b.band === band)?.label || "전체 평형"} 월별 중위 거래가·거래량 · 최근 ${d.points.length}개월`} />
            {!!d.markers.length && (
              <ul className="re-mk-list">
                {d.markers.map((m) => m.note && <li key={m.ymd}>{ymLabel(m.ymd)} · <Link to={`/notes?id=${m.note.id}`}>{m.note.title}</Link> <span className="caption">({m.note.scope === "region" ? d.region : "전국"} 정책)</span></li>)}
              </ul>
            )}
            <p className="calc-note">표시는 이 시군구 또는 전국 단위 정책 노트의 게시 달입니다. 노트가 가격 변화의 원인이라는 뜻은 아닙니다.</p>
            <SourceLine source={d.source} asOf={d.as_of} fetchedAt={d.fetched_at} />
          </>
        )
      )}
    </section>
  );
}

type FavN = { notice_id: string; name: string; region: string; receipt_start: string | null; receipt_end: string | null; winner_date: string | null; url: string };

/** 청약 공고에서 ☆로 담은 관심 공고 (방문자 상태 apply_fav — 2026-11-02) */
function FavNotices() {
  const { state } = useMe();
  const fav = useApplyFav();
  const ids = Array.isArray(state.apply_fav) ? (state.apply_fav as string[]) : [];
  const { data } = useLoad(() => (ids.length ? get<{ apply: FavN[]; apply_fav: string[] }>("me/space") : Promise.resolve(null)), [ids.join(",")]);
  const rows = (data?.apply || []).filter((n) => ids.includes(n.notice_id));
  if (!ids.length) return null;
  const dd = (s: string | null) => (s ? Math.ceil((new Date(s + "T00:00:00").getTime() - new Date(new Date().toDateString()).getTime()) / 86400000) : null);
  const md = (s: string | null) => (s ? `${Number(s.slice(5, 7))}.${Number(s.slice(8, 10))}` : "-");
  return (
    <div className="re-box">
      <div className="re-list-h"><h3>관심 청약 공고 {ids.length}</h3><Link to="/deals?tab=apply">청약 공고 →</Link></div>
      <ul className="ap-cards">
        {rows.map((n) => {
          const d = dd(n.receipt_start || n.receipt_end);
          return (
            <li key={n.notice_id}>
              <div className="ap-card">
                <Star on={fav.has(n.notice_id)} label={`${n.name} 관심 공고 빼기`} onClick={() => fav.toggle(n.notice_id)} />
                <div className="ap-card-b">
                  <a className="ap-card-t" href={n.url || "#"} target="_blank" rel="noopener">{n.name}</a>
                  <div className="ap-card-m">
                    {d !== null && <span className={`ap-dd${d >= 0 && d <= 3 ? " hot" : ""}`}>{d < 0 ? "지남" : d === 0 ? "오늘" : `D-${d}`}</span>}
                    <span className="ap-chip">{n.region}</span>
                    <span className="ap-when">접수 {md(n.receipt_start)}~{md(n.receipt_end)}{n.winner_date ? ` · 발표 ${md(n.winner_date)}` : ""}</span>
                  </div>
                </div>
              </div>
            </li>
          );
        })}
        {!rows.length && <li className="caption">불러오는 중…</li>}
      </ul>
    </div>
  );
}
