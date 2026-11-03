// 메일 로그인 창 (2026-11-02) — POST /api/auth/request 로 링크·코드를 보낸다.
// 2026-11-03: 메일의 6자리 코드를 이 창에 바로 넣어 로그인(POST /api/auth/verify-code). 휴대폰 메일 앱이 링크를 앱 안 브라우저로
// 열어 '다른 기기'로 처리되던 문제를 피한다. 메일의 '로그인하기' 버튼(/login?t=…)도 그대로 쓸 수 있다.
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError, post } from "../api";
import { announceAuth, useMe } from "../me";
import { Alert, Dialog } from "./ui";

export default function LoginDialog({ onClose }: { onClose: () => void }) {
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const [suggest, setSuggest] = useState("");
  const [code, setCode] = useState("");
  const { me, reload } = useMe();
  const nav = useNavigate();
  // 메일 링크를 같은 브라우저의 다른 탭에서 눌러 로그인하면(그 탭이 announceAuth) 이 창은 저절로 닫고 내 공간으로
  const who = me?.account?.email || "";
  const startedAs = useRef(who);  // 창을 연 때의 계정 — 바뀌었을 때만 닫는다
  useEffect(() => { if (msg && who && who !== startedAs.current) { onClose(); nav("/my"); } }, [msg, who]); // eslint-disable-line react-hooks/exhaustive-deps
  const send = async (addr = email, typoOk = false) => {
    setBusy(true); setErr(""); setSuggest("");
    try {
      const r = await post<{ message: string }>("auth/request", { email: addr.trim(), typo_ok: typoOk });
      setMsg(r.message); setCode("");
    } catch (e) {
      if (e instanceof ApiError && e.data?.suggest) setSuggest(String(e.data.suggest));
      setErr(e instanceof Error ? e.message : "보내지 못했습니다.");
    } finally { setBusy(false); }
  };
  const verify = async () => {
    setBusy(true); setErr("");
    try {
      await post("auth/verify-code", { code });
      announceAuth();
      await reload();
      onClose();
      nav("/my");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "로그인하지 못했습니다.");
    } finally { setBusy(false); }
  };
  return (
    <Dialog title={msg ? "메일을 확인해 주세요" : "집보미 로그인"} onClose={onClose}>
      {msg ? (
        <form onSubmit={(e) => { e.preventDefault(); if (code.length === 6) verify(); }}>
          <p>{msg}</p>
          <div className="field login-code">
            <label htmlFor="lg-code2">확인 코드 (메일에 적힌 숫자 6자리)</label>
            <input id="lg-code2" inputMode="numeric" autoComplete="one-time-code" maxLength={6} autoFocus value={code}
              onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))} placeholder="000000" />
          </div>
          {err && <Alert kind="err">{err}</Alert>}
          <button className="btn primary block" disabled={busy || code.length !== 6}>{busy ? "확인 중…" : "로그인하기"}</button>
          <p className="caption">메일 앱에서 버튼을 눌러 다른 화면에서 로그인했더라도, 이 창에 코드를 넣으면 여기서도 로그인돼요.</p>
          <p className="caption">로그인하면 이 브라우저에 저장해 둔 관심 단지·알림·저장한 노트가 계정으로 옮겨지고, 다른 기기에서도 똑같이 보여요.
            메일이 오지 않으면 <button type="button" className="linkish" disabled={busy} onClick={() => { setMsg(""); setErr(""); }}>주소를 다시 넣기</button></p>
        </form>
      ) : (
        <form onSubmit={(e) => { e.preventDefault(); if (email.trim()) send(); }}>
          <p className="caption" style={{ marginTop: 0 }}>비밀번호 없이 메일로 받은 6자리 코드(또는 링크)로 로그인해요. 관심 단지·알림·저장한 노트·계산 기록이 어느 기기에서든 그대로 이어집니다.</p>
          <div className="field"><label htmlFor="lg-email">이메일</label>
            <input id="lg-email" type="email" required autoFocus value={email} onChange={(e) => setEmail(e.target.value)} placeholder="name@example.com" maxLength={254} /></div>
          {err && <Alert kind="err">{err}{suggest && <> <button type="button" className="linkish" onClick={() => { setEmail(suggest); send(suggest); }}>{suggest} 로 보내기</button></>}</Alert>}
          {err && !suggest && /도메인|주소/.test(err) && <button type="button" className="linkish" onClick={() => send(email, true)}>이 주소 그대로 보내기</button>}
          <button className="btn primary block" disabled={busy || !email.trim()} style={{ marginTop: 8 }}>{busy ? "보내는 중…" : "로그인 메일 받기"}</button>
          <p className="caption">로그인하면 계정 이메일과 저장한 설정을 보관합니다. 자세한 내용은 <a href="/privacy" target="_blank" rel="noopener">개인정보 처리방침</a>을 확인하세요.</p>
        </form>
      )}
    </Dialog>
  );
}
