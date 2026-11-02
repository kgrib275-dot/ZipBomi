// 메일 링크 로그인 창 (2026-11-02) — POST /api/auth/request. 링크를 누르면 /login?t=… 에서 확정한다.
import { useState } from "react";
import { ApiError, post } from "../api";
import { Alert, Dialog } from "./ui";

export default function LoginDialog({ onClose }: { onClose: () => void }) {
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const [suggest, setSuggest] = useState("");
  const send = async (addr = email, typoOk = false) => {
    setBusy(true); setErr(""); setSuggest("");
    try {
      const r = await post<{ message: string }>("auth/request", { email: addr.trim(), typo_ok: typoOk });
      setMsg(r.message);
    } catch (e) {
      if (e instanceof ApiError && e.data?.suggest) setSuggest(String(e.data.suggest));
      setErr(e instanceof Error ? e.message : "보내지 못했습니다.");
    } finally { setBusy(false); }
  };
  return (
    <Dialog title={msg ? "메일을 확인해 주세요" : "집보미 로그인"} onClose={onClose}>
      {msg ? (
        <>
          <p>{msg}</p>
          <p className="caption">메일의 '로그인하기'를 누르면 이 브라우저에 저장해 둔 관심 단지·알림·저장한 노트가 계정으로 옮겨지고, 다른 기기에서도 똑같이 보여요.</p>
          <button className="btn primary block" onClick={onClose}>확인</button>
        </>
      ) : (
        <form onSubmit={(e) => { e.preventDefault(); if (email.trim()) send(); }}>
          <p className="caption" style={{ marginTop: 0 }}>비밀번호 없이 메일로 받은 링크로 로그인해요. 관심 단지·알림·저장한 노트·계산 기록이 어느 기기에서든 그대로 이어집니다.</p>
          <div className="field"><label htmlFor="lg-email">이메일</label>
            <input id="lg-email" type="email" required autoFocus value={email} onChange={(e) => setEmail(e.target.value)} placeholder="name@example.com" maxLength={254} /></div>
          {err && <Alert kind="err">{err}{suggest && <> <button type="button" className="linkish" onClick={() => { setEmail(suggest); send(suggest); }}>{suggest} 로 보내기</button></>}</Alert>}
          {err && !suggest && /도메인|주소/.test(err) && <button type="button" className="linkish" onClick={() => send(email, true)}>이 주소 그대로 보내기</button>}
          <button className="btn primary block" disabled={busy || !email.trim()} style={{ marginTop: 8 }}>{busy ? "보내는 중…" : "로그인 링크 받기"}</button>
          <p className="caption">로그인하면 계정 이메일과 저장한 설정을 보관합니다. 자세한 내용은 <a href="/privacy" target="_blank" rel="noopener">개인정보 처리방침</a>을 확인하세요.</p>
        </form>
      )}
    </Dialog>
  );
}
