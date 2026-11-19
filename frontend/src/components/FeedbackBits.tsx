// 사용자 피드백 (2026-11-19) — AnswerRating: 보미AI 답변 👍👎, ReportData: 숫자 옆 '이상해요'. POST /api/feedback → 관리 > 피드백.
// 👍 은 건수만. 👎 는 질문·답변 앞부분이 관리자에게 가므로 보내기 전에 한 번 묻는다. 계정 정보는 보내지 않는다.
import { useState } from "react";
import { ApiError, post } from "../api";

export function AnswerRating({ q, a, compact = false }: { q: string; a: string; compact?: boolean }) {
  const [st, setSt] = useState<"" | "asking" | "up" | "down" | "err">("");
  const send = async (kind: "ask_up" | "ask_down") => {
    try {
      await post("feedback", { kind, page: window.location.pathname, text: q.slice(0, 200), extra: a.slice(0, 500) });
      setSt(kind === "ask_up" ? "up" : "down");
    } catch { setSt("err"); }
  };
  if (st === "up" || st === "down") return <div className={`ans-rate${compact ? " compact" : ""}`}><span className="caption">{st === "up" ? "고마워요! 👍" : "알려 주셔서 고마워요. 답변을 고치는 데 쓸게요."}</span></div>;
  return (
    <div className={`ans-rate${compact ? " compact" : ""}`}>
      <span className="caption">도움이 됐나요?</span>
      <button type="button" className="btn sm ghost" onClick={() => send("ask_up")} aria-label="도움이 됐어요">👍</button>
      <button type="button" className="btn sm ghost" onClick={() => setSt("asking")} aria-label="도움이 안 됐어요">👎</button>
      {st === "asking" && (
        <span className="ans-rate-ask">
          <span className="caption">이 질문·답변 앞부분이 관리자에게 전달돼요. 개인정보가 있으면 보내지 마세요.</span>
          <button type="button" className="btn sm primary" onClick={() => send("ask_down")}>보내기</button>
          <button type="button" className="btn sm ghost" onClick={() => setSt("")}>취소</button>
        </span>
      )}
      {st === "err" && <span className="caption"> 보내지 못했어요.</span>}
    </div>
  );
}

export function ReportData({ what }: { what: string }) {
  const [open, setOpen] = useState(false);
  const [t, setT] = useState("");
  const [msg, setMsg] = useState("");
  const send = async () => {
    try {
      await post("feedback", { kind: "data", page: window.location.pathname + window.location.search.slice(0, 60), text: t.trim(), extra: what });
      setMsg("알려 주셔서 고마워요. 확인할게요."); setOpen(false); setT("");
    } catch (e) { setMsg(e instanceof ApiError ? e.message : "보내지 못했어요."); }
  };
  return (
    <span className="report-data">
      <button type="button" className="linkish" onClick={() => { setOpen(!open); setMsg(""); }}>이상해요</button>
      {msg && <span className="caption"> {msg}</span>}
      {open && (
        <span className="report-form">
          <input type="text" maxLength={300} value={t} onChange={(e) => setT(e.target.value)} placeholder="무엇이 이상한가요? (예: 이 단지 최근가가 실제와 달라요)" aria-label="이상한 점" />
          <button type="button" className="btn sm primary" disabled={t.trim().length < 2} onClick={send}>보내기</button>
          <span className="caption">보는 화면 주소와 위 설명만 전달돼요. 이름·연락처는 적지 마세요.</span>
        </span>
      )}
    </span>
  );
}
