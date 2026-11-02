"""국토교통부 실거래가 공개 API (공공데이터포털 RTMSDataSvc*) 공통 클라이언트.

- 주소: https://apis.data.go.kr/1613000/<서비스>/get<서비스> — 인자 serviceKey·LAWD_CD(시군구 5자리)·DEAL_YMD(YYYYMM)·numOfRows·pageNo, 응답 XML.
  2026-11 키 없이 13개 서비스를 모두 불러 SERVICE_KEY_IS_NULL 응답을 확인했다(없는 서비스 이름은 NO_OPENAPI_SERVICE_ERROR 가 온다).
  항목 이름은 data.go.kr 각 문서(15126463~15126475)에 붙은 swagger 에서 확인했다.
- 하나의 키(DATA_GO_KR_KEY)를 쓰지만 API 마다 '활용신청'을 따로 해야 한다. 신청하지 않은 API 는
  SERVICE_KEY_IS_NOT_REGISTERED_ERROR 를 돌려주므로 NotRegistered 로 구분해 그 데이터셋만 '활용신청 필요'로 표시한다.
- 개발 계정은 API 별 하루 약 1만 건 — 호출 수를 DB(re_api_calls)에 API·날짜별로 세어 프로세스 재시작·여러 서버에도 넘지 않게 한다.
- 항목(item)의 모든 하위 태그를 그대로 dict 로 돌려준다 (저장은 re_store.py·redata.py, 화면용 가공은 molit.py).
- 키는 환경 변수가 비어 있으면 .env 파일을 다시 읽는다 — 관리자가 키를 넣으면 서버 재시작 없이 다음 수집부터 켜진다.
"""
from __future__ import annotations

import logging
import os
import re
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from urllib.parse import unquote

import httpx

from pipeline import db

BASE = "https://apis.data.go.kr/1613000"
PAGE_SIZE = 1000
MAX_PAGES = 20  # 한 시군구·한 달이 2만 건을 넘는 일은 없다 — 무한 반복 방지
HARD_CAP = 9800  # API 하나의 하루 호출 상한 (개발 계정 1만 건 — 화면 즉시 조회와 배치를 합쳐서)
UA = "ZipBomi/1.0 (+data collection; contact: site admin)"

_lock = threading.Lock()
_KEY_IN_URL = re.compile(r"((?:serviceKey|authKey|apiKey)=)[^&\s\"']+", re.I)


class _HttpxRedact(logging.Filter):
    """httpx 요청 로그에서 키 값을 가린다 (파일 로그에 serviceKey 가 남지 않게).
    '부동산 데이터 수집' 작업 스레드의 요청 로그는 아예 뺀다 — 수천 줄이 진행 줄(✓ …)을 밀어내지 않게."""

    def filter(self, record: logging.LogRecord) -> bool:
        if threading.current_thread().name == "job-re_data":
            return False
        try:
            msg = record.getMessage()
        except Exception:  # noqa: BLE001
            return True
        if _KEY_IN_URL.search(msg):
            record.msg, record.args = _KEY_IN_URL.sub(r"\1***", msg), ()
        return True


_httpx_logger = logging.getLogger("httpx")
if not any(isinstance(f, _HttpxRedact) for f in _httpx_logger.filters):
    _httpx_logger.addFilter(_HttpxRedact())


class RtmsError(Exception):
    """API 오류 — 메시지는 화면·로그에 그대로 보여도 되는 한국어 문구 (키 값은 넣지 않는다)."""


class KeyMissing(RtmsError):
    pass


class NotRegistered(RtmsError):
    """키는 있으나 이 API 를 활용신청하지 않았거나(또는 승인 전) 키가 틀림."""


class LimitExceeded(RtmsError):
    pass


_env_cache: dict = {}


def _env_file_value(name: str) -> str:
    """서버가 떠 있는 동안 .env 에 키를 새로 넣어도 재시작 없이 다음 실행부터 쓰게 — 파일이 바뀔 때만 다시 읽는다 (값은 어디에도 출력하지 않는다)."""
    path = db.ROOT / ".env"
    try:
        st = path.stat()
    except OSError:
        return ""
    sig = (st.st_mtime_ns, st.st_size)
    if _env_cache.get("sig") != sig:
        try:
            from dotenv import dotenv_values
            _env_cache.update(sig=sig, vals=dict(dotenv_values(path)))
        except Exception:  # noqa: BLE001 - .env 를 못 읽으면 환경 변수만 쓴다
            _env_cache.update(sig=sig, vals={})
    return str(_env_cache["vals"].get(name) or "").strip()


def env_value(name: str) -> str:
    return os.environ.get(name, "").strip() or _env_file_value(name)


def api_key() -> str:
    key = env_value("DATA_GO_KR_KEY")
    # 포털이 주는 '인코딩 키'(% 포함)를 그대로 넣어도 되게 — httpx 가 다시 인코딩하면 %25 로 깨져 '등록되지 않은 키'가 된다
    return unquote(key) if "%" in key else key


def configured() -> bool:
    return bool(api_key())


def url(service: str) -> str:
    return f"{BASE}/{service}/get{service}"


# ---------- 하루 호출 수 (DB) ----------

def _today() -> str:
    return datetime.now(db.KST).strftime("%Y-%m-%d")


def _ensure_calls(conn) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS re_api_calls (api TEXT NOT NULL, day TEXT NOT NULL, n INTEGER NOT NULL DEFAULT 0, "
                 "PRIMARY KEY (api, day))")


def calls_today(api: str) -> int:
    conn = db.connect()
    try:
        _ensure_calls(conn)
        row = conn.execute("SELECT n FROM re_api_calls WHERE api=? AND day=?", (api, _today())).fetchone()
        return int(row["n"]) if row else 0
    finally:
        conn.close()


def count_call(api: str, cap: int = HARD_CAP) -> None:
    """호출 하나를 센다. 오늘 cap 에 닿았으면 LimitExceeded (부르기 전에)."""
    with _lock:
        conn = db.connect()
        try:
            with conn:
                _ensure_calls(conn)
                day = _today()
                row = conn.execute("SELECT n FROM re_api_calls WHERE api=? AND day=?", (api, day)).fetchone()
                n = int(row["n"]) if row else 0
                if n >= min(cap, HARD_CAP):
                    raise LimitExceeded(f"오늘 호출 한도({min(cap, HARD_CAP):,}건)에 닿았습니다. 다음 실행에 이어서 받습니다.")
                conn.execute("INSERT INTO re_api_calls (api, day, n) VALUES (?,?,1) "
                             "ON CONFLICT(api, day) DO UPDATE SET n = n + 1", (api, day))
                conn.execute("DELETE FROM re_api_calls WHERE day < date(?, '-30 day')", (day,))
        finally:
            conn.close()


# ---------- 응답 해석 ----------

def check_error(root: ET.Element) -> None:
    # 키 오류는 <OpenAPI_ServiceResponse><cmmMsgHeader> 로, 일반 오류는 <response><header><resultCode> 로 온다
    auth = root.find(".//cmmMsgHeader")
    if auth is not None:
        msg = (auth.findtext("errMsg") or "").strip()
        reason = (auth.findtext("returnReasonCode") or "").strip()
        if "NOT_REGISTERED" in msg or reason in ("30", "31"):
            raise NotRegistered("활용신청이 필요하거나(승인 대기 포함) 키가 이 API 에 등록되지 않았습니다.")
        if "KEY_IS_NULL" in msg:
            raise KeyMissing("API 키가 없습니다.")
        if "LIMITED" in msg or "EXCEEDS" in msg or reason == "22":
            raise LimitExceeded("공공데이터포털 하루 호출 한도를 다 썼습니다. 다음 실행에 이어서 받습니다.")
        raise RtmsError(f"API 오류 ({msg or '알 수 없음'})")
    code = (root.findtext(".//header/resultCode") or "").strip()
    if code and code not in ("00", "000", "03"):  # 03 = 자료 없음
        msg = (root.findtext(".//header/resultMsg") or "").strip()
        if code in ("30", "31") or "NOT_REGISTERED" in msg:
            raise NotRegistered("활용신청이 필요하거나(승인 대기 포함) 키가 이 API 에 등록되지 않았습니다.")
        if code == "22":
            raise LimitExceeded("공공데이터포털 하루 호출 한도를 다 썼습니다.")
        raise RtmsError(f"API 오류 ({code} {msg})")


def item_dict(it: ET.Element) -> dict:
    """item 의 모든 하위 태그 → {태그: 공백 정리한 글자} (빈 값도 키는 남긴다)."""
    return {ch.tag: (ch.text or "").strip() for ch in it}


def fetch_items(service: str, lawd: str, ymd: str, client: httpx.Client | None = None, cap: int = HARD_CAP,
                retries: int = 3) -> tuple[list[dict], int]:
    """한 시군구·한 달 전체 (쪽 나눔 끝까지) → (항목 목록, 부른 횟수). 네트워크 오류는 짧게 쉬며 다시 시도."""
    key = api_key()
    if not key:
        raise KeyMissing("API 키(DATA_GO_KR_KEY)가 없습니다.")
    own = client is None
    client = client or httpx.Client(timeout=25, headers={"User-Agent": UA})
    items: list[dict] = []
    calls = 0
    try:
        for page in range(1, MAX_PAGES + 1):
            r = None
            for attempt in range(retries):
                count_call(service, cap)
                calls += 1
                try:
                    r = client.get(url(service), params={"serviceKey": key, "LAWD_CD": lawd, "DEAL_YMD": ymd,
                                                         "numOfRows": PAGE_SIZE, "pageNo": page})
                    if r.status_code >= 500:
                        raise httpx.HTTPStatusError("server error", request=r.request, response=r)
                    break
                except httpx.HTTPError:
                    r = None
                    if attempt == retries - 1:
                        raise RtmsError("공공데이터포털 서버에 연결하지 못했습니다 (재시도 후 실패).")
                    time.sleep(1.5 * (2 ** attempt))  # 1.5s → 3s 로 물러서며
            assert r is not None
            if r.status_code == 429:
                raise LimitExceeded("공공데이터포털이 요청이 너무 많다고 응답했습니다 (429). 다음 실행에 이어서 받습니다.")
            if r.status_code in (401, 403) and not r.content.lstrip().startswith(b"<"):
                raise NotRegistered("활용신청이 필요하거나 키가 이 API 에 등록되지 않았습니다.")
            try:
                root = ET.fromstring(r.content)
            except ET.ParseError as e:
                raise RtmsError(f"응답을 읽지 못했습니다 (HTTP {r.status_code}).") from e
            check_error(root)
            page_items = root.findall(".//items/item")
            items.extend(item_dict(it) for it in page_items)
            try:
                total = int((root.findtext(".//body/totalCount") or "0").strip() or 0)
            except ValueError:
                total = 0
            if not page_items or page * PAGE_SIZE >= total:
                break
            time.sleep(0.25)  # 쪽 사이 짧게 쉬어 공공 서버에 몰아치지 않는다
    finally:
        if own:
            client.close()
    return items, calls
