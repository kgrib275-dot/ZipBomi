"""부동산 전용 기능 API — 실거래가 조회 (/api/re/*).

- 데이터: 국토교통부 아파트 매매 실거래가 상세 자료 (pipeline/molit.py, DB 캐시). LLM 은 쓰지 않는다.
- 공공 API 는 하루 한도가 있으므로 캐시에 없을 때만 남용 제한(throttle)을 센다 — 캐시된 화면은 누구나 마음껏 본다.
- 관심 목록·계산기 입력은 방문자 상태(/api/me/state 의 re_watch·calc_inputs)에 저장하므로 여기엔 없다.
- /re/data·/re/apply·/re/indicators 는 배치 '부동산 데이터 수집'(pipeline/redata.py)이 저장한 DB 만 읽는다 — 공공 API 를 부르지 않는다.
"""
from __future__ import annotations

import re
import time
from datetime import date

from fastapi import APIRouter, HTTPException, Query

from api.deps import Caller, CallerDep, throttle
from pipeline import molit, re_store, regions_kr, rtms

router = APIRouter(tags=["realestate"])

_YMD_RE = re.compile(r"^\d{6}$")
_LAWD_RE = re.compile(r"^\d{5}$")
FIRST_YEAR = 2006  # 실거래가 신고제가 시작된 해 — 그 전 자료는 없다


def _lawd(v: str) -> str:
    # 목록에 있는 코드만 받는다 — 아무 숫자나 넣어 공공 API 한도를 쓰지 못하게
    if not _LAWD_RE.match(v or "") or v not in regions_kr.NAMES:
        raise HTTPException(status_code=400, detail="지원하지 않는 지역 코드입니다.")
    return v


def _ymd(v: str) -> str:
    if not _YMD_RE.match(v or ""):
        raise HTTPException(status_code=400, detail="년월은 YYYYMM 형식이어야 합니다.")
    y, m = int(v[:4]), int(v[4:])
    t = date.today()
    if not 1 <= m <= 12 or y < FIRST_YEAR or (y, m) > (t.year, t.month):
        raise HTTPException(status_code=400, detail="조회할 수 없는 년월입니다.")
    return v


def _last_month() -> str:
    t = date.today()
    y, m = (t.year, t.month - 1) if t.month > 1 else (t.year - 1, 12)
    return f"{y:04d}{m:02d}"


def _shift(ymd: str, k: int) -> str:
    """ymd 에서 k 달 뒤(음수면 앞)."""
    n = int(ymd[:4]) * 12 + int(ymd[4:]) - 1 + k
    return f"{n // 12:04d}{n % 12 + 1:02d}"


@router.get("/re/ping")
def ping() -> dict:
    return {"ok": True}


@router.get("/re/status")
def status() -> dict:
    return {"configured": molit.configured()}


@router.get("/re/regions")
def regions() -> dict:
    return {"configured": molit.configured(), "groups": regions_kr.grouped(), "default_ymd": _last_month()}


@router.get("/re/deals")
def deals(lawd: str = Query(...), ymd: str = Query(""), c: Caller = CallerDep) -> dict:
    lawd = _lawd(lawd)
    ymd = _ymd(ymd or _last_month())
    base = {"configured": molit.configured(), "lawd": lawd, "region": regions_kr.NAMES[lawd], "ymd": ymd}
    if not base["configured"]:
        return base
    hit = molit.cached_month(lawd, ymd)
    if not hit:
        throttle("re_fetch", c, per_visitor=40, per_ip=120, minutes=60)
        try:
            hit = molit.get_month(lawd, ymd)
        except molit.MolitError as e:
            # 키·승인 같은 운영 사정은 관리자에게만 — 방문자에게는 '갱신 중'으로 (2026-11 Phase 0)
            msg = str(e) if c.is_admin or "한도" in str(e) else "데이터 갱신 중입니다 — 잠시 뒤 다시 확인해 주세요."
            raise HTTPException(status_code=502, detail=msg) from e
    rows, fetched_at = hit if hit else ([], "")
    rows = sorted(rows, key=lambda r: r["date"], reverse=True)
    return {**base, "fetched_at": fetched_at, "summary": molit.summarize(rows), "rows": rows}


@router.get("/re/deals/trend")
def trend(lawd: str = Query(...), months: int = Query(12, ge=1, le=12), ymd: str = Query(""), c: Caller = CallerDep) -> dict:
    """최근 n개월(최대 12) 3.3㎡당 중위가격. 빈 달만 차례로 받아 온다 — 최대 12번, 한 번에 하나씩, 사이에 쉬면서."""
    lawd = _lawd(lawd)
    end = _ymd(ymd or _last_month())
    base = {"configured": molit.configured(), "lawd": lawd, "region": regions_kr.NAMES[lawd]}
    if not base["configured"]:
        return base
    want = [m for m in (_shift(end, -i) for i in range(months - 1, -1, -1)) if int(m[:4]) >= FIRST_YEAR]
    have = {m: molit.cached_month(lawd, m) for m in want}
    allow = True
    if any(v is None for v in have.values()):
        try:
            throttle("re_trend", c, per_visitor=8, per_ip=30, minutes=60)
        except HTTPException:
            allow = False  # 한도에 걸리면 캐시에 있는 달만 보여 준다 (화면 전체를 실패시키지 않게)
    points, partial, first = [], False, True
    for m in want:
        hit = have[m]
        if hit is None and allow:
            if not first:
                time.sleep(0.3)
            first = False
            try:
                hit = molit.get_month(lawd, m)
            except molit.MolitError:
                hit = None
                allow = False  # 한 번 실패하면 남은 달은 부르지 않는다 (키 오류·한도 초과면 계속 실패하므로)
        if hit is None:
            partial = True
            points.append({"ymd": m, "median_pyeong": None, "count": None})
            continue
        rows = hit[0]
        points.append({"ymd": m, "median_pyeong": molit.month_median_pyeong(rows),
                       "count": sum(1 for r in rows if not r["cancelled"])})
    return {**base, "points": points, "partial": partial}


# ───────────── 배치로 저장한 부동산 데이터 (DB 만 읽음) ─────────────

_PUBLIC_GROUPS = ("rtms",)


def _public_datasets() -> list[dict]:
    st = re_store.states()
    cov = re_store.coverage()
    out = []
    for d in re_store.datasets():
        if d.get("group") not in _PUBLIC_GROUPS or not d["enabled"]:
            continue
        c = cov.get(d["key"]) or {}
        status = "no_key" if not rtms.configured() else ((st.get(d["key"]) or {}).get("status") or "pending")
        out.append({"key": d["key"], "name": d["name"], "prop": d.get("prop"), "deal": d.get("deal"),
                    "status": status, "status_label": "갱신 중" if status in ("no_key", "not_registered") else re_store.STATUS_LABELS.get(status, status),  # 키·활용신청 사정은 관리 화면에서만
                    "row_count": int(c.get("rows") or 0), "ymd_from": c.get("ymd_from"), "ymd_to": c.get("ymd_to")})
    return out


@router.get("/re/datasets")
def re_datasets() -> dict:
    return {"configured": rtms.configured(), "datasets": _public_datasets()}


@router.get("/re/data")
def re_data(dataset: str = Query(...), lawd: str = Query(...), ymd: str = Query("")) -> dict:
    """데이터셋 하나의 한 시군구·한 달 — 저장된 행과 요약 (매매: 중위가·3.3㎡당, 전월세: 전세/월세 중위)."""
    ds = {d["key"]: d for d in _public_datasets()}
    if dataset not in ds:
        raise HTTPException(status_code=400, detail="지원하지 않는 데이터셋입니다.")
    lawd = _lawd(lawd)
    ymd = _ymd(ymd or _last_month())
    rows, fetched_at = re_store.month_rows(dataset, lawd, ymd)
    return {**ds[dataset], "dataset": dataset, "configured": rtms.configured(), "lawd": lawd,
            "region": regions_kr.NAMES[lawd], "ymd": ymd, "fetched": fetched_at is not None, "fetched_at": fetched_at or "",
            "summary": re_store.summarize(dataset, rows), "rows": rows}


@router.get("/re/apply")
def re_apply(scope: str = Query("upcoming"), region: str = Query(""), q: str = Query(""), house_type: str = Query(""),
             limit: int = Query(200, ge=1, le=500)) -> dict:
    """청약 공고 (청약홈 + LH) — upcoming: 접수 마감 전 공고를 접수 빠른 순, all: 최근 공고 순."""
    if scope not in ("upcoming", "all"):
        raise HTTPException(status_code=400, detail="scope 는 upcoming 또는 all 입니다.")
    q = q.strip()[:40]
    rows = re_store.notices(scope, region.strip()[:10], q, house_type.strip()[:30], limit)
    st = re_store.states()
    return {"configured": rtms.configured(), "scope": scope, "rows": rows,
            "sources": {k: (st.get(k) or {}).get("status") or ("no_key" if k != "lh_notice" and not rtms.configured() else "pending")
                        for k in ("apply_notice", "lh_notice")}}


@router.get("/re/apply/{notice_id}")
def re_apply_detail(notice_id: str) -> dict:
    if len(notice_id) > 80:
        raise HTTPException(status_code=404, detail="없는 공고입니다.")
    n = re_store.notice_detail(notice_id)
    if not n:
        raise HTTPException(status_code=404, detail="없는 공고입니다.")
    return n


@router.get("/re/indicators")
def re_indicators() -> dict:
    """기준금리·주담대 금리·KB 가격지수·지가변동률 (최근 24개)."""
    return re_store.indicators()


# ───────────── 관심 단지·지역 드릴다운 (Phase 2 — 저장된 rtms_apt_trade·rtms_apt_rent 만 읽음, 10분 캐시) ─────────────

def _name(v: str, n: int) -> str:
    v = " ".join((v or "").split())
    if len(v) > n:
        raise HTTPException(status_code=400, detail="이름이 너무 깁니다.")
    return v


@router.get("/re/stored")
def re_stored() -> dict:
    """아파트 매매가 저장된 시군구 코드 — 키가 없어도(업로드 등) 저장된 자료가 있으면 화면이 드릴다운을 보여 준다."""
    from pipeline import re_trend
    return re_trend._cached("stored", _stored)


def _stored() -> dict:
    re_store.ensure_schema()
    from pipeline import db as _db
    conn = _db.connect()
    try:
        lawds = {r[0] for r in conn.execute("SELECT DISTINCT lawd_cd FROM rtms_apt_trade")}
        try:
            lawds |= {r[0] for r in conn.execute("SELECT DISTINCT lawd_cd FROM re_apt_trade WHERE total > 0")}
        except Exception:  # noqa: BLE001 - 화면 캐시 표가 아직 없음
            pass
    finally:
        conn.close()
    return {"lawds": sorted(c for c in lawds if c in regions_kr.NAMES)}


@router.get("/re/region/trend")
def region_trend(lawd: str = Query(...), dong: str = Query(""), apt: str = Query(""), months: int = Query(24, ge=6, le=36),
                 markers: str = Query("volume"), band: str = Query("")) -> dict:
    """시군구 → 동 → 단지 월별 거래량·3.3㎡당 평균가 + 노트 표시(volume: 거래량 ±30% 달, policy: 정책 노트 게시 달)."""
    from pipeline import re_trend
    lawd = _lawd(lawd)
    if markers not in ("volume", "policy"):
        raise HTTPException(status_code=400, detail="markers 는 volume 또는 policy 입니다.")
    if band not in ("", "s", "m", "l"):
        raise HTTPException(status_code=400, detail="band 는 s·m·l 중 하나입니다.")
    return re_trend.region_trend(lawd, _name(dong, 20), _name(apt, 60), months, markers, band)


@router.get("/re/apt/summary")
def apt_summary(lawd: str = Query(...), apt: str = Query(...), dong: str = Query(""), jibun: str = Query("")) -> dict:
    """관심 단지 카드 — 최근 3개월 평형별 최고·최저·최근가, 직전 3개월 대비 중위가 변동률, 전세가율, 관련 노트 3편."""
    from pipeline import re_trend
    lawd = _lawd(lawd)
    apt = _name(apt, 60)
    if not apt:
        raise HTTPException(status_code=400, detail="단지 이름이 필요합니다.")
    return re_trend.apt_summary(lawd, _name(dong, 20), apt, _name(jibun, 20))
