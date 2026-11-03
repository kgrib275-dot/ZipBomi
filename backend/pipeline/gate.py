"""1분 둘러보기 후 메일 로그인 요구 (2026-11-02).

처음 들어온 시각을 서명한 쿠키(zgt)로 기억한다. 로그인하지 않은 방문자는 그 뒤 TRIAL_SEC 가 지나면 공개 API 가
401 {login_required} 를 돌려주고, 화면은 소개 페이지로 옮겨 로그인 창을 띄운다(api.ts·Layout.tsx).
- 관리자(이 PC·관리 토큰)는 막지 않는다.
- 소개·처리방침·로그인·구독 확인/해지·문의·방문 기록처럼 로그인 전에 꼭 필요한 API 는 늘 연다(OPEN).
- 화면(HTML)·공유 미리보기·사이트맵은 막지 않는다 — 검색·공유 미리보기는 그대로.
"""
from __future__ import annotations

import hmac
import os
import time

from . import accounts, engage

TRIAL_SEC = int(os.environ.get("ZIPGENIE_TRIAL_SEC", "60") or 60)  # 시험(부하 테스트)에서만 늘린다
COOKIE = "zgt"
OPEN = ("/api/me", "/api/auth/", "/api/about", "/api/privacy", "/api/site", "/api/contact", "/api/engage", "/api/re/ping",
        "/api/subscribe", "/api/unsubscribe", "/api/letter", "/api/refer")
_acc_cache: dict[str, tuple[float, bool]] = {}


def _sig(ts: int) -> str:
    return engage._sig(f"trial:{ts}")


def make_cookie(ts: int | None = None) -> str:
    ts = int(ts or time.time())
    return f"{ts}.{_sig(ts)}"


def first_seen(cookie: str | None) -> int | None:
    """서명이 맞는 처음 방문 시각, 없거나 위조면 None."""
    if not isinstance(cookie, str) or "." not in cookie:
        return None
    t, _, s = cookie.partition(".")
    if not t.isdigit() or not hmac.compare_digest(s, _sig(int(t))):
        return None
    ts = int(t)
    return ts if ts <= time.time() + 60 else None


def logged_in(raw: str | None) -> bool:
    """방문자 원값(accounts.resolve 를 거친 값)이 로그인 계정인지 — 요청마다 DB 를 읽지 않게 "로그인됨"만 10초 기억.
    예전엔 "로그인 안 됨"도 30초 기억해, 로그인을 처리하지 않은 다른 프로세스가 로그인 직후 최대 30초 동안 로그인 창을 다시 띄웠다 (2026-11-03)."""
    if not raw:
        return False
    now = time.monotonic()
    hit = _acc_cache.get(raw)
    if hit and now - hit[0] < 10:
        return True
    ok = accounts.by_raw(raw) is not None
    if len(_acc_cache) > 20000:
        _acc_cache.clear()
    if ok:
        _acc_cache[raw] = (now, True)
    else:
        _acc_cache.pop(raw, None)
    return ok


def forget(raw: str | None) -> None:
    """로그인·로그아웃 직후 — 기억한 판정을 지운다."""
    if raw:
        _acc_cache.pop(raw, None)


_SQL = "CREATE TABLE IF NOT EXISTS trial_ip (ip TEXT PRIMARY KEY, first_at REAL NOT NULL)"
# 같은 IP 에서 하루에 새로 시작할 수 있는 둘러보기 수 (2026-11-03). 예전엔 IP 하나에 1분 하나뿐이라, 사무실·통신사 공유 IP 뒤의
# 두 번째 사람은 들어오자마자 로그인 화면을 봤다. 이제 쿠키(zgt)를 새로 줄 때만 IP 를 세고, 하루 이 수를 넘으면 그 IP 의 첫 시각으로 준다
# (쿠키를 지워 가며 1분을 계속 새로 받는 것은 여전히 막힌다).
IP_TRIALS_PER_DAY = int(os.environ.get("ZIPGENIE_IP_TRIALS", "20") or 20)


def _ip_trials(ip_key: str, now: float, count: bool) -> tuple[float, int]:
    """(이 IP 의 오늘 첫 둘러보기 시각, 오늘 새로 준 둘러보기 수). count=True 면 하나 더 센다. 프로세스가 여러 개여도 같은 값이 되게 DB 에 둔다.
    하루 지나면 새로."""
    from . import db
    c = db.connect()
    try:
        c.execute(_SQL)
        if "n" not in {r[1] for r in c.execute("PRAGMA table_info(trial_ip)")}:
            try:
                c.execute("ALTER TABLE trial_ip ADD COLUMN n INTEGER NOT NULL DEFAULT 0")
            except Exception:  # noqa: BLE001 - 다른 프로세스가 먼저 넣었다
                pass
        c.execute("DELETE FROM trial_ip WHERE ip=? AND first_at < ?", (ip_key, now - 86400))
        c.execute("INSERT OR IGNORE INTO trial_ip (ip, first_at, n) VALUES (?, ?, 0)", (ip_key, now))
        if count:
            c.execute("UPDATE trial_ip SET n = n + 1 WHERE ip=?", (ip_key,))
        row = c.execute("SELECT first_at, n FROM trial_ip WHERE ip=?", (ip_key,)).fetchone()
        c.commit()
        return (float(row[0]), int(row[1])) if row else (now, 0)
    except Exception:  # noqa: BLE001 - DB 가 바쁘면 새 방문자로 (제한이 잠깐 느슨해질 뿐)
        return now, 0
    finally:
        c.close()


def new_cookie(ip_key: str | None) -> str:
    """처음 온 브라우저에 줄 둘러보기 쿠키. 이 IP 가 오늘 IP_TRIALS_PER_DAY 개를 넘게 받았으면 이미 끝난 둘러보기로 준다."""
    now = time.time()
    if ip_key:
        _, n = _ip_trials(ip_key, now, count=True)
        if n > IP_TRIALS_PER_DAY:
            return make_cookie(int(now) - TRIAL_SEC)
    return make_cookie(int(now))


def left(cookie: str | None, ip_key: str | None = None) -> int:
    """남은 둘러보기 초. 쿠키가 있으면 쿠키 시각으로. 쿠키가 없으면(첫 요청·쿠키를 받지 않는 클라이언트) 이 IP 가 오늘 둘러보기를
    다 썼는지로 본다 — 쿠키를 지워도 같은 IP 에서 무한히 새로 받지는 못한다."""
    now = time.time()
    ts = first_seen(cookie)
    if ts is None and ip_key:
        _, n = _ip_trials(ip_key, now, count=False)
        if n >= IP_TRIALS_PER_DAY:
            return 0
    if ts is None:
        return TRIAL_SEC
    return max(0, TRIAL_SEC - int(now - ts))


def is_open(path: str) -> bool:
    return any(path == p.rstrip("/") or path.startswith(p) for p in OPEN)
