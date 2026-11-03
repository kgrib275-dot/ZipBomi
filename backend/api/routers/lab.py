"""데이터 랩·지식 지도·참여 지도 HTML 문서 (/api/lab/html, /api/lab/map/html, /api/map/html).

React 화면은 iframe srcdoc 으로 띄운다. Streamlit 판 app_pages/lab.py·today.py 의 st.iframe 과 같은 문서.
참여 지도의 예시 데이터·개별 행(engage.map_data)은 관리자만 볼 수 있다 — 공개는 engage.map_public(묶은 값)만.
"""
from __future__ import annotations


from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, Response

from api.common import cached
from api.deps import Caller, CallerDep
from app import datalab, geo_map
from pipeline import engage, knowledge, settings_store

router = APIRouter(tags=["lab"])



def _cached(key: str, fn, ttl: int):
    return cached("lab:" + key, fn, ttl)  # 만료 순간 한 요청만 다시 계산 (api/common.cached)


_HEADERS = {"Cache-Control": "private, max-age=120", "X-Content-Type-Options": "nosniff"}


def _lab_doc() -> tuple[str, bytes]:
    """(문서, gzip 으로 미리 압축한 문서). 문서가 약 1MB 라 요청마다 압축하면 0.5초씩 들었다 (2026-11-03) — 계산할 때 한 번만 압축한다."""
    import gzip
    html = datalab.page_html(datalab.build_data())
    return html, gzip.compress(html.encode("utf-8"), compresslevel=6)


def warm() -> None:
    _cached("lab", _lab_doc, 300)


@router.get("/lab/html", response_class=HTMLResponse)
def lab_html(request: Request) -> Response:
    """탐색 대시보드 — app/datalab.py 가 만들던 HTML 문서 그대로 (5분 캐시). gzip 을 받는 브라우저에는 미리 압축한 것을 준다
    (GZipMiddleware 는 Content-Encoding 이 이미 있으면 다시 압축하지 않는다)."""
    html, gz = _cached("lab", _lab_doc, 300)
    if "gzip" in request.headers.get("accept-encoding", ""):
        return Response(gz, media_type="text/html; charset=utf-8",
                        headers={**_HEADERS, "Content-Encoding": "gzip", "Vary": "Accept-Encoding"})
    return HTMLResponse(html, headers=_HEADERS)


@router.get("/lab/map/html", response_class=HTMLResponse)
def knowledge_map_html() -> HTMLResponse:
    """지식 지도 — 노트·기사 임베딩을 2차원으로 펼친 문서 (10분 캐시)."""
    html = _cached("kmap", lambda: datalab.map_html(knowledge.knowledge_map()), 600)
    return HTMLResponse(html, headers=_HEADERS)


@router.get("/map/html", response_class=HTMLResponse)
def participation_map_html(days: int | None = Query(None, ge=1, le=3650), sample: str = "", c: Caller = CallerDep) -> HTMLResponse:
    """참여 지도. 공개: 서버에서 묶은 값만(설정의 예시 데이터 포함 여부 따름). 관리자: ?days·?sample=1 로 개별 행·예시 데이터."""
    if c.is_admin and (days or sample):
        data = engage.map_data(days, include_sample=sample == "1")
        return HTMLResponse(geo_map.html(data), headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})
    include = settings_store.load()["engage"]["sample_on_map"]
    html = _cached(f"pmap:{include}", lambda: geo_map.html(engage.map_public(include_sample=include)), 120)
    return HTMLResponse(html, headers=_HEADERS)


# ───────── 데이터 랩 — 시장 숫자 (2026-11-02) ─────────
# 월별 전국·서울 아파트 매매(건수·중위 3.3㎡가), 금리·심리·KB 지수, 시군구 순위(최근 3개월 3.3㎡ 중위·직전 3개월 대비·거래량).
_ECON = ("mortgage_new", "house_outlook_csi", "consumer_csi", "kb_sale_apt", "kb_sale_apt_seoul", "kb_jeonse_apt")


def _lab_market() -> dict:
    from datetime import date
    from statistics import median
    from pipeline import db, regions_kr
    t = date.today()
    cur = f"{t.year}{t.month:02d}"
    y, m = t.year, t.month - 24
    while m <= 0:
        y, m = y - 1, m + 12
    since = f"{y}{m:02d}"
    c = db.connect()
    try:
        rows = c.execute("SELECT deal_ymd, lawd_cd, amount, area FROM rtms_apt_trade WHERE deal_ymd >= ? AND deal_ymd < ? "
                         "AND COALESCE(cancelled,0)=0 AND amount IS NOT NULL AND area > 0", (since, cur)).fetchall()
        econ = {}
        for s in _ECON:
            pts = c.execute("SELECT period, value, name, unit FROM re_econ_series WHERE series=? ORDER BY period DESC LIMIT 36", (s,)).fetchall()
            if pts:
                econ[s] = {"name": pts[0]["name"], "unit": pts[0]["unit"], "points": [{"p": r["period"], "v": r["value"]} for r in reversed(pts)]}
    finally:
        c.close()
    PY = 3.305785
    by_m: dict = {}
    by_r: dict = {}
    months = sorted({r["deal_ymd"] for r in rows})
    recent3, prev3 = set(months[-3:]), set(months[-6:-3])
    for r in rows:
        pp = r["amount"] / r["area"] * PY
        d = by_m.setdefault(r["deal_ymd"], {"all": [], "seoul": []})
        d["all"].append(pp)
        if r["lawd_cd"].startswith("11"):
            d["seoul"].append(pp)
        if r["deal_ymd"] in recent3 or r["deal_ymd"] in prev3:
            g = by_r.setdefault(r["lawd_cd"], {"r": [], "p": [], "price": []})
            (g["r"] if r["deal_ymd"] in recent3 else g["p"]).append(pp)
            if r["deal_ymd"] in recent3:
                g["price"].append(r["amount"])
    monthly = [{"ym": k, "count": len(v["all"]), "pp": round(median(v["all"])), "seoul_count": len(v["seoul"]),
                "seoul_pp": round(median(v["seoul"])) if v["seoul"] else None} for k, v in sorted(by_m.items())]
    ranks = []
    for code, g in by_r.items():
        if len(g["r"]) < 10:
            continue
        rm, pm = median(g["r"]), (median(g["p"]) if len(g["p"]) >= 10 else None)
        name = regions_kr.NAMES.get(code, code)
        ranks.append({"lawd": code, "name": name, "sido": name.split(" ")[0], "pp": round(rm), "price": round(median(g["price"])),
                      "deals": len(g["r"]), "chg": round((rm - pm) / pm * 100, 1) if pm else None})
    return {"monthly": monthly, "econ": econ, "ranks": ranks, "recent": sorted(recent3), "source": "국토교통부 아파트 매매 실거래가 · 한국은행 ECOS"}


@router.get("/lab/market")
def lab_market() -> dict:
    """데이터 랩 시장 숫자 — 1시간 캐시 (실거래 수집은 하루 1번)."""
    return _cached("market", _lab_market, 3600)


# ───────── 데이터 랩 — 시·도 상세 (영업용, 2026-11-02) ─────────
# 시군구별 최근 3개월 거래량·3.3㎡ 중위·직전 3개월 대비·전세가율·평형별 중위가·월세 비중, 거래 활발 단지, 최근 2개월 신고가(24개월 최고 경신).
_SIDO_PRE = {"11": "서울", "41": "경기", "26": "부산", "28": "인천"}


def _band(area: float) -> str:
    return "s" if area <= 60 else "m" if area <= 85 else "l"


def _lab_region(sido: str) -> dict:
    from datetime import date
    from statistics import median
    from pipeline import db, regions_kr
    PY = 3.305785
    t = date.today()
    cur = f"{t.year}{t.month:02d}"

    def back(n: int) -> str:
        y, m = t.year, t.month - n
        while m <= 0:
            y, m = y - 1, m + 12
        return f"{y}{m:02d}"
    c = db.connect()
    try:
        tr = c.execute("SELECT lawd_cd, deal_ymd, deal_date, umd, name, area, floor, amount FROM rtms_apt_trade WHERE lawd_cd LIKE ? "
                       "AND deal_ymd >= ? AND deal_ymd < ? AND COALESCE(cancelled,0)=0 AND amount IS NOT NULL AND area > 0",
                       (sido + "%", back(24), cur)).fetchall()
        months = sorted({r["deal_ymd"] for r in tr})
        r3, p3 = set(months[-3:]), set(months[-6:-3])
        rent = c.execute("SELECT lawd_cd, area, deposit, monthly_rent FROM rtms_apt_rent WHERE lawd_cd LIKE ? AND deal_ymd IN (%s) AND area > 0"
                         % ",".join("?" * len(r3)), (sido + "%", *sorted(r3))).fetchall() if r3 else []
    finally:
        c.close()
    d: dict = {}
    for r in tr:
        g = d.setdefault(r["lawd_cd"], {"r": [], "p": [], "b": {"s": [], "m": [], "l": []}})
        pp = r["amount"] / r["area"] * PY
        if r["deal_ymd"] in r3:
            g["r"].append(pp); g["b"][_band(r["area"])].append(r["amount"])
        elif r["deal_ymd"] in p3:
            g["p"].append(pp)
    jr: dict = {}
    for r in rent:
        g = jr.setdefault(r["lawd_cd"], {"j": [], "n": 0, "w": 0})
        g["n"] += 1
        if (r["monthly_rent"] or 0) > 0:
            g["w"] += 1
        elif r["deposit"]:
            g["j"].append(r["deposit"] / r["area"] * PY)
    districts = []
    for code, g in d.items():
        if len(g["r"]) < 5:
            continue
        rm = median(g["r"])
        pm = median(g["p"]) if len(g["p"]) >= 5 else None
        j = jr.get(code, {})
        jm = median(j["j"]) if len(j.get("j", [])) >= 5 else None
        districts.append({"lawd": code, "name": regions_kr.NAMES.get(code, code).split(" ", 1)[-1], "deals": len(g["r"]), "pp": round(rm),
                          "chg": round((rm - pm) / pm * 100, 1) if pm else None, "jeonse_ratio": round(jm / rm * 100, 1) if jm else None,
                          "monthly_share": round(j["w"] / j["n"] * 100, 1) if j.get("n") else None,
                          "s": round(median(g["b"]["s"])) if g["b"]["s"] else None, "m": round(median(g["b"]["m"])) if g["b"]["m"] else None,
                          "l": round(median(g["b"]["l"])) if g["b"]["l"] else None})
    # 거래 활발 단지 (최근 3개월)
    apts: dict = {}
    for r in tr:
        if r["deal_ymd"] in r3 and r["name"]:
            apts.setdefault((r["lawd_cd"], r["umd"], r["name"]), []).append(r)
    hot = []
    for (code, umd, name), rs in sorted(apts.items(), key=lambda kv: -len(kv[1]))[:15]:
        hot.append({"lawd": code, "region": regions_kr.NAMES.get(code, code).split(" ", 1)[-1], "umd": umd, "name": name, "deals": len(rs),
                    "median": round(median(x["amount"] for x in rs)), "pp": round(median(x["amount"] / x["area"] * PY for x in rs))})
    # 신고가 — 최근 2개월 거래가 같은 단지·평형대의 그 전 24개월 최고가를 넘은 경우
    last2 = set(months[-2:])
    best: dict = {}
    highs = []
    for r in sorted(tr, key=lambda x: (x["deal_date"] or "")):
        key = (r["lawd_cd"], r["umd"], r["name"], round(r["area"] / 3))  # 같은 평형(전용 ±3㎡)끼리만 — 원룸형·일반형이 섞이지 않게
        if r["deal_ymd"] in last2 and key in best and r["amount"] > best[key][0] and best[key][1] >= 2:
            highs.append({"lawd": r["lawd_cd"], "region": regions_kr.NAMES.get(r["lawd_cd"], r["lawd_cd"]).split(" ", 1)[-1], "umd": r["umd"],
                          "name": r["name"], "area": round(r["area"], 1), "floor": r["floor"], "amount": r["amount"], "prev": best[key][0],
                          "pct": round((r["amount"] - best[key][0]) / best[key][0] * 100, 1), "date": r["deal_date"]})
        b = best.get(key, (0, 0))
        best[key] = (max(b[0], r["amount"]), b[1] + 1)
    highs.sort(key=lambda x: (x["date"] or "", x["amount"]), reverse=True)
    return {"sido": _SIDO_PRE.get(sido, sido), "recent": sorted(r3), "districts": sorted(districts, key=lambda x: -x["pp"]),
            "hot": hot, "highs": highs[:25], "n_highs": len(highs), "source": "국토교통부 아파트 매매·전월세 실거래가"}


@router.get("/lab/region")
def lab_region(sido: str = Query("11", pattern="^(11|41|26|28)$")) -> dict:
    return _cached(f"region:{sido}", lambda: _lab_region(sido), 3600)
