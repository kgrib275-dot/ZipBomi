// 전체 검색 창 (2026-11-19) — 상단 🔍 또는 Ctrl/⌘+K 로 연다. 화면·단지·시군구·청약 공고·노트를 한 곳에서, 초성(ㄷㅊ)과 오타(레미안)도 찾는다.
// 화면 이름은 여기서 바로 거르고, 나머지는 GET /api/find (backend/api/routers/find.py). LLM 없음.
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { get } from "../api";
import { getRecent, recentIcon } from "../recent";

type Hit = { key: string; to: string; label: string; sub?: string; group: string };
type Found = {
  apts: { lawd: string; dong: string; apt: string; region: string }[]; regions: { code: string; name: string }[];
  notices: { id: string; name: string; region: string; date: string }[]; notes: { id: number; title: string; kind: string }[];
};
const PAGES: [string, string][] = [["/", "홈 · 이번 주 시장"], ["/map", "지도로 보기"], ["/deals", "실거래가 조회"], ["/lab", "지역 비교 · 데이터 랩"], ["/my-homes", "관심 단지"],
  ["/calendar", "청약 일정 달력"], ["/deals?tab=apply", "청약 공고 목록"], ["/calendar?tab=scores", "지난 당첨 가점"], ["/notes", "시장 해설 노트"], ["/now", "규제 · 금리 현황"],
  ["/calc", "내 집 계산기 (대출·취득세·청약 가점)"], ["/my", "내 공간 · 달력 · 알림"], ["/ask", "보미AI에게 묻기"], ["/today", "오늘의 퀴즈"], ["/terms", "부동산 용어 퀴즈"],
  ["/about", "서비스 소개"], ["/help", "고객센터 · 문의"], ["/privacy", "개인정보 처리방침"]];
const CHO = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ";
const norm = (s: string) => s.toLowerCase().replace(/[\s·\-_.,()[\]]/g, "");
const cho = (s: string) => Array.from(norm(s)).map((ch) => { const o = ch.charCodeAt(0) - 0xac00; return o >= 0 && o < 11172 ? CHO[Math.floor(o / 588)] : ch; }).join("");
const isCho = (q: string) => q.length >= 2 && Array.from(q).every((c) => CHO.includes(c));
const pageMatch = (q: string, t: string) => (isCho(norm(q)) ? cho(t).includes(norm(q)) : norm(t).includes(norm(q)));

export default function FindBox({ onClose }: { onClose: () => void }) {
  const nav = useNavigate();
  const [q, setQ] = useState("");
  const [found, setFound] = useState<Found | null>(null);
  const [cur, setCur] = useState(0);
  const [busy, setBusy] = useState(false);
  const inp = useRef<HTMLInputElement>(null);
  useEffect(() => { inp.current?.focus(); }, []);
  useEffect(() => {
    const t = q.trim();
    if (norm(t).length < 2) { setFound(null); setBusy(false); return; }
    setBusy(true);
    const id = setTimeout(() => { get<Found>(`find?q=${encodeURIComponent(t)}`).then(setFound).catch(() => setFound(null)).finally(() => setBusy(false)); }, 200);
    return () => clearTimeout(id);
  }, [q]);
  const hits = useMemo<Hit[]>(() => {
    const t = q.trim();
    const pages = (t ? PAGES.filter(([, l]) => pageMatch(t, l)) : PAGES.slice(0, 8)).slice(0, 6).map(([to, label]): Hit => ({ key: "p" + to, to, label, group: "화면" }));
    const recent = !t ? getRecent().slice(0, 5).map((r): Hit => ({ key: "c" + r.to, to: r.to, label: `${recentIcon(r.kind)} ${r.title}`, sub: r.sub, group: "최근 본 것" })) : [];
    if (!found) return [...recent, ...pages];
    return [
      ...found.apts.map((a): Hit => ({ key: `a${a.lawd}${a.dong}${a.apt}`, to: `/my-homes?lawd=${a.lawd}&dong=${encodeURIComponent(a.dong)}&apt=${encodeURIComponent(a.apt)}`, label: a.apt, sub: `${a.region} ${a.dong}`.trim(), group: "단지" })),
      ...found.regions.map((r): Hit => ({ key: "r" + r.code, to: `/deals?lawd=${r.code}`, label: r.name, sub: "실거래가 보기", group: "지역" })),
      ...found.notices.map((n): Hit => ({ key: "n" + n.id, to: `/deals?tab=apply&q=${encodeURIComponent(n.name.slice(0, 30))}`, label: n.name, sub: `${n.region} ${n.date}`.trim(), group: "청약 공고" })),
      ...found.notes.map((n): Hit => ({ key: "t" + n.id, to: `/notes?id=${n.id}`, label: n.title, sub: n.kind, group: "노트" })),
      ...pages,
    ];
  }, [q, found]);
  useEffect(() => setCur(0), [hits.length, q]);
  const go = (h?: Hit) => { if (!h) return; onClose(); nav(h.to); };
  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setCur((c) => Math.min(hits.length - 1, c + 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setCur((c) => Math.max(0, c - 1)); }
    else if (e.key === "Enter") { e.preventDefault(); go(hits[cur]); }
  };
  let last = "";
  return (
    <div className="find-bg" role="presentation" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="find-box" role="dialog" aria-modal="true" aria-label="전체 검색" onKeyDown={onKey}>
        <input ref={inp} type="search" value={q} maxLength={40} onChange={(e) => setQ(e.target.value)} placeholder="단지·지역·청약 공고·노트·화면 찾기 (초성도 돼요: ㄷㅊ)"
          aria-label="검색어" aria-controls="find-list" autoComplete="off" />
        <ul id="find-list" role="listbox">
          {hits.map((h, i) => {
            const head = h.group !== last ? <li className="find-h" role="presentation" key={"h" + h.group}>{h.group}</li> : null;
            last = h.group;
            return [head, <li key={h.key} role="option" aria-selected={i === cur} className={i === cur ? "on" : ""} onMouseEnter={() => setCur(i)} onClick={() => go(h)}>
              <span className="t">{h.label}</span>{h.sub && <span className="s">{h.sub}</span>}</li>];
          })}
          {!busy && q.trim() && norm(q).length >= 2 && found && hits.every((h) => h.group === "화면") && <li className="find-none" role="presentation">찾는 단지·공고·노트가 없어요. 철자를 줄여 보세요.</li>}
        </ul>
        <div className="find-ft"><span>↑↓ 고르기 · Enter 열기 · Esc 닫기</span><button type="button" className="btn sm ghost" onClick={onClose}>닫기</button></div>
      </div>
    </div>
  );
}
