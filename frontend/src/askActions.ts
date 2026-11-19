// 보미AI 답변 → 바로 해 볼 일 (2026-11-19) — 답변 글에서 금액·지역을, 보던 화면과 내 프로필에서 다음 질문을 규칙으로 찾는다 (AI 호출 없음).
// 금액은 '만원' 단위 정수로 돌려준다(계산기 주소의 price 와 같은 단위).
export type Money = { man: number; raw: string };
export type RegionLite = { code: string; name: string };

const NUM = "(\\d{1,3}(?:,\\d{3})+|\\d+(?:\\.\\d+)?)";
// '5억 2천만원' '12억' '5억2,000만원' '8,500만원' — 퍼센트·㎡·평·층 같은 다른 숫자는 '억'·'만원' 이 붙은 것만 잡아서 걸러진다
const EOK = new RegExp(`${NUM}\\s*억(?:\\s*(?:${NUM}\\s*천|${NUM})\\s*만)?\\s*원?`, "g");
const MAN = new RegExp(`${NUM}\\s*만\\s*원`, "g");
const toNum = (s: string) => Number(s.replace(/,/g, ""));

export function findMoney(text: string, max = 3): Money[] {
  const out: Money[] = [];
  const seen = new Set<number>();
  const add = (v: number, raw: string) => {
    const m = Math.round(v);
    if (isFinite(m) && m >= 1000 && m <= 9_999_999 && !seen.has(m) && out.length < max) { seen.add(m); out.push({ man: m, raw: raw.trim() }); }
  };
  const t = String(text || "");
  for (const x of t.matchAll(EOK)) {
    const eok = toNum(x[1]);
    const rest = x[2] ? toNum(x[2]) * 1000 : x[3] ? toNum(x[3]) : 0;
    // 한 줄에 '억' 만 있고 뒤에 '원 …' 없이 '배·% ' 같은 말이 오는 경우(예: 5억 배)는 드물어 그대로 둔다
    add(eok * 10000 + rest, x[0]);
  }
  const rest = t.replace(EOK, " ");
  for (const x of rest.matchAll(MAN)) add(toNum(x[1]), x[0]);
  return out;
}

/** 답변에 나온 시군구 — 전체 이름('성남시 분당구')이나 끝 이름('분당구')이 3글자 이상이고 한 곳뿐일 때만(중구·서구처럼 여러 시도에 있는 이름은 건너뜀) */
export function findRegions(text: string, list: RegionLite[], max = 2): RegionLite[] {
  const last = (n: string) => n.split(" ").slice(-1)[0];
  const full = new Map<string, number>(), tail = new Map<string, number>();
  for (const r of list) { full.set(r.name, (full.get(r.name) || 0) + 1); tail.set(last(r.name), (tail.get(last(r.name)) || 0) + 1); }
  const hits: { r: RegionLite; at: number }[] = [];
  for (const r of list) {
    const cands = [r.name, last(r.name)].filter((n, i) => n.length >= 3 && (i === 0 ? full.get(n) === 1 : tail.get(n) === 1));
    const ats = cands.map((n) => text.indexOf(n)).filter((a) => a >= 0);
    if (ats.length) hits.push({ r, at: Math.min(...ats) });
  }
  return hits.sort((a, b) => a.at - b.at).slice(0, max).map((h) => h.r);
}

const BASE = ["내 관심 단지 최근 거래 흐름 요약해 줘", "이번 주 꼭 알아야 할 부동산 소식 3가지", "내 가점으로 해볼 만한 청약은?", "스트레스 DSR이 내 대출 한도에 주는 영향은?"];
const BY_PATH: [RegExp, string[]][] = [
  [/^\/(deals|map|lab)/, ["이 지역 최근 실거래 흐름을 요약해 줘", "이 지역에서 곧 접수하는 청약 공고가 있어?", "이 지역 전세가율은 어느 정도야?"]],
  [/^\/calendar/, ["내 가점으로 해볼 만한 청약은?", "이번 달 접수 마감이 가까운 공고만 정리해 줘", "청약 당첨 가점은 지역마다 어떻게 달라?"]],
  [/^\/calc/, ["스트레스 DSR이 내 대출 한도에 주는 영향은?", "취득세 중과 조건을 쉽게 설명해 줘", "전세 끼고 사는 갭투자의 위험은?"]],
  [/^\/my-homes/, ["내 관심 단지 최근 거래 흐름 요약해 줘", "관심 단지 전세가율이 높으면 뭐가 위험해?", "관심 단지 지역의 최근 정책 노트를 알려 줘"]],
  [/^\/now/, ["이번 달 바뀐 대출 규제를 요약해 줘", "지금 기준금리가 대출 이자에 주는 영향은?"]],
  [/^\/my(\/|$|\?)/, ["내 일정 중에 챙길 것을 정리해 줘", "내 관심 단지 최근 거래 흐름 요약해 줘"]],
];
const BY_TYPE: Record<string, string> = {
  tenant: "전세 계약 만기 전에 챙길 것을 알려 줘",
  first_home: "생애최초 구입자가 받을 수 있는 혜택을 정리해 줘",
  buyer: "집을 사기 전에 꼭 확인할 것을 순서대로 알려 줘",
  investor: "다주택자가 지금 알아야 할 세금 규칙은?",
};

/** 지금 화면·내 프로필에 맞는 질문 추천 4개 (중복 없이) */
export function suggestFor(pathname: string, profile?: { type?: string; regions?: string[] } | null, regionName?: (code: string) => string, max = 4): string[] {
  const out: string[] = [];
  const push = (s?: string) => { if (s && !out.includes(s) && out.length < max) out.push(s); };
  for (const [re, list] of BY_PATH) if (re.test(pathname)) list.forEach(push);
  const rn = profile?.regions?.[0] && regionName ? regionName(profile.regions[0]) : "";
  if (rn) push(`${rn} 최근 시세 흐름은 어때?`);
  push(profile?.type ? BY_TYPE[profile.type] : undefined);
  BASE.forEach(push);
  return out;
}
