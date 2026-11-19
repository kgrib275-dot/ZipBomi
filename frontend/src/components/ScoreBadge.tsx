// 내 가점 vs 지난 당첨선 (2026-11-19) — 청약 공고 옆에 '이 지역 지난 1년 당첨 최저 가점'과 내 가점을 나란히. 참고 숫자일 뿐 당첨 가능 여부 판정이 아니다.
// 자료: GET /api/re/score-summary (저장된 청약홈 당첨 가점). 건수 3 미만·자료 없음이면 아무것도 그리지 않는다. 계산은 브라우저에서만.
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { get } from "../api";
import { useProfile } from "../profile";
import { subScore } from "../pages/Calendar";

type Sum = { regions: Record<string, { n: number; median: number; min: number; max: number }> };
let cache: Promise<Sum | null> | null = null;
const load = () => (cache ||= get<Sum>("re/score-summary").catch(() => { cache = null; return null; }));

export default function ScoreBadge({ region }: { region: string }) {
  const [sum, setSum] = useState<Sum | null>(null);
  const { profile } = useProfile();
  useEffect(() => { let alive = true; load().then((s) => alive && setSum(s)); return () => { alive = false; }; }, []);
  const key = sum && Object.keys(sum.regions).find((k) => k === region || (region && (k.startsWith(region) || region.startsWith(k))));
  const r = key ? sum!.regions[key] : null;
  if (!r) return null;
  const mine = subScore(profile);
  const diff = mine === null ? null : Math.round((mine - r.median) * 10) / 10;
  return (
    <div className="score-badge" title="지난 1년 이 지역 공고들의 당첨 최저 가점을 모은 값이에요. 단지·주택형마다 크게 다르니 참고만 하세요.">
      📈 지난 1년 {region} 당첨 최저 가점 중앙값 <b>{r.median}점</b> <span className="caption">({r.min}~{r.max}점 · {r.n}건)</span>
      {diff === null ? <> · <Link to="/calc?tab=sub">내 가점 넣어 보기</Link></> : <> · 내 <b>{mine}점</b> ({diff >= 0 ? `+${diff}` : diff}점)</>}
    </div>
  );
}
