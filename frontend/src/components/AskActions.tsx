// 보미AI 답변 → 바로 해 볼 일 (2026-11-19) — 답변에 나온 금액은 계산기로, 시군구는 실거래가로 이어 주는 버튼. 규칙으로만 찾는다(AI 호출 없음).
// 일정 담기(AskToCalendar)와 함께 답변 아래에 붙는다. 찾은 게 없으면 아무것도 그리지 않는다.
import { useMemo } from "react";
import { Link } from "react-router-dom";
import { findMoney, findRegions } from "../askActions";
import { useRegions } from "../profile";

const fmt = (m: number) => {
  const eok = Math.floor(m / 10000), rest = m % 10000;
  return eok ? `${eok}억${rest ? ` ${rest.toLocaleString("ko-KR")}만` : ""}원` : `${rest.toLocaleString("ko-KR")}만원`;
};

export default function AskActions({ text, compact = false }: { text: string; compact?: boolean }) {
  const { list } = useRegions();
  const money = useMemo(() => findMoney(text), [text]);
  const regions = useMemo(() => findRegions(text, list), [text, list]);
  if (!money.length && !regions.length) return null;
  return (
    <div className={`ask-act${compact ? " compact" : ""}`} aria-label="답변으로 바로 해 보기">
      {money.map((m) => (
        <span key={m.man} className="aa-grp">
          <Link className="btn sm" to={`/calc?price=${m.man}&tab=loan&label=${encodeURIComponent("보미AI 답변")}`} title="이 금액으로 대출 한도·월 상환액 계산">💰 {fmt(m.man)} 대출 계산</Link>
          <Link className="btn sm ghost" to={`/calc?price=${m.man}&tab=tax&label=${encodeURIComponent("보미AI 답변")}`} title="이 금액으로 취득세 계산">취득세</Link>
        </span>
      ))}
      {regions.map((r) => <Link key={r.code} className="btn sm" to={`/deals?lawd=${r.code}`}>📊 {r.name} 실거래가</Link>)}
    </div>
  );
}
