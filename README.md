# 집보미 (ZIPBOMI) — 집을 봐 주는 비서

> 2026-11-02 이름을 ZipGenie(집지니)에서 **집보미(ZIPBOMI)**로 바꿨습니다. 프로젝트 폴더 `ZipBomi`, 실행 파일 `start-zipbomi.bat`, DB `backend/data/zipbomi.db`, 공개 주소 `zipbomi.tail6bd481.ts.net`.
> 이미 쓰는 사람의 로그인·저장값이 끊기지 않도록 내부 식별자(환경 변수 `ZIPGENIE_*`, 쿠키 `zgv`, 요청 헤더 `X-Requested-With: zipgenie`, 브라우저 저장 키 `zipgenie-*`)는 옛 이름 그대로 둡니다.

부동산 뉴스·정책·실거래가·청약·금리 자료를 모아 **노트(해설)**, **실거래가 조회**, **분양 일정·알림**, **대출·세금·청약 계산기**,
**현행 수치**, **질문하기**로 보여 주는 웹 서비스입니다. 백엔드는 FastAPI + SQLite, 화면은 React(Vite)이며 한 프로세스가 API 와 화면을 함께 내보냅니다.

- 저장소: https://github.com/kgrib275-dot/ZipBomi
- 설계 기준 `docs/ZIPBOMI_SPEC.md` · 단계별 계획 `docs/ROADMAP_PHASES.md` · API 메모 `docs/API.md`, `docs/API-notes-backend-public.md`
- 최종 갱신 2026-11-02

---

## 목차
1. [빠른 시작 (Windows)](#1-빠른-시작-windows)
2. [빠른 시작 (macOS · Linux)](#2-빠른-시작-macos--linux)
3. [환경 변수 `.env`](#3-환경-변수-env)
4. [외부 API 키 발급](#4-외부-api-키-발급)
5. [처음 실행 후 할 일](#5-처음-실행-후-할-일)
6. [기술 스택](#6-기술-스택)
7. [폴더 구조](#7-폴더-구조)
8. [아키텍처](#8-아키텍처)
9. [화면과 메뉴](#9-화면과-메뉴)
10. [데이터 수집](#10-데이터-수집)
11. [벡터화 · 의미 검색](#11-벡터화--의미-검색)
12. [Databricks 적재](#12-databricks-적재)
13. [배치 스케줄](#13-배치-스케줄)
14. [DB 테이블](#14-db-테이블)
15. [보안 · 개인정보](#15-보안--개인정보)
16. [운영 (백업 · 처리량 · 공개)](#16-운영-백업--처리량--공개)
17. [테스트 결과](#17-테스트-결과)
18. [자주 겪는 문제](#18-자주-겪는-문제)
19. [실서비스 전에 남은 것](#19-실서비스-전에-남은-것)

---

## 1. 빠른 시작 (Windows)

### 필요한 것
| 도구 | 버전 (검증) | 확인 |
|---|---|---|
| Git | 2.40 이상 (2.56) | `git --version` |
| Python | **3.12** (3.12.7) | `py -3.12 --version` |
| Node.js | **20 LTS** 이상 (20.11.0, npm 10.2.4) | `node -v` |
| Microsoft Edge 또는 Playwright Chromium | 선택 — 공유 이미지(OG 카드)·PDF 리포트 생성용 | |

### 설치
```bat
git clone https://github.com/kgrib275-dot/ZipBomi.git
cd ZipBomi

rem 1) 백엔드 가상환경 + 패키지
cd backend
py -3.12 -m venv venv
venv\Scripts\python -m pip install --upgrade pip
venv\Scripts\pip install -r requirements.txt
rem (선택) Edge 가 없으면 Chromium 을 받아 둔다 — OG 카드·PDF 리포트용
venv\Scripts\python -m playwright install chromium

rem 2) 환경 변수 — 예시를 복사한 뒤 값 채우기 (3장 참고). 비워 둔 키는 그 기능만 꺼진다
copy .env.example .env
notepad .env
cd ..

rem 3) 화면 빌드
cd frontend
npm ci
npm run build
cd ..
```

### 실행
```bat
start-zipbomi.bat
```
- http://localhost:5030 — 사이트, http://localhost:5030/admin — 관리 화면 (이 PC 에서 열면 관리자로 인식)
- 배치 스케줄러가 켜진 채로 뜨고, 서버가 멈추면 5초 뒤 저절로 다시 시작합니다. 창을 닫으면 종료.
- `frontend/dist` 가 없으면 처음 한 번 화면을 빌드합니다.
- DB(`backend/data/zipbomi.db`)와 설정 파일은 첫 실행 때 자동으로 만들어집니다.

### 개발 모드
```bat
start-dev.bat
```
백엔드 http://localhost:5030 (코드 바뀌면 자동 재시작, 스케줄러 꺼짐) + 화면 개발 서버 http://localhost:5183 (`/api` 는 5030 으로 프록시).

화면만 고쳤다면 `cd frontend && npm run build` — 실행 중인 서버가 새 `dist` 를 바로 내보냅니다(재시작 불필요).

---

## 2. 빠른 시작 (macOS · Linux)
```bash
git clone https://github.com/kgrib275-dot/ZipBomi.git && cd ZipBomi

cd backend
python3.12 -m venv venv
venv/bin/pip install --upgrade pip
venv/bin/pip install -r requirements.txt
venv/bin/python -m playwright install --with-deps chromium   # 선택
cp .env.example .env && ${EDITOR:-nano} .env
cd ../frontend && npm ci && npm run build && cd ../backend

# 실행 (배치 스케줄러 켜기)
ZIPGENIE_PORT=5030 ZIPGENIE_SCHEDULER=1 venv/bin/python serve.py
# 개발: venv/bin/python serve.py --reload   +   (frontend) npm run dev
```
`start-*.bat` 은 Windows 전용이므로 위 명령을 그대로 쓰거나 systemd·supervisor 로 감쌉니다.

---

## 3. 환경 변수 `.env`
`backend/.env` (`.gitignore` 대상 — 절대 커밋하지 않습니다). 예시는 `backend/.env.example`. **비어 있는 키는 그 기능만 꺼지고 나머지는 동작합니다.**

| 변수 | 필수 | 쓰는 곳 |
|---|---|---|
| `DATA_GO_KR_KEY` | 권장 | 공공데이터포털 — 국토부 실거래가 API, 청약홈 분양정보·경쟁률·당첨가점. **일반 인증키(Decoding)** 를 넣는다(Encoding 키도 자동 처리) |
| `ECOS_API_KEY` | 권장 | 한국은행 ECOS — 기준금리·주담대 금리·KB 지수·지가·심리지수·가계대출. 비우면 공개 sample 키(요청당 10건) |
| `GEMINI_API_KEYS` | 선택 | Gemini — 기사 관련도 채점·노트 초안·주간 흐름·질문하기·임베딩. 콤마로 여러 개 넣으면 돌아가며 사용 |
| `ANTHROPIC_API_KEY` | 선택 | Claude — 관리 > AI 모델 설정에서 Claude 를 고를 때 (화면에서 넣으면 `data/llm_keys.json`) |
| `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET` | 선택 | 네이버 뉴스 검색 출처 |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `SMTP_FROM`, `SMTP_TLS` | 선택 | 구독 확인·뉴스레터·청약 D-3·전세 만기 알림 메일. `SMTP_TLS` = `starttls`/`ssl`/`none` |
| `ALERT_EMAIL` | 선택 | 수집·발송 실패 경보를 받을 관리자 메일 |
| `SITE_URL` | 필수(메일 쓸 때) | 메일 속 링크·공유 주소의 기준. 외부에서 열리는 주소여야 메일 링크가 동작 |
| `ADMIN_TOKEN` | 선택 | 이 PC 밖에서 관리 화면을 쓸 때 (`X-Admin-Token` 헤더). 비우면 로컬 접속만 관리자 |
| `DATABRICKS_SERVER_HOSTNAME`, `DATABRICKS_HTTP_PATH`, `DATABRICKS_TOKEN` | 선택 | Databricks 적재 |
| `DATABRICKS_CATALOG`, `DATABRICKS_SCHEMA` | 선택 | 적재 위치 (기본 `workspace.zipgenie`) |
| `KAKAO_JS_KEY` | 선택 | 카카오 공유 |
| `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET` | 선택 | Reddit 출처 |

서버 실행 옵션 (보통 `start-zipbomi.bat` 이 정함):

| 변수 | 기본 | 뜻 |
|---|---|---|
| `ZIPGENIE_PORT` | 5030 | 포트 |
| `ZIPGENIE_HOST` | 127.0.0.1 | 바인드 주소 (외부 직접 공개 시 0.0.0.0 — 보통은 리버스 프록시 뒤에 둔다) |
| `ZIPGENIE_SCHEDULER` | (없음) | `1` 이면 배치 스케줄러 실행 |
| `ZIPGENIE_NO_SCHEDULER` | (없음) | `1` 이면 어떤 경우에도 스케줄러 끔 |
| `ZIPGENIE_WORKERS` | 1 | uvicorn 프로세스 수 (최대 8). `start-zipbomi.bat` 은 공개 서버를 3 으로 띄운다 |
| `ZIPGENIE_ADMIN_UPSTREAM` | (없음) | 공개 서버가 `/api/admin/*` 를 넘길 관리·배치 서버 주소 (bat: `http://127.0.0.1:5031`) |
| `ZIPGENIE_TRIAL_SEC` | 60 | 로그인 전 둘러보기 시간(초). 부하 시험 때만 늘린다 |
| `ZIPGENIE_DB` | `backend/data/zipbomi.db` | 다른 DB 파일 사용 (시험용 사본 등 — 이때 자동 백업은 건너뜀) |
| `ZIPGENIE_DEBUG` | (없음) | `1` 이면 `/api/openapi.json` 공개 |

---

## 4. 외부 API 키 발급
| 서비스 | 발급 위치 | 비고 |
|---|---|---|
| 공공데이터포털 | https://www.data.go.kr → 로그인 → 아래 API 마다 **[활용신청]** → 마이페이지 > 개발계정에서 일반 인증키(Decoding) 복사 | 키 하나로 여러 API 를 쓰지만 **API 마다 신청·승인**이 필요. 승인 직후 1~2시간은 "등록되지 않은 인증키"가 나올 수 있음 |
| 한국은행 ECOS | https://ecos.bok.or.kr/api/ → 인증키 신청 | |
| Gemini | https://aistudio.google.com/apikey | 호출량만큼 토큰 비용 |
| 네이버 검색 | https://developers.naver.com → 애플리케이션 등록 → 검색 API | |
| Gmail SMTP | Google 계정 > 보안 > 2단계 인증 > 앱 비밀번호 | 하루 발송 한도가 있어 대량 발송엔 전용 메일 서비스 권장 |

공공데이터포털에서 신청할 API:

| 데이터셋 키 | 이름 | 신청 페이지 |
|---|---|---|
| `apt_trade` | 아파트 매매 실거래가 상세 | https://www.data.go.kr/data/15126468/openapi.do |
| `apt_rent` | 아파트 전월세 | https://www.data.go.kr/data/15126474/openapi.do |
| `rh_trade` / `rh_rent` | 연립다세대 매매 / 전월세 | https://www.data.go.kr/data/15126467/openapi.do · https://www.data.go.kr/data/15126473/openapi.do |
| `sh_trade` / `sh_rent` | 단독다가구 매매 / 전월세 | https://www.data.go.kr/data/15126465/openapi.do · https://www.data.go.kr/data/15126472/openapi.do |
| `offi_trade` / `offi_rent` | 오피스텔 매매 / 전월세 | https://www.data.go.kr/data/15126464/openapi.do · https://www.data.go.kr/data/15126475/openapi.do |
| `silv_trade` | 분양권·입주권 전매 | https://www.data.go.kr/data/15126471/openapi.do |
| `land_trade` | 토지 매매 | https://www.data.go.kr/data/15126466/openapi.do |
| `nrg_trade` | 상업업무용 매매 | https://www.data.go.kr/data/15126463/openapi.do |
| `indu_trade` | 공장·창고 매매 (기본 꺼짐) | https://www.data.go.kr/data/15126470/openapi.do |
| `apply_notice`, `apply_model` | 청약홈 분양정보 (공고·주택형별 분양가) | https://www.data.go.kr/data/15098547/openapi.do |
| `apply_cmpet` | 청약홈 경쟁률·당첨가점 | https://www.data.go.kr/data/15098905/openapi.do |

정확한 매핑은 `backend/config/re_datasets.yaml`. 신청 여부는 관리 > 부동산 데이터에서 데이터셋별 상태("정상" / "활용신청 필요")로 확인합니다.

---

## 5. 처음 실행 후 할 일
1. http://localhost:5030/admin 접속 → **대시보드**에서 "뉴스 수집" 실행 → 기사 수집·채점 확인.
2. **부동산 데이터** → "지금 실행"으로 실거래가·청약·한국은행 자료 수집 (키가 없거나 신청 안 된 API 는 CSV 로 받거나 건너뜀).
3. **노트 초안 생성** 실행 → **노트 검토**에서 행을 눌러 팝업으로 고친 뒤 게시 (게시한 노트만 사이트에 보임).
4. **현행 수치**에서 "확인 대기" 항목(LTV·DSR·중과세율 등)을 원문으로 확인 후 게시.
5. **개인정보 처리방침**에서 시행일·공지 버전 등록.
6. **배치 스케줄**에서 자동 실행 켜기/시각 조정 (13장).

---

## 6. 기술 스택

### 백엔드 (`backend/requirements.txt`)
| 패키지 | 버전 | 용도 |
|---|---|---|
| Python | 3.12 | |
| FastAPI | 0.115.6 | REST API, 정적 화면 서빙 |
| Uvicorn[standard] | 0.32.1 | ASGI 서버 (`serve.py`) |
| SQLite (내장) | — | 운영 DB, WAL 모드 |
| httpx | 0.28.1 | 외부 API·RSS·CSV 호출 |
| feedparser | 6.0.14 | RSS/Atom 수집 |
| RapidFuzz | 3.14.6 | 기사 중복 제거 |
| PyYAML | 6.0.3 | `config/*.yaml` |
| pandas (<3.1) | 2.x | CSV·통계 처리 |
| numpy | 2.x | 임베딩 코사인 유사도, 지식 지도·관련 노트 |
| google-genai | 2.30.0 | Gemini (채점·초안·질문하기·임베딩 `gemini-embedding-001`) |
| anthropic | 2.3.0 | Claude (선택 공급자) |
| databricks-sql-connector / thrift | 4.6.0 / 0.24.0 | Databricks Delta 적재 |
| playwright | 1.63.0 | OG 공유 카드·주간 PDF 리포트 렌더링 (Edge 또는 Chromium) |
| dnspython | 2.7.0 | 구독 이메일 도메인 MX 확인 |
| python-dotenv | 1.2.4 | `.env` 로드 |
| python-multipart | 0.0.17 | 파일 업로드(실거래 CSV) |

### 프론트엔드 (`frontend/package.json`)
| 패키지 | 용도 |
|---|---|
| React 18 · React DOM | 화면 |
| React Router 6 | 라우팅 (`src/App.tsx`) |
| Vite 5 · @vitejs/plugin-react | 개발 서버(5183)·빌드 |
| TypeScript 5 | 타입 검사 (`npm run typecheck`) |
| Leaflet 1.9 | 지도 `/map` |
| d3 7.9 · topojson (정적 파일 `backend/static/vendor`) | 데이터 랩 지도 |
| CSS 변수 테마 (`src/styles/theme.css`) | 다크·라이트, 노랑 강조 |

### 외부 데이터 · 서비스
국토교통부 실거래가(공공데이터포털 API + rt.molit.go.kr CSV), 청약홈(한국부동산원), LH 청약·임대 공고, 한국은행 ECOS, 언론사 RSS 57곳,
Google 뉴스 검색 RSS, 네이버 뉴스 검색 API, Gemini/Claude, SMTP(Gmail), Databricks(선택).

### 쓰지 않는 것
Docker(Dockerfile 없음), 별도 벡터 DB, Redis, 외부 큐 — 모두 단일 프로세스 + SQLite 로 동작합니다.

---

## 7. 폴더 구조
```
ZipBomi/
├─ start-zipbomi.bat        운영 실행 (스케줄러 켜짐, 자동 재시작)
├─ start-dev.bat             개발 실행 (백엔드 --reload + Vite)
├─ docs/                     설계·로드맵·API 메모
├─ backend/
│  ├─ serve.py               uvicorn 실행기 (ZIPGENIE_* 환경 변수)
│  ├─ requirements.txt
│  ├─ .env.example           환경 변수 예시 (.env 는 커밋 금지)
│  ├─ api/
│  │  ├─ main.py             FastAPI 앱, 미들웨어(보안 헤더·CSRF·본문 제한·접근 기록), lifespan(DB 초기화·스케줄러)
│  │  ├─ common.py           관리자 판정, 방문자 쿠키(zgv) 등
│  │  └─ routers/            공개 API (home, home_market, notes, realestate, re_map, calendar, now, me, ask, subscribe, privacy…)
│  │                         관리 API admin_*.py (외부 접근 차단)
│  ├─ pipeline/              수집·가공·배치
│  │  ├─ collectors/         RSS·HTML·네이버·Reddit 수집기
│  │  ├─ db.py               스키마·쿼리·백업
│  │  ├─ jobs.py · scheduler.py · joblog.py   배치 작업과 실행 로그
│  │  ├─ llm.py · gemini_keys.py · claude_llm.py   채점·초안·요약
│  │  ├─ vectorizer.py · knowledge.py · agent_chat.py   임베딩·의미 검색·질문하기
│  │  ├─ redata.py · rtms.py · rt_download.py · re_upload.py · re_sources.py · re_store.py   부동산 데이터
│  │  ├─ policy.py           현행 수치·변경 이력·노트 자동 문구
│  │  ├─ reminders.py        청약 D-3·전세 만기 알림
│  │  ├─ privacy.py          처리방침 항목·버전
│  │  ├─ warehouse.py        Databricks 적재
│  │  └─ mailer.py · notify.py · alerts.py   메일·경보
│  ├─ app/                   OG 카드·성향 테스트·용어·데이터 랩 HTML
│  ├─ config/                sources.yaml(뉴스 출처), re_datasets.yaml(부동산 데이터셋) 등
│  ├─ static/                로고·파비콘·OG 이미지·vendor JS
│  ├─ tools/                 피드 점검·콘텐츠 가져오기 스크립트
│  └─ data/                  (git 제외) zipgenie.db, settings.json, llm_keys.json, backups/, downloads/, logs/
└─ frontend/
   ├─ index.html · vite.config.ts · tsconfig.json · package.json
   └─ src/
      ├─ App.tsx             라우트
      ├─ layout/             Layout(메뉴), Theme
      ├─ components/         ui(Dialog·Tabs 등), Dialogs(구독·문의), NoteCard…
      ├─ pages/              공개 화면, pages/admin/ 관리 화면
      ├─ policy.tsx · profile.tsx   현행 수치·프로필 공용
      └─ styles/             theme.css, profile.css
```

---

## 8. 아키텍처
```
브라우저 ──HTTP──▶ uvicorn(FastAPI, 5030)
                    ├─ /api/*        공개 API (방문자 쿠키 zgv, 상태 변경은 X-Requested-With: zipgenie 필수)
                    ├─ /api/admin/*  관리 API (로컬 접속 또는 ADMIN_TOKEN)
                    └─ /*            frontend/dist (SPA) + /og, /static
                         │
                         ▼
                 SQLite backend/data/zipbomi.db (WAL)
                         ▲
배치 스케줄러(같은 프로세스, ZIPGENIE_SCHEDULER=1)
   ├─ 뉴스 수집 → 키워드 필터 → 중복 제거 → LLM 채점
   ├─ 노트 초안 → 관리자 검토 → 게시
   ├─ 임베딩(vectorize) → 의미 검색·질문하기
   ├─ 부동산 데이터(API/CSV) · 한국은행 · 청약
   ├─ 알림 메일(reminders) · 주간 흐름 · 뉴스레터
   └─ DB 백업 · (선택) Databricks MERGE
```
- 공개 화면은 화면별 짧은 캐시(`/api/now` 300초, `/api/home/market` 600초, 실거래 조회 24시간).
- 공개 방문자 판정: Tailscale Funnel 헤더(`Tailscale-Funnel-Request`)·`X-Forwarded-For` 를 보고 외부 요청이면 관리 API 를 막습니다.

---

## 9. 화면과 메뉴
| 주소 | 내용 |
|---|---|
| `/` | 홈 — "내 연소득으로 살 수 있는 집 가격" 즉시 계산, 지금 시장(금리·지난달 전국 거래·많이 거래된 지역·최고가·2주 안 청약·오늘 읽은 기사), 이번 주 노트 |
| `/notes` | 노트 — 카테고리·형식(3분 요약·깊이 읽기·숫자로 보기)·내 조건 필터, 단어+의미 검색 |
| `/deals` | 실거래가 — 지역·월 조회, 3.3㎡당 통계·추이, 단지 검색, 청약 공고 탭 |
| `/map` | 지도 — 지역별 시세·청약 위치 |
| `/my-homes` | 관심 단지·지역·메모 (방문자 본인만) |
| `/calendar` | 분양 일정 달력, 🔔 접수 D-3 알림, 당첨 가점 비교 탭 |
| `/calc` | 계산기 — 대출 한도(LTV·DSR)·월 상환, 취득세, 청약 가점, 전세가율·갭. URL 매개변수(price·jeonse·ltv·dsr·rate·tab…)로 값 전달 |
| `/now` | 현행 수치 — 기준금리·주담대 금리·LTV/DSR·취득세율·주택가격전망 CSI·주택관련 가계대출 (출처·기준일 표시) |
| `/ask` | 질문하기 — 노트·기사 근거 답변 (구독 확인 후) |
| `/me` | 내 프로필 — 유형·관심 지역·소득·전세 만기·알림 설정 |
| `/today` `/type` `/career` `/habit` `/diagnosis` `/lab` | 퀴즈·성향 테스트·데이터 랩 |
| `/about` `/privacy` `/terms` `/letter` `/refer` `/confirm` `/unsubscribe` | 소개·처리방침·구독 관련 |
| `/admin/*` | 관리 |

메뉴(7칸): 이번 주 · 노트 · 시세▾(실거래가·지도·관심 단지) · 청약▾(분양 일정·청약 공고) · 계산기▾(계산기·현행 수치) · 질문하기 · 더 보기▾(퀴즈·테스트·데이터 랩·소개).

관리 화면: 대시보드, 노트 검토(행 클릭 → 편집 팝업, 게시·저장·반려 버튼 하단 고정), 데일리 브리핑, 수집 기사, 주간 흐름, 주간 PDF 리포트,
의미 검색·질문하기, 수집 설정, 배치 스케줄, AI 모델 설정, 부동산 데이터, 현행 수치, 실거래 CSV 업로드, 개인정보 처리방침, 구독자, 참여 현황,
접근 기록, 데이터 웨어하우스. 실행 중인 작업은 화면 아래 로그 독에 실시간으로 표시됩니다.

---

## 10. 데이터 수집
- **뉴스** (`config/sources.yaml`): 57곳 — 국토부, 경제지 부동산 섹션 RSS, 경향·국민·SBS·서울신문·연합뉴스TV 경제, Google 뉴스 주제 검색 21개 등
  (실제 응답·기사 날짜를 확인한 것만). 네이버 검색 키워드 22개. 부동산 키워드 규칙 → 중복 제거 → 관련도 채점(1~5점).
- **실거래가** (`pipeline/redata.py`·`rtms.py`·`rt_download.py`): 데이터셋마다 `source: auto` — API 가 되면 API, 안 되면 rt.molit.go.kr CSV.
  - CSV 는 하루 60파일 상한. 받은 파일의 검색조건(실거래구분·시도·시군구·계약일자)을 요청과 대조해 다르면 한 번 다시 받고 그래도 다르면 건너뜀.
  - NUL 바이트 구멍이 있는 파일은 손상으로 처리. 캡차 등 자동화 방지 장치는 우회하지 않습니다.
  - 관리 > 실거래 CSV 업로드로 직접 받은 CSV 도 넣을 수 있습니다.
- **청약**: 청약홈 분양정보·주택형별 분양가·경쟁률·당첨가점, LH 청약·임대 공고.
- **한국은행 ECOS** (`config/re_datasets.yaml`): 기준금리, 주담대 금리, KB 매매·전세 지수, 지가변동률, 주택가격전망 CSI·소비자심리지수(511Y002),
  주택관련 가계대출 잔액(151Y005, 십억원).
- **현행 수치** (`pipeline/policy.py`): 자동 항목(기준금리·주담대 금리·CSI·가계대출)은 수집값으로 갱신, 규제 수치(LTV·DSR·취득세율 등)는
  관리자가 원문 확인 후 게시. 바뀐 값은 `policy_param_history` 에 기록.

---

## 11. 벡터화 · 의미 검색
- `pipeline/vectorizer.py` — Gemini `gemini-embedding-001`(768차원)로 **노트 전부**와 **관련도 3점 이상 기사**를 임베딩.
- 별도 벡터 DB 없이 SQLite `notes.embedding`·`articles.embedding`(TEXT, JSON 배열)에 저장, 검색은 numpy 코사인 유사도.
  기사는 최근 90일만 검색, 노트는 기간 제한 없음. 노트의 제목·요약·본문·태그를 고치면 임베딩을 지워 다음 실행 때 다시 만듭니다.
- 쓰는 곳: 노트 검색(단어 검색과 결합), 질문하기 근거(노트 4 + 기사 4), 관리 > 의미 검색.
- 키가 없거나 호출이 실패하면 단어 검색만 동작합니다. Gemini 호출이라 토큰 비용이 듭니다 — 배치에서 끌 수 있습니다.

## 11-1. 계정 · 내 공간 · 알림 (2026-11-02)
- **메일 링크 로그인** (`api/routers/auth.py`, `pipeline/accounts.py`): 비밀번호 없음. `POST /api/auth/request` → 메일의 `/login?t=…` → 화면 버튼으로
  `POST /api/auth/verify` (30분·한 번만, 토큰은 sha256 해시로 저장). 계정은 방문자 쿠키 원값(raw) 하나를 가지며, 로그인하면 브라우저 쿠키를 그 값으로
  바꿔 심어 프로필·관심 단지·알림·필터·계산 입력(visitor_state)이 기기와 상관없이 이어진다. 로그인 전 브라우저에 쌓인 값은 계정 쪽에 합친다(목록은 합집합).
  같은 주소의 확인된 구독자와 자동으로 이어진다. `POST /api/auth/logout`, '내 기록 지우기'(`DELETE /api/me`)는 계정까지 삭제.
  로그인 메일은 주소당 1분 간격·하루 10통, 확인·연결·로그인 메일 합계 하루 300통 상한.
- **내 공간** `/my` (`GET /api/me/space`, `pipeline/my_space.py`): 관심 단지 최근 6개월 거래·3.3㎡당 변동, 관심·알림 청약(D-day), 저장한 노트(`note_bm`),
  저장한 계산(`calc_saves`, 계산기 '이 계산 저장'), 메모(`my_memo`), 관심 공고(`apply_fav`).
- **내 자료로 질문하기**: `/api/ask` 가 `mine`(기본 켬)이면 `my_space.context_text()` 의 '내 상황' 글을 근거에 붙인다 (Gemini 로 전송 — 처리방침 국외 이전 항목에 명시).
- **로그인 보안 3중**: ① 1회용 링크(128비트·해시 저장·30분·버튼 확정) ② 요청한 브라우저(nonce 쿠키 `zgl`)가 아니면 메일의 6자리 코드 필요, 5번 틀리면 무효
  ③ 로그인마다 알림 메일 + '모든 기기에서 로그아웃'(`POST /api/auth/revoke`·`/api/auth/logout-all` — 계정 raw 교체로 다른 기기 쿠키 무효). 요청·확인 횟수 제한.
- **내 일정 달력·항목 메모**: `/my` 통합 달력(관심·알림 공고 일정, 전세 만기, 항목 알림 `my_items`, 직접 넣은 일정 `my_events`). 항목마다 메모·알림 날짜.
- **상단 🔔** (`layout/AlertBell.tsx`, `GET /api/me/alerts`): 켠 청약·전세 만기 알림과 상태(D-day·메일 예정·보냄·지남), 내 공간 알림·일정(3일 전부터).
- **원격 관리**: `.env` `ADMIN_TOKEN` 설정 → 공개 주소 `/admin` 에서 토큰 입력(5회 틀리면 잠시 차단). 이 PC 는 브라우저 요청(Sec-Fetch-Site)일 때만 토큰 없이 관리자.

## 11-2. 데이터 랩 · 청약 통계 (2026-11-02)
- `/lab` 위쪽 시장 놀이터 (`GET /api/lab/market`, 1시간 캐시): 2년 월별 거래량·3.3㎡ 중위 + 금리·심리·KB 지수, 예산 슬라이더, 시군구 순위, 3곳 비교.
- 청약 신청·당첨자 통계 (`pipeline/apply_stats.py`, 공공데이터 15110812 ApplyhomeStatSvc 6종 → `re_apply_stat`, 매일 re_data 끝에) →
  `GET /api/re/apply-stats` → `/calendar?tab=scores` 위쪽 (지역 가점 당첨선 추이·지역 경쟁률·연령대별 당첨). 15126242(경쟁률·가점 파일)는 활용신청 승인 필요.
- 출처 326곳 (`config/sources.yaml`): 정부·공공·경제지·종합·전문지·Google 뉴스·유튜브 78·블로그·커뮤니티·해외 언론·해외 연구. 영어 기사용 키워드 규칙 `housing market (EN)`.


## 11-3. 서비스 구성 · 로그인 전 제한 · 보미AI · 데이터 보존 (2026-11-02)
**서버 구성 (동시 접속 1천 명 대비)**
- `start-zipbomi.bat` → 공개 서버 **5030 (프로세스 3개, 예약 작업 없음)** + `backend/run-admin.bat` → 관리·배치 서버 **5031 (프로세스 1개, 예약 작업 실행)**.
- 공개 서버는 `/api/admin/*` 를 관리·배치 서버로 그대로 넘긴다(`ZIPGENIE_ADMIN_UPSTREAM`) — 관리 화면 주소는 그대로(`/admin`), 작업 상태·실행 로그는 한곳.
- 모두에게 같은 공개 자료(`/api/now`·`/api/home/market`·`/api/lab/*` 등)는 `Cache-Control: public, max-age=60`. 개인 응답은 캐시하지 않는다.
- 실측(이 PC, i7-1165G7 8스레드): 프로세스 1개 → 3개에서 `/api/home` 142 → 269 req/s, `/api/me` 169 → 288 req/s, `/api/now` 269 → 751 req/s.
  동시 1천 명이 보통 만드는 요청은 초당 100~200건.
- ⚠ 실행 중인 bat 파일을 고치지 않는다(cmd 가 줄 위치로 다시 읽어 꼬인다). 바꾼 뒤에는 창을 닫고 다시 실행.

**로그인 전 1분 둘러보기** (`pipeline/gate.py`, `layout/TrialGate.tsx`)
- 처음 방문 시각을 서명 쿠키(`zgt`)와 IP(`trial_ip` 표, 2일 뒤 삭제)로 기억. 1분이 지나면 공개 API 가 401 `{login_required}` → 화면은 `/about?login=1` 로 옮겨 로그인 창.
- 늘 열린 API: `/api/me*`, `/api/auth/*`, 소개·처리방침·구독·문의·방문 기록. 화면(HTML)·공유 미리보기·사이트맵은 막지 않는다. 관리자는 막지 않는다.

**보미AI** (옛 질문하기) — 오른쪽 패널(`layout/AskPanel.tsx`, ✦ 버튼)로 보던 화면 옆에서 질문, `/ask` 는 전체 화면.
- 로그인 계정마다 **처음 1회 무료**(`accounts.ask_credits/ask_used`). 다 쓰면 "관리자에게 사용 신청" → 문의. 관리 > 회원 계정에서 +5/+30회.
- 내 공간 자료(관심 단지 시세·공고·프로필·메모)를 근거로 넘긴다(`mine`).

**개인 데이터 보존**
- 로그인 계정의 저장값은 오래 접속하지 않아도 지우지 않는다(탈퇴 = '내 기록 지우기' 때만). 비로그인 방문자는 395일 미접속 시 정리.
- 저장 한도: 계정 400KB·방문자 32KB, 값 하나 4,000자·목록 300개. 넘으면 **조용히 버리지 않고 413** → 화면 위 알림.
- 저장 실패(연결 끊김)는 2·5·15·30초 뒤 다시 보내고, 못 보낸 변경은 브라우저(`zg-unsaved`)에 남겨 다음 방문 때 다시 보낸다.
- 내 공간 '내 데이터 백업' — JSON 내려받기·되살리기. DB 는 매일 자동 백업(14일).

**메뉴** — 시세(실거래가·지도·데이터 랩·관심 단지) · 청약(분양 일정·공고) · 소식(이번 주·노트·현행 수치) · 더 보기(계산기·퀴즈·테스트·소개) + ✦ 보미AI.
**내 공간** — 내 일정 달력(공고·전세 만기·알림·일정·할 일), 할 일 체크리스트, 관심 단지 비교 표, 항목별 메모·알림, 설정 전체 보기, 데이터 백업.

## 12. Databricks 적재
- `pipeline/warehouse.py` — 운영 DB 는 로컬 SQLite 로 두고, 바뀐 행만 `<catalog>.<schema>`(기본 `workspace.zipgenie`) Delta 테이블로 MERGE.
- 행 내용 해시를 로컬 `warehouse_sync` 에 기억해 변경분만 보내고, 로컬에서 지운 행은 Databricks 에서도 지웁니다.
- 보내지 않는 것: 구독자·문의(이메일)·접속 기록(IP)·임베딩 열.
- 기본 꺼짐(`settings.json` 의 `warehouse.auto_sync=false`). 관리 > 데이터 웨어하우스에서 수동 적재·전체 재적재.

## 13. 배치 스케줄
`backend/data/settings.json` (관리 > 배치 스케줄). 새로 설치하면 기본값으로 시작합니다.

| 작업 | 기본 | 기본 시각 | 내용 |
|---|---|---|---|
| `collection` | 꺼짐 | 08:00 · 11:00 · 14:00 · 17:30 | 뉴스 수집·채점 |
| `drafting` | 꺼짐 | 07:30 · 13:30 | 노트 초안 |
| `vectorize` | 꺼짐 | 08:00 · 14:00 | 임베딩 |
| `re_data` | 켜짐 | 06:30 | 실거래가·청약·한국은행·CSV 자동 다운로드 |
| `reminders` | 켜짐 | 08:10 | 청약 D-3, 전세 만기 D-90·D-30 메일 |
| `weekly`, `newsletter`, `teams` | 설정값 | — | 주간 흐름·뉴스레터·Teams 알림 |

DB 백업도 스케줄러가 돌 때만 실행됩니다 → 운영은 반드시 `ZIPGENIE_SCHEDULER=1`(= `start-zipbomi.bat`).

## 14. DB 테이블
- 콘텐츠: `notes`(status draft/published/rejected, format, policy_params, embedding), `articles`, `article_archives`, `issues`, `keywords`, `newsletters`
- 방문자·구독: `visitor_state`, `profiles`, `engagements`, `daily_polls`, `daily_quizzes`, `subscribers`, `subscriber_profile`, `members`, `contacts`, `newsletter_sends`, `reminder_log`
- 부동산: `rtms_*`(실거래 12종), `re_apply_notice/model/cmpet/score`, `re_econ_series`, `re_base_rate`, `re_listing`, `re_dataset_conf/state`, `re_api_calls`, `re_fetch_log`, `rt_csv_*`, `re_upload_log`
- 정책·개인정보: `policy_params`, `policy_param_history`, `privacy_versions`
- 운영: `access_logs`, `run_logs`, `schedule_claims`, `app_meta`

스키마는 `pipeline/db.py`·`re_store.py`·`policy.py` 등이 시작 시 자동으로 만들고 열을 추가합니다(마이그레이션 도구 없음).

## 15. 보안 · 개인정보
- 관리 API: 로컬 접속 또는 `ADMIN_TOKEN` 만 허용, 외부(Funnel·XFF) 요청은 401/403. `X-Forwarded-For` 위장으로 우회 불가.
- CSRF: 상태를 바꾸는 요청은 `X-Requested-With: zipgenie` 헤더 필수(없으면 428), 다른 사이트 출처 요청은 403.
- 요청 본문 64KB 제한, 보안 헤더(CSP·X-Frame-Options·X-Content-Type-Options·Referrer-Policy), 방문자 쿠키 `HttpOnly; SameSite`.
- 프로필 입력은 허용값 목록으로 정리(XSS 방지), SQL 은 모두 파라미터 바인딩.
- 개인정보: 처리방침 버전 관리(공지일·시행일), 구독 해지 시 프로필·알림 기록 삭제, Databricks 로 개인정보 미전송.
- 비밀값은 `.env`·`data/llm_keys.json` 에만 두고 git 에 올리지 않습니다.

## 16. 운영 (백업 · 처리량 · 공개)
- **백업**: 스케줄러가 `backend/data/backups/` 에 매일 DB 사본을 남깁니다(DB 크기 × 보관 개수만큼 디스크 필요).
- **처리량**: 단건 응답 2~37ms, 프로세스 1개 기준 초당 약 60~100건. 더 필요하면 `ZIPGENIE_WORKERS` 를 2~4 로 올리거나 리버스 프록시 캐시를 둡니다.
- **공개**: 서버는 127.0.0.1 에만 바인드하고, 공개는 **별도 Tailscale 기기 `zipgenie`** 의 Funnel(443)로 합니다 → https://zipbomi.tail6bd481.ts.net
  (같은 PC 의 다른 프로젝트가 기본 기기의 Funnel 443·8443·10000 을 쓰고 있어 겹치지 않게 두 번째 tailscaled 를 사용자 공간 모드로 띄움).
  - 상태·인증서·로그: `backend/data/tailscale/` (git 제외). `start-zipbomi.bat` 이 꺼져 있으면 자동으로 띄우고 Funnel 설정은 유지됩니다.
  - 처음 한 번 설정 (새 PC):
    ```bat
    set TS="C:\Program Files\Tailscale\tailscale.exe"
    set SOCK=\\.\pipe\zipgenie-tailscaled
    start "" /min "C:\Program Files\Tailscale\tailscaled.exe" --windows-mode=dev --tun=userspace-networking --statedir="%CD%\backend\data\tailscale" --socket=%SOCK% --port=41642
    %TS% --socket=%SOCK% up --hostname=zipgenie --accept-dns=false --unattended   & rem 출력된 로그인 링크를 승인
    %TS% --socket=%SOCK% funnel --bg --https=443 http://127.0.0.1:5030
    %TS% --socket=%SOCK% funnel status
    ```
  - 끄기: `%TS% --socket=%SOCK% funnel --https=443 off` (기본 기기의 Funnel 은 영향 없음).
  - `.env` 의 `SITE_URL` 을 공개 주소로 맞춰야 메일 링크·사이트맵·공유 주소가 맞습니다. Caddy·Nginx 등 다른 리버스 프록시로 옮길 때도 같습니다.
- **로그**: 관리 화면 실행 로그 독, `backend/data/logs/`.

## 17. 테스트 결과
2026-11-02, 실서버 DB 사본·시험 포트, 실제 메일 발송 없음.
- **기능**: API·화면 28개 × 데스크톱/휴대폰·상호작용 117개 중 115개 통과 (나머지 2개는 404 가 맞는 경우). 콘솔 오류·가로 넘침 없음.
- **보안**: 58개 항목 차단 확인 — 관리 API 104개 외부 접근, XFF 위장, CSRF, 본문 제한, `.env`·DB 노출·경로 우회, SQL 주입·XSS,
  외부 리다이렉트, 쿠키, 보안 헤더, CORS, TRACE, 남용 한도, 구독 전 질문하기 차단.
- **부하**: 방문자 1만 명·동시 200·프로세스 1개 — 요청 72,907건, 실패 22건(0.03%), 초당 64건, p50 약 2초·p95 약 10초.
- **데이터 품질**: rt.molit.go.kr 가 다른 검색 결과를 섞어 보낸 CSV 3건을 찾아 47,885행 롤백, 이후 검색조건 대조로 차단.

## 18. 자주 겪는 문제
| 증상 | 원인 · 해결 |
|---|---|
| `[Errno 10048] error while attempting to bind on address ('127.0.0.1', 5030)` 가 반복 | 다른 프로세스가 5030 사용 중. `Get-NetTCPConnection -LocalPort 5030` 으로 PID 확인 후 종료하거나 `ZIPGENIE_PORT` 변경 |
| 공공데이터 API "등록되지 않은 인증키" / 관리 화면 "활용신청 필요" | 해당 API 활용신청 안 됨 또는 승인 직후 동기화 대기(1~2시간) |
| 상태 변경 요청이 428 | `X-Requested-With: zipgenie` 헤더 누락 (화면 밖에서 API 를 부를 때) |
| 메일 속 링크가 안 열림 | `SITE_URL` 이 localhost |
| `start-zipbomi.bat` 이 "이미 집보미 가 실행 중입니다" 하고 끝남 | 다른 창에서 이미 실행 중 — 그 창을 쓰거나 닫고 다시 실행 |
| 공개 주소가 안 열림 | `tailscale --socket=\\.\pipe\zipgenie-tailscaled status` 로 기기 상태 확인, 꺼져 있으면 bat 재실행. 첫 접속은 인증서 발급으로 수십 초 걸릴 수 있음 |
| 수집·백업·알림이 안 돎 | 스케줄러 꺼진 채 실행 — `ZIPGENIE_SCHEDULER=1` |
| OG 카드·PDF 생성 실패 | Edge 없음 → `python -m playwright install chromium` |
| PowerShell 스크립트 한글 깨짐 | Windows PowerShell 5.1 은 UTF-8 BOM 필요 |
| `pandas` 설치 오류 (사내 PC) | 앱 제어 정책으로 3.1 DLL 차단 — requirements 의 `<3.1` 유지 |

## 19. 실서비스 전에 남은 것
1. 지금은 PC + Tailscale Funnel 공개(https://zipbomi.tail6bd481.ts.net) — 상시 서비스는 전용 도메인·호스팅 결정 후 `SITE_URL` 변경.
2. 공공데이터포털 활용신청 승인 확인(청약홈 2종·연립 매매·분양권·토지).
3. 현행 수치 "확인 대기" 8개(DSR·스트레스 DSR·LTV·생애최초 LTV·주담대 한도·다주택 중과세율) 원문 확인 후 게시.
4. 개인정보 처리방침 새 버전 공지(알림 설정·발송 기록 항목 추가분).
5. 대량 발송용 메일 서비스와 SPF·DKIM, 이용약관, 지도 매물 공개 시 공인중개사법 광고 규정 검토.
6. ECOS 개인 키, 원격 관리용 `ADMIN_TOKEN`, 백업 보관 개수·용량.
7. `backend/static/og/` 의 예전 공유 카드 정리.
8. 로드맵 Phase 5(톤·편집자 메모·질문하기 검색 화면·첫 방문 안내), Phase 6(공유 이미지 점검·유입 경로 기록).
