// 뉴스레터 발송 일정 — 관리 > 배치 스케줄의 실제 설정(/api/site 의 newsletter)을 화면 문구에 쓴다 (2026-11-03).
// 예전엔 화면마다 '월요일 아침 7시'를 적어 두었는데, 실제 설정은 09:00 이고 발송이 꺼져 있었다.
import { useEffect, useState } from "react";
import { get } from "./api";

export type Newsletter = { enabled: boolean; when: string };
let cache: Promise<Newsletter> | null = null;
const FALLBACK: Newsletter = { enabled: false, when: "" };

export function useNewsletter(): Newsletter {
  const [nl, setNl] = useState<Newsletter>(FALLBACK);
  useEffect(() => {
    cache = cache || get<{ newsletter?: Newsletter }>("site").then((r) => r.newsletter || FALLBACK).catch(() => FALLBACK);
    let alive = true;
    cache.then((v) => { if (alive) setNl(v); });
    return () => { alive = false; };
  }, []);
  return nl;
}

/** '매주 월요일 오전 9시' 또는 발송 전이면 '발송을 시작하면 첫 호부터' */
export function scheduleText(nl: Newsletter): string {
  return nl.enabled && nl.when ? `매주 ${nl.when}` : "발송을 시작하면 첫 호부터";
}
