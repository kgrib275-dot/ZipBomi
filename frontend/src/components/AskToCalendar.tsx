// 보미AI 답변 → 내 달력 (2026-11-17). 답변 글에서 날짜를 규칙으로 찾아(AI 호출 없음) 후보로 보여 주고,
// 고른 것만 내 공간 '내 일정'(my_events)에 담는다. 담은 뒤에는 구글 캘린더 링크·.ics 로 바깥 캘린더에도 보낼 수 있다.
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { type CalEvent, downloadIcs, findDates, googleCalUrl } from "../calendarLink";
import { useMyItems } from "../pages/MyCalendar";

type Row = { on: boolean; date: string; title: string; memo: string };

const fullUrl = (u?: string) => (!u ? "" : u.startsWith("/") ? window.location.origin + u : u);

export default function AskToCalendar({ text, compact = false }: { text: string; compact?: boolean }) {
  const { addEvents } = useMyItems();
  const [open, setOpen] = useState(false);
  const [saved, setSaved] = useState<CalEvent[] | null>(null);
  const hits = useMemo(() => (open ? findDates(text) : []), [open, text]);
  const [rows, setRows] = useState<Row[] | null>(null);
  const today = new Date();
  const todayIso = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;

  const start = () => {
    const hs = findDates(text);
    const base = hs.length ? hs : [{ date: todayIso, title: "", line: "", url: undefined }];
    setRows(base.map((h) => ({
      on: !!hs.length && h.date >= todayIso,
      date: h.date, title: h.title,
      memo: ["보미AI 답변에서 담음", h.line, fullUrl(h.url)].filter(Boolean).join("\n").slice(0, 300),
    })));
    setSaved(null);
    setOpen(true);
  };
  const set = (i: number, patch: Partial<Row>) => setRows((rs) => (rs || []).map((r, k) => (k === i ? { ...r, ...patch } : r)));
  const picked = (rows || []).filter((r) => r.on && /^\d{4}-\d{2}-\d{2}$/.test(r.date) && r.title.trim());
  const save = () => {
    if (!picked.length) return;
    const list = picked.map((r) => ({ date: r.date, title: r.title.trim().slice(0, 80), memo: r.memo }));
    addEvents(list);
    setSaved(list);
  };

  if (!open) {
    return <button type="button" className={`btn sm a2c-btn${compact ? " ghost" : ""}`} onClick={start} title="답변에 나온 날짜를 내 달력에 담기">📅 일정 담기</button>;
  }
  return (
    <div className={`a2c${compact ? " compact" : ""}`}>
      {saved ? (
        <>
          <p className="a2c-h">✅ 내 달력에 {saved.length}건 담았어요. <Link to="/my">내 공간에서 보기</Link></p>
          <ul className="a2c-done">
            {saved.map((e, i) => (
              <li key={i}><span className="d">{e.date.slice(5).replace("-", ".")}</span><span className="t">{e.title}</span>
                <a href={googleCalUrl(e)} target="_blank" rel="noopener noreferrer" title="구글 캘린더에 추가 (구글 화면이 열려요)">G+ 구글</a></li>
            ))}
          </ul>
          <div className="a2c-row">
            <button type="button" className="btn sm" onClick={() => downloadIcs(saved)}>📥 .ics 받기</button>
            <button type="button" className="btn sm ghost" onClick={() => setOpen(false)}>닫기</button>
          </div>
          <p className="caption">.ics 파일은 아이폰·아웃룩·삼성 캘린더에서 열면 담겨요.</p>
        </>
      ) : (
        <>
          <p className="a2c-h">{hits.length ? `답변에서 날짜 ${hits.length}개를 찾았어요. 담을 것만 고르고 제목을 다듬어 주세요.` : "답변에서 날짜를 찾지 못했어요. 직접 날짜와 제목을 넣어 담을 수 있어요."}</p>
          <ul className="a2c-list">
            {(rows || []).map((r, i) => (
              <li key={i} className={r.on ? "on" : ""}>
                <input type="checkbox" checked={r.on} onChange={(e) => set(i, { on: e.target.checked })} aria-label="이 일정 담기" />
                <input type="date" value={r.date} onChange={(e) => set(i, { date: e.target.value, on: true })} aria-label="날짜" />
                <input type="text" value={r.title} maxLength={80} placeholder="일정 제목 (예: OO단지 접수 마감)" onChange={(e) => set(i, { title: e.target.value, on: true })} aria-label="제목" />
              </li>
            ))}
          </ul>
          {hits.length > 0 && <p className="caption">지난 날짜는 처음에 꺼 둬요. 날짜는 글에서 규칙으로 찾은 거라 공고 원문과 꼭 맞춰 보세요.</p>}
          <div className="a2c-row">
            <button type="button" className="btn sm primary" disabled={!picked.length} onClick={save}>내 달력에 {picked.length}건 담기</button>
            <button type="button" className="btn sm ghost" onClick={() => setRows((rs) => [...(rs || []), { on: true, date: todayIso, title: "", memo: "보미AI 답변에서 담음" }])}>+ 직접 추가</button>
            <button type="button" className="btn sm ghost" onClick={() => setOpen(false)}>닫기</button>
          </div>
        </>
      )}
    </div>
  );
}
