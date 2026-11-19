// 최근 본 것 이어 보기 (2026-11-19) — 홈 맨 위 한 줄. 이 브라우저에 남긴 기록만 쓰며(src/recent.ts) 없으면 그리지 않는다.
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { type Recent, clearRecent, getRecent, recentIcon, recordRecent } from "../recent";

export default function RecentStrip() {
  const [list, setList] = useState(getRecent);
  if (!list.length) return null;
  return (
    <nav className="recent-strip" aria-label="최근 본 것">
      <span className="caption">이어 보기</span>
      {list.slice(0, 5).map((r) => <Link key={r.to} className="pill" to={r.to} title={r.sub || r.title}>{recentIcon(r.kind)} {r.title.length > 18 ? r.title.slice(0, 18) + "…" : r.title}</Link>)}
      <button type="button" className="linkish" onClick={() => { clearRecent(); setList([]); }} title="이 브라우저의 최근 본 기록 지우기">지우기</button>
    </nav>
  );
}

/** 화면에 보이지 않는 기록용 — 열려 있는 동안 한 번 '최근 본 것'에 남긴다 */
export function RecordRecent({ r }: { r: Recent }) {
  useEffect(() => { recordRecent(r); }, [r.to]); // eslint-disable-line react-hooks/exhaustive-deps
  return null;
}
