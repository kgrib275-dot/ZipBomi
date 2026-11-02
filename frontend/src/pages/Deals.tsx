// 실거래가 (/deals) — 국토교통부 아파트 매매 실거래가를 시군구·년월로 본다 (backend /api/re/*, DB 캐시).
// 2026-11: 데이터셋 선택(매매/전월세 × 아파트·연립다세대·단독다가구·오피스텔, 분양권, 토지, 상업업무용 — 배치가 저장한 DB, /api/re/data)과
// '청약 공고' 탭(/api/re/apply — 청약홈 + LH)을 더했다. 아파트 매매는 예전 화면(/api/re/deals) 그대로.
// 관심 목록(★)은 방문자 상태 re_watch 에 저장 — 이 브라우저(쿠키)에게만 보이는 개인 메모다.
// 키(DATA_GO_KR_KEY)가 없으면 숫자를 지어내지 않고 안내만 보여 준다 — 단, 저장된 자료(배치·파일 업로드)가 있는 시군구는 DB 로 보여 준다.
// 2026-11-02 Phase 2: ☆ 관심 단지(re_watch: lawd·dong·apt·jibun) → /my-homes, '지역 흐름' 드릴다운(시군구 → 동 → 단지, 거래량 ±30% 달에 노트 표시).
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { get } from "../api";
import { Alert, useLoad } from "../components/ui";
import { useMe } from "../me";
import { ApplyTab, DataPending, DatasetPicker, DatasetView } from "./DealsData";
import { type TrendRes as DrillRes, type Watch, ChartTip, Pager, SizeSel, SourceLine, Star, TipBox, TrendChart, usePageSize, pctText, useWatch, ymLabel } from "./reShared";
import "./RealEstate.css";

type Region = { code: string; name: string };
type RegionsRes = { configured: boolean; groups: { sido: string; items: Region[] }[]; default_ymd: string };
type Row = {
  apt: string; dong: string; jibun: string; apt_dong: string; area: number; floor: number | null; amount: number;
  date: string; build_year: number | null; deal_type: string; cancelled: boolean; cancel_day: string;
};
type Extreme = { amount: number; apt: string; area: number; date: string };
type Summary = {
  count: number; cancelled: number; median?: number; avg_m2?: number; avg_pyeong?: number; median_pyeong?: number;
  max?: Extreme; min?: Extreme; top_apts?: { apt: string; dong: string; count: number; median: number; median_pyeong: number }[];
};
type DealsRes = { configured: boolean; lawd: string; region: string; ymd: string; fetched_at?: string; summary?: Summary; rows?: Row[] };
type Point = { ymd: string; median_pyeong: number | null; count: number | null };
type TrendRes = { configured: boolean; points?: Point[]; partial?: boolean };

const LS = "zipgenie-deals";
const PYEONG = 3.305785; // 1평 = 3.305785㎡ (서버와 같은 값)
const PAGE = 20;
const AREAS = [
  { k: "all", label: "전체" },
  { k: "s", label: "60㎡ 이하 (59형)" },
  { k: "m", label: "60~85㎡ (84형)" },
  { k: "l", label: "85㎡ 초과 (대형)" },
];
const SORTS = [
  { k: "new", label: "최신순" },
  { k: "high", label: "가격 높은순" },
  { k: "low", label: "가격 낮은순" },
  { k: "pp", label: "3.3㎡당 높은순" },
];

/** 만원 → '12억 3,400만원' (억 아래는 만원 단위로) */
function man(v: number | null | undefined): string {
  if (v === null || v === undefined || !isFinite(v)) return "-";
  const n = Math.round(v);
  const eok = Math.floor(Math.abs(n) / 10000);
  const rest = Math.abs(n) % 10000;
  const sign = n < 0 ? "-" : "";
  if (!eok) return `${sign}${rest.toLocaleString("ko-KR")}만원`;
  return `${sign}${eok}억${rest ? ` ${rest.toLocaleString("ko-KR")}만` : ""}원`;
}

function loadLS(): Record<string, string> {
  try {
    const v = JSON.parse(localStorage.getItem(LS) || "{}");
    return v && typeof v === "object" ? v : {};
  } catch {
    return {};
  }
}

function lastMonth(): string {
  const d = new Date();
  d.setDate(1);
  d.setMonth(d.getMonth() - 1);
  return `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, "0")}`;
}
const thisMonthInput = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
};
const ymdLabel = (ymd: string) => `${ymd.slice(0, 4)}년 ${Number(ymd.slice(4))}월`;
const pp = (r: Row) => (r.amount / r.area) * PYEONG;

/** ?lawd=11680&ymd=202610 — 지도·공유 링크에서 바로 그 지역·달을 연다 (저장된 값보다 우선) */
function queryInit(): { lawd?: string; ymd?: string } {
  const sp = new URLSearchParams(window.location.search);
  const lawd = sp.get("lawd") || "";
  const ymd = (sp.get("ymd") || "").replace("-", "");
  return { lawd: /^\d{5}$/.test(lawd) ? lawd : undefined, ymd: /^\d{6}$/.test(ymd) ? ymd : undefined };
}

export default function Deals() {
  const saved = useMemo(loadLS, []);
  const qs = useMemo(queryInit, []);
  const regions = useLoad(() => get<RegionsRes>("re/regions"), []);
  const [sido, setSido] = useState(saved.sido || "서울");
  const [lawd, setLawd] = useState(qs.lawd || saved.lawd || "11680");
  const [ymd, setYmd] = useState(qs.ymd || (/^\d{6}$/.test(saved.ymd || "") ? saved.ymd : lastMonth()));
  const [area, setArea] = useState(saved.area || "all");
  const [sort, setSort] = useState(saved.sort || "new");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(0);
  const [size, setSize] = usePageSize("deals");
  const [favOnly, setFavOnly] = useState(false);
  // ?tab=apply 로 바로 '청약 공고' 탭을 열 수 있다 (공유 링크)
  const [tab, setTab] = useState<"deals" | "apply">(() => {
    const t = new URLSearchParams(window.location.search).get("tab") || saved.tab;
    return t === "apply" && !qs.lawd ? "apply" : "deals";
  });
  const [ds, setDs] = useState(/^[a-z_]{3,30}$/.test(saved.ds || "") ? saved.ds : "apt_trade");
  const { me } = useMe();
  const isAdmin = !!me?.is_admin;
  const W = useWatch();
  const watch = W.watch;
  // 키가 없어도 저장된 아파트 매매 자료가 있는 시군구 (파일 업로드·지난 배치) — 있으면 DB 로 보여 준다
  const stored = useLoad(() => get<{ lawds: string[] }>("re/stored"), []);
  const storedMode = !regions.data?.configured && !!stored.data?.lawds.length;

  // 마지막으로 고른 값 기억 — 다음에 들어오면 같은 지역·달부터
  useEffect(() => {
    try {
      localStorage.setItem(LS, JSON.stringify({ sido, lawd, ymd, area, sort, tab, ds }));
    } catch { /* 저장소를 못 쓰면 기억만 안 한다 */ }
  }, [sido, lawd, ymd, area, sort, tab, ds]);

  const groups = regions.data?.groups || [];
  // 링크로 받은 시군구에 맞춰 시도 선택도 맞춘다 (지역 목록이 온 뒤 한 번)
  useEffect(() => {
    if (!qs.lawd || !regions.data) return;
    const g = regions.data.groups.find((x) => x.items.some((it) => it.code === qs.lawd));
    if (g) setSido(g.sido);
  }, [qs.lawd, regions.data]);
  const configured = regions.data?.configured;
  const sidoItems = groups.find((g) => g.sido === sido)?.items || [];
  const regionName = (code: string) => {
    for (const g of groups) for (const it of g.items) if (it.code === code) return `${g.sido} ${it.name}`;
    return code;
  };

  // 키가 있을 때만 조회 — 없으면 서버도 빈 응답이라 부를 필요가 없다
  const isApt = tab === "deals" && ds === "apt_trade";
  const deals = useLoad<DealsRes | null>(() => (configured && isApt ? get<DealsRes>(`re/deals?lawd=${lawd}&ymd=${ymd}`) : Promise.resolve(null)), [lawd, ymd, configured, isApt]);
  const trend = useLoad<TrendRes | null>(() => (configured && isApt ? get<TrendRes>(`re/deals/trend?lawd=${lawd}&ymd=${ymd}&months=12`) : Promise.resolve(null)), [lawd, ymd, configured, isApt]);

  useEffect(() => setPage(0), [lawd, ymd, area, sort, q, favOnly]);

  const rows = useMemo(() => {
    let rs = deals.data?.rows || [];
    const qq = q.trim().replace(/\s+/g, "").toLowerCase();
    if (qq) rs = rs.filter((r) => (r.apt + r.dong).replace(/\s+/g, "").toLowerCase().includes(qq));
    if (favOnly) rs = rs.filter((r) => W.has(lawd, r.apt, r.dong));
    if (area === "s") rs = rs.filter((r) => r.area <= 60);
    else if (area === "m") rs = rs.filter((r) => r.area > 60 && r.area <= 85);
    else if (area === "l") rs = rs.filter((r) => r.area > 85);
    const cmp: Record<string, (a: Row, b: Row) => number> = {
      new: (a, b) => b.date.localeCompare(a.date),
      high: (a, b) => b.amount - a.amount,
      low: (a, b) => a.amount - b.amount,
      pp: (a, b) => pp(b) - pp(a),
    };
    return [...rs].sort(cmp[sort] || cmp.new);
  }, [deals.data, q, area, sort, favOnly, W, lawd]);
  const pages = Math.max(1, Math.ceil(rows.length / size));
  const shown = rows.slice(page * size, page * size + size);

  // ----- 관심 목록 (단지 = 시군구·동·이름, 지역 = apt "") -----
  const isWatched = (l: string, apt: string, dong = "") => W.has(l, apt, dong);
  const toggleWatch = (l: string, apt: string, dong = "", jibun = "") => W.toggle({ lawd: l, region: regionName(l), apt, dong, jibun });
  const setNote = (i: number, note: string) => W.update(i, { note: note.slice(0, 200) });
  const openWatch = (w: Watch) => {
    const g = groups.find((x) => x.items.some((it) => it.code === w.lawd));
    if (g) setSido(g.sido);
    setLawd(w.lawd);
    setQ(w.apt);
  };

  const pickSido = (s: string) => {
    setSido(s);
    const first = groups.find((g) => g.sido === s)?.items[0];
    if (first) setLawd(first.code);
  };

  if (regions.loading && !regions.data) return <div className="page-loading">불러오는 중…</div>;
  if (regions.error || !regions.data) return <Alert kind="err">{regions.error || "지역 목록을 불러오지 못했습니다."}</Alert>;

  const sm = deals.data?.summary;
  const regionBox = (
    <div className="re-box">
      <div className="re-row">
        <div className="field narrow">
          <label htmlFor="re-sido">시도</label>
          <select id="re-sido" value={sido} onChange={(e) => pickSido(e.target.value)}>
            {groups.map((g) => <option key={g.sido}>{g.sido}</option>)}
          </select>
        </div>
        <div className="field">
          <label htmlFor="re-sgg">시군구</label>
          <select id="re-sgg" value={lawd} onChange={(e) => setLawd(e.target.value)}>
            {!sidoItems.some((it) => it.code === lawd) && <option value={lawd}>{regionName(lawd)}</option>}
            {sidoItems.map((it) => <option key={it.code} value={it.code}>{it.name}</option>)}
          </select>
        </div>
        <div className="field narrow">
          <label htmlFor="re-ym">계약 년월</label>
          <input id="re-ym" type="month" min="2006-01" max={thisMonthInput()} value={`${ymd.slice(0, 4)}-${ymd.slice(4)}`}
            onChange={(e) => e.target.value && setYmd(e.target.value.replace("-", ""))} />
        </div>
      </div>
    </div>
  );
  return (
    <div className="re-page">
      <div>
        <div className="eyebrow">실거래가 · 청약</div>
        <h2 className="sec-h">{tab === "apply" ? <>청약 <span className="grad">분양 공고</span></> : <>부동산 <span className="grad">실거래가</span></>}</h2>
        <p className="sec-p">국토교통부 신고 자료로 매매·전월세 거래를, 청약홈·LH 공고로 분양 일정을 봅니다. 관심 단지는 ☆로 모아 두세요. <Link className="re-link" to="/calc">내 집 계산기 →</Link></p>
      </div>

      <div className="btn-row re-tabs" role="tablist" aria-label="보기">
        <button type="button" role="tab" aria-selected={tab === "deals"} className={`pill ${tab === "deals" ? "on" : ""}`} onClick={() => setTab("deals")}>실거래가</button>
        <button type="button" role="tab" aria-selected={tab === "apply"} className={`pill ${tab === "apply" ? "on" : ""}`} onClick={() => setTab("apply")}>청약 공고</button>
      </div>

      {tab === "apply" ? <ApplyTab /> : <>
      <DatasetPicker value={ds} onChange={setDs} />

      <WatchPanel watch={watch} onOpen={(w) => { setDs("apt_trade"); openWatch(w); }} onNote={setNote} onRemove={(w) => toggleWatch(w.lawd, w.apt, w.dong || "")} />

      {!isApt ? (
        <>
          {regionBox}
          <DatasetView ds={ds} lawd={lawd} ymd={ymd} regionName={regionName(lawd)} />
        </>
      ) : storedMode ? (
        <>
          {isAdmin && <Alert kind="info">[관리자] 인증키가 없어 새 자료는 받지 못하지만, 저장된 자료(배치·파일 업로드)가 있는 시군구는 아래처럼 보입니다.</Alert>}
          {regionBox}
          <Drilldown key={lawd} lawd={lawd} regionName={regionName(lawd)} isWatched={isWatched} toggleWatch={toggleWatch} />
          <DatasetView ds="apt_trade" lawd={lawd} ymd={ymd} regionName={regionName(lawd)}
            star={(x) => x.name ? <Star on={isWatched(lawd, x.name, x.umd)} label={`${x.name} 관심 단지 저장`} onClick={() => toggleWatch(lawd, x.name, x.umd, x.jibun || "")} /> : null} />
        </>
      ) : !configured ? (
        isAdmin ? (
          <div className="re-box">
            <h3>실거래가 데이터 연결 필요 <span className="caption">· 관리자에게만 보이는 안내</span></h3>
            <p className="sec-p">공공데이터포털 인증키(DATA_GO_KR_KEY)가 없어 실거래가를 불러오지 못합니다. <code>backend/.env</code> 에 키를 넣고 관리 &gt; 부동산 데이터에서 API별 활용신청 상태를 확인하세요.</p>
            <p className="sec-p" style={{ marginTop: 8 }}><Link className="re-link" to="/admin/redata">관리 &gt; 부동산 데이터 →</Link></p>
          </div>
        ) : <DataPending onApply={() => setTab("apply")} />
      ) : (
        <>
          {regionBox}

          <div className="re-region-h">
            <h3>{regionName(lawd)} · {ymdLabel(ymd)}</h3>
            <Star on={isWatched(lawd, "")} label="관심 지역 저장" onClick={() => toggleWatch(lawd, "")} />
            {deals.data?.fetched_at && <span className="caption">자료 받은 시각 {deals.data.fetched_at.slice(0, 16).replace("T", " ")}</span>}
          </div>

          {deals.loading && !deals.data ? <div className="page-loading">실거래가를 불러오는 중… (처음 보는 지역·달은 몇 초 걸려요)</div>
            : deals.error ? <Alert kind="err">{deals.error}</Alert>
            : sm && sm.count === 0 ? <div className="re-box re-empty">이 달에 신고된 거래가 없습니다{sm.cancelled ? ` (해제 ${sm.cancelled}건 제외)` : ""}. 신고 기한이 계약 후 30일이라 최근 달은 늦게 채워집니다.</div>
            : sm ? (
              <>
                <div className="re-metrics">
                  <Card k="거래 건수" v={`${sm.count.toLocaleString()}건`} s={sm.cancelled ? `해제 ${sm.cancelled}건 제외` : "해제 거래 제외"} />
                  <Card k="중위 거래가" v={man(sm.median)} />
                  <Card k="3.3㎡당 평균" v={man(sm.avg_pyeong)} s={`중위 ${man(sm.median_pyeong)}`} />
                  <Card k="㎡당 평균" v={man(sm.avg_m2)} />
                  <Card k="최고가" v={man(sm.max?.amount)} s={sm.max ? `${sm.max.apt} ${sm.max.area}㎡` : ""} />
                  <Card k="최저가" v={man(sm.min?.amount)} s={sm.min ? `${sm.min.apt} ${sm.min.area}㎡` : ""} />
                </div>

                <TrendBox t={trend.data} loading={trend.loading} error={trend.error} />

                <Drilldown key={lawd} lawd={lawd} regionName={regionName(lawd)} isWatched={isWatched} toggleWatch={toggleWatch} />

                {!!sm.top_apts?.length && (
                  <div className="re-box">
                    <h3>거래 많은 단지 TOP {sm.top_apts.length}</h3>
                    <div className="re-tops">
                      {sm.top_apts.map((t) => (
                        <div key={t.apt + t.dong} className="re-top">
                          <Star on={isWatched(lawd, t.apt, t.dong)} label={`${t.apt} 관심 단지 저장`} onClick={() => toggleWatch(lawd, t.apt, t.dong)} />
                          <div className="nm">{t.apt}<small>{t.dong} · {t.count}건 · 3.3㎡당 {man(t.median_pyeong)}</small></div>
                          <div className="pr">{man(t.median)}</div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                <div className="re-box">
                  <h3>거래 목록</h3>
                  <div className="re-row" style={{ marginBottom: 10 }}>
                    <div className="field">
                      <label htmlFor="re-q">단지명·동 검색</label>
                      <input id="re-q" type="text" value={q} placeholder="예: 래미안, 대치동" onChange={(e) => setQ(e.target.value)} />
                    </div>
                    <div className="field narrow">
                      <label htmlFor="re-sort">정렬</label>
                      <select id="re-sort" value={sort} onChange={(e) => setSort(e.target.value)}>
                        {SORTS.map((s) => <option key={s.k} value={s.k}>{s.label}</option>)}
                      </select>
                    </div>
                  </div>
                  <div className="btn-row" style={{ marginBottom: 10 }}>
                    {AREAS.map((a) => <button key={a.k} type="button" className={`pill ${area === a.k ? "on" : ""}`} onClick={() => setArea(a.k)}>{a.label}</button>)}
                    <button type="button" className={`pill ${favOnly ? "on" : ""}`} aria-pressed={favOnly} onClick={() => setFavOnly(!favOnly)}>{favOnly ? "★" : "☆"} 관심 단지만</button>
                    <span className="caption">{rows.length.toLocaleString()}건</span>
                    <span className="cal-gap" />
                    <SizeSel size={size} setSize={setSize} setPage={setPage} />
                  </div>
                  <div className="table-wrap">
                    <table className="table re-table">
                      <thead>
                        <tr><th>계약일</th><th>단지</th><th className="num">전용㎡</th><th className="num">층</th><th className="num">거래가</th><th className="num">3.3㎡당</th><th className="num">건축</th><th>비고</th></tr>
                      </thead>
                      <tbody>
                        {shown.map((r, i) => (
                          <tr key={`${page}-${i}`} className={r.cancelled ? "re-cancel" : ""}>
                            <td>{r.date.slice(5)}</td>
                            <td className="apt">
                              <Star on={isWatched(lawd, r.apt, r.dong)} label={`${r.apt} 관심 단지 저장`} onClick={() => toggleWatch(lawd, r.apt, r.dong, r.jibun)} />
                              {r.apt} <span className="caption">{r.dong}</span>
                            </td>
                            <td className="num">{r.area.toFixed(1)}</td>
                            <td className="num">{r.floor ?? "-"}</td>
                            <td className="num"><b>{man(r.amount)}</b></td>
                            <td className="num">{man(pp(r))}</td>
                            <td className="num">{r.build_year ?? "-"}</td>
                            <td>
                              {r.cancelled && <span className="re-tag warn">해제{r.cancel_day ? ` ${r.cancel_day}` : ""}</span>}
                              {r.deal_type === "직거래" && <span className="re-tag">직거래</span>}
                              {!r.cancelled && <Link className="re-calc-link" to={`/calc?price=${r.amount}&label=${encodeURIComponent(`${r.apt} ${r.area.toFixed(0)}㎡`)}`} title="이 가격으로 대출 한도·취득세 계산">계산 →</Link>}
                            </td>
                          </tr>
                        ))}
                        {!shown.length && <tr><td colSpan={8} className="re-empty">{favOnly ? "이 달에 거래된 관심 단지가 없습니다. 단지 이름 앞 ☆를 눌러 관심 단지로 저장하세요." : "조건에 맞는 거래가 없습니다."}</td></tr>}
                      </tbody>
                    </table>
                  </div>
                  <Pager page={page} pages={pages} setPage={setPage} />
                  <p className="calc-note" style={{ marginTop: 10 }}>해제 거래는 줄을 그어 표시하고 통계에서 뺐습니다. 3.3㎡당 = 거래가 ÷ 전용면적 × 3.305785.</p>
                </div>
              </>
            ) : null}
        </>
      )}
      </>}
    </div>
  );
}


function Card({ k, v, s }: { k: string; v: string; s?: string }) {
  return (
    <div className="re-metric">
      <div className="k">{k}</div>
      <div className="v">{v}</div>
      {s && <div className="s">{s}</div>}
    </div>
  );
}

function WatchPanel({ watch, onOpen, onNote, onRemove }: { watch: Watch[]; onOpen: (w: Watch) => void; onNote: (i: number, v: string) => void; onRemove: (w: Watch) => void }) {
  return (
    <div className="re-box">
      <h3>내 관심 목록 <span className="caption">· 나에게만 보여요</span> <Link className="re-link" to="/my-homes" style={{ fontSize: ".9rem", marginLeft: 6 }}>관심 단지 대시보드 →</Link></h3>
      {!watch.length ? (
        <div className="re-empty">지역 이름 옆이나 단지 앞의 ☆를 누르면 여기에 모입니다.</div>
      ) : (
        <div className="re-watch">
          {watch.map((w, i) => (
            <div key={`${w.lawd}-${w.dong || ""}-${w.apt}`} className="re-watch-item">
              <div className="nm">{w.apt ? <Link to={`/my-homes?lawd=${w.lawd}&dong=${encodeURIComponent(w.dong || "")}&apt=${encodeURIComponent(w.apt)}`}>{w.apt}</Link> : "지역 전체"}<small>{w.region}{w.dong ? ` ${w.dong}` : ""} · {w.added}</small></div>
              <NoteInput value={w.note} onSave={(v) => onNote(i, v)} />
              <div className="btn-row" style={{ gap: 6 }}>
                <button type="button" className="btn sm" onClick={() => onOpen(w)}>보기</button>
                <button type="button" className="btn sm ghost" aria-label="관심 목록에서 빼기" onClick={() => onRemove(w)}>빼기</button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/** 메모는 글자마다 저장하지 않고 칸을 벗어날 때(또는 Enter) 한 번 저장한다 */
function NoteInput({ value, onSave }: { value: string; onSave: (v: string) => void }) {
  const [v, setV] = useState(value);
  useEffect(() => setV(value), [value]);
  return (
    <input type="text" value={v} maxLength={200} placeholder="메모 (예: 84㎡ 12억 이하면 검토)" aria-label="메모"
      onChange={(e) => setV(e.target.value)} onBlur={() => v !== value && onSave(v)}
      onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()} />
  );
}

function TrendBox({ t, loading, error }: { t: TrendRes | null; loading: boolean; error: string | null }) {
  const [hover, setHover] = useState<number | null>(null);
  if (loading && !t) return <div className="re-box re-empty">최근 12개월 흐름을 불러오는 중… (처음엔 달마다 받아 와서 조금 걸려요)</div>;
  if (error) return <Alert kind="warn">{error}</Alert>;
  const all = t?.points || [];
  const idx = all.map((p, i) => [p, i] as const).filter(([p]) => p.median_pyeong !== null) as (readonly [Point & { median_pyeong: number }, number])[];
  if (idx.length < 2) return null;
  const W = 640, H = 200, L = 14, R = 14, T = 26, B = 28;
  const vals = idx.map(([p]) => p.median_pyeong);
  const lo = Math.min(...vals), hi = Math.max(...vals);
  const span = hi - lo || hi * 0.05 || 1;
  const x = (i: number) => L + (all.length > 1 ? (i / (all.length - 1)) * (W - L - R) : 0);
  const y = (v: number) => T + (1 - (v - lo) / span) * (H - T - B);
  // 빈 달(자료 없음)에서는 선을 끊는다 — 없는 값을 이어 그리면 사실과 다른 흐름처럼 보인다
  const segs: string[] = [];
  let cur = "";
  all.forEach((p, i) => {
    if (p.median_pyeong === null) { if (cur) segs.push(cur); cur = ""; return; }
    cur += `${cur ? "L" : "M"}${x(i).toFixed(1)},${y(p.median_pyeong).toFixed(1)}`;
  });
  if (cur) segs.push(cur);
  const [first, fi] = idx[0];
  const [last, li] = idx[idx.length - 1];
  const chg = ((last.median_pyeong - first.median_pyeong) / first.median_pyeong) * 100;
  return (
    <div className="re-box re-trend">
      <h3>3.3㎡당 중위가격 · 최근 {all.length}개월 <span className="caption">({chg >= 0 ? "+" : ""}{chg.toFixed(1)}%)</span></h3>
      <div className="ctip-wrap">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`3.3㎡당 중위가격 추이, ${ymdLabel(first.ymd)}부터 ${ymdLabel(last.ymd)}까지 ${chg.toFixed(1)}% 변화`}>
        <line className="grid" x1={L} x2={W - R} y1={y(hi)} y2={y(hi)} />
        <line className="grid" x1={L} x2={W - R} y1={y(lo)} y2={y(lo)} />
        {segs.map((d, i) => <path key={i} className="ln" d={d} />)}
        {idx.map(([p, i]) => (
          <circle key={p.ymd} className="dot" cx={x(i)} cy={y(p.median_pyeong)} r={hover === i ? 5 : 3.5} />
        ))}
        <text className="val" x={x(fi)} y={y(first.median_pyeong) - 8} textAnchor="start">{man(first.median_pyeong)}</text>
        <text className="val" x={x(li)} y={y(last.median_pyeong) - 8} textAnchor="end">{man(last.median_pyeong)}</text>
        {all.map((p, i) => (i === 0 || i === all.length - 1 || i % 3 === 0) && (
          <text key={"l" + p.ymd} x={x(i)} y={H - 8} textAnchor={i === 0 ? "start" : i === all.length - 1 ? "end" : "middle"}>{`${p.ymd.slice(2, 4)}.${p.ymd.slice(4)}`}</text>
        ))}
        {hover !== null && all[hover] && (
          <ChartTip x={x(hover)} y={all[hover].median_pyeong !== null ? y(all[hover].median_pyeong as number) : null} top={T - 6} bottom={H - B} />
        )}
        {/* 달마다 넓은 투명 칸 — 작은 점을 정확히 맞추지 않아도, 휴대폰에서 눌러도 값이 보이게 */}
        {all.map((p, i) => {
          const w = (W - L - R) / Math.max(all.length - 1, 1);
          return <rect key={"h" + p.ymd} className="hit" x={x(i) - w / 2} width={w} y={0} height={H - B}
            onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)} onClick={() => setHover(i)} onTouchStart={() => setHover(i)} />;
        })}
      </svg>
      {hover !== null && all[hover] && (
        <TipBox x={x(hover)} y={all[hover].median_pyeong !== null ? y(all[hover].median_pyeong as number) : null} W={W} H={H}
          lines={[ymdLabel(all[hover].ymd), all[hover].median_pyeong !== null ? `3.3㎡당 ${man(all[hover].median_pyeong as number)}` : "거래 없음",
            `거래 ${all[hover].count ?? 0}건`]} />
      )}
      </div>
      {t?.partial && <p className="calc-note">일부 달은 아직 받지 못해 비어 있습니다. 잠시 뒤 다시 열면 채워집니다.</p>}
    </div>
  );
}

/** 지역 흐름 드릴다운 — 시군구 → 동 → 단지. 달마다 거래량(막대)·3.3㎡당 평균가(선), 거래량이 전월 대비 ±30% 바뀐 달에 노트 표시. */
function Drilldown({ lawd, regionName, isWatched, toggleWatch }: {
  lawd: string; regionName: string; isWatched: (l: string, apt: string, dong?: string) => boolean;
  toggleWatch: (l: string, apt: string, dong?: string, jibun?: string) => void;
}) {
  const [dong, setDong] = useState("");
  const [apt, setApt] = useState("");
  const t = useLoad(() => get<DrillRes>(`re/region/trend?lawd=${lawd}&dong=${encodeURIComponent(dong)}&apt=${encodeURIComponent(apt)}&months=24`), [lawd, dong, apt]);
  const d = t.data;
  if (t.loading && !d) return <div className="re-box re-empty">지역 흐름을 불러오는 중…</div>;
  if (t.error) return <Alert kind="warn">{t.error}</Alert>;
  if (!d || (!d.total && !dong && !apt)) return null; // 저장된 자료가 없는 시군구 — 칸을 숨긴다
  const levelName = apt || dong || regionName;
  return (
    <div className="re-box">
      <h3>지역 흐름 · 최근 {d.points.length}개월</h3>
      <nav className="re-crumbs" aria-label="지역 단계">
        {dong || apt ? <button type="button" onClick={() => { setDong(""); setApt(""); }}>{regionName}</button> : <span className="cur">{regionName}</span>}
        {dong && <><span className="sep">›</span>{apt ? <button type="button" onClick={() => setApt("")}>{dong}</button> : <span className="cur">{dong}</span>}</>}
        {apt && <><span className="sep">›</span><span className="cur">{apt}</span>
          <Star on={isWatched(lawd, apt, dong)} label={`${apt} 관심 단지 저장`} onClick={() => toggleWatch(lawd, apt, dong)} /></>}
      </nav>
      {!d.total ? <div className="re-empty">{levelName}의 저장된 거래가 없습니다.</div> : (
        <>
          <TrendChart points={d.points} markers={d.markers} value="avg_pyeong" valueLabel="3.3㎡당 평균가" title={`${levelName} 월별 거래량·3.3㎡당 평균가`} />
          {!!d.markers.length && (
            <ul className="re-mk-list">
              {d.markers.map((m) => (
                <li key={m.ymd}>{ymLabel(m.ymd)} 거래량 {pctText(m.change_pct)}{m.note ? <> · <Link to={`/notes?id=${m.note.id}`}>{m.note.title}</Link> <span className="caption">({m.note.scope === "region" ? "이 지역 노트" : "전국 정책 노트"})</span></> : <span className="caption"> · 같은 달 관련 노트 없음</span>}</li>
              ))}
            </ul>
          )}
          <p className="calc-note">노트 표시: {d.rule}. 이번 달·지난달은 신고 기한(계약 후 30일) 안이라 건수가 더 늘 수 있어 표시에서 뺍니다.</p>
        </>
      )}
      {!apt && !!d.children.length && (
        <>
          <div className="caption" style={{ marginTop: 10 }}>{dong ? "단지" : "법정동"}별 최근 12개월 — 눌러서 한 단계 아래로</div>
          <div className="re-kids">
            {d.children.map((k) => (
              <div key={k.name} className="re-kid">
                {dong && <Star on={isWatched(lawd, k.name, dong)} label={`${k.name} 관심 단지 저장`} onClick={() => toggleWatch(lawd, k.name, dong, k.jibun)} />}
                <button type="button" className="go" onClick={() => (dong ? setApt(k.name) : setDong(k.name))}>
                  {k.name}<small>{k.count}건 · 3.3㎡당 평균 {man(k.avg_pyeong)}</small>
                </button>
              </div>
            ))}
          </div>
        </>
      )}
      {apt && <p className="sec-p" style={{ marginTop: 8 }}><Link className="re-link" to={`/my-homes?lawd=${lawd}&dong=${encodeURIComponent(dong)}&apt=${encodeURIComponent(apt)}`}>이 단지 평형별 시세·전세가율 보기 →</Link></p>}
      <SourceLine source={d.source} asOf={d.as_of} fetchedAt={d.fetched_at} />
    </div>
  );
}
