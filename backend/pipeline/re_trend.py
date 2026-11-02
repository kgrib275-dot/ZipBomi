"""관심 단지·지역 드릴다운 집계 (Phase 2, 2026-11-02) — 저장된 실거래 표만 읽는다 (공공 API·LLM 호출 없음).

- 원천: rtms_apt_trade(아파트 매매) · rtms_apt_rent(아파트 전월세, 전세 = 월세 0 계약). 해제 신고된 거래는 뺀다.
  rtms_apt_trade 에 그 시군구 행이 하나도 없으면 화면 조회 캐시 re_apt_trade(molit.py)를 대신 읽는다.
- 단지 구분: (시군구 코드, 법정동 umd, 단지명 name). 지번이 있으면 같이 맞춘다(같은 동에 같은 이름 단지가 둘인 경우).
- 평형 구간: 전용 60㎡ 이하(59형) · 60~85㎡(84형) · 85㎡ 초과(대형).
- 노트 표시: 거래량이 전월 대비 ±30% 이상 바뀐 달(전월 건수 MIN_PREV 이상일 때만 — 1건→2건 같은 잡음 제외)에
  그 달 그 지역(시군구 코드·동·단지 이름)을 다룬 노트, 없으면 그 달의 전국 정책 노트를 붙인다.
  단지 상세는 그 시군구 또는 전국 단위 정책 노트를 게시일 달에 붙인다.
- 결과는 프로세스 안에서 10분 캐시 (키 수 상한 있음).
"""
from __future__ import annotations

import json
import statistics
import threading
import time
from datetime import date, timedelta

from pipeline import db, profile, re_store, regions_kr

SOURCE = "국토교통부 실거래가 신고 자료"
PYEONG = 3.305785
POLICY_CAT = "정책·세금·대출"
BANDS = (("s", "전용 59㎡형", 0.0, 60.0), ("m", "전용 84㎡형", 60.0, 85.0), ("l", "대형(85㎡ 초과)", 85.0, 1e9))
VOLUME_SWING = 0.30
MIN_PREV = 3
TTL = 600
_MAX_KEYS = 600

_cache: dict[str, tuple[float, object]] = {}
_lock = threading.Lock()


def _cached(key: str, fn):
    k = f"{db.DB_PATH}|{key}"
    now = time.monotonic()
    hit = _cache.get(k)
    if hit and now - hit[0] < TTL:
        return hit[1]
    val = fn()
    with _lock:
        if len(_cache) >= _MAX_KEYS:
            for old in sorted(_cache, key=lambda x: _cache[x][0])[: _MAX_KEYS // 4]:
                _cache.pop(old, None)
        _cache[k] = (now, val)
    return val


def clear_cache() -> None:
    _cache.clear()


def band_of(area: float | None) -> str | None:
    if not area or area <= 0:
        return None
    for k, _, lo, hi in BANDS:
        if lo < area <= hi:
            return k
    return None


BAND_LABEL = {k: label for k, label, _, _ in BANDS}


# ───────────────────────── 원천 행 ─────────────────────────

def _months(end: str, n: int) -> list[str]:
    return [re_store.shift_ymd(end, -i) for i in range(n - 1, -1, -1)]


def _trade_rows(lawd: str, start: str, dong: str = "", apt: str = "", jibun: str = "") -> list[dict]:
    """매매 행 {ymd, date, umd, name, jibun, area, amount} — 해제 제외."""
    re_store.ensure_schema()
    where, params = ["lawd_cd = ?", "deal_ymd >= ?", "cancelled = 0", "amount > 0"], [lawd, start]
    if dong:
        where.append("umd = ?")
        params.append(dong)
    if apt:
        where.append("name = ?")
        params.append(apt)
    if jibun:
        where.append("jibun = ?")
        params.append(jibun)
    conn = db.connect()
    try:
        rows = [{"ymd": r["deal_ymd"], "date": r["deal_date"] or "", "umd": r["umd"] or "", "name": r["name"] or "",
                 "jibun": r["jibun"] or "", "area": r["area"], "amount": r["amount"], "floor": r["floor"]}
                for r in conn.execute("SELECT deal_ymd, deal_date, umd, name, jibun, area, amount, floor FROM rtms_apt_trade "
                                      f"WHERE {' AND '.join(where)}", params)]
        if rows or conn.execute("SELECT 1 FROM rtms_apt_trade WHERE lawd_cd = ? LIMIT 1", (lawd,)).fetchone():
            return rows
        # 배치 표가 빈 시군구 — 화면 조회 캐시(re_apt_trade)
        try:
            cache = conn.execute("SELECT deal_ymd, rows FROM re_apt_trade WHERE lawd_cd = ? AND deal_ymd >= ?", (lawd, start)).fetchall()
        except Exception:  # noqa: BLE001 - 캐시 표가 아직 없으면 자료 없음
            return []
    finally:
        conn.close()
    out = []
    for r in cache:
        try:
            items = json.loads(r["rows"])
        except (TypeError, ValueError):
            continue
        for x in items:
            if x.get("cancelled") or not x.get("amount"):
                continue
            if (dong and x.get("dong") != dong) or (apt and x.get("apt") != apt) or (jibun and x.get("jibun") != jibun):
                continue
            out.append({"ymd": r["deal_ymd"], "date": x.get("date") or "", "umd": x.get("dong") or "", "name": x.get("apt") or "",
                        "jibun": x.get("jibun") or "", "area": x.get("area"), "amount": x["amount"], "floor": x.get("floor")})
    return out


def _jeonse_rows(lawd: str, start: str, dong: str = "", apt: str = "", jibun: str = "") -> list[dict]:
    re_store.ensure_schema()
    where, params = ["lawd_cd = ?", "deal_ymd >= ?", "cancelled = 0", "deposit > 0", "COALESCE(monthly_rent, 0) = 0"], [lawd, start]
    for col, v in (("umd", dong), ("name", apt), ("jibun", jibun)):
        if v:
            where.append(f"{col} = ?")
            params.append(v)
    conn = db.connect()
    try:
        return [{"ymd": r["deal_ymd"], "date": r["deal_date"] or "", "area": r["area"], "deposit": r["deposit"]}
                for r in conn.execute(f"SELECT deal_ymd, deal_date, area, deposit FROM rtms_apt_rent WHERE {' AND '.join(where)}", params)]
    finally:
        conn.close()


def _fetched_at(lawd: str) -> str | None:
    conn = db.connect()
    try:
        r = conn.execute("SELECT MAX(fetched_at) AS f FROM re_fetch_log WHERE dataset = 'apt_trade' AND lawd_cd = ?", (lawd,)).fetchone()
        return r["f"] if r else None
    except Exception:  # noqa: BLE001
        return None
    finally:
        conn.close()


def _pp(r: dict) -> float | None:
    return r["amount"] / r["area"] * PYEONG if r.get("area") else None


def _median(vals) -> int | None:
    v = [x for x in vals if x]
    return round(statistics.median(v)) if v else None


def _pct(cur: float | None, prev: float | None) -> float | None:
    return round((cur - prev) / prev * 100, 1) if cur and prev else None


# ───────────────────────── 노트 고르기 ─────────────────────────

_notes_cache: dict = {}


def _notes() -> list[dict]:
    hit = _notes_cache.get(str(db.DB_PATH))
    if hit and time.monotonic() - hit[0] < 120:
        return hit[1]
    notes = db.notes("published")
    _notes_cache[str(db.DB_PATH)] = (time.monotonic(), notes)
    return notes


def _brief(n: dict, scope: str) -> dict:
    return {"id": n["id"], "title": n["title"], "summary": (n.get("summary") or "")[:220], "category": n.get("category"),
            "kind": n.get("kind"), "published": (n.get("published") or "")[:10], "scope": scope}


def _is_policy(n: dict) -> bool:
    return n.get("category") == POLICY_CAT or n.get("kind") == "정책 해설"


def _region_score(n: dict, lawd: str, words: list[str]) -> float:
    text = f"{n.get('title', '')} {n.get('summary', '')}"
    s = 0.0
    if any(w and w in text for w in words):
        s += 3
    if lawd in profile.note_regions(n):
        s += 2
    return s


def pick_month_note(lawd: str, ymd: str, words: list[str]) -> dict | None:
    """그 달 그 지역을 다룬 노트 하나, 없으면 그 달의 전국 정책 노트."""
    month = f"{ymd[:4]}-{ymd[4:]}"
    pool = [n for n in _notes() if (n.get("published") or "").startswith(month)]
    scored = [(s, n) for n in pool if (s := _region_score(n, lawd, words)) > 0]
    if scored:
        scored.sort(key=lambda x: (x[0], x[1].get("category") == "시장·시세", x[1].get("published") or ""), reverse=True)
        return _brief(scored[0][1], "region")
    national = [n for n in pool if _is_policy(n) and not profile.note_regions(n)]
    return _brief(national[0], "national") if national else None


def policy_markers(lawd: str, months: list[str]) -> list[dict]:
    """단지 상세 — 그 시군구 또는 전국 단위 정책 노트를 게시 달에 (한 달에 하나, 지역 노트 우선)."""
    want = set(months)
    by: dict[str, tuple[int, dict]] = {}
    for n in _notes():
        ym = (n.get("published") or "")[:7].replace("-", "")
        if ym not in want or not _is_policy(n):
            continue
        regs = profile.note_regions(n)
        if regs and lawd not in regs:
            continue
        rank = 2 if regs else 1
        cur = by.get(ym)
        if not cur or rank > cur[0]:
            by[ym] = (rank, _brief(n, "region" if regs else "national"))
    return [{"ymd": ym, "kind": "policy", "note": v[1]} for ym, v in sorted(by.items())]


def notes_for(lawd: str, words: list[str], k: int = 3) -> list[dict]:
    """그 단지(이름) 또는 그 시군구를 언급한 최신 노트."""
    hits = [(s, n) for n in _notes() if (s := _region_score(n, lawd, words)) > 0]
    hits.sort(key=lambda x: (x[1].get("published") or "", x[0]), reverse=True)
    return [_brief(n, "region") for _, n in hits[:k]]


# ───────────────────────── 지역·단지 추이 ─────────────────────────

def _end_ymd() -> str:
    return re_store.this_ymd()


def region_trend(lawd: str, dong: str = "", apt: str = "", months: int = 24, markers: str = "volume", band: str = "") -> dict:
    """band(s/m/l): 그 평형 구간 거래만 — 단지 상세에서 59형·84형 가격이 한 선에 섞이지 않게."""
    months = max(6, min(int(months or 24), 36))
    band = band if band in BAND_LABEL else ""
    return _cached(f"trend|{lawd}|{dong}|{apt}|{months}|{markers}|{band}", lambda: _region_trend(lawd, dong, apt, months, markers, band))


def _region_trend(lawd: str, dong: str, apt: str, months: int, markers: str, band: str = "") -> dict:
    ms = _months(_end_ymd(), months)
    rows = _trade_rows(lawd, ms[0], dong, apt)
    if band:
        rows = [r for r in rows if band_of(r["area"]) == band]
    by: dict[str, list[dict]] = {}
    for r in rows:
        by.setdefault(r["ymd"], []).append(r)
    points = []
    for m in ms:
        rs = by.get(m, [])
        pps = [p for p in (_pp(r) for r in rs) if p]
        points.append({"ymd": m, "count": len(rs), "avg_pyeong": round(statistics.fmean(pps)) if pps else None,
                       "median": _median(r["amount"] for r in rs),
                       "partial": m >= re_store.shift_ymd(ms[-1], -1)})  # 신고 기한 안 — 건수가 더 늘 수 있음
    # 아래 단계 목록 (최근 12개월 건수 순)
    recent = [r for r in rows if r["ymd"] >= ms[-12]]
    children: list[dict] = []
    if not apt:
        key = "name" if dong else "umd"
        grp: dict[str, list[dict]] = {}
        for r in recent:
            if r[key]:
                grp.setdefault(r[key], []).append(r)
        for name, rs in sorted(grp.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:60]:
            pps = [p for p in (_pp(r) for r in rs) if p]
            children.append({"name": name, "count": len(rs), "avg_pyeong": round(statistics.fmean(pps)) if pps else None,
                             "dong": name if key == "umd" else dong,
                             "jibun": rs[0]["jibun"] if key == "name" else ""})
    words = [w for w in (apt, dong) if w and len(w) >= 2]
    marks: list[dict] = []
    if markers == "policy":
        marks = policy_markers(lawd, ms)
    else:
        settled = re_store.shift_ymd(ms[-1], -1)  # 이번 달·지난달은 신고 기한(계약 후 30일) 안이라 건수가 덜 찼다 — 표시 대상에서 뺀다
        for i in range(1, len(points)):
            if points[i]["ymd"] >= settled:
                continue
            prev, cur = points[i - 1]["count"], points[i]["count"]
            if prev >= MIN_PREV and abs(cur - prev) / prev >= VOLUME_SWING:
                marks.append({"ymd": points[i]["ymd"], "kind": "volume", "change_pct": round((cur - prev) / prev * 100, 1),
                              "note": pick_month_note(lawd, points[i]["ymd"], words)})
    dates = [r["date"] for r in rows if r["date"]]
    return {"lawd": lawd, "region": regions_kr.NAMES.get(lawd, lawd), "dong": dong, "apt": apt,
            "level": "apt" if apt else "dong" if dong else "sigungu", "band": band, "points": points, "children": children,
            "markers": marks, "total": len(rows), "as_of": max(dates) if dates else None, "fetched_at": _fetched_at(lawd),
            "source": SOURCE, "rule": f"전월 대비 거래량 ±{int(VOLUME_SWING * 100)}% 이상 (전월 {MIN_PREV}건 이상인 달)"}


def apt_summary(lawd: str, dong: str, apt: str, jibun: str = "") -> dict:
    return _cached(f"apt|{lawd}|{dong}|{apt}|{jibun}", lambda: _apt_summary(lawd, dong, apt, jibun))


def _apt_summary(lawd: str, dong: str, apt: str, jibun: str) -> dict:
    end = _end_ymd()
    recent_start = re_store.shift_ymd(end, -2)       # 최근 3개월 (이번 달 포함)
    prev_start = re_store.shift_ymd(end, -5)         # 직전 3개월
    year_start = re_store.shift_ymd(end, -11)
    rows = _trade_rows(lawd, year_start, dong, apt, jibun)
    jeonse = _jeonse_rows(lawd, prev_start, dong, apt, jibun)
    recent = [r for r in rows if r["ymd"] >= recent_start]
    prev = [r for r in rows if prev_start <= r["ymd"] < recent_start]
    bands = []
    for k, label, _, _ in BANDS:
        rb = [r for r in recent if band_of(r["area"]) == k]
        pb = [r for r in prev if band_of(r["area"]) == k]
        jb = [r for r in jeonse if r["ymd"] >= recent_start and band_of(r["area"]) == k]
        if not (rb or pb):
            continue
        item: dict = {"band": k, "label": label, "count": len(rb), "prev_count": len(pb)}
        if rb:
            hi = max(rb, key=lambda r: r["amount"])
            lo = min(rb, key=lambda r: r["amount"])
            last = max(rb, key=lambda r: (r["date"], r["amount"]))
            pick = lambda r: {"amount": r["amount"], "date": r["date"], "area": r["area"], "floor": r.get("floor")}  # noqa: E731
            item.update({"max": pick(hi), "min": pick(lo), "latest": pick(last)})
        med, pmed = _median(r["amount"] for r in rb), _median(r["amount"] for r in pb)
        jmed = _median(r["deposit"] for r in jb)
        item.update({"median": med, "prev_median": pmed, "change_pct": _pct(med, pmed), "jeonse_median": jmed,
                     "jeonse_count": len(jb), "jeonse_ratio": round(jmed / med * 100, 1) if jmed and med else None})
        bands.append(item)
    main = max(bands, key=lambda b: (b["count"], b["prev_count"])) if bands else None
    last = max(rows, key=lambda r: (r["date"], r["amount"])) if rows else None
    dates = [r["date"] for r in rows if r["date"]]
    return {"lawd": lawd, "region": regions_kr.NAMES.get(lawd, lawd), "dong": dong, "apt": apt, "jibun": jibun,
            "bands": bands, "main_band": main["band"] if main else None,
            "change_pct": main["change_pct"] if main else None, "jeonse_ratio": main["jeonse_ratio"] if main else None,
            "recent_count": len(recent), "year_count": len(rows),
            "last_trade": {"amount": last["amount"], "date": last["date"], "area": last["area"]} if last else None,
            "window": {"recent": [recent_start, end], "prev": [prev_start, re_store.shift_ymd(recent_start, -1)]},
            "notes": notes_for(lawd, [w for w in (apt, dong) if w and len(w) >= 2]),
            "as_of": max(dates) if dates else None, "fetched_at": _fetched_at(lawd), "source": SOURCE}


# ───────────────────────── 뉴스레터용: 관심 단지 이번 주 ─────────────────────────

def watch_week(item: dict, today: date | None = None) -> dict | None:
    """관심 단지 하나의 메일용 요약 — 최근 30일 계약 건수·최근가·직전 분기 대비 변동률(주 평형 중위)."""
    lawd, apt = item.get("lawd") or "", item.get("apt") or ""
    if lawd not in regions_kr.NAMES or not apt:
        return None
    s = apt_summary(lawd, item.get("dong") or "", apt, item.get("jibun") or "")
    today = today or date.today()
    since = (today - timedelta(days=30)).isoformat()
    rows = _trade_rows(lawd, re_store.shift_ymd(_end_ymd(), -1), item.get("dong") or "", apt, item.get("jibun") or "")
    n30 = sum(1 for r in rows if r["date"] >= since)
    return {"apt": apt, "dong": item.get("dong") or "", "lawd": lawd, "region": s["region"], "count_30d": n30,
            "last_trade": s["last_trade"], "change_pct": s["change_pct"], "jeonse_ratio": s["jeonse_ratio"],
            "main_band": BAND_LABEL.get(s["main_band"] or "", ""), "as_of": s["as_of"]}
