// AX 준비도 자가진단 (/diagnosis) — 12문항 × 4단계, 세 영역. 답할 때마다 점수·레이더가 바로 바뀐다.
// 답은 방문자 상태(dq_<영역>_<번호>)와 결과 링크(?a=코드)에만 담긴다. 가장 약한 영역은 diag_weak 로 남겨 홈 추천에 쓴다.
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { get, post } from "../api";
import { SubscribeCTA } from "../components/Dialogs";
import NoteCard, { NoteCardData } from "../components/NoteCard";
import { useShareVisit } from "../components/ProfileForm";
import ShareBar from "../components/ShareBar";
import { Alert, useLoad } from "../components/ui";
import { useMe } from "../me";
import ProfileCTA from "../components/ProfileCTA";
import { useProfile } from "../profile";
import "./Diagnosis.css";

type Areas = Record<string, [string, string[]]>;
type Level = [number, string, string]; // (상한, 이름, 색)
type DiagData = { areas: Areas; scale: string[]; levels: Level[]; next: Record<string, string[]> };
type Result = {
  code: string; scores?: Record<string, number>; total?: number; level?: [string, string]; weakest?: string;
  // 서버는 {영역: {label, score, level, color, step}} 로 보낸다 — 문자열·목록 모양도 받는다
  next_steps?: Record<string, string | { step?: string }> | { cat: string; step: string }[]; recommended?: NoteCardData[]; report_txt?: string;
  share?: { url?: string; image?: string; title?: string; text?: string };
};

const DEFAULT_LEVELS: Level[] = [[25, "준비 시작", "#B8AB8A"], [50, "기초 다짐", "#FFD54A"], [75, "실행 준비", "#F5B800"], [101, "실행 가능", "#0ca30c"]];

// 서버가 주는 단계 색(다크 기준 hex)을 테마 토큰으로 — 다크에서는 같은 색, 라이트에서는 대비를 맞춘 색
const TONE: Record<string, string> = { "#8c9bb5": "var(--muted)", "#5bc2f5": "var(--accent-2)", "#2e9bea": "var(--accent)", "#b8ab8a": "var(--muted)", "#ffd54a": "var(--accent-2)", "#f5b800": "var(--accent)", "#d9a100": "var(--accent-deep)", "#0ca30c": "var(--ok)" };
const tone = (c: string) => TONE[c.toLowerCase()] || c;

function levelOf(levels: Level[], score: number): [string, string] {
  const hit = levels.find(([limit]) => score < limit) || levels[levels.length - 1];
  return hit ? [hit[1], tone(hit[2])] : ["", "var(--muted)"];
}

export default function Diagnosis() {
  useShareVisit("diagnosis");
  const { state, setState } = useMe();
  const [params, setParams] = useSearchParams();
  const { data, error, loading } = useLoad<DiagData>(() => get<DiagData>("diagnosis"), []);
  const areas = useMemo(() => data?.areas || {}, [data]);
  const scale = data?.scale || ["아직 아니에요", "조금", "대체로", "확실히"];
  const levels = data?.levels?.length ? data.levels : DEFAULT_LEVELS;
  const keys = useMemo(() => Object.entries(areas).flatMap(([cat, [, qs]]) => qs.map((_, i) => [cat, i] as [string, number])), [areas]);

  // ---------- 공유 링크에서 답 불러오기 (한 번만) ----------
  const loaded = useRef(false);
  useEffect(() => {
    if (loaded.current || !keys.length) return;
    loaded.current = true;
    const shared = params.get("a") || "";
    if (new RegExp(`^[0-${scale.length - 1}]{${keys.length}}$`).test(shared)) {
      const patch: Record<string, unknown> = {};
      keys.forEach(([cat, i], k) => { patch[`dq_${cat}_${i}`] = scale[Number(shared[k])]; });
      setState(patch);
    }
  }, [keys, params, scale, setState]);

  // ---------- 점수 계산 (답하지 않은 문항은 '아직 없음'으로) ----------
  const answers = useMemo(() => {
    const out: Record<string, number | null> = {};
    keys.forEach(([cat, i]) => {
      const v = state[`dq_${cat}_${i}`];
      const idx = typeof v === "string" ? scale.indexOf(v) : typeof v === "number" ? v : -1;
      out[`${cat}:${i}`] = idx >= 0 ? idx : null;
    });
    return out;
  }, [keys, state, scale]);
  const done = Object.values(answers).filter((v) => v !== null).length;
  const scores = useMemo(() => {
    const s: Record<string, number> = {};
    Object.entries(areas).forEach(([cat, [, qs]]) => {
      const sum = qs.reduce((a, _, i) => a + (answers[`${cat}:${i}`] || 0), 0);
      s[cat] = (sum / ((scale.length - 1) * Math.max(1, qs.length))) * 100;
    });
    return s;
  }, [areas, answers, scale.length]);
  const cats = Object.keys(scores);
  const total = cats.length ? cats.reduce((a, c) => a + scores[c], 0) / cats.length : 0;
  const code = keys.map(([cat, i]) => (answers[`${cat}:${i}`] ?? 0)).join("");
  const weakest = cats.length ? cats.reduce((a, c) => (scores[c] < scores[a] ? c : a), cats[0]) : "";

  // 결과 링크 = 현재 주소
  useEffect(() => {
    if (!keys.length) return;
    const cur = params.get("a") || "";
    if (done && cur !== code) { params.set("a", code); setParams(params, { replace: true }); }
    else if (!done && cur) { params.delete("a"); setParams(params, { replace: true }); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [done, code, keys.length]);

  // 가장 약한 영역을 기억한다 (홈 '나를 위한 추천')
  useEffect(() => {
    if (done && weakest && state.diag_weak !== weakest) setState({ diag_weak: weakest });
  }, [done, weakest, state.diag_weak, setState]);

  // 모든 문항에 답하면 내 프로필에 기록 (점수·단계·가장 약한 영역 — 같은 값이면 다시 쓰지 않는다)
  const { recordTest } = useProfile();
  const complete = keys.length > 0 && done === keys.length;
  const levelName = levelOf(levels, total)[0];
  const weakLabel = areas[weakest]?.[0] || "";
  const rounded = Math.round(total);
  useEffect(() => {
    if (!complete) return;
    const t = window.setTimeout(() => recordTest("diagnosis", { score: rounded, level: levelName, weak: weakLabel }), 600);
    return () => window.clearTimeout(t);
  }, [complete, rounded, levelName, weakLabel, recordTest]);

  // ---------- 서버 결과 (추천 노트·보고서·기록) — 답이 바뀌면 잠시 뒤 한 번만 ----------
  const [res, setRes] = useState<Result | null>(null);
  useEffect(() => {
    if (!done || !keys.length) { setRes(null); return; }
    const t = window.setTimeout(() => {
      post<Result>("diagnosis/result", { answers: keys.map(([cat, i]) => answers[`${cat}:${i}`]) }).then(setRes).catch(() => setRes(null));
    }, 500);
    return () => window.clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [code, done, keys.length]);

  if (loading && !data) return <div className="page-loading">불러오는 중…</div>;
  if (error || !data) return <Alert kind="err">{error || "자가진단을 불러오지 못했습니다."}</Alert>;

  const [name, color] = levelOf(levels, total);
  const nextStep = (cat: string) => {
    const ns = res?.next_steps;
    if (ns && !Array.isArray(ns) && ns[cat]) {
      const v = ns[cat];
      if (typeof v === "string") return v;
      if (v && typeof v === "object" && v.step) return v.step;
    }
    if (Array.isArray(ns)) { const f = ns.find((x) => x.cat === cat); if (f) return f.step; }
    const list = data.next?.[cat] || [];
    return list[Math.min(list.length - 1, Math.floor(scores[cat] / 25))] || "";
  };
  const lvlIdx = Math.min(3, Math.floor(total / 25));
  const report = res?.report_txt || [
    `내 집 마련 준비도 자가진단 결과 — 종합 ${Math.round(total)}점 (${name} 단계)`, "",
    ...cats.map((c) => `[${areas[c][0]}] ${Math.round(scores[c])}점 (${levelOf(levels, scores[c])[0]}) — 다음 단계: ${nextStep(c)}`),
    "", "문항별 응답",
    ...keys.map(([c, i]) => `- ${areas[c][1][i]}: ${answers[`${c}:${i}`] !== null ? scale[answers[`${c}:${i}`] as number] : "미응답"}`),
  ].join("\n");
  const download = () => {
    const blob = new Blob([report], { type: "text/plain;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "ax_self_check.txt";
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  };

  return (
    <div className="diag-page">
      <div className="eyebrow">자가진단</div>
      <h2 className="sec-h">내 집 마련 <span className="grad">준비도 자가진단</span></h2>
      <p className="sec-p" style={{ maxWidth: 760 }}>12문항에 답하면 자금·대출 / 정보·지역 / 실행·계약 세 영역의 준비도와 다음 단계를 바로 보여 드려요. 답은 서버에 저장하지 않고, 결과 링크에만 담깁니다.</p>

      <div className="diag-cols">
        <div className="diag-q">
          {Object.entries(areas).map(([cat, [label, qs]]) => (
            <section key={cat}>
              <h3 className="diag-h">{label} · {cat}</h3>
              {qs.map((q, i) => {
                const cur = answers[`${cat}:${i}`];
                return (
                  <div className="diag-item" key={i}>
                    <div className="diag-qt">{i + 1}. {q}</div>
                    <div className="seg" role="radiogroup" aria-label={q}>
                      {scale.map((s, k) => (
                        <button key={s} type="button" role="radio" aria-checked={cur === k} className={cur === k ? "on" : ""}
                          onClick={() => setState({ [`dq_${cat}_${i}`]: cur === k ? null : s })}>{s}</button>
                      ))}
                    </div>
                  </div>
                );
              })}
            </section>
          ))}
        </div>

        <div className="diag-result">
          <div className="eyebrow">결과 · {done}/{keys.length} 응답</div>
          <div className="diag-prog"><div style={{ width: `${(done / Math.max(1, keys.length)) * 100}%` }} /></div>
          <div className="diag-total">
            <b>{Math.round(total)}</b>
            <span style={{ color }}>● {name} 단계</span>
          </div>
          <p className="caption" style={{ margin: "4px 0 0" }}>100점 만점 · 영역 평균</p>
          <Radar scores={scores} areas={areas} />
          {done < keys.length && <p className="caption">남은 문항 {keys.length - done}개 — 답하지 않은 문항은 '아직 아니에요'로 계산해요.</p>}
        </div>
      </div>

      {done > 0 && (
        <>
          <div className="space" />
          <div className="eyebrow">다음 단계</div>
          <h3 className="sec-h" style={{ fontSize: "1.4rem" }}>영역별 <span className="grad">다음 단계</span></h3>
          <div className="diag-next">
            {cats.map((cat) => {
              const [lv, lc] = levelOf(levels, scores[cat]);
              return (
                <div className="box" key={cat}>
                  <div className="diag-nh"><b>{areas[cat][0]}</b><span style={{ color: lc }}>{Math.round(scores[cat])}점 · {lv}</span></div>
                  <div className="diag-bar"><div style={{ width: `${Math.round(scores[cat])}%` }} /></div>
                  <p>{nextStep(cat)}</p>
                  {cat === weakest && <p className="diag-weak">▲ 가장 먼저 보강할 영역</p>}
                </div>
              );
            })}
          </div>

          <ShareBar content="diagnosis" note={`결과 코드 ${code}`} url={res?.share?.url || `/s/d?a=${code}`} title={res?.share?.title || `내 집 마련 준비도: ${name} 단계`}
            text={res?.share?.text || `내 집 마련 준비도 자가진단 결과 저는 '${name}' 단계(${Math.round(total)}점)예요. 12문항·3분이면 돼요.`}
            image={res?.share?.image || `/app/static/og/diag-${lvlIdx}.png`} imageName="zipgenie-self-check.png" />
          <div className="btn-row" style={{ margin: "10px 0" }}>
            <button className="btn" type="button" onClick={download}>⬇ 결과 내려받기 (.txt)</button>
            <Link className="btn primary" to="/calc">내 집 계산기로 자금 계산해 보기 →</Link>
          </div>
          {complete ? <ProfileCTA what="준비도 진단" /> : <p className="caption">12문항을 모두 답하면 결과가 내 프로필에 기록돼요.</p>}
          <SubscribeCTA source="diagnosis" headline={`${areas[weakest]?.[0] || ""} 영역을 채울 노트를 매주 받아 보세요`} sub="가장 약한 영역에 도움이 되는 소식과 체크리스트를 주간 메일로 보내 드려요." />
          {!!res?.recommended?.length && (
            <>
              <div className="eyebrow" style={{ marginTop: 24 }}>추천 노트</div>
              <h3 className="sec-h" style={{ fontSize: "1.3rem" }}>{areas[weakest]?.[0]} 영역 <span className="grad">추천 노트</span></h3>
              <div className="grid">{res.recommended.map((n) => <NoteCard key={n.id} n={n} />)}</div>
            </>
          )}
        </>
      )}
    </div>
  );
}

/** 3축 레이더 — Streamlit 판 radar_svg 를 인라인 SVG 로 옮김 (한 계열이라 한 색, 값은 꼭짓점에 직접 표시). */
function Radar({ scores, areas }: { scores: Record<string, number>; areas: Areas }) {
  const size = 320, cx = 160, cy = 170, r = 115;
  const cats = Object.keys(scores);
  if (!cats.length) return null;
  const ang = cats.map((_, i) => -Math.PI / 2 + (i * 2 * Math.PI) / cats.length);
  const pt = (a: number, v: number): [number, number] => [cx + Math.cos(a) * r * v, cy + Math.sin(a) * r * v];
  const pts = (v: number) => ang.map((a) => pt(a, v).map((n) => n.toFixed(1)).join(",")).join(" ");
  const poly = ang.map((a, i) => pt(a, (scores[cats[i]] || 0) / 100).map((n) => n.toFixed(1)).join(",")).join(" ");
  const alt = cats.map((c) => `${areas[c]?.[0] || c} ${Math.round(scores[c])}점`).join(", ");
  return (
    <svg className="diag-radar" viewBox={`0 0 ${size} ${size + 20}`} role="img" aria-label={`영역별 점수 레이더: ${alt}`}
      fontFamily="IBM Plex Sans KR, Malgun Gothic, sans-serif">
      {[0.25, 0.5, 0.75, 1].map((g) => <polygon key={g} points={pts(g)} fill="none" style={{ stroke: "var(--line)" }} strokeWidth={1} />)}
      {ang.map((a, i) => { const [x, y] = pt(a, 1); return <line key={i} x1={cx} y1={cy} x2={x.toFixed(1)} y2={y.toFixed(1)} style={{ stroke: "var(--line)" }} />; })}
      <polygon points={poly} fill="rgba(245,184,0,.22)" style={{ stroke: "var(--accent)" }} strokeWidth={2} />
      {ang.map((a, i) => {
        const c = cats[i];
        const [x, y] = pt(a, (scores[c] || 0) / 100);
        const [lx, ly] = pt(a, 1.22);
        const anchor = Math.abs(Math.cos(a)) < 0.3 ? "middle" : Math.cos(a) > 0 ? "start" : "end";
        return (
          <g key={c}>
            <circle cx={x.toFixed(1)} cy={y.toFixed(1)} r={5} style={{ fill: "var(--accent)", stroke: "var(--surface)" }} strokeWidth={2} />
            <text x={lx.toFixed(1)} y={ly.toFixed(1)} textAnchor={anchor} style={{ fill: "var(--ink-2)" }} fontSize={12}>
              {areas[c]?.[0] || c}
              <tspan x={lx.toFixed(1)} dy={16} style={{ fill: "var(--ink)" }} fontWeight={700} fontSize={15}>{Math.round(scores[c])}</tspan>
            </text>
          </g>
        );
      })}
    </svg>
  );
}
