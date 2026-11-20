"""공개 페이지(/c 공고·/a 단지·/s/p 가점 카드·/g 함께 보기)가 읽는 자료 (2026-11-20) — 저장된 표만 읽는 규칙 계산, 외부 호출·LLM 없음.

- 공고: re_apply_notice(+주택형 re_apply_model, 원자료 raw 의 일정)·공급 방식(재공급·무순위)·지난 1년 지역 당첨 가점 분포.
- 단지: rtms_apt_trade 최근 6개월 — 평형별 거래 건수·중위가·최근 거래. 계약 후 30일까지 신고가 늦을 수 있고 해제 거래는 뺀다.
- 개인 정보는 다루지 않는다(함께 보기는 api/routers/board.py 가 주인이 고른 것만 읽어 온다).
"""
from __future__ import annotations

import json
import re
import statistics
from datetime import date, timedelta

from . import db, regions_kr

ID_RE = re.compile(r"^[A-Za-z0-9_-]{3,64}$")
SIDOS = ["서울", "경기", "인천", "부산", "대구", "광주", "대전", "울산", "세종", "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주"]


def _q(sql: str, args: tuple = ()) -> list:
    try:
        c = db.connect()
        try:
            return c.execute(sql, args).fetchall()
        finally:
            c.close()
    except Exception:  # noqa: BLE001 - 표가 없으면 빈 결과
        return []


def supply_kind(n: dict) -> str:
    """'resale'(불법행위 재공급 등) · 'lottery'(무순위·잔여세대·임의공급) · ''(일반 분양·임대) — api/routers/calendar._supply 와 같은 규칙."""
    t = f"{n.get('category') or ''} {n.get('house_type') or ''} {n.get('name') or ''}"
    if "재공급" in t:
        return "resale"
    return "lottery" if any(k in t for k in ("무순위", "잔여세대", "임의공급")) else ""


def _d(s) -> str:
    return str(s)[:10] if s else ""


def schedule(n: dict) -> list[tuple[str, str]]:
    """공고 일정 표 [(이름, '2026-11-25' 또는 '2026-11-26 ~ 2026-11-27')] — 원자료 raw 에 있으면 순위별까지, 없으면 접수·발표만."""
    try:
        raw = json.loads(n.get("raw") or "{}")
    except (TypeError, ValueError):
        raw = {}
    rng = lambda a, b: (a if a == b else f"{a} ~ {b}") if a and b else (a or b or "")  # noqa: E731
    rows = [("공고", _d(n.get("notice_date") or raw.get("RCRIT_PBLANC_DE")))]
    sp = rng(_d(raw.get("SPSPLY_RCEPT_BGNDE")), _d(raw.get("SPSPLY_RCEPT_ENDDE")))
    if sp:
        rows.append(("특별공급 접수", sp))
    r1a, r1b = _d(raw.get("GNRL_RNK1_CRSPAREA_RCPTDE")), _d(raw.get("GNRL_RNK1_ETC_AREA_RCPTDE"))
    if r1a or r1b:
        rows.append(("1순위 접수", " / ".join(x for x in (f"해당 지역 {r1a}" if r1a else "", f"기타 지역 {r1b}" if r1b else "") if x)))
    r2 = _d(raw.get("GNRL_RNK2_CRSPAREA_RCPTDE"))
    if r2:
        rows.append(("2순위 접수", r2))
    if not (sp or r1a or r1b or r2):
        rows.append(("접수", rng(_d(n.get("receipt_start")), _d(n.get("receipt_end")))))
    rows.append(("당첨자 발표", _d(n.get("winner_date") or raw.get("PRZWNER_PRESNATN_DE"))))
    ct = rng(_d(n.get("contract_start") or raw.get("CNTRCT_CNCLS_BGNDE")), _d(n.get("contract_end") or raw.get("CNTRCT_CNCLS_ENDDE")))
    if ct:
        rows.append(("계약", ct))
    return [(k, v) for k, v in rows if v]


def region_scores(region: str, months: int = 12) -> dict | None:
    """지역(시도) 지난 당첨 가점 분포 — 3건 미만이면 None."""
    since = (date.today() - timedelta(days=months * 31)).isoformat()
    rows = _q("SELECT s.low FROM re_apply_score s JOIN re_apply_notice n ON n.notice_id = s.notice_id WHERE n.region = ? "
              "AND COALESCE(n.winner_date, n.notice_date, '') >= ? AND s.low IS NOT NULL AND s.low > 0 AND COALESCE(s.top, 0) > 0", (region, since))
    v = sorted(float(r[0]) for r in rows)
    if len(v) < 3:
        return None
    mid = v[len(v) // 2] if len(v) % 2 else (v[len(v) // 2 - 1] + v[len(v) // 2]) / 2
    return {"region": region, "n": len(v), "median": round(mid, 1), "min": v[0], "max": v[-1]}


def type_label(h) -> str:
    """청약홈 주택형 '084.9794A' → '84A', '039.9342' → '39' (전용면적 정수부 + 타입 글자)."""
    m = re.match(r"^\s*0*(\d+)(?:\.\d+)?\s*([A-Za-z]*)", str(h or ""))
    return f"{m.group(1)}{m.group(2)}" if m else str(h or "").strip()


def notice(notice_id: str) -> dict | None:
    if not ID_RE.match(notice_id or ""):
        return None
    cols = ("notice_id", "name", "house_type", "address", "lawd_cd", "region", "households", "notice_date", "receipt_start", "receipt_end",
            "winner_date", "url", "raw", "source", "category", "contract_start", "contract_end", "builder", "move_in_ym")
    r = _q(f"SELECT {', '.join(cols)} FROM re_apply_notice WHERE notice_id = ?", (notice_id,))
    if not r:
        return None
    n = dict(zip(cols, r[0]))
    n["supply"] = supply_kind(n)
    n["schedule"] = schedule(n)
    n["models"] = [{"type": type_label(m[0]), "households": m[1], "special": m[2], "top": m[3]}
                   for m in _q("SELECT house_ty, households, special_households, top_amount FROM re_apply_model WHERE notice_id=? ORDER BY model_no", (notice_id,))]
    n["scores"] = region_scores(n.get("region") or "") if n.get("region") else None
    n["raw"] = None  # 화면으로 원자료를 내보내지 않는다
    return n


def ym_back(months: int) -> str:
    t = date.today()
    y, m = t.year, t.month - months
    while m <= 0:
        y, m = y - 1, m + 12
    return f"{y}{m:02d}"


def apt_info(lawd: str, apt: str, dong: str = "") -> dict | None:
    """단지 최근 6개월 거래 요약. 거래가 없으면 None."""
    if lawd not in regions_kr.NAMES or not apt or len(apt) > 60 or len(dong) > 20:
        return None
    rows = _q("SELECT deal_date, area, floor, amount, COALESCE(umd,'') FROM rtms_apt_trade WHERE lawd_cd=? AND name=? AND (?='' OR umd=?) "
              "AND deal_ymd>=? AND COALESCE(cancelled,0)=0 AND amount>0 AND area>0 ORDER BY deal_date DESC LIMIT 400", (lawd, apt, dong, dong, ym_back(5)))
    if not rows:
        return None
    g: dict[int, list[int]] = {}
    for _d_, area, _f, amt, _u in rows:
        g.setdefault(round(area), []).append(amt)
    bands = [{"area": a, "n": len(v), "median": int(statistics.median(v)), "min": min(v), "max": max(v)} for a, v in sorted(g.items(), key=lambda x: -len(x[1]))[:5]]
    return {"lawd": lawd, "region": regions_kr.NAMES[lawd], "apt": apt, "dong": dong or rows[0][4], "n": len(rows), "bands": bands,
            "recent": [{"date": r[0], "area": round(r[1], 1), "floor": r[2], "amount": r[3]} for r in rows[:6]], "as_of": rows[0][0]}


def sitemap_notices(days: int = 150, limit: int = 600) -> list[tuple[str, str]]:
    since = (date.today() - timedelta(days=days)).isoformat()
    return [(r[0], _d(r[1])) for r in _q("SELECT notice_id, COALESCE(notice_date, receipt_start) FROM re_apply_notice WHERE COALESCE(notice_date, receipt_start, '') >= ? "
                                         "ORDER BY notice_date DESC LIMIT ?", (since, limit))]


def sitemap_apts(limit: int = 300) -> list[tuple[str, str, str]]:
    return [(r[0], r[1], r[2]) for r in _q("SELECT lawd_cd, name, COALESCE(umd,'') FROM rtms_apt_trade WHERE deal_ymd>=? AND COALESCE(cancelled,0)=0 "
                                           "GROUP BY lawd_cd, name, umd ORDER BY COUNT(*) DESC LIMIT ?", (ym_back(2), limit))]


def man(v: int | float | None) -> str:
    """만원 → '25억 2,000만원'."""
    if v is None:
        return "-"
    v = int(round(v))
    e, r = divmod(v, 10000)
    return f"{e}억{(' ' + format(r, ',') + '만') if r else ''}원" if e else f"{format(r, ',')}만원"
