"""예산으로 살 수 있는 단지 · 비슷한 단지 (2026-11-19) — 저장된 아파트 매매 실거래(rtms_apt_trade)만 읽는 규칙 계산. LLM 없음.

- GET /api/re/affordable?lawd=&price=  : 최근 3개월 거래 중 단지·평형별 중위 거래가가 예산(만원) 이하인 곳, 거래 많은 순.
- GET /api/re/apt/similar?lawd=&dong=&apt= : 같은 시군구에서 3.3㎡당 가격·전용면적이 가까운 단지 3곳 (최근 6개월).
거래 신고는 계약 뒤 30일까지 늦을 수 있고 해제 거래는 뺀다. 가격 예측·추천이 아니라 '지금까지 거래된 값' 비교다.
"""
from __future__ import annotations

import math
import statistics
from datetime import date

from fastapi import APIRouter, HTTPException, Query

from pipeline import db, regions_kr

router = APIRouter(tags=["afford"])


def _ym_back(months: int) -> str:
    t = date.today()
    y, m = t.year, t.month - months
    while m <= 0:
        y, m = y - 1, m + 12
    return f"{y}{m:02d}"


def _rows(sql: str, args: tuple) -> list[tuple]:
    try:
        con = db.connect()
        try:
            return con.execute(sql, args).fetchall()
        finally:
            con.close()
    except Exception:  # noqa: BLE001 - 표가 아직 없으면 빈 결과
        return []


def _lawd(v: str) -> str:
    if v not in regions_kr.NAMES:
        raise HTTPException(400, "시군구 코드가 올바르지 않습니다.")
    return v


@router.get("/re/affordable")
def affordable(lawd: str = Query(...), price: int = Query(..., ge=1000, le=10_000_000), months: int = Query(3, ge=1, le=6), limit: int = Query(15, ge=1, le=30)) -> dict:
    _lawd(lawd)
    rows = _rows("SELECT name, COALESCE(umd,''), area, amount FROM rtms_apt_trade WHERE lawd_cd=? AND deal_ymd>=? AND COALESCE(cancelled,0)=0 "
                 "AND amount>0 AND area>0 AND name<>''", (lawd, _ym_back(months - 1)))
    g: dict[tuple, list[int]] = {}
    for name, umd, area, amount in rows:
        g.setdefault((name, umd, round(area)), []).append(amount)
    out = []
    for (name, umd, area), v in g.items():
        med = statistics.median(v)
        if med <= price:
            out.append({"apt": name, "dong": umd, "area": area, "n": len(v), "median": int(med), "min": min(v), "max": max(v)})
    out.sort(key=lambda x: (-x["n"], -x["median"]))
    return {"region": regions_kr.NAMES[lawd], "price": price, "months": months, "total": len(out), "rows": out[:limit],
            "source": "국토교통부 아파트 매매 실거래가 (저장된 자료)", "note": "단지·전용면적(반올림)별 최근 거래 중위가가 예산 이하인 곳. 층·향에 따라 같은 평형도 값이 달라요."}


@router.get("/re/apt/similar")
def similar(lawd: str = Query(...), apt: str = Query(..., max_length=60), dong: str = Query("", max_length=20)) -> dict:
    _lawd(lawd)
    rows = _rows("SELECT name, COALESCE(umd,''), area, amount FROM rtms_apt_trade WHERE lawd_cd=? AND deal_ymd>=? AND COALESCE(cancelled,0)=0 "
                 "AND amount>0 AND area>0 AND name<>''", (lawd, _ym_back(5)))
    g: dict[tuple, list[tuple[float, int]]] = {}
    for name, umd, area, amount in rows:
        g.setdefault((name, umd), []).append((area, amount))

    def stat(v: list[tuple[float, int]]) -> tuple[float, float]:
        return statistics.median(a for a, _ in v), statistics.median(am / a * 3.3 for a, am in v)  # (면적, 3.3㎡당 만원)

    me_keys = [k for k in g if k[0] == apt and (not dong or k[1] == dong)]
    if not me_keys or len(g[me_keys[0]]) < 2:
        return {"rows": [], "reason": "이 단지의 최근 거래가 적어 비교할 수 없어요."}
    a0, p0 = stat(g[me_keys[0]])
    cand = []
    for k, v in g.items():
        if k == me_keys[0] or len(v) < 3:
            continue
        a, p = stat(v)
        dist = abs(math.log(p / p0)) + abs(a - a0) / a0 * 0.5
        cand.append((dist, k, a, p, len(v)))
    cand.sort()
    return {"rows": [{"apt": k[0], "dong": k[1], "area": round(a, 1), "pp": int(p), "n": n} for _, k, a, p, n in cand[:3]],
            "base": {"area": round(a0, 1), "pp": int(p0)}, "months": 6,
            "note": "같은 시군구에서 최근 6개월 3.3㎡당 거래가와 전용면적이 가까운 단지예요. 입지·연식·브랜드는 비교하지 않았어요."}
