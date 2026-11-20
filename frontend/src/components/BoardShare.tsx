// 함께 보기 링크 (2026-11-20) — 내 관심 단지·관심 공고를 가족·친구에게 읽기 전용으로 보여 준다. 서버: /api/me/board (api/routers/board.py), 공개 페이지 /g/<토큰>.
// 링크는 만들 때 한 번만 보여 준다(서버에는 해시만). 일부러 ShareBar(공유 기록에 주소가 남음)를 쓰지 않고 복사·기기 공유 버튼만 둔다.
import { useEffect, useState } from "react";
import { ApiError, del, get, post } from "../api";

type St = { on: boolean; include?: string[]; expires_at?: string; views?: number; last_view_at?: string | null };

export default function BoardShare() {
  const [st, setSt] = useState<St | null>(null);
  const [url, setUrl] = useState("");
  const [apts, setApts] = useState(true);
  const [notices, setNotices] = useState(true);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  useEffect(() => { get<St>("me/board").then(setSt).catch(() => setSt({ on: false })); }, []);
  const make = async () => {
    if (st?.on && !window.confirm("새 링크를 만들면 지금 쓰는 링크는 바로 멈춰요. 만들까요?")) return;
    setBusy(true); setMsg("");
    try {
      const r = await post<{ url: string; include: string[]; expires_at: string }>("me/board", { include: [...(apts ? ["apts"] : []), ...(notices ? ["notices"] : [])] });
      setUrl(r.url); setSt({ on: true, include: r.include, expires_at: r.expires_at, views: 0 });
    } catch (e) { setMsg(e instanceof ApiError ? e.message : "만들지 못했어요."); } finally { setBusy(false); }
  };
  const stop = async () => {
    if (!window.confirm("링크를 멈출까요? 받은 사람은 더 이상 볼 수 없어요.")) return;
    setBusy(true);
    try { await del("me/board"); setUrl(""); setSt({ on: false }); setMsg("링크를 멈췄어요."); } catch { setMsg("멈추지 못했어요."); } finally { setBusy(false); }
  };
  const copy = async () => { try { await navigator.clipboard.writeText(url); setMsg("복사했어요 — 카톡에 붙여 넣으세요 ✓"); } catch { window.prompt("주소를 복사하세요", url); } };
  const native = () => { navigator.share({ title: "함께 보는 관심 보드", text: "내 관심 단지와 청약 공고예요", url }).catch(() => undefined); };
  return (
    <details className="expander board-share">
      <summary>👪 가족·친구와 함께 보기 (읽기 전용 링크){st?.on ? " · 켜짐" : ""}</summary>
      <div className="body">
        <p className="caption" style={{ marginTop: 0 }}>링크를 받은 사람은 가입 없이 내가 고른 항목만 봐요. <b>일정·할 일·메모·예산·소득·이메일은 보이지 않고</b>, 만든 지 30일 뒤 저절로 닫혀요. 언제든 멈출 수 있어요.</p>
        <label className="check"><input type="checkbox" checked={apts} onChange={(e) => setApts(e.target.checked)} /> 관심 단지 (최근 거래)</label>
        <label className="check"><input type="checkbox" checked={notices} onChange={(e) => setNotices(e.target.checked)} /> 관심 청약 공고 (일정)</label>
        {url && (
          <div className="board-url">
            <input type="text" readOnly value={url} onFocus={(e) => e.target.select()} aria-label="함께 보기 링크" />
            <div className="btn-row">
              <button type="button" className="btn sm primary" onClick={copy}>링크 복사</button>
              {typeof navigator !== "undefined" && "share" in navigator && <button type="button" className="btn sm" onClick={native}>공유하기</button>}
            </div>
            <p className="caption">이 링크는 지금 한 번만 보여 드려요. 잃어버리면 '새 링크 만들기'를 누르세요(예전 링크는 멈춰요).</p>
          </div>
        )}
        {st?.on && !url && <p className="caption">링크를 쓰는 중이에요 · 열람 {st.views ?? 0}회 · {String(st.expires_at || "").slice(0, 10)}까지 · {(st.include || []).map((k) => (k === "apts" ? "관심 단지" : "관심 공고")).join("·")}</p>}
        <div className="btn-row">
          <button type="button" className="btn sm" disabled={busy || (!apts && !notices)} onClick={make}>{st?.on ? "새 링크 만들기" : "링크 만들기"}</button>
          {st?.on && <button type="button" className="btn sm ghost" disabled={busy} onClick={stop}>링크 멈추기</button>}
        </div>
        {msg && <p className="caption" role="status">{msg}</p>}
      </div>
    </details>
  );
}
