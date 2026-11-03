// 관리 영역 틀 — 왼쪽 메뉴(15개 화면) + 중첩 라우트. 관리자가 아니거나 API 가 403 을 돌려주면 토큰 입력 화면을 띄운다.
import { lazy, Suspense, useEffect, useState } from "react";
import { NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { ApiError, get, post } from "../../api";
import { Alert } from "../../components/ui";
import { useMe } from "../../me";
import "./admin.css";
import { RevealToggle, ToastProvider, onForbidden } from "./common";
import { JobsProvider } from "./JobRunner";
import { LogDock } from "./LogDock";

const L = (p: () => Promise<{ default: React.ComponentType }>) => lazy(p);
const PAGES: { path: string; label: string; grp?: string; C: React.LazyExoticComponent<React.ComponentType> }[] = [
  { path: "dashboard", label: "대시보드", grp: "운영", C: L(() => import("./Dashboard")) },
  { path: "review", label: "노트 검토", grp: "콘텐츠", C: L(() => import("./Review")) },
  { path: "briefing", label: "데일리 브리핑", C: L(() => import("./Briefing")) },
  { path: "articles", label: "수집 기사", C: L(() => import("./Articles")) },
  { path: "issues", label: "주간 흐름", C: L(() => import("./Issues")) },
  { path: "report", label: "주간 PDF 리포트", C: L(() => import("./Report")) },
  { path: "search", label: "의미 검색·질문하기", C: L(() => import("./Search")) },
  { path: "collect", label: "수집 설정", grp: "설정", C: L(() => import("./Collect")) },
  { path: "schedule", label: "배치 스케줄", C: L(() => import("./Schedule")) },
  { path: "llm", label: "AI 모델 설정", C: L(() => import("./Llm")) },
  { path: "redata", label: "부동산 데이터", C: L(() => import("./ReData")) },
  { path: "policy", label: "현행 수치", C: L(() => import("./Policy")) },
  { path: "ops", label: "운영 점검", grp: "운영 현황", C: L(() => import("./Ops")) },
  { path: "engagement", label: "참여 분석", C: L(() => import("./Engagement")) },
  { path: "warehouse", label: "Databricks 적재", C: L(() => import("./Warehouse")) },
  { path: "subscribers", label: "구독·발송", grp: "사람", C: L(() => import("./Subscribers")) },
  { path: "accounts", label: "회원 계정", C: L(() => import("./Accounts")) },
  { path: "access", label: "관리자·접속", C: L(() => import("./Access")) },
  { path: "privacy", label: "개인정보 처리방침", C: L(() => import("./PrivacySettings")) },
];

const NAV_KEY = "zipgenie-adm-nav";  // 접어 둔 그룹·전체 접힘 상태 (이 브라우저에만)

/** 왼쪽 메뉴 — 16개 화면이 그룹별로 접힌다. 메뉴가 길어 좁은 화면에서는 본문이 아래로 밀렸다 (2026-10-30). */
function SideNav() {
  const { pathname } = useLocation();
  const current = PAGES.find((p) => pathname.startsWith(`/admin/${p.path}`)) || PAGES[0];
  const [st, setSt] = useState<{ collapsed: boolean; closed: string[] }>(() => {
    try { return { collapsed: false, closed: [], ...JSON.parse(localStorage.getItem(NAV_KEY) || "{}") }; } catch { return { collapsed: false, closed: [] }; }
  });
  useEffect(() => { try { localStorage.setItem(NAV_KEY, JSON.stringify(st)); } catch { /* 사생활 보호 모드 */ } }, [st]);
  // 그룹 나누기: grp 가 있는 항목이 새 그룹을 연다
  const groups: { name: string; items: typeof PAGES }[] = [];
  for (const p of PAGES) {
    if (p.grp) groups.push({ name: p.grp, items: [] });
    groups[groups.length - 1].items.push(p);
  }
  const toggleGroup = (name: string) => setSt((s) => ({ ...s, closed: s.closed.includes(name) ? s.closed.filter((n) => n !== name) : [...s.closed, name] }));
  return (
    <nav className={`adm-side${st.collapsed ? " collapsed" : ""}`} aria-label="관리 메뉴">
      <button type="button" className="nav-tg" onClick={() => setSt((s) => ({ ...s, collapsed: !s.collapsed }))}
        aria-expanded={!st.collapsed} title={st.collapsed ? "메뉴 펼치기" : "메뉴 접기"}>
        <span>☰</span><b>{st.collapsed ? current.label : "메뉴"}</b><i>{st.collapsed ? "펼치기" : "접기"}</i>
      </button>
      {!st.collapsed && groups.map((g) => {
        // 현재 화면이 속한 그룹은 항상 펼친다 — 접힌 머리글 아래 현재 항목만 홀로 남으면 어디 속한지 안 보였다
        const open = !st.closed.includes(g.name) || g.items.includes(current);
        return (
          <div key={g.name} className={`nav-grp${open ? "" : " closed"}`}>
            <button type="button" className="grp" onClick={() => toggleGroup(g.name)} aria-expanded={open}>
              <i>{open ? "▾" : "▸"}</i>{g.name}{!open && <small>{g.items.length}</small>}
            </button>
            {g.items.map((p) => open && (
              <NavLink key={p.path} to={`/admin/${p.path}`} className={({ isActive }) => (isActive ? "on" : "")}>{p.label}</NavLink>
            ))}
          </div>
        );
      })}
    </nav>
  );
}

/** 관리자 로그인 (2026-11-03 ISMS-P) — .env ADMIN_TOKEN + (ADMIN_TOTP_SECRET 이 있으면) OTP 6자리. 세션 쿠키는 HttpOnly 라 화면 스크립트가 읽지 못한다.
 *  30분 동안 쓰지 않거나 8시간이 지나면 다시 로그인한다. 5번 틀리면 30분 잠금. */
function AdminLogin({ reason, onDone }: { reason: string; onDone: () => Promise<void> }) {
  const [tok, setTok] = useState("");
  const [otp, setOtp] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [st, setSt] = useState<{ otp: boolean; configured: boolean; idle_min: number; max_hours: number } | null>(null);
  useEffect(() => { get<{ otp: boolean; configured: boolean; idle_min: number; max_hours: number }>("auth/admin-status").then(setSt).catch(() => undefined); }, []);
  const save = async () => {
    setBusy(true); setErr("");
    try {
      await post("auth/admin-login", { token: tok.trim(), otp: st?.otp ? otp.trim() : undefined });
      setTok(""); setOtp("");
      await onDone();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "로그인하지 못했습니다.");
    } finally { setBusy(false); }
  };
  return (
    <div className="box adm-token">
      <div className="eyebrow">Admin</div>
      <h2 className="sec-h" style={{ fontSize: "1.4rem" }}>🔒 관리자 로그인</h2>
      <Alert kind="warn">{reason}</Alert>
      <p className="caption">backend .env 의 ADMIN_TOKEN{st?.otp ? " 과 OTP 앱의 6자리" : ""}로 로그인해요. 토큰은 브라우저에 저장하지 않고,
        {st ? ` ${st.idle_min}분 동안 쓰지 않거나 ${st.max_hours}시간이 지나면` : " 일정 시간이 지나면"} 다시 로그인해야 해요. 5번 틀리면 30분 동안 잠겨요.</p>
      {st && !st.configured && <Alert kind="err">.env 에 ADMIN_TOKEN 이 없어 관리자 로그인을 할 수 없습니다.</Alert>}
      <form onSubmit={(e) => { e.preventDefault(); if (tok.trim()) save(); }}>
        <div className="field">
          <label htmlFor="adm-tok">관리자 토큰</label>
          <input id="adm-tok" type="password" autoComplete="off" value={tok} onChange={(e) => setTok(e.target.value)} autoFocus />
        </div>
        {st?.otp && (
          <div className="field">
            <label htmlFor="adm-otp">OTP 6자리</label>
            <input id="adm-otp" inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={otp} onChange={(e) => setOtp(e.target.value.replace(/\D/g, ""))} />
          </div>
        )}
        {err && <Alert kind="err">{err}</Alert>}
        <div className="btn-row">
          <button className="btn primary" disabled={busy || !tok.trim() || (!!st?.otp && otp.length !== 6)}>로그인</button>
        </div>
      </form>
    </div>
  );
}

function AdminLogout() {
  const { reload } = useMe();
  return (
    <button type="button" className="btn sm ghost adm-logout" onClick={async () => { await post("auth/admin-logout").catch(() => undefined); await reload(); }}>
      관리자 로그아웃
    </button>
  );
}

export default function AdminApp() {
  const { me, reload } = useMe();
  const [forbidden, setForbidden] = useState<string | null>(null);
  const [dockH, setDockH] = useState(0);  // 실행 로그 독 높이 — 본문 아래 여백으로 써서 끝 내용이 가려지지 않게

  useEffect(() => {
    onForbidden(() => setForbidden("로그인이 끝났거나(30분 미사용·8시간 경과) 권한이 없습니다. 다시 로그인해 주세요."));
    return () => onForbidden(() => undefined);
  }, []);

  if (!me) return <div className="page-loading">불러오는 중…</div>;
  if (!me.is_admin || forbidden) {
    return (
      <div className="container page">
        <AdminLogin
          reason={forbidden || "관리 화면은 관리자 로그인이 필요합니다."}
          onDone={async () => {
            await reload();
            setForbidden(null);
          }}
        />
      </div>
    );
  }

  return (
    <ToastProvider>
      <JobsProvider>
        <div className="container adm">
          <SideNav />
          <main className="adm-main" style={dockH ? { paddingBottom: dockH + 12 } : undefined}>
            <div className="adm-topbar"><RevealToggle /><AdminLogout /></div>
            <Suspense fallback={<div className="page-loading">불러오는 중…</div>}>
              <Routes>
                <Route index element={<Navigate to="dashboard" replace />} />
                {PAGES.map((p) => <Route key={p.path} path={p.path} element={<p.C />} />)}
                <Route path="*" element={<Navigate to="dashboard" replace />} />
              </Routes>
            </Suspense>
          </main>
        </div>
        <LogDock onHeight={setDockH} />
      </JobsProvider>
    </ToastProvider>
  );
}
