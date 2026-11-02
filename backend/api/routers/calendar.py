"""분양 일정 (/api/re/calendar) · 당첨 가점 비교 (/api/re/scores) — Phase 4 (2026-11-02).

둘 다 배치 '부동산 데이터 수집'이 저장한 re_apply_notice·re_apply_score 만 읽는다 (공공 API 를 부르지 않음, LLM 없음).
- 일정: 공고일·접수 시작·접수 마감·당첨자 발표·계약 시작을 날짜별 사건으로 편다. LH 공고는 목록에 공고일·마감일만 있다.
- 가점: 청약홈 APT 당첨가점(주택형·거주지역별 최저·최고·평균). 공공데이터포털 키(DATA_GO_KR_KEY)가 있어야 쌓인다.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

from fastapi import APIRouter, HTTPException, Query

from pipeline import db, re_store, rtms

router = APIRouter(tags=["calendar"])

EVENTS = [("notice_date", "notice", "공고"), ("receipt_start", "start", "접수 시작"), ("receipt_end", "end", "접수 마감"),
          ("winner_date", "winner", "당첨 발표"), ("contract_start", "contract", "계약")]
LONG_OPEN_DAYS = 120  # 공고부터 마감까지 이보다 길면 '상시·선착순' 공고로 보고 마감 사건을 달력에 찍지 않는다 (목록에는 남김)


def _d(v) -> date | None:
    try:
        return date.fromisoformat(str(v)[:10]) if v else None
    except ValueError:
        return None


def _kind(n: dict) -> str:
    t = f"{n.get('category') or ''} {n.get('house_type') or ''} {n.get('name') or ''}"
    return "rent" if "임대" in t else "sale"


def _rows(sql: str, params: tuple = ()) -> list[dict]:
    re_store.ensure_schema()
    c = db.connect()
    try:
        return [dict(r) for r in c.execute(sql, params)]
    finally:
        c.close()


@router.get("/re/calendar")
def calendar(ym: str = Query(""), region: str = Query(""), kind: str = Query("")) -> dict:
    """ym 달(YYYY-MM, 기본 이번 달)의 청약 사건. region = 시도 짧은 이름 쉼표 목록 ('서울,경기'), kind = sale·rent."""
    today = date.today()
    if ym and not re.fullmatch(r"\d{4}-\d{2}", ym):
        raise HTTPException(400, "ym 은 YYYY-MM 형식입니다.")
    y, m = (int(ym[:4]), int(ym[5:])) if ym else (today.year, today.month)
    if not (1 <= m <= 12 and 2020 <= y <= today.year + 2):
        raise HTTPException(400, "조회할 수 없는 달입니다.")
    first = date(y, m, 1)
    last = (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1))
    if kind not in ("", "sale", "rent"):
        raise HTTPException(400, "kind 는 sale 또는 rent 입니다.")
    regions = [r.strip() for r in region.split(",") if r.strip()][:10]
    cols = ", ".join(c for c, _, _ in EVENTS)
    rows = _rows(f"SELECT notice_id, name, house_type, category, region, households, url, status, source, {cols} "
                 "FROM re_apply_notice WHERE " + " OR ".join(f"({c} BETWEEN ? AND ?)" for c, _, _ in EVENTS),
                 tuple(v for _ in EVENTS for v in (first.isoformat(), last.isoformat() + "T99")))
    events, notices = [], {}
    for n in rows:
        if kind and _kind(n) != kind:
            continue
        if regions and not any(r in (n.get("region") or "") or (n.get("region") or "") in r for r in regions):
            continue
        nd, ed = _d(n.get("notice_date")), _d(n.get("receipt_end"))
        long_open = bool(nd and ed and (ed - nd).days > LONG_OPEN_DAYS)
        hit = False
        for col, key, label in EVENTS:
            d = _d(n.get(col))
            if not d or not (first <= d <= last):
                continue
            if key == "end" and long_open:
                continue
            events.append({"date": d.isoformat(), "type": key, "label": label, "notice_id": n["notice_id"]})
            hit = True
        if hit:
            notices[n["notice_id"]] = {
                "id": n["notice_id"], "name": n["name"], "region": n.get("region") or "", "kind": _kind(n),
                "category": n.get("category") or n.get("house_type") or "", "households": n.get("households"),
                "url": n.get("url") if str(n.get("url") or "").startswith("http") else "", "status": n.get("status") or "",
                "source": "LH 청약플러스" if n.get("source") == "lh" else "청약홈",
                "dates": {key: (n.get(col) or "")[:10] for col, key, _ in EVENTS if n.get(col)},
                "long_open": long_open,
            }
    events.sort(key=lambda e: (e["date"], e["type"]))
    st = re_store.states()
    return {"ym": f"{y:04d}-{m:02d}", "events": events, "notices": notices, "today": today.isoformat(),
            "applyhome": rtms.configured() and (st.get("apply_notice") or {}).get("status") == "ok",
            "fetched_at": max((r.get("fetched_at") or "" for r in _rows("SELECT MAX(fetched_at) fetched_at FROM re_apply_notice")), default="")}


@router.get("/re/scores")
def scores(region: str = Query(""), months: int = Query(12, ge=1, le=36), limit: int = Query(60, ge=1, le=200)) -> dict:
    """최근 당첨 가점 (청약홈 APT) — 공고·주택형·거주지역별 최저·평균·최고. 화면이 내 가점과 비교한다."""
    since = (date.today() - timedelta(days=months * 31)).isoformat()
    regions = [r.strip() for r in region.split(",") if r.strip()][:10]
    rows = _rows("SELECT s.notice_id, s.model_no, s.house_ty, s.reside, s.low, s.top, s.avg, n.name, n.region, n.winner_date, "
                 "n.notice_date, n.url FROM re_apply_score s JOIN re_apply_notice n ON n.notice_id = s.notice_id "
                 "WHERE COALESCE(n.winner_date, n.notice_date, '') >= ? AND s.low IS NOT NULL AND COALESCE(s.top, 0) > 0 "
                 "ORDER BY COALESCE(n.winner_date, n.notice_date) DESC LIMIT 2000", (since,))
    if regions:
        rows = [r for r in rows if any(x in (r.get("region") or "") or (r.get("region") or "") in x for x in regions)]
    total = _rows("SELECT COUNT(*) n FROM re_apply_score")[0]["n"]
    st = re_store.states()
    return {"rows": rows[:limit], "matched": len(rows), "stored": total, "configured": rtms.configured(),
            "status": (st.get("apply_cmpet") or {}).get("status") or ("no_key" if not rtms.configured() else "pending"),
            "source": "한국부동산원 청약홈 (공공데이터포털 APT 당첨가점)"}


# ───────── 청약 통계 (청약홈 신청·당첨자 통계, pipeline/apply_stats.py) — 2026-11-02 ─────────
def _num(v) -> float | None:
    try:
        return float(str(v).replace(",", "").replace("(", "").replace(")", "").replace("△", "-"))
    except (TypeError, ValueError):
        return None


def _apply_stats() -> dict:
    from pipeline import apply_stats
    t = date.today()
    since = f"{t.year - 2}{t.month:02d}"
    score = [r for r in apply_stats.load("score_area", since) if r.get("reside") == "해당지역"]
    by_area: dict[str, list] = {}
    for r in score:
        by_area.setdefault(r["area"], []).append({"ym": r["ym"], "low": _num(r.get("LWET_SCORE")), "med": _num(r.get("MED_SCORE")),
                                                  "avg": _num(r.get("AVRG_SCORE")), "top": _num(r.get("TOP_SCORE"))})
    cm = apply_stats.load("cmpet_area", since)
    months = sorted({r["ym"] for r in cm})
    last12 = set(months[-12:])
    agg: dict[str, list[float]] = {}
    nat: dict[str, list[float]] = {}
    for r in cm:
        req, hh = _num(r.get("SUPLY_REQ_CNT")) or 0, _num(r.get("SUPLY_HSHLDCO")) or 0
        n = nat.setdefault(r["ym"], [0, 0]); n[0] += req; n[1] += hh
        if r["ym"] in last12:
            a = agg.setdefault(r["area"], [0, 0]); a[0] += req; a[1] += hh
    cmpet_rank = sorted(({"area": k, "req": int(v[0]), "hh": int(v[1]), "rate": round(v[0] / v[1], 1)} for k, v in agg.items() if v[1] >= 50),
                        key=lambda x: -x["rate"])
    cmpet_month = [{"ym": k, "rate": round(v[0] / v[1], 1) if v[1] else None, "req": int(v[0]), "hh": int(v[1])} for k, v in sorted(nat.items())]
    ages = {}
    for kind in ("req_age", "win_age"):
        rows = apply_stats.load(kind, since)
        ages[kind] = [{"ym": r["ym"], "a30": r.get("AGE_30") or 0, "a40": r.get("AGE_40") or 0, "a50": r.get("AGE_50") or 0, "a60": r.get("AGE_60") or 0} for r in rows]
    return {"score": by_area, "cmpet_rank": cmpet_rank, "cmpet_month": cmpet_month, "ages": ages,
            "period": f"{months[-12][:4]}.{months[-12][4:]}~{months[-1][:4]}.{months[-1][4:]}" if len(months) >= 12 else "",
            "source": "한국부동산원 청약홈 청약 신청·당첨자 정보 (공공데이터포털)"}


@router.get("/re/apply-stats")
def apply_stats_api() -> dict:
    from api.common import cached
    return cached("re:apply_stats", _apply_stats, 3600)
