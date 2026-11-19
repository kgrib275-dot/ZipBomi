// 계약 날짜로 일정 한 번에 만들기 (2026-11-19) — 매매 / 전월세 입주 / 전세 만기 역산. 고른 날짜를 내 달력(my_events)에 담는다.
// 담긴 일정은 달력·🔔·하루 전 알림(메일·푸시)·캘린더 구독에 그대로 이어진다. 계산은 브라우저에서만 (src/contractPlan.ts).
import { useMemo, useState } from "react";
import { type Kind, type PlanEvent, planBuy, planLease, planLeaseEnd } from "../contractPlan";
import { useProfile } from "../profile";
import { useMyItems } from "../pages/MyCalendar";

export default function ContractPlanner() {
  const { events, addEvents } = useMyItems();
  const { profile } = useProfile();
  const [kind, setKind] = useState<Kind>("buy");
  const [a, setA] = useState("");
  const [b, setB] = useState("");
  const [c, setC] = useState(profile?.lease_end || "");
  const [off, setOff] = useState<Record<string, boolean>>({});
  const [done, setDone] = useState("");
  const today = new Date().toLocaleDateString("sv-SE");
  const list = useMemo<PlanEvent[]>(
    () => (kind === "buy" ? planBuy(a, b) : kind === "lease" ? planLease(a, c) : planLeaseEnd(c)).sort((x, y) => x.date.localeCompare(y.date)),
    [kind, a, b, c],
  );
  const have = (e: PlanEvent) => events.some((x) => x.date === e.date && x.title === e.title);
  const key = (e: PlanEvent) => e.date + e.title;
  const pick = list.filter((e) => e.date >= today && !have(e) && !off[key(e)]);
  const add = () => { addEvents(pick); setDone(`${pick.length}건을 내 달력에 담았어요. 하루 전에 🔔·알림으로 알려 드려요.`); };
  return (
    <details className="expander contract-plan" onToggle={() => setDone("")}>
      <summary>📆 계약 날짜로 챙길 일정 한 번에 만들기</summary>
      <div className="body">
        <div className="btn-row" role="tablist" aria-label="계약 종류">
          {([["buy", "집 사는 계약"], ["lease", "전·월세 입주"], ["renew", "전세 만기 역산"]] as [Kind, string][]).map(([k, l]) => (
            <button key={k} type="button" role="tab" aria-selected={kind === k} className={`btn sm${kind === k ? " primary" : " ghost"}`} onClick={() => { setKind(k); setDone(""); }}>{l}</button>
          ))}
        </div>
        <div className="cp-in">
          {kind === "buy" && (<><label>계약일 <input type="date" value={a} onChange={(e) => setA(e.target.value)} /></label><label>잔금일 <input type="date" value={b} onChange={(e) => setB(e.target.value)} /></label></>)}
          {kind === "lease" && (<><label>입주일 <input type="date" value={a} onChange={(e) => setA(e.target.value)} /></label><label>계약 만기일 (비우면 2년) <input type="date" value={c} onChange={(e) => setC(e.target.value)} /></label></>)}
          {kind === "renew" && <label>계약 만기일 <input type="date" value={c} onChange={(e) => setC(e.target.value)} /></label>}
        </div>
        {list.length > 0 ? (
          <ul className="cp-list">
            {list.map((e) => {
              const past = e.date < today, dup = have(e);
              return (
                <li key={key(e)} className={past || dup ? "dim" : ""}>
                  <label>
                    <input type="checkbox" disabled={past || dup} checked={!past && !dup && !off[key(e)]} onChange={(x) => setOff({ ...off, [key(e)]: !x.target.checked })} />
                    <b>{e.date.slice(5).replace("-", ".")}</b> {e.title.replace(/^\[[^\]]+\] /, "")}{past ? " (지난 날짜)" : dup ? " (이미 담음)" : ""}
                  </label>
                  <span className="caption">{e.memo}</span>
                </li>
              );
            })}
          </ul>
        ) : <p className="caption">날짜를 넣으면 챙길 일정이 나와요.</p>}
        {pick.length > 0 && <div className="btn-row"><button type="button" className="btn sm primary" onClick={add}>내 달력에 {pick.length}건 담기</button></div>}
        {done && <p className="caption" role="status">{done}</p>}
        <p className="caption">법령에 정해진 기한(2026년 11월 기준)을 단순 계산한 안내예요. 증여·상속·법인·분양권, 법 개정, 휴일 연장 등은 반영하지 못하니 중요한 신고는 관할 기관·법무사·세무사에게 확인하세요.</p>
      </div>
    </details>
  );
}
