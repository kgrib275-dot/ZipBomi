"""부동산 데이터 저장소 — 테이블 정의·저장·조회 (수집은 redata.py / re_sources.py, 설정은 config/re_datasets.yaml).

테이블 (모두 CREATE TABLE IF NOT EXISTS — 키가 없어도 만들어 두어 화면·지도가 빈 표를 조회할 수 있다)
- rtms_<데이터셋>   국토교통부 실거래가 (아파트 매매·전월세 등 데이터셋마다 한 표). 한 시군구·한 달(lawd_cd, deal_ymd)을
                    받을 때마다 그 칸을 통째로 바꿔 넣는다 — 해제·정정 신고가 늦게 반영돼도 중복이 생기지 않는다.
                    uid = 원본 항목 전체의 해시(+같은 항목이 여러 번이면 순번). 원본 항목은 raw(JSON)에 모두 남긴다.
- re_apply_notice   청약 분양공고 (청약홈 API + LH 청약플러스 공고 목록). 지도 기능과 약속한 열 이름을 지킨다.
- re_apply_model    공고별 주택형(전용면적)·공급세대·분양 최고가
- re_apply_cmpet    공고별 주택형·순위·거주지역 경쟁률
- re_apply_score    APT 당첨가점 (최저·최고·평균)
- re_base_rate      한국은행 기준금리 변경 이력
- re_econ_series    월별 지표 (주담대 금리·KB 가격지수·지가변동률 — 한국은행 ECOS)
- re_fetch_log      데이터셋·시군구·달별로 언제 몇 건 받았는지 (이어 받기·적용 범위 계산)
- re_dataset_conf   관리 화면에서 바꾼 켜기/끄기·과거 채우기 개월 수 (yaml 기본값보다 우선)
- re_dataset_state  데이터셋별 마지막 실행·상태·오류
"""
from __future__ import annotations

import hashlib
import json
import re
import statistics
import threading
from datetime import date, datetime
from pathlib import Path

import yaml

from pipeline import db, regions_kr

CONFIG_FILE = db.ROOT / "config" / "re_datasets.yaml"
PYEONG = 3.305785
_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{1,30}$")

STATUS_LABELS = {"no_key": "키 없음", "not_registered": "활용신청 필요", "ok": "정상", "off": "꺼짐",
                 "error": "오류", "pending": "대기", "limit": "한도 도달"}


# ───────────────────────── 설정 ─────────────────────────

_cfg_cache: dict = {}


def load_config() -> dict:
    """re_datasets.yaml (파일이 바뀔 때만 다시 읽는다)."""
    try:
        st = CONFIG_FILE.stat()
    except FileNotFoundError:
        return {"defaults": {}, "datasets": [], "rejected": []}
    sig = (st.st_mtime_ns, st.st_size)
    if _cfg_cache.get("sig") != sig:
        raw = yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8")) or {}
        ds = [d for d in raw.get("datasets") or [] if isinstance(d, dict) and _KEY_RE.match(str(d.get("key", "")))]
        _cfg_cache.update(sig=sig, cfg={"defaults": raw.get("defaults") or {}, "datasets": ds,
                                        "rejected": raw.get("rejected") or []})
    return _cfg_cache["cfg"]


def defaults() -> dict:
    d = {"backfill_months": 24, "refresh_months": 3, "daily_cap": 9000, "max_minutes_per_run": 150, "delay_sec": 0.2}
    d.update(load_config()["defaults"])
    d["daily_cap"] = min(int(d["daily_cap"]), 9000)
    return d


def datasets() -> list[dict]:
    """yaml 목록 + 관리 화면에서 바꾼 값(re_dataset_conf)."""
    conf = {r["key"]: r for r in _rows("SELECT * FROM re_dataset_conf")}
    base = defaults()
    out = []
    for d in load_config()["datasets"]:
        d = dict(d)
        d.setdefault("backfill_months", base["backfill_months"])
        d["daily_cap"] = min(int(d.get("daily_cap", base["daily_cap"])), 9000)
        c = conf.get(d["key"])
        if c:
            if c["enabled"] is not None:
                d["enabled"] = bool(c["enabled"])
            if c["backfill_months"]:
                d["backfill_months"] = int(c["backfill_months"])
        d["enabled"] = bool(d.get("enabled", True))
        if d.get("data_id"):
            d["data_url"] = f"https://www.data.go.kr/data/{d['data_id']}/openapi.do"
        out.append(d)
    return out


def dataset(key: str) -> dict | None:
    return next((d for d in datasets() if d["key"] == key), None)


def rtms_keys() -> list[str]:
    return [d["key"] for d in load_config()["datasets"] if d.get("group") == "rtms"]


def set_conf(key: str, enabled: bool | None = None, backfill_months: int | None = None) -> None:
    with _conn() as conn:
        conn.execute("INSERT INTO re_dataset_conf (key, enabled, backfill_months, updated_at) VALUES (?,?,?,?) "
                     "ON CONFLICT(key) DO UPDATE SET enabled=COALESCE(excluded.enabled, enabled), "
                     "backfill_months=COALESCE(excluded.backfill_months, backfill_months), updated_at=excluded.updated_at",
                     (key, None if enabled is None else int(enabled), backfill_months, _now()))


# ───────────────────────── 스키마 ─────────────────────────

_RTMS_COLS = ("lawd_cd TEXT NOT NULL, deal_ymd TEXT NOT NULL, uid TEXT NOT NULL, deal_date TEXT, umd TEXT, jibun TEXT, "
              "name TEXT, kind TEXT, area REAL, land_area REAL, floor INTEGER, build_year INTEGER, amount INTEGER, "
              "deposit INTEGER, monthly_rent INTEGER, deal_type TEXT, cancelled INTEGER NOT NULL DEFAULT 0, "
              "contract_type TEXT, contract_term TEXT, raw TEXT NOT NULL, fetched_at TEXT NOT NULL, "
              "PRIMARY KEY (lawd_cd, deal_ymd, uid)")

_SCHEMA = [
    # ── 지도 기능과의 약속: 열 이름·뜻을 바꾸지 않는다 (notice_id … fetched_at). 뒤의 열은 이 모듈이 더 쓰는 것.
    "CREATE TABLE IF NOT EXISTS re_apply_notice (notice_id TEXT PRIMARY KEY, name TEXT, house_type TEXT, address TEXT, "
    "lawd_cd TEXT, region TEXT, households INTEGER, notice_date TEXT, receipt_start TEXT, receipt_end TEXT, "
    "winner_date TEXT, url TEXT, lat REAL, lng REAL, raw TEXT, fetched_at TEXT, "
    "source TEXT, category TEXT, status TEXT, contract_start TEXT, contract_end TEXT, move_in_ym TEXT, "
    "builder TEXT, house_manage_no TEXT, pblanc_no TEXT, op TEXT)",
    "CREATE INDEX IF NOT EXISTS ix_re_apply_notice_end ON re_apply_notice(receipt_end)",
    "CREATE INDEX IF NOT EXISTS ix_re_apply_notice_lawd ON re_apply_notice(lawd_cd)",
    "CREATE INDEX IF NOT EXISTS ix_re_apply_notice_date ON re_apply_notice(notice_date)",
    "CREATE TABLE IF NOT EXISTS re_apply_model (notice_id TEXT NOT NULL, model_no TEXT NOT NULL, house_ty TEXT NOT NULL, "
    "area REAL, households INTEGER, special_households INTEGER, top_amount INTEGER, raw TEXT, fetched_at TEXT, "
    "PRIMARY KEY (notice_id, model_no, house_ty))",
    "CREATE TABLE IF NOT EXISTS re_apply_cmpet (notice_id TEXT NOT NULL, model_no TEXT NOT NULL, house_ty TEXT NOT NULL, "
    "rank TEXT NOT NULL, reside TEXT NOT NULL, households INTEGER, req_cnt INTEGER, rate TEXT, raw TEXT, fetched_at TEXT, "
    "PRIMARY KEY (notice_id, model_no, house_ty, rank, reside))",
    "CREATE TABLE IF NOT EXISTS re_apply_score (notice_id TEXT NOT NULL, model_no TEXT NOT NULL, house_ty TEXT NOT NULL, "
    "reside TEXT NOT NULL, low REAL, top REAL, avg REAL, raw TEXT, fetched_at TEXT, "
    "PRIMARY KEY (notice_id, model_no, house_ty, reside))",
    "CREATE TABLE IF NOT EXISTS re_base_rate (changed_on TEXT PRIMARY KEY, rate REAL NOT NULL, fetched_at TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS re_econ_series (series TEXT NOT NULL, period TEXT NOT NULL, value REAL, name TEXT, "
    "unit TEXT, fetched_at TEXT NOT NULL, PRIMARY KEY (series, period))",
    "CREATE TABLE IF NOT EXISTS re_fetch_log (dataset TEXT NOT NULL, lawd_cd TEXT NOT NULL, deal_ymd TEXT NOT NULL, "
    "rows INTEGER NOT NULL, calls INTEGER NOT NULL DEFAULT 1, fetched_at TEXT NOT NULL, PRIMARY KEY (dataset, lawd_cd, deal_ymd))",
    "CREATE TABLE IF NOT EXISTS re_dataset_conf (key TEXT PRIMARY KEY, enabled INTEGER, backfill_months INTEGER, updated_at TEXT)",
    "CREATE TABLE IF NOT EXISTS re_dataset_state (key TEXT PRIMARY KEY, status TEXT, message TEXT, last_run_at TEXT, "
    "last_ok_at TEXT, last_error_at TEXT, last_error TEXT, last_rows INTEGER, cursor TEXT)",
    "CREATE TABLE IF NOT EXISTS re_api_calls (api TEXT NOT NULL, day TEXT NOT NULL, n INTEGER NOT NULL DEFAULT 0, "
    "PRIMARY KEY (api, day))",
]

_ready: set = set()
_ready_lock = threading.Lock()


def table(key: str) -> str:
    if not _KEY_RE.match(key):
        raise ValueError("잘못된 데이터셋 키")
    return f"rtms_{key}"


def ensure_schema(conn=None) -> None:
    """모든 표를 만든다 (DB 파일마다 한 번)."""
    path = str(db.DB_PATH)
    if path in _ready:
        return
    with _ready_lock:
        if path in _ready:
            return
        own = conn is None
        conn = conn or db.connect()
        try:
            for sql in _SCHEMA:
                conn.execute(sql)
            for key in rtms_keys():
                t = table(key)
                conn.execute(f"CREATE TABLE IF NOT EXISTS {t} ({_RTMS_COLS})")
                conn.execute(f"CREATE INDEX IF NOT EXISTS ix_{t}_lawd_ymd ON {t}(lawd_cd, deal_ymd)")
                conn.execute(f"CREATE INDEX IF NOT EXISTS ix_{t}_ymd ON {t}(deal_ymd)")
            conn.commit()
        finally:
            if own:
                conn.close()
        _ready.add(path)


class _Conn:
    def __enter__(self):
        ensure_schema()
        self.c = db.connect()
        return self.c

    def __exit__(self, et, ev, tb):
        try:
            if et is None:
                self.c.commit()
        finally:
            self.c.close()


def _conn() -> _Conn:
    return _Conn()


def _rows(sql: str, params: tuple = ()) -> list[dict]:
    with _conn() as c:
        return [dict(r) for r in c.execute(sql, params).fetchall()]


def _now() -> str:
    return datetime.now(db.KST).isoformat(timespec="seconds")


# ───────────────────────── 값 정리 ─────────────────────────

def to_int(s) -> int | None:
    try:
        return int(float(str(s).replace(",", "").strip()))
    except (TypeError, ValueError):
        return None


def to_float(s) -> float | None:
    try:
        return float(str(s).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def to_date(s) -> str | None:
    """'2026-10-30' · '20261030' · '2026.10.30' → '2026-10-30'."""
    d = re.sub(r"\D", "", str(s or ""))
    if len(d) >= 8:
        return f"{d[:4]}-{d[4:6]}-{d[6:8]}"
    return None


def _first(it: dict, *keys: str) -> str:
    for k in keys:
        v = (it.get(k) or "").strip()
        if v:
            return v
    return ""


def rtms_row(it: dict) -> dict:
    """RTMS 항목(모든 태그 dict) → 공통 열. 데이터셋마다 태그 이름이 달라 후보를 차례로 본다."""
    y, m, d = to_int(it.get("dealYear")), to_int(it.get("dealMonth")), to_int(it.get("dealDay"))
    return {
        "deal_date": f"{y:04d}-{m:02d}-{d:02d}" if y and m and d else None,
        "umd": _first(it, "umdNm"), "jibun": _first(it, "jibun"),
        "name": _first(it, "aptNm", "offiNm", "mhouseNm"),
        "kind": _first(it, "houseType", "ownershipGbn", "buildingUse", "jimok", "buildingType"),
        "area": to_float(_first(it, "excluUseAr", "totalFloorAr", "buildingAr", "dealArea")),
        "land_area": to_float(_first(it, "landAr", "plottageAr")),
        "floor": to_int(it.get("floor")), "build_year": to_int(it.get("buildYear")),
        "amount": to_int(it.get("dealAmount")), "deposit": to_int(it.get("deposit")),
        "monthly_rent": to_int(it.get("monthlyRent")),
        "deal_type": _first(it, "dealingGbn"), "cancelled": 1 if (it.get("cdealType") or "").strip() == "O" else 0,
        "contract_type": _first(it, "contractType"), "contract_term": _first(it, "contractTerm"),
    }


def replace_partition(key: str, lawd: str, ymd: str, items: list[dict], calls: int) -> int:
    """한 시군구·한 달을 통째로 바꿔 넣는다 (같은 거래가 두 번 들어가지 않게)."""
    t = table(key)
    at = _now()
    seen: dict[str, int] = {}
    rows = []
    for it in items:
        raw = json.dumps(it, ensure_ascii=False, sort_keys=True)
        h = hashlib.sha1(raw.encode()).hexdigest()[:20]
        n = seen.get(h, 0)
        seen[h] = n + 1
        uid = h if n == 0 else f"{h}-{n}"
        r = rtms_row(it)
        rows.append((lawd, ymd, uid, r["deal_date"], r["umd"], r["jibun"], r["name"], r["kind"], r["area"], r["land_area"],
                     r["floor"], r["build_year"], r["amount"], r["deposit"], r["monthly_rent"], r["deal_type"],
                     r["cancelled"], r["contract_type"], r["contract_term"], raw, at))
    with _conn() as c:
        c.execute(f"DELETE FROM {t} WHERE lawd_cd=? AND deal_ymd=?", (lawd, ymd))
        c.executemany(f"INSERT OR REPLACE INTO {t} (lawd_cd, deal_ymd, uid, deal_date, umd, jibun, name, kind, area, land_area, "
                      "floor, build_year, amount, deposit, monthly_rent, deal_type, cancelled, contract_type, contract_term, "
                      "raw, fetched_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        c.execute("INSERT INTO re_fetch_log (dataset, lawd_cd, deal_ymd, rows, calls, fetched_at) VALUES (?,?,?,?,?,?) "
                  "ON CONFLICT(dataset, lawd_cd, deal_ymd) DO UPDATE SET rows=excluded.rows, calls=excluded.calls, "
                  "fetched_at=excluded.fetched_at", (key, lawd, ymd, len(rows), calls, at))
    return len(rows)


def fetched_parts(key: str) -> dict[tuple[str, str], str]:
    """{(lawd, ymd): 받은 시각}."""
    return {(r["lawd_cd"], r["deal_ymd"]): r["fetched_at"]
            for r in _rows("SELECT lawd_cd, deal_ymd, fetched_at FROM re_fetch_log WHERE dataset=?", (key,))}


# ───────────────────────── 상태 ─────────────────────────

def set_state(key: str, status: str, message: str = "", rows: int | None = None, ok: bool | None = None,
              error: str | None = None, cursor: str | None = None) -> None:
    at = _now()
    with _conn() as c:
        c.execute("INSERT INTO re_dataset_state (key, status, message, last_run_at, last_ok_at, last_error_at, last_error, "
                  "last_rows, cursor) VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET status=excluded.status, "
                  "message=excluded.message, last_run_at=excluded.last_run_at, "
                  "last_ok_at=COALESCE(excluded.last_ok_at, last_ok_at), "
                  "last_error_at=COALESCE(excluded.last_error_at, last_error_at), "
                  "last_error=COALESCE(excluded.last_error, last_error), "
                  "last_rows=COALESCE(excluded.last_rows, last_rows), cursor=COALESCE(excluded.cursor, cursor)",
                  (key, status, message[:500], at, at if ok else None, at if error else None,
                   error[:500] if error else None, rows, cursor))


def states() -> dict[str, dict]:
    return {r["key"]: r for r in _rows("SELECT * FROM re_dataset_state")}


def coverage() -> dict[str, dict]:
    """데이터셋별 받은 칸 수·행 수·처음/마지막 달 (re_fetch_log)."""
    out = {r["dataset"]: r for r in _rows(
        "SELECT dataset, COUNT(*) AS parts, SUM(rows) AS rows, MIN(deal_ymd) AS ymd_from, MAX(deal_ymd) AS ymd_to, "
        "COUNT(DISTINCT lawd_cd) AS regions, MAX(fetched_at) AS last_fetch FROM re_fetch_log GROUP BY dataset")}
    return out


def table_counts() -> dict[str, int]:
    """키 없이 받는 데이터셋·청약 표의 행 수 (관리 화면용)."""
    q = {
        "bok_base_rate": "SELECT COUNT(*) FROM re_base_rate",
        "lh_notice": "SELECT COUNT(*) FROM re_apply_notice WHERE source='lh'",
        "apply_notice": "SELECT COUNT(*) FROM re_apply_notice WHERE source='applyhome'",
        "apply_model": "SELECT COUNT(*) FROM re_apply_model",
        "apply_cmpet": "SELECT (SELECT COUNT(*) FROM re_apply_cmpet) + (SELECT COUNT(*) FROM re_apply_score)",
    }
    out = {}
    with _conn() as c:
        for k, sql in q.items():
            out[k] = c.execute(sql).fetchone()[0]
        for d in load_config()["datasets"]:
            if d.get("group") == "ecos":
                ids = [s["id"] for s in d.get("series") or []]
                if ids:
                    out[d["key"]] = c.execute(f"SELECT COUNT(*) FROM re_econ_series WHERE series IN ({','.join('?' * len(ids))})",
                                              ids).fetchone()[0]
    return out


def calls_today() -> dict[str, int]:
    day = datetime.now(db.KST).strftime("%Y-%m-%d")
    return {r["api"]: r["n"] for r in _rows("SELECT api, n FROM re_api_calls WHERE day=?", (day,))}


# ───────────────────────── 지역 (주소 → 시군구 코드) ─────────────────────────

SIDO_SHORT = {
    "서울특별시": "서울", "서울시": "서울", "부산광역시": "부산", "대구광역시": "대구", "인천광역시": "인천", "광주광역시": "광주",
    "대전광역시": "대전", "울산광역시": "울산", "세종특별자치시": "세종", "세종시": "세종", "경기도": "경기",
    "강원도": "강원", "강원특별자치도": "강원", "충청북도": "충북", "충청남도": "충남", "전라북도": "전북",
    "전북특별자치도": "전북", "전라남도": "전남", "경상북도": "경북", "경상남도": "경남", "제주특별자치도": "제주", "제주도": "제주",
    "전남광주통합특별시": "전남광주", "전국": "전국",  # LH 목록에 실제로 나오는 표기 (2026-11 확인)
}
_SHORTS = set(SIDO_SHORT.values())
_SIDO_ITEMS = {sido: items for sido, items in regions_kr.REGIONS}


# 2026-11 실거래가 공개시스템이 광주를 '전남광주통합특별시'로 표기한다 — 뒤의 구 이름이 광주 구면 광주, 아니면 전남.
# (목록에 광주광역시가 없어 예전엔 광주 거래가 모두 '지원 지역 밖'이 됐다)
MERGED_GJ = "전남광주통합특별시"
_GJ_GU = {"동구", "서구", "남구", "북구", "광산구"}


def sido_of(text: str) -> str | None:
    t = (text or "").strip()
    if not t:
        return None
    toks = t.split()
    first = toks[0]
    if first == MERGED_GJ:
        return "광주" if len(toks) < 2 or toks[1] in _GJ_GU else "전남"
    if first in SIDO_SHORT:
        return SIDO_SHORT[first]
    if first in _SHORTS:
        return first
    for long, short in SIDO_SHORT.items():
        if t.startswith(long):
            return short
    return None


def lawd_from_address(address: str, sido_hint: str | None = None) -> tuple[str | None, str | None]:
    """주소 → (시군구 5자리 코드, 시도). regions_kr 목록의 이름과 겹치는 것이 정확히 하나일 때만 코드를 준다."""
    addr = re.sub(r"\s+", " ", (address or "").strip())
    sido = sido_of(addr) or (sido_of(sido_hint or "") if sido_hint else None)
    if not sido:
        return None, None
    items = _SIDO_ITEMS.get(sido)
    if not items:
        return None, sido
    if len(items) == 1:  # 세종
        return items[0][0], sido
    toks = addr.split()
    if toks and (toks[0] in SIDO_SHORT or toks[0] in _SHORTS or toks[0] == MERGED_GJ):
        toks = toks[1:]
    head = toks[:3]
    hits = [code for code, name in items if all(p in head for p in name.split())]
    if len(hits) > 1:  # '수원시'만 맞는 것 말고 구까지 맞는 것이 하나면 그것
        best = [code for code, name in items if code in hits and len(name.split()) > 1]
        hits = best if len(best) == 1 else hits
    return (hits[0] if len(hits) == 1 else None), sido


# ───────────────────────── 청약 공고 저장 ─────────────────────────

_NOTICE_COLS = ("notice_id", "name", "house_type", "address", "lawd_cd", "region", "households", "notice_date",
                "receipt_start", "receipt_end", "winner_date", "url", "raw", "fetched_at", "source", "category", "status",
                "contract_start", "contract_end", "move_in_ym", "builder", "house_manage_no", "pblanc_no", "op")


def upsert_notices(rows: list[dict]) -> int:
    if not rows:
        return 0
    at = _now()
    from .db import safe_url
    # 공고 원문 주소는 http(s) 만 (2026-11-03) — 외부 자료가 javascript: 주소를 넣어도 화면 링크로 실행되지 않게
    rows = [{**r, "url": safe_url(r.get("url")) or None} for r in rows]
    cols = ", ".join(_NOTICE_COLS)
    upd = ", ".join(f"{c}=excluded.{c}" for c in _NOTICE_COLS if c != "notice_id")
    vals = [tuple((r.get(c) if c != "fetched_at" else at) for c in _NOTICE_COLS) for r in rows]
    with _conn() as c:
        # lat·lng 는 건드리지 않는다 (지도 기능이 채울 수 있다)
        c.executemany(f"INSERT INTO re_apply_notice ({cols}) VALUES ({','.join('?' * len(_NOTICE_COLS))}) "
                      f"ON CONFLICT(notice_id) DO UPDATE SET {upd}", vals)
        # 예전에 검사 없이 저장된 주소도 정리한다
        c.execute("UPDATE re_apply_notice SET url=NULL WHERE url IS NOT NULL AND url NOT LIKE 'http://%' AND url NOT LIKE 'https://%'")
    return len(rows)


def upsert_many(tbl: str, cols: tuple[str, ...], rows: list[tuple]) -> int:
    if not rows:
        return 0
    if tbl not in ("re_apply_model", "re_apply_cmpet", "re_apply_score", "re_base_rate", "re_econ_series"):
        raise ValueError(tbl)
    with _conn() as c:
        c.executemany(f"INSERT OR REPLACE INTO {tbl} ({', '.join(cols)}) VALUES ({','.join('?' * len(cols))})", rows)
    return len(rows)


# ───────────────────────── 조회 (화면·지도) ─────────────────────────

def shift_ymd(ymd: str, k: int) -> str:
    n = int(ymd[:4]) * 12 + int(ymd[4:]) - 1 + k
    return f"{n // 12:04d}{n % 12 + 1:02d}"


def this_ymd() -> str:
    t = date.today()
    return f"{t.year:04d}{t.month:02d}"


def _is_rent(key: str) -> bool:
    return key.endswith("_rent")


def _price(key: str, r: dict) -> int | None:
    """대표 가격(만원): 매매는 거래가, 전월세는 전세(월세 0) 보증금."""
    if _is_rent(key):
        return r["deposit"] if (r["monthly_rent"] or 0) == 0 else None
    return r["amount"]


def region_price_summary(dataset: str = "apt_trade", months: int = 3) -> list[dict]:
    """지도용 — 최근 months 개월(이번 달 포함) 시군구별 거래 수·중위 가격·3.3㎡당 중위 가격 (만원). 자료가 없으면 [].

    전월세 데이터셋은 전세(월세 0) 보증금 기준. apt_trade 는 배치 표가 비어 있는 시군구에 한해 화면 조회 캐시(re_apt_trade)도 쓴다.
    해제 신고된 거래는 뺀다.
    """
    if dataset not in rtms_keys():
        return []
    months = max(1, min(int(months or 3), 36))
    start = shift_ymd(this_ymd(), -(months - 1))
    t = table(dataset)
    by: dict[str, list[tuple[float, float | None]]] = {}
    with _conn() as c:
        for r in c.execute(f"SELECT lawd_cd, amount, deposit, monthly_rent, area FROM {t} "
                           "WHERE deal_ymd >= ? AND cancelled = 0", (start,)):
            p = _price(dataset, dict(r))
            if not p:
                continue
            a = r["area"]
            by.setdefault(r["lawd_cd"], []).append((p, p / a * PYEONG if a and a > 0 else None))
        if dataset == "apt_trade":
            try:
                cache = c.execute("SELECT lawd_cd, rows FROM re_apt_trade WHERE deal_ymd >= ?", (start,)).fetchall()
            except Exception:  # noqa: BLE001 - 화면 캐시 표가 아직 없으면 건너뛴다
                cache = []
            extra: dict[str, list] = {}
            for r in cache:
                if r["lawd_cd"] in by:
                    continue
                try:
                    for x in json.loads(r["rows"]):
                        if not x.get("cancelled") and x.get("amount") and x.get("area"):
                            extra.setdefault(r["lawd_cd"], []).append((x["amount"], x["amount"] / x["area"] * PYEONG))
                except (ValueError, TypeError):
                    continue
            by.update(extra)
    out = []
    for lawd, vals in sorted(by.items()):
        name = regions_kr.NAMES.get(lawd, "")
        sido, _, sgg = name.partition(" ")
        pps = [v for _, v in vals if v]
        out.append({"lawd_cd": lawd, "region": sido or None, "sigungu": sgg or None, "deals": len(vals),
                    "median_price_manwon": round(statistics.median(p for p, _ in vals)),
                    "median_per_3_3m2_manwon": round(statistics.median(pps)) if pps else None})
    return out


_PUBLIC_COLS = ("deal_date", "umd", "jibun", "name", "kind", "area", "land_area", "floor", "build_year", "amount", "deposit",
                "monthly_rent", "deal_type", "cancelled", "contract_type", "contract_term")


def month_rows(key: str, lawd: str, ymd: str, limit: int = 5000) -> tuple[list[dict], str | None]:
    """한 데이터셋·시군구·달의 행 (공통 열 + 화면에 쓸 만한 원본 몇 개) 과 받은 시각."""
    t = table(key)
    with _conn() as c:
        rows = c.execute(f"SELECT {', '.join(_PUBLIC_COLS)}, raw FROM {t} WHERE lawd_cd=? AND deal_ymd=? "
                         "ORDER BY deal_date DESC LIMIT ?", (lawd, ymd, limit)).fetchall()
        log = c.execute("SELECT fetched_at FROM re_fetch_log WHERE dataset=? AND lawd_cd=? AND deal_ymd=?",
                        (key, lawd, ymd)).fetchone()
    out = []
    for r in rows:
        d = {k: r[k] for k in _PUBLIC_COLS}
        d["cancelled"] = bool(d["cancelled"])
        try:
            raw = json.loads(r["raw"])
        except (ValueError, TypeError):
            raw = {}
        # 화면에 덧붙이면 좋은 원본 항목 (데이터셋마다 있으면): 용도지역·지분거래·갱신요구권·종전 보증금 등
        for k in ("landUse", "shareDealingType", "useRRRight", "preDeposit", "preMonthlyRent", "rgstDate", "aptDong",
                  "ownershipGbn", "buildingType", "partCnclsAt"):
            if raw.get(k):
                d[k] = raw[k]
        out.append(d)
    return out, (log["fetched_at"] if log else None)


def summarize(key: str, rows: list[dict]) -> dict:
    """데이터셋별 요약 — 매매: 건수·중위가·3.3㎡(또는 ㎡)당 중위가·최고/최저. 전월세: 전세/월세 건수·중위 보증금·중위 월세·갱신 비율."""
    live = [r for r in rows if not r["cancelled"]]
    out: dict = {"count": len(live), "cancelled": len(rows) - len(live)}
    if not live:
        return out
    names: dict[str, int] = {}
    for r in live:
        if r.get("name"):
            names[r["name"]] = names.get(r["name"], 0) + 1
    out["top_names"] = [{"name": n, "count": c} for n, c in sorted(names.items(), key=lambda kv: -kv[1])[:10]]
    if _is_rent(key):
        jeonse = [r for r in live if (r["monthly_rent"] or 0) == 0 and r["deposit"]]
        wolse = [r for r in live if (r["monthly_rent"] or 0) > 0]
        out.update({
            "jeonse": len(jeonse), "wolse": len(wolse),
            "median_jeonse": round(statistics.median(r["deposit"] for r in jeonse)) if jeonse else None,
            "median_wolse_deposit": round(statistics.median(r["deposit"] or 0 for r in wolse)) if wolse else None,
            "median_wolse_rent": round(statistics.median(r["monthly_rent"] for r in wolse)) if wolse else None,
            "renewal": sum(1 for r in live if (r.get("contract_type") or "") == "갱신"),
        })
        pp = [r["deposit"] / r["area"] * PYEONG for r in jeonse if r["area"]]
        out["median_jeonse_pyeong"] = round(statistics.median(pp)) if pp else None
        return out
    priced = [r for r in live if r["amount"]]
    if not priced:
        return out
    hi = max(priced, key=lambda r: r["amount"])
    lo = min(priced, key=lambda r: r["amount"])
    unit = [r["amount"] / r["area"] for r in priced if r["area"]]
    out.update({
        "median": round(statistics.median(r["amount"] for r in priced)),
        "median_m2": round(statistics.median(unit), 1) if unit else None,
        "median_pyeong": round(statistics.median(unit) * PYEONG) if unit else None,
        "max": {"amount": hi["amount"], "name": hi.get("name") or hi.get("umd"), "area": hi["area"], "date": hi["deal_date"]},
        "min": {"amount": lo["amount"], "name": lo.get("name") or lo.get("umd"), "area": lo["area"], "date": lo["deal_date"]},
        "direct": sum(1 for r in live if r.get("deal_type") == "직거래"),
    })
    return out


def notices(scope: str = "upcoming", region: str = "", q: str = "", house_type: str = "", limit: int = 300) -> list[dict]:
    """청약 공고 — upcoming: 접수 마감이 오늘 이후(마감일 모르면 공고 60일 안)인 것을 접수 시작 빠른 순, all: 최근 공고 순."""
    today = date.today().isoformat()
    where, params = [], []
    if region:
        where.append("region = ?")
        params.append(region)
    if house_type:
        where.append("house_type = ?")
        params.append(house_type)
    if q:
        where.append("(name LIKE ? ESCAPE '\\' OR address LIKE ? ESCAPE '\\')")
        qe = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")  # 검색어의 %·_ 는 글자 그대로
        params += [f"%{qe}%", f"%{qe}%"]
    if scope == "upcoming":
        where.append("(receipt_end >= ? OR (receipt_end IS NULL AND notice_date >= date(?, '-60 day')))")
        params += [today, today]
        order = "COALESCE(receipt_start, receipt_end, notice_date) ASC"
    else:
        order = "notice_date DESC"
    sql = ("SELECT notice_id, name, house_type, category, address, lawd_cd, region, households, notice_date, receipt_start, "
           "receipt_end, winner_date, contract_start, contract_end, move_in_ym, url, source, status, builder, lat, lng "
           "FROM re_apply_notice" + (f" WHERE {' AND '.join(where)}" if where else "") + f" ORDER BY {order} LIMIT ?")
    return _rows(sql, (*params, max(1, min(limit, 1000))))


def notice_detail(notice_id: str) -> dict | None:
    rows = _rows("SELECT * FROM re_apply_notice WHERE notice_id=?", (notice_id,))
    if not rows:
        return None
    n = rows[0]
    n.pop("raw", None)
    n["models"] = _rows("SELECT model_no, house_ty, area, households, special_households, top_amount FROM re_apply_model "
                        "WHERE notice_id=? ORDER BY model_no, house_ty", (notice_id,))
    n["cmpet"] = _rows("SELECT model_no, house_ty, rank, reside, households, req_cnt, rate FROM re_apply_cmpet "
                       "WHERE notice_id=? ORDER BY model_no, house_ty, rank, reside", (notice_id,))
    n["score"] = _rows("SELECT model_no, house_ty, reside, low, top, avg FROM re_apply_score WHERE notice_id=? "
                       "ORDER BY model_no, house_ty, reside", (notice_id,))
    return n


def indicators() -> dict:
    base = _rows("SELECT changed_on, rate FROM re_base_rate ORDER BY changed_on DESC LIMIT 12")
    series: dict[str, dict] = {}
    for r in _rows("SELECT series, period, value, name, unit FROM re_econ_series ORDER BY series, period"):
        s = series.setdefault(r["series"], {"id": r["series"], "name": r["name"], "unit": r["unit"], "points": []})
        s["points"].append({"period": r["period"], "value": r["value"]})
    for s in series.values():
        s["points"] = s["points"][-24:]
    return {"base_rate": base, "series": list(series.values())}


def db_path() -> Path:
    return db.DB_PATH
