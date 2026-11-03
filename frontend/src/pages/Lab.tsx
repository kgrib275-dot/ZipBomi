// 데이터 랩 (/lab) — 위: 시장 숫자 놀이터(LabMarket, 2026-11-02), 아래: — 백엔드가 만든 인터랙티브 대시보드 HTML 문서(/api/lab/html)를 iframe srcdoc 으로 띄운다.
// 높이는 문서가 postMessage 로 알려 주면 그 값, 아니면 1400px (DocFrame).
import { useEffect, useRef, useState } from "react";
import { get } from "../api";
import { SubscribeCTA } from "../components/Dialogs";
import DocFrame from "../components/DocFrame";
import { Alert, Guide, useLoad } from "../components/ui";
import LabMarket from "./LabMarket";
import "./LabMarket.css";

export default function Lab() {
  // 아래쪽 뉴스 흐름 문서(약 1MB)는 화면에 가까워질 때 불러온다 (2026-11-03) — 위쪽 시장 숫자가 먼저 빨리 뜨게
  const anchor = useRef<HTMLDivElement>(null);
  const [near, setNear] = useState(false);
  useEffect(() => {
    const el = anchor.current;
    if (!el || near) return;
    if (!("IntersectionObserver" in window)) { setNear(true); return; }
    const io = new IntersectionObserver((es) => { if (es.some((e) => e.isIntersecting)) setNear(true); }, { rootMargin: "800px 0px" });
    io.observe(el);
    return () => io.disconnect();
  }, [near]);
  const { data, error, loading } = useLoad<string | null>(() => (near ? get<string>("lab/html").then((h) => (typeof h === "string" ? h : String(h ?? ""))) : Promise.resolve(null)), [near]);
  return (
    <div className="lab-page">
      <div className="eyebrow">데이터 랩</div>
      <h2 className="sec-h">숫자로 직접 <span className="grad">만져 보는 부동산</span></h2>
      <p className="muted" style={{ margin: "0 0 14px" }}>실거래 수십만 건과 금리·심리 지표를 직접 골라 보고, 내 예산으로 갈 수 있는 동네와 지역 순위를 확인하세요. 막대·선 위에 올리거나 눌러 보면 달별 값이 나와요.</p>
      <LabMarket />
      <div className="space" />
      <div className="eyebrow" ref={anchor}>뉴스 흐름</div>
      <h2 className="sec-h">부동산 뉴스 흐름을 <span className="grad">직접 탐색</span>하세요</h2>
      <p className="muted" style={{ margin: "0 0 6px" }}>집보미가 매일 읽는 기사에서 어떤 주제가 함께 움직이는지 보여 줍니다. 기간·소스 그룹·키워드를 고르면 모든 차트가 함께 좁혀지고, ▶ 버튼으로 날짜별로 자라는 모습을 재생할 수 있습니다.</p>
      <Guide title="여기서 볼 것" items={[
        ["급상승 키워드", "오른쪽 패널 맨 위 — 최근 갑자기 많이 잡힌 주제입니다."],
        ["키워드 네트워크", "원을 누르면 함께 나온 키워드와 대표 기사, 스트림·히트맵이 그 키워드로 좁혀집니다."],
        ["▶ 타임랩스", "필터 줄의 재생 버튼으로 날짜별로 주제가 자라는 모습을 봅니다."],
        ["지식 지도", "맨 아래 — 비슷한 글끼리 모인 무리를 확대해 보고 점을 눌러 원문을 엽니다."],
      ]} />
      {(loading || !near) && !data && <div className="page-loading">데이터 랩을 그리는 중...</div>}
      {error && <Alert kind="err">{error}</Alert>}
      {data && <DocFrame html={data} title="부동산 데이터 랩 인터랙티브 대시보드" fallback={1400} />}
      <div className="space" />
      <SubscribeCTA source="lab" headline="이 데이터가 매주 노트가 됩니다" sub="급상승 키워드를 편집자가 읽고 정리한 노트를 매주 메일로 받아 보세요." />
    </div>
  );
}
