"""전체 검색 (2026-11-19) — 상단 ⌘K 검색 창이 부른다. 단지·시군구·청약 공고·노트를 한 번에, 초성('ㄷㅊ')·오타('레미안')도 찾는다.

- 단지: 최근 거래가 있는 (시군구·동·단지명) 목록을 메모리에 30분 캐시. 노트·공고는 그때그때 저장된 표에서.
- 자료가 없는 종류는 빈 목록 — 숫자를 지어내지 않는다. LLM 없음.
"""
from __future__ import annotations

import time
from datetime import date

from fastapi import APIRouter, Query

from pipeline import db, hangul, re_store, regions_kr

router = APIRouter(tags=["find"])
_cache: dict = {"at": 0.0, "apts": []}
TTL = 1800
PER = 6


def _apts() -> list[tuple]:
    if time.time() - _cache["at"] < TTL and _cache["apts"]:
        return _cache["apts"]
    since = (date.today().replace(day=1)).replace(year=date.today().year - 2).strftime("%Y%m")
    try:
        con = db.connect()
        try:
            rows = con.execute("SELECT lawd_cd, COALESCE(umd,''), name, COUNT(*) FROM rtms_apt_trade WHERE deal_ymd >= ? AND COALESCE(cancelled,0)=0 AND name<>'' "
                               "GROUP BY lawd_cd, umd, name", (since,)).fetchall()
        finally:
            con.close()
    except Exception:  # noqa: BLE001 - 표가 아직 없으면 빈 목록
        rows = []
    _cache["apts"] = [(r[0], r[1], r[2], r[3]) for r in rows]
    _cache["at"] = time.time()
    return _cache["apts"]


def _rank(items, q: str, text_of, boost=lambda x: 0):
    hit = []
    for x in items:
        m = hangul.match(q, text_of(x))
        if m:
            hit.append((m, boost(x), x))
    if not hit:  # 못 찾으면 오타 허용으로 한 번 더
        hit = [(0, boost(x), x) for x in items if hangul.fuzzy(q, text_of(x))]
    hit.sort(key=lambda t: (-t[0], -t[1]))
    return [t[2] for t in hit[:PER]]


@router.get("/find")
def find(q: str = Query("", max_length=40)) -> dict:
    q = q.strip()
    if len(hangul.norm(q)) < 2:
        return {"q": q, "apts": [], "regions": [], "notices": [], "notes": []}
    apts = _rank(_apts(), q, lambda a: a[2], lambda a: a[3])
    regions = _rank(list(regions_kr.NAMES.items()), q, lambda r: r[1].split(" ", 1)[-1] if " " in r[1] else r[1])
    try:
        notices = _rank(re_store.notices("all", limit=600), q, lambda n: f"{n.get('name') or ''}")
    except Exception:  # noqa: BLE001
        notices = []
    notes = _rank(db.notes(), q, lambda n: n["title"])
    return {"q": q,
            "apts": [{"lawd": a[0], "dong": a[1], "apt": a[2], "region": regions_kr.NAMES.get(a[0], "")} for a in apts],
            "regions": [{"code": c, "name": n} for c, n in regions],
            "notices": [{"id": n["notice_id"], "name": n["name"], "region": n.get("region") or "", "date": n.get("receipt_start") or n.get("notice_date") or ""} for n in notices],
            "notes": [{"id": n["id"], "title": n["title"], "kind": n.get("kind") or ""} for n in notes]}
