// 내 공간 도구 (2026-11-02) — 할 일 체크리스트(my_todos), 관심 단지 비교 표, 내 데이터 내보내기·가져오기(백업).
import { useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useMe } from "../me";
import { man } from "../policy";

export type Todo = { id: string; text: string; done?: boolean; due?: string };
const KEYS = ["profile", "re_watch", "apply_fav", "note_bm", "calc_saves", "calc_inputs", "my_memo", "my_items", "my_events", "my_todos", "notes_mine"];

export function useTodos() {
  const { state, setState } = useMe();
  const list = (Array.isArray(state.my_todos) ? state.my_todos : []) as Todo[];
  return {
    list,
    add: (text: string, due = "") => setState({ my_todos: [...list, { id: Math.random().toString(36).slice(2, 10), text: text.slice(0, 120), due }].slice(-200) }),
    toggle: (id: string) => setState({ my_todos: list.map((t) => (t.id === id ? { ...t, done: !t.done } : t)) }),
    remove: (id: string) => setState({ my_todos: list.filter((t) => t.id !== id) }),
    clearDone: () => setState({ my_todos: list.filter((t) => !t.done) }),
  };
}

const PRESET = ["은행 대출 상담 예약", "등기부등본 확인", "임장 체크리스트 작성", "청약통장 납입 확인", "전세 계약 갱신 의사 통보"];

export function TodoBox() {
  const { list, add, toggle, remove, clearDone } = useTodos();
  const [text, setText] = useState("");
  const [due, setDue] = useState("");
  const open = list.filter((t) => !t.done).sort((a, b) => (a.due || "9999").localeCompare(b.due || "9999"));
  const done = list.filter((t) => t.done);
  const today = new Date().toISOString().slice(0, 10);
  return (
    <section className="my-sec">
      <div className="my-h"><h3>할 일 <small>{open.length}</small></h3>{done.length > 0 && <button type="button" className="linkish" onClick={clearDone}>끝낸 일 {done.length}개 지우기</button>}</div>
      <form className="td-add" onSubmit={(e) => { e.preventDefault(); if (text.trim()) { add(text.trim(), due); setText(""); setDue(""); } }}>
        <input type="text" maxLength={120} value={text} onChange={(e) => setText(e.target.value)} placeholder="예: 은행 대출 상담, 등기부 확인" />
        <input type="date" value={due} onChange={(e) => setDue(e.target.value)} aria-label="마감일" title="마감일 (3일 전부터 🔔에 떠요)" />
        <button className="btn sm primary" disabled={!text.trim()}>추가</button>
      </form>
      {!list.length && <div className="td-preset">{PRESET.map((p) => <button key={p} type="button" className="pill sm" onClick={() => add(p)}>+ {p}</button>)}</div>}
      <ul className="td-list">
        {[...open, ...done].map((t) => (
          <li key={t.id} className={t.done ? "done" : ""}>
            <label><input type="checkbox" checked={!!t.done} onChange={() => toggle(t.id)} /> <span>{t.text}</span></label>
            {t.due && <span className={`td-due${!t.done && t.due < today ? " late" : !t.done && t.due <= today ? " today" : ""}`}>{t.due.slice(5).replace("-", ".")}</span>}
            <button type="button" className="my-x" aria-label="지우기" onClick={() => remove(t.id)}>×</button>
          </li>
        ))}
      </ul>
    </section>
  );
}

type W = { lawd: string; region: string; apt: string; dong: string; deals_6m: number; pp_recent: number | null; change_pct: number | null;
  last: { date: string; amount: number; area: number | null } | null };

/** 관심 단지 비교 — 3.3㎡가·변동·거래량·마지막 거래를 한 표에, 열 이름으로 정렬 */
export function CompareTable({ watch }: { watch: W[] }) {
  const [by, setBy] = useState<"pp_recent" | "change_pct" | "deals_6m">("pp_recent");
  const rows = [...watch].filter((w) => w.apt).sort((a, b) => ((b[by] as number) ?? -1e9) - ((a[by] as number) ?? -1e9));
  if (rows.length < 2) return null;
  const max = Math.max(1, ...rows.map((r) => r.pp_recent || 0));
  const th = (k: typeof by, l: string) => <th className="num"><button type="button" className={`lr-th${by === k ? " on" : ""}`} onClick={() => setBy(k)}>{l}{by === k ? " ↓" : ""}</button></th>;
  return (
    <section className="my-sec">
      <div className="my-h"><h3>관심 단지 비교 <small>{rows.length}</small></h3><span className="caption">최근 3개월 실거래 기준</span></div>
      <div className="table-wrap">
        <table className="table">
          <thead><tr><th>단지</th>{th("pp_recent", "3.3㎡ 중위")}{th("change_pct", "직전 3개월 대비")}{th("deals_6m", "6개월 거래")}<th>마지막 거래</th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.lawd + r.dong + r.apt}>
                <td><Link to={`/my-homes?lawd=${r.lawd}&dong=${encodeURIComponent(r.dong)}&apt=${encodeURIComponent(r.apt)}`}><b>{r.apt}</b></Link><div className="caption">{r.region} {r.dong}</div></td>
                <td className="num">{r.pp_recent ? man(r.pp_recent) : "-"}<span className="lr-bar"><i style={{ width: `${((r.pp_recent || 0) / max) * 100}%` }} /></span></td>
                <td className="num"><span className={`lr-v${(r.change_pct ?? 0) > 0 ? " up" : (r.change_pct ?? 0) < 0 ? " down" : ""}`}>{r.change_pct === null ? "-" : `${r.change_pct > 0 ? "+" : ""}${r.change_pct}%`}</span></td>
                <td className="num">{r.deals_6m}건</td>
                <td className="caption">{r.last ? `${r.last.date.slice(2).replace(/-/g, ".")} · ${man(r.last.amount)}` : "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

/** 내 데이터 내보내기·가져오기 — 저장한 모든 것을 파일로 백업하고 되살린다 */
export function DataBackup() {
  const { state, setState, flush } = useMe();
  const file = useRef<HTMLInputElement>(null);
  const [msg, setMsg] = useState("");
  const out = () => {
    const data: Record<string, unknown> = { _app: "zipbomi", _at: new Date().toISOString() };
    for (const k of KEYS) if (state[k] !== undefined) data[k] = state[k];
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = `집보미_내공간_${new Date().toISOString().slice(0, 10)}.json`; a.click(); URL.revokeObjectURL(a.href);
    setMsg("내려받았어요. 이 파일로 언제든 되살릴 수 있어요.");
  };
  const inp = async (f: File) => {
    try {
      const d = JSON.parse(await f.text());
      if (!d || d._app !== "zipbomi") throw new Error("집보미에서 내려받은 파일이 아니에요.");
      if (!window.confirm("이 파일의 내용으로 내 공간을 덮어쓸까요? (지금 저장된 같은 항목은 파일 내용으로 바뀝니다)")) return;
      const patch: Record<string, unknown> = {};
      for (const k of KEYS) if (d[k] !== undefined) patch[k] = d[k];
      setState(patch); await flush();
      setMsg("되살렸어요.");
    } catch (e) { setMsg(e instanceof Error ? e.message : "읽지 못했어요."); }
  };
  return (
    <section className="my-sec">
      <div className="my-h"><h3>내 데이터 백업</h3></div>
      <div className="bk-row">
        <button type="button" className="btn sm" onClick={out}>⬇ 내 공간 내려받기 (JSON)</button>
        <button type="button" className="btn sm ghost" onClick={() => file.current?.click()}>⬆ 파일로 되살리기</button>
        <input ref={file} type="file" accept="application/json,.json" hidden onChange={(e) => { const f = e.target.files?.[0]; if (f) inp(f); e.target.value = ""; }} />
        {msg && <span className="caption">{msg}</span>}
      </div>
      <p className="caption">관심 단지·공고·노트·계산·메모·알림·일정·할 일·프로필을 한 파일로 받아 둘 수 있어요. 로그인하면 서버에도 계속 보관됩니다.</p>
    </section>
  );
}
