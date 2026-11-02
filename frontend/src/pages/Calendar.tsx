// 분양 일정 (/calendar) + 당첨 가점 비교 (/calendar?tab=scores) — Phase 4.
// 자료: 배치가 저장한 청약홈·LH 공고(/api/re/calendar)와 청약홈 APT 당첨가점(/api/re/scores). 화면은 저장된 것만 읽는다.
// '알림 받기'는 내 프로필(alert_apply)에 공고 id 를 넣는다 → 확인된 구독자라면 접수 3일 전 메일 (backend/pipeline/reminders.py).
import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { get } from "../api";
import { Alert, Tabs, useLoad } from "../components/ui";
import { useMe } from "../me";
import { useProfile, useRegions } from "../profile";
import "./RealEstate.css";

type Ev = { date: string; type: string; label: string; notice_id: string };
type Notice = { id: string; name: string; region: string; kind: "sale" | "rent"; category: string; households: number | null; url: string;
  status: string; source: string; dates: Record<string, string>; long_open: boolean };
type CalRes = { ym: string; events: Ev[]; notices: Record<string, Notice>; today: string; applyhome: boolean; fetched_at: string };
type ScoreRow = { notice_id: string; model_no: string; house_ty: string; reside: string; low: number; top: number | null; avg: number | null;
  name: string; region: string; winner_date: string | null; notice_date: string | null; url: string };
type ScoreRes = { rows: ScoreRow[]; matched: number; stored: number; configured: boolean; status: string; source: string };

const TABS = ["분양 일정", "당첨 가점 비교"];
const DOW = ["일", "월", "화", "수", "목", "금", "토"];
const MAX_ALERTS = 20;

/** 청약 가점 (주택공급에 관한 규칙 별표 1) — 계산기(/calc)와 같은 번호 체계 */
export function subScore(p: { sub_home?: number; sub_fam?: number; sub_acct?: number } | null | undefined): number | null {
  if (!p || p.sub_home === undefined || p.sub_fam === undefined || p.sub_acct === undefined) return null;
  return (p.sub_home === 0 ? 0 : 2 * p.sub_home) + (5 + 5 * p.sub_fam) + (p.sub_acct + 1);
}

const ymOf = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
function shift(ym: string, n: number): string {
  const [y, m] = ym.split("-").map(Number);
  return ymOf(new Date(y, m - 1 + n, 1));
}

export default function CalendarPage() {
  const [sp, setSp] = useSearchParams();
  const tab = sp.get("tab") === "scores" ? TABS[1] : TABS[0];
  useEffect(() => { document.title = "분양 일정 · 당첨 가점 — ZipGenie"; }, []);
  return (
    <div className="re-page">
      <div>
        <div className="eyebrow">분양 일정</div>
        <h2 className="sec-h">이번 달 <span className="grad">청약 일정</span></h2>
        <p className="sec-p">
          청약홈·LH 공고의 접수·발표 일정을 달력으로 봅니다. 관심 공고에 🔔를 누르면 접수 3일 전에 메일로 알려 드려요.{" "}
          <Link className="re-link" to="/deals?tab=apply">공고 목록 →</Link>
        </p>
      </div>
      <Tabs items={TABS} value={tab} onChange={(t) => setSp(t === TABS[1] ? { tab: "scores" } : {}, { replace: true })} />
      {tab === TABS[0] ? <CalendarTab /> : <ScoresTab />}
    </div>
  );
}

function useMySidos(): string[] {
  const { profile } = useProfile();
  const { byCode } = useRegions();
  return useMemo(() => Array.from(new Set((profile?.regions || []).map((c) => (byCode[c]?.name || "").split(" ")[0]).filter(Boolean))), [profile?.regions, byCode]);
}

function CalendarTab() {
  const [ym, setYm] = useState(() => ymOf(new Date()));
  const [kind, setKind] = useState<"" | "sale" | "rent">("");
  const [mineOnly, setMineOnly] = useState(false);
  const [pick, setPick] = useState<string | null>(null);
  const sidos = useMySidos();
  const { me } = useMe();
  const { profile, save } = useProfile();
  const alerts = profile?.alert_apply || [];
  const region = mineOnly ? sidos.join(",") : "";
  const r = useLoad(() => get<CalRes>(`re/calendar?ym=${ym}&kind=${kind}&region=${encodeURIComponent(region)}`), [ym, kind, region]);
  const d = r.data;
  const byDate = useMemo(() => {
    const m: Record<string, Ev[]> = {};
    for (const e of d?.events || []) (m[e.date] ||= []).push(e);
    return m;
  }, [d]);
  const toggle = (id: string) => {
    const on = alerts.includes(id);
    if (!on && alerts.length >= MAX_ALERTS) { window.alert(`알림은 공고 ${MAX_ALERTS}개까지 받을 수 있어요.`); return; }
    save({ alert_apply: on ? alerts.filter((x) => x !== id) : [...alerts, id] });
  };

  const [y, m] = ym.split("-").map(Number);
  const first = new Date(y, m - 1, 1);
  const days = new Date(y, m, 0).getDate();
  const cells: (number | null)[] = [...Array(first.getDay()).fill(null), ...Array.from({ length: days }, (_, i) => i + 1)];
  while (cells.length % 7) cells.push(null);
  const iso = (day: number) => `${ym}-${String(day).padStart(2, "0")}`;
  const listDates = Object.keys(byDate).filter((k) => !pick || k === pick).sort();

  return (
    <>
      <div className="btn-row cal-bar">
        <button type="button" className="btn sm ghost" onClick={() => { setYm(shift(ym, -1)); setPick(null); }} aria-label="이전 달">‹</button>
        <b className="cal-ym">{y}년 {m}월</b>
        <button type="button" className="btn sm ghost" onClick={() => { setYm(shift(ym, 1)); setPick(null); }} aria-label="다음 달">›</button>
        <button type="button" className="btn sm ghost" onClick={() => { setYm(ymOf(new Date())); setPick(null); }}>이번 달</button>
        <span className="cal-gap" />
        {([["", "전체"], ["sale", "분양"], ["rent", "임대"]] as const).map(([k, l]) => (
          <button key={k} type="button" className={`pill ${kind === k ? "on" : ""}`} onClick={() => setKind(k)}>{l}</button>
        ))}
        {sidos.length > 0 && (
          <button type="button" className={`pill ${mineOnly ? "on" : ""}`} onClick={() => setMineOnly(!mineOnly)} title={sidos.join(", ")}>내 관심 지역만</button>
        )}
      </div>
      {alerts.length > 0 && (
        <p className="caption" style={{ margin: 0 }}>
          🔔 알림 받는 공고 {alerts.length}개.{" "}
          {me?.subscribed ? "접수 3일 전(시작일이 없으면 마감 3일 전)에 구독 메일로 보내 드려요." : <>메일은 뉴스레터 구독을 확인한 브라우저에만 가요. 구독하면 이 설정 그대로 알려 드려요.</>}
        </p>
      )}
      {r.error && <Alert kind="err">{r.error}</Alert>}
      <div className="cal-grid" role="grid" aria-label={`${y}년 ${m}월 청약 일정`}>
        {DOW.map((w, i) => <div key={w} className={`cal-dow ${i === 0 ? "sun" : i === 6 ? "sat" : ""}`}>{w}</div>)}
        {cells.map((day, i) => {
          if (!day) return <div key={`e${i}`} className="cal-cell empty" />;
          const k = iso(day), evs = byDate[k] || [];
          const counts: Record<string, number> = {};
          for (const e of evs) counts[e.label] = (counts[e.label] || 0) + 1;
          return (
            <button key={k} type="button" className={`cal-cell ${k === d?.today ? "today" : ""} ${pick === k ? "on" : ""} ${evs.length ? "has" : ""}`}
              onClick={() => setPick(pick === k ? null : k)} disabled={!evs.length} aria-label={`${m}월 ${day}일 ${evs.length}건`}>
              <span className="cal-d">{day}</span>
              {Object.entries(counts).slice(0, 3).map(([l, n]) => <span key={l} className={`cal-ev t-${evs.find((e) => e.label === l)?.type}`}>{l} {n}</span>)}
            </button>
          );
        })}
      </div>
      <div className="cal-list">
        {r.loading && !d ? <div className="page-loading">불러오는 중…</div> : !listDates.length ? (
          <div className="re-box re-empty">이 달에 표시할 청약 일정이 없어요{mineOnly ? " (내 관심 지역 기준)" : ""}.</div>
        ) : listDates.map((k) => (
          <section key={k}>
            <h3 className="cal-date">{Number(k.slice(5, 7))}월 {Number(k.slice(8))}일 ({DOW[new Date(k).getDay()]}){k === d?.today && <span className="re-tag">오늘</span>}</h3>
            {byDate[k].map((e) => {
              const n = d!.notices[e.notice_id];
              if (!n) return null;
              const on = alerts.includes(n.id);
              return (
                <div key={e.type + e.notice_id} className="cal-item">
                  <span className={`cal-ev t-${e.type}`}>{e.label}</span>
                  <div className="cal-main">
                    <b>{n.name}</b>
                    <div className="caption">
                      {n.region} · {n.kind === "rent" ? "임대" : "분양"}{n.category ? ` · ${n.category}` : ""}{n.households ? ` · ${n.households.toLocaleString()}세대` : ""} · {n.source}
                    </div>
                    <div className="caption">
                      {n.dates.notice && `공고 ${n.dates.notice}`}{n.dates.start && ` · 접수 ${n.dates.start}`}{n.dates.end && ` · 마감 ${n.dates.end}${n.long_open ? " (상시·선착순)" : ""}`}{n.dates.winner && ` · 발표 ${n.dates.winner}`}
                    </div>
                  </div>
                  <div className="cal-act">
                    <button type="button" className={`btn sm ${on ? "primary" : "ghost"}`} aria-pressed={on} onClick={() => toggle(n.id)} title="접수 3일 전 알림">{on ? "🔔 알림 중" : "🔔 알림 받기"}</button>
                    {n.url && <a className="btn sm ghost" href={n.url} target="_blank" rel="noopener">공고 ↗</a>}
                  </div>
                </div>
              );
            })}
          </section>
        ))}
      </div>
      <p className="calc-note">
        출처: 한국부동산원 청약홈, LH 청약플러스 공고 목록{d?.fetched_at ? ` · 자료 받은 시각 ${d.fetched_at.slice(0, 16).replace("T", " ")}` : ""}.
        LH 목록에는 공고일·마감일만 있어 접수 시작일은 공고 원문에서 확인하세요. 마감까지 넉 달이 넘는 상시·선착순 공고는 마감일을 달력에 찍지 않아요.
        {!d?.applyhome && " 청약홈 공고는 자료 갱신 중이에요."}
      </p>
    </>
  );
}

function ScoresTab() {
  const { profile } = useProfile();
  const { me } = useMe();
  const sidos = useMySidos();
  const [mineOnly, setMineOnly] = useState(true);
  const region = mineOnly ? sidos.join(",") : "";
  const r = useLoad(() => get<ScoreRes>(`re/scores?months=12&region=${encodeURIComponent(region)}`), [region]);
  const mine = subScore(profile);
  const d = r.data;
  return (
    <>
      <div className="re-box">
        <div className="caption">내 청약 가점</div>
        {mine === null ? (
          <p style={{ margin: "4px 0 0" }}>무주택 기간·부양가족·통장 가입 기간을 <Link to="/me">내 프로필</Link>에 넣거나 <Link to="/calc?tab=sub">가점 계산기</Link>로 계산해 보세요. 넣으면 아래 당첨 가점과 바로 비교해 드려요.</p>
        ) : <div className="calc-big">{mine}점 <small className="caption">/ 84</small></div>}
      </div>
      {sidos.length > 0 && (
        <div className="btn-row"><button type="button" className={`pill ${mineOnly ? "on" : ""}`} onClick={() => setMineOnly(!mineOnly)}>내 관심 지역만 ({sidos.join(", ")})</button></div>
      )}
      {r.error && <Alert kind="err">{r.error}</Alert>}
      {r.loading && !d ? <div className="page-loading">불러오는 중…</div> : d && !d.stored ? (
        <div className="re-box re-empty">
          {me?.is_admin
            ? "[관리자] 당첨 가점은 청약홈 경쟁률·당첨가점 API 로 받습니다. 공공데이터포털 인증키(DATA_GO_KR_KEY)를 넣고 '청약 경쟁률·당첨가점' 활용신청을 하면 다음 수집부터 채워집니다 — 관리 > 부동산 데이터."
            : "최근 당첨 가점 자료를 준비하고 있어요. 그동안 가점 계산기로 내 점수를 확인해 두세요."}
        </div>
      ) : d && !d.rows.length ? (
        <div className="re-box re-empty">최근 12개월 {mineOnly ? "내 관심 지역의 " : ""}당첨 가점 자료가 없어요.</div>
      ) : d && (
        <div className="table-wrap">
          <table className="table re-table">
            <thead><tr><th>단지 · 발표</th><th>주택형</th><th>거주</th><th className="num">최저</th><th className="num">평균</th><th className="num">최고</th>{mine !== null && <th>내 점수와</th>}</tr></thead>
            <tbody>
              {d.rows.map((x, i) => {
                const diff = mine !== null ? mine - x.low : null;
                return (
                  <tr key={i}>
                    <td>{x.url ? <a href={x.url} target="_blank" rel="noopener">{x.name}</a> : x.name}<div className="caption">{x.region} · {x.winner_date || x.notice_date || ""}</div></td>
                    <td>{x.house_ty}</td><td>{x.reside}</td>
                    <td className="num">{x.low}</td><td className="num">{x.avg ?? "-"}</td><td className="num">{x.top ?? "-"}</td>
                    {diff !== null && <td>{diff >= 0 ? <span className="re-tag">최저보다 +{diff}</span> : diff >= -5 ? <span className="re-tag warn">{diff}점 · 근접</span> : <span className="re-tag warn">{diff}점</span>}</td>}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <p className="calc-note">
        출처: {d?.source || "한국부동산원 청약홈"}. 최저 당첨 가점 이상이어도 당첨을 뜻하지 않아요. 같은 단지라도 해마다·주택형마다 경쟁이 다르고, 특별공급·추첨제 물량은 가점과 무관해요.
      </p>
    </>
  );
}
