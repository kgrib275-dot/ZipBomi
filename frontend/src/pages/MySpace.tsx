// 내 공간 (/my, 2026-11-02) — 관심 단지 최근 거래·관심/알림 공고·저장한 노트·저장한 계산·메모를 한 화면에,
// 그리고 '내 자료로 질문하기'. GET /api/me/space (backend/pipeline/my_space.py). 로그인하면 어느 기기에서든 같다.
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { get, post } from "../api";
import { useDialogs } from "../components/Dialogs";
import { Alert, useLoad } from "../components/ui";
import { announceAuth, useMe } from "../me";
import { man } from "../policy";
import { useRegions } from "../profile";
import { ItemNote, MyCalendar } from "./MyCalendar";
import { CompareTable, DataBackup, TodoBox } from "./MyTools";
import "./MySpace.css";
import "./RealEstate.css";

type W = { lawd: string; region: string; apt: string; dong: string; note: string; deals_6m: number; pp_recent: number | null; pp_before: number | null;
  change_pct: number | null; last: { date: string; amount: number; area: number | null; floor: number | null; name: string } | null };
type N = { notice_id: string; name: string; region: string; receipt_start: string | null; receipt_end: string | null; winner_date: string | null; url: string };
type Space = { profile: Record<string, unknown>; watch: W[]; apply: N[]; apply_alert: string[]; apply_fav: string[];
  notes: { id: number; title: string; category: string; published: string; summary: string }[];
  calcs: { label: string; summary: string; url: string; at: string }[]; memo: string; account: { email: string; since: string } | null };

const dday = (s: string | null) => (s ? Math.ceil((new Date(s + "T00:00:00").getTime() - new Date(new Date().toDateString()).getTime()) / 86400000) : null);
const SUGGEST = ["내 관심 단지들 최근 거래 흐름을 요약해 줘", "내 가점이면 다가오는 청약 중 어디가 해볼 만해?", "내 소득으로 관심 지역에서 가능한 집값은?", "저장한 노트 기준으로 이번 주 꼭 볼 것만 알려 줘"];

export default function MySpace() {
  const { me, state, setState } = useMe();
  const { openLogin } = useDialogs();
  const nav = useNavigate();
  const { data, error, reload } = useLoad(() => get<Space>("me/space"), [JSON.stringify([state.re_watch, state.apply_fav, state.note_bm, state.calc_saves, (state.profile as Record<string, unknown> | undefined)?.alert_apply])]);
  const [memo, setMemo] = useState("");
  useEffect(() => { if (data) setMemo(data.memo); }, [data?.memo]); // eslint-disable-line react-hooks/exhaustive-deps
  const acc = me?.account;
  const empty = data && !data.watch.length && !data.apply.length && !data.notes.length && !data.calcs.length;
  const removeCalc = (i: number) => setState({ calc_saves: (data?.calcs || []).filter((_, j) => j !== i) });
  const logout = async () => { await post("auth/logout"); announceAuth(); window.location.href = "/"; };
  const logoutAll = async () => {
    if (!window.confirm("모든 기기에서 로그아웃할까요? 이 브라우저만 로그인 상태로 남고, 다른 기기는 다시 로그인해야 합니다.")) return;
    await post("auth/logout-all"); window.alert("다른 모든 기기에서 로그아웃했습니다.");
  };
  const [devices, setDevices] = useState(false);
  return (
    <div className="my">
      <div className="eyebrow">내 공간</div>
      <h2 className="sec-h">나만의 <span className="grad">집 노트</span></h2>
      <div className="my-acc">
        {acc ? <><span>✓ {acc.email} 로 로그인 · {acc.since}부터</span><button type="button" className="linkish" onClick={logout}>로그아웃</button>
          <button type="button" className="linkish" onClick={() => setDevices((v) => !v)}>로그인한 기기</button>
          <button type="button" className="linkish" onClick={logoutAll} title="다른 기기에서 로그인된 것을 모두 끊습니다">모든 기기에서 로그아웃</button></>
          : <><span>지금은 이 브라우저에만 저장돼요. 로그인하면 휴대폰·PC 어디서든 그대로 보여요.</span><button type="button" className="btn sm primary" onClick={openLogin}>메일로 로그인</button></>}
        <Link to="/me" className="linkish">내 프로필 고치기</Link>
      </div>

      {acc && devices && <MyDevices />}

      <AskMine />

      {error && <Alert kind="err">{error}</Alert>}
      {!data ? <div className="page-loading">불러오는 중…</div> : (
        <>
          {/* 내 메모 — 달력 옆(좁은 화면은 바로 아래)에 붙여 한눈에 (2026-11-02) */}
          <MyCalendar apply={data.apply} alerts={data.apply_alert} lease={(data.profile as { lease_end?: string }).lease_end}
            side={<div className="my-memo-box"><b>📝 내 메모</b>
              <textarea className="my-memo" rows={5} maxLength={2000} value={memo} placeholder="임장 메모, 은행 상담 내용, 체크할 것… (질문하기에서도 참고해요)"
                onChange={(e) => setMemo(e.target.value)} onBlur={() => { if (memo !== data.memo) { setState({ my_memo: memo }); reload(); } }} />
              <span className="caption">칸 밖을 누르면 저장돼요.</span></div>} />
          <TodoBox />
          {empty && <Alert kind="info">아직 모아 둔 것이 없어요. <Link to="/deals">실거래가</Link>에서 단지 앞 ☆, <Link to="/calendar">분양 일정</Link>에서 🔔, <Link to="/notes">노트</Link>에서 ☆를 누르면 여기에 모여요.</Alert>}
          <section className="my-sec">
            <div className="my-h"><h3>관심 단지·지역 <small>{data.watch.length}</small></h3><Link to="/my-homes">관리 →</Link></div>
            {!data.watch.length ? <p className="caption">실거래가 화면에서 단지 이름 앞 ☆를 누르면 최근 거래가 여기 모여요.</p> : (
              <div className="my-grid">
                {data.watch.map((w) => (
                  <Link key={w.lawd + w.dong + w.apt} className="my-card" to={`/deals?lawd=${w.lawd}`}>
                    <b>{w.apt || `${w.region} 전체`}</b>
                    <span className="caption">{w.region} {w.dong}</span>
                    <div className="my-num">{w.pp_recent ? man(w.pp_recent) : "-"}<small>/3.3㎡ (최근 3개월)</small></div>
                    {w.change_pct !== null && <span className={`my-chg ${w.change_pct > 0 ? "up" : w.change_pct < 0 ? "down" : ""}`}>{w.change_pct > 0 ? "▲" : w.change_pct < 0 ? "▼" : "–"} {Math.abs(w.change_pct)}%</span>}
                    <span className="caption">{w.last ? `마지막 ${w.last.date.slice(5)} · ${man(w.last.amount)}${w.last.area ? ` · ${Math.round(w.last.area)}㎡` : ""}` : "최근 6개월 거래 없음"} · 6개월 {w.deals_6m}건</span>
                    {w.note && <span className="my-note">📝 {w.note}</span>}
                    <ItemNote k={`w:${w.lawd}|${w.dong}|${w.apt}`} title={w.apt || `${w.region} 전체`} />
                  </Link>
                ))}
              </div>
            )}
          </section>

          <CompareTable watch={data.watch} />

          <section className="my-sec">
            <div className="my-h"><h3>관심·알림 청약 <small>{data.apply.length}</small></h3><Link to="/calendar">분양 일정 →</Link></div>
            {!data.apply.length ? <p className="caption">분양 일정에서 🔔, 청약 공고에서 ☆를 누르면 여기 모여요.</p> : (
              <ul className="my-list">
                {data.apply.map((n) => {
                  const d = dday(n.receipt_start || n.receipt_end);
                  return (
                    <li key={n.notice_id}>
                      <span className={`my-dd${d !== null && d >= 0 && d <= 3 ? " hot" : ""}`}>{d === null ? "-" : d < 0 ? "지남" : d === 0 ? "오늘" : `D-${d}`}</span>
                      <a href={n.url || "#"} target="_blank" rel="noopener">{n.name}</a>
                      <span className="caption">{n.region} · 접수 {n.receipt_start?.slice(5) || "-"}~{n.receipt_end?.slice(5) || "-"}{data.apply_alert.includes(n.notice_id) ? " · 🔔" : ""}</span>
                      <ItemNote k={`a:${n.notice_id}`} title={n.name} />
                    </li>
                  );
                })}
              </ul>
            )}
          </section>

          <section className="my-sec">
            <div className="my-h"><h3>저장한 노트 <small>{data.notes.length}</small></h3><Link to="/notes">노트 →</Link></div>
            {!data.notes.length ? <p className="caption">노트 카드 오른쪽 위 ☆를 누르면 여기 모여요.</p> : (
              <ul className="my-list">
                {data.notes.map((n) => <li key={n.id}><span className="my-dd">{n.published.slice(5, 10)}</span><Link to={`/notes?id=${n.id}`}>{n.title}</Link><span className="caption">{n.category}</span><ItemNote k={`n:${n.id}`} title={n.title} /></li>)}
              </ul>
            )}
          </section>

          <section className="my-sec">
            <div className="my-h"><h3>저장한 계산 <small>{data.calcs.length}</small></h3><Link to="/calc">계산기 →</Link></div>
            {!data.calcs.length ? <p className="caption">계산기에서 '이 계산 저장'을 누르면 여기 모여 비교할 수 있어요.</p> : (
              <ul className="my-list">
                {data.calcs.map((x, i) => (
                  <li key={i}><span className="my-dd">{x.at?.slice(5, 10)}</span><button type="button" className="linkish" onClick={() => nav(x.url)}>{x.label}</button>
                    <span className="caption">{x.summary}</span><ItemNote k={`c:${x.at}`} title={x.label} /><button type="button" className="my-x" aria-label="지우기" onClick={() => removeCalc(i)}>×</button></li>
                ))}
              </ul>
            )}
          </section>

          <AllSettings />
          <DataBackup />


        </>
      )}
    </div>
  );
}

/** 내 자료로 질문하기 — /ask 로 보내되 '내 공간 자료 함께'를 켠 채로 */
function AskMine() {
  const nav = useNavigate();
  const [q, setQ] = useState("");
  const go = (text: string) => { if (text.trim()) nav(`/ask?q=${encodeURIComponent(text.trim())}&mine=1`); };
  return (
    <div className="my-ask">
      <b>🧞 내 자료로 물어보기</b>
      <span className="caption">관심 단지 시세·관심 공고·내 프로필·저장한 노트·메모를 근거로 답해요.</span>
      <form onSubmit={(e) => { e.preventDefault(); go(q); }} className="my-ask-f">
        <input type="text" value={q} onChange={(e) => setQ(e.target.value)} maxLength={300} placeholder="예: 내 관심 단지 중 최근에 오른 곳은?" />
        <button className="btn primary">물어보기</button>
      </form>
      <div className="my-sug">{SUGGEST.map((s) => <button key={s} type="button" className="pill sm" onClick={() => go(s)}>{s}</button>)}</div>
    </div>
  );
}

const TYPES: Record<string, string> = { first_home: "무주택(첫 집)", upgrade: "1주택 갈아타기", tenant: "임차인(전월세)", investor: "투자 관심" };
const SORTS: Record<string, string> = { new: "최신순", popular: "인기순" };
const lsv = (k: string) => { try { return localStorage.getItem(k) || ""; } catch { return ""; } };
const manTxt = (v: unknown) => (typeof v === "number" && v > 0 ? man(v) : "");

/** 사이트에서 설정한 모든 것 — 서버에 저장된 값(로그인하면 기기 사이 공유)과 이 브라우저에만 있는 화면 설정, 바꾸는 곳 링크 */
function AllSettings() {
  const { me, state } = useMe();
  const { byCode } = useRegions();
  const p = (state.profile || {}) as Record<string, unknown>;
  const list = (v: unknown) => (Array.isArray(v) ? (v as unknown[]).map(String) : []);
  const regs = list(p.regions).map((c) => byCode[c]?.name || c).join(", ");
  const sub = p.sub_home !== undefined && p.sub_fam !== undefined && p.sub_acct !== undefined
    ? (() => { const h = Number(p.sub_home), f = Number(p.sub_fam), a = Number(p.sub_acct); return `${(h === 0 ? 0 : 2 * h) + 5 + 5 * f + a + 1}점 (무주택 ${h}년·부양 ${f}명·통장 ${a}년)`; })() : "";
  const filt = [list(state.cats).join("·"), list(state.kinds).join("·"), list(state.formats).length ? `형식 ${list(state.formats).length}개` : "",
    list(state.inds).join("·"), state.q ? `검색 "${String(state.q)}"` : "", state.semantic ? "뜻으로 찾기" : "", state.notes_mine ? "내 조건만" : ""].filter(Boolean).join(" · ");
  const tests = [state.axt_recorded ? "성향 테스트" : "", state.diag_weak ? "준비도 진단" : "", list(state.car_picks).length ? "내 집 마련 전략" : "",
    list(state.hab_answers).length ? "공부 습관" : "", state.term_recorded ? "용어 퀴즈" : ""].filter(Boolean).join(", ");
  const rows: [string, string, string, string][] = [
    // [묶음, 항목, 값, 바꾸는 곳]
    ["프로필", "유형", TYPES[String(p.type)] || "", "/me"],
    ["프로필", "관심 지역", regs, "/me"],
    ["프로필", "예산", p.budget_min || p.budget_max ? `${manTxt(p.budget_min) || "-"} ~ ${manTxt(p.budget_max) || "-"}` : "", "/me"],
    ["프로필", "연소득 · 기존 부채", [manTxt(p.income), manTxt(p.debt) ? `부채 연 ${manTxt(p.debt)}` : ""].filter(Boolean).join(" · "), "/me"],
    ["프로필", "청약 가점", sub, "/me"],
    ["프로필", "전세 만기", p.lease_end ? String(p.lease_end) : "", "/me"],
    ["알림", "전세 만기 알림", p.alert_lease ? "켬 (90일·30일 전)" : "끔", "/me"],
    ["알림", "청약 공고 알림", list(p.alert_apply).length ? `${list(p.alert_apply).length}개 (접수 3일 전)` : "없음", "/calendar"],
    ["알림", "뉴스레터 구독", me?.subscribed ? "구독 중" : "구독 안 함", "/letter"],
    ["모아 보기", "관심 단지·지역", `${list(state.re_watch).length}개`, "/my-homes"],
    ["모아 보기", "관심 공고", `${list(state.apply_fav).length}개`, "/deals?tab=apply"],
    ["모아 보기", "저장한 노트", `${list(state.note_bm).length}개`, "/notes"],
    ["모아 보기", "저장한 계산", `${list(state.calc_saves).length}개`, "/calc"],
    ["화면", "노트 필터·정렬", [filt, SORTS[String(state.sort)] || ""].filter(Boolean).join(" · ") || "기본", "/notes"],
    ["화면", "계산기 입력", state.calc_inputs ? "저장됨 (다시 열면 그대로)" : "없음", "/calc"],
    ["화면", "테스트 결과", tests || "없음", "/type"],
    ["이 브라우저", "화면 테마", lsv("zipgenie-theme") === "light" ? "라이트" : lsv("zipgenie-theme") === "dark" ? "다크" : "기기 설정 따름", ""],
    ["이 브라우저", "지도 바탕", lsv("zg-map-base") === "sat" ? "위성 사진" : "일반 지도", "/map"],
    ["이 브라우저", "분양 일정 지역", lsv("zg-cal-sido") || "전국", "/calendar"],
    ["이 브라우저", "가장 비싼 거래 보기", [lsv("zg-top-sido") ? { all: "전국", 11: "서울", 41: "경기", 26: "부산" }[lsv("zg-top-sido") as "all"] : "전국", { apt: "아파트", offi: "오피스텔", nrg: "상가·업무" }[(lsv("zg-top-kind") || "apt") as "apt"]].join(" · "), "/"],
    ["이 브라우저", "목록 표시 개수", ["notes", "deals", "apply"].map((k) => `${{ notes: "노트", deals: "실거래", apply: "공고" }[k]} ${lsv(`zg-size-${k}`) || "기본"}`).join(" · "), ""],
  ];
  const groups = [...new Set(rows.map((r) => r[0]))];
  return (
    <section className="my-sec">
      <div className="my-h"><h3>내가 설정한 것 전체</h3><span className="caption">{me?.account ? "로그인 계정에 저장 · '이 브라우저' 항목만 기기마다 따로" : "이 브라우저에 저장 — 로그인하면 기기 사이에 이어져요"}</span></div>
      <div className="my-set">
        {groups.map((g) => (
          <div key={g} className="my-set-g">
            <b>{g}</b>
            <dl>
              {rows.filter((r) => r[0] === g).map(([, k, v, to]) => (
                <div key={k} className="my-set-r"><dt>{k}</dt><dd className={v ? "" : "muted"}>{v || "설정 안 함"}</dd>{to ? <Link to={to}>바꾸기</Link> : <span />}</div>
              ))}
            </dl>
          </div>
        ))}
      </div>
    </section>
  );
}


// 로그인한 기기 (2026-11-03) — GET /api/auth/sessions, 하나씩 로그아웃은 POST /api/auth/sessions/end
type Sess = { id: string; created_at: string; last_seen: string; ua: string; current: boolean };
function device(ua: string): string {
  const os = /iPhone|iPad/.test(ua) ? "iPhone·iPad" : /Android/.test(ua) ? "Android" : /Windows/.test(ua) ? "Windows" : /Mac OS/.test(ua) ? "Mac" : "기기";
  const br = /KAKAOTALK/i.test(ua) ? "카카오톡" : /NAVER/.test(ua) ? "네이버 앱" : /Edg\//.test(ua) ? "Edge" : /SamsungBrowser/.test(ua) ? "삼성 인터넷"
    : /Chrome\//.test(ua) ? "Chrome" : /Safari\//.test(ua) ? "Safari" : /Firefox\//.test(ua) ? "Firefox" : "브라우저";
  return `${os} · ${br}`;
}
function MyDevices() {
  const { data, error, reload } = useLoad(() => get<{ sessions: Sess[]; legacy: boolean }>("auth/sessions"), []);
  const [err, setErr] = useState("");
  const end = async (id: string) => {
    setErr("");
    try { await post("auth/sessions/end", { id }); reload(); } catch (e) { setErr(e instanceof Error ? e.message : "처리하지 못했습니다."); }
  };
  return (
    <section className="my-sec">
      <div className="my-h"><h3>로그인한 기기 <small>{data?.sessions.length ?? ""}</small></h3></div>
      {(error || err) && <Alert kind="err">{error || err}</Alert>}
      {data?.legacy && <p className="caption">이 브라우저는 예전 방식으로 로그인돼 목록에 없어요. 로그아웃 후 다시 로그인하면 목록에 나타나요.</p>}
      {!data ? <div className="page-loading">불러오는 중…</div> : !data.sessions.length ? <p className="caption">목록에 있는 기기가 없어요.</p> : (
        <ul className="my-list">
          {data.sessions.map((x) => (
            <li key={x.id}>
              <span className="my-dd">{x.last_seen.slice(5, 10)}</span>
              <span>{device(x.ua)}{x.current ? " (지금 이 기기)" : ""}</span>
              <span className="caption">처음 {x.created_at.slice(0, 10)} · 최근 {x.last_seen.slice(0, 16).replace("T", " ")}</span>
              {!x.current && <button type="button" className="linkish" onClick={() => end(x.id)}>로그아웃</button>}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
