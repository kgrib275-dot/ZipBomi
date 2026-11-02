// 노트 (/notes) — Streamlit 판 app_pages/notes.py + app/note_ui.py 이식.
// ?id= 가 있으면 상세, 없으면 목록. 필터(q·semantic·cats·kinds·inds·sort)는 방문자 상태(useMe)에 저장돼 다음 방문에도 그대로다.
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { get } from "../api";
import { INDUSTRIES, SubscribeCTA } from "../components/Dialogs";
import NoteCard, { FORMATS, NoteCardData, useBookmarks } from "../components/NoteCard";
import ShareBar from "../components/ShareBar";
import { Alert, useLoad } from "../components/ui";
import { useMe } from "../me";
import { TYPE_LABEL, hasCore, regionShort, useProfile, useRegions } from "../profile";
import { CATEGORIES, useShareVisit } from "./shared";
import { Pager, SizeSel, usePageSize } from "./reShared";
import { type Param, ParamCard, basisOf, useNow } from "../policy";
import "./RealEstate.css";
import "./Notes.css";
import "../styles/profile.css";

type ListRes = {
  notes: NoteCardData[];
  meta?: { categories?: string[]; kinds?: string[]; industries?: string[] };
  semantic_note?: string;
  mine?: { applied: boolean; type: string; regions: string[] };
};
type Impact = { key: string; label: string; html: string; from?: string };
type Detail = {
  note: NoteCardData & { body_html: string; toc?: string[]; url?: string; status?: string; body?: string; impact?: Impact[]; policy?: Param[] };
  prev?: { id: number; title: string } | null;
  next?: { id: number; title: string } | null;
  related?: NoteCardData[];
  share_url?: string;
};

const SORTS: [string, string][] = [["latest", "최신순"], ["popular", "인기순"]];

const asList = (v: unknown): string[] => (Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : []);

/** 브라우저 탭·북마크·공유 제목. 화면을 떠나면 이전 제목으로 되돌린다 (SPA 라 서버가 넣은 <title>이 그대로 남지 않게). */
function useTitle(title: string | undefined) {
  useEffect(() => {
    if (!title) return;
    const prev = document.title;
    document.title = title;
    return () => { document.title = prev; };
  }, [title]);
}

export default function NotesPage() {
  const [params] = useSearchParams();
  const id = params.get("id");
  useShareVisit("note");
  return id && /^[0-9]{1,9}$/.test(id) ? <NoteDetail id={id} /> : <NoteList />;
}

/* ====================== 상세 ====================== */
function NoteDetail({ id }: { id: string }) {
  const { data, error, loading } = useLoad(() => get<Detail>(`notes/${id}`), [id]);
  const bodyRef = useRef<HTMLDivElement>(null);
  const [more, setMore] = useState(false);
  const [pendingJump, setPendingJump] = useState<string | null>(null);
  const { profile } = useProfile();
  useTitle(data?.note.title ? `${data.note.title} — 집보미` : undefined);

  useEffect(() => { window.scrollTo(0, 0); setMore(false); }, [id]);
  useEffect(() => {
    if (more && pendingJump) { jumpTo(bodyRef.current, pendingJump); setPendingJump(null); }
  }, [more, pendingJump]);

  if (error) return (
    <>
      <Link className="more" to="/notes">← 노트 목록</Link>
      <Alert kind="warn">{error}</Alert>
    </>
  );
  if (loading || !data) return <div className="page-loading">불러오는 중…</div>;
  const n = data.note;
  const tags = (n.tags || "").split(",").filter(Boolean).map((t) => `#${t}`).join(" ");
  const audiences = (n.audiences || "").split(",").filter(Boolean);
  // 읽는 시간: 본문 글자 수 / 600 (원본은 마크다운 길이 기준)
  const textLen = (n.body || n.body_html || "").replace(/<[^>]+>/g, "").length;
  const minutes = Math.max(1, Math.round(textLen / 600));
  const toc = n.toc || [];
  // 긴 노트는 '요약·핵심 포인트'만 먼저 보이고 나머지(기술·운영 디테일·현업 실행·AX 적용)는 '자세히 보기'로 편다 — 3분 안에 핵심
  const html = n.body_html || "";
  const cut = textLen > 1500 ? nthIndex(html, "<h3", 3) : -1;
  const head = cut > 0 && !more ? html.slice(0, cut) : html;
  const restTitles = cut > 0 ? toc.slice(2) : [];
  const headMin = Math.max(1, Math.round(head.replace(/<[^>]+>/g, "").length / 600));

  const impact = n.impact || [];
  const jump = (want: string) => {
    if (want === IMPACT_TITLE) { jumpTo(bodyRef.current, want); return; }
    if (cut > 0 && !more && restTitles.some((t) => t === want)) { setMore(true); setPendingJump(want); return; }
    jumpTo(bodyRef.current, want);
  };

  return (
    <>
      <Link className="more" to="/notes">← 노트 목록</Link>
      {n.status && n.status !== "published" && <Alert kind="warn">게시 전 초안 미리보기입니다. 관리 &gt; 노트 검토에서 게시할 수 있습니다.</Alert>}
      <div className="meta detail-meta">
        <span className="badge">{n.category}</span><span className="kind">{n.kind}</span>
      </div>
      <h1 className="detail-h">{n.title}</h1>
      <div className="src" style={{ color: "var(--muted)", fontSize: ".85rem" }}>
        {n.source} · {(n.published || "").replace(/-/g, ".")} · {tags}
      </div>
      {audiences.length > 0 && <div className="aud" style={{ marginTop: 10 }}>{audiences.map((a) => <span key={a}>{a}</span>)}</div>}

      {/* 목차 칩 + 읽는 시간 (note_ui.detail_bar) */}
      <div className="nt-bar">
        <span className="nt-read">{cut > 0 ? `핵심 ${headMin}분 · 전체 ${minutes}분` : `약 ${minutes}분 읽기`}</span>
        {toc.map((h) => <button key={h} type="button" className="toc" onClick={() => jump(h)}>{h}</button>)}
        {impact.length > 0 && <button type="button" className="toc" onClick={() => jump(IMPACT_TITLE)}>{IMPACT_TITLE}</button>}
      </div>
      <ShareBar content="note" url={data.share_url} title={n.title} />
      <hr className="divider" />
      <div ref={bodyRef}>
        <div className="note-body" dangerouslySetInnerHTML={{ __html: head }} />
        {cut > 0 && !more && (
          <button type="button" className="btn block" style={{ marginTop: 12 }} onClick={() => setMore(true)}>
            자세히 보기 — {restTitles.join(" · ")} (+{Math.max(1, minutes - headMin)}분)
          </button>
        )}
        {impact.length > 0 && <ImpactBlocks key={n.id} blocks={impact} mine={profile?.type} />}
      </div>
      {!!n.policy?.length && <PolicyBlock items={n.policy} />}
      {n.url && <a className="btn" href={n.url} target="_blank" rel="noopener" style={{ marginTop: 14 }}>↗ 원문 보기</a>}

      {(data.prev || data.next) && (
        <div className="note-nav">
          {data.prev && <Link className="nav-prev" to={`/notes?id=${data.prev.id}`}><span>← 이전 노트</span><b>{data.prev.title}</b></Link>}
          {data.next && <Link className="nav-next" to={`/notes?id=${data.next.id}`}><span>다음 노트 →</span><b>{data.next.title}</b></Link>}
        </div>
      )}

      {data.related && data.related.length > 0 && (
        <>
          <div className="eyebrow" style={{ marginTop: 28 }}>관련 노트</div>
          <h3 className="sec-h" style={{ fontSize: "1.3rem" }}>이 노트와 <span className="grad">가까운 노트</span></h3>
          <div className="grid">{data.related.map((r) => <NoteCard key={r.id} n={r} />)}</div>
        </>
      )}
      <hr className="divider" />
      <SubscribeCTA source="note_detail" headline="이런 노트를 매주 받아 보세요" sub="한 주의 노트 5편과 부동산 흐름 요약을 월요일 아침 메일로 보내 드려요." />
    </>
  );
}

const IMPACT_TITLE = "나에게 미치는 영향";

/** 이 노트가 다루는 현행 수치 — 지금 값·기준일·근거와 '내 돈으로 치면' 예시 (pipeline/policy.py · policy.tsx) */
function PolicyBlock({ items }: { items: Param[] }) {
  const { profile } = useProfile();
  const { map } = useNow();
  const basis = basisOf(profile);
  const all = { ...map, ...Object.fromEntries(items.map((p) => [p.key, p])) };
  return (
    <section className="now-related" aria-label="관련 현행 수치">
      <h3 style={{ margin: "0 0 4px" }}>관련 현행 수치</h3>
      <p className="caption" style={{ margin: "0 0 10px" }}>
        이 노트가 다루는 숫자의 지금 값이에요. {basis.mine ? "예시는 내 프로필의 예산·연소득으로 계산했어요." : "예시는 8억원 집·연소득 7,000만원 기준이에요."}{" "}
        <Link to="/now">현행 수치 전체 →</Link>
      </p>
      <div className="now-grid">{items.map((p) => <ParamCard key={p.key} p={p} basis={basis} map={all} compact />)}</div>
    </section>
  );
}

/** 나에게 미치는 영향 — 유형별 접이식 블록. 내 프로필 유형을 맨 앞에 펼쳐 두고 나머지는 접는다. 프로필이 없으면 모두 펼친다. */
function ImpactBlocks({ blocks, mine }: { blocks: Impact[]; mine?: string }) {
  const has = !!mine && blocks.some((b) => b.key === mine);
  const ordered = has ? [...blocks.filter((b) => b.key === mine), ...blocks.filter((b) => b.key !== mine)] : blocks;
  return (
    <section className="impact note-body">
      <h3>{IMPACT_TITLE}</h3>
      <p className="caption" style={{ margin: "0 0 6px" }}>
        {has ? `내 유형(${TYPE_LABEL[mine!]})을 먼저 펼쳐 두었어요. 다른 유형은 눌러서 볼 수 있어요.`
          : mine ? `이 노트에는 ${TYPE_LABEL[mine] || "내 유형"} 관점이 따로 정리돼 있지 않아 전체를 펼쳐 두었어요.`
          : <>유형별로 정리했어요. <Link to="/me">내 프로필</Link>에서 유형을 정하면 내 유형만 먼저 펼쳐 둡니다.</>}
      </p>
      {ordered.map((b) => {
        const isMine = b.key === mine;
        return (
          <details key={b.key} className={isMine ? "mine" : ""} open={!has || isMine}>
            <summary>{b.label}{isMine && <span className="tag">내 유형</span>}</summary>
            <div className="ib" dangerouslySetInnerHTML={{ __html: b.html }} />
          </details>
        );
      })}
    </section>
  );
}

/* ====================== 목록 ====================== */
function NoteList() {
  const { me, state, setState } = useMe();
  const [params] = useSearchParams();
  const [bm, toggleBm] = useBookmarks();
  const [only, setOnly] = useState(false);
  useTitle("부동산 노트 — 집보미");

  // 필터 값: 방문자 상태 → 없으면 기본값. 업종 기본값은 구독할 때 고른 업종(pref_inds).
  const q = typeof state.q === "string" ? state.q : "";
  const semantic = state.semantic === true;
  const cats = asList(state.cats);
  const kinds = asList(state.kinds);
  const formats = asList(state.formats).filter((x) => x in FORMATS);
  const inds = state.inds === undefined ? asList(state.pref_inds).filter((x) => INDUSTRIES.includes(x)) : asList(state.inds);
  const sort = state.sort === "popular" || state.sort === "인기순" ? "popular" : "latest";
  const { profile } = useProfile();
  const canMine = hasCore(profile);
  const { byCode } = useRegions();
  const mineOn = state.notes_mine === true && canMine; // '내 조건에 맞는 노트만' — 방문자 상태에 기억

  // 주소의 ?cat= / ?ind= 는 그 값으로 필터를 맞춘다 (홈 카테고리 내비·For you 카드에서 들어올 때)
  const cat = params.get("cat"), ind = params.get("ind"), qParam = (params.get("q") || "").trim().slice(0, 60);
  useEffect(() => {
    if (!me) return; // 방문자 상태를 받기 전에 바꾸면 서버 스냅샷이 덮어쓴다
    if (cat && CATEGORIES.includes(cat)) setState({ cats: [cat] });
    if (ind && INDUSTRIES.includes(ind)) setState({ inds: [ind] });
    if (qParam) setState({ q: qParam, cats: [], kinds: [] }); // 홈 급상승 키워드 띠에서 들어올 때 — 그 키워드로 검색
  }, [me, cat, ind, qParam, setState]);

  // 검색어 입력은 잠깐 모아서 저장·조회한다
  const [qLocal, setQLocal] = useState(q);
  const seeded = useRef(false);
  useEffect(() => {
    if (me && !seeded.current) { seeded.current = true; setQLocal(qParam || q); }
  }, [me, q, qParam]);
  useEffect(() => {
    const t = window.setTimeout(() => { if (qLocal !== q) setState({ q: qLocal }); }, 350);
    return () => window.clearTimeout(t);
  }, [qLocal, q, setState]);

  const query = useMemo(() => {
    const p = new URLSearchParams();
    if (q) p.set("q", q);
    if (semantic) p.set("semantic", "1");
    if (cats.length) p.set("cats", cats.join(","));
    if (kinds.length) p.set("kinds", kinds.join(","));
    if (formats.length) p.set("formats", formats.join(","));
    if (inds.length) p.set("inds", inds.join(","));
    p.set("sort", sort);
    if (mineOn) p.set("mine", "1");
    // 프로필이 바뀌면 다시 받는다 (서버가 저장된 프로필로 거른다)
    if (mineOn) p.set("_p", `${profile?.type || ""}.${(profile?.regions || []).join("-")}`);
    return p.toString();
  }, [q, semantic, cats.join(","), kinds.join(","), formats.join(","), inds.join(","), sort, mineOn, profile?.type, (profile?.regions || []).join("-")]); // eslint-disable-line react-hooks/exhaustive-deps

  const { data, error, loading } = useLoad(() => get<ListRes>(`notes?${query}`), [query]);
  // 유형 목록은 필터 없이 받은 첫 결과의 meta 를 기억한다 (필터를 걸어도 알약이 줄지 않게)
  const [meta, setMeta] = useState<{ kinds: string[]; industries: string[]; total: number } | null>(null);
  useEffect(() => {
    if (!data) return;
    setMeta((m) => {
      const kindsAll = data.meta?.kinds?.length ? data.meta.kinds : Array.from(new Set(data.notes.map((n) => n.kind))).sort();
      const indsAll = data.meta?.industries?.length ? data.meta.industries : INDUSTRIES;
      const unfiltered = !q && !cats.length && !kinds.length && !inds.length;
      if (!m || unfiltered) return { kinds: kindsAll, industries: indsAll, total: unfiltered ? data.notes.length : m?.total ?? data.notes.length };
      return { ...m, kinds: m.kinds.length ? m.kinds : kindsAll };
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);

  const toggle = (key: "cats" | "kinds" | "inds" | "formats", cur: string[], v: string) =>
    setState({ [key]: cur.includes(v) ? cur.filter((x) => x !== v) : [...cur, v] });

  const hits = data?.notes || [];
  const filtered = only ? hits.filter((n) => bm.has(n.id)) : hits;
  // 표시 개수·쪽 (2026-11-02) — 개수는 이 브라우저에 기억, 필터가 바뀌면 첫 쪽으로
  const [size, setSize] = usePageSize("notes", 12);
  const [page, setPage] = useState(0);
  const pages = Math.max(1, Math.ceil(filtered.length / size));
  const pageNow = Math.min(page, pages - 1);
  const shown = filtered.slice(pageNow * size, pageNow * size + size);
  const goPage = (p: number) => { setPage(p); document.querySelector(".nf-result")?.scrollIntoView({ behavior: "smooth", block: "center" }); };
  useEffect(() => setPage(0), [q, semantic, cats.join(","), kinds.join(","), formats.join(","), inds.join(","), sort, mineOn, only]); // eslint-disable-line react-hooks/exhaustive-deps
  const extraCount = kinds.length + formats.length + inds.length;
  const [moreOpen, setMoreOpen] = useState(false);
  const moreOn = moreOpen;
  const anyFilter = !!q || cats.length > 0 || extraCount > 0 || mineOn || only;
  const clearAll = () => { setQLocal(""); setState({ q: "", cats: [], kinds: [], formats: [], inds: [], notes_mine: false }); setOnly(false); };
  const semanticOn = !!q && semantic && hits.length > 0 && hits.some((n) => n.similarity !== undefined);
  const tail = semanticOn ? " · 뜻이 가까운 순" : sort === "popular" ? " · 조회 많은 순" : "";

  return (
    <>
      <div className="eyebrow">노트</div>
      <h2 className="sec-h">모든 <span className="grad">노트</span></h2>
      <p className="sec-p" style={{ marginBottom: 12 }}>노트 {meta?.total ?? hits.length}편. 검색하거나 분야를 고르면 바로 걸러져요. ☆로 저장한 노트는 '저장한 노트'에서 모아 봅니다.</p>

      <Top3 />

      {/* 2026-11-02 단순화: 검색·정렬·내 조건·저장한 노트를 한 줄에, 분야는 칩 한 줄, 나머지(유형·읽는 방식·지역)는 '필터 더 보기' 안에 */}
      <div className="nf-bar">
        <div className="nf-search">
          <span className="nf-ico" aria-hidden="true">⌕</span>
          <input id="note-q" type="search" value={qLocal} onChange={(e) => setQLocal(e.target.value)} maxLength={200} aria-label="노트 검색"
            placeholder={semantic ? "문장으로 물어보세요 (예: 전세 만기 때 뭘 확인하지?)" : "제목·요약·태그 검색"} />
          <button type="button" className={`nf-sem${semantic ? " on" : ""}`} aria-pressed={semantic} title="단어가 달라도 뜻이 가까운 노트를 찾습니다"
            onClick={() => setState({ semantic: !semantic })}>뜻으로 찾기</button>
        </div>
        <div className="seg nf-sort" role="group" aria-label="정렬">
          {SORTS.map(([v, l]) => <button key={v} type="button" className={sort === v ? "on" : ""} onClick={() => setState({ sort: v })}>{l}</button>)}
        </div>
      </div>

      <div className="nf-chips">
        <button type="button" className={`pill ${!cats.length ? "on" : ""}`} onClick={() => setState({ cats: [] })}>전체</button>
        {CATEGORIES.map((c) => <button key={c} type="button" className={`pill ${cats.includes(c) ? "on" : ""}`} onClick={() => toggle("cats", cats, c)}>{c}</button>)}
        <span className="nf-sep" aria-hidden="true" />
        <button type="button" className={`pill ${mineOn ? "on" : ""}`} aria-pressed={mineOn} disabled={!canMine}
          title={canMine ? "내 프로필(유형·관심 지역) 기준" : "내 프로필에서 유형·관심 지역을 정하면 쓸 수 있어요"}
          onClick={() => setState({ notes_mine: !mineOn })}>{mineOn ? "✓ " : ""}내 조건만</button>
        <button type="button" className={`pill ${only ? "on" : ""}`} aria-pressed={only} onClick={() => setOnly((o) => !o)}>
          {only ? "★" : "☆"} 저장한 노트{bm.size ? ` ${bm.size}` : ""}
        </button>
        <button type="button" className={`pill nf-more${moreOn ? " open" : ""}`} aria-expanded={moreOn} onClick={() => setMoreOpen(!moreOn)}>
          필터 더 보기{extraCount ? <b>{extraCount}</b> : null} <span aria-hidden="true">{moreOn ? "▴" : "▾"}</span>
        </button>
      </div>

      {moreOn && (
        <div className="nf-more-box">
          <div className="nf-row"><span className="nf-k">유형</span>
            {(meta?.kinds || []).map((k) => <button key={k} type="button" className={`pill sm ${kinds.includes(k) ? "on" : ""}`} onClick={() => toggle("kinds", kinds, k)}>{k}</button>)}
          </div>
          <div className="nf-row"><span className="nf-k">읽는 방식</span>
            {Object.entries(FORMATS).map(([k, l]) => <button key={k} type="button" className={`pill sm ${formats.includes(k) ? "on" : ""}`} onClick={() => toggle("formats", formats, k)}>{l}</button>)}
          </div>
          <div className="nf-row"><span className="nf-k" title="노트에 나온 시·구 이름으로 분류합니다.">지역</span>
            {(meta?.industries || INDUSTRIES).map((k) => <button key={k} type="button" className={`pill sm ${inds.includes(k) ? "on" : ""}`} onClick={() => toggle("inds", inds, k)}>{k}</button>)}
          </div>
        </div>
      )}

      {data?.semantic_note && <p className="caption">{data.semantic_note}</p>}
      {error && <Alert kind="err">{error}</Alert>}
      <div className="nf-result">
        <span>{loading && !data ? "찾는 중…" : `${filtered.length}편${tail}`}
          {mineOn && canMine && <> · {[profile?.type ? TYPE_LABEL[profile.type] : "", ...(profile?.regions || []).map((c) => regionShort(byCode, c))].filter(Boolean).join(" · ")} 기준 <Link to="/me">바꾸기</Link></>}
        </span>
        <span className="nf-right">
          {anyFilter && <button type="button" className="nf-clear" onClick={clearAll}>필터 모두 지우기 ✕</button>}
          <SizeSel size={size} setSize={setSize} setPage={setPage} />
        </span>
      </div>

      {shown.length > 0 ? (
        <>
          <div className="grid" style={{ marginTop: 12 }}>
            {shown.map((n) => <NoteCard key={n.id} n={n} bookmarked={bm.has(n.id)} onBookmark={toggleBm} />)}
          </div>
          <Pager page={pageNow} pages={pages} setPage={goPage} />
        </>
      ) : only ? (
        <div className="bm-empty">북마크한 노트가 없습니다. 카드 오른쪽 위 ☆를 눌러 저장하세요.</div>
      ) : data ? (
        <Alert kind="info">조건에 맞는 노트가 없습니다.</Alert>
      ) : null}
    </>
  );
}

function nthIndex(s: string, sub: string, n: number): number {
  let i = -1;
  for (let k = 0; k < n; k++) { i = s.indexOf(sub, i + 1); if (i < 0) return -1; }
  return i;
}

function jumpTo(root: HTMLElement | null, want: string) {
  const hs = root?.querySelectorAll("h3") || [];
  const h = Array.from(hs).find((x) => (x.textContent || "").trim().startsWith(want));
  h?.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
}

/** 나에게 맞는 TOP 3 (2026-11-02) — 프로필(유형·관심 지역)이 있으면 /api/home/mine 의 맞춤 3편, 없으면 많이 본 3편 */
function Top3() {
  const { data } = useLoad(async () => {
    const mine = await get<{ has_profile: boolean; items: (NoteCardData & { reason?: string })[]; regions?: string[]; type?: string }>("home/mine");
    if (mine.has_profile && mine.items.length) return { mine: true, items: mine.items.slice(0, 3), who: [mine.type, ...(mine.regions || [])].filter(Boolean).join(" · ") };
    const pop = await get<{ notes: NoteCardData[] }>("notes?sort=popular");
    return { mine: false, items: (pop.notes || []).slice(0, 3), who: "" };
  }, []);
  if (!data || !data.items.length) return null;
  return (
    <section className="top3">
      <div className="top3-h">
        <b>{data.mine ? "나에게 맞는 TOP 3" : "많이 본 TOP 3"}</b>
        <span className="caption">{data.mine ? `${data.who} 기준` : <><Link to="/me">내 프로필</Link>을 정하면 관심사에 맞춰 골라 드려요</>}</span>
      </div>
      <div className="top3-g">
        {data.items.map((n, i) => (
          <Link key={n.id} to={`/notes?id=${n.id}`} className="top3-c">
            <span className="rk">{i + 1}</span>
            <span className="cat">{n.category}</span>
            <b>{n.title}</b>
            {"reason" in n && (n as { reason?: string }).reason && <span className="why">✓ {(n as { reason?: string }).reason}</span>}
          </Link>
        ))}
      </div>
    </section>
  );
}
