// 내 가점 카드 공유 (2026-11-20) — 점수와 (고르면) 지역이 링크에 담겨, 받는 사람 미리보기에 '내 청약 가점 52점 · 서울 당첨 중앙값 61점' 카드가 뜬다.
// 서버는 GET /s/p?score=&r= 에서 점수(0~84)·지역(시도 목록)만 받아 그린다. 이름·계정 정보는 링크에 들어가지 않는다.
import { useState } from "react";
import { SIDOS, SIDO_OF } from "../pages/Calendar";
import { useProfile } from "../profile";
import ShareBar from "./ShareBar";

export default function ScoreShare({ score }: { score: number }) {
  const { profile } = useProfile();
  const mine = (profile?.regions || []).map((c) => SIDO_OF[String(c).slice(0, 2)]).find(Boolean) || "";
  const [region, setRegion] = useState(mine);
  if (!(score >= 0 && score <= 84)) return null;
  return (
    <div className="score-share">
      <span className="caption">내 가점 카드 공유 — 점수가 링크에 담겨요(이름·계정 정보는 안 담겨요).</span>
      <label className="caption">비교할 지역 <select value={region} onChange={(e) => setRegion(e.target.value)} aria-label="비교할 지역">
        <option value="">지역 없이</option>{SIDOS.map((s) => <option key={s} value={s}>{s}</option>)}</select></label>
      <ShareBar content="score" url={`/s/p?score=${Math.round(score)}${region ? `&r=${encodeURIComponent(region)}` : ""}`} title={`내 청약 가점 ${Math.round(score)}점`} />
    </div>
  );
}
