// 음성으로 질문 입력 (2026-11-19) — 브라우저 기본 음성 인식(Web Speech API)을 쓴다. 집보미 서버는 소리를 받지 않고, 글자로 바뀐 문장만 입력칸에 들어간다.
// 안내: 크롬·사파리 등은 인식을 위해 음성을 브라우저 회사 서버로 보낼 수 있다 — 처음 한 번 확인을 받는다. 지원하지 않는 브라우저에서는 버튼을 그리지 않는다.
import { useEffect, useRef, useState } from "react";

type SR = { lang: string; interimResults: boolean; continuous: boolean; start(): void; stop(): void; onresult: ((e: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null; onend: (() => void) | null; onerror: (() => void) | null };
const Ctor = (): (new () => SR) | null => {
  const w = window as unknown as { SpeechRecognition?: new () => SR; webkitSpeechRecognition?: new () => SR };
  return w.SpeechRecognition || w.webkitSpeechRecognition || null;
};
const KEY = "zg-voice-ok";
const ls = (f: () => string | null) => { try { return f(); } catch { return null; } };

export default function VoiceButton({ value, onChange, max = 500, disabled = false }: { value: string; onChange: (v: string) => void; max?: number; disabled?: boolean }) {
  const [on, setOn] = useState(false);
  const rec = useRef<SR | null>(null);
  const base = useRef("");
  useEffect(() => () => { try { rec.current?.stop(); } catch { /* 이미 멈춤 */ } }, []);
  if (typeof window === "undefined" || !Ctor()) return null;
  const toggle = () => {
    if (on) { rec.current?.stop(); return; }
    if (ls(() => localStorage.getItem(KEY)) !== "1") {
      if (!window.confirm("음성 입력은 브라우저가 소리를 글자로 바꿔 줘요. 브라우저(크롬·사파리 등)가 인식을 위해 음성을 자기 회사 서버로 보낼 수 있어요. 집보미 서버는 소리를 받지 않아요. 계속할까요?")) return;
      ls(() => { localStorage.setItem(KEY, "1"); return null; });
    }
    const C = Ctor()!;
    const r = new C();
    r.lang = "ko-KR"; r.interimResults = true; r.continuous = false;
    base.current = value && !value.endsWith(" ") ? value + " " : value;
    r.onresult = (e) => {
      const t = Array.from(e.results).map((x) => x[0].transcript).join("");
      onChange((base.current + t).slice(0, max));
    };
    r.onend = () => setOn(false);
    r.onerror = () => setOn(false);
    rec.current = r;
    try { r.start(); setOn(true); } catch { setOn(false); }
  };
  return (
    <button type="button" className={`btn voice-btn${on ? " on" : ""}`} onClick={toggle} disabled={disabled} aria-pressed={on}
      aria-label={on ? "음성 입력 멈추기" : "음성으로 입력"} title="음성으로 질문 입력 (브라우저 기능 사용)">{on ? "⏹" : "🎤"}</button>
  );
}
