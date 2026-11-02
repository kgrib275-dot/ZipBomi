// 전 페이지 공통 틀 — 헤더(내비·구독·테마·KO/EN), 푸터, 플로팅 버튼, 구독 띠, 대화상자, 추천 링크(?ref=)·공유 유입(?s=1) 기록.
import { useEffect, useState } from "react";
import { Link, NavLink, useLocation, useSearchParams } from "react-router-dom";
import { track } from "../api";
import { DialogProvider, useDialogs } from "../components/Dialogs";
import { useMe } from "../me";
import { hasCore, useProfile, useProfileSync } from "../profile";
import AlertBell from "./AlertBell";
import Nudge from "./Nudge";
import { ThemeToggle } from "./Theme";
import { LangToggle } from "./Translate";

const PLAY = [["/type", "부동산 성향 16유형"], ["/career", "내 집 마련 전략 찾기"], ["/habit", "부동산 공부 습관 진단"], ["/terms", "부동산 용어 퀴즈"], ["/diagnosis", "내 집 마련 준비도 진단"]] as const;
// 메뉴 (2026-11-02 정리) — 할 일 기준으로 묶었다: 시세 보기 · 청약 · 계산 · 묻기. 퀴즈·테스트·데이터 랩·소개는 '더 보기'로.
// 위 칸 7개라 960~1100px 에서도 한 줄에 들어간다 (예전 11개는 넘쳤다).
type MenuItem = { to?: string; label: string; items?: readonly (readonly [string, string])[] };
const MENU: MenuItem[] = [
  { to: "/", label: "✦ 이번 주" },
  { to: "/notes", label: "노트" },
  { to: "/deals", label: "시세", items: [["/deals", "실거래가 · 지역 흐름"], ["/map", "지도 · 분양·매물"], ["/my-homes", "★ 관심 단지"]] },
  { to: "/calendar", label: "청약", items: [["/calendar", "분양 일정 · 당첨 가점"], ["/deals?tab=apply", "청약 공고 목록"]] },
  { to: "/calc", label: "계산기", items: [["/calc", "내 집 계산기"], ["/now", "현행 수치 · 규제·금리"]] },
  { to: "/ask", label: "질문하기" },
  { label: "더 보기", items: [["/today", "오늘의 퀴즈"], ...PLAY, ["/lab", "데이터 랩"], ["/about", "소개"]] },
];

export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <DialogProvider>
      <Shell>{children}</Shell>
    </DialogProvider>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  const { me, state, setState } = useMe();
  const { openSubscribe } = useDialogs();
  const [open, setOpen] = useState(false);
  const loc = useLocation();
  const [params] = useSearchParams();
  useProfileSync(); // 내 프로필: 서버 값 ↔ 이 브라우저 사본
  const { profile } = useProfile();

  useEffect(() => {
    setOpen(false);
    document.querySelector("main")?.scrollTo?.(0, 0);
    window.scrollTo(0, 0);
  }, [loc.pathname]);

  // 추천 링크로 온 방문 → 구독 시 추천인으로 남긴다. 공유 링크(?s=1) 유입 기록은 각 페이지가 content 를 알고 한다.
  useEffect(() => {
    const ref = params.get("ref");
    if (ref && /^[a-z0-9]{6,12}$/.test(ref) && state.ref !== ref) {
      setState({ ref });
      track("ref_visit", ref);
    }
  }, [params, state.ref, setState]);

  const isAdminArea = loc.pathname.startsWith("/admin");
  return (
    <>
      <header className="hdr">
        <div className="container hdr-in">
          <Link to="/" className="logo notranslate" translate="no" aria-label="집보미"><img className="logo-dk" src="/logo.svg" alt="" height={26} /><img className="logo-lt" src="/logo-light.svg" alt="" height={26} /></Link>
          <button className="btn sm burger" aria-label="메뉴" onClick={() => setOpen((o) => !o)}><span aria-hidden="true">☰</span><span className="burger-lbl"> 메뉴</span></button>
          <nav className={`nav ${open ? "open" : ""}`}>
            {MENU.map((m) => {
              if (!m.items) return <NavLink key={m.label} to={m.to!} end={m.to === "/"} className={({ isActive }) => (isActive ? "on" : "")}>{m.label}</NavLink>;
              const here = m.items.some(([to]) => to.split("?")[0] === loc.pathname && (!to.includes("?") || loc.search === to.slice(to.indexOf("?"))));
              return (
                <div key={m.label} className="dd">
                  {m.to ? <NavLink to={m.to} className={() => (here ? "on" : "")}>{m.label} ▾</NavLink>
                    : <button type="button" className={here ? "on" : ""} aria-haspopup="true">{m.label} ▾</button>}
                  <div className="menu">{m.items.map(([to, label]) => <NavLink key={to} to={to} end>{label}</NavLink>)}</div>
                </div>
              );
            })}
            {me?.is_admin && <NavLink to="/admin" className={() => (isAdminArea ? "on" : "")}>관리</NavLink>}
          </nav>
          <div className="hdr-right">
            <AlertBell />
            <NavLink to="/my" className={({ isActive }) => `btn sm ghost me-link${isActive ? " on" : ""}`} title={me?.account ? `내 공간 — ${me.account.email}` : "내 공간 — 관심 단지·알림·저장한 노트·계산"}>
              <span aria-hidden="true">{me?.account ? "●" : hasCore(profile) ? "◉" : "○"}</span> <span className="lbl">내 공간</span>
            </NavLink>
            <ThemeToggle />
            <LangToggle />
            <button className="btn primary sm sub" onClick={() => openSubscribe("header")}>구독</button>
          </div>
        </div>
      </header>
      <main>
        <div className="container page">{children}</div>
      </main>
      <Footer />
      <a className="fab fab-ask notranslate" translate="no" href="/ask" title="질문하기">✦</a>
      <button className="fab fab-top notranslate" translate="no" title="맨 위로" onClick={() => window.scrollTo({ top: 0, behavior: "smooth" })}>↑</button>
      {!isAdminArea && !state.subscribed && (!me?.is_admin || params.get("nudge") === "1") && <Nudge onSubscribe={() => openSubscribe("sticky_bar")} />}
    </>
  );
}

function Footer() {
  const { me } = useMe();
  return (
    <footer className="container">
      <div className="site-foot">
        <span>© 2026 <b>집보미</b></span>
        <span>집보미 · 집에 관한 모든 것 — 시세·청약·대출·세금·정책을 한곳에서</span>
        <span>
          <Link to="/letter">뉴스레터 미리보기</Link>
          {me?.privacy_active !== false && <> · <Link to="/privacy" style={{ color: "var(--ink-hi)", fontWeight: 800 }}>개인정보 처리방침</Link></>}
        </span>
      </div>
    </footer>
  );
}
