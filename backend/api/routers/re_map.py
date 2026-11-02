"""지도(/map) API — 지역 시세 원, 청약 분양 공고, 직접 등록한 매물 (/api/re/map/*).

- 시세: pipeline.re_store.region_price_summary (실거래가 수집기가 채우는 캐시). 아직 없으면 빈 목록 — 숫자를 지어내지 않는다.
- 분양: 수집기가 채우는 re_apply_notice 테이블. 좌표가 없으면 시군구 중심(pipeline.regions_geo)에 살짝 흩어 찍고 approx=True.
- 매물: 관리자가 지도에서 직접 등록하는 re_listing (매물 포털을 긁어 오지 않는다). 방문자는 공개(is_public=1)만,
  메모는 절대 안 보이고 연락처는 contact_public=1 일 때만 보인다. 쓰기는 관리자 + CSRF 헤더(api/main.py 미들웨어).
- 읽기는 DB 몇 줄을 읽는 가벼운 요청이라 남용 제한(throttle)을 걸지 않는다 — throttle 은 부를 때마다 기록을 쓰므로
  지도처럼 자주 여는 화면에 걸면 기록 테이블만 불어난다. 응답 크기는 LIMIT 으로 묶는다.
"""
from __future__ import annotations

import hashlib
import logging
import math
import re
import sqlite3
import threading
from datetime import date, datetime, timedelta
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field, ValidationError, field_validator

from api.deps import AdminDep, is_admin
from pipeline import db, regions_geo, regions_kr

log = logging.getLogger(__name__)
router = APIRouter(tags=["realestate-map"])

LAT_MIN, LAT_MAX, LNG_MIN, LNG_MAX = 33.0, 39.0, 124.0, 132.0
DEAL_TYPES = ("매매", "전세", "월세")
HOUSE_TYPES = ("아파트", "오피스텔", "빌라", "단독", "상가", "토지")
MAX_LISTINGS = 2000
MAX_NOTICES = 600

_LISTING_SCHEMA = """
CREATE TABLE IF NOT EXISTS re_listing (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  title          TEXT NOT NULL,
  deal_type      TEXT NOT NULL,
  house_type     TEXT NOT NULL,
  price_manwon   INTEGER,
  deposit_manwon INTEGER,
  monthly_manwon INTEGER,
  area_m2        REAL,
  floor          INTEGER,
  address        TEXT NOT NULL DEFAULT '',
  lat            REAL NOT NULL,
  lng            REAL NOT NULL,
  memo           TEXT NOT NULL DEFAULT '',
  contact        TEXT NOT NULL DEFAULT '',
  contact_public INTEGER NOT NULL DEFAULT 0,
  is_public      INTEGER NOT NULL DEFAULT 0,
  created_at     TEXT NOT NULL,
  updated_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_re_listing_public ON re_listing(is_public);
"""
_ready = {"done": False}
_ready_lock = threading.Lock()


def _now() -> str:
    return datetime.now(db.KST).isoformat(timespec="seconds")


def _conn() -> sqlite3.Connection:
    conn = db.connect()
    if not _ready["done"]:
        with _ready_lock:
            if not _ready["done"]:
                conn.executescript(_LISTING_SCHEMA)
                conn.commit()
                _ready["done"] = True
    return conn


def _safe_url(u: object) -> str:
    """http(s) 주소만 링크로 — javascript: 같은 주소가 팝업 링크로 들어가지 않게."""
    s = str(u or "").strip()
    return s if re.match(r"^https?://[^\s<>\"']+$", s) and len(s) <= 500 else ""


def _valid_ll(lat: object, lng: object) -> tuple[float, float] | None:
    try:
        la, ln = float(lat), float(lng)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if math.isfinite(la) and math.isfinite(ln) and LAT_MIN <= la <= LAT_MAX and LNG_MIN <= ln <= LNG_MAX:
        return la, ln
    return None


def _jitter(key: str, lat: float, lng: float) -> tuple[float, float]:
    """같은 시군구 중심에 여러 공고가 겹치지 않게 키에서 정해지는 작은 흔들림 (±약 0.9km) — 새로고침해도 같은 자리."""
    h = hashlib.sha1(key.encode("utf-8")).digest()
    dx = (h[0] / 255 - 0.5) * 0.016
    dy = (h[1] / 255 - 0.5) * 0.016
    return round(lat + dy, 6), round(lng + dx, 6)


# ───────────── 지역 (바로가기 + 시세 원) ─────────────

@router.get("/re/map/regions")
def map_regions() -> dict:
    items: list[dict] = []
    try:
        from pipeline import re_store  # 실거래가 수집기가 만드는 모듈 — 아직 없을 수 있다
        rows = re_store.region_price_summary(dataset="apt_trade", months=3) or []
    except Exception:  # noqa: BLE001 — 모듈·테이블이 없거나 실패하면 빈 시세로 (화면은 안내 띠를 보여 준다)
        log.debug("region_price_summary 를 쓸 수 없음", exc_info=True)
        rows = []
    for r in rows:
        try:
            code = str(r.get("lawd_cd") or "")
            ll = regions_geo.centroid(code)
            if not ll:
                continue
            deals = int(r.get("deals") or 0)
            if deals <= 0:
                continue
            med = r.get("median_price_manwon")
            per = r.get("median_per_3_3m2_manwon")
            items.append({
                "lawd_cd": code,
                "region": str(r.get("region") or regions_kr.NAMES.get(code, code))[:40],
                "sigungu": str(r.get("sigungu") or "")[:30],
                "deals": deals,
                "median_price_manwon": round(float(med)) if med is not None else None,
                "median_per_3_3m2_manwon": round(float(per)) if per is not None else None,
                "lat": ll[0], "lng": ll[1],
            })
        except (TypeError, ValueError, AttributeError):
            continue
    return {"groups": regions_geo.grouped(), "items": items, "months": 3}


# ───────────── 분양 (청약 공고) ─────────────

def _d(v: object) -> date | None:
    s = re.sub(r"[^0-9]", "", str(v or ""))[:8]
    if len(s) != 8:
        return None
    try:
        return date(int(s[:4]), int(s[4:6]), int(s[6:]))
    except ValueError:
        return None


def _status(start: date | None, end: date | None, today: date) -> str:
    if end and today > end:
        return "마감"
    if start and today < start:
        return "예정"
    if start or end:
        return "접수중"
    return "예정"


@router.get("/re/map/apply")
def map_apply(region: str = Query("", max_length=20), status: str = Query("", max_length=10)) -> dict:
    if status and status not in ("예정", "접수중", "마감"):
        raise HTTPException(status_code=400, detail="상태는 예정·접수중·마감 중 하나입니다.")
    sidos = {s for s, _ in regions_kr.REGIONS}
    if region and region not in sidos and region not in regions_kr.NAMES:
        raise HTTPException(status_code=400, detail="지원하지 않는 지역입니다.")
    today = datetime.now(db.KST).date()
    since = today - timedelta(days=90)  # 마감된 지 석 달 지난 공고는 지도에서 뺀다
    try:
        conn = db.connect()
        try:
            rows = [dict(r) for r in conn.execute(
                "SELECT notice_id, name, house_type, address, lawd_cd, region, households, notice_date, receipt_start, "
                "receipt_end, winner_date, url, lat, lng FROM re_apply_notice "
                "ORDER BY COALESCE(receipt_start, notice_date) DESC LIMIT ?", (MAX_NOTICES * 3,)).fetchall()]
        finally:
            conn.close()
    except Exception:  # noqa: BLE001 — 테이블이 아직 없으면 빈 목록
        log.debug("re_apply_notice 를 읽을 수 없음", exc_info=True)
        rows = []
    out = []
    for r in rows:
        start, end = _d(r.get("receipt_start")), _d(r.get("receipt_end"))
        if end and end < since:
            continue
        st = _status(start, end, today)
        if status and st != status:
            continue
        code = str(r.get("lawd_cd") or "")[:5]
        if code not in regions_kr.NAMES:
            code = regions_geo.lawd_for_address(str(r.get("address") or "")) or ""
        reg_name = regions_kr.NAMES.get(code, str(r.get("region") or ""))
        if region:
            if region in regions_kr.NAMES and code != region:
                continue
            if region in sidos and not (reg_name.startswith(region + " ") or str(r.get("region") or "").startswith(region)):
                continue
        ll = _valid_ll(r.get("lat"), r.get("lng"))
        approx = False
        if not ll:
            c = regions_geo.centroid(code) if code else None
            if not c:
                continue  # 위치를 모르는 공고는 목록에도 지도에도 안 찍는다 (엉뚱한 곳에 찍지 않게)
            ll, approx = _jitter(str(r.get("notice_id")), *c), True
        try:
            households = int(r["households"]) if r.get("households") not in (None, "") else None
        except (TypeError, ValueError):
            households = None
        out.append({
            "id": str(r.get("notice_id") or "")[:60],
            "name": str(r.get("name") or "")[:120],
            "house_type": str(r.get("house_type") or "")[:30],
            "address": str(r.get("address") or "")[:200],
            "lawd_cd": code, "region": reg_name[:40],
            "households": households,
            "notice_date": win.isoformat() if (win := _d(r.get("notice_date"))) else "",
            "receipt_start": start.isoformat() if start else "",
            "receipt_end": end.isoformat() if end else "",
            "winner_date": wd.isoformat() if (wd := _d(r.get("winner_date"))) else "",
            "url": _safe_url(r.get("url")),
            "status": st, "lat": ll[0], "lng": ll[1], "approx": approx,
        })
        if len(out) >= MAX_NOTICES:
            break
    # 접수중(곧 끝나는 순) → 예정(곧 시작하는 순) → 마감(최근에 끝난 순)
    live = sorted((x for x in out if x["status"] == "접수중"), key=lambda x: x["receipt_end"] or "9")
    soon = sorted((x for x in out if x["status"] == "예정"), key=lambda x: x["receipt_start"] or "9")
    closed = sorted((x for x in out if x["status"] == "마감"), key=lambda x: x["receipt_end"], reverse=True)
    out = live + soon + closed
    return {"items": out, "today": today.isoformat()}


# ───────────── 매물 (직접 등록) ─────────────

class ListingIn(BaseModel):
    title: str = Field(min_length=1, max_length=80)
    deal_type: Literal["매매", "전세", "월세"]
    house_type: Literal["아파트", "오피스텔", "빌라", "단독", "상가", "토지"]
    price_manwon: Optional[int] = Field(None, ge=0, le=10_000_000)      # 1,000억까지
    deposit_manwon: Optional[int] = Field(None, ge=0, le=10_000_000)
    monthly_manwon: Optional[int] = Field(None, ge=0, le=100_000)       # 월 10억까지
    area_m2: Optional[float] = Field(None, gt=0, le=1_000_000)
    floor: Optional[int] = Field(None, ge=-10, le=200)
    address: str = Field("", max_length=200)
    lat: float = Field(ge=LAT_MIN, le=LAT_MAX)
    lng: float = Field(ge=LNG_MIN, le=LNG_MAX)
    memo: str = Field("", max_length=1000)
    contact: str = Field("", max_length=100)
    contact_public: bool = False
    is_public: bool = False

    model_config = {"extra": "forbid"}

    @field_validator("title", "address", "memo", "contact")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", v or "").strip()
        return v

    @field_validator("area_m2", "lat", "lng")
    @classmethod
    def _finite(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and not math.isfinite(v):
            raise ValueError("숫자가 올바르지 않습니다")
        return v

    def check(self) -> "ListingIn":
        if not self.title:
            raise HTTPException(status_code=400, detail="제목을 입력해 주세요.")
        if self.deal_type == "매매" and not self.price_manwon:
            raise HTTPException(status_code=400, detail="매매가를 입력해 주세요.")
        if self.deal_type == "전세" and not self.deposit_manwon:
            raise HTTPException(status_code=400, detail="전세 보증금을 입력해 주세요.")
        if self.deal_type == "월세" and (self.deposit_manwon is None or not self.monthly_manwon):
            raise HTTPException(status_code=400, detail="월세는 보증금과 월세를 입력해 주세요.")
        if self.contact_public and not self.contact:
            self.contact_public = False
        return self


class ListingPatch(BaseModel):
    """수정 — 보낸 칸만 바꾼다 (지도에서 핀을 끌어 옮기면 lat·lng 만 온다)."""
    title: Optional[str] = None
    deal_type: Optional[str] = None
    house_type: Optional[str] = None
    price_manwon: Optional[int] = None
    deposit_manwon: Optional[int] = None
    monthly_manwon: Optional[int] = None
    area_m2: Optional[float] = None
    floor: Optional[int] = None
    address: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    memo: Optional[str] = None
    contact: Optional[str] = None
    contact_public: Optional[bool] = None
    is_public: Optional[bool] = None

    model_config = {"extra": "forbid"}


_COLS = ("title", "deal_type", "house_type", "price_manwon", "deposit_manwon", "monthly_manwon", "area_m2", "floor",
         "address", "lat", "lng", "memo", "contact", "contact_public", "is_public")


def _row_out(r: dict, admin: bool) -> dict:
    d = {k: r[k] for k in ("id", "title", "deal_type", "house_type", "price_manwon", "deposit_manwon", "monthly_manwon",
                           "area_m2", "floor", "address", "lat", "lng", "updated_at")}
    d["is_public"] = bool(r["is_public"])
    if admin:
        d.update(memo=r["memo"], contact=r["contact"], contact_public=bool(r["contact_public"]), created_at=r["created_at"])
    elif r["contact_public"] and r["contact"]:
        d["contact"] = r["contact"]
    return d


def _get(conn: sqlite3.Connection, lid: int) -> dict:
    r = conn.execute("SELECT * FROM re_listing WHERE id=?", (lid,)).fetchone()
    if not r:
        raise HTTPException(status_code=404, detail="매물을 찾을 수 없습니다.")
    return dict(r)


def _values(m: ListingIn) -> tuple:
    d = m.model_dump()
    d["contact_public"] = int(bool(d["contact_public"]))
    d["is_public"] = int(bool(d["is_public"]))
    if d["deal_type"] == "매매":
        d["deposit_manwon"] = d["monthly_manwon"] = None
    elif d["deal_type"] == "전세":
        d["price_manwon"] = d["monthly_manwon"] = None
    else:
        d["price_manwon"] = None
    return tuple(d[k] for k in _COLS)


@router.get("/re/map/listings")
def list_listings(request: Request) -> dict:
    admin = is_admin(request)
    conn = _conn()
    try:
        sql = "SELECT * FROM re_listing" + ("" if admin else " WHERE is_public=1") + " ORDER BY updated_at DESC LIMIT ?"
        rows = [dict(r) for r in conn.execute(sql, (MAX_LISTINGS,)).fetchall()]
    finally:
        conn.close()
    return {"admin": admin, "items": [_row_out(r, admin) for r in rows]}


@router.post("/re/map/listings", dependencies=[AdminDep])
def create_listing(body: ListingIn) -> dict:
    body.check()
    now = _now()
    conn = _conn()
    try:
        n = conn.execute("SELECT COUNT(*) FROM re_listing").fetchone()[0]
        if n >= MAX_LISTINGS:
            raise HTTPException(status_code=400, detail=f"매물은 {MAX_LISTINGS}개까지 등록할 수 있습니다.")
        cur = conn.execute(
            f"INSERT INTO re_listing ({', '.join(_COLS)}, created_at, updated_at) VALUES ({', '.join('?' * (len(_COLS) + 2))})",
            (*_values(body), now, now))
        conn.commit()
        return _row_out(_get(conn, int(cur.lastrowid)), True)
    finally:
        conn.close()


@router.put("/re/map/listings/{lid}", dependencies=[AdminDep])
def update_listing(lid: int, body: ListingPatch) -> dict:
    conn = _conn()
    try:
        cur = _get(conn, lid)
        merged = {k: cur[k] for k in _COLS}
        merged["contact_public"], merged["is_public"] = bool(merged["contact_public"]), bool(merged["is_public"])
        merged.update(body.model_dump(exclude_unset=True))
        try:
            m = ListingIn(**merged)
        except ValidationError as e:
            raise HTTPException(status_code=422, detail="입력값이 올바르지 않습니다.") from e
        m.check()
        conn.execute(f"UPDATE re_listing SET {', '.join(f'{k}=?' for k in _COLS)}, updated_at=? WHERE id=?",
                     (*_values(m), _now(), lid))
        conn.commit()
        return _row_out(_get(conn, lid), True)
    finally:
        conn.close()


@router.delete("/re/map/listings/{lid}", dependencies=[AdminDep])
def delete_listing(lid: int) -> dict:
    conn = _conn()
    try:
        _get(conn, lid)
        conn.execute("DELETE FROM re_listing WHERE id=?", (lid,))
        conn.commit()
    finally:
        conn.close()
    return {"ok": True}
