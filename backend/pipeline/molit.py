"""국토교통부 아파트 매매 실거래가 상세 자료 (공공데이터포털 RTMSDataSvcAptTradeDev) 조회·캐시.

- 주소: https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev
  인자 serviceKey·LAWD_CD(시군구 5자리)·DEAL_YMD(YYYYMM)·numOfRows·pageNo, 응답은 XML
  (2026-11 키 없이 요청해 SERVICE_KEY_IS_NULL XML 을, data.go.kr 15126468 문서의 swagger 로 항목 이름을 확인했다).
- 키는 .env DATA_GO_KR_KEY. 없으면 configured()=False 로 화면이 안내만 한다(가짜 숫자를 만들지 않는다).
- 결과는 re_apt_trade 테이블에 (lawd_cd, deal_ymd) 단위로 통째로 저장한다. 공공 API 는 하루 호출 한도가 있고 느리므로
  같은 지역·달을 여러 방문자가 봐도 하루 한 번만 부른다. 지난 달 자료도 신고 기한(계약 후 30일)·해제 신고 때문에 바뀌므로
  최근 3개월은 24시간, 그보다 오래된 달은 7일이 지나면 다시 받는다.
- 이 모듈만 테이블을 쓰므로 db.py 를 고치지 않고 처음 쓸 때 만든다.
- 2026-11: API 호출은 공통 클라이언트 pipeline/rtms.py 로 옮겼다 (다른 실거래 데이터셋과 하루 호출 수를 함께 센다).
  배치 '부동산 데이터 수집'(redata.py)이 아파트 매매를 받으면 이 캐시(re_apt_trade)도 함께 채운다.
"""
from __future__ import annotations

import json
import statistics
import threading
from datetime import date, datetime, timedelta

from pipeline import db, rtms

SERVICE = "RTMSDataSvcAptTradeDev"
URL = rtms.url(SERVICE)
PYEONG = 3.305785  # 1평 = 3.305785㎡ — '3.3㎡당 가격'은 관례상 이 값으로 환산한다
# 화면 즉시 조회는 이 API 의 하루 호출 수(배치 포함, DB 집계)가 이 값 아래일 때만 — 배치(re_data)가 쓸 몫을 남긴다
DAILY_CAP_TOTAL = 9800

_SQL = ("CREATE TABLE IF NOT EXISTS re_apt_trade (lawd_cd TEXT NOT NULL, deal_ymd TEXT NOT NULL, rows TEXT NOT NULL, "
        "total INTEGER NOT NULL, fetched_at TEXT NOT NULL, PRIMARY KEY (lawd_cd, deal_ymd))")
_ready: list = []
_api_lock = threading.Lock()  # 공공 API 는 한 번에 하나씩만 부른다 (동시 요청이 몰려도 순서대로, 예의 있게)


class MolitError(Exception):
    """API 오류 — 메시지는 화면에 그대로 보여도 되는 한국어 문구."""


def api_key() -> str:
    return rtms.api_key()


def configured() -> bool:
    return bool(api_key())


def _conn():
    conn = db.connect()
    if not _ready:
        conn.execute(_SQL)
        conn.commit()
        _ready.append(True)
    return conn


def _int(s: str | None) -> int | None:
    try:
        return int(str(s).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _float(s: str | None) -> float | None:
    try:
        return float(str(s).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def parse_item(it: dict) -> dict | None:
    """API 항목 하나(rtms.item_dict 결과) → 화면에 쓰는 행. 금액·면적이 없는 행은 통계를 망치므로 버린다."""
    amount = _int(it.get("dealAmount"))  # 만원 단위, "82,000" 처럼 쉼표 포함
    area = _float(it.get("excluUseAr"))
    if not amount or not area or area <= 0:
        return None
    y, m, d = _int(it.get("dealYear")), _int(it.get("dealMonth")), _int(it.get("dealDay"))
    t = lambda k: (it.get(k) or "").strip()  # noqa: E731
    return {
        "apt": t("aptNm"), "dong": t("umdNm"), "jibun": t("jibun"), "apt_dong": t("aptDong"),
        "area": round(area, 2), "floor": _int(it.get("floor")), "amount": amount,
        "date": f"{y:04d}-{m:02d}-{d:02d}" if y and m and d else "",
        "build_year": _int(it.get("buildYear")),
        "deal_type": t("dealingGbn"),  # 중개거래·직거래
        "cancelled": t("cdealType") == "O",  # 계약 해제 신고된 거래 — 통계에서 뺀다
        "cancel_day": t("cdealDay"),
        "seller": t("slerGbn"), "buyer": t("buyerGbn"),
    }


def fetch_month(lawd: str, ymd: str) -> list[dict]:
    """API 에서 한 시군구·한 달 전체를 받는다 (쪽 나눔 끝까지, 공통 클라이언트 rtms.fetch_items)."""
    if not api_key():
        raise MolitError("실거래가 API 키가 없습니다.")
    try:
        items, _ = rtms.fetch_items(SERVICE, lawd, ymd, cap=DAILY_CAP_TOTAL)
    except rtms.NotRegistered as e:
        raise MolitError("실거래가 API 키가 맞지 않거나 아직 승인되지 않았습니다. 관리자에게 알려 주세요.") from e
    except rtms.LimitExceeded as e:
        raise MolitError("오늘 실거래가 조회 한도를 다 썼습니다. 내일 다시 시도해 주세요.") from e
    except rtms.RtmsError as e:
        raise MolitError(f"실거래가 API 오류: {e}") from e
    return [x for x in (parse_item(it) for it in items) if x]


def _max_age(ymd: str) -> timedelta:
    y, m = int(ymd[:4]), int(ymd[4:])
    t = date.today()
    months_ago = (t.year - y) * 12 + (t.month - m)
    return timedelta(hours=24) if months_ago <= 3 else timedelta(days=7)


def cached_month(lawd: str, ymd: str) -> tuple[list[dict], str] | None:
    """캐시가 있고 아직 신선하면 (행, 받은 시각)."""
    conn = _conn()
    try:
        row = conn.execute("SELECT rows, fetched_at FROM re_apt_trade WHERE lawd_cd=? AND deal_ymd=?", (lawd, ymd)).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    try:
        at = datetime.fromisoformat(row["fetched_at"])
        if datetime.now(db.KST) - at > _max_age(ymd):
            return None
        return json.loads(row["rows"]), row["fetched_at"]
    except (ValueError, TypeError):
        return None


def _store(lawd: str, ymd: str, rows: list[dict]) -> str:
    at = datetime.now(db.KST).isoformat(timespec="seconds")
    conn = _conn()
    try:
        conn.execute("INSERT INTO re_apt_trade (lawd_cd, deal_ymd, rows, total, fetched_at) VALUES (?,?,?,?,?) "
                     "ON CONFLICT(lawd_cd, deal_ymd) DO UPDATE SET rows=excluded.rows, total=excluded.total, "
                     "fetched_at=excluded.fetched_at",
                     (lawd, ymd, json.dumps(rows, ensure_ascii=False), len(rows), at))
        conn.commit()
    finally:
        conn.close()
    return at


def get_month(lawd: str, ymd: str, allow_fetch: bool = True) -> tuple[list[dict], str] | None:
    """캐시 우선, 없거나 오래됐으면 API. allow_fetch=False 면 캐시만 본다(남용 제한에 걸린 방문자)."""
    hit = cached_month(lawd, ymd)
    if hit or not allow_fetch:
        return hit
    with _api_lock:
        hit = cached_month(lawd, ymd)  # 기다리는 동안 다른 요청이 이미 받아 왔을 수 있다
        if hit:
            return hit
        rows = fetch_month(lawd, ymd)
        return rows, _store(lawd, ymd, rows)


# ---------- 통계 ----------

def per_pyeong(r: dict) -> float:
    return r["amount"] / r["area"] * PYEONG


def summarize(rows: list[dict]) -> dict:
    """해제된 거래를 뺀 통계 — 건수·중위가·㎡당/3.3㎡당 평균·최고/최저·단지별 상위 10."""
    live = [r for r in rows if not r["cancelled"]]
    out: dict = {"count": len(live), "cancelled": len(rows) - len(live)}
    if not live:
        return out
    amounts = [r["amount"] for r in live]
    per_m2 = [r["amount"] / r["area"] for r in live]
    hi = max(live, key=lambda r: r["amount"])
    lo = min(live, key=lambda r: r["amount"])
    by_apt: dict[tuple[str, str], list[dict]] = {}
    for r in live:
        by_apt.setdefault((r["apt"], r["dong"]), []).append(r)
    top = sorted(by_apt.items(), key=lambda kv: (-len(kv[1]), kv[0][0]))[:10]
    out.update({
        "median": round(statistics.median(amounts)),
        "avg_m2": round(statistics.fmean(per_m2), 1),
        "avg_pyeong": round(statistics.fmean(per_m2) * PYEONG),
        "median_pyeong": round(statistics.median(per_pyeong(r) for r in live)),
        "max": {"amount": hi["amount"], "apt": hi["apt"], "area": hi["area"], "date": hi["date"]},
        "min": {"amount": lo["amount"], "apt": lo["apt"], "area": lo["area"], "date": lo["date"]},
        "top_apts": [{"apt": a, "dong": d, "count": len(rs), "median": round(statistics.median(x["amount"] for x in rs)),
                      "median_pyeong": round(statistics.median(per_pyeong(x) for x in rs))} for (a, d), rs in top],
    })
    return out


def month_median_pyeong(rows: list[dict]) -> float | None:
    vals = [per_pyeong(r) for r in rows if not r["cancelled"]]
    return round(statistics.median(vals)) if vals else None
