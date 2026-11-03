// 1분 둘러보기 (2026-11-02) — 로그인하지 않은 방문자는 처음 들어온 뒤 1분 동안 둘러보고, 그 뒤에는 메일 로그인을 요청한다.
// 2026-11-03: 소개 페이지로 옮기지 않고 보던 화면 위에 로그인 창을 띄운다 — 읽던 글·공유받은 화면이 사라지지 않고, 로그인하면 그 화면에서 이어진다.
// 남은 시간은 서버가 /api/me 의 trial_left 로 알려 준다(쿠키·IP 기준, backend/pipeline/gate.py). 서버도 같은 기준으로 API 를 막는다(401).
import { useEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";
import { useDialogs } from "../components/Dialogs";
import { useMe } from "../me";

const OPEN = ["/about", "/privacy", "/login", "/confirm", "/unsubscribe", "/admin"];

export default function TrialGate() {
  const { me } = useMe();
  const { openLogin } = useDialogs();
  const loc = useLocation();
  const asked = useRef(false);
  const [left, setLeft] = useState<number | null>(null);
  const [blocked, setBlocked] = useState(false);
  useEffect(() => {
    if (!me) return;
    if (me.trial_left === null || me.trial_left === undefined) { setLeft(null); setBlocked(false); return; }
    const end = Date.now() + me.trial_left * 1000;
    const tick = () => { const l = Math.max(0, Math.ceil((end - Date.now()) / 1000)); setLeft(l); if (l <= 0) setBlocked(true); };
    tick();
    const t = window.setInterval(tick, 1000);
    return () => window.clearInterval(t);
  }, [me]);
  useEffect(() => {
    const on = () => setBlocked(true);
    window.addEventListener("zg-login-required", on);
    return () => window.removeEventListener("zg-login-required", on);
  }, []);
  const open = OPEN.some((p) => loc.pathname === p || loc.pathname.startsWith(p + "/"));
  useEffect(() => {
    if (blocked && !open && !me?.account && !me?.is_admin && !asked.current) {
      asked.current = true;
      (window as unknown as { __zgGateBlocked?: boolean }).__zgGateBlocked = true;  // 로그인 뒤 이 화면을 다시 불러온다 (LoginDialog)
      openLogin();
    }
  }, [blocked, open, me, openLogin]);
  if (!me || me.account || me.is_admin || left === null) return null;
  if (!blocked) return (
    <div className="trial-bar" role="status">
      <span>👀 둘러보기 중 · <b>{left}초</b> 남음</span>
      <span className="sp">메일 인증(로그인)하면 모든 기능을 계속 쓸 수 있어요.</span>
      <button type="button" className="btn sm primary" onClick={openLogin}>메일로 로그인</button>
    </div>
  );
  return (
    <div className="trial-bar done" role="alert">
      <span>🔒 둘러보기 시간이 끝났어요.</span>
      <span className="sp">메일 인증(로그인) 후 이 화면에서 바로 이어 볼 수 있어요. 비밀번호 없이 메일의 6자리 코드로 1분이면 끝나요.</span>
      <button type="button" className="btn sm primary" onClick={openLogin}>메일로 로그인</button>
    </div>
  );
}

/** 저장 실패 알림 — 한도 초과·연결 불안정 (me.tsx 가 zg-save-error 로 알린다) */
export function SaveError() {
  const [msg, setMsg] = useState("");
  useEffect(() => {
    const on = (e: Event) => setMsg(String((e as CustomEvent).detail || "저장하지 못했습니다."));
    window.addEventListener("zg-save-error", on);
    return () => window.removeEventListener("zg-save-error", on);
  }, []);
  if (!msg) return null;
  return (
    <div className="trial-bar done" role="alert">
      <span>⚠ {msg}</span>
      <button type="button" className="btn sm ghost" onClick={() => setMsg("")}>닫기</button>
    </div>
  );
}
