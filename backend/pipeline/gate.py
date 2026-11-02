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
    """방문자 쿠키 원값이 로그인 계정인지 — 요청마다 DB 를 읽지 않게 30초 기억."""
    if not raw:
        return False
    now = time.monotonic()
    hit = _acc_cache.get(raw)
    if hit and now - hit[0] < 30:
        return hit[1]
    ok = accounts.by_raw(raw) is not None
    if len(_acc_cache) > 20000:
        _acc_cache.clear()
    _acc_cache[raw] = (now, ok)
    return ok


def forget(raw: str | None) -> None:
    """로그인·로그아웃 직후 — 기억한 판정을 지운다."""
    if raw:
        _acc_cache.pop(raw, None)


_ip_first: dict[str, float] = {}
_SQL = "CREATE TABLE IF NOT EXISTS trial_ip (ip TEXT PRIMARY KEY, first_at REAL NOT NULL)"


def _ip_first_seen(ip_key: str, now: float) -> float:
    """IP 처음 방문 시각 — 프로세스가 여러 개여도 같은 값이 되게 DB 에 둔다(메모리는 앞단 캐시). 하루 지나면 새로."""
    t0 = _ip_first.get(ip_key)
    if t0 is not None and now - t0 <= 86400:
        return t0
    from . import db
    c = db.connect()
    try:
        c.execute(_SQL)
        c.execute("DELETE FROM trial_ip WHERE ip=? AND first_at < ?", (ip_key, now - 86400))
        c.execute("INSERT OR IGNORE INTO trial_ip (ip, first_at) VALUES (?, ?)", (ip_key, now))
        row = c.execute("SELECT first_at FROM trial_ip WHERE ip=?", (ip_key,)).fetchone()
        c.commit()
        t0 = float(row[0]) if row else now
    except Exception:  # noqa: BLE001 - DB 가 바쁘면 메모리 값으로
        t0 = now
    finally:
        c.close()
    if len(_ip_first) > 50000:
        _ip_first.clear()
    _ip_first[ip_key] = t0
    return t0


def left(cookie: str | None, ip_key: str | None = None) -> int:
    """남은 둘러보기 초. 쿠키 시각과 IP 처음 시각 중 이른 쪽 — 쿠키를 지워도 같은 IP 면 1분이 새로 생기지 않는다."""
    now = time.time()
    ts = first_seen(cookie)
    if ip_key:
        t0 = _ip_first_seen(ip_key, now)
        ts = min(ts, t0) if ts is not None else t0
    if ts is None:
        return TRIAL_SEC
    return max(0, TRIAL_SEC - int(now - ts))


def is_open(path: str) -> bool:
    return any(path == p.rstrip("/") or path.startswith(p) for p in OPEN)
