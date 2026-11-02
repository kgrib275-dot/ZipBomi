# ZipGenie 고도화 — Phase별 계획 (2026-11-02, 지시서 기준)

## 현재 구조 (파악 결과)
- 라우트: `/` `/notes` `/deals` `/calc` `/map`(작업 중) `/today` `/ask` `/lab` `/about` `/type` `/career` `/habit` `/diagnosis` `/terms` `/letter` `/privacy` `/admin/*`
- DB(SQLite `backend/data/zipgenie.db`): `articles`(383건, 채점 4점↑ 72건) · `notes`(id,title,source,url,category,kind,audiences,tags,summary,body,published,status,article_hash,created_at,embedding) · `issues`(주간 흐름) · `subscribers`(+visitor 연결·질문 횟수) · `visitor_state`(방문자별 JSON) · `engagements`(이벤트) · `newsletters`
- 노트 파이프라인: `pipeline/jobs.py` draft()/weekly() → `pipeline/llm.py` 프롬프트 → 관리 > 노트 검토(draft → published)
- 메일: `pipeline/mailer.py` prepare()/render()(수신자별 개인 블록) · 발송 jobs.newsletter()
- 개인 상태: 방문자 쿠키(zgv) + `visitor_state` 서버 저장 + localStorage. 구독자는 `subscribers.visitor`로 브라우저와 연결됨

## Phase 0 — 돌아가는 상태로 보이게 (최우선)
- 0-1 실거래가: 매매·전월세 RTMS 연결(진행 중인 수집기 작업), 시군구×월 캐시, 키 없을 때 안내는 관리자에게만·일반 사용자는 "데이터 갱신 중"
- 0-2 노트 30편 초안(4점↑ 기사, 카테고리별 8편↑ 목표) + 주간 흐름 3주치 → 검토 큐. 콘텐츠 10편 미만이면 숫자 카드 숨김
- 0-3 데이터 랩 운영 지표 → 관리자 화면, 급상승 키워드 = 지난주 대비 증감률 + 대표 노트 링크, 띠 중복 렌더링 수정(무한 스크롤용 복제 → 한 벌만 보이게)
## Phase 1 — 프로필 개인화: `/me` 프로필(유형·관심 지역 3·예산·소득·부채·청약 항목·전세 만기), localStorage + 구독자 서버 저장, 테스트 결과 자동 기록, 2단계 온보딩, "나에게 영향 있는 3가지", 노트 유형별 영향 섹션, "내 조건 노트만" 토글, notes.regions[]/audience[] 필드
## Phase 2 — 관심 단지: `/my-homes` 대시보드, 단지 상세 추이 + 정책 노트 마커, 시군구→동→단지 드릴다운, 거래량 ±30% 구간 노트 마커, 뉴스레터 개인화 템플릿, 구독 CTA 문구
## Phase 3 — 연결: "이 가격으로 계산하기", 가능 여부 한 줄 판정, notes.policy_params + 정책 영향 숫자화, `/now` 현행 수치(기준일·근거 링크·변경됨 배지)
## Phase 4 — 소형 기능: 당첨 가점 비교(청약홈 데이터 수집 가능 여부 먼저 확인), `/calendar` 분양 일정 + D-3 메일, 전세 만기 D-90/D-30 메일, 노트 형식 brief/deep/data
## Phase 5 — 톤·신뢰도: 소개 문구 편집부 중심, editor_note 표시, 질문하기 = 검색 결과 + 근거 기반 정리 답변, 안내 박스 첫 방문만 펼침, 데이터 랩 "더 보기"로
## Phase 6 — 랜딩·모객: 히어로 = "내 연소득으로 살 수 있는 집 가격은?" 즉시 계산 + 구독, 16유형 공유 이미지 점검·CTA "관심 단지 등록", 퍼널 이벤트 자체 DB 로깅

## 원칙
- 기존 기능(노트·계산기·테스트·퀴즈·뉴스레터) 유지, Phase마다 전체 페이지 렌더링 점검
- 숫자·규제 수치는 출처와 기준일 표시
- "AI" 표현은 법적 고지 자리에만. 다만 자동 도구로 쓴 초안을 사람이 검토한다는 사실은 소개·처리방침 고지에 남긴다(아래 참고)
- 편집자 이름은 실제 이름을 관리 화면에서 입력할 때만 표시(지어낸 이름 금지)
