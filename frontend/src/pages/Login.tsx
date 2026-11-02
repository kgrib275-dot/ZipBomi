// 메일 링크 로그인 확정 (/login?t=…) — 링크를 연 것만으로 확정하지 않고(메일 보안 검사기가 링크를 미리 열어도 쓰이지 않게) 버튼으로 확정.
// 요청한 브라우저가 아니면 메일의 6자리 확인 코드를 함께 넣는다. /login?revoke=… 는 로그인 알림 메일의 '모든 기기에서 로그아웃'.
import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { ApiError, post } from "../api";
import { Alert } from "../components/ui";
import { useMe } from "../me";

export default function Login() {
  const [sp] = useSearchParams();
  const t = sp.get("t") || "";
  const rv = sp.get("revoke") || "";
  const nav = useNavigate();
  const { reload } = useMe();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [needCode, setNeedCode] = useState(false);
  const [code, setCode] = useState("");
  const [done, setDone] = useState("");
  const go = async () => {
    setBusy(true); setErr("");
    try {
      await post("auth/verify", needCode ? { t, code } : { t });
      await reload();
      nav("/my");
    } catch (e) {
      if (e instanceof ApiError && e.data?.need_code) { setNeedCode(true); setErr(needCode ? e.message : ""); }
      else setErr(e instanceof Error ? e.message : "로그인하지 못했습니다.");
    } finally { setBusy(false); }
  };
  const revoke = async () => {
    setBusy(true); setErr("");
    try { const r = await post<{ message: string }>("auth/revoke", { r: rv }); setDone(r.message); await reload(); }
    catch (e) { setErr(e instanceof Error ? e.message : "처리하지 못했습니다."); } finally { setBusy(false); }
  };
  const valid = (x: string) => /^[0-9a-f]{32}$/.test(x);
  if (rv) return (
    <div className="login-page">
      <div className="eyebrow">보안</div>
      <h2 className="sec-h">모든 기기에서 <span className="grad">로그아웃</span></h2>
      {done ? <Alert kind="ok">{done}</Alert> : !valid(rv) ? <Alert kind="err">링크가 올바르지 않습니다.</Alert> : (
        <>
          <p className="sec-p">본인이 로그인하지 않았다면 아래 버튼을 눌러 주세요. 지금 로그인된 모든 기기가 로그아웃됩니다. 저장한 내용은 지워지지 않아요.</p>
          {err && <Alert kind="err">{err}</Alert>}
          <button className="btn primary" disabled={busy} onClick={revoke}>{busy ? "처리 중…" : "모든 기기에서 로그아웃"}</button>
        </>
      )}
      <p style={{ marginTop: 16 }}><Link to="/">홈으로</Link></p>
    </div>
  );
  return (
    <div className="login-page">
      <div className="eyebrow">로그인</div>
      <h2 className="sec-h">집보미에 <span className="grad">로그인</span>합니다</h2>
      {!valid(t) ? <Alert kind="err">링크가 올바르지 않습니다. 메일의 버튼을 다시 눌러 주세요.</Alert> : (
        <form onSubmit={(e) => { e.preventDefault(); go(); }}>
          <p className="sec-p">아래 버튼을 누르면 이 브라우저가 계정에 연결됩니다. 이 브라우저에 저장해 둔 관심 단지·알림·저장한 노트는 계정에 합쳐져요.</p>
          {needCode && (
            <div className="field login-code">
              <label htmlFor="lg-code">확인 코드 (메일에 적힌 숫자 6자리)</label>
              <input id="lg-code" inputMode="numeric" autoComplete="one-time-code" maxLength={6} autoFocus value={code}
                onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))} placeholder="000000" />
              <span className="caption">로그인을 요청한 기기가 아닌 곳에서 열어 한 번 더 확인해요. 5번 틀리면 링크가 무효가 됩니다.</span>
            </div>
          )}
          {err && <Alert kind="err">{err}</Alert>}
          <button className="btn primary" disabled={busy || (needCode && code.length !== 6)}>{busy ? "확인 중…" : "로그인하기"}</button>{" "}
          <Link className="btn ghost" to="/">취소</Link>
        </form>
      )}
    </div>
  );
}
