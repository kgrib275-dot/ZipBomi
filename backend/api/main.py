"""집보미 API + 정적 화면 서버 (FastAPI).

한 프로세스가 맡는 것:
1. /api/…            React 화면이 쓰는 JSON API (api/routers/*)
2. /n/ /sitemap.xml /robots.txt /s/… /r/…   검색 엔진·메신저용 서버 렌더링 페이지 (app/web.py)
3. /app/static/…     공유 이미지·로고·vendor JS
4. /assets/… 와 그 밖의 모든 GET   React 빌드(frontend/dist) — 없는 경로는 index.html (SPA)
5. 배치 스케줄러 (ZIPGENIE_SCHEDULER=1 일 때만 — start-public 이 설정)

실행: python serve.py  (포트 ZIPGENIE_PORT, 기본 5030)
"""
from __future__ import annotations

import importlib
import logging
import os
import pkgutil
import re
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parent.parent  # backend/
DIST = ROOT.parent / "frontend" / "dist"
load_dotenv(ROOT / ".env")

from pipeline import db, settings_store  # noqa: E402  (.env 먼저)

log = logging.getLogger("zipgenie.api")


def _log_file() -> None:
    from logging.handlers import RotatingFileHandler
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    log_dir = ROOT / "data" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    port = os.environ.get("ZIPGENIE_PORT", "5030")
    # 프로세스마다 파일을 따로 쓴다 (2026-11-03) — 공개 서버는 프로세스 3개라 같은 파일을 셋이 열면 Windows 에서 회전(이름 바꾸기)이
    # 실패하고(WinError 32) 그 뒤 기록이 버려졌다. 14일 넘은 로그는 시작할 때 지운다.
    cutoff = time.time() - 14 * 86400
    for old in log_dir.glob("zipbomi-*.log*"):
        try:
            if old.stat().st_mtime < cutoff:
                old.unlink()
        except OSError:
            pass
    h = RotatingFileHandler(log_dir / f"zipbomi-{port}-{os.getpid()}.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8",
                            delay=True)
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.getLogger().addHandler(h)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _log_file()
    import anyio.to_thread
    anyio.to_thread.current_default_thread_limiter().total_tokens = 100  # 동시 요청 작업 스레드 (기본 40)
    db.init_db()
    from pipeline import profile
    profile.ensure_table()
    filled = profile.backfill_notes()  # 새로 생긴 notes.regions·audience 를 키워드 규칙으로 채운다 (LLM 없음, 빈 것만)
    if filled["checked"]:
        log.info("노트 시군구·대상 유형 채움: %s", filled)
    from pipeline import policy
    policy.ensure()
    linked = policy.backfill_notes()  # 노트 ↔ 현행 수치 항목 (키워드 규칙, 빈 것만)
    if linked["checked"]:
        log.info("노트 현행 수치 연결: %s", linked)
    policy.refresh_auto()
    from pipeline import note_format
    fm = note_format.backfill()  # 노트 형식 (brief/deep/data) — 빈 것만
    if fm["checked"]:
        log.info("노트 형식 채움: %s", fm)
    from pipeline.scheduler import start_scheduler_thread, start_watchdog_thread
    start_scheduler_thread()
    start_watchdog_thread()  # 공개 서버만 — 관리·배치 서버(스케줄러)가 멈췄는지 본다
    log.info("집보미 API 시작 · DB %s · 프론트 빌드 %s", db.DB_PATH, "있음" if DIST.exists() else "없음(npm run build 필요)")
    threading.Thread(target=_warm_caches, daemon=True, name="zipbomi-warm").start()
    yield


def _warm_caches() -> None:
    """모두에게 같은 무거운 응답을 시작하자마자 미리 계산한다 (2026-11-03) — 프로세스마다 캐시가 따로라, 재시작 뒤 첫 방문자가
    지도 시세(1.5초)·홈 순위(0.5초) 등을 기다렸다. 만료 뒤에는 api/common.cached 가 뒤에서 다시 계산한다."""
    from api.routers import home, home_market, lab, now, re_map
    jobs = [("지도 시세", re_map.map_regions), ("홈 공용", lambda: home.cached("home:shared", home._shared, home._SHARED_TTL)),
            ("홈 시장", home_market.home_market), ("홈 순위", lambda: home_market.home_top("apt", "all", 10)),
            ("홈 거래량", lambda: home_market.home_volume("apt", "all")), ("현행 수치", now.now),
            ("데이터 랩 시장", lab.lab_market), ("데이터 랩 문서", lab.warm)]
    for name, fn in jobs:
        try:
            fn()
        except Exception:  # noqa: BLE001 - 미리 계산 실패는 첫 요청 때 다시
            log.warning("캐시 미리 계산 실패: %s", name, exc_info=True)


app = FastAPI(title="집보미 API", docs_url="/api/docs" if os.environ.get("ZIPGENIE_DEBUG") else None,
              redoc_url=None, openapi_url="/api/openapi.json" if os.environ.get("ZIPGENIE_DEBUG") else None, lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=1000, compresslevel=5)

# 보안 헤더 — 다른 사이트가 이 화면을 iframe 에 넣어 클릭을 가로채지 못하게(frame-ancestors), 형식 추측 금지 등.
# 스크립트 출처 제한(CSP script-src)은 데이터 랩·지도 문서(srcdoc)의 인라인 스크립트와 카카오 SDK 때문에 넣지 않았다.
_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": "frame-ancestors 'none'; object-src 'none'; base-uri 'self'; form-action 'self'",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
}
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
MAX_BODY = 64 * 1024            # 공개 API 요청 본문 상한 (관리 API 는 2MB) — 큰 본문으로 DB·백업을 불리지 못하게
MAX_BODY_ADMIN = 2 * 1024 * 1024
WRITE_PER_MIN = 240             # IP 하나가 1분에 보낼 수 있는 쓰기 요청 수 (회사 공용 IP 를 고려해 넉넉히)
# 이 수는 프로세스마다 따로 센다 — 공개 서버 프로세스가 3개면 실제 한도가 3배가 되므로 프로세스 수로 나눈다 (2026-11-03)
_WORKERS = max(1, int(os.environ.get("ZIPGENIE_WORKERS", "1") or 1))
_WRITE_LIMIT = max(20, WRITE_PER_MIN // _WORKERS)
_writes: dict[str, list[float]] = {}
_writes_lock = threading.Lock()


def _too_many_writes(ip: str) -> bool:
    """IP별 최근 1분 쓰기 요청 수 — 쿠키를 지워 가며 퀴즈·투표·기록을 반복해 통계를 왜곡하거나 DB를 불리는 것을 막는다."""
    now = time.monotonic()
    with _writes_lock:
        if len(_writes) > 20000:  # 메모리 상한 — 오래된 IP 정리
            for k in [k for k, v in _writes.items() if not v or now - v[-1] > 60]:
                _writes.pop(k, None)
        q = [t for t in _writes.get(ip, []) if now - t < 60]
        if len(q) >= _WRITE_LIMIT:
            _writes[ip] = q
            return True
        q.append(now)
        _writes[ip] = q
        return False


_SHARED_GET = {"/api/now", "/api/home/market", "/api/home/top", "/api/home/volume", "/api/lab/market", "/api/lab/region", "/api/re/apply-stats",
               "/api/re/calendar", "/api/re/scores", "/api/re/indicators", "/api/re/map/regions", "/api/re/map/apply", "/api/re/regions",
               "/api/re/datasets", "/api/site", "/api/about", "/api/type"}  # /api/today 는 방문자별 답이 섞여 뺐다


@app.middleware("http")
async def _guard(request: Request, call_next):
    # 위조 요청(CSRF) 차단 — 상태를 바꾸는 /api 요청은 우리 화면(api.ts)이 붙이는 X-Requested-With 가 있어야 한다.
    # 다른 사이트의 페이지는 이 헤더를 붙이면 브라우저가 사전 확인(CORS)을 하고, 이 서버는 CORS 를 허용하지 않으므로 막힌다.
    # 관리자 판정이 '이 PC(127.0.0.1)에서 온 요청'이라, 관리자가 이 PC에서 악성 페이지를 열면 몰래 관리자 IP 등록·발송이 되던 문제.
    if request.method not in _SAFE_METHODS and request.url.path.startswith("/api/"):
        is_admin_path = request.url.path.startswith("/api/admin/")
        try:
            size = int(request.headers.get("content-length") or 0)
        except ValueError:
            size = 0
        # 실거래가 파일 업로드(관리 > 부동산 데이터, admin_redata.upload)만 60MB+여유 — 다른 관리 API 는 그대로 2MB.
        # 이 경로는 Content-Length 를 꼭 받는다 (길이 없는 chunked 본문으로 상한을 건너뛰지 못하게).
        is_upload = request.url.path == "/api/admin/redata/upload"
        if is_upload and not request.headers.get("content-length"):
            return JSONResponse({"detail": "파일 크기를 알 수 없습니다."}, status_code=411)
        if size > (61 * 1024 * 1024 if is_upload else MAX_BODY_ADMIN if is_admin_path else MAX_BODY):
            return JSONResponse({"detail": "요청이 너무 큽니다."}, status_code=413)
        if not is_admin_path:
            raw = request.client.host if request.client else ""
            ip, _ = settings_store.client_ip(raw, dict(request.headers))
            if _too_many_writes(settings_store.rate_key(ip) or raw or "-"):
                return JSONResponse({"detail": "요청이 너무 잦습니다. 잠시 후 다시 시도해 주세요."}, status_code=429)
        site = request.headers.get("sec-fetch-site", "")
        one_click = request.url.path == "/api/unsubscribe/one-click"  # 메일 앱의 원클릭 수신 거부 (토큰이 열쇠, subscribe.py)
        if not one_click and (request.headers.get("x-requested-with") != "zipgenie" or site not in ("", "same-origin", "none")):
            # 403 이 아니라 428 — 관리 화면은 403 을 '관리자 아님'으로 보고 토큰 입력 화면으로 넘어가 버려서,
            # 이 헤더가 없는 예전 화면(배포 전에 열어 둔 탭)에서는 저장이 조용히 안 되는 것처럼 보였다 (2026-10-29).
            return JSONResponse({"detail": "화면이 예전 버전입니다. 새로고침(F5)한 뒤 다시 시도해 주세요."}, status_code=428)
    response = await call_next(request)
    for k, v in _SECURITY_HEADERS.items():
        response.headers.setdefault(k, v)
    # 모두에게 같은 공개 자료는 브라우저가 1분 동안 다시 쓰게 — 화면을 오갈 때 같은 요청을 줄인다 (2026-11-02 동시 접속 대비).
    # 사람마다 다른 응답(/api/me·/api/home·/api/home/mine·/api/notes 등)은 넣지 않는다.
    if request.method == "GET" and response.status_code == 200 and request.url.path in _SHARED_GET:
        response.headers["Cache-Control"] = "public, max-age=60"
    if request.headers.get("x-forwarded-proto") == "https" or request.headers.get("tailscale-funnel-request"):
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
    return response


def _gate_blocked(request: Request) -> bool:
    """둘러보기가 끝났고 로그인·관리자도 아니면 True. DB 를 읽으므로 작업 스레드에서 부른다."""
    from api.deps import COOKIE as VISITOR_COOKIE, is_admin
    from pipeline import accounts, engage, gate
    cookie_raw, _ = engage.check_cookie(request.cookies.get(VISITOR_COOKIE))
    raw, _ = accounts.resolve(cookie_raw)  # 기기 로그인 값 → 계정 raw
    if gate.logged_in(raw):
        return False
    ip, _ = settings_store.client_ip(request.client.host if request.client else None, dict(request.headers))
    return gate.left(request.cookies.get(gate.COOKIE), settings_store.rate_key(ip)) <= 0 and not is_admin(request)


def _new_trial_cookie(request: Request) -> str:
    from pipeline import gate
    ip, _ = settings_store.client_ip(request.client.host if request.client else None, dict(request.headers))
    return gate.new_cookie(settings_store.rate_key(ip))


@app.middleware("http")
async def _trial_gate(request: Request, call_next):
    """1분 둘러보기 뒤 메일 로그인 요구 (pipeline/gate.py, 2026-11-02). 관리자·열어 둔 API·화면(HTML)은 막지 않는다.
    판정에 DB 를 읽으므로 작업 스레드에서 한다 (2026-11-03) — 예전엔 이벤트 루프에서 바로 읽어, 배치가 DB 쓰기 잠금을 쥐고 있으면
    그 프로세스의 모든 요청이 최대 15초 멈췄다."""
    from starlette.concurrency import run_in_threadpool
    from pipeline import gate
    path = request.url.path
    is_api = path.startswith("/api/")
    if is_api and not path.startswith("/api/admin/") and not gate.is_open(path):
        if await run_in_threadpool(_gate_blocked, request):
            return JSONResponse({"detail": {"message": "계속 이용하려면 메일 인증(로그인)이 필요해요. 1분이면 끝나요.", "login_required": True}},
                                status_code=401)
    response = await call_next(request)
    # 둘러보기 쿠키는 API 응답과 화면(HTML) 응답에 심는다 — 화면을 받을 때 먼저 심어 두면 첫 API 요청들이 쿠키 없이 와서
    # IP 의 하루 둘러보기 수를 여러 개 쓰지 않는다
    # 서버가 그린 공유 페이지(/n/ 노트·/s/·/r/)는 둘러보기를 시작하지 않는다 — 공유받은 글을 읽다가 '이어 보기'를 누르자마자 막히지 않게 (2026-11-03)
    is_html = (request.method == "GET" and response.headers.get("content-type", "").startswith("text/html")
               and not path.startswith(("/n/", "/s/", "/r/", "/m/")))
    if (is_api or is_html) and response.status_code < 400 and gate.first_seen(request.cookies.get(gate.COOKIE)) is None:
        response.set_cookie(gate.COOKIE, await run_in_threadpool(_new_trial_cookie, request), max_age=365 * 24 * 3600, httponly=True,
                            samesite="lax", secure=request.url.scheme == "https" or bool(request.headers.get("tailscale-funnel-request"))
                            or request.headers.get("x-forwarded-proto") == "https",  # Cloudflare Tunnel 등 다른 프록시도 (2026-11-04)
                            path="/")
    return response


# ───────── 관리 API 접속기록 (2026-11-03 ISMS-P 2.9.4 — pipeline/admin_auth.py) ─────────
# 관리 요청을 실제로 처리하는 서버(관리·배치 서버 5031, 또는 넘기지 않는 개발 서버)에서 남긴다. 403(관리자 아님)도 남긴다.
# 실행 로그 독이 몇 초마다 부르는 작업 상태 조회(GET /api/admin/jobs…)는 빼고, 다운로드·전체 보기 사유는 그 API 가 직접 남긴다.
_AUDIT_SKIP_GET = ("/api/admin/jobs",)


@app.middleware("http")
async def _admin_audit(request: Request, call_next):
    path = request.url.path
    if not path.startswith("/api/admin/") or path == "/api/admin/audit/event" or             (request.method == "GET" and path.startswith(_AUDIT_SKIP_GET)):
        return await call_next(request)
    response = await call_next(request)
    from starlette.concurrency import run_in_threadpool
    from pipeline import admin_auth
    ip, _ = settings_store.client_ip(request.client.host if request.client else None, dict(request.headers))
    actor = getattr(request.state, "admin_actor", "-")
    try:
        await run_in_threadpool(admin_auth.audit, actor, ip, request.method, path, response.status_code, request.url.query)
    except Exception:  # noqa: BLE001 - 기록 실패가 관리 작업을 막지 않게 (로그에는 남긴다)
        log.exception("관리 접속기록 실패: %s %s", request.method, path)
    return response


# ───────── 관리 요청을 관리·배치 서버로 넘기기 (2026-11-02 동시 접속 대비) ─────────
# 공개 서버를 여러 프로세스로 돌리면 관리 화면의 작업 상태·실행 로그(메모리)가 프로세스마다 갈라진다. 그래서 공개 서버(5030, 여러 프로세스)는
# /api/admin/* 를 관리·배치 서버(5031, 프로세스 1개, 예약 작업 실행)로 그대로 넘긴다. Host·쿠키·Funnel 헤더·X-Forwarded-For 를 그대로 넘기므로
# 관리자 판정(로컬 브라우저·관리 토큰)은 관리·배치 서버가 지금과 같은 규칙으로 한다. ZIPGENIE_ADMIN_UPSTREAM 이 없으면 넘기지 않는다.
_ADMIN_UPSTREAM = os.environ.get("ZIPGENIE_ADMIN_UPSTREAM", "").rstrip("/")
_HOP = {"connection", "keep-alive", "transfer-encoding", "te", "upgrade", "proxy-authorization", "proxy-authenticate", "trailer", "content-length"}
_admin_client = None


@app.middleware("http")
async def _admin_proxy(request: Request, call_next):
    if not _ADMIN_UPSTREAM or not request.url.path.startswith("/api/admin/"):
        return await call_next(request)
    global _admin_client
    import httpx
    from fastapi.responses import Response as _Resp
    if _admin_client is None:
        _admin_client = httpx.AsyncClient(base_url=_ADMIN_UPSTREAM, timeout=httpx.Timeout(600.0, connect=5.0))
    # 관리자가 아니면 본문을 읽기 전에 돌려보낸다 (2026-11-03) — 이 미들웨어는 _guard 의 크기 상한보다 먼저 돌아,
    # 익명 요청이 거대한(길이 머리글 없는) 본문으로 공개 서버 메모리를 채울 수 있었다. 최종 판정은 관리·배치 서버가 다시 한다.
    from starlette.concurrency import run_in_threadpool
    from api.deps import _client_ip, _token_blocked, is_admin
    if request.headers.get("x-admin-token") and await run_in_threadpool(lambda: _token_blocked(_client_ip(request)[0] or "?")):
        return JSONResponse({"detail": "관리 토큰 오류가 잦아 잠시 차단되었습니다. 10분 뒤 다시 시도해 주세요."}, status_code=429)
    if not await run_in_threadpool(is_admin, request):
        from pipeline import admin_auth
        ip, _ = settings_store.client_ip(request.client.host if request.client else None, dict(request.headers))
        await run_in_threadpool(admin_auth.audit, "-", ip, request.method, request.url.path, 403, request.url.query)  # 권한 없는 접근 시도도 남긴다
        return JSONResponse({"detail": "관리자만 쓸 수 있습니다"}, status_code=403)
    limit = 61 * 1024 * 1024 if request.url.path == "/api/admin/redata/upload" else MAX_BODY_ADMIN
    try:
        if int(request.headers.get("content-length") or 0) > limit:
            return JSONResponse({"detail": "요청이 너무 큽니다."}, status_code=413)
    except ValueError:
        return JSONResponse({"detail": "요청 길이가 올바르지 않습니다."}, status_code=400)
    body = bytearray()
    async for chunk in request.stream():  # 길이 머리글 없이 오는 본문도 상한까지만 받는다
        body += chunk
        if len(body) > limit:
            return JSONResponse({"detail": "요청이 너무 큽니다."}, status_code=413)
    headers = [(k, v) for k, v in request.headers.items() if k.lower() not in _HOP]
    try:
        r = await _admin_client.request(request.method, request.url.path, params=request.url.query or None,
                                        headers=headers, content=bytes(body))
    except httpx.HTTPError:
        return JSONResponse({"detail": "관리·배치 서버(5031)에 연결할 수 없습니다. start-zipbomi.bat 창을 확인해 주세요."}, status_code=502)
    out = [(k, v) for k, v in r.headers.multi_items() if k.lower() not in _HOP and k.lower() != "content-encoding"]
    resp = _Resp(content=r.content, status_code=r.status_code)
    for k, v in out:
        resp.headers.append(k, v)
    return resp


# AI 학습·수집용 크롤러 — 자기 이름(User-Agent)을 밝히는 것만 막는다. 검색 로봇(Google·네이버·다음)과 링크 미리보기(카카오·페이스북)는 그대로 둔다.
# 가장 바깥에 둔다(맨 마지막에 선언) — 로봇이 둘러보기 쿠키·IP 한도(하루 5번)를 쓰지 못하게 문턱보다 먼저 거른다.
# 이름을 속이는 프로그램은 못 막으므로 진짜 방어는 아래 로그인 문턱(데이터 API 401)과 Cloudflare 봇 차단이다. robots.txt 에도 같은 목록 (app/web.py AI_BOTS).
from app.web import AI_BOTS  # noqa: E402
_AI_BOT_RE = re.compile("|".join(re.escape(b) for b in AI_BOTS), re.I)


@app.middleware("http")
async def _no_ai_crawlers(request: Request, call_next):
    if request.url.path != "/robots.txt" and _AI_BOT_RE.search(request.headers.get("user-agent", "")):
        return JSONResponse({"detail": "AI 학습·수집용 접근은 허용하지 않습니다."}, status_code=403)
    return await call_next(request)


from fastapi.exceptions import RequestValidationError  # noqa: E402


@app.exception_handler(RequestValidationError)
async def _bad_input(request: Request, exc: RequestValidationError) -> JSONResponse:
    """형식이 틀린 요청 — 보낸 값(input)을 그대로 되돌려 주지 않고 위치·이유만 (2026-11-02 보안 점검)."""
    return JSONResponse({"detail": [{"loc": e.get("loc"), "msg": e.get("msg")} for e in exc.errors()[:10]]}, status_code=422)


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception):
    log.exception("처리되지 않은 오류: %s %s", request.method, request.url.path)
    return JSONResponse({"detail": "서버 오류가 났습니다. 잠시 후 다시 시도해 주세요."}, status_code=500)  # 내부 정보 비노출


# 1) API 라우터 자동 등록
from api import routers as _routers_pkg  # noqa: E402

for mod in pkgutil.iter_modules(_routers_pkg.__path__):
    m = importlib.import_module(f"api.routers.{mod.name}")
    if hasattr(m, "router"):
        app.include_router(m.router, prefix="/api")
    if hasattr(m, "root_router"):  # 접두어 없는 공개 경로 (메일 링크 /m/… — api/routers/mail_link.py)
        app.include_router(m.root_router)

# 2) 검색·공유·PDF 서버 렌더링 페이지
from app import web  # noqa: E402

for route in web.ROUTES:
    app.router.routes.append(route)

# 3) 정적 파일 — 공유 이미지 주소(/app/static/og/…)는 Streamlit 판과 같게 유지
class _CachedStatic(StaticFiles):
    """Cache-Control 을 붙인 정적 파일 — 예전엔 ETag 만 있어 다시 방문할 때마다 파일마다 확인 요청을 보냈다."""

    def __init__(self, *a, cache: str, **kw):
        super().__init__(*a, **kw)
        self._cache_header = cache

    def file_response(self, *a, **kw):
        resp = super().file_response(*a, **kw)
        resp.headers["Cache-Control"] = self._cache_header
        return resp


app.mount("/app/static", _CachedStatic(directory=ROOT / "static", cache="public, max-age=86400"), name="static")
if (DIST / "assets").exists():
    # 빌드 파일은 이름에 내용 해시가 들어가 바뀌면 이름도 바뀐다 → 1년 고정 캐시
    app.mount("/assets", _CachedStatic(directory=DIST / "assets", cache="public, max-age=31536000, immutable"), name="assets")


# 4) SPA — 나머지 GET 은 React index.html. 공유 미리보기(제목·설명·썸네일)는 응답 때 페이지별로 넣는다 (app/og_meta.py)
from app import og_meta  # noqa: E402


@app.get("/{path:path}", include_in_schema=False)
async def spa(path: str):
    if path.startswith("api/"):
        raise HTTPException(status_code=404)
    if path == "favicon.ico":  # 오래된 브라우저·검색 로봇이 찾는 주소 — 404 대신 SVG 아이콘으로 (2026-11-03)
        icon = DIST / "favicon.svg"
        if icon.is_file():
            return FileResponse(icon, media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=86400"})
    file = DIST / path
    if path and file.is_file() and DIST in file.resolve().parents:
        if path == "sw.js":  # 서비스 워커는 하루 캐시하면 새 버전이 늦게 퍼진다 — 항상 확인하게 (PWA, 2026-11-05)
            return FileResponse(file, media_type="text/javascript", headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"})
        if path == "manifest.webmanifest":
            return FileResponse(file, media_type="application/manifest+json", headers={"Cache-Control": "public, max-age=86400"})
        return FileResponse(file, headers={"Cache-Control": "public, max-age=86400"})  # 로고·파비콘 등
    html = _index_html()
    if html is None:
        return HTMLResponse("<h1>집보미</h1><p>프론트엔드를 아직 빌드하지 않았습니다: <code>cd frontend && npm run build</code></p>", status_code=503)
    # 앱에 없는 경로는 index.html 을 그대로 주되 404 로 — React 가 '페이지 없음' 화면을 그리고 검색 엔진은 soft 404 로 세지 않는다
    status = 200 if path.split("/", 1)[0] in _APP_ROUTES else 404
    return HTMLResponse(og_meta.render(html, path), status_code=status, headers={"Cache-Control": "no-cache"})


# App.tsx 가 선언한 라우트의 첫 경로 조각 ("" = 홈). og_meta.PAGES 에 있는 것은 자동으로 들어간다.
_APP_ROUTES = {p.strip("/") for p in og_meta.PAGES} | {
    "", "home", "notes", "today", "lab", "ask", "about", "type", "terms", "diagnosis", "habit", "career",
    "letter", "refer", "confirm", "unsubscribe", "privacy", "admin", "deals", "calc", "map", "me", "my-homes", "now", "calendar", "my", "login"}


_index: dict = {}


def _index_html() -> str | None:
    """dist/index.html — 다시 빌드하면 바로 반영되도록 수정 시각이 바뀔 때만 다시 읽는다 (페이지마다 디스크를 읽지 않게)."""
    index = DIST / "index.html"
    try:
        mtime = index.stat().st_mtime_ns
    except FileNotFoundError:
        return None
    if _index.get("mtime") != mtime:
        _index.update(mtime=mtime, html=index.read_text(encoding="utf-8"))
    return _index["html"]
