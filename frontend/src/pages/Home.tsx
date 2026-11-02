// 홈 (/) — Streamlit 판 app_pages/home.py 이식.
// 히어로(숫자 카운트업) → 급상승 키워드 띠 → For you → 처음이라면 3가지 → 이번 주 흐름 → 이번 주 꼭 알아야 할 3가지
// → 쌓이는 노트(카테고리 내비 + 최신 9편, 60초마다 새로 받아 새 카드는 빛남) → 소스 → 뉴스레터 CTA.
import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useSearchParams } from "react-router-dom";
import { get, track } from "../api";
import { useDialogs } from "../components/Dialogs";
import NoteCard, { NoteCardData } from "../components/NoteCard";
import { SectionHead, useLoad } from "../components/ui";
import "./Home.css";
import "../styles/profile.css";
import { RegionPicker, TYPES, TypeKey, hasCore, useProfile } from "../profile";
import TryIt from "./TryIt";
import { AffordHero, MarketBoard } from "./HomeMarket";
import { CATEGORIES, CountUp, MIN_NOTES_FOR_COUNTS, useShareVisit } from "./shared";

export { CATEGORIES, CountUp, useShareVisit };  // 예전 경로로 가져오는 곳을 위해


type Issue = { id?: number; week: string; range: string; headline_em: string; headline: string; body_html: string; editor_note_html?: string; pdf_url?: string };
type Home = {
  issue: Issue | null;
  issues: { week: string; headline_em: string; headline_short: string }[];
  leader3: { id: number; title: string; category: string; point: string }[];
  stance: string;
  for_you: { url: string; kicker: string; title: string }[];
  ticker: {
    head: string; basis?: string;
    rows: { keyword: string; cur: number; prev: number; rising: boolean; growth: number | null; is_new: boolean; label: string; href: string; note_title: string | null }[];
  } | null;
  latest_notes: NoteCardData[];
  counts: { notes: number; articles_week: number; sources: number };
  sources: Record<string, { name: string; url: string }[]>;
};


/** 공유 링크(?s=1)로 들어온 방문을 세션당 한 번 기록한다 (app/play_ui.track_share_visit). */

/** 소스 목록 — 그룹별 펼침 상자 (홈 '어디서 찾아 읽나'). */
// 출처 묶음 — 묶음 탭(곳 수) + 고른 묶음의 출처 칩. 예전 접이식 목록은 묶음이 많아지면 칸 높이가 들쭉날쭉했다 (2026-11-02)
const SRC_ICON: Record<string, string> = { "정부·공공": "🏛", "경제지 부동산": "📰", "종합·경제 뉴스": "🗞", "부동산 전문지": "🏗", "Google 뉴스 검색": "🔎",
  "네이버 뉴스 검색": "🔎", "유튜브": "▶", "블로그·커뮤니티": "💬", "해외 언론": "🌐", "해외 연구·리서치": "📊" };
/** 화면에 가까워질 때 그린다 — 첫 화면 아래 구역의 API 요청(시장 요약·최고가 거래)을 첫 그리기 뒤로 미룬다 (2026-11-02 속도 개선) */
function LazyMount({ children, minHeight }: { children: React.ReactNode; minHeight: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const [on, setOn] = useState(() => typeof IntersectionObserver === "undefined");
  useEffect(() => {
    if (on || !ref.current) return;
    const io = new IntersectionObserver((es) => { if (es.some((e) => e.isIntersecting)) { setOn(true); io.disconnect(); } }, { rootMargin: "600px 0px" });
    io.observe(ref.current);
    return () => io.disconnect();
  }, [on]);
  return <div ref={ref} style={on ? undefined : { minHeight }}>{on ? children : null}</div>;
}

export function SourceGroups({ sources }: { sources: Record<string, { name: string; url: string }[]> }) {
  const groups = Object.entries(sources).filter(([, v]) => v.length);
  const [pick, setPick] = useState(groups[0]?.[0] || "");
  const items = sources[pick] || [];
  return (
    <div className="src-box">
      <div className="src-tabs" role="tablist" aria-label="출처 묶음">
        {groups.map(([g, v]) => (
          <button key={g} type="button" role="tab" aria-selected={pick === g} className={`src-tab${pick === g ? " on" : ""}`} onClick={() => setPick(g)}>
            <span aria-hidden="true">{SRC_ICON[g] || "•"}</span>{g}<b>{v.length}</b>
          </button>
        ))}
      </div>
      <div className="src-chips" role="tabpanel" aria-label={pick}>
        {items.map((s) => <a key={s.name + s.url} href={s.url} target="_blank" rel="noopener" className="src-chip">{s.name.replace(/^유튜브 · /, "")}<span aria-hidden="true">↗</span></a>)}
      </div>
    </div>
  );
}

/** 내부 주소면 Link, 아니면 a. */
function Go({ href, className, children }: { href: string; className?: string; children: React.ReactNode }) {
  if (href.startsWith("/")) return <Link to={href} className={className}>{children}</Link>;
  return <a href={href} className={className}>{children}</a>;
}

function Ticker({ t }: { t: Home["ticker"] }) {
  const rows = (t?.rows || []).slice(0, 12);
  const trackRef = useRef<HTMLDivElement>(null);
  const setRef = useRef<HTMLDivElement>(null);
  const [overflow, setOverflow] = useState(false);
  // 한 벌이 띠 너비를 넘칠 때만 흐르게 한다 — 이음매 없는 흐름용 복제본은 그때만 붙이고(aria-hidden) 화면 읽기에는 한 벌만.
  useEffect(() => {
    const track = trackRef.current, set = setRef.current;
    if (!track || !set) return;
    const measure = () => setOverflow(set.scrollWidth > track.clientWidth + 1);
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(measure);
    ro.observe(track);
    ro.observe(set);
    return () => ro.disconnect();
  }, [rows.length]);
  if (!t || !rows.length) return null;
  const render = (copy: boolean) => rows.map((r, i) => (
    <Link key={(copy ? "b" : "a") + i} to={r.href || `/notes?q=${encodeURIComponent(r.keyword)}`} tabIndex={copy ? -1 : undefined}
      title={r.note_title ? `대표 노트: ${r.note_title}` : `${r.keyword} 노트 찾아보기`}>
      <i className={r.rising ? "up" : ""} aria-hidden="true">{r.is_new ? "●" : r.rising ? "▲" : "▼"}</i>{r.keyword}
      <b className={r.is_new ? "new" : r.rising ? "" : "down"}>{r.label || (r.is_new ? "신규" : `${r.growth ?? 0}%`)}</b>
    </Link>
  ));
  return (
    <div className="ticker" aria-label={t.head} title={t.basis || ""}>
      <span className="ticker-h">{t.head}</span>
      <div className="ticker-track" ref={trackRef}>
        <div className={`ticker-run${overflow ? "" : " static"}`}>
          <div className="ticker-set" ref={setRef}>{render(false)}</div>
          {overflow && <div className="ticker-set" aria-hidden="true">{render(true)}</div>}
        </div>
      </div>
    </div>
  );
}

/** 최신 노트 9편 — 60초마다 다시 받아 새로 생긴 카드는 잠깐 빛난다. 카테고리 수도 여기서 센다. */
function LatestNotes({ initial, onCounts }: { initial: NoteCardData[]; onCounts: (c: Record<string, number>, total: number) => void }) {
  const [notes, setNotes] = useState<NoteCardData[]>(initial);
  const [fresh, setFresh] = useState<Set<number>>(new Set());
  const known = useRef<Set<number> | null>(null);
  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const r = await get<{ notes: NoteCardData[] }>("notes?sort=latest");
        if (!alive || !r?.notes) return;
        const all = r.notes;
        const counts: Record<string, number> = {};
        for (const n of all) counts[n.category] = (counts[n.category] || 0) + 1;
        onCounts(counts, all.length);
        const latest = all.slice(0, 9);
        const ids = latest.map((n) => n.id);
        if (known.current) {
          const nf = new Set(ids.filter((i) => !known.current!.has(i)));
          if (nf.size) {
            setFresh(nf);
            window.setTimeout(() => alive && setFresh(new Set()), 5000);
          }
        }
        known.current = new Set(ids);
        setNotes(latest);
      } catch { /* 다음 주기에 다시 */ }
    };
    load();
    const t = window.setInterval(load, 60_000);
    return () => { alive = false; window.clearInterval(t); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return (
    <div className="grid">
      {notes.map((n) => <NoteCard key={n.id} n={n} fresh={fresh.has(n.id)} />)}
    </div>
  );
}

type Mine = {
  has_profile: boolean; items: (NoteCardData & { reason: string; matched: boolean })[];
  filled?: boolean; matched?: number; days?: number; type?: string; regions?: string[];
};

/** 프로필이 없는 방문자 — 2단계(유형 → 관심 지역 1곳)로 프로필을 만든다. 나머지는 /me 에서. */
function Onboarding() {
  const { save, flush } = useProfile();
  const [step, setStep] = useState(1);
  const [type, setType] = useState<TypeKey | undefined>();
  const [regions, setRegions] = useState<string[]>([]);
  const finish = async (regs: string[]) => {
    save({ type, regions: regs.length ? regs : undefined });
    await flush();
  };
  return (
    <section className="onb" id="mine" aria-label="내 프로필 만들기">
      <div className="eyebrow">나에게 맞춰 보기</div>
      <h3>두 가지만 알려 주면 <span className="grad">이번 주 나에게 영향 있는 노트</span>를 골라 드려요</h3>
      <div className="onb-steps"><span className={step === 1 ? "on" : ""}>1. 나는 지금</span><span>›</span><span className={step === 2 ? "on" : ""}>2. 관심 지역 1곳</span></div>
      {step === 1 ? (
        <div className="type-pick" role="radiogroup" aria-label="유형">
          {TYPES.map(([k, l, d]) => (
            <button key={k} type="button" role="radio" aria-checked={type === k} className={type === k ? "on" : ""}
              onClick={() => { setType(k); setStep(2); }}><b>{l}</b><span>{d}</span></button>
          ))}
        </div>
      ) : (
        <>
          <RegionPicker id="onb-region" value={regions} onChange={setRegions} max={1} placeholder="관심 있는 시군구 (예: 마포, 분당, 해운대)" />
          <div className="btn-row">
            <button type="button" className="btn primary" disabled={!regions.length} onClick={() => finish(regions)}>이대로 맞춰 보기 →</button>
            <button type="button" className="btn ghost" onClick={() => finish([])}>지역은 나중에</button>
            <button type="button" className="btn sm ghost" onClick={() => setStep(1)}>← 유형 다시 고르기</button>
          </div>
        </>
      )}
      <p className="caption" style={{ margin: "12px 0 0" }}>로그인 없이 이 브라우저에만 저장돼요. 예산·소득·청약 항목은 나중에 <Link to="/me">내 프로필</Link>에서 채울 수 있어요.</p>
    </section>
  );
}

/** 이번 주 나에게 영향 있는 것 3가지 — 프로필(유형·관심 지역)로 최근 14일 게시 노트를 서버가 고른다. */
function MineBlock() {
  const { profile, flush } = useProfile();
  const sig = `${profile?.type || ""}|${(profile?.regions || []).join(",")}`;
  const [mine, setMine] = useState<Mine | null | undefined>(undefined); // undefined = 고르는 중, null = 못 받음(블록 숨김)
  useEffect(() => {
    let alive = true;
    (async () => {
      await flush(); // 방금 저장한 프로필이 서버에 닿은 뒤에 고른다
      try { const r = await get<Mine>("home/mine"); if (alive) setMine(r); } catch { if (alive) setMine(null); }
    })();
    return () => { alive = false; };
  }, [sig, flush]);
  if (mine === null) return null;
  if (!mine) return <section className="mine" id="mine"><div className="page-loading" style={{ minHeight: 160 }}>나에게 맞는 노트를 고르는 중…</div></section>;
  if (!mine.has_profile) return null;
  const basis = [mine.type, ...(mine.regions || [])].filter(Boolean).join(" · ");
  return (
    <section className="mine l3" id="mine">
      <div className="eyebrow">내 프로필 기준</div>
      <h3 className="sec-h sub" style={{ marginBottom: 4 }}>이번 주 <span className="grad">나에게 영향 있는 것</span> 3가지</h3>
      <p className="mine-basis"><span>{basis} · 최근 {mine.days ?? 14}일 노트</span><Link to="/me">프로필 고치기 →</Link></p>
      {mine.items.length ? (
        <div className="l3-grid">
          {mine.items.map((t, i) => (
            <Link key={t.id} className="l3-card" to={`/notes?id=${t.id}`}>
              <span className="l3-n">{i + 1}</span>
              <span className={`why${t.matched ? "" : " dim"}`}>{t.reason}</span>
              <b className="t">{t.title}</b>
              <span className="src">{t.category} · {t.published}</span>
            </Link>
          ))}
        </div>
      ) : <p className="caption">아직 게시된 노트가 없어요. 노트가 쌓이면 여기에 먼저 골라 드릴게요.</p>}
      {mine.filled && mine.items.length > 0 && (
        <p className="mine-fill">최근 {mine.days ?? 14}일 노트 중 내 조건에 맞는 것이 {mine.matched ?? 0}편이라, 나머지는 최신 노트로 채웠어요.</p>
      )}
    </section>
  );
}

// 히어로 주제 — [이름, 화면, 아이콘]
const HERO_TOPICS: [string, string, string][] = [["실거래가", "/deals", "📈"], ["청약 일정", "/calendar", "🗓"], ["대출 한도", "/calc", "🏦"],
  ["취득세", "/calc?tab=tax", "🧾"], ["현행 규제", "/now", "📌"], ["시장 노트", "/notes", "📰"]];
const ROT_WORDS = ["시세", "청약", "대출", "세금", "전월세", "정책"];

/** 돌아가며 바뀌는 주제 단어 — 움직임 줄이기 설정이면 첫 단어만 */
function RotWord() {
  const [i, setI] = useState(0);
  useEffect(() => {
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;
    const t = window.setInterval(() => setI((x) => (x + 1) % ROT_WORDS.length), 2200);
    return () => window.clearInterval(t);
  }, []);
  return (
    <span className="rot" aria-live="off">
      <span key={i} className="rot-w grad">{ROT_WORDS[i]}</span>
    </span>
  );
}

/** 마우스 위치를 히어로의 CSS 변수로 — 빛(hero-glow)이 따라온다 */
function heroGlow(e: React.MouseEvent<HTMLElement>) {
  const r = e.currentTarget.getBoundingClientRect();
  e.currentTarget.style.setProperty("--mx", `${e.clientX - r.left}px`);
  e.currentTarget.style.setProperty("--my", `${e.clientY - r.top}px`);
}

export default function HomePage() {
  const { openSubscribe } = useDialogs();
  const { data, error } = useLoad(() => get<Home>("home"));
  const [catCounts, setCatCounts] = useState<Record<string, number> | null>(null);
  const [total, setTotal] = useState<number | null>(null);
  const { ready, profile } = useProfile();
  const loc = useLocation();
  useShareVisit("home");
  // /#mine (테스트 결과·내 프로필에서 들어올 때) — 블록이 그려진 뒤 그 자리로
  useEffect(() => {
    if (loc.hash !== "#mine" || !data) return;
    const t = window.setTimeout(() => document.getElementById("mine")?.scrollIntoView({ block: "start" }), 300);
    return () => window.clearTimeout(t);
  }, [loc.hash, data]);

  // 히어로(제목·버튼)는 API 를 기다리지 않고 바로 그린다 — 예전엔 /api/home 응답 전까지 '불러오는 중'만 보여
  // 휴대폰 첫 화면(LCP)이 6초를 넘었다. 숫자만 응답 뒤에 채운다.
  const hero = (c: { notes: number; articles_week: number; sources: number } | null) => (
    // 2026-11-02: 서비스 취지 = 집에 관한 모든 것. 주제 단어가 돌아가며 바뀌고(RotWord), 칩을 누르면 그 화면으로,
    // 마우스를 움직이면 빛이 따라온다(HeroGlow). '살 수 있는 집값' 계산은 아래 별도 구역(afford-sec)으로 옮겼다.
    <section className="hero hero2" onMouseMove={heroGlow}>
      <div className="hero-glow" aria-hidden="true" />
      <div className="hero-main">
        <div className="hero-kicker"><span className="grad">ZIPBOMI</span> · 집보미 — 집을 봐 주는 비서</div>
        <h1 className="hero-h1">집에 관한 모든 것,<br /><RotWord />까지 한곳에서</h1>
        <p className="hero-sub">아파트 실거래가부터 청약 일정, 대출 한도, 세금, 정책 변화까지. 흩어진 집 이야기를 매일 모아 숫자와 함께 정리해 드립니다.</p>
        <nav className="hero-topics" aria-label="주제 바로가기">
          {HERO_TOPICS.map(([label, to, icon]) => <Link key={to} to={to} className="hero-topic"><i aria-hidden="true">{icon}</i>{label}</Link>)}
        </nav>
        {c && c.notes >= MIN_NOTES_FOR_COUNTS && (
          <div className="hero-stats">
            <div><CountUp to={c.notes} /><span>쌓인 노트</span></div>
            <div><CountUp to={c.articles_week} /><span>7일간 읽은 기사</span></div>
            <div><CountUp to={c.sources} /><span>살펴보는 출처</span></div>
          </div>
        )}
        <div className="hero-btns">
          <button className="btn primary" onClick={() => openSubscribe("home_hero")}>월요일 맞춤 브리핑 받기 →</button>
          <Link className="btn ghost" to="/deals">실거래가 보기</Link>
        </div>
      </div>
    </section>
  );
  // .home — 홈 전용 가독성 규칙(Home.css 맨 아래)의 범위. 다른 페이지 스타일은 건드리지 않는다.
  if (error) return <div className="home">{hero(null)}<div className="alert err">{error}</div></div>;
  if (!data) return <div className="home">{hero(null)}<div className="page-loading" style={{ minHeight: 600 }}>불러오는 중…</div></div>;

  const issue = data.issue || { week: "", range: "", headline_em: "", headline: "첫 주간 흐름을 준비 중입니다", body_html: "" };
  const counts = data.counts || { notes: 0, articles_week: 0, sources: 0 };
  const issues = data.issues || [];
  const nNotes = total ?? counts.notes;
  const nSources = counts.sources ?? Object.values(data.sources || {}).reduce((a, v) => a + v.length, 0);
  const showCounts = nNotes >= MIN_NOTES_FOR_COUNTS;
  const hasIssue = !!data.issue?.id;

  return (
    <div className="home">
      {/* ---------- 히어로 ---------- */}
      {hero({ notes: counts.notes, articles_week: counts.articles_week, sources: nSources })}

      <Ticker t={data.ticker} />

      {/* ---------- 바로 계산 — 살 수 있는 집값 (히어로에서 분리, 2026-11-02) ---------- */}
      <section className="afford-sec" aria-label="살 수 있는 집 가격 계산">
        <div className="eyebrow">바로 계산</div>
        <h2 className="sec-h">대출까지 받으면 <span className="grad">얼마짜리 집</span>을 살 수 있을까?</h2>
        <AffordHero />
      </section>

      {/* ---------- 지금 시장 (지표·거래·청약·기사 — 2026-11-02 보강) ---------- */}
      <LazyMount minHeight={420}><MarketBoard /></LazyMount>

      {/* ---------- For you ---------- */}
      {data.for_you?.length > 0 && (
        <>
          <div className="eyebrow">나에게 맞는 다음 단계</div>
          <div className="start foryou">
            {data.for_you.slice(0, 4).map((c) => (
              <Go key={c.url + c.title} href={c.url}><span className="n">{c.kicker}</span><b>{c.title}</b><em>보기 →</em></Go>
            ))}
          </div>
        </>
      )}

      {/* ---------- 처음 오셨나요 ---------- */}
      <div className="eyebrow">처음 오셨다면</div>
      <h3 className="sec-h sub">처음이라면 <span className="grad">이 3가지</span>만 보세요</h3>
      <div className="start">
        <a href={hasIssue ? "#this-week" : "/notes"}><span className="n">01 · 1분</span><b>이번 주 부동산 흐름</b>
          <span>한 주의 시세·정책·청약 소식을 한 줄 헤드라인과 노트로 묶었어요. 바로 아래에 있어요.</span><em>매주 월요일 갱신</em></a>
        <Link to="/type"><span className="n">02 · 1분</span><b>나의 부동산 성향은?</b>
          <span>12문항으로 16가지 부동산 성향 중 내 유형과 잘 맞는 전략을 알려 드려요.</span><em>결과 공유하기 ↗</em></Link>
        <Link to="/today"><span className="n">03 · 30초</span><b>오늘의 부동산 퀴즈</b>
          <span>실제 기사로 만든 3문제와 '내일의 키워드' 투표. 매일 새로 나와요.</span><em>🔥 연속 참여 기록</em></Link>
      </div>

      {/* ---------- 1분 안에 해 보기 (각 페이지 인터랙션 맛보기) ---------- */}
      <TryIt />

      {/* ---------- 나에게 영향 있는 것 3가지 (프로필 없으면 2단계 온보딩) ---------- */}
      {ready && (hasCore(profile) ? <MineBlock /> : <Onboarding />)}

      {/* ---------- 이번 주 흐름 ---------- */}
      <div id="this-week" />
      {hasIssue && <section className="week">
        <div>
          <div className="eyebrow">이번 주 · {issue.week} · {issue.range}</div>
          <h2 className="sec-h">이번 주 <span className="grad">부동산 흐름</span></h2>
          <h3 className="week-title">{issue.headline_em && <span>{issue.headline_em} </span>}{issue.headline}</h3>
          <p className="week-body" dangerouslySetInnerHTML={{ __html: issue.body_html || "" }} />
          {issue.editor_note_html && (
            <div className="ednote"><i>EDITOR'S NOTE</i><span dangerouslySetInnerHTML={{ __html: issue.editor_note_html }} /></div>
          )}
          {issue.pdf_url && <a className="btn" style={{ marginTop: 14 }} href={issue.pdf_url} download>📄 이번 호 PDF 리포트 받기</a>}
        </div>
        <div className="flow">
          <span className="flow-h">흐름의 이동</span>
          <ol>
            {issues.slice(-5).map((x, i, arr) => (
              <li key={x.week + i} className={i === arr.length - 1 ? "now" : ""}>
                <b>{x.week}</b>{`${x.headline_em || ""} ${x.headline_short || ""}`.trim()}
              </li>
            ))}
          </ol>
        </div>
      </section>}

      {/* ---------- 이번 주 꼭 알아야 할 3가지 ---------- */}
      {data.leader3?.length > 0 && (
        <div className="l3">
          <div className="eyebrow">핵심 3가지</div>
          <h3 className="sec-h sub" style={{ marginBottom: 4 }}>이번 주 <span className="grad">꼭 알아야 할 3가지</span></h3>
          <p className="sec-p" style={{ margin: 0 }}>{data.stance}</p>
          <div className="l3-grid">
            {data.leader3.map((t, i) => (
              <Link key={t.id} className="l3-card" to={`/notes?id=${t.id}`}>
                <span className="l3-n">{i + 1}</span>
                <b className="t">{t.point}</b>
                <span className="src">{t.category} · {(t.title || "").slice(0, 60)}</span>
              </Link>
            ))}
          </div>
          <Link to="/letter" className="more wrap" style={{ display: "inline-block", marginTop: 12 }}>✉ 이 내용이 매주 메일로 옵니다 · 메일 미리 보기 →</Link>
        </div>
      )}

      {/* ---------- 노트 (게시된 노트가 있을 때만 — 없을 때 빈 칸을 보이지 않는다) ---------- */}
      {(data.latest_notes || []).length > 0 && <>
      <div style={{ marginTop: 36 }} />
      <SectionHead
        eyebrow="최신 노트" title="쌓이는" grad="노트"
        p={<>기사와 발표 원문을 읽고 요약·핵심 포인트·내게 미치는 영향까지 정리했어요.{showCounts ? ` 노트 ${nNotes}편.` : ""}</>}
        right={<Link className="more" to="/notes">전체 보기 →</Link>}
      />
      <nav className="cat-nav">
        {CATEGORIES.map((c) => (
          <Link key={c} to={`/notes?cat=${encodeURIComponent(c)}`}>
            <b>{c}</b>{showCounts && <i>{catCounts ? catCounts[c] || 0 : "·"}</i>}
          </Link>
        ))}
      </nav>
      <LatestNotes initial={data.latest_notes || []} onCounts={(c, t) => { setCatCounts(c); setTotal(t); }} />
      </>}

      {/* ---------- 소스 ---------- */}
      <section className="sources">
        <div className="eyebrow">출처</div>
        <h2 className="sec-h">어디서 <span className="grad">찾아 읽나</span></h2>
        <p className="sec-p" style={{ marginBottom: 18 }}>
          아래 {nSources}곳을 매일 훑어 중요한 것만 골라 노트로 남깁니다. 정부 발표·통계처럼 1차 자료를 먼저 봅니다.
        </p>
        <SourceGroups sources={data.sources || {}} />
      </section>

      {/* ---------- 뉴스레터 CTA ---------- */}
      <section className="cta">
        <div>
          <div className="eyebrow" style={{ color: "#FFE89A" }}>뉴스레터</div>
          <h2 className="sec-h" style={{ color: "#fff" }}>이번 주 부동산 소식,<br />월요일 아침 메일로</h2>
          <p className="sec-p">시세·청약·대출·세금·정책 중 꼭 알아야 할 것만 골라 보내 드려요.</p>
        </div>
        <button className="btn cta-btn" onClick={() => openSubscribe("home_cta")}>무료로 받아 보기 →</button>
      </section>
    </div>
  );
}
