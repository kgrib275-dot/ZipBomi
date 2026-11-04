# 집보미 (ZIPBOMI) — 집을 봐 주는 비서

> 2026-11-02 이름을 ZipGenie(집지니)에서 **집보미(ZIPBOMI)**로 바꿨습니다. 프로젝트 폴더 `ZipBomi`, 실행 파일 `start-zipbomi.bat`, DB `backend/data/zipbomi.db`, 공개 주소 `zipbomi.tail6bd481.ts.net`.
> 이미 쓰는 사람의 로그인·저장값이 끊기지 않도록 내부 식별자(환경 변수 `ZIPGENIE_*`, 쿠키 `zgv`, 요청 헤더 `X-Requested-With: zipgenie`, 브라우저 저장 키 `zipgenie-*`)는 옛 이름 그대로 둡니다.

부동산 뉴스·정책·실거래가·청약·금리 자료를 모아 **노트(해설)**, **실거래가 조회**, **분양 일정·알림**, **대출·세금·청약 계산기**,
**현행 수치**, **보미AI(질문)**로 보여 주는 **무료** 웹 서비스입니다. 백엔드는 FastAPI + SQLite, 화면은 React(Vite)이며 한 프로세스가 API 와 화면을 함께 내보냅니다.

- 저장소: https://github.com/kgrib275-dot/ZipBomi
- 설계 기준 `docs/ZIPBOMI_SPEC.md` · 단계별 계획 `docs/ROADMAP_PHASES.md` · API 메모 `docs/API.md`, `docs/API-notes-backend-public.md`
- 최종 갱신 2026-11-03 — 이날 바뀐 것: 로그인·운영 안정성(11-5절), ISMS-P 기준 보안(11-6절·`docs/ISMS-P.md`), 품질 검수 반영(11-7절),
  속도 개선·메뉴 정리(11-5절 '속도', 11-3절 '메뉴'), 개인정보 수집 문구 '확인했습니다'·처리방침 구제 기관 정리,
  지도의 네이버·카카오·구글 단추를 키 없이도 사용(지금 위치를 새 창으로 — 19절 6번), 관리자 OTP 재사용 차단(11-6절)
- 2026-11-04 — 공개 전 점검표(5절), 자체 도메인 공개 절차(16절 Cloudflare Tunnel), `.env.example` 에 OTP·지도 키 추가, 광고용 처리방침 조항(11-8절)

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
    - [11-4. 무료 서비스 출시 준비 (2026-11-03)](#11-4-무료-서비스-출시-준비-2026-11-03)
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
- http://localhost:5030 — 사이트, http://localhost:5030/admin — 관리 화면 (`.env` `ADMIN_TOKEN` 을 한 번 입력)
- 배치 스케줄러가 켜진 채로 뜨고, 서버가 멈추면 5초 뒤 저절로 다시 시작합니다. 창을 닫으면 종료.
- `frontend/dist` 가 없으면 처음 한 번 화면을 빌드합니다.
- 이미 실행 중인 집보미 서버(5030·5031)가 있으면 그 창까지 자동으로 끄고 새로 띄웁니다 (`stop-zipbomi.ps1`). Tailscale 공개 기기는 그대로 둡니다.
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
| `ADMIN_TOKEN` | **필수(운영)** | 관리자 로그인 토큰. 관리 화면에서 로그인하면 세션 쿠키(30분 미사용·8시간 최대)를 받는다 (11-6절) |
| `ADMIN_TOTP_SECRET` | 권장 | 관리자 OTP 2단계 인증 비밀값 — `backend/venv/Scripts/python backend/tools/admin_otp.py` 로 만들어 OTP 앱에 등록 |
| `DATABRICKS_SERVER_HOSTNAME`, `DATABRICKS_HTTP_PATH`, `DATABRICKS_TOKEN` | 선택 | Databricks 적재 |
| `DATABRICKS_CATALOG`, `DATABRICKS_SCHEMA` | 선택 | 적재 위치 (기본 `workspace.zipgenie`) |
| `KAKAO_JS_KEY` | 선택 | 카카오 공유 + 지도 화면 안 카카오맵 (developers.kakao.com > JavaScript 키, 플랫폼 > Web 에 공개 도메인 등록, 카카오맵 사용 설정 켜기) |
| `NAVER_MAP_CLIENT_ID` | 선택 | 지도 화면 안 네이버 지도 (네이버 클라우드 Maps — 뉴스 검색용 `NAVER_CLIENT_ID` 와 다름) |
| `GOOGLE_MAPS_KEY` | 선택 | 지도 화면 안 구글 지도 (Maps JavaScript API). 지도 키 세 개는 비워도 단추가 그 회사 지도 새 창으로 열린다 |
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
| `ZIPGENIE_LOCAL_ADMIN` | (없음) | `1` 이면 이 PC 브라우저 접속을 토큰 없이 관리자로 (개발용 — `start-dev.bat` 만 켠다. 운영에서 켜지 않는다) |
| `ZIPGENIE_TRUST_ADMIN_IPS` | (없음) | `1` 이면 관리 > 관리자 IP 에 등록한 IP 를 토큰 없이 관리자로 (X-Forwarded-For 위조 위험 — 기본 끔) |
| `ZIPGENIE_LOGIN_MAIL_CAP` | 150 | 하루 로그인 메일 상한 (로그인 1번 = 링크 메일 + 알림 메일 2통) |
| `ZIPGENIE_MAIL_CAP` | 120 | 하루 구독 확인·질문하기 연결 메일 상한 (로그인 메일과 따로 센다) |
| `ZIPGENIE_IP_TRIALS` | 50 | 같은 IP 에서 하루 새로 시작할 수 있는 1분 둘러보기 수 (이동통신망 등 공유 IP 대비) |

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

### 공개 전 점검표 (새 PC·새 도메인에 그대로 따라 하기)
1. `.env` — `ADMIN_TOKEN`(40자 이상 무작위), `SITE_URL`(공개 주소, https), `SMTP_*`(로그인 메일), `DATA_GO_KR_KEY`·`ECOS_API_KEY`.
2. 관리자 OTP — `cd backend && venv\Scripts\python tools\admin_otp.py` → 나온 비밀값을 OTP 앱(Google OTP 등)에 등록하고 `.env` `ADMIN_TOTP_SECRET` 에 넣는다.
3. `start-zipbomi.bat` 실행(화면 빌드 자동) → 관리 > **운영 점검**에서 경고 항목이 없는지 확인.
4. 공개 주소 연결 — 자체 도메인은 16절 '자체 도메인으로 공개', 임시로는 16절 Tailscale Funnel.
5. `register-autostart.ps1` 실행(로그인 1분 뒤 자동 시작) + Windows 전원 옵션 '절전 안 함'.
6. 외부 백업 위치 정하기(16절 '백업' 목록 그대로 주 1회).
7. 관리 > 개인정보 처리방침 시행·공지, 현행 수치 기준일 확인, 뉴스레터 발송 여부 결정.
8. Google Search Console·네이버 서치어드바이저에 `https://<도메인>/sitemap.xml` 등록.

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
├─ stop-zipbomi.ps1         실행 중인 서버(5030·5031)와 그 창 종료, 화면 코드가 바뀌었으면 다시 빌드 (start-zipbomi.bat 이 먼저 부름)
├─ register-autostart.ps1   Windows 로그인 때 자동 시작 등록·해제
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
| `/` | 홈 — "내 연소득으로 살 수 있는 집 가격" 즉시 계산, 지금 시장(금리·지난달 전국 거래·많이 거래된 지역·최고가·2주 안 청약·최근 읽은 기사), 이번 주 노트 |
| `/notes` | 노트 — 카테고리·형식(3분 요약·깊이 읽기·숫자로 보기)·내 조건 필터, 단어+의미 검색 |
| `/deals` | 실거래가 — 지역·월 조회, 3.3㎡당 통계·추이, 단지 검색, 청약 공고 탭 |
| `/map` | 지도 — 지역별 시세·청약 위치, 네이버·카카오·구글 지도로 보기(키 없으면 새 창, 정보 창의 '네이버 지도에서 보기') |
| `/my-homes` | 관심 단지·지역·메모 (방문자 본인만) |
| `/calendar` | 분양 일정 달력, 🔔 접수 D-3 알림, 당첨 가점 비교 탭 |
| `/calc` | 계산기 — 대출 한도(LTV·DSR)·월 상환, 취득세, 청약 가점, 전세가율·갭. URL 매개변수(price·jeonse·ltv·dsr·rate·tab…)로 값 전달 |
| `/now` | 현행 수치 — 기준금리·주담대 금리·LTV/DSR·취득세율·주택가격전망 CSI·주택관련 가계대출 (출처·기준일 표시) |
| `/ask` | 보미AI — 노트·기사 근거 답변 (메일 로그인 후, 계정마다 처음 1회 무료) |
| `/me` | 내 프로필 — 유형·관심 지역·소득·전세 만기·알림 설정 |
| `/today` `/terms` `/type` `/career` `/habit` `/diagnosis` `/lab` | 퀴즈(오늘의 퀴즈·용어 퀴즈)·성향 테스트·데이터 랩 |
| `/about` `/privacy` `/login` `/letter` `/refer` `/confirm` `/unsubscribe` | 소개·처리방침·로그인·구독 관련 |
| `/admin/*` | 관리 |

메뉴: 11-3 절 '메뉴' 참고 (2026-11-03 정리 — 시세·청약·소식·계산기·더 보기 + ✦ 보미AI).

관리 화면: 대시보드, 노트 검토(행 클릭 → 편집 팝업, 게시·저장·반려 버튼 하단 고정), 데일리 브리핑, 수집 기사, 주간 흐름, 주간 PDF 리포트,
의미 검색·질문하기, 수집 설정, 배치 스케줄, AI 모델 설정, 부동산 데이터, 현행 수치, 운영 점검, 참여 분석, Databricks 적재, 구독·발송,
회원 계정, 문의함, 관리자·접속(접속기록·위변조 점검), 개인정보 처리방침. 실행 중인 작업은 화면 아래 로그 독에 실시간으로 표시됩니다.

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
  로그인 메일은 주소당 1분 간격·하루 10통. 하루 전체 상한은 로그인 150통·확인·연결 120통을 따로 센다 (2026-11-03, 11-5절).
- **내 공간** `/my` (`GET /api/me/space`, `pipeline/my_space.py`): 관심 단지 최근 6개월 거래·3.3㎡당 변동, 관심·알림 청약(D-day), 저장한 노트(`note_bm`),
  저장한 계산(`calc_saves`, 계산기 '이 계산 저장'), 메모(`my_memo`), 관심 공고(`apply_fav`).
- **내 자료로 질문하기**: `/api/ask` 가 `mine: true`(기본 꺼짐 — 이용자가 켤 때만, 2026-11-03)면 `my_space.context_text()` 의 '내 상황' 글을 근거에 붙인다 (관리 > AI 모델 설정의 공급자로 전송 — 처리방침 위탁·국외 이전 항목에 자동으로 맞춰 표시).
- **로그인 보안 3중**: ① 1회용 링크(128비트·해시 저장·30분·버튼 확정) ② 요청한 브라우저(nonce 쿠키 `zgl`)가 아니면 메일의 6자리 코드 필요, 5번 틀리면 무효
  ③ 로그인마다 알림 메일 + '모든 기기에서 로그아웃'(`POST /api/auth/revoke`·`/api/auth/logout-all` — 계정 raw 교체로 다른 기기 쿠키 무효). 요청·확인 횟수 제한.
- **내 일정 달력·항목 메모**: `/my` 통합 달력(관심·알림 공고 일정, 전세 만기, 항목 알림 `my_items`, 직접 넣은 일정 `my_events`). 항목마다 메모·알림 날짜.
- **상단 🔔** (`layout/AlertBell.tsx`, `GET /api/me/alerts`): 켠 청약·전세 만기 알림과 상태(D-day·메일 예정·보냄·지남), 내 공간 알림·일정(3일 전부터).
- **관리 화면**: `.env` `ADMIN_TOKEN` 설정 → `/admin` 에서 토큰 입력(10분에 10번 틀리면 잠시 차단). 2026-11-03부터 이 PC 에서도 토큰이 필요하다 (11-5절).
- 2026-11-03 바뀐 로그인 구조(코드 입력·기기별 로그인·메일 상한 분리)는 11-5절.

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
- 처음 방문 시각을 서명 쿠키(`zgt`)로 기억. 1분이 지나면 공개 API 가 401 `{login_required}` → 화면은 `/about?login=1` 로 옮겨 로그인 창.
- 같은 IP 는 하루 `ZIPGENIE_IP_TRIALS`(50)개까지 새 둘러보기를 받는다(`trial_ip` 표). 넘으면 새 쿠키는 이미 끝난 둘러보기로 준다 — 쿠키를 지워 가며 1분을 계속 받지 못하게.
- 늘 열린 API: `/api/me*`, `/api/auth/*`, 소개·처리방침·구독·문의·방문 기록. 화면(HTML)·공유 미리보기·사이트맵은 막지 않는다. 관리자는 막지 않는다.

**보미AI** (옛 질문하기) — 오른쪽 패널(`layout/AskPanel.tsx`, ✦ 버튼)로 보던 화면 옆에서 질문, `/ask` 는 전체 화면.
- 로그인 계정마다 **처음 1회 무료**(`accounts.ask_credits/ask_used`). 다 쓰면 "관리자에게 사용 신청" → 문의. 관리 > 회원 계정에서 +5/+30회.
- 내 공간 자료(관심 단지 시세·공고·프로필·메모)를 근거로 넘긴다(`mine`).

**개인 데이터 보존**
- 로그인 계정의 저장값은 오래 접속하지 않아도 지우지 않는다(탈퇴 = '내 기록 지우기' 때만). 비로그인 방문자는 395일 미접속 시 정리.
- 저장 한도: 계정 400KB·방문자 32KB, 값 하나 4,000자·목록 300개. 넘으면 **조용히 버리지 않고 413** → 화면 위 알림.
- 저장 실패(연결 끊김)는 2·5·15·30초 뒤 다시 보내고, 못 보낸 변경은 브라우저(`zg-unsaved`)에 남겨 다음 방문 때 다시 보낸다.
- 내 공간 '내 데이터 백업' — JSON 내려받기·되살리기. DB 는 매일 자동 백업(14일).

**메뉴** (2026-11-03 정리) — 시세(지도·실거래가·지역 비교·관심 단지) · 청약(분양 일정·청약 공고·당첨 가점) · 소식(이번 주 시장·해설 노트·규제·금리) · 계산기 · 더 보기(재미로 알아보기: 퀴즈·테스트 / 서비스 소개) + ✦ 보미AI.
**내 공간** — 내 일정 달력(공고·전세 만기·알림·일정·할 일), 할 일 체크리스트, 관심 단지 비교 표, 항목별 메모·알림, 설정 전체 보기, 데이터 백업.

## 11-4. 무료 서비스 출시 준비 (2026-11-03)
집보미는 **무료** 개인 서비스로 운영한다. 콘텐츠·데이터·메일 운영 기준은 [docs/CONTENT_POLICY.md](docs/CONTENT_POLICY.md).
- **유료 월 구독 끔**: `settings.ask.membership` 기본 `false`.
  - 꺼져 있으면 `/ask`의 월 구독 코드·신청 화면을 숨긴다. `POST /api/membership/request`는 404를 돌려주고, 처리방침의 월 구독 항목도 빠진다.
  - 켜려면 먼저 사업자등록과 통신판매업 신고를 하고, 바닥글에 사업자 정보를 표시한다.
- **보미AI**: 횟수는 관리 > 회원 계정에서 무료로 늘려 준다.
  - "내 공간 자료도 참고"는 **켤 때만** 보낸다. 기본 꺼짐이고, 패널에서 고른 값은 localStorage `zipgenie-ask-mine`에 저장한다.
- **생성형 AI 표시 (인공지능 기본법)**: 노트 아래, 보미AI 패널과 `/ask`, 바닥글, 소개 FAQ에 넣었다.
  - "AI 단어를 화면에 쓰지 않는다"는 규칙의 예외인 법적 고지라 지우지 않는다.
- **개인정보 처리방침 v1**: 2026-11-03 시행.
  - 운영자·보호책임자 김성환, 연락처 shkim.m01@gmail.com.
  - 메일 발송 업체는 `SMTP_HOST`가 gmail.com이고 발송 업체 칸이 비어 있으면 자동으로 Google LLC (Gmail), 미국 국외 이전으로 표시한다.
  - Gemini는 "무료 등급은 Google이 서비스 개선·사람 검토에 이용할 수 있음"으로 적었다. 유료 등급으로 바꾸면 이 문구를 고치고 새 버전을 공지한다.
- 회사 메일로 만든 계정·구독은 개인 Gmail로 옮겼다. 운영에는 회사 계정·브랜드를 쓰지 않는다.

## 11-5. 로그인·운영 안정성 점검 반영 (2026-11-03)
**로그인**
- **로그인 창에서 코드 바로 입력**: `POST /api/auth/request` 뒤 창에 메일의 6자리 코드를 넣으면 `POST /api/auth/verify-code` 로 로그인.
  링크를 요청한 브라우저(nonce 쿠키 `zgl`) + 코드 두 가지를 확인한다(`login_tokens.ncode_hash`, 5번 틀리면 무효).
  휴대폰 메일 앱이 링크를 앱 안 브라우저로 열어 '다른 기기'로 처리되던 문제를 피한다. 메일의 링크(`/login?t=…`)도 그대로 쓸 수 있다.
- **기기별 로그인** (`account_sessions` 표): 로그인하면 쿠키(`zgv`)에 계정 raw 대신 그 기기만의 값(sid, DB 에는 해시)을 심고, 요청마다
  `accounts.resolve()` 로 계정 raw 로 바꾼다. 내 공간 '로그인한 기기'(`GET /api/auth/sessions`)에서 기기별 로그아웃(`POST /api/auth/sessions/end`).
  로그아웃은 그 기기 값을 지워 쿠키를 다시 쓸 수 없다. 1년 안 쓴 기기는 로그아웃. 예전 방식 쿠키(계정 raw)도 받고, 다음 로그인 때 바뀐다.
- **다른 계정 자료 섞임 고침**: 로그인할 때 익명으로 쌓은 값만 계정에 합친다. 예전엔 A 계정으로 로그인된 브라우저에서 B 가 로그인하면 A 의 자료가 B 에 복사됐다.
- **메일 상한 분리**: 로그인 메일 하루 `ZIPGENIE_LOGIN_MAIL_CAP`(150), 구독 확인·연결 메일 `ZIPGENIE_MAIL_CAP`(120)을 따로 센다.
  못 보냈으면 429 로 알린다(예전엔 "보냈습니다"라고 답했다). 구독 신청은 IP 당 하루 40건. 확인·기록은 프로세스 공용 잠금(`pipeline/xlock.py`)으로 묶는다.
  ⚠ 개인 Gmail 은 하루 500통 — 사용자가 늘면 메일 발송 서비스(Resend·AWS SES 등)로 바꾼다.
- 로그인 판정 캐시는 "로그인됨"만 10초 기억(로그인 직후 다른 프로세스가 로그인 창을 다시 띄우던 문제).

**관리자**
- 운영에서는 **127.0.0.1 접속도 토큰 없이는 관리자가 아니다**. Host·Sec-Fetch-Site 머리글은 브라우저가 아닌 프로그램이 마음대로 넣을 수 있고,
  공개용 tailscaled(사용자 공간 모드)나 같은 PC 의 다른 서비스를 거친 요청도 127.0.0.1 로 들어오기 때문. `/admin` 에서 `ADMIN_TOKEN` 을 한 번 입력한다.
  개발 서버(`start-dev.bat`)는 `ZIPGENIE_LOCAL_ADMIN=1` 로 예전처럼. 등록 IP 관리자는 `ZIPGENIE_TRUST_ADMIN_IPS=1` 일 때만.
- 공개 서버는 `/api/admin/*` 를 넘기기 전에 관리자인지 먼저 보고, 본문은 2MB(실거래가 업로드 61MB)까지만 받는다.

**서버**
- 둘러보기 판정(DB 읽기)을 작업 스레드에서 한다 — 배치가 DB 를 잡고 있어도 공개 서버 이벤트 루프가 멈추지 않게.
- 로그 파일을 프로세스마다 따로(`data/logs/zipbomi-<포트>-<PID>.log`), 14일 지난 로그는 시작할 때 지운다.
- 노트 공유 카드(Chromium)는 PC 전체에서 한 번에 하나만 그린다.
- 공개 서버가 5분마다 관리·배치 서버 스케줄러 기록(`scheduler_tick`)을 보고, 10분 넘게 멈췄으면 경보(Teams·`ALERT_EMAIL`, 1시간에 한 번).
- 매일 작업(수집·초안·벡터화·부동산 데이터·알림 메일)을 정해진 시각에 놓쳤으면 3시간 안에서 한 번 따라잡는다.
- 하루 정리·백업은 별도 스레드에서. 백업 중 끊겨 남은 `.tmp`(1시간 지난 것)와 30일 지난 `.bad` 는 지운다.
- 쓰기 요청 분당 한도·보미AI IP 동시 질문 수는 프로세스 수(`ZIPGENIE_WORKERS`)로 나눠 PC 전체 기준이 되게. 남용 제한 확인·기록은 프로세스 공용 잠금으로 묶는다.
- `start-zipbomi.bat` 은 이미 떠 있는 집보미 서버(5030·5031)와 그 창을 끄고 새로 띄운다 (`stop-zipbomi.ps1`).

**속도** (DB 사본·프로세스 3개 실측: `/api/me` 42 → 5.5ms, `/api/home` 50~78 → 6.7ms, 지도 시세 첫 요청 0.8~1.5초 → 5ms, `/api/lab/html` 0.5초 → 4ms)
- DB 연결 재사용 (`pipeline/db.py connect`) — 3.4GB DB 는 새 연결의 첫 쿼리마다 스키마를 읽어 약 5ms 가 들었다. 스레드마다 빈 연결을 돌려 쓴다. `ZIPGENIE_DB_POOL=0` 이면 끈다.
- 공용 캐시(`api/common.cached`)는 만료되면 직전 값을 바로 주고 뒤에서 다시 계산한다. 서버 시작 때 지도 시세·홈·현행 수치·데이터 랩을 미리 계산한다.
- 데이터 랩 문서(약 1MB)는 계산할 때 gzip 으로 한 번만 압축해 두고, 화면에서는 그 부분에 가까워질 때 불러온다.
- 모바일 메뉴는 화면보다 길면 메뉴 안에서 스크롤, 보미AI 패널은 좁은 화면에서 양옆 0(스크롤바 폭 때문에 왼쪽이 잘리던 문제).

## 11-6. ISMS-P 기준 보안 (2026-11-03)
항목별 상태·운영자 정기 점검·사고 대응은 [docs/ISMS-P.md](docs/ISMS-P.md). 코드로 넣은 것:
- **관리자 로그인 세션** (`pipeline/admin_auth.py`, `POST /api/auth/admin-login`·`admin-logout`): 토큰(+ OTP)으로 로그인하면 HttpOnly·SameSite=Strict 쿠키 `zga`.
  토큰을 브라우저 저장소에 두지 않는다(예전 `zipgenie-admin-token` 은 지운다). 30분 미사용·8시간이면 끊기고, 같은 IP 5번 실패면 30분 잠금.
  `ADMIN_TOTP_SECRET` 을 넣으면 OTP 필수, `X-Admin-Token` 헤더 로그인은 막힌다.
  한 번 로그인에 쓴 OTP 숫자는 다시 쓸 수 없다(`admin_otp_used` — 화면에 보인 숫자를 누가 바로 넣어도 거절, 토큰이 맞을 때만 소비, 2026-11-03).
  OTP 의 남은 위험(가짜 관리자 페이지에 토큰·OTP 를 넣는 피싱)은 즐겨찾기한 주소로만 로그인하는 것으로 막는다 — 더 강하게 하려면 패스키(WebAuthn).
- **관리자 접속기록** (`admin_audit` 표): 관리 API 요청(작업 상태 폴링 제외)·권한 없는 시도·로그인·실패·잠금·로그아웃·다운로드·전체 보기.
  누가(세션 해시 앞 10자리)·언제·IP·무엇을·결과·사유. 행마다 앞 행 해시를 이어 고치거나 지우면 `GET /api/admin/audit/verify` 가 찾는다. 2년 보관.
  관리 > 관리자·접속에서 보고 점검, 운영 점검 화면에도 OTP·위변조 상태 표시.
- **개인정보 표시 제한·다운로드 사유**: 관리 화면 표의 이메일은 가려서 보이고 '전체 보기'와 모든 CSV 내려받기는 사유(4자 이상)를 받아 기록한다(`POST /api/admin/audit/event`).
- 처리방침 제8조 안전성 확보 조치 문구 갱신 — 관리 화면에서 새 버전 공지.

## 11-7. 품질 검수 반영 (2026-11-03)
사용자·관리자·서비스 세 관점 검수(운영 DB 사본·휴대폰/PC·밝은/어두운 테마)에서 재현된 문제를 고쳤다.
- **로그인 흐름**: 둘러보기 1분이 끝나면 다른 화면으로 옮기지 않고 보던 화면 위에 로그인 창 → 로그인하면 그 화면 그대로. 서버가 그린 공유 페이지(`/n/`·`/s/`·`/r/`)는 둘러보기를 시작하지 않는다.
  로그인 창에 만 14세 확인·수집 안내(서버도 `agree` 확인). `/login` 만 열면 로그인 단추.
- **메일**: 청약 알림의 구독 해지 링크(`?token=`) 수정, 모든 메일에 글자 본문, 구독 메일에 `List-Unsubscribe`(원클릭 `POST /api/unsubscribe/one-click`),
  바탕색을 표에도(메일 앱이 `<body>` 스타일을 지울 때 대비), 뉴스레터 바닥에 AI 고지·보낸 곳. 청약 D-3·전세 만기 알림은 로그인 계정에도 보낸다.
- **법적 고지**: 처리방침 제8·9조를 공지 때 함께 고정(`privacy.MEASURES`·`COOKIES`), 쿠키 zgv·zgt·zgl·zga 와 브라우저 저장소를 사실대로.
  AI 공급자(Claude 선택 시 Anthropic)가 위탁·국외 이전에 자동 반영. 노트 공유 페이지에 AI·면책 고지, 홈 지표 칸마다 출처, 현행 수치는 기준일 없이 게시 불가.
  기사 본문 가져오기는 그 사이트 `robots.txt` 를 지킨다(막히면 발췌만).
- **화면**: 접수 중인 청약 '지남' 표시 수정(`applyStatus.ts`), 실거래가 탭은 주소로만, 탭 제목, 뒤로 가기 스크롤 복원, ↑ 단추는 내려갔을 때만, 휴대폰 그래프 글자·표,
  대화상자 키보드 접근성, 문의 중복 접수 방지(부서·직책 칸 삭제), 홈 기사 시각 한국 시각, 계산기 금리 기본값 = 현행 주담대 금리, 조 단위, 지난 공고 🔔 숨김.
- **관리**: 운영 점검 요약·대시보드 배치·의미 검색 현황·구독자 집계 표시 수정, 보미AI 충전은 계정 기준, 위험한 작업(뉴스레터 전체 발송·Teams·대량 수집·전체 재적재) 확인 창,
  세션이 끝나도 쓰던 화면 유지(로그인 창만 겹쳐 띄움)·쓰는 동안 세션 유지·25분 미사용 경고, 날짜 계산을 한국 시각으로, 처리방침 공지 흐름(달라진 부분·중요 변경 30일·확인),
  **문의함**(`/admin/contacts` — 미처리 먼저·처리 완료 표시·답장), 문장 속 이메일·IP 가림, 접속기록 검색 지연·한국어 이름, 노트 검토 실패 시 창 유지, 현행 수치 공개 값 변경 확인,
  휴대폰 관리 화면(메뉴 접기·공개용 단추 숨김), 로그인 잠김 해제 시각·성공 시 실패 수 초기화, 시험 DB 서버에서 백업 막음.

## 11-8. 광고를 붙일 때의 처리방침 (2026-11-04)
- 관리 > 개인정보 처리방침 > **광고 사업자** 칸(`ads_vendor`, 예 `Google LLC (Google AdSense)`)을 채우면 처리방침에 **제9조의2 행태정보의 수집·이용 및 거부(맞춤형 광고)**가 생긴다
  (`pipeline/privacy.py ads()`): 수집 항목·방법·목적·보유 기간, 수집·처리하는 자(광고 사업자가 직접 수집 — 운영자는 받지 않음), 거부 방법
  (Google 내 광고 센터·브라우저 타사 쿠키 차단·휴대폰 광고 ID), 만 14세 미만 맞춤형 광고 안 함, 문의처. 제9조 쿠키 문구·'거부 시 불이익'도 광고용으로 바뀐다.
- 칸을 비워 두면 내용이 예전과 똑같다(지금 공지한 버전에 영향 없음 — 운영 DB 사본으로 확인).
- **순서**: 광고 사업자 입력 → 새 버전을 **중요 변경(30일 공지)**으로 공지 → 시행일 이후 광고 코드를 붙인다. 광고 스크립트를 붙일 때는 보안 헤더(CSP)에 광고 도메인을 더해야 한다(아직 안 함).
- 개인정보보호위원회 맞춤형 광고 행태정보 가이드라인 항목을 따랐지만 법률 검토를 대신하지 않는다.

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
- 계정·보안: `accounts`, `account_sessions`(기기별 로그인), `login_tokens`, `admin_sessions`, `admin_audit`(관리자 접속기록·해시 연결), `trial_ip`
- 운영: `access_logs`, `run_logs`, `schedule_claims`, `app_meta`

스키마는 `pipeline/db.py`·`re_store.py`·`policy.py` 등이 시작 시 자동으로 만들고 열을 추가합니다(마이그레이션 도구 없음).

## 15. 보안 · 개인정보
- 관리 API: `ADMIN_TOKEN` 만 허용(2026-11-03부터 로컬 접속도 토큰 필요, 개발 서버만 예외). `X-Forwarded-For`·Host 위장으로 우회 불가.
- CSRF: 상태를 바꾸는 요청은 `X-Requested-With: zipgenie` 헤더 필수(없으면 428), 다른 사이트 출처 요청은 403.
- 요청 본문 64KB 제한, 보안 헤더(CSP·X-Frame-Options·X-Content-Type-Options·Referrer-Policy), 방문자 쿠키 `HttpOnly; SameSite`.
- 프로필 입력은 허용값 목록으로 정리(XSS 방지), SQL 은 모두 파라미터 바인딩.
- 개인정보: 처리방침 버전 관리(공지일·시행일, v1 2026-11-03 시행), 구독 해지 시 프로필·알림 기록 삭제, Databricks 로 개인정보 미전송.
- 로그인: 메일 링크(1회용·30분) + 다른 기기면 6자리 코드 + 로그인 알림 메일·모든 기기 로그아웃. 로그인 전 방문자는 1분 둘러보기 뒤 API 401.
- 비밀값은 `.env`·`data/llm_keys.json` 에만 두고 git 에 올리지 않습니다.

## 16. 운영 (백업 · 처리량 · 공개)
- **백업**: 스케줄러가 `backend/data/backups/` 에 매일 DB 사본을 남깁니다(DB 크기 × 보관 개수만큼 디스크 필요, 14개 ≈ 50GB).
  자동 백업은 **DB 만** 합니다. 외부 백업에는 아래도 함께 넣으세요: `backend/.env`, `backend/data/settings.json`, `backend/data/llm_keys.json`,
  `backend/data/admin_token.txt`, `backend/data/tailscale/`(공개 주소 기기), `backend/static/og/`(공유 이미지), `backend/data/reports/`.
- **복원** (DB 가 깨졌거나 잘못 지웠을 때):
  1. 서버 창 두 개(5030·5031)를 닫는다 (`stop-zipbomi.ps1` 을 실행해도 된다).
  2. `backend/data/zipbomi.db` 를 다른 이름으로 옮겨 두고(증거·되돌리기용), 같은 폴더의 `zipbomi.db-wal`·`zipbomi.db-shm` 도 함께 옮긴다.
  3. `backend/data/backups/zipbomi-YYYYMMDD.db` 중 원하는 날짜를 `backend/data/zipbomi.db` 로 **복사**한다.
  4. `start-zipbomi.bat` 실행 → 관리 > 운영 점검에서 DB·백업 상태 확인. 그날 이후 들어온 구독·계정·저장값은 사라진다(복원 시점까지만 남음).
  - 시험 복원은 백업을 사본으로 복사해 `ZIPGENIE_DB=<사본 경로>` 로 시험 포트(5052 등)에 띄워 확인한다 — 운영 DB 를 건드리지 않는다.
- **자동 시작**: `register-autostart.ps1` 을 한 번 실행하면 Windows 로그인 1분 뒤 `start-zipbomi.bat` 이 자동으로 실행된다(해제 `-Remove`).
  재부팅 뒤 로그인이 필요하므로 Windows 자동 로그인 또는 재부팅 알림을 함께 쓰고, 절전·최대 절전은 끈다.
- **화면 빌드**: `start-zipbomi.bat` 이 시작할 때(`stop-zipbomi.ps1`) `frontend/src` 가 빌드보다 새로우면 자동으로 `npm run build` 한다 (2026-11-03).
- **처리량**: 공개 서버 프로세스 3개(`ZIPGENIE_WORKERS=3`) 기준 `/api/now` 초당 751건, `/api/me` 288건, `/api/home` 269건 (i7 8스레드 실측). 구성은 11-3 절.
- **외부 백업**: 자동 백업은 같은 디스크라 디스크 고장에 대비하지 못한다. 매주 외장 디스크·클라우드에 사본을 둔다.
- **재시작**: `start-zipbomi.bat` 을 고친 뒤에는 실행 중인 창에서 Ctrl+C 로 재시작하지 말고 창을 닫고 다시 실행한다(cmd 가 바뀐 파일을 줄 위치로 읽어 꼬인다).
- **공개**: 서버는 127.0.0.1 에만 바인드하고, 공개는 **별도 Tailscale 기기 `zipbomi`** 의 Funnel(443)로 합니다 → https://zipbomi.tail6bd481.ts.net
  (같은 PC 의 다른 프로젝트가 기본 기기의 Funnel 443·8443·10000 을 쓰고 있어 겹치지 않게 두 번째 tailscaled 를 사용자 공간 모드로 띄움).
  - 상태·인증서·로그: `backend/data/tailscale/` (git 제외). `start-zipbomi.bat` 이 꺼져 있으면 자동으로 띄우고 Funnel 설정은 유지됩니다.
  - 처음 한 번 설정 (새 PC):
    ```bat
    set TS="C:\Program Files\Tailscale\tailscale.exe"
    set SOCK=\\.\pipe\zipgenie-tailscaled
    start "" /min "C:\Program Files\Tailscale\tailscaled.exe" --windows-mode=dev --tun=userspace-networking --statedir="%CD%\backend\data\tailscale" --socket=%SOCK% --port=41642
    %TS% --socket=%SOCK% up --hostname=zipbomi --accept-dns=false --unattended   & rem 출력된 로그인 링크를 승인
    %TS% --socket=%SOCK% funnel --bg --https=443 http://127.0.0.1:5030
    %TS% --socket=%SOCK% funnel status
    ```
  - 끄기: `%TS% --socket=%SOCK% funnel --https=443 off` (기본 기기의 Funnel 은 영향 없음).
  - `.env` 의 `SITE_URL` 을 공개 주소로 맞춰야 메일 링크·사이트맵·공유 주소가 맞습니다. Caddy·Nginx 등 다른 리버스 프록시로 옮길 때도 같습니다.
- **자체 도메인으로 공개 (Cloudflare Tunnel — 무료, 공유기 포트 열지 않음)**: 코드에 공개 주소가 박혀 있지 않아 `SITE_URL` 만 바꾸면 된다
  (CSRF 는 `Sec-Fetch-Site`, 쿠키 Secure·접속자 IP 는 프록시 헤더 `X-Forwarded-For`·`X-Forwarded-Proto` 로 판단 — 2026-11-04 확인).
  1. 도메인 구입(.com·.kr 연 1.5~3만 원). Cloudflare 에서 사거나, 다른 곳에서 샀으면 Cloudflare 에 사이트를 추가하고 네임서버를 Cloudflare 로 바꾼다.
  2. Cloudflare 대시보드 > **Zero Trust > Networks > Tunnels > Create a tunnel**(Cloudflared) → 이름 `zipbomi`.
  3. 이 PC 에 cloudflared 설치: `winget install --id Cloudflare.cloudflared` → 화면에 나온 `cloudflared.exe service install <토큰>` 을 **관리자 PowerShell** 에서 실행
     (Windows 서비스로 등록돼 재부팅해도 저절로 켜진다. 토큰은 비밀값 — 저장소·채팅에 남기지 않는다).
  4. 같은 화면 **Public Hostname** 추가: 도메인(예 `zipbomi.kr` 또는 `www.zipbomi.kr`) → Service `HTTP` · `127.0.0.1:5030`.
  5. `backend/.env` `SITE_URL=https://<도메인>` → `start-zipbomi.bat` 다시 실행 → 관리 > 운영 점검에서 SITE_URL 확인.
  6. 카카오·네이버 지도 키를 쓰면 각 개발자 사이트에 새 도메인 등록, 검색 사이트에 새 사이트맵 등록.
  7. 기존 `*.ts.net` 주소는 한동안 켜 둔다 — 이미 보낸 메일 링크·공유 링크가 그 주소다. 로그인 쿠키는 주소마다 따로라 새 도메인에서는 한 번 다시 로그인한다.
  - Cloudflare 의 SSL/TLS 모드는 기본(Flexible/Full 어느 것이든 터널은 동작), **Always Use HTTPS** 를 켠다.
- **로그**: 관리 화면 실행 로그 독, `backend/data/logs/`.

## 17. 테스트 결과
2026-11-02, 실서버 DB 사본·시험 포트, 실제 메일 발송 없음.
- **기능**: API·화면 28개 × 데스크톱/휴대폰·상호작용 117개 중 115개 통과 (나머지 2개는 404 가 맞는 경우). 콘솔 오류·가로 넘침 없음.
- **보안**: 58개 항목 차단 확인 — 관리 API 104개 외부 접근, XFF 위장, CSRF, 본문 제한, `.env`·DB 노출·경로 우회, SQL 주입·XSS,
  외부 리다이렉트, 쿠키, 보안 헤더, CORS, TRACE, 남용 한도, 구독 전 질문하기 차단.
- **부하**: 방문자 1만 명·동시 200·프로세스 1개 — 요청 72,907건, 실패 22건(0.03%), 초당 64건, p50 약 2초·p95 약 10초.
- **데이터 품질**: rt.molit.go.kr 가 다른 검색 결과를 섞어 보낸 CSV 3건을 찾아 47,885행 롤백, 이후 검색조건 대조로 차단.

- **2026-11-02 재점검** (프로세스 3개 구성): 기능·화면 133개 중 132개 통과(남은 1개는 404 가 맞음), 보안 67개 중 64개 통과(남은 3개도 정상 차단·동작 확인).
  1분 둘러보기 제한·공유 캐시·저장 한도 413·쿠키 없이 같은 IP 재접속 차단 확인. 동시 1,000명 asyncio 시험은 초당 75건(같은 PC 에서 시험 프로그램이 CPU 를 나눠 써 병목).
- **2026-11-03**: 프런트 빌드 통과, 처리방침 v1 '시행 중', 월 구독 신청 404 확인.
- **2026-11-03 로그인·보안·검수** (시험용 DB·운영 DB 사본, 실제 메일 발송 없음):
  - 로그인 41개 통과 — 코드 로그인·기기별 로그인·다른 계정 자료 섞임 방지·메일 상한 분리·관리자 판정·둘러보기 IP 한도·매일 작업 따라잡기·링크/코드 각 1회.
  - 관리자 보안 22개 통과 — 세션 쿠키 속성·30분 미사용/8시간 만료·5회 실패 잠금·OTP(RFC 6238)·헤더 로그인 차단·접속기록 해시 사슬 위변조 탐지.
  - 휴대폰 흐름 2개 통과 — 같은 브라우저 다른 창에서 링크 로그인 시 처음 창 자동 로그인, 메일 앱 안 브라우저 로그인 뒤 처음 창 코드 로그인.
  - 품질 검수 세 관점(사용자 390/768/1280 × 밝은/어두운, 관리 19개 화면, 서비스·법적 고지) → 반영 뒤 재확인 28개 중 26개 통과(남은 2개는 시험 조건 문제로 화면에서 정상 확인).
  - 속도(운영 DB 사본·프로세스 3개): `/api/me` 42 → 5.5ms, `/api/home` 50~78 → 6.7ms, 지도 시세 첫 요청 0.8~1.5초 → 5ms, `/api/lab/html` 0.5초 → 4ms.

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
1. 서버 재시작(`start-zipbomi.bat` 창을 닫고 다시 실행) 뒤 공개 주소에서 5031 연결·관리 화면·처리방침·월 구독 404 확인.
2. KB 매매·전세지수 재배포 조건 확인(KB부동산 약관) — 안 되면 홈 지표 두 칸 숨김.
3. 외부 백업(외장 디스크·클라우드) 주 1회.
4. 현행 수치 8개는 게시돼 있으나 LTV 3개·주담대 최대 금액은 기준일이 비어 있음 — 원문으로 다시 확인해 기준일을 채운다(2026-11-03 부터 기준일 없이는 새로 게시할 수 없고, 화면에는 '기준일 확인 중'으로 표시).
5. 공공데이터포털 활용신청 승인 확인(청약홈 경쟁률·가점 파일 15126242 는 지금 401, 연립 매매·분양권·토지).
6. 지도 키 발급: `NAVER_MAP_CLIENT_ID`(네이버 클라우드 Maps — 뉴스 검색용 `NAVER_CLIENT_ID` 와 다름), `KAKAO_JS_KEY`(+ 도메인 등록), `GOOGLE_MAPS_KEY`.
   키가 없어도 지도 화면의 네이버·카카오·구글 단추는 **지금 보던 위치를 그 회사 지도 새 창으로** 연다(2026-11-03). 공고·시세 정보 창에는 '네이버 지도에서 보기'.
   키를 넣으면 같은 단추가 집보미 화면 안에 그 회사 지도를 그린다. 네이버: 네이버 클라우드 플랫폼 > Maps > Application 등록(Dynamic Map) →
   서비스 URL 에 공개 주소·`http://localhost:5030` 등록 → Client ID 를 `.env` `NAVER_MAP_CLIENT_ID` 에. `ECOS_API_KEY` 도 비어 있음.
7. 구독자가 늘면: Gmail 하루 약 500통 한도 → 발송 서비스와 SPF·DKIM, Gemini 유료 등급(처리방침 문구도 갱신).
8. 자체 도메인 + Cloudflare Tunnel 로 이전 — 절차는 16절 '자체 도메인으로 공개'(`*.ts.net` 은 옮길 수 없음). PC 를 늘 켜 두기 어렵거나 이 PC 가 회사 PC 라면 VPS(리눅스, 메모리 4GB 이상)로 옮기고 2절 명령 + systemd 로 띄운다.
9. 이용약관, 지도 매물 공개 시 공인중개사법 광고 규정 검토.
10. 첫 커밋(`1b3bebb`) 메시지는 옛 이름 "집지니" 그대로(force push 는 하지 않음).
11. 노트 다시 검토: 30번은 원문(11월 3일 1순위)과 달리 '2월 3일'로 적혀 있음, 6번·11번은 같은 주제(종부세 주택 수 중과 폐지) 중복 — 관리 > 노트 검토에서 고치거나 합친다.
12. 뉴스레터 발송을 켤지 결정(관리 > 배치 스케줄). 화면의 구독 안내는 이 설정의 요일·시각을 그대로 보여 주고, 꺼져 있으면 '발송을 시작하면 첫 호부터'로 안내한다.
13. 검색 등록: Google Search Console·네이버 서치어드바이저에 `사이트맵(/sitemap.xml)` 등록.
