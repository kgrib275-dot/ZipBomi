// 보미AI 옆 패널 (2026-11-02) — 페이지를 옮기지 않고 보던 화면 옆에서 질문한다. ✦ 버튼·메뉴 '보미AI'로 연다.
// 질문은 /api/ask (내 공간 자료 함께 — mine), 대화는 이 탭(sessionStorage)에만 남고 /ask 전체 화면과 이어진다.
// 로그인 전이면 로그인 안내, 무료 1회를 다 쓰면 관리자 문의로 사용 신청.
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, get, post } from "../api";
import { useDialogs } from "../components/Dialogs";
import { useMe } from "../me";

type Turn = { role: "user" | "assistant"; content: string };
type Usage = { enabled: boolean; quota: number; used: number; limit_hit: boolean; linked: boolean; need_grant?: boolean; is_admin: boolean;
  email_masked?: string; member?: { expires?: string } | null };
const HKEY = "zipgenie-ask-history";
const MKEY = "zipgenie-ask-mine";
const SUGGEST = ["내 관심 단지 최근 거래 흐름 요약해 줘", "이번 주 꼭 알아야 할 부동산 소식 3가지", "내 가점으로 해볼 만한 청약은?", "스트레스 DSR이 내 대출 한도에 주는 영향은?"];

const load = (): Turn[] => { try { const v = JSON.parse(sessionStorage.getItem(HKEY) || "[]"); return Array.isArray(v) ? v : []; } catch { return []; } };

/** 답변 글 — 줄바꿈·**굵게**·[링크](주소) 만 (사이트 안 경로와 http(s) 링크만 연다) */
function Text({ s }: { s: string }) {
  return (
    <>
      {s.split("\n").map((line, i) => {
        const parts: React.ReactNode[] = [];
        const re = /\*\*[^*]+\*\*|\[[^\]]+\]\([^)\s]+\)/g;
        let last = 0, k = 0;
        for (let m = re.exec(line); m; m = re.exec(line)) {
          if (m.index > last) parts.push(line.slice(last, m.index));
          const t = m[0];
          if (t.startsWith("**")) parts.push(<b key={k++}>{t.slice(2, -2)}</b>);
          else {
            const lm = /^\[([^\]]+)\]\(([^)\s]+)\)$/.exec(t);
            const href = lm?.[2] || "";
            const internal = /^\/(?![/\\])/.test(href);
            parts.push(internal || /^https?:\/\//i.test(href) ? <a key={k++} href={href} target={internal ? "_self" : "_blank"} rel="noopener noreferrer">{lm?.[1]}</a> : lm?.[1]);
          }
          last = m.index + t.length;
        }
        if (last < line.length) parts.push(line.slice(last));
        return <p key={i}>{parts.length ? parts : " "}</p>;
      })}
    </>
  );
}

export default function AskPanel() {
  const { me } = useMe();
  const { openLogin, openContact } = useDialogs();
  const [open, setOpen] = useState(false);
  const [hist, setHist] = useState<Turn[]>(load);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [usage, setUsage] = useState<Usage | null>(null);
  const [mine, setMine] = useState(() => { try { return localStorage.getItem(MKEY) === "1"; } catch { return false; } });
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const on = () => setOpen(true);
    window.addEventListener("zg-open-ask", on);
    return () => window.removeEventListener("zg-open-ask", on);
  }, []);
  useEffect(() => { if (open) get<Usage>("ask/usage").then(setUsage).catch(() => undefined); }, [open, me?.account]);
  useEffect(() => { try { sessionStorage.setItem(HKEY, JSON.stringify(hist.slice(-20))); } catch { /* 무시 */ } end.current?.scrollIntoView({ block: "nearest" }); }, [hist, busy]);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);
  const send = async (text: string) => {
    const t = text.trim();
    if (!t || busy) return;
    setErr(""); setBusy(true); setQ("");
    const next: Turn[] = [...hist, { role: "user", content: t }];
    setHist(next);
    try {
      const r = await post<{ answer: string }>("ask", { question: t, mine, history: hist.slice(-6) });
      setHist([...next, { role: "assistant", content: r.answer }]);
    } catch (e) {
      setHist(hist);
      setQ(t);
      if (e instanceof ApiError && e.data?.contact) setUsage((u) => (u ? { ...u, limit_hit: true, need_grant: true } : u));
      setErr(e instanceof Error ? e.message : "답을 받지 못했어요.");
    } finally {
      setBusy(false);
      get<Usage>("ask/usage").then(setUsage).catch(() => undefined);
    }
  };
  if (!open) return null;
  const loggedIn = !!me?.account || !!me?.is_admin;
  const left = usage ? Math.max(0, usage.quota - usage.used) : 0;
  return (
    <aside className="ask-panel" role="dialog" aria-label="보미AI">
      <div className="ap-h">
        <span className="ap-logo" aria-hidden="true">✦</span><b>보미AI</b>
        <span className="sp" />
        <Link to="/ask" className="ap-ic" title="전체 화면으로" onClick={() => setOpen(false)}>⤢</Link>
        <button type="button" className="ap-ic" aria-label="닫기" onClick={() => setOpen(false)}>×</button>
      </div>
      <div className="ap-sub">
        {!loggedIn ? "메일로 로그인하면 처음 1번 무료" : usage?.is_admin ? "관리자 · 한도 없음" : usage?.member ? "월 구독" : usage ? `남은 질문 ${left}/${usage.quota}회` : ""}
        <span> · 생성형 AI 답변이라 틀릴 수 있어요</span>
      </div>
      <div className="ap-body">
        {!hist.length && (
          <div className="ap-empty">
            <div className="ap-big">✦</div>
            <b>무엇이든 물어보세요</b>
            <p>시세·청약·대출·세금·정책을 노트와 공개 자료로 답합니다. 아래에서 켜면 내 공간의 관심 단지·공고도 참고해요.</p>
            <p className="ap-ai">보미AI 답변은 생성형 AI가 만든 결과물이라 틀릴 수 있어요. 중요한 결정 전에는 원문·공고로 확인하세요. 주민번호·계좌번호 같은 민감한 정보는 적지 마세요.</p>
            {SUGGEST.map((s) => <button key={s} type="button" className="ap-sug" disabled={!loggedIn || busy} onClick={() => send(s)}>{s}<span>›</span></button>)}
          </div>
        )}
        {hist.map((t, i) => <div key={i} className={`ap-msg ${t.role}`}>{t.role === "assistant" ? <Text s={t.content} /> : t.content}</div>)}
        {busy && <div className="ap-msg assistant typing">답을 찾는 중…</div>}
        {err && <div className="ap-err">{err}</div>}
        <div ref={end} />
      </div>
      {!loggedIn ? (
        <div className="ap-foot"><button type="button" className="btn primary block" onClick={openLogin}>✉️ 메일로 로그인하고 질문하기</button></div>
      ) : usage?.need_grant ? (
        <div className="ap-foot">
          <p className="caption">무료 1회를 모두 쓰셨어요. 더 쓰시려면 관리자에게 사용을 신청해 주세요.</p>
          <button type="button" className="btn primary block" onClick={() => openContact(`[보미AI 사용 신청]\n계정: ${usage.email_masked || ""}\n사용 목적: \n희망 횟수: `)}>📨 관리자에게 사용 신청</button>
        </div>
      ) : (
        <>
        <label className="ap-mine" title="관심 단지·관심 공고·내 프로필·메모를 질문과 함께 Google Gemini로 보냅니다">
          <input type="checkbox" checked={mine} onChange={(e) => { setMine(e.target.checked); try { localStorage.setItem(MKEY, e.target.checked ? "1" : "0"); } catch { /* 무시 */ } }} /> 내 공간 자료도 참고해서 답하기
        </label>
        <form className="ap-in" onSubmit={(e) => { e.preventDefault(); send(q); }}>
          <textarea rows={2} maxLength={500} value={q} placeholder="예: 광진구 84㎡ 요즘 시세 어때?" onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(q); } }} disabled={busy} />
          <button className="btn primary" disabled={busy || !q.trim()} aria-label="보내기">↑</button>
        </form>
        </>
      )}
    </aside>
  );
}
