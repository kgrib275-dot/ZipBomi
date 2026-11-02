// 방문자 상태 — GET /api/me 한 번으로 받아 모든 화면이 공유한다 (관리자 여부, 구독 여부, 월 구독, 기억한 값).
// 기억할 값(필터·진행 중인 테스트 등)은 setState 로 바꾸면 PUT /api/me/state 로 저장되어 다음 방문에도 그대로다.
// 충돌 방지 (2026-11-02): ① 같은 브라우저의 다른 탭에 바뀐 값을 바로 알린다(BroadcastChannel) — 오래된 탭이 관심 목록 같은
// 목록 값을 통째로 저장해 다른 탭의 추가분을 지우지 않게. ② 탭으로 돌아오면 서버 값을 다시 받는다(저장 대기 중인 값은 유지).
// ③ 저장 대기(0.4초) 중에 페이지를 닫거나 떠나도 keepalive 요청으로 마저 보낸다.
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { get, put } from "./api";

export type Member = { id: number; expires: string; quota: number; used: number } | null;
export type Me = {
  visitor: string;
  is_admin: boolean;
  member: Member;
  state: Record<string, unknown>; // visitor_state 스냅샷 (서버가 허용한 키만)
  privacy_active: boolean;
  subscribed?: boolean;
  ask_enabled: boolean;
  kakao_key: string;
  site_url: string;
  account?: { email: string; since: string } | null;
  map_keys?: { naver: string; kakao: string; google: string }; // 메일 링크 로그인 (2026-11-02)
};

type Ctx = {
  me: Me | null;
  reload: () => Promise<void>;
  state: Record<string, unknown>;
  setState: (patch: Record<string, unknown>) => void;
  flush: () => Promise<void>; // 모아 둔 저장을 바로 보낸다 (저장 직후 서버 계산 결과가 필요할 때 — 홈 '나에게 영향 있는 것')
};

const MeCtx = createContext<Ctx>({ me: null, reload: async () => undefined, state: {}, setState: () => undefined, flush: async () => undefined });

export function MeProvider({ children }: { children: React.ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [state, setLocal] = useState<Record<string, unknown>>({});
  const timer = useRef<number | undefined>(undefined);
  const pending = useRef<Record<string, unknown>>({});
  const inflight = useRef<Promise<unknown>>(Promise.resolve());
  const chan = useRef<BroadcastChannel | null>(null);

  const reload = useCallback(async () => {
    try {
      const m = await get<Me>("me");
      setMe(m);
      setLocal({ ...(m.state || {}), ...pending.current }); // 아직 보내지 않은 내 변경은 서버 값으로 덮지 않는다
    } catch {
      setMe((prev) => prev ?? ({ visitor: "", is_admin: false, member: null, state: {}, privacy_active: true, ask_enabled: false, kakao_key: "", site_url: "" } as Me));
    }
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  // 다른 탭이 저장한 값 받기 + 탭으로 돌아오면 다시 받기 + 떠날 때 남은 저장 보내기
  useEffect(() => {
    try {
      chan.current = new BroadcastChannel("zipgenie-state");
      chan.current.onmessage = (e: MessageEvent) => {
        const patch = e.data as Record<string, unknown>;
        if (patch && typeof patch === "object") setLocal((s) => ({ ...s, ...patch, ...pending.current }));
      };
    } catch { /* 지원하지 않는 브라우저 — 탭 복귀 때 다시 받기로 충분 */ }
    let last = Date.now();
    const onVisible = () => {
      if (document.visibilityState === "visible" && Date.now() - last > 15_000) reload();
      if (document.visibilityState === "hidden") { last = Date.now(); sendNow(); }
    };
    const sendNow = () => {
      if (!Object.keys(pending.current).length) return;
      const body = pending.current;
      pending.current = {};
      window.clearTimeout(timer.current);
      try {
        fetch("/api/me/state", { method: "PUT", keepalive: true, credentials: "same-origin",
          headers: { "Content-Type": "application/json", "X-Requested-With": "zipgenie" }, body: JSON.stringify(body) });
        chan.current?.postMessage(body);
      } catch { /* 무시 */ }
    };
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("pagehide", sendNow);
    return () => {
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("pagehide", sendNow);
      chan.current?.close();
    };
  }, [reload]);

  const setState = useCallback((patch: Record<string, unknown>) => {
    setLocal((s) => ({ ...s, ...patch }));
    pending.current = { ...pending.current, ...patch };
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => {
      const body = pending.current;
      pending.current = {};
      inflight.current = put("me/state", body).then(() => chan.current?.postMessage(body)).catch(() => undefined);
    }, 400); // 연타해도 한 번에 저장
  }, []);

  const flush = useCallback(async () => {
    window.clearTimeout(timer.current);
    if (Object.keys(pending.current).length) {
      const body = pending.current;
      pending.current = {};
      inflight.current = put("me/state", body).then(() => chan.current?.postMessage(body)).catch(() => undefined);
    }
    await inflight.current;
  }, []);

  const value = useMemo(() => ({ me, reload, state, setState, flush }), [me, reload, state, setState, flush]);
  return <MeCtx.Provider value={value}>{children}</MeCtx.Provider>;
}

export const useMe = () => useContext(MeCtx);
