// 보미AI 답변의 근거 자료 (2026-11-17) — 근거 노트마다 ☆ 를 눌러 내 공간 '저장한 노트'(note_bm)에 남긴다.
// 대화는 탭을 닫으면 사라지지만 저장한 노트는 계정(로그인 전에는 이 브라우저)에 남는다. 기사는 원문 링크만.
import { Link } from "react-router-dom";
import { useBookmarks } from "./NoteCard";

export type Source = { title: string; url: string; kind: string; sim: number };

/** 노트 주소(/notes?id=12 · {사이트}/notes?id=12)에서 번호 */
export function noteId(s: Source): number | null {
  if (s.kind !== "노트") return null;
  const m = /\/notes\?(?:.*&)?id=(\d+)/.exec(s.url);
  return m ? Number(m[1]) : null;
}

export default function AskSources({ sources, compact = false }: { sources: Source[]; compact?: boolean }) {
  const [bm, toggle] = useBookmarks();
  if (!sources.length) return null;
  const saved = sources.filter((s) => { const id = noteId(s); return id !== null && bm.has(id); }).length;
  return (
    <details className={`expander ask-src${compact ? " compact" : ""}`}>
      <summary>📖 근거 자료 {sources.length}{saved ? ` · ☆ ${saved}개 저장` : ""}</summary>
      <ul className="body srcs">
        {sources.map((s, k) => {
          const id = noteId(s);
          const on = id !== null && bm.has(id);
          return (
            <li key={k}>
              {id !== null && (
                <button type="button" className={`src-bm${on ? " on" : ""}`} onClick={() => toggle(id)} aria-pressed={on}
                  title={on ? "저장한 노트에서 빼기" : "내 공간 '저장한 노트'에 담기"} aria-label={`${s.title} ${on ? "저장 취소" : "저장"}`}>{on ? "★" : "☆"}</button>
              )}
              {id !== null ? <Link to={`/notes?id=${id}`}>{s.title}</Link> : <a href={s.url} target="_blank" rel="noopener noreferrer">{s.title}</a>}
              <span className="caption"> · {s.kind}{compact ? "" : ` · 유사도 ${Number(s.sim).toFixed(2)}`}</span>
            </li>
          );
        })}
      </ul>
      {saved > 0 && <p className="caption src-foot">저장한 노트는 <Link to="/my">내 공간</Link>에서 다시 볼 수 있어요.</p>}
    </details>
  );
}
