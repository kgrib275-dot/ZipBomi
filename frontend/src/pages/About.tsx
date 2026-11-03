// 소개 (/about) — Streamlit 판 app_pages/about.py 이식. 숫자 띠·흐름선 스타일은 Home.css 를 같이 쓴다.
import { useEffect } from "react";
import { Link } from "react-router-dom";
import { get } from "../api";
import { useDialogs } from "../components/Dialogs";
import { useLoad } from "../components/ui";
import { CountUp, MIN_NOTES_FOR_COUNTS } from "./shared";
import "./Home.css";

type About = {
  sources?: Record<string, { name: string; url: string }[]>;
  // 계약의 counts 는 항목이 정해져 있지 않아 홈과 같은 이름(notes·sources) + articles·issues 를 기대하고 없으면 0 으로 둔다.
  counts?: { sources?: number; articles?: number; articles_week?: number; notes?: number; issues?: number };
};

const STEPS: [string, string][] = [
  ["수집", "정부 보도자료·부동산 뉴스 RSS·검색 API를 하루 여러 번 읽습니다."],
  ["거르기", "같은 주소·비슷한 제목을 지우고, 부동산 키워드 규칙에 맞는 기사만 남깁니다."],
  ["채점", "집과 부동산 결정에 얼마나 중요한지 1~5점으로 매기고 한 줄 요약을 붙입니다."],
  ["노트 초안", "높은 점수의 원문을 읽고 요약·핵심 포인트·나에게 미치는 영향·체크할 것으로 정리합니다."],
  ["사람 검토", "편집자가 초안을 확인하고 고친 뒤에만 게시합니다."],
  ["주간 흐름", "한 주의 노트를 한 줄 흐름으로 묶어 뉴스레터·PDF로 보냅니다."],
];

// 기능이 바뀌면 이 목록도 같이 고친다 (2026-11-03 로그인 코드 입력·기기별 로그아웃 / 2026-11-02 내 공간·메일 로그인·상단 알림·지도 바탕 선택 추가 / 지도·청약 공고·데이터 종류·내 프로필, Phase 2 관심 단지·지역 흐름, Phase 3 현행 수치·계산 연결, Phase 4 분양 일정·알림·노트 형식, 홈 시장 요약 반영)
const FEATURES: [string, string, string, string][] = [
  ["/my", "🏠", "내 공간", "관심 단지 최근 거래·비교 표·관심/알림 청약·저장한 노트·계산·메모·할 일과 내 일정 달력을 한 화면에. 내 데이터는 파일로 백업도 돼요. 항목마다 메모·알림 날짜를 달면 맨 위 🔔에 떠요. 메일로 받은 6자리 코드(또는 링크)로 로그인하면 휴대폰·PC 어디서든 그대로, 내 자료를 근거로 질문할 수 있어요. 로그인한 기기 목록에서 기기별로 로그아웃도 돼요"],
  ["/lab", "🧪", "데이터 랩", "2년 거래량과 금리·심리 지표, 내 예산으로 갈 수 있는 동네, 시군구 상승률 순위, 세 동네 가격 비교를 직접 골라 보기"],
  ["/me", "👤", "내 프로필", "유형·관심 지역·예산을 넣으면 홈과 노트가 내 조건에 맞춰집니다. 로그인하면 기기 사이에 이어져요."],
  ["/my-homes", "⭐", "관심 단지", "실거래가에서 ☆로 담은 단지의 평형별 최근가·변동률·전세가율과 월별 추이, 관련 정책 노트를 한 화면에"],
  ["/map", "🗺", "지도", "분양 공고·지역별 시세·등록 매물을 지도 위에서 한 번에. 일반 지도·위성 사진, 지금 위치를 네이버·구글 지도로 열기"],
  ["/deals", "📊", "실거래가", "아파트·연립다세대·단독·오피스텔 매매와 전월세, 분양권·토지·상업용까지 지역·월별로. 시군구 → 동 → 단지로 내려가며 거래량·3.3㎡당 가격 흐름도"],
  ["/deals?tab=apply", "📅", "청약 공고", "청약홈·LH 공고를 접수 일정 순으로, 기준금리·주담대 금리·가격지수와 함께"],
  ["/calc", "🧮", "내 집 계산기", "대출 한도·월 상환액·취득세·청약 가점·전세가율을 바로 계산하고, 모아둔 돈을 넣으면 살 수 있는지 한 줄로. 실거래가·관심 단지에서 '계산 →'으로 그 가격 그대로"],
  ["/now", "📌", "현행 수치", "DSR·기준금리·주담대 금리·취득세율·청약 가점 만점을 기준일·근거 링크와 함께. 최근 바뀐 값에는 '변경됨' 표시"],
  ["/calendar", "🗓", "분양 일정·당첨 가점", "청약 접수·발표 일정을 달력으로, 지역별 가점 당첨선 추이·경쟁률·연령대별 당첨자와 최근 당첨 가점을 내 가점과 비교. 🔔를 누르면 접수 3일 전 메일 알림, 맨 위 🔔에서 다가오는 일정 확인"],
  ["/", "📈", "지금 시장", "첫 화면에서 금리·주택가격전망·대출 잔액, 지난달 전국 거래량과 중위가, 거래 많은 지역, 오늘 읽은 기사를 한눈에"],
  ["/notes", "📝", "노트", "시세·정책·청약 소식을 원문과 함께 정리하고, 내 유형에 미치는 영향을 따로 적습니다"],
];

const MORE: [string, string, string, string][] = [
  ["/today", "🧩", "오늘의 퀴즈", "매일 3문제와 내일 예측 투표"],
  ["/type", "🧭", "부동산 성향 16유형", "12문항으로 내 성향과 잘 맞는 전략 찾기"],
  ["/diagnosis", "☑", "준비도 자가진단", "12문항으로 자금·정보·실행 준비도 점검"],
  ["/ask", "✦", "보미AI", "보던 화면 옆 패널에서 묻기 — 내 관심 단지·공고·프로필을 근거로 답해요. 로그인하면 처음 1번 무료, 더 쓰려면 관리자에게 신청"],
  ["/lab", "🕸", "데이터 랩", "키워드 네트워크·히트맵으로 흐름 탐색"],
];

export default function AboutPage() {
  const { openSubscribe, openContact, openLogin } = useDialogs();
  // 1분 둘러보기가 끝나 넘어온 경우 — 로그인 창을 바로 연다 (layout/TrialGate.tsx)
  const needLogin = typeof window !== "undefined" && new URLSearchParams(window.location.search).get("login") === "1";
  useEffect(() => { if (needLogin) openLogin(); }, [needLogin, openLogin]);
  const { data } = useLoad(() => get<About>("about"));
  const c = data?.counts || {};
  const nSources = c.sources ?? Object.values(data?.sources || {}).reduce((a, v) => a + v.length, 0);
  const nArticles = c.articles ?? c.articles_week ?? 0;
  const nNotes = c.notes ?? 0;
  const nIssues = c.issues ?? 0;

  const FAQ: [string, string][] = [
    ["노트는 AI가 쓰나요?", "네, 초안은 생성형 AI(Google Gemini)가 원문을 읽고 쓰고, 운영자가 검토하고 고친 노트만 게시합니다. 노트마다 아래에 이 사실과 원문 링크를 적어 둡니다."],
    ["보미AI는 무엇인가요?", "생성형 AI(Google Gemini)로 질문에 답하는 기능이에요. 메일로 로그인하면 처음 1번 무료이고, 더 쓰려면 관리자에게 신청하면 무료로 횟수를 늘려 드려요. 답은 틀릴 수 있으니 원문·공고로 확인하세요. '내 공간 자료도 참고'를 켤 때만 관심 단지·공고·메모를 함께 보냅니다."],
    ["돈을 내야 하나요?", "아니요. 집보미는 무료 서비스입니다. 구독·로그인·보미AI 모두 비용이 없어요."],
    ["투자 조언인가요?", "아니요. 공개된 기사·발표를 정리한 참고 자료예요. 세율·대출 규제는 자주 바뀌니 실제 결정 전에는 꼭 최신 공고와 전문가 상담으로 확인하세요."],
    ["얼마나 자주 갱신되나요?", "수집은 하루 여러 번, 노트는 검토되는 대로, 주간 흐름은 매주 한 번 나옵니다."],
    ["어떤 자료를 읽나요?", `국토교통부·한국부동산원 보도자료, 경제지 부동산 섹션, 키워드별 뉴스 검색 등 ${nSources}곳입니다. 홈의 '어디서 찾아 읽나'에서 전체 목록을 볼 수 있어요.`],
    ["실거래가·청약 정보는 어디서 오나요?", "실거래가는 국토교통부 실거래가 신고 자료(공공데이터포털), 청약 공고는 한국부동산원 청약홈과 LH 청약플러스, 금리·KB 가격지수·주택가격전망지수·소비자심리지수·주택관련 대출 잔액은 한국은행 경제통계시스템에서 받습니다. 신고·공시 시점 차이로 최근 1~2개월은 계속 채워집니다."],
    ["내 프로필·관심 단지는 어디에 저장되나요?", "로그인 없이 이 브라우저에 저장됩니다. 뉴스레터를 구독하면 맞춤 메일(내 관심 단지·내 조건 노트)을 위해 구독 이메일에 연결해 보관하고, 구독을 해지하거나 '내 기록 지우기'를 누르면 지워집니다."],
    ["관심 단지는 어떻게 쓰나요?", "실거래가 화면에서 단지 이름 앞의 ☆를 누르면 '관심 단지'에 카드로 모입니다. 최근 3개월 평형별 최고·최저·최근가, 직전 3개월 대비 중위가 변동률, 전세가율을 국토교통부 실거래가 신고 자료로 계산하고 기준일을 함께 적습니다. 목록은 이 브라우저에만 저장되고, 맞춤 브리핑을 구독하면 월요일 메일에 내 관심 단지 변동이 실립니다."],
    ["지역 흐름의 노트 표시는 무엇인가요?", "시군구·동·단지별 월 거래량이 전월보다 30% 넘게 늘거나 줄어든 달에, 그 달 그 지역을 다룬 노트(없으면 전국 정책 노트)를 붙여 둡니다. 함께 읽어 볼 자료라는 뜻이지 원인이라는 뜻은 아닙니다."],
    ["현행 수치는 어떻게 관리하나요?", "기준금리와 주택담보대출 평균 금리는 한국은행 공표 자료에서 자동으로 읽습니다. 대출 규제·세율은 편집부가 금융위원회 발표와 법령 원문을 확인한 값만 기준일·근거 링크와 함께 올립니다. 확인 전인 값은 보여 주지 않습니다. 노트에는 그 노트가 다루는 수치를 붙이고, 내 프로필의 예산·연소득으로 '내 돈으로 치면 얼마'인지 예시를 계산해 보여 줍니다."],
    ["지도의 매물은 무엇인가요?", "편집부가 직접 확인해 등록한 매물만 보여 줍니다. 포털 매물을 가져오지 않습니다."],
    ["구독을 해지하려면?", "뉴스레터 아래의 '구독 해지' 링크를 누르면 바로 해지됩니다."],
  ];

  return (
    <>
      <div className="eyebrow">소개</div>
      <h2 className="sec-h">집보미 <span className="grad">소개</span></h2>
      <p className="sec-p" style={{ maxWidth: 760 }}>
        집보미(ZIPBOMI)는 "집을 봐 주는 비서"입니다. 집에 관한 모든 것을 한곳에서 봅니다. 아파트 실거래가·청약 일정·대출 한도·세금·정책 변화를 매일 모아 숫자와 함께 정리하고, 나에게 필요한 것은 노트로 남겨 둡니다.
      </p>

      <div className="cols3" style={{ marginTop: 18 }}>
        {([
          ["🔭", "찾기", "정부 발표·통계·부동산 뉴스를 매일 훑어 꼭 알아야 할 소식을 고릅니다."],
          ["✏️", "정리하기", "요약에서 끝내지 않고 핵심 포인트와 실수요자·투자자에게 미치는 영향까지 붙입니다."],
          ["🗂", "쌓기", "노트를 시장·시세 · 정책·세금·대출 · 청약·분양·개발로 나눠 찾기 쉽게 쌓습니다."],
        ] as [string, string, string][]).map(([icon, title, desc]) => (
          <div key={title} className="box">
            <h3 style={{ fontSize: "1.15rem", marginBottom: 8 }}>{icon} {title}</h3>
            <p className="sec-p">{desc}</p>
          </div>
        ))}
      </div>

      <h3 className="sub-h">여기서 할 수 있는 것</h3>
      <div className="cols3" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(min(260px,100%),1fr))" }}>
        {FEATURES.map(([to, icon, title, desc]) => (
          <Link key={to} to={to} className="box" style={{ textDecoration: "none", color: "inherit" }}>
            <b style={{ fontSize: "1.08rem" }}>{icon} {title}</b>
            <p className="sec-p" style={{ marginTop: 6 }}>{desc}</p>
          </Link>
        ))}
      </div>

      <h3 className="sub-h">카테고리</h3>
      <div className="table-wrap">
        <table className="table">
          <thead><tr><th>카테고리</th><th>다루는 내용</th></tr></thead>
          <tbody>
            <tr><td>시장·시세</td><td>매매·전월세 시세, 거래량, 지역별 동향, 금리와 시장</td></tr>
            <tr><td>정책·세금·대출</td><td>부동산 정책·규제, 취득·보유·양도세, 대출 규제(LTV·DSR), 임대차 제도</td></tr>
            <tr><td>청약·분양·개발</td><td>청약·분양, 재건축·재개발, 신도시·교통 호재, 공급 일정</td></tr>
          </tbody>
        </table>
      </div>

      {/* ---------- 숫자로 보기 — 게시 노트 10편 미만이면 통째로 숨긴다 ---------- */}
      {nNotes >= MIN_NOTES_FOR_COUNTS && <>
      <div className="space" />
      <div className="eyebrow">숫자로 보기</div>
      <h3 className="sec-h" style={{ fontSize: "1.4rem" }}>숫자로 보는 <span className="grad">집보미</span></h3>
      <div className="hero-stats" style={{ marginTop: 14 }}>
        <div><CountUp to={nSources} /><span>살펴보는 출처</span></div>
        <div><CountUp to={nArticles} /><span>검토한 기사</span></div>
        <div><CountUp to={nNotes} /><span>게시 노트</span></div>
        {nIssues > 0 && <div><CountUp to={nIssues} /><span>주간 흐름</span></div>}
      </div>
      </>}

      {/* ---------- 만드는 과정 ---------- */}
      <div className="space" />
      <div className="eyebrow">이렇게 만듭니다</div>
      <h3 className="sec-h" style={{ fontSize: "1.4rem" }}>원문이 <span className="grad">노트가 되기까지</span></h3>
      <ol className="flowline">
        {STEPS.map(([b, s]) => <li key={b}><b>{b}</b><span>{s}</span></li>)}
      </ol>

      <h3 className="sub-h">편집 원칙</h3>
      <div className="cols2">
        <div className="box"><b>원문을 먼저 봅니다</b><br />모든 노트에 원문 링크를 답니다. 원문에 없는 수치·사실·인용은 쓰지 않고, 추정은 '~로 보입니다'처럼 구분합니다.</div>
        <div className="box"><b>내 상황에 맞춰 씁니다</b><br />무주택자·갈아타기·임차인 등 누구에게 어떤 영향이 있는지, 지금 확인할 것을 함께 적습니다.</div>
      </div>

      <h3 className="sub-h">더 둘러보기</h3>
      <div className="cols3" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(min(220px,100%),1fr))" }}>
        {MORE.map(([to, icon, title, desc], i) => (
          <div key={i} className="box">
            <Link to={to} className="more">{icon} {title}</Link>
            <div className="caption" style={{ marginTop: 6 }}>{desc}</div>
          </div>
        ))}
      </div>

      <h3 className="sub-h">자주 묻는 질문</h3>
      {FAQ.map(([q, a]) => (
        <details key={q} className="expander">
          <summary>{q}</summary>
          <div className="body sec-p">{a}</div>
        </details>
      ))}

      <div className="btn-row" style={{ marginTop: 28 }}>
        <button className="btn primary" onClick={() => openSubscribe("about")}>월요일 아침 맞춤 브리핑 받기 →</button>
        <button className="btn" onClick={() => openContact()}>문의하기</button>
      </div>
    </>
  );
}
