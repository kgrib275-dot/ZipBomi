// 내 공간 — 통합 달력과 항목별 메모·알림 (2026-11-02).
// 달력: 관심·알림 공고의 접수 시작·마감·발표, 전세 만기, 항목에 단 알림 날짜, 직접 넣은 일정(my_events)을 한 달력에.
// 항목 메모·알림(my_items): {키: {title, memo, remind(YYYY-MM-DD), remind_note}} — 알림 날짜가 다가오면 상단 🔔에 뜬다(/api/me/alerts).
import { useMemo, useState } from "react";
import { useMe } from "../me";
import { useTodos } from "./MyTools";

export type MyItem = { title?: string; memo?: string; remind?: string; remind_note?: string };
type Ev = { date: string; label: string; kind: "start" | "end" | "win" | "lease" | "remind" | "event"; title: string; key?: string };
type NoticeLite = { notice_id: string; name: string; receipt_start: string | null; receipt_end: string | null; winner_date: string | null };

const DOW = ["일", "월", "화", "수", "목", "금", "토"];
const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

export function useMyItems() {
  const { state, setState } = useMe();
  const items = (state.my_items && typeof state.my_items === "object" ? state.my_items : {}) as Record<string, MyItem>;
  const events = (Array.isArray(state.my_events) ? state.my_events : []) as { id: string; date: string; title: string; memo?: string }[];
  const setItem = (key: string, v: MyItem | null) => {
    const next = { ...items };
    if (!v || (!v.memo && !v.remind)) delete next[key]; else next[key] = v;
    setState({ my_items: next });
  };
  const addEvent = (date: string, title: string, memo = "") =>
    setState({ my_events: [...events, { id: Math.random().toString(36).slice(2, 10), date, title: title.slice(0, 80), memo: memo.slice(0, 300) }].slice(-100) });
  const delEvent = (id: string) => setState({ my_events: events.filter((e) => e.id !== id) });
  return { items, events, setItem, addEvent, delEvent };
}

/** 항목 하나의 메모·알림 버튼과 펼침 편집기 */
export function ItemNote({ k, title }: { k: string; title: string }) {
  const { items, setItem } = useMyItems();
  const cur = items[k] || {};
  const [open, setOpen] = useState(false);
  const [memo, setMemo] = useState(cur.memo || "");
  const [remind, setRemind] = useState(cur.remind || "");
  const [note, setNote] = useState(cur.remind_note || "");
  const stop = (e: React.SyntheticEvent) => { e.preventDefault(); e.stopPropagation(); };
  const save = () => { setItem(k, { title, memo: memo.trim().slice(0, 500), remind, remind_note: note.trim().slice(0, 100) }); setOpen(false); };
  return (
    <span className="in-wrap" onClick={(e) => e.stopPropagation()}>
      <button type="button" className={`in-btn${cur.memo || cur.remind ? " on" : ""}`} onClick={(e) => { stop(e); setOpen(!open); }}
        title="이 항목에 메모·알림 달기">{cur.remind ? `🔔 ${cur.remind.slice(5).replace("-", ".")}` : cur.memo ? "📝 메모" : "📝 메모·알림"}</button>
      {cur.memo && !open && <span className="in-memo">{cur.memo}</span>}
      {open && (
        <span className="in-pop" onClick={stop}>
          <textarea rows={2} maxLength={500} value={memo} onChange={(e) => setMemo(e.target.value)} placeholder="메모 (예: 남향·로열층만, 은행 상담 11/10)" />
          <span className="in-row">
            <label>알림 날짜 <input type="date" value={remind} onChange={(e) => setRemind(e.target.value)} /></label>
            <input type="text" maxLength={100} value={note} onChange={(e) => setNote(e.target.value)} placeholder="알림 내용 (선택)" />
          </span>
          <span className="in-row">
            <button type="button" className="btn sm primary" onClick={save}>저장</button>
            {(cur.memo || cur.remind) && <button type="button" className="btn sm ghost" onClick={() => { setItem(k, null); setMemo(""); setRemind(""); setNote(""); setOpen(false); }}>지우기</button>}
            <button type="button" className="btn sm ghost" onClick={() => setOpen(false)}>닫기</button>
          </span>
          <span className="caption">알림 날짜 3일 전부터 맨 위 🔔에 떠요.</span>
        </span>
      )}
    </span>
  );
}

/** 통합 달력 */
export function MyCalendar({ apply, alerts, lease, side }: { apply: NoticeLite[]; alerts: string[]; lease?: string; side?: React.ReactNode }) {
  const { items, events, addEvent, delEvent } = useMyItems();
  const todos = useTodos().list;
  const [ym, setYm] = useState(() => new Date().toISOString().slice(0, 7));
  const [day, setDay] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const evs = useMemo(() => {
    const out: Ev[] = [];
    for (const n of apply) {
      const tag = alerts.includes(n.notice_id) ? "🔔 " : "";
      if (n.receipt_start) out.push({ date: n.receipt_start, label: "접수", kind: "start", title: tag + n.name });
      if (n.receipt_end) out.push({ date: n.receipt_end, label: "마감", kind: "end", title: tag + n.name });
      if (n.winner_date) out.push({ date: n.winner_date, label: "발표", kind: "win", title: tag + n.name });
    }
    if (lease) out.push({ date: lease, label: "만기", kind: "lease", title: "전세 만기" });
    for (const [k, v] of Object.entries(items)) if (v.remind) out.push({ date: v.remind, label: "알림", kind: "remind", title: `${v.title || "내 항목"}${v.remind_note ? ` — ${v.remind_note}` : ""}`, key: k });
    for (const e of events) out.push({ date: e.date, label: "일정", kind: "event", title: e.title, key: e.id });
    for (const t of todos) if (t.due && !t.done) out.push({ date: t.due, label: "할 일", kind: "remind", title: t.text });
    return out;
  }, [apply, alerts, lease, items, events, todos]);
  const [y, m] = ym.split("-").map(Number);
  const first = new Date(y, m - 1, 1).getDay(), days = new Date(y, m, 0).getDate();
  const cells: (string | null)[] = [...Array(first).fill(null), ...Array.from({ length: days }, (_, i) => `${ym}-${String(i + 1).padStart(2, "0")}`)];
  while (cells.length % 7) cells.push(null);
  const today = iso(new Date());
  const shift = (k: number) => { const d = new Date(y, m - 1 + k, 1); setYm(iso(d).slice(0, 7)); setDay(null); };
  const upcoming = evs.filter((e) => (day ? e.date === day : e.date >= today)).sort((a, b) => a.date.localeCompare(b.date)).slice(0, day ? 50 : 8);
  return (
    <section className="my-sec">
      <div className="my-h"><h3>내 일정 달력</h3><span className="caption">관심·알림 공고 · 전세 만기 · 내 알림 · 내 일정</span></div>
      <div className="mycal">
        <div className="mcal">
          <div className="mcal-h">
            <button type="button" className="btn sm ghost" onClick={() => shift(-1)} aria-label="이전 달">‹</button>
            <b>{y}년 {m}월</b>
            <button type="button" className="btn sm ghost" onClick={() => shift(1)} aria-label="다음 달">›</button>
          </div>
          <div className="mcal-g">
            {DOW.map((w, i) => <span key={w} className={`mcal-w${i === 0 ? " sun" : ""}`}>{w}</span>)}
            {cells.map((d, i) => {
              if (!d) return <span key={i} />;
              const es = evs.filter((e) => e.date === d);
              return (
                <button key={d} type="button" className={`mcal-d${d === today ? " today" : ""}${d === day ? " on" : ""}${es.length ? " has" : ""}`}
                  onClick={() => setDay(d === day ? null : d)} aria-label={`${Number(d.slice(8))}일 ${es.length}건`}>
                  <span className="n">{Number(d.slice(8))}</span>
                  <span className="dots">{[...new Set(es.map((e) => e.kind))].slice(0, 3).map((k) => <i key={k} className={`k-${k}`} />)}</span>
                </button>
              );
            })}
          </div>
          <div className="mcal-lg"><i className="k-start" />접수 <i className="k-end" />마감 <i className="k-win" />발표 <i className="k-remind" />알림 <i className="k-event" />일정</div>
        </div>
        <div className="mycal-list">
          <b>{day ? `${Number(day.slice(5, 7))}월 ${Number(day.slice(8))}일` : "다가오는 일정"}</b>
          {!upcoming.length ? <p className="caption">{day ? "이날 일정이 없어요." : "다가오는 일정이 없어요. 공고에 🔔·☆를 누르거나 아래에서 일정을 넣어 보세요."}</p> : (
            <ul>
              {upcoming.map((e, i) => (
                <li key={i}><span className={`mtag k-${e.kind}`}>{e.label}</span><span className="d">{e.date.slice(5).replace("-", ".")}</span>
                  <span className="t">{e.title}</span>
                  {e.kind === "event" && e.key && <button type="button" className="my-x" aria-label="일정 지우기" onClick={() => delEvent(e.key!)}>×</button>}</li>
              ))}
            </ul>
          )}
          <form className="mycal-add" onSubmit={(ev) => { ev.preventDefault(); if (title.trim()) { addEvent(day || today, title.trim()); setTitle(""); } }}>
            <input type="text" maxLength={80} value={title} onChange={(e) => setTitle(e.target.value)} placeholder={`${(day || today).slice(5).replace("-", ".")} 일정 추가 (예: 임장, 은행 상담)`} />
            <button className="btn sm primary" disabled={!title.trim()}>추가</button>
          </form>
          {side}
        </div>
      </div>
    </section>
  );
}
