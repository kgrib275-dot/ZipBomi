// 고객센터 (/help) — 자주 묻는 질문(분류·검색) + 문의 양식 (2026-11-05).
// 로그인 전 둘러보기가 끝난 사람도 들어올 수 있어야 한다(로그인 메일이 안 오는 사람이 문의할 곳) — TrialGate OPEN 과 백엔드 gate.OPEN 에 /help·/api/contact 가 들어 있다.
import { useEffect, useMemo, useState } from "react";
import { useLocation, useSearchParams } from "react-router-dom";
import { get } from "../api";
import { ContactForm } from "../components/Dialogs";
import { FAQ, FAQ_CATS, type FaqCat } from "../faq";
import { Tabs, useLoad } from "../components/ui";
import "./Home.css";

const ALL = "전체";
// 자주 찾는 도움 — 누르면 해당 질문을 바로 열어 준다
const QUICK: [string, string, string][] = [
  ["📭", "로그인 메일이 안 와요", "로그인 메일이 안 와요"],
  ["🗑", "내 정보 지우기", "내 정보·기록을 지우고 싶어요"],
  ["🛠", "숫자가 달라 보여요", "숫자가 실제와 달라 보여요"],
  ["⚖", "권리침해 신고", "저작권·명예훼손 등 권리침해를 신고하고 싶어요"],
];

export default function Help() {
  const { data } = useLoad(() => get<{ counts?: { sources?: number }; sources?: Record<string, unknown[]> }>("about"), []);
  const sources = data?.counts?.sources ?? Object.values(data?.sources || {}).reduce((a, v) => a + v.length, 0);
  const [cat, setCat] = useState<string>(ALL);
  const [q, setQ] = useState("");
  const [openQ, setOpenQ] = useState<string | null>(null);
  const [sp] = useSearchParams();
  const loc = useLocation();
  const kind = sp.get("kind") || undefined;

  useEffect(() => {
    // /help#contact 또는 ?kind=… 로 들어오면 문의 양식으로
    if (loc.hash === "#contact" || kind) document.getElementById("contact")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [loc.hash, kind]);

  const items = useMemo(() => {
    const t = q.trim().toLowerCase();
    return FAQ.filter((f) => {
      if (cat !== ALL && f.cat !== (cat as FaqCat)) return false;
      if (!t) return true;
      const a = typeof f.a === "string" ? f.a : "";
      return f.q.toLowerCase().includes(t) || a.toLowerCase().includes(t) || f.cat.includes(t);
    });
  }, [cat, q]);

  return (
    <>
      <div className="eyebrow">도움말</div>
      <h2 className="sec-h">고객<span className="grad">센터</span></h2>
      <p className="sec-p" style={{ maxWidth: 760 }}>자주 묻는 질문에서 답을 찾아 보시고, 없으면 아래에서 문의해 주세요. 보통 1~2일 안에 이메일로 답장 드려요.</p>

      <div className="cols3" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(min(200px,100%),1fr))", marginTop: 18 }}>
        {QUICK.map(([icon, label, target]) => (
          <button key={label} type="button" className="box" style={{ textAlign: "left", cursor: "pointer", font: "inherit", color: "inherit" }}
            onClick={() => { setCat(ALL); setQ(""); setOpenQ(target); setTimeout(() => document.getElementById("faq-list")?.scrollIntoView({ behavior: "smooth", block: "start" }), 0); }}>
            <b>{icon} {label}</b>
          </button>
        ))}
      </div>

      <h3 className="sub-h" id="faq-list">자주 묻는 질문</h3>
      <div className="field">
        <label htmlFor="faq-q" className="sr-only">질문 검색</label>
        <input id="faq-q" type="search" placeholder="궁금한 단어로 찾아보기 (예: 로그인, 해지, 삭제)" maxLength={50} value={q}
          onChange={(e) => { setQ(e.target.value); setOpenQ(null); }} />
      </div>
      <Tabs items={[ALL, ...FAQ_CATS]} value={cat} onChange={(v) => { setCat(v); setOpenQ(null); }} />
      {items.map((f) => (
        <details key={f.q} className="expander" open={openQ === f.q || undefined} onToggle={(e) => { if (!(e.currentTarget as HTMLDetailsElement).open && openQ === f.q) setOpenQ(null); }}>
          <summary>{f.q}</summary>
          <div className="body sec-p">{typeof f.a === "function" ? f.a({ sources }) : f.a}</div>
        </details>
      ))}
      {!items.length && <p className="caption">찾는 질문이 없어요. 아래에서 문의해 주시면 답장 드릴게요.</p>}

      <h3 className="sub-h" id="contact" style={{ marginTop: 28 }}>원하는 답이 없나요? 문의하기</h3>
      <div style={{ maxWidth: 720 }}><ContactForm kind={kind} /></div>
    </>
  );
}
