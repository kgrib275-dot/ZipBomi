// 작은 공용 조각 — 섹션 제목, 안내 상자, 알림, 대화상자 틀, 탭.
import { useEffect, useRef, useState } from "react";

export function Eyebrow({ children }: { children: React.ReactNode }) {
  return <div className="eyebrow">{children}</div>;
}

export function SectionHead({ eyebrow, title, grad, p, right }: { eyebrow?: string; title: string; grad?: string; p?: React.ReactNode; right?: React.ReactNode }) {
  return (
    <div className="sec-head">
      <div>
        {eyebrow && <div className="eyebrow">{eyebrow}</div>}
        <h2 className="sec-h">
          {title} {grad && <span className="grad">{grad}</span>}
        </h2>
        {p && <p className="sec-p">{p}</p>}
      </div>
      {right}
    </div>
  );
}

export function Guide({ title, items }: { title: string; items: [string, string][] }) {
  return (
    <div className="guide">
      <div className="guide-h">👀 {title}</div>
      <ol>
        {items.map(([h, d]) => (
          <li key={h}>
            <b>{h}</b>
            <span>{d}</span>
          </li>
        ))}
      </ol>
    </div>
  );
}

export function Alert({ kind = "info", children }: { kind?: "info" | "ok" | "warn" | "err"; children: React.ReactNode }) {
  return <div className={`alert ${kind}`}>{children}</div>;
}

/** keep: 편집 중인 폼처럼 실수로 닫히면 안 되는 창 — 바깥 클릭·Esc 로 닫지 않는다 */
export function Dialog({ title, onClose, wide, xl, keep, children }: { title: string; onClose: () => void; wide?: boolean; xl?: boolean; keep?: boolean; children: React.ReactNode }) {
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => !keep && e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, keep]);
  // 키보드 접근성 (2026-11-03): 열면 창 안 첫 입력칸으로 포커스, Tab 은 창 안에서만 돌고, 뒤 페이지는 스크롤되지 않게. 닫으면 원래 자리로.
  useEffect(() => {
    const before = document.activeElement as HTMLElement | null;
    const el = box.current;
    const sel = 'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';
    if (el && !el.contains(document.activeElement)) {
      const first = el.querySelector<HTMLElement>("input:not([disabled]),textarea:not([disabled]),select:not([disabled])") || el.querySelector<HTMLElement>(sel);
      first?.focus();
    }
    const trap = (e: KeyboardEvent) => {
      if (e.key !== "Tab" || !el) return;
      const items = Array.from(el.querySelectorAll<HTMLElement>(sel)).filter((x) => x.offsetParent !== null);
      if (!items.length) return;
      const a = items[0], z = items[items.length - 1];
      if (e.shiftKey && document.activeElement === a) { e.preventDefault(); z.focus(); }
      else if (!e.shiftKey && document.activeElement === z) { e.preventDefault(); a.focus(); }
      else if (!el.contains(document.activeElement)) { e.preventDefault(); a.focus(); }
    };
    window.addEventListener("keydown", trap);
    const root = document.documentElement;
    root.classList.add("dlg-open");
    return () => { window.removeEventListener("keydown", trap); root.classList.remove("dlg-open"); before?.focus?.(); };
  }, []);
  return (
    <div className="dlg-bg" onMouseDown={(e) => !keep && e.target === e.currentTarget && onClose()}>
      <div ref={box} className={`dlg ${wide ? "wide" : ""} ${xl ? "xl" : ""}`} role="dialog" aria-modal="true" aria-label={title}>
        <div className="dlg-h">
          <h3>{title}</h3>
          <button className="x" aria-label="닫기" onClick={onClose}>×</button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function Tabs({ items, value, onChange }: { items: string[]; value: string; onChange: (v: string) => void }) {
  return (
    <div className="tabs" role="tablist">
      {items.map((t) => (
        <button key={t} role="tab" className={t === value ? "on" : ""} onClick={() => onChange(t)}>{t}</button>
      ))}
    </div>
  );
}

export function Metric({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div className="metric">
      <div className="k">{k}</div>
      <div className="v">{v}</div>
    </div>
  );
}

/** 불러오기 패턴 — 로딩·오류·데이터를 한 번에. */
export function useLoad<T>(loader: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let alive = true;
    setLoading(true);
    loader().then((d) => alive && (setData(d), setError(null))).catch((e) => alive && setError(e.message)).finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);
  return { data, error, loading, reload: () => setTick((t) => t + 1), setData };
}
