// 노트 카드 — 목록·홈·추천에서 공용. ☆ 저장은 방문자 상태 note_bm (로그인하면 어느 기기에서든, 2026-11-02).
import { useEffect, useMemo } from "react";
import { Link } from "react-router-dom";
import { useMe } from "../me";

export type NoteCardData = {
  id: number; title: string; category: string; kind: string; summary: string; published: string; source?: string;
  tags?: string; audiences?: string; industries?: string[]; similarity?: number; views?: number; format?: string;
};
// 노트 형식 (Phase 4, backend/pipeline/note_format.py)
export const FORMATS: Record<string, string> = { brief: "3분 요약", deep: "깊이 읽기", data: "숫자로 보기" };

const KEY = "zipgenie-bookmarks";
export function loadBookmarks(): Set<number> {
  try { return new Set(JSON.parse(localStorage.getItem(KEY) || "[]")); } catch { return new Set(); }
}
export function saveBookmarks(s: Set<number>) {
  try { localStorage.setItem(KEY, JSON.stringify([...s])); } catch { /* 사생활 보호 모드 */ }
}
export function useBookmarks(): [Set<number>, (id: number) => void] {
  const { me, state, setState } = useMe();
  const list = useMemo(() => (Array.isArray(state.note_bm) ? (state.note_bm as unknown[]).filter((x): x is number => typeof x === "number") : []), [state.note_bm]);
  // 예전 브라우저 저장분 옮기기 (한 번)
  useEffect(() => {
    if (!me) return;
    const old = loadBookmarks();
    if (!old.size) return;
    const merged = [...new Set([...list, ...old])].slice(0, 100);
    setState({ note_bm: merged });
    saveBookmarks(new Set());
  }, [me]); // eslint-disable-line react-hooks/exhaustive-deps
  const bm = useMemo(() => new Set(list), [list]);
  return [bm, (id) => setState({ note_bm: bm.has(id) ? list.filter((x) => x !== id) : [id, ...list].slice(0, 100) })];
}

export default function NoteCard({ n, fresh, bookmarked, onBookmark }: { n: NoteCardData; fresh?: boolean; bookmarked?: boolean; onBookmark?: (id: number) => void }) {
  return (
    <Link to={`/notes?id=${n.id}`} className={`card ${fresh ? "fresh" : ""}`}>
      {onBookmark && (
        <button type="button" className={`ax-bm ${bookmarked ? "on" : ""}`} aria-label="북마크" title="북마크"
          onClick={(e) => { e.preventDefault(); e.stopPropagation(); onBookmark(n.id); }}>{bookmarked ? "★" : "☆"}</button>
      )}
      <div className="meta"><span className="chip">{n.category}</span><span>{n.kind}</span>{n.format && FORMATS[n.format] && <span className="fmt-badge">{FORMATS[n.format]}</span>}{n.published && <span>· {n.published}</span>}</div>
      <h3>{n.title}</h3>
      <p>{n.summary}</p>
      {(n.industries?.length || n.similarity !== undefined) && (
        <div className="meta">
          {n.industries?.map((i) => <span key={i}>#{i}</span>)}
          {n.similarity !== undefined && <span>유사도 {n.similarity.toFixed(2)}</span>}
        </div>
      )}
    </Link>
  );
}
