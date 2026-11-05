// 메일 로그인 창 (2026-11-02) — POST /api/auth/request 로 링크·코드를 보낸다.
// 2026-11-03: 메일의 6자리 코드를 이 창에 바로 넣어 로그인(POST /api/auth/verify-code). 휴대폰 메일 앱이 링크를 앱 안 브라우저로
// 열어 '다른 기기'로 처리되던 문제를 피한다. 메일의 '로그인하기' 버튼(/login?t=…)도 그대로 쓸 수 있다.
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError, post } from "../api";
import { announceAuth, useMe } from "../me";
import { Alert, Dialog } from "./ui";

// 로그인 메일을 보낸 뒤의 '코드 입력 단계'를 기억한다 (2026-11-05) — 메일 앱·다른 브라우저로 갔다 오는 사이 휴대폰이 이 탭을 정리해 화면이 새로 불러와져도
// 창이 사라지지 않게. 보낸 시각만 저장하고 이메일 같은 개인정보는 넣지 않는다(이 탭을 닫으면 지워짐). 링크·코드 유효 시간(30분)이 지나면 무시한다.
// 사용자가 ×로 닫으면(DISMISS) 새로 불러와져도 저절로 다시 열지는 않고, 다시 열면 코드 입력 단계부터 이어 간다.
const WAIT_KEY = "zg-login-wait", DISMISS_KEY = "zg-login-dismiss", WAIT_MS = 30 * 60 * 1000;
const RESTORED_MSG = "로그인 메일을 보냈어요. 메일에 적힌 6자리 코드를 넣어 주세요. (링크는 30분 안에 한 번만 쓸 수 있어요.)";
const ss = (f: (s: Storage) => void) => { try { f(sessionStorage); } catch { /* 저장이 막힌 브라우저 — 기억만 못 할 뿐 로그인은 된다 */ } };
export function loginWaiting(): boolean {
  try { const t = Number(sessionStorage.getItem(WAIT_KEY)); return t > 0 && Date.now() - t < WAIT_MS; } catch { return false; }
}
export function loginShouldReopen(): boolean {
  try { return loginWaiting() && sessionStorage.getItem(DISMISS_KEY) !== "1"; } catch { return false; }
}
export function clearLoginWait() { ss((s) => { s.removeItem(WAIT_KEY); s.removeItem(DISMISS_KEY); }); }

export default function LoginDialog({ onClose }: { onClose: () => void }) {
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(() => (loginWaiting() ? RESTORED_MSG : ""));
  const close = () => { ss((s) => s.setItem(DISMISS_KEY, "1")); onClose(); };
  const [err, setErr] = useState("");
  const [suggest, setSuggest] = useState("");
  const [code, setCode] = useState("");
  const [agree, setAgree] = useState(false);  // 만 14세 이상·수집 안내 확인 (2026-11-03 — 처리방침 제7조, 구독 창과 같게)
  const { me, reload } = useMe();
  const nav = useNavigate();
  // 메일 링크를 같은 브라우저의 다른 탭에서 눌러 로그인하면(그 탭이 announceAuth) 이 창은 저절로 닫고 내 공간으로
  const who = me?.account?.email || "";
  const startedAs = useRef(who);  // 창을 연 때의 계정 — 바뀌었을 때만 닫는다
  useEffect(() => { if (msg && who && who !== startedAs.current) afterLogin(); }, [msg, who]); // eslint-disable-line react-hooks/exhaustive-deps
  // 메일을 기다리는 동안 3초마다 로그인됐는지 확인 — 메일 앱이 링크를 같은 브라우저의 다른 창(크롬 맞춤 탭 등)으로 열어 그쪽에서
  // 로그인하면 탭 사이 알림이 오지 않는 경우가 있다 (2026-11-03 휴대폰에서 확인)
  useEffect(() => {
    if (!msg) return;
    const id = window.setInterval(() => { if (document.visibilityState === "visible") reload(); }, 3000);
    return () => window.clearInterval(id);
  }, [msg, reload]);
  const send = async (addr = email, typoOk = false) => {
    setBusy(true); setErr(""); setSuggest("");
    try {
      const r = await post<{ message: string }>("auth/request", { email: addr.trim(), typo_ok: typoOk, agree: true });
      setMsg(r.message); setCode("");
      ss((s) => { s.setItem(WAIT_KEY, String(Date.now())); s.removeItem(DISMISS_KEY); });
    } catch (e) {
      if (e instanceof ApiError && e.data?.suggest) setSuggest(String(e.data.suggest));
      setErr(e instanceof Error ? e.message : "보내지 못했습니다.");
    } finally { setBusy(false); }
  };
  // 로그인한 뒤에는 보던 화면에서 이어 간다 (2026-11-03) — 둘러보기가 끝나 막혔던 화면이면 자료를 다시 불러오고,
  // 로그인 전용 화면(/login, /about?login=1)에서 왔으면 ?next= 주소나 내 공간으로.
  const afterLogin = () => {
    clearLoginWait();
    onClose();
    const sp = new URLSearchParams(window.location.search);
    const next = sp.get("next");
    const loginPage = window.location.pathname === "/login" || (window.location.pathname === "/about" && sp.get("login") === "1");
    // 이 사이트 안의 주소만 — '//' 뿐 아니라 '/\'(브라우저가 '//' 처럼 읽음)·제어 문자도 막는다 (2026-11-05 react-router 열린 리다이렉트 권고)
    const safe = !!next && next.startsWith("/") && !next.startsWith("//") && !next.includes("\\") && !/[\u0000-\u001f\u007f]/.test(next);
    if (loginPage) nav(safe ? (next as string) : "/my");
    else if ((window as unknown as { __zgGateBlocked?: boolean }).__zgGateBlocked) window.location.reload();
  };
  const verify = async () => {
    setBusy(true); setErr("");
    try {
      await post("auth/verify-code", { code });
      announceAuth();
      await reload();
      afterLogin();
    } catch (e) {
      await reload();  // 링크로 이미 이 브라우저가 로그인됐으면 코드가 쓰였어도 위 useEffect 가 창을 닫는다
      setErr(e instanceof Error ? e.message : "로그인하지 못했습니다.");
    } finally { setBusy(false); }
  };
  return (
    <Dialog title={msg ? "메일을 확인해 주세요" : "집보미 로그인"} onClose={close} noBackdropClose>
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
            메일이 오지 않으면 <button type="button" className="linkish" disabled={busy} onClick={() => { clearLoginWait(); setMsg(""); setErr(""); }}>주소를 다시 넣기</button></p>
        </form>
      ) : (
        <form onSubmit={(e) => { e.preventDefault(); if (!agree) { setErr("만 14세 이상인지와 개인정보 수집·이용 안내를 확인해 주세요."); return; } if (email.trim()) send(); }}>
          <p className="caption" style={{ marginTop: 0 }}>비밀번호 없이 메일로 받은 6자리 코드(또는 링크)로 로그인해요. 관심 단지·알림·저장한 노트·계산 기록이 어느 기기에서든 그대로 이어집니다.</p>
          <div className="field"><label htmlFor="lg-email">이메일</label>
            <input id="lg-email" type="email" required autoFocus value={email} onChange={(e) => setEmail(e.target.value)} placeholder="name@example.com" maxLength={254} /></div>
          {err && <Alert kind="err">{err}{suggest && <> <button type="button" className="linkish" onClick={() => { setEmail(suggest); send(suggest); }}>{suggest} 로 보내기</button></>}</Alert>}
          {err && !suggest && /도메인|주소/.test(err) && <button type="button" className="linkish" onClick={() => send(email, true)}>이 주소 그대로 보내기</button>}
          <button className="btn primary block" disabled={busy || !email.trim() || !agree} style={{ marginTop: 8 }}>{busy ? "보내는 중…" : "로그인 메일 받기"}</button>
          <p className="caption"><b>개인정보 수집·이용 안내</b> · 항목: 이메일(필수), 로그인 기기 정보(브라우저 종류·사용 일시) · 목적: 로그인, 여러 기기에서 내 설정·관심 목록 이어 보기, 로그인 알림 메일
            · 보유: 탈퇴('내 기록 지우기')할 때까지 · 로그인에 꼭 필요한 정보만 받으며, 입력하지 않으면 로그인할 수 없습니다. 메일은 발송 업체에 위탁해 보냅니다. <a href="/privacy" target="_blank" rel="noopener">개인정보 처리방침</a></p>
          <label className="check"><input type="checkbox" checked={agree} onChange={(e) => setAgree(e.target.checked)} /> 만 14세 이상이며, 위 개인정보 수집·이용 안내를 확인했습니다 (필수)</label>
        </form>
      )}
    </Dialog>
  );
}
