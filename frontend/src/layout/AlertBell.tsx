// 상단 🔔 — 내가 켠 청약 접수·전세 만기 알림과 상태 (2026-11-02). GET /api/me/alerts.
// 메일은 구독을 확인한 브라우저에만 간다 — 여기서는 메일과 관계없이 '언제 무엇이 다가오는지'를 바로 보여 준다.
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { get } from "../api";
import { useDialogs } from "../components/Dialogs";
import { useMe } from "../me";

type Item = { kind: "apply" | "lease" | "custom"; id: string; title: string; region: string; what: string; due: string | null; left: number | null;
  state: "wait" | "soon" | "sent" | "past"; sent_at: string | null; url: string; mail_on: string | null };
type Res = { items: Item[]; subscribed: boolean; urgent: number };

const md = (s: string | null) => (s ? `${Number(s.slice(5, 7))}.${Number(s.slice(8, 10))}` : "-");

export default function AlertBell() {
  const { state } = useMe();
  const { openSubscribe } = useDialogs();
  const [data, setData] = useState<Res | null>(null);
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const prof = state.profile as { alert_apply?: string[]; alert_lease?: boolean; lease_end?: string } | undefined;
  // 내 공간 항목 알림·내 일정(my_items·my_events)이 바뀌어도 다시 받는다
  const key = `${(prof?.alert_apply || []).join(",")}|${prof?.alert_lease ? prof?.lease_end : ""}|${JSON.stringify(state.my_items || {}).length}|${JSON.stringify(state.my_events || []).length}`;
  useEffect(() => {
    if (key === "||2|2") { setData({ items: [], subscribed: false, urgent: 0 }); return; }
    const t = window.setTimeout(() => get<Res>("me/alerts").then(setData).catch(() => undefined), 600); // 저장(0.4초 모음) 뒤에
    return () => window.clearTimeout(t);
  }, [key]);
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false); };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDoc); document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDoc); document.removeEventListener("keydown", onKey); };
  }, [open]);
  const items = data?.items || [];
  const badge = data?.urgent || 0;
  return (
    <div className="bell" ref={box}>
      <button type="button" className={`btn sm ghost bell-btn${badge ? " hot" : ""}`} aria-expanded={open} aria-haspopup="dialog"
        aria-label={`알림 ${items.length}개${badge ? `, 곧 다가오는 일정 ${badge}개` : ""}`} onClick={() => setOpen(!open)} title="내 알림">
        <span aria-hidden="true">🔔</span>{items.length > 0 && <b className="bell-n">{badge || items.length}</b>}
      </button>
      {open && (
        <div className="bell-pop" role="dialog" aria-label="내 알림">
          <div className="bell-h"><b>내 알림</b><span className="caption">{items.length ? `${items.length}개` : ""}</span></div>
          {!items.length ? (
            <p className="bell-empty">아직 켠 알림이 없어요.<br /><Link to="/calendar" onClick={() => setOpen(false)}>청약 일정</Link>에서 공고마다 🔔를 누르거나,{" "}
              <Link to="/me" onClick={() => setOpen(false)}>내 프로필</Link>에서 전세 만기 알림을 켜 보세요.</p>
          ) : (
            <ul className="bell-list">
              {items.map((x) => {
                const tag = x.state === "sent" ? "메일 보냄" : x.state === "past" ? "지남" : x.left === 0 ? "오늘" : x.left !== null ? `D-${x.left}` : "-";
                const body = (
                  <>
                    <span className={`bell-tag s-${x.state}`}>{tag}</span>
                    <span className="bell-t">{x.title}</span>
                    <span className="bell-m">{x.kind === "custom" ? `${x.what} · ${md(x.due)}` : x.kind === "lease" ? `만기 ${md(x.due)}` : `${x.region ? x.region + " · " : ""}${x.what} ${md(x.due)}`}
                      {x.state === "wait" && x.mail_on && data?.subscribed ? ` · ${md(x.mail_on)} 메일 예정` : ""}</span>
                  </>
                );
                return <li key={x.kind + x.id}>{x.url.startsWith("/") ? <Link to={x.url} onClick={() => setOpen(false)}>{body}</Link>
                  : x.url ? <a href={x.url} target="_blank" rel="noopener">{body}</a> : <div>{body}</div>}</li>;
              })}
            </ul>
          )}
          {!data?.subscribed && items.length > 0 && (
            <div className="bell-foot">메일로도 받으려면 <button type="button" className="linkish" onClick={() => { setOpen(false); openSubscribe("bell"); }}>뉴스레터를 구독</button>하세요. 구독 전에는 여기서만 보여요.</div>
          )}
          <div className="bell-foot"><Link to="/calendar" onClick={() => setOpen(false)}>청약 일정에서 알림 관리 →</Link></div>
        </div>
      )}
    </div>
  );
}
