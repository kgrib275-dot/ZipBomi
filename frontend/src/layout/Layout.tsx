// 전 페이지 공통 틀 — 헤더(내비·구독·테마·KO/EN), 푸터, 플로팅 버튼, 구독 띠, 대화상자, 추천 링크(?ref=)·공유 유입(?s=1) 기록.
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Link, NavLink, useLocation, useNavigationType, useSearchParams } from "react-router-dom";
import { track } from "../api";
import { DialogProvider, useDialogs } from "../components/Dialogs";
import { useMe } from "../me";
import { useProfile, useProfileSync } from "../profile";
import AlertBell from "./AlertBell";
import AskPanel from "./AskPanel";
import Nudge from "./Nudge";
import TrialGate, { SaveError } from "./TrialGate";
import { ThemeToggle } from "./Theme";
import { LangToggle } from "./Translate";

const PLAY = [["/today", "오늘의 퀴즈"], ["/terms", "부동산 용어 퀴즈"], ["/type", "부동산 성향 16유형"], ["/career", "내 집 마련 전략 찾기"],
  ["/diagnosis", "내 집 마련 준비도 진단"], ["/habit", "부동산 공부 습관 진단"]] as const;
// 메뉴 (2026-11-02 정리) — 할 일 기준으로 묶었다: 시세 보기 · 청약 · 계산 · 묻기. 퀴즈·테스트·데이터 랩·소개는 '더 보기'로.
// 위 칸 7개라 960~1100px 에서도 한 줄에 들어간다 (예전 11개는 넘쳤다).
type MenuItem = { to?: string; label: string; items?: readonly (readonly [string, string])[] };
// 2026-11-02 메뉴 정리: 밀고 가는 3개(시세·청약·소식) + 더 보기. 보미AI 는 오른쪽 패널(✦ 버튼)로.
// 2026-11-03 메뉴 다시 정리 — 흔한 부동산 서비스 순서(시세 → 청약 → 뉴스 → 도구)로. 자주 쓰는 계산기는 위 칸으로 올리고,
// 퀴즈·테스트는 '더 보기' 안에서 제목('-')으로 묶었다. 항목 이름은 짧게(무엇을 하는 곳인지만).
const MENU: MenuItem[] = [
  { to: "/map", label: "시세", items: [["/map", "지도로 보기"], ["/deals", "실거래가 조회"], ["/lab", "지역 비교 · 데이터 랩"], ["/my-homes", "관심 단지"]] },
  { to: "/calendar", label: "청약", items: [["/calendar", "청약 일정 달력"], ["/deals?tab=apply", "청약 공고 목록"], ["/calendar?tab=scores", "지난 당첨 가점 · 경쟁률"]] },
  { to: "/notes", label: "소식", items: [["/", "이번 주 시장"], ["/notes", "시장 해설 노트"], ["/now", "규제 · 금리 현황"]] },
  { to: "/calc", label: "계산기" },
  { label: "더 보기", items: [["-", "재미로 알아보기"], ...PLAY, ["-", "집보미"], ["/about", "서비스 소개"], ["/help", "고객센터 · 문의"]] },
]

// 화면을 옮겨도 탭 제목이 처음 연 화면 그대로였다 (2026-11-03) — 경로별 기본 제목. 노트·달력처럼 자기 제목을 정하는 화면은 그 뒤(useEffect)에 덮어쓴다.
const TITLES: Record<string, string> = {
  "/": "집보미 — 이번 주 부동산 시장", "/home": "집보미 — 이번 주 부동산 시장", "/map": "지도로 보기", "/deals": "실거래가 조회", "/lab": "데이터 랩",
  "/my-homes": "관심 단지", "/calendar": "청약 일정 · 당첨 가점", "/notes": "시장 해설 노트", "/now": "규제 · 금리 현황", "/calc": "내 집 계산기",
  "/today": "오늘의 퀴즈", "/terms": "부동산 용어 퀴즈", "/type": "부동산 성향 16유형", "/career": "내 집 마련 전략 찾기", "/diagnosis": "내 집 마련 준비도 진단",
  "/habit": "부동산 공부 습관 진단", "/about": "서비스 소개", "/help": "고객센터", "/privacy": "개인정보 처리방침", "/my": "내 공간", "/me": "내 프로필", "/ask": "보미AI",
  "/login": "로그인", "/letter": "뉴스레터 미리 보기", "/refer": "추천 현황", "/confirm": "구독 확인", "/unsubscribe": "구독 해지", "/admin": "관리",
};
function useRouteTitle(pathname: string) {
  useLayoutEffect(() => {
    const key = pathname.startsWith("/admin") ? "/admin" : pathname.replace(/\/+$/, "") || "/";
    const t = TITLES[key];
    if (t) document.title = key === "/" || key === "/home" ? t : `${t} — 집보미`;
  }, [pathname]);
}

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
  useRouteTitle(loc.pathname);

  // 스크롤 위치 — 뒤로·앞으로 가기면 그 화면에 있던 자리로 되돌리고, 새로 이동하면 맨 위로 (2026-11-03: 목록 → 노트 → 뒤로에서 자리를 잃었다).
  // 목록은 자료가 늦게 들어와 높이가 자라므로 몇 번 나눠서 맞춘다.
  const navType = useNavigationType();
  const scrollPos = useRef<Record<string, number>>({});
  const curKey = useRef(loc.key);
  const prevPath = useRef(loc.pathname);
  const [showTop, setShowTop] = useState(false);
  useEffect(() => {
    const onScroll = () => { scrollPos.current[curKey.current] = window.scrollY; setShowTop(window.scrollY > 600); };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);
  useEffect(() => {
    setOpen(false);
    curKey.current = loc.key;
    const saved = scrollPos.current[loc.key];
    const timers: number[] = [];
    if (navType === "POP" && saved !== undefined) {
      for (const ms of [0, 60, 200, 450, 900]) timers.push(window.setTimeout(() => { if (Math.abs(window.scrollY - saved) > 4) window.scrollTo(0, saved); }, ms));
    } else if (prevPath.current !== loc.pathname) {
      document.querySelector("main")?.scrollTo?.(0, 0);
      window.scrollTo(0, 0);
    }
    prevPath.current = loc.pathname;
    return () => timers.forEach((t) => window.clearTimeout(t));
  }, [loc.key]); // eslint-disable-line react-hooks/exhaustive-deps

  // 추천 링크로 온 방문 → 구독 시 추천인으로 남긴다. 공유 링크(?s=1) 유입 기록은 각 페이지가 content 를 알고 한다.
  useEffect(() => {
    const ref = params.get("ref");
    if (ref && /^[a-z0-9]{6,12}$/.test(ref) && state.ref !== ref) {
      setState({ ref });
      track("ref_visit", ref);
    }
  }, [params, state.ref, setState]);

  // 모바일 메뉴를 연 동안 뒤 페이지가 같이 스크롤되지 않게 잠그고, 메뉴 밖을 누르거나 Esc 로 닫는다 (2026-11-03)
  useEffect(() => {
    if (!open) return;
    const root = document.documentElement;
    root.classList.add("nav-lock");
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    window.addEventListener("keydown", onKey);
    return () => { root.classList.remove("nav-lock"); window.removeEventListener("keydown", onKey); };
  }, [open]);

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
              const here = m.items.some(([to]) => to !== "-" && to.split("?")[0] === loc.pathname && (!to.includes("?") || loc.search === to.slice(to.indexOf("?"))));
              return (
                <div key={m.label} className="dd">
                  {m.to ? <NavLink to={m.to} className={() => (here ? "on" : "")}>{m.label}<span className="caret" aria-hidden="true"> ▾</span></NavLink>
                    : <button type="button" className={here ? "on" : ""} aria-haspopup="true">{m.label}<span className="caret" aria-hidden="true"> ▾</span></button>}
                  <div className="menu">{m.items.map(([to, label]) => (to === "-" ? <span key={label} className="mh">{label}</span>
                    : <NavLink key={to} to={to} end className={() => (to.split("?")[0] === loc.pathname && (to.includes("?") ? loc.search === to.slice(to.indexOf("?")) : !loc.search.includes("tab=")) ? "on" : "")}>{label}</NavLink>))}</div>
                </div>
              );
            })}
            {me?.is_admin && <NavLink to="/admin" className={() => (isAdminArea ? "on" : "")}>관리</NavLink>}
          </nav>
          <div className="hdr-right">
            <button type="button" className="btn sm bomi-btn" onClick={() => window.dispatchEvent(new Event("zg-open-ask"))} title="보미AI — 보던 화면 옆에서 질문">✦ <span className="lbl">보미AI</span></button>
            <AlertBell />
            <NavLink to="/my" className={({ isActive }) => `btn sm ghost me-link${isActive ? " on" : ""}`} title={me?.account ? `내 공간 — ${me.account.email}` : "내 공간 — 관심 단지·알림·저장한 노트·계산"}>
              <span aria-hidden="true" className={`me-ico${me?.account ? " in" : ""}`}>👤</span> <span className="lbl">내 공간</span>
            </NavLink>
            <ThemeToggle />
            <LangToggle />
            <button className="btn primary sm sub" onClick={() => openSubscribe("header")}>구독</button>
          </div>
        </div>
      </header>
      {open && <div className="nav-backdrop" aria-hidden="true" onClick={() => setOpen(false)} />}
      {!isAdminArea && <TrialGate />}
      <SaveError />
      <main>
        <div className="container page">{children}</div>
      </main>
      <Footer />
      {/* 관리 화면에서는 공개용 둥근 단추·보미AI 패널을 숨긴다 (2026-11-03 — 휴대폰 관리 화면을 가렸다) */}
      {!isAdminArea && <button type="button" className="fab fab-ask notranslate" translate="no" title="보미AI" onClick={() => window.dispatchEvent(new Event("zg-open-ask"))}>✦</button>}
      {!isAdminArea && <AskPanel />}
      {showTop && <button className="fab fab-top notranslate" translate="no" title="맨 위로" aria-label="맨 위로" onClick={() => window.scrollTo({ top: 0, behavior: "smooth" })}>↑</button>}
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
        <span className="foot-note">무료 정보 서비스 · 투자 권유가 아닌 참고 자료입니다 · 노트 초안과 보미AI 답변은 생성형 AI로 만듭니다</span>
        <span>
          <Link to="/help">고객센터</Link> · <Link to="/letter">뉴스레터 미리보기</Link>
          {me?.privacy_active !== false && <> · <Link to="/privacy" style={{ color: "var(--ink-hi)", fontWeight: 800 }}>개인정보 처리방침</Link></>}
        </span>
      </div>
    </footer>
  );
}
