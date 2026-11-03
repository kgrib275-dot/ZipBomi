"""라우터 공용 — 노트 카드 직렬화, 마크다운 → HTML, 쿼리 문자열 목록 파싱, 공유 캐시."""
from __future__ import annotations

import threading
import time

from app.web import md_html  # 노트 본문 형식(### 제목, 목록, **굵게**)만 HTML 로 — 이스케이프 포함
from pipeline import industry, note_format, profile

CARD_KEYS = ("id", "title", "category", "kind", "summary", "published", "source", "tags", "audiences", "url")


def note_card(n: dict, **extra) -> dict:
    out = {k: n.get(k) for k in CARD_KEYS}
    out["industries"] = industry.of(n)
    out["regions"] = profile.note_regions(n)    # 시군구 코드 (notes.regions)
    out["audience"] = profile.note_audience(n)  # 대상 유형 키 (notes.audience)
    out["format"] = note_format.of(n)  # brief / deep / data (Phase 4)
    out.update(extra)
    return out


def csv_list(raw: str | None) -> list[str]:
    return [x.strip() for x in (raw or "").split(",") if x.strip()]


_cache: dict = {}
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def cached(key: str, fn, ttl: float):
    """모든 방문자가 같은 값을 ttl 초 동안 나눠 쓴다.

    만료된 순간 동시에 들어온 요청이 모두 같은 계산을 하지 않게 한 요청만 다시 계산한다 (1만 명 복사본 실측: 오늘의 부동산
    빈 캐시 + 동시 20명 → 24초). 그동안 다른 요청은 직전 값이 있으면 그걸 바로 받고, 없으면(처음) 계산이 끝나길 기다린다."""
    hit = _cache.get(key)
    now = time.monotonic()
    if hit and now - hit[0] < ttl:
        return hit[1]
    with _locks_guard:
        lock = _locks.setdefault(key, threading.Lock())
    if hit:
        # 만료된 값이 있으면 그 값을 바로 주고 다시 계산은 뒤에서 한다 (2026-11-03) — 예전엔 만료 뒤 처음 온 방문자가
        # 계산이 끝날 때까지(지도 시세 1.5초 등) 기다렸다. 이미 누가 계산 중이면 그냥 직전 값.
        if lock.acquire(blocking=False):
            threading.Thread(target=_refresh, args=(key, fn, lock), daemon=True, name=f"cache-{key[:30]}").start()
        return hit[1]
    lock.acquire()
    try:
        hit = _cache.get(key)
        if hit and time.monotonic() - hit[0] < ttl:
            return hit[1]
        val = fn()
        _cache[key] = (time.monotonic(), val)
        return val
    finally:
        lock.release()


def _refresh(key: str, fn, lock: threading.Lock) -> None:
    try:
        _cache[key] = (time.monotonic(), fn())
    except Exception:  # noqa: BLE001 - 실패하면 직전 값을 계속 쓰고 다음 만료 때 다시
        import logging
        logging.getLogger("zipgenie.cache").exception("캐시 다시 계산 실패: %s", key)
    finally:
        lock.release()


def cached_set(key: str, val) -> None:
    """계산해 둔 값을 바로 캐시에 넣는다 (방금 바뀐 값을 다음 요청들이 쓰게)."""
    _cache[key] = (time.monotonic(), val)


def prune(prefix: str, keep: set[str]) -> None:
    """날짜별 키처럼 계속 늘어나는 캐시 키 정리."""
    for k in [k for k in _cache if k.startswith(prefix) and k not in keep]:
        _cache.pop(k, None)
        _locks.pop(k, None)


__all__ = ["md_html", "note_card", "csv_list", "cached", "cached_set", "prune"]
