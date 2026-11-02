// 내 프로필 — 로그인 없이 쓰는 개인화 기준값 (유형·관심 지역·예산·소득·부채·청약 항목·전세 만기·테스트 결과).
// 저장: 방문자 상태 'profile'(PUT /api/me/state → 서버가 허용 항목만 남김) + localStorage 사본.
// 확인된 구독자 브라우저라면 서버가 구독 이메일 기준 사본(subscriber_profile)도 맞춘다 (backend/pipeline/profile.py).
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { get } from "./api";
import { useMe } from "./me";

export type TypeKey = "first_home" | "upgrade" | "tenant" | "investor";
export const TYPES: [TypeKey, string, string][] = [
  ["first_home", "무주택(첫 집)", "첫 집을 준비하고 있어요"],
  ["upgrade", "1주택 갈아타기", "지금 집을 팔고 옮길 계획이에요"],
  ["tenant", "임차인(전월세)", "전세·월세로 살고 있어요"],
  ["investor", "투자 관심", "투자 관점으로 시장을 봐요"],
];
export const TYPE_LABEL: Record<string, string> = Object.fromEntries(TYPES.map(([k, l]) => [k, l]));
export const TYPE_SHORT: Record<string, string> = { first_home: "무주택", upgrade: "갈아타기", tenant: "임차인", investor: "투자" };

// 청약 가점 선택지 — 계산기(/calc)와 같은 번호 (주택공급에 관한 규칙 별표 1)
export const HOME_OPTS = ["해당 없음 (유주택·만30세 미만 미혼)", "1년 미만", ...Array.from({ length: 14 }, (_, i) => `${i + 1}년 이상 ~ ${i + 2}년 미만`), "15년 이상"];
export const FAM_OPTS = ["0명", "1명", "2명", "3명", "4명", "5명", "6명 이상"];
export const ACCT_OPTS = ["6개월 미만", "6개월 ~ 1년 미만", ...Array.from({ length: 14 }, (_, i) => `${i + 1}년 이상 ~ ${i + 2}년 미만`), "15년 이상"];

export type TestRec = { code?: string; name?: string; emoji?: string; score?: number; level?: string; weak?: string; at?: string };
export type Profile = {
  type?: TypeKey; regions?: string[];
  budget_min?: number; budget_max?: number; income?: number; debt?: number;
  sub_home?: number; sub_fam?: number; sub_acct?: number; lease_end?: string;
  alert_lease?: boolean; alert_apply?: string[];  // 알림 메일 (Phase 4, backend/pipeline/reminders.py)
  tests?: { type16?: TestRec; diagnosis?: TestRec; career?: TestRec; habit?: TestRec };
  updated_at?: string;
};

const LS = "zipgenie-myprofile";
const isObj = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);

export function readLocal(): Profile | null {
  try { const v = JSON.parse(localStorage.getItem(LS) || "null"); return isObj(v) ? (v as Profile) : null; } catch { return null; }
}
function writeLocal(p: Profile | null) {
  try { if (p) localStorage.setItem(LS, JSON.stringify(p)); else localStorage.removeItem(LS); } catch { /* 사생활 보호 모드 */ }
}
/** '내 기록 지우기' 때 브라우저 사본도 지운다. */
export const clearLocalProfile = () => writeLocal(null);

export const hasCore = (p: Profile | null | undefined) => !!p && (!!p.type || !!p.regions?.length);
const today = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; };

/** 지금 프로필 — 서버 값이 있으면 그것, 없으면 이 브라우저 사본. */
export function profileOf(state: Record<string, unknown>): Profile | null {
  return isObj(state.profile) ? (state.profile as Profile) : readLocal();
}

export function useProfile() {
  const { me, state, setState, flush } = useMe();
  const profile = useMemo(() => profileOf(state), [state]);
  const ref = useRef(profile);
  ref.current = profile;
  const save = useCallback((patch: Partial<Profile>) => {
    const next: Record<string, unknown> = { ...(ref.current || {}), ...patch, updated_at: new Date().toISOString().slice(0, 19) };
    for (const k of Object.keys(next)) if (next[k] === undefined || next[k] === null || next[k] === "") delete next[k];
    ref.current = next as Profile;
    writeLocal(next as Profile);
    setState({ profile: next });
  }, [setState]);
  const clear = useCallback(() => { ref.current = null; writeLocal(null); setState({ profile: null }); }, [setState]);
  /** 테스트 결과를 프로필에 남긴다 — 같은 결과면 다시 쓰지 않는다. */
  const recordTest = useCallback((key: keyof NonNullable<Profile["tests"]>, rec: TestRec) => {
    const cur = ref.current?.tests?.[key];
    if (cur && cur.code === rec.code && cur.name === rec.name && cur.score === rec.score && cur.level === rec.level) return;
    save({ tests: { ...(ref.current?.tests || {}), [key]: { ...rec, at: today() } } });
  }, [save]);
  return { ready: !!me, profile, save, clear, recordTest, flush };
}

/** 서버 값과 브라우저 사본을 맞춘다 (Layout 에서 한 번). 서버에 없고 사본만 있으면 서버로 올리고, 서버 값이 있으면 사본을 덮는다. */
export function useProfileSync() {
  const { me, state, setState } = useMe();
  const done = useRef(false);
  useEffect(() => {
    if (!me || done.current) return;
    done.current = true;
    const local = readLocal();
    if (isObj(state.profile)) writeLocal(state.profile as Profile);
    else if (local && (hasCore(local) || local.tests)) setState({ profile: local });
  }, [me, state.profile, setState]);
}

// ---------------- 시군구 (실거래가와 같은 코드 목록) ----------------

export type RegionOpt = { code: string; label: string; sido: string; name: string };
let regionsP: Promise<RegionOpt[]> | null = null;
export function loadRegions(): Promise<RegionOpt[]> {
  if (!regionsP) {
    regionsP = get<{ groups: { sido: string; items: { code: string; name: string }[] }[] }>("re/regions")
      .then((r) => (r.groups || []).flatMap((g) => g.items.map((it) => ({ code: it.code, sido: g.sido, name: it.name, label: `${g.sido} ${it.name}` }))))
      .catch((e) => { regionsP = null; throw e; });
  }
  return regionsP;
}
export function useRegions() {
  const [list, setList] = useState<RegionOpt[]>([]);
  useEffect(() => { let alive = true; loadRegions().then((l) => alive && setList(l)).catch(() => undefined); return () => { alive = false; }; }, []);
  const byCode = useMemo(() => Object.fromEntries(list.map((r) => [r.code, r])), [list]);
  return { list, byCode };
}
export const regionShort = (byCode: Record<string, RegionOpt>, code: string) => byCode[code]?.name.split(" ").slice(-1)[0] || code;

/** 시군구 고르기 — 이름 일부를 치면 후보가 뜬다 (예: '마포', '분당', '해운대'). */
export function RegionPicker({ value, onChange, max = 3, id, placeholder }: { value: string[]; onChange: (v: string[]) => void; max?: number; id?: string; placeholder?: string }) {
  const { list, byCode } = useRegions();
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [hi, setHi] = useState(0);
  const needle = q.replace(/\s+/g, "");
  const hits = useMemo(() => (needle ? list.filter((r) => r.label.replace(/\s+/g, "").includes(needle) && !value.includes(r.code)).slice(0, 8) : []), [list, needle, value]);
  const full = value.length >= max;
  const add = (code: string) => { if (!value.includes(code) && !full) onChange([...value, code]); setQ(""); setHi(0); };
  return (
    <div className="rp">
      {value.length > 0 && (
        <div className="rp-chips">
          {value.map((c) => (
            <span key={c} className="rp-chip">{byCode[c]?.label || c}
              <button type="button" aria-label={`${byCode[c]?.label || c} 빼기`} onClick={() => onChange(value.filter((x) => x !== c))}>×</button>
            </span>
          ))}
        </div>
      )}
      {!full && (
        <div className="rp-box">
          <input id={id} type="text" value={q} autoComplete="off" placeholder={placeholder || "시군구 이름 (예: 마포, 분당, 해운대)"}
            role="combobox" aria-expanded={open && hits.length > 0} aria-autocomplete="list"
            onChange={(e) => { setQ(e.target.value); setOpen(true); setHi(0); }}
            onFocus={() => setOpen(true)} onBlur={() => window.setTimeout(() => setOpen(false), 150)}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") { e.preventDefault(); setHi((h) => Math.min(hits.length - 1, h + 1)); }
              else if (e.key === "ArrowUp") { e.preventDefault(); setHi((h) => Math.max(0, h - 1)); }
              else if (e.key === "Enter" && hits[hi]) { e.preventDefault(); add(hits[hi].code); }
            }} />
          {open && hits.length > 0 && (
            <ul className="rp-list" role="listbox">
              {hits.map((r, i) => (
                <li key={r.code} role="option" aria-selected={i === hi} className={i === hi ? "on" : ""}
                  onMouseDown={(e) => { e.preventDefault(); add(r.code); }}>{r.label}</li>
              ))}
            </ul>
          )}
          {open && needle && !hits.length && list.length > 0 && <div className="rp-empty caption">맞는 시군구가 없어요. 실거래가 조회가 되는 시군구만 고를 수 있어요.</div>}
        </div>
      )}
      <div className="caption">{value.length}/{max}곳{full ? " · 바꾸려면 ×로 하나를 빼세요" : ""}</div>
    </div>
  );
}

/** 만원 → '12억 3,400만원' */
export function man(v: number | undefined): string {
  if (v === undefined || !isFinite(v)) return "";
  const n = Math.round(v), a = Math.abs(n), eok = Math.floor(a / 10000), rest = a % 10000;
  if (!eok) return `${rest.toLocaleString("ko-KR")}만원`;
  return `${eok}억${rest ? ` ${rest.toLocaleString("ko-KR")}만` : ""}원`;
}
