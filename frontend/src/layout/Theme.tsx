// 라이트/다크 전환 — 다크(기본) → 라이트 → 시스템(OS 따름) 순으로 돈다. 고른 값은 localStorage "ax_theme" 에 두고
// <html data-theme> 로 건다. 처음 오는 사람(저장값 없음)은 다크 (2026-11-05 기본 다크). 첫 그림 전 적용은 index.html 의 작은 inline 스크립트가 한다 (깜빡임 방지).
import { useEffect, useState } from "react";

type Pref = "system" | "light" | "dark";
const KEY = "ax_theme";
const NEXT: Record<Pref, Pref> = { dark: "light", light: "system", system: "dark" };
const ICON: Record<Pref, string> = { system: "◐", light: "☀︎", dark: "☾" };
const LABEL: Record<Pref, string> = { system: "시스템 설정", light: "라이트", dark: "다크" };

function readPref(): Pref {
  try {
    const v = localStorage.getItem(KEY);
    return v === "light" || v === "system" ? v : "dark";
  } catch {
    return "dark";
  }
}

function applyPref(p: Pref) {
  const root = document.documentElement;
  if (p === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", p);
  try {
    localStorage.setItem(KEY, p);  // 시스템도 '고른 값'으로 저장한다 — 비어 있으면 기본(다크)
  } catch {
    /* 저장이 막혀 있어도 이번 화면에는 적용된다 */
  }
  // 모바일 주소창 색 — 지금 실제로 보이는 배경색에 맞춘다
  const bg = getComputedStyle(root).getPropertyValue("--bg").trim();
  // 두 개(다크용·라이트용)를 모두 맞춘다 — 기기가 라이트인데 화면이 다크일 때 주소창만 밝게 보이지 않게
  if (bg) document.querySelectorAll('meta[name="theme-color"]').forEach((m) => m.setAttribute("content", bg));
}

export function ThemeToggle() {
  const [pref, setPref] = useState<Pref>(readPref);
  useEffect(() => applyPref(pref), [pref]);
  const next = NEXT[pref];
  return (
    <button type="button" className="theme-btn" onClick={() => setPref(next)}
      title={`화면 테마: ${LABEL[pref]} (눌러서 ${LABEL[next]})`} aria-label={`화면 테마: ${LABEL[pref]}. 눌러서 ${LABEL[next]}로 바꾸기`}>
      <span aria-hidden="true">{ICON[pref]}</span>
    </button>
  );
}
