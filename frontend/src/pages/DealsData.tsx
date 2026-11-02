// /deals 의 추가 화면 조각 — 데이터셋 선택, 배치가 저장한 실거래 데이터 보기(/api/re/data), 청약 공고 탭(/api/re/apply), 금리·지수(/api/re/indicators).
// 공공 API 를 직접 부르지 않고 배치 '부동산 데이터 수집'이 저장한 DB 만 읽는다. 자료가 없으면 숫자를 지어내지 않고 이유를 보여 준다.
import { Fragment, useEffect, useMemo, useState } from "react";
import { get } from "../api";
import { Link } from "react-router-dom";
import { Alert, useLoad } from "../components/ui";
import { useMe } from "../me";

type DsInfo = { key: string; name: string; prop: string; deal: string; status: string; status_label: string; row_count: number; ymd_from?: string; ymd_to?: string };
type DataRow = {
  deal_date: string | null; umd: string; jibun: string; name: string; kind: string; area: number | null; land_area: number | null;
  floor: number | null; build_year: number | null; amount: number | null; deposit: number | null; monthly_rent: number | null;
  deal_type: string; cancelled: boolean; contract_type: string; contract_term: string; landUse?: string; shareDealingType?: string;
  useRRRight?: string; preDeposit?: string; preMonthlyRent?: string;
};
type Summary = {
  count: number; cancelled: number; median?: number; median_m2?: number; median_pyeong?: number; direct?: number;
  max?: { amount: number; name: string; area: number; date: string }; min?: { amount: number; name: string; area: number; date: string };
  jeonse?: number; wolse?: number; median_jeonse?: number | null; median_wolse_deposit?: number | null; median_wolse_rent?: number | null;
  renewal?: number; median_jeonse_pyeong?: number | null; top_names?: { name: string; count: number }[];
};
type DataRes = DsInfo & { dataset: string; configured: boolean; region: string; ymd: string; fetched: boolean; fetched_at: string; summary: Summary; rows: DataRow[] };
type Notice = {
  notice_id: string; name: string; house_type: string; category: string | null; address: string; lawd_cd: string | null; region: string | null;
  households: number | null; notice_date: string | null; receipt_start: string | null; receipt_end: string | null; winner_date: string | null;
  contract_start: string | null; move_in_ym: string | null; url: string | null; source: string; status: string | null; builder: string | null;
};
type ApplyRes = { configured: boolean; rows: Notice[]; sources: Record<string, string> };
type Detail = Notice & {
  models: { model_no: string; house_ty: string; area: number | null; households: number | null; special_households: number | null; top_amount: number | null }[];
  cmpet: { house_ty: string; rank: string; reside: string; households: number | null; req_cnt: number | null; rate: string | null }[];
  score: { house_ty: string; reside: string; low: number | null; top: number | null; avg: number | null }[];
};
type Indicators = { base_rate: { changed_on: string; rate: number }[]; series: { id: string; name: string; unit: string; points: { period: string; value: number }[] }[] };

const PYEONG = 3.305785;
const PROPS = [
  { k: "apt", label: "아파트" }, { k: "rh", label: "연립·다세대" }, { k: "sh", label: "단독·다가구" }, { k: "offi", label: "오피스텔" },
  { k: "silv", label: "분양권·입주권", only: "silv_trade" }, { k: "land", label: "토지", only: "land_trade" }, { k: "nrg", label: "상업·업무용", only: "nrg_trade" },
];

function man(v: number | null | undefined): string {
  if (v === null || v === undefined || !isFinite(v)) return "-";
  const n = Math.round(v);
  const eok = Math.floor(Math.abs(n) / 10000);
  const rest = Math.abs(n) % 10000;
  const sign = n < 0 ? "-" : "";
  if (!eok) return `${sign}${rest.toLocaleString("ko-KR")}만원`;
  return `${sign}${eok}억${rest ? ` ${rest.toLocaleString("ko-KR")}만` : ""}원`;
}
const ymLabel = (ymd: string) => `${ymd.slice(0, 4)}년 ${Number(ymd.slice(4))}월`;

/** 매매/전월세 × 유형 선택 — 아파트 매매(apt_trade)는 예전 화면을 그대로 쓴다. */
/** 방문자용 '데이터 갱신 중' 안내 — 키·활용신청 같은 운영 사정은 관리자 화면에서만 보여 준다. */
export function DataPending({ onApply, compact }: { onApply?: () => void; compact?: boolean }) {
  return (
    <div className={`re-box${compact ? " re-empty" : ""}`}>
      {!compact && <h3>데이터 갱신 중입니다</h3>}
      <p className="sec-p">{compact ? "데이터 갱신 중입니다 — " : ""}곧 지역별 실거래가가 보입니다. 국토교통부 신고 자료를 지역·달별로 차례로 정리하고 있어요.</p>
      <p className="sec-p" style={{ marginTop: 8 }}>
        그동안 <Link className="re-link" to="/calc">내 집 계산기</Link>로 대출 한도·취득세·청약 가점을 계산하거나,{" "}
        {onApply ? <button type="button" className="re-link" style={{ background: "none", border: 0, padding: 0, cursor: "pointer", font: "inherit" }} onClick={onApply}>청약 공고</button>
          : <Link className="re-link" to="/deals?tab=apply">청약 공고</Link>}를 확인해 보세요.
      </p>
    </div>
  );
}

export function DatasetPicker({ value, onChange }: { value: string; onChange: (k: string) => void }) {
  const prop = PROPS.find((p) => p.only === value)?.k || value.split("_")[0];
  const deal = value.endsWith("_rent") ? "rent" : "trade";
  const cur = PROPS.find((p) => p.k === prop) || PROPS[0];
  const pick = (p: typeof PROPS[number], d: string) => onChange(p.only || `${p.k}_${d}`);
  return (
    <div className="re-box re-ds">
      <div className="btn-row" style={{ marginBottom: 8 }}>
        <span className="caption" style={{ minWidth: 48 }}>거래</span>
        <button type="button" className={`pill ${deal === "trade" ? "on" : ""}`} onClick={() => pick(cur, "trade")}>매매</button>
        <button type="button" className={`pill ${deal === "rent" ? "on" : ""}`} disabled={!!cur.only} title={cur.only ? "이 유형은 매매 자료만 있습니다" : ""}
          onClick={() => !cur.only && pick(cur, "rent")}>전월세</button>
      </div>
      <div className="btn-row">
        <span className="caption" style={{ minWidth: 48 }}>유형</span>
        {PROPS.map((p) => (
          <button key={p.k} type="button" className={`pill ${prop === p.k ? "on" : ""}`} onClick={() => pick(p, p.only ? "trade" : deal)}>{p.label}</button>
        ))}
      </div>
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

const PAGE = 20;

/** 배치로 저장한 데이터셋 하나의 한 시군구·한 달. */
export function DatasetView({ ds, lawd, ymd, regionName, star }: { ds: string; lawd: string; ymd: string; regionName: string; star?: (x: DataRow) => React.ReactNode }) {
  const r = useLoad<DataRes>(() => get<DataRes>(`re/data?dataset=${ds}&lawd=${lawd}&ymd=${ymd}`), [ds, lawd, ymd]);
  const isAdmin = !!useMe().me?.is_admin;
  const [q, setQ] = useState("");
  const [page, setPage] = useState(0);
  useEffect(() => setPage(0), [ds, lawd, ymd, q]);
  const rent = ds.endsWith("_rent");
  const rows = useMemo(() => {
    const qq = q.trim().replace(/\s+/g, "").toLowerCase();
    const rs = r.data?.rows || [];
    return qq ? rs.filter((x) => `${x.name}${x.umd}${x.kind}`.replace(/\s+/g, "").toLowerCase().includes(qq)) : rs;
  }, [r.data, q]);
  if (r.loading && !r.data) return <div className="page-loading">불러오는 중…</div>;
  if (r.error) return <Alert kind="err">{r.error}</Alert>;
  const d = r.data;
  if (!d) return null;
  const sm = d.summary;
  const pages = Math.max(1, Math.ceil(rows.length / PAGE));
  const shown = rows.slice(page * PAGE, page * PAGE + PAGE);
  const land = ds === "land_trade";
  // 집을 사는 거래만 계산기로 보낸다 (토지·상업업무용·전월세 제외)
  const home = !rent && ["apt_trade", "rh_trade", "sh_trade", "offi_trade", "silv_trade"].includes(ds);
  const unitLabel = land ? "㎡당" : "3.3㎡당";
  const unit = (x: DataRow) => {
    const price = rent ? x.deposit : x.amount;
    if (!price || !x.area) return null;
    return land ? price / x.area : (price / x.area) * PYEONG;
  };
  return (
    <>
      <div className="re-region-h">
        <h3>{regionName} · {ymLabel(ymd)} · {d.name}</h3>
        {d.fetched_at && <span className="caption">자료 받은 시각 {d.fetched_at.slice(0, 16).replace("T", " ")}</span>}
      </div>
      {!d.fetched ? (
        <div className="re-box re-empty">
          {(d.status === "no_key" || d.status === "not_registered") && !isAdmin ? "데이터 갱신 중입니다 — 곧 이 자료도 지역별로 보입니다. 그동안 다른 유형이나 청약 공고를 확인해 보세요."
            : d.status === "no_key" ? "[관리자] 공공데이터포털 인증키(DATA_GO_KR_KEY)가 없어 이 데이터셋을 받지 못했습니다 — 관리 > 부동산 데이터에서 확인하세요."
            : d.status === "not_registered" ? "[관리자] 이 API 는 공공데이터포털 활용신청이 필요합니다 — 관리 > 부동산 데이터에서 신청 링크를 확인하세요."
            : `이 지역·달은 아직 받지 않았습니다${d.ymd_from ? ` (저장된 범위 ${d.ymd_from.slice(0, 4)}.${d.ymd_from.slice(4)}~${(d.ymd_to || "").slice(0, 4)}.${(d.ymd_to || "").slice(4)})` : ""}. 매일 아침 최근 달부터 차례로 채웁니다.`}
        </div>
      ) : sm.count === 0 ? (
        <div className="re-box re-empty">이 달에 신고된 거래가 없습니다{sm.cancelled ? ` (해제 ${sm.cancelled}건 제외)` : ""}.</div>
      ) : (
        <>
          <div className="re-metrics">
            <Card k="거래 건수" v={`${sm.count.toLocaleString()}건`} s={sm.cancelled ? `해제 ${sm.cancelled}건 제외` : rent ? `갱신 ${sm.renewal ?? 0}건` : ""} />
            {rent ? (
              <>
                <Card k="전세 중위 보증금" v={man(sm.median_jeonse)} s={`전세 ${sm.jeonse ?? 0}건 · 3.3㎡당 ${man(sm.median_jeonse_pyeong)}`} />
                <Card k="월세 중위" v={sm.median_wolse_rent ? `${man(sm.median_wolse_deposit)} / ${sm.median_wolse_rent}만` : "-"} s={`월세 ${sm.wolse ?? 0}건 (보증금 / 월세)`} />
              </>
            ) : (
              <>
                <Card k="중위 거래가" v={man(sm.median)} s={sm.direct ? `직거래 ${sm.direct}건` : ""} />
                <Card k={`${unitLabel} 중위`} v={man(land ? sm.median_m2 : sm.median_pyeong)} />
                <Card k="최고가" v={man(sm.max?.amount)} s={sm.max ? `${sm.max.name || ""} ${sm.max.area ?? ""}㎡` : ""} />
                <Card k="최저가" v={man(sm.min?.amount)} s={sm.min ? `${sm.min.name || ""} ${sm.min.area ?? ""}㎡` : ""} />
              </>
            )}
          </div>
          <div className="re-box">
            <h3>거래 목록</h3>
            <div className="re-row" style={{ marginBottom: 10 }}>
              <div className="field">
                <label htmlFor="re-dq">이름·동 검색</label>
                <input id="re-dq" type="text" value={q} placeholder="예: 단지명, 법정동, 용도" onChange={(e) => setQ(e.target.value)} />
              </div>
              <span className="caption">{rows.length.toLocaleString()}건</span>
            </div>
            <div className="table-wrap">
              <table className="table re-table">
                <thead>
                  <tr>
                    <th>계약일</th><th>{land ? "지목·용도" : "이름"}</th><th className="num">{land ? "거래면적" : "면적㎡"}</th>
                    {!land && <th className="num">층</th>}
                    <th className="num">{rent ? "보증금" : "거래가"}</th>{rent && <th className="num">월세</th>}
                    <th className="num">{unitLabel}</th><th>비고</th>
                  </tr>
                </thead>
                <tbody>
                  {shown.map((x, i) => (
                    <tr key={`${page}-${i}`} className={x.cancelled ? "re-cancel" : ""}>
                      <td>{(x.deal_date || "").slice(5) || "-"}</td>
                      <td className="apt">{star?.(x)}{x.name || x.kind || "-"} <span className="caption">{x.umd}{x.name && x.kind ? ` · ${x.kind}` : ""}{x.landUse ? ` · ${x.landUse}` : ""}</span></td>
                      <td className="num">{x.area ? x.area.toFixed(1) : "-"}</td>
                      {!land && <td className="num">{x.floor ?? "-"}</td>}
                      <td className="num"><b>{man(rent ? x.deposit : x.amount)}</b></td>
                      {rent && <td className="num">{x.monthly_rent ? `${x.monthly_rent}만` : "-"}</td>}
                      <td className="num">{man(unit(x))}</td>
                      <td>
                        {x.cancelled && <span className="re-tag warn">해제</span>}
                        {x.deal_type === "직거래" && <span className="re-tag">직거래</span>}
                        {x.contract_type && <span className="re-tag">{x.contract_type}</span>}
                        {x.useRRRight && <span className="re-tag">갱신요구권</span>}
                        {x.shareDealingType && <span className="re-tag">지분</span>}
                        {home && !x.cancelled && x.amount ? <Link className="re-calc-link" to={`/calc?price=${x.amount}&label=${encodeURIComponent(`${x.name || x.kind || ""} ${x.area ? `${x.area.toFixed(0)}㎡` : ""}`.trim())}`} title="이 가격으로 대출 한도·취득세 계산">계산 →</Link> : null}
                      </td>
                    </tr>
                  ))}
                  {!shown.length && <tr><td colSpan={8} className="re-empty">조건에 맞는 거래가 없습니다.</td></tr>}
                </tbody>
              </table>
            </div>
            {pages > 1 && (
              <div className="re-pager">
                <button type="button" className="btn sm" disabled={page === 0} onClick={() => setPage(page - 1)}>이전</button>
                <span className="caption">{page + 1} / {pages}</span>
                <button type="button" className="btn sm" disabled={page >= pages - 1} onClick={() => setPage(page + 1)}>다음</button>
              </div>
            )}
            <p className="calc-note" style={{ marginTop: 10 }}>
              {rent ? "전세 = 월세 0원 계약. 3.3㎡당은 전세 보증금 기준." : land ? "㎡당 = 거래가 ÷ 거래면적." : "해제 거래는 통계에서 뺐습니다. 3.3㎡당 = 거래가 ÷ 면적 × 3.305785."}
              {" "}출처: 국토교통부 실거래가 공개 자료.
            </p>
          </div>
        </>
      )}
    </>
  );
}

const fmtD = (s: string | null) => (s ? s.slice(5).replace("-", ".") : "-");
const daysTo = (s: string | null) => (s ? Math.ceil((new Date(s + "T00:00:00").getTime() - new Date(new Date().toDateString()).getTime()) / 86400000) : null);

function NoticeDetail({ id }: { id: string }) {
  const r = useLoad<Detail>(() => get<Detail>(`re/apply/${encodeURIComponent(id)}`), [id]);
  if (r.loading && !r.data) return <div className="caption">불러오는 중…</div>;
  if (r.error || !r.data) return <div className="caption">{r.error}</div>;
  const d = r.data;
  return (
    <div className="re-apply-detail">
      <p className="caption">{d.address}{d.builder ? ` · ${d.builder}` : ""}{d.move_in_ym ? ` · 입주 예정 ${d.move_in_ym.slice(0, 4)}.${d.move_in_ym.slice(4)}` : ""}</p>
      {!!d.models.length && (
        <div className="table-wrap"><table className="table re-table">
          <thead><tr><th>주택형</th><th className="num">일반</th><th className="num">특별</th><th className="num">분양 최고가</th></tr></thead>
          <tbody>{d.models.map((m, i) => <tr key={i}><td>{m.house_ty}</td><td className="num">{m.households ?? "-"}</td><td className="num">{m.special_households ?? "-"}</td><td className="num">{man(m.top_amount)}</td></tr>)}</tbody>
        </table></div>
      )}
      {!!d.cmpet.length && (
        <div className="table-wrap"><table className="table re-table">
          <thead><tr><th>주택형</th><th>순위</th><th>거주</th><th className="num">공급</th><th className="num">접수</th><th className="num">경쟁률</th></tr></thead>
          <tbody>{d.cmpet.map((m, i) => <tr key={i}><td>{m.house_ty}</td><td>{m.rank}</td><td>{m.reside}</td><td className="num">{m.households ?? "-"}</td><td className="num">{m.req_cnt ?? "-"}</td><td className="num">{m.rate ?? "-"}</td></tr>)}</tbody>
        </table></div>
      )}
      {!!d.score.length && (
        <div className="table-wrap"><table className="table re-table">
          <thead><tr><th>주택형</th><th>거주</th><th className="num">최저 가점</th><th className="num">평균</th><th className="num">최고</th></tr></thead>
          <tbody>{d.score.map((m, i) => <tr key={i}><td>{m.house_ty}</td><td>{m.reside}</td><td className="num">{m.low ?? "-"}</td><td className="num">{m.avg ?? "-"}</td><td className="num">{m.top ?? "-"}</td></tr>)}</tbody>
        </table></div>
      )}
      {!d.models.length && !d.cmpet.length && <p className="caption">주택형·경쟁률 자료가 아직 없습니다{d.source === "lh" ? " (LH 공고는 공고문 링크에서 확인하세요)" : ""}.</p>}
    </div>
  );
}

/** 청약 공고 — 접수 예정·진행 중 먼저, 지역·유형·검색. */
export function ApplyTab() {
  const [scope, setScope] = useState<"upcoming" | "all">("upcoming");
  const [region, setRegion] = useState("");
  const [q, setQ] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const [page, setPage] = useState(0);
  const r = useLoad<ApplyRes>(() => get<ApplyRes>(`re/apply?scope=${scope}${region ? `&region=${encodeURIComponent(region)}` : ""}&limit=300`), [scope, region]);
  const ind = useLoad<Indicators>(() => get<Indicators>("re/indicators"), []);
  const isAdmin = !!useMe().me?.is_admin;
  useEffect(() => setPage(0), [scope, region, q]);
  const rows = useMemo(() => {
    const qq = q.trim().replace(/\s+/g, "");
    const rs = r.data?.rows || [];
    return qq ? rs.filter((n) => `${n.name}${n.address}${n.category || ""}`.replace(/\s+/g, "").includes(qq)) : rs;
  }, [r.data, q]);
  const regions = useMemo(() => [...new Set((r.data?.rows || []).map((n) => n.region).filter(Boolean) as string[])].sort(), [r.data]);
  const shown = rows.slice(page * PAGE, page * PAGE + PAGE);
  const pages = Math.max(1, Math.ceil(rows.length / PAGE));
  const src = r.data?.sources || {};
  const base = ind.data?.base_rate?.[0];
  const mort = ind.data?.series.find((s) => s.id === "mortgage_new");
  const mortLast = mort?.points[mort.points.length - 1];
  return (
    <>
      {(base || mortLast) && (
        <div className="re-metrics">
          {base && <Card k="한국은행 기준금리" v={`${base.rate.toFixed(2)}%`} s={`${base.changed_on} 변경`} />}
          {mortLast && <Card k="주담대 금리(신규, 예금은행)" v={`${mortLast.value.toFixed(2)}%`} s={`${mortLast.period.slice(0, 4)}.${mortLast.period.slice(4)} 기준`} />}
          {["kb_sale_apt", "kb_sale_apt_seoul"].map((id) => ind.data?.series.find((s) => s.id === id)).filter((s): s is Indicators["series"][number] => !!s).map((s) => {
            const p = s.points; const last = p[p.length - 1]; const prev = p[p.length - 2];
            return last ? <Card key={s.id} k={s.name} v={last.value.toFixed(1)} s={prev ? `전월 대비 ${(((last.value - prev.value) / prev.value) * 100).toFixed(2)}%` : last.period} /> : null;
          })}
        </div>
      )}
      <div className="re-box">
        <div className="re-row">
          <div className="btn-row">
            <button type="button" className={`pill ${scope === "upcoming" ? "on" : ""}`} onClick={() => setScope("upcoming")}>접수 예정·진행</button>
            <button type="button" className={`pill ${scope === "all" ? "on" : ""}`} onClick={() => setScope("all")}>최근 공고 전체</button>
          </div>
          <div className="field narrow">
            <label htmlFor="ap-rg">지역</label>
            <select id="ap-rg" value={region} onChange={(e) => setRegion(e.target.value)}>
              <option value="">전체</option>
              {regions.map((x) => <option key={x}>{x}</option>)}
            </select>
          </div>
          <div className="field">
            <label htmlFor="ap-q">단지·주소 검색</label>
            <input id="ap-q" type="text" value={q} placeholder="예: 래미안, 행복주택, 화성" onChange={(e) => setQ(e.target.value)} />
          </div>
        </div>
      </div>
      {src.apply_notice && src.apply_notice !== "ok" && (
        <p className="caption">청약홈(민간·공공 분양) 공고는 {!isAdmin ? "데이터 갱신이 끝나면" : src.apply_notice === "no_key" ? "[관리자] 공공데이터포털 키(DATA_GO_KR_KEY)가 등록되면" : src.apply_notice === "not_registered" ? "[관리자] 공공데이터포털 활용신청을 마치면" : "다음 수집 때"} 함께 보입니다. 지금은 LH 공고만 있어요.</p>
      )}
      {r.loading && !r.data ? <div className="page-loading">불러오는 중…</div>
        : r.error ? <Alert kind="err">{r.error}</Alert>
        : !rows.length ? <div className="re-box re-empty">조건에 맞는 공고가 없습니다. 공고 목록은 매일 아침 새로 받습니다.</div>
        : (
          <div className="re-box">
            <h3>공고 {rows.length.toLocaleString()}건</h3>
            <div className="table-wrap">
              <table className="table re-table">
                <thead><tr><th>공고</th><th>유형</th><th>지역</th><th className="num">세대</th><th>공고일</th><th>접수</th><th>발표</th><th /></tr></thead>
                <tbody>
                  {shown.map((n) => {
                    const dd = daysTo(n.receipt_start || n.receipt_end);
                    return (
                      <Fragment key={n.notice_id}>
                        <tr className="click" onClick={() => setOpen(open === n.notice_id ? null : n.notice_id)}>
                          <td className="apt">{n.name}{n.status && <span className="re-tag">{n.status}</span>}{dd !== null && dd >= 0 && dd <= 7 && <span className="re-tag warn">D-{dd}</span>}</td>
                          <td>{n.house_type === "LH" ? (n.category || "LH") : n.house_type}</td>
                          <td>{n.region || "-"}<div className="caption">{n.address && n.address !== n.region ? n.address.split(" ").slice(1, 3).filter((t) => t !== "외").join(" ") : ""}</div></td>
                          <td className="num">{n.households ?? "-"}</td>
                          <td>{fmtD(n.notice_date)}</td>
                          <td>{n.receipt_start ? `${fmtD(n.receipt_start)}~${fmtD(n.receipt_end)}` : n.receipt_end ? `~${fmtD(n.receipt_end)}` : "-"}</td>
                          <td>{fmtD(n.winner_date)}</td>
                          <td>{n.url && <a className="re-link" href={n.url} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}>공고</a>}</td>
                        </tr>
                        {open === n.notice_id && <tr><td colSpan={8}><NoticeDetail id={n.notice_id} /></td></tr>}
                      </Fragment>
                    );
                  })}
                </tbody>
              </table>
            </div>
            {pages > 1 && (
              <div className="re-pager">
                <button type="button" className="btn sm" disabled={page === 0} onClick={() => setPage(page - 1)}>이전</button>
                <span className="caption">{page + 1} / {pages}</span>
                <button type="button" className="btn sm" disabled={page >= pages - 1} onClick={() => setPage(page + 1)}>다음</button>
              </div>
            )}
            <p className="calc-note" style={{ marginTop: 10 }}>출처: 한국부동산원 청약홈(공공데이터포털)·LH 청약플러스 공고 목록. 일정은 반드시 공고문에서 다시 확인하세요.</p>
          </div>
        )}
    </>
  );
}
