"""실거래가 CSV 자동 다운로드 — 국토교통부 실거래가 공개시스템(rt.molit.go.kr → 자료제공 → 조건별 자료제공)에서
브라우저의 [CSV 다운] 버튼과 같은 요청으로 파일을 받아 re_upload.ingest 로 넣는다. 공공데이터포털 API 키·활용신청이 없어도
실거래가 데이터셋을 채우기 위한 것 (redata.run 이 데이터셋별 source: auto|api|csv 에 따라 부른다).

사이트 흐름 (2026-11-02 페이지·스크립트에서 확인):
  ① GET  /pt/xls/xls.do?mobileAt=            → 세션 쿠키(JSESSIONID·WMONID) + 페이지 안 폼 주소의 ';jsessionid=…'
  ② POST /data/sido.do                        → 시도 목록 [{signguCode:'11000', ctprvnNm:'서울특별시'} …] (실행마다 한 번)
  ③ POST /pt/xls/ptXlsDownDataCheck.do;jsessionid=…  (폼 frm_xls 직렬화)  → {"cnt": n, "error": "…"}
  ④ POST /pt/xls/ptXlsCSVDown.do;jsessionid=…        (같은 폼)            → CSV 파일 (CP949)
  폼: srhThingNo(A 아파트·B 연립다세대·C 단독다가구·D 오피스텔·E 분양입주권·F 상업업무용·G 토지·H 공장창고), srhDelngSecd(1 매매·2 전월세),
      srhAddrGbn=1(지번), srhLfstsSecd=1, sidoNm·sggNm·emdNm·loadNm·areaNm·hsmpNm(화면 표시 이름), mobileAt, srhFromDt·srhToDt(YYYY-MM-DD),
      srhNewRonSecd, srhSidoCd(빈 값 = 전국), srhSggCd, srhEmdCd, srhRoadNm, srhLoadCd, srhHsmpCd, srhArea, srhFromAmount, srhToAmount, srhLrArea.
  사이트 제한: 하루 다운로드 100건(서버가 셈), 전국은 계약일 범위 1개월(31일) 이하, 시도 단위는 1년(366일) 이하.

예의 (사이트를 괴롭히지 않게):
- 요청은 한 번에 하나, 요청 사이 최소 5초, 시간 제한(연결 10초·응답 120초), 네트워크 오류·5xx 만 물러서며 최대 2번 다시.
- 우리 몫은 KST 하루 60건(DB rt_csv_log 로 셈) — 사이트 한도 100건 중 나머지는 관리자가 손으로 받을 몫으로 남긴다.
- 사이트가 오류·한도 문구를 돌려주면 그날 자동 다운로드를 멈춘다 (rt_csv_state.stop_day).
- 보안문자·로그인·차단 화면·403/429 가 보이면 우회하지 않고 멈춘 뒤 '자동 다운로드 차단됨'으로 남긴다.
- 받은 파일은 data/downloads/ 에 두고 30일 지나면 지운다.
"""
from __future__ import annotations

import logging
import re
import threading
from urllib.parse import urlencode
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx

from pipeline import db, re_store, regions_kr

log = logging.getLogger("zipgenie.rt_download")

BASE = "https://rt.molit.go.kr"
PAGE = f"{BASE}/pt/xls/xls.do?mobileAt="
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; compatible; ZipGenie/1.0; real-estate batch, max 60 CSV/day)"
MIN_GAP = 5.0                 # 요청 사이 최소 초
HARD_CAP = 60                 # 하루 다운로드 상한 (설정으로 더 낮출 수만 있다)
KEEP_DAYS = 30
MAX_FILE = 200 * 1024 * 1024
DOWNLOAD_DIR = db.ROOT / "data" / "downloads"
BLOCKED_LABEL = "자동 다운로드 차단됨"

# 데이터셋 → (srhThingNo, srhDelngSecd)
CODES: dict[str, tuple[str, str]] = {
    "apt_trade": ("A", "1"), "apt_rent": ("A", "2"),
    "rh_trade": ("B", "1"), "rh_rent": ("B", "2"),
    "sh_trade": ("C", "1"), "sh_rent": ("C", "2"),
    "offi_trade": ("D", "1"), "offi_rent": ("D", "2"),
    "silv_trade": ("E", "1"), "nrg_trade": ("F", "1"), "land_trade": ("G", "1"), "indu_trade": ("H", "1"),
}
# 사이트 시도 목록을 못 받을 때 쓰는 값 (2026-11-02 /data/sido.do 응답)
SIDO_FALLBACK = {"서울": ("11000", "서울특별시"), "부산": ("26000", "부산광역시"), "대구": ("27000", "대구광역시"),
                 "인천": ("28000", "인천광역시"), "대전": ("30000", "대전광역시"), "울산": ("31000", "울산광역시"),
                 "세종": ("36000", "세종특별자치시"), "경기": ("41000", "경기도"), "광주": ("12000", "전남광주통합특별시")}
# 광주: 2026-11 사이트 목록에는 '광주광역시'가 없고 '전남광주통합특별시'(12000)만 있다. re_store.sido_of 가 뒤의 구 이름으로
# 광주(29xxx)와 전남을 가르므로 이 시도 창을 받으면 광주 구 거래만 들어가고 전남 행은 '지원 지역 밖'으로 센다.

_BLOCK_WORDS = ("captcha", "보안문자", "자동입력", "로그인이 필요", "접근이 차단", "접근 차단", "차단되었", "비정상적인 접근",
                "too many requests", "access denied")
_FORM_CT = {"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"}  # jQuery $.serialize() 와 같은 본문
_LIMIT_WORDS = ("횟수", "100건", "초과", "제한")

_SQL = (
    "CREATE TABLE IF NOT EXISTS rt_csv_log (id INTEGER PRIMARY KEY AUTOINCREMENT, day TEXT NOT NULL, at TEXT NOT NULL, "
    "dataset TEXT NOT NULL, scope TEXT NOT NULL, scope_name TEXT, date_from TEXT, date_to TEXT, kind TEXT, status TEXT, "
    "cnt INTEGER, rows INTEGER, inserted INTEGER, downloaded INTEGER NOT NULL DEFAULT 0, file TEXT, message TEXT)",
    "CREATE INDEX IF NOT EXISTS ix_rt_csv_log_day ON rt_csv_log(day)",
    "CREATE TABLE IF NOT EXISTS rt_csv_coverage (dataset TEXT NOT NULL, scope TEXT NOT NULL, ymd TEXT NOT NULL, "
    "fetched_at TEXT NOT NULL, log_id INTEGER, PRIMARY KEY (dataset, scope, ymd))",
    "CREATE TABLE IF NOT EXISTS rt_csv_state (k TEXT PRIMARY KEY, v TEXT, at TEXT)",
)


class SiteError(Exception):
    """사이트가 오류 문구를 돌려줌 — 그날 다운로드를 멈춘다."""


class LimitReached(SiteError):
    """하루 한도(사이트 또는 우리 상한)."""


class Mismatch(SiteError):
    """받은 파일 종류가 요청과 다름 (예: 전월세를 청했는데 매매 파일) — 같은 세션으로 연달아 받으면 사이트가 직전 파일을 다시 주는 일이 있었다 (2026-11-02).
    그날 전체를 멈추지 않고 새 세션으로 한 번 다시 받고, 그래도 다르면 그 창만 건너뛴다."""


class Corrupt(Mismatch):
    """받은 파일 중간이 0 바이트로 비어 있음 (2026-11-02 경기 아파트 매매 1년치에서 16.8MB 구간이 비어 옴) — 다시 받는다."""


# 파일 머리 '검색조건'의 실거래구분 앞부분 (사이트 표기, 2026-11-02 확인)
THING_LABELS = {"A": "아파트", "B": "연립다세대", "C": "단독다가구", "D": "오피스텔", "E": "분양입주권",
                "F": "상업업무용", "G": "토지", "H": "공장창고"}


def file_conditions(path: Path) -> dict[str, str]:
    """CSV 머리의 '□ 검색조건' 줄들 ('실거래구분 : 아파트(매매)' 등)을 사전으로."""
    with open(path, "rb") as f:
        head = f.read(8192)
    try:
        text = head.decode("utf-8")
    except UnicodeDecodeError:
        text = head.decode("cp949", errors="replace")
    out: dict[str, str] = {}
    for line in text.splitlines()[:30]:
        t = line.strip().strip('"').strip()
        if " : " in t:
            k, v = t.split(" : ", 1)
            out[k.strip()] = v.strip()
    return out


def condition_problem(w: "Window", cond: dict[str, str]) -> str | None:
    """받은 파일의 검색조건이 요청한 창과 다르면 그 차이를 한 줄로 (같으면 None).
    2026-11-02: 사이트가 다른 사람의 검색 결과(전남 여수 토지 2025, 경기 과천 상업업무용 등)를 섞어 보낸 일이 세 번 있었다."""
    if not cond:
        return None  # 머리 안내가 없는 형식이면 판정하지 않는다 (머리글 검사는 ingest 가 한다)
    thing, deal = CODES[w.dataset]
    want_kind = f"{THING_LABELS[thing]}({'매매' if deal == '1' else '전월세'})"
    got_kind = cond.get("실거래구분", "").replace(" ", "")
    if got_kind and got_kind != want_kind:
        return f"실거래구분 {got_kind} ≠ 요청 {want_kind}"
    want_sido = "전체" if w.scope == "전국" else w.scope_name
    got_sido = cond.get("시도", "")
    if got_sido and got_sido != want_sido:
        return f"시도 {got_sido} ≠ 요청 {want_sido}"
    if w.scope != "전국" and cond.get("시군구", "전체") != "전체":
        return f"시군구 {cond.get('시군구')} ≠ 요청 전체"
    got_range = cond.get("계약일자", "").replace(" ", "")
    if got_range and got_range != f"{w.date_from}~{w.date_to}":
        return f"계약일자 {got_range} ≠ 요청 {w.date_from}~{w.date_to}"
    return None


NUL_RUN = b"\x00" * 4096


def _has_hole(path: Path) -> bool:
    """CSV 안에 0 바이트가 길게 이어진 구간이 있는지 (정상 CSV 에는 없다)."""
    tail = b""
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            if NUL_RUN in tail + chunk:
                return True
            tail = chunk[-len(NUL_RUN):]
    return False


class Blocked(SiteError):
    """보안문자·로그인·차단 화면 — 우회하지 않고 멈춘다."""


# ───────────────────────── DB ─────────────────────────

def _conn():
    c = db.connect()
    for s in _SQL:
        c.execute(s)
    return c


def today() -> str:
    return datetime.now(db.KST).strftime("%Y-%m-%d")


def downloads_today(day: str | None = None) -> int:
    c = _conn()
    try:
        return c.execute("SELECT COUNT(*) FROM rt_csv_log WHERE day=? AND downloaded=1", (day or today(),)).fetchone()[0]
    finally:
        c.close()


def daily_cap() -> int:
    try:
        v = int(re_store.defaults().get("csv_daily_cap", HARD_CAP))
    except (TypeError, ValueError):
        v = HARD_CAP
    return max(0, min(v, HARD_CAP))


def get_state() -> dict[str, str]:
    c = _conn()
    try:
        return {r["k"]: r["v"] for r in c.execute("SELECT k, v FROM rt_csv_state")}
    finally:
        c.close()


def set_state(**kv: str | None) -> None:
    c = _conn()
    try:
        for k, v in kv.items():
            c.execute("INSERT INTO rt_csv_state (k, v, at) VALUES (?,?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v, at=excluded.at",
                      (k, v, re_store._now()))
        c.commit()
    finally:
        c.close()


def stopped_today() -> str | None:
    """오늘 멈춘 이유 (없으면 None)."""
    st = get_state()
    return st.get("stop_reason") or "멈춤" if st.get("stop_day") == today() else None


def stop_for_today(reason: str, blocked: bool = False) -> None:
    set_state(stop_day=today(), stop_reason=reason[:300], blocked=BLOCKED_LABEL if blocked else "")
    log.warning("CSV 자동 다운로드 오늘은 멈춤 — %s", reason)


def _log_start(w: "Window", kind: str) -> int:
    c = _conn()
    try:
        cur = c.execute("INSERT INTO rt_csv_log (day, at, dataset, scope, scope_name, date_from, date_to, kind, status) "
                        "VALUES (?,?,?,?,?,?,?,?, 'running')",
                        (today(), re_store._now(), w.dataset, w.scope, w.scope_name, w.date_from, w.date_to, kind))
        c.commit()
        return cur.lastrowid
    finally:
        c.close()


def _log_update(log_id: int, **kv) -> None:
    if not kv:
        return
    c = _conn()
    try:
        c.execute(f"UPDATE rt_csv_log SET {', '.join(f'{k}=?' for k in kv)} WHERE id=?", (*kv.values(), log_id))
        c.commit()
    finally:
        c.close()


def coverage_map() -> dict[tuple[str, str, str], str]:
    """{(dataset, scope, YYYYMM): 받은 시각}."""
    c = _conn()
    try:
        return {(r["dataset"], r["scope"], r["ymd"]): r["fetched_at"] for r in
                c.execute("SELECT dataset, scope, ymd, fetched_at FROM rt_csv_coverage")}
    finally:
        c.close()


def _mark(w: "Window", log_id: int) -> None:
    at = re_store._now()
    c = _conn()
    try:
        c.executemany("INSERT INTO rt_csv_coverage (dataset, scope, ymd, fetched_at, log_id) VALUES (?,?,?,?,?) "
                      "ON CONFLICT(dataset, scope, ymd) DO UPDATE SET fetched_at=excluded.fetched_at, log_id=excluded.log_id",
                      [(w.dataset, w.scope, m, at, log_id) for m in w.months])
        c.commit()
    finally:
        c.close()


def summary() -> dict:
    """관리 화면 — 오늘 받은 수·상한·멈춤 상태, 데이터셋별 마지막 창·마지막 오류·받은 달 수."""
    c = _conn()
    try:
        last = {r["dataset"]: dict(r) for r in c.execute(
            "SELECT * FROM rt_csv_log WHERE id IN (SELECT MAX(id) FROM rt_csv_log WHERE status NOT IN ('running') "
            "GROUP BY dataset)")}
        err = {r["dataset"]: dict(r) for r in c.execute(
            "SELECT * FROM rt_csv_log WHERE id IN (SELECT MAX(id) FROM rt_csv_log WHERE status IN "
            "('error','limit','blocked') GROUP BY dataset)")}
        months = {r["dataset"]: r["n"] for r in c.execute(
            "SELECT dataset, COUNT(DISTINCT ymd) AS n FROM rt_csv_coverage GROUP BY dataset")}
        total = {r["dataset"]: (r["n"], r["ins"]) for r in c.execute(
            "SELECT dataset, SUM(downloaded) AS n, SUM(COALESCE(inserted,0)) AS ins FROM rt_csv_log GROUP BY dataset")}
    finally:
        c.close()
    st = get_state()
    stop = st.get("stop_reason") if st.get("stop_day") == today() else None
    return {"today": downloads_today(), "cap": daily_cap(), "site_cap": 100, "stopped": stop,
            "blocked": bool(stop and st.get("blocked")), "blocked_label": BLOCKED_LABEL,
            "datasets": {k: {"last": last.get(k), "last_error": err.get(k), "months": months.get(k, 0),
                             "downloads": (total.get(k) or (0, 0))[0] or 0, "inserted": (total.get(k) or (0, 0))[1] or 0}
                         for k in CODES}}


def cleanup(keep_days: int = KEEP_DAYS) -> int:
    if not DOWNLOAD_DIR.exists():
        return 0
    cut = time.time() - keep_days * 86400
    n = 0
    for p in DOWNLOAD_DIR.glob("*.csv"):
        try:
            if p.stat().st_mtime < cut:
                p.unlink()
                n += 1
        except OSError:
            pass
    return n


# ───────────────────────── 계획 ─────────────────────────

def _ym(d: date) -> str:
    return f"{d.year:04d}{d.month:02d}"


def _first(ymd: str) -> date:
    return date(int(ymd[:4]), int(ymd[4:]), 1)


def _last(ymd: str) -> date:
    n = re_store.shift_ymd(ymd, 1)
    return _first(n) - timedelta(days=1)


@dataclass
class Window:
    dataset: str
    scope: str            # '전국' 또는 시도 코드 '11000'
    scope_name: str       # '전국' · '서울특별시'
    date_from: str        # YYYY-MM-DD
    date_to: str
    months: list[str] = field(default_factory=list)
    kind: str = "daily"   # daily · backfill · test

    @property
    def label(self) -> str:
        a, b = self.months[0], self.months[-1]
        ms = f"{a[:4]}-{a[4:]}" + ("" if a == b else f"~{b[:4]}-{b[4:]}")
        if self.months and self.date_to < _last(b).isoformat():
            ms += f" ({self.date_to[5:]}까지)"
        return f"{self.scope_name} {ms}"

    def as_dict(self) -> dict:
        return {"dataset": self.dataset, "scope": self.scope, "scope_name": self.scope_name, "from": self.date_from,
                "to": self.date_to, "months": self.months, "kind": self.kind, "label": self.label}


def our_sidos(site: dict[str, tuple[str, str]] | None = None) -> list[tuple[str, str, str]]:
    """regions_kr 에 있는 시도 → [(짧은 이름, 사이트 시도 코드, 사이트 시도 이름)] (regions_kr 순서)."""
    site = site or SIDO_FALLBACK
    return [(short, *site[short]) for short, _ in regions_kr.REGIONS if short in site]


def plan(datasets: list[dict], now: datetime | None = None, sidos: list[tuple[str, str, str]] | None = None,
         refresh_hours: float = 20) -> list[Window]:
    """오늘 받을 창 목록 — ① 매일: 데이터셋마다 전국 × (지지난달·지난달 전체 + 이번 달 1일~오늘), 20시간 안에 받은 달은 뺀다.
    ② 과거 채우기: 4개월 전 ~ backfill_months 전, 시도 × 연속한 달 최대 12개씩, 가장 오래 비어 있는 달부터. 받은 칸은 rt_csv_coverage 로 건너뛴다."""
    now = now or datetime.now(db.KST)
    td = now.date()
    cur = _ym(td)
    have = coverage_map()
    sidos = sidos or our_sidos()
    daily: list[Window] = []
    back: list[tuple[str, int, int, Window]] = []
    for di, d in enumerate(datasets):
        key = d["key"]
        for k in (2, 1, 0):
            m = re_store.shift_ymd(cur, -k)
            at = have.get((key, "전국", m))
            if at:
                try:
                    if now - datetime.fromisoformat(at) < timedelta(hours=refresh_hours):
                        continue
                except ValueError:
                    pass
            end = td if k == 0 else _last(m)
            daily.append(Window(key, "전국", "전국", _first(m).isoformat(), end.isoformat(), [m], "daily"))
        months = [re_store.shift_ymd(cur, -i) for i in range(int(d.get("backfill_months") or 24) - 1, 2, -1)]  # 오래된 달부터
        for si, (_, code, name) in enumerate(sidos):
            missing = [m for m in months if (key, code, m) not in have and (key, "전국", m) not in have]
            chunk: list[str] = []
            for m in missing + [None]:
                if chunk and (m is None or len(chunk) >= 12 or m != re_store.shift_ymd(chunk[-1], 1)):
                    w = Window(key, code, name, _first(chunk[0]).isoformat(), _last(chunk[-1]).isoformat(), chunk, "backfill")
                    back.append((chunk[0], di, si, w))
                    chunk = []
                if m is not None:
                    chunk.append(m)
    back.sort(key=lambda x: x[:3])
    return daily + [w for *_, w in back]


# ───────────────────────── 사이트 세션 ─────────────────────────

_gap_lock = threading.Lock()
_last_req = [0.0]
_req_count = [0]


def requests_made() -> int:
    return _req_count[0]


class Session:
    """GET 페이지로 쿠키·jsessionid 를 받고 같은 세션으로 확인·다운로드. 요청 사이 최소 MIN_GAP 초."""

    def __init__(self, gap: float = MIN_GAP):
        self.gap = max(MIN_GAP, gap)
        self.c = httpx.Client(timeout=httpx.Timeout(120, connect=10), follow_redirects=True,
                              headers={"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9"})
        self.jsid = ""
        self.sidos: dict[str, tuple[str, str]] = {}

    def close(self) -> None:
        self.c.close()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    def _wait(self) -> None:
        with _gap_lock:
            left = _last_req[0] + self.gap - time.monotonic()
            if left > 0:
                time.sleep(left)
            _last_req[0] = time.monotonic()
            _req_count[0] += 1

    def _send(self, method: str, url: str, stream_to: Path | None = None, **kw) -> httpx.Response:
        """네트워크 오류·5xx 는 10초 → 30초 물러서며 최대 2번 다시. 403·429 는 차단으로 본다."""
        for attempt in range(3):
            self._wait()
            try:
                if stream_to is None:
                    r = self.c.request(method, url, **kw)
                else:
                    with self.c.stream(method, url, **kw) as r:
                        if r.status_code == 200:  # 형식은 받은 뒤 앞부분으로 판정 (서버 content-type 을 믿지 않는다)
                            n = 0
                            with open(stream_to, "wb") as f:
                                for chunk in r.iter_bytes(1 << 16):
                                    n += len(chunk)
                                    if n > MAX_FILE:
                                        raise SiteError("파일이 너무 큽니다 (200MB 초과)")
                                    f.write(chunk)
                        else:
                            r.read()
                if r.status_code in (403, 429):
                    raise Blocked(f"HTTP {r.status_code}")
                if r.status_code >= 500:
                    raise httpx.HTTPStatusError(f"HTTP {r.status_code}", request=r.request, response=r)
                return r
            except (httpx.TransportError, httpx.HTTPStatusError) as e:
                if attempt == 2:
                    raise SiteError(f"연결 실패: {type(e).__name__} {e}") from e
                wait = (10, 30)[attempt]
                log.info("rt.molit.go.kr 응답 없음 (%s) — %d초 뒤 다시", type(e).__name__, wait)
                time.sleep(wait)
        raise SiteError("연결 실패")  # pragma: no cover

    @staticmethod
    def _check_block(text: str) -> None:
        low = text.lower()
        for w in _BLOCK_WORDS:
            if w.lower() in low:
                raise Blocked(f"차단·인증 화면으로 보임 ('{w}')")

    def open(self) -> None:
        r = self._send("GET", PAGE)
        text = r.text
        if r.status_code != 200 or "frm_xls" not in text:
            self._check_block(text)
            raise SiteError(f"자료제공 화면이 예상과 다릅니다 (HTTP {r.status_code}) — 사이트가 바뀌었는지 확인 필요")
        self._check_block(text)
        m = re.search(r"ptXlsCSVDown\.do;jsessionid=([A-Za-z0-9_.\-]+)", text)
        self.jsid = m.group(1) if m else (self.c.cookies.get("JSESSIONID") or "")
        if "ptXlsCSVDown.do" not in text or "ptXlsDownDataCheck.do" not in text:
            raise SiteError("CSV 다운로드 주소를 화면에서 찾지 못했습니다 — 사이트가 바뀌었는지 확인 필요")

    def _url(self, path: str) -> str:
        return f"{BASE}{path};jsessionid={self.jsid}" if self.jsid else f"{BASE}{path}"

    def _ajax_headers(self) -> dict:
        return {"Referer": PAGE, "Origin": BASE, "X-Requested-With": "XMLHttpRequest",
                "Accept": "application/json, text/javascript, */*; q=0.01"}

    def load_sidos(self) -> dict[str, tuple[str, str]]:
        """사이트 시도 목록 {짧은 이름: (코드, 이름)} — 못 받으면 SIDO_FALLBACK."""
        try:
            r = self._send("POST", self._url("/data/sido.do"), headers=self._ajax_headers(), data={})
            out = {}
            for o in r.json():
                short = re_store.sido_of(o.get("ctprvnNm", ""))  # '전남광주통합특별시' 단독 → 광주
                if short and o.get("signguCode"):
                    out[short] = (str(o["signguCode"]), o["ctprvnNm"])
            if out:
                self.sidos = out
                return out
        except (ValueError, SiteError) as e:
            if isinstance(e, Blocked):
                raise
            log.info("시도 목록을 못 받아 기본값 사용 (%s)", e)
        self.sidos = dict(SIDO_FALLBACK)
        return self.sidos

    @staticmethod
    def form(dataset: str, w: Window) -> list[tuple[str, str]]:
        """frm_xls 를 브라우저 $.serialize() 와 같은 순서·값으로."""
        thing, deal = CODES[dataset]
        sido = "" if w.scope == "전국" else w.scope
        return [
            ("srhThingNo", thing), ("srhDelngSecd", deal), ("srhAddrGbn", "1"), ("srhLfstsSecd", "1"),
            ("sidoNm", "전체" if not sido else w.scope_name), ("sggNm", "전체"), ("emdNm", "전체"), ("loadNm", "전체"),
            ("areaNm", "전체"), ("hsmpNm", "전체"), ("hsmpNm", ""), ("hsmpNm", ""), ("mobileAt", ""),
            ("srhFromDt", w.date_from), ("srhToDt", w.date_to), ("srhNewRonSecd", ""), ("srhSidoCd", sido),
            ("srhSggCd", ""), ("srhEmdCd", ""), ("srhRoadNm", ""), ("srhLoadCd", ""), ("srhHsmpCd", ""), ("srhArea", ""),
            ("srhFromAmount", ""), ("srhToAmount", ""), ("srhLrArea", ""),
        ]

    def check(self, w: Window) -> int:
        r = self._send("POST", self._url("/pt/xls/ptXlsDownDataCheck.do"), headers={**self._ajax_headers(), **_FORM_CT},
                       content=urlencode(self.form(w.dataset, w)))
        try:
            js = r.json()
        except ValueError:
            self._check_block(r.text)
            raise SiteError(f"자료 확인 응답이 JSON 이 아닙니다 (HTTP {r.status_code})")
        err = str(js.get("error") or "").strip()
        if err:
            if any(x in err for x in _LIMIT_WORDS):
                raise LimitReached(f"사이트 한도: {err}")
            raise SiteError(f"사이트 오류: {err}")
        try:
            return int(js.get("cnt") or 0)
        except (TypeError, ValueError):
            return 0

    def download(self, w: Window, dest: Path) -> int:
        headers = {"Referer": PAGE, "Origin": BASE,
                   "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}
        r = self._send("POST", self._url("/pt/xls/ptXlsCSVDown.do"), stream_to=dest, headers={**headers, **_FORM_CT},
                       content=urlencode(self.form(w.dataset, w)))
        ctype = r.headers.get("content-type", "").lower()
        if r.status_code != 200 or not dest.exists():
            text = ""
            try:
                text = r.text[:2000]
            except Exception:  # noqa: BLE001 - 스트림이면 글자가 없을 수 있다
                pass
            self._check_block(text)
            raise SiteError(f"CSV 대신 다른 응답 (HTTP {r.status_code}, {ctype or '형식 없음'})")
        size = dest.stat().st_size
        if size == 0:
            raise SiteError("빈 파일을 받았습니다")
        with open(dest, "rb") as f:
            head = f.read(8192)
        try:
            t = head.decode("utf-8")
        except UnicodeDecodeError:
            t = head.decode("cp949", errors="ignore")  # 공개시스템 CSV 는 CP949 (끝이 잘린 UTF-8 도 여기로 오지만 판정엔 충분)
        low = t.lower()
        if "<html" in low or "<!doctype" in low or t.lstrip().startswith("{"):
            self._check_block(t)
            plain = re.sub(r"<[^>]+>|\s+", " ", t).strip()
            if any(x in plain for x in _LIMIT_WORDS):
                raise LimitReached(f"사이트 한도: {plain[:200]}")
            raise SiteError(f"CSV 대신 웹 화면·오류 응답을 받았습니다 ({ctype or '형식 없음'}): {plain[:150]}")
        if _has_hole(dest):
            raise Corrupt("받은 파일 중간이 비어 있음 (전송 중 깨짐)")
        why = condition_problem(w, file_conditions(dest))
        if why:
            raise Mismatch(f"요청과 다른 검색 결과 파일을 받음 ({why})")
        return size


# ───────────────────────── 실행 ─────────────────────────

def _fname(w: Window) -> str:
    stamp = datetime.now(db.KST).strftime("%Y%m%d-%H%M%S")
    return f"{w.dataset}_{'all' if w.scope == '전국' else w.scope}_{w.date_from}_{w.date_to}_{stamp}.csv"


def fetch_one(s: Session, w: Window, names: dict[str, str]) -> dict:
    """창 하나: 자료 확인 → 다운로드 → ingest. 사이트 오류·한도·차단은 예외로 올린다 (부르는 쪽이 그날 멈춘다)."""
    from pipeline import re_upload
    name = names.get(w.dataset, w.dataset)
    log_id = _log_start(w, w.kind)
    try:
        cnt = s.check(w)
    except Exception as e:  # noqa: BLE001 - 기록을 닫고 그대로 올린다
        st = "blocked" if isinstance(e, Blocked) else "limit" if isinstance(e, LimitReached) else "error"
        _log_update(log_id, status=st, message=f"{type(e).__name__}: {e}"[:500] if st == "error" else str(e)[:500])
        raise
    if cnt == 0:
        _log_update(log_id, status="empty", cnt=0, rows=0, inserted=0, message="조건에 맞는 자료 없음")
        _mark(w, log_id)
        log.info("· CSV %s %s — 자료 없음", name, w.label)
        return {"status": "empty", "rows": 0, "inserted": 0}
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    fn = _fname(w)
    dest = DOWNLOAD_DIR / fn
    _log_update(log_id, cnt=cnt, downloaded=1, file=fn)  # 요청을 보내는 순간 하루 수에 센다
    try:
        size = s.download(w, dest)
    except Exception as e:  # noqa: BLE001 - 기록을 닫고 그대로 올린다
        st = "blocked" if isinstance(e, Blocked) else ("limit" if isinstance(e, LimitReached) else "error")
        _log_update(log_id, status=st, message=str(e)[:500])
        try:
            dest.unlink()
        except OSError:
            pass
        raise
    try:
        res = re_upload.ingest(dest, fn, dataset=w.dataset, size=size, note="자동 다운로드")
    except re_upload.UploadError as e:
        _log_update(log_id, status="error", message=f"파일 읽기 실패: {e}"[:500])
        if "맞지 않습니다" in str(e):
            raise Mismatch(f"요청과 다른 종류의 파일을 받음 ({e})") from e
        raise SiteError(f"받은 파일을 읽지 못했습니다 — 형식이 바뀌었을 수 있습니다 ({e})") from e
    msg = f"{res['rows_total']:,}행 → 새로 {res['inserted']:,} · 중복 {res['duplicates']:,} · 지원 지역 밖 {res['unmatched']:,}"
    _log_update(log_id, status="ok", rows=res["rows_total"], inserted=res["inserted"], message=msg)
    _mark(w, log_id)
    log.info("✓ CSV %s %s (%s행 → 새로 %s)", name, w.label, f"{res['rows_total']:,}", f"{res['inserted']:,}")
    return {"status": "ok", "rows": res["rows_total"], "inserted": res["inserted"], "file": fn, "upload_id": res.get("id")}


def run(datasets: list[dict], deadline: float, dry_run: bool = False, max_downloads: int | None = None) -> dict:
    """CSV 경로 — datasets 는 CSV 로 받을 실거래가 데이터셋. 하루 상한·멈춤·시간 상한을 지킨다."""
    names = {d["key"]: d["name"] for d in datasets}
    datasets = [d for d in datasets if d["key"] in CODES]
    used = downloads_today()
    cap = daily_cap()
    room = max(0, cap - used)
    if max_downloads is not None:
        room = min(room, max_downloads)
    out: dict = {"downloads": 0, "rows": 0, "inserted": 0, "empty": 0, "errors": 0, "today": used, "cap": cap,
                 "per_dataset": {}, "stopped": None, "requests": 0}
    if not datasets:
        return out
    stop = stopped_today()
    if dry_run:
        windows = plan(datasets)
        out["plan"] = [dict(w.as_dict(), within_cap=i < room) for i, w in enumerate(windows)]
        n_daily = sum(1 for w in windows if w.kind == "daily")
        log.info("▷ CSV 계획 (시험 실행 — 받지 않음): 오늘 %d/%d건 받았고 남은 몫 %d건%s", used, cap, room,
                 f" · 오늘은 멈춤 상태: {stop}" if stop else "")
        log.info("  매일 갱신 %d창 + 과거 채우기 %d창 (시도 %s)", n_daily, len(windows) - n_daily,
                 ", ".join(n for _, _, n in our_sidos()))
        for i, w in enumerate(windows):
            mark = "→" if i < room else "  (상한 밖, 다음 날)"
            if i < room + 5 or i == len(windows) - 1:
                log.info("  %s %s %s [%s] %s~%s", mark, names.get(w.dataset, w.dataset), w.label, w.kind, w.date_from, w.date_to)
            elif i == room + 5:
                log.info("  … %d창 더", len(windows) - room - 6)
        return out
    if stop:
        out["stopped"] = stop
        log.info("– CSV 자동 다운로드: 오늘은 멈춤 상태 (%s) — 내일 다시", stop)
        return out
    if room <= 0:
        out["stopped"] = f"오늘 상한 {cap}건을 다 씀"
        log.info("– CSV 자동 다운로드: 오늘 상한 %d건을 다 씀 — 내일 이어서", cap)
        return out
    n_old = cleanup()
    if n_old:
        log.info("오래된 CSV %d개 지움 (%d일 지남)", n_old, KEEP_DAYS)
    start_req = requests_made()
    with Session() as s:
        try:
            s.open()
            site_sidos = s.load_sidos()
        except SiteError as e:
            stop_for_today(str(e), blocked=isinstance(e, Blocked))
            out["stopped"] = str(e)
            out["requests"] = requests_made() - start_req
            return out
        windows = plan(datasets, sidos=our_sidos(site_sidos))
        log.info("▷ CSV 자동 다운로드: 오늘 %d/%d건 받음 · 이번에 최대 %d건 · 대상 %d창 (매일 %d + 과거 %d)", used, cap, room,
                 len(windows), sum(1 for w in windows if w.kind == "daily"), sum(1 for w in windows if w.kind != "daily"))
        for w in windows:
            if out["downloads"] >= room:
                out["stopped"] = f"하루 상한 {cap}건 — 나머지 {len(windows) - windows.index(w)}창은 다음 날"
                break
            if time.monotonic() > deadline:
                out["stopped"] = "시간 몫을 다 써서 멈춤 — 다음 실행에 이어서"
                break
            try:
                # 파일마다 새 세션 — 한 세션으로 연달아 받으면 사이트가 직전 파일을 다시 내준 일이 있었다 (간격은 전역으로 지킨다)
                with Session() as ws:
                    ws.open()
                    try:
                        r = fetch_one(ws, w, names)
                    except Mismatch as e:
                        log.warning("↻ CSV %s %s: %s — 새 세션으로 한 번 더", names.get(w.dataset, w.dataset), w.label, e)
                        time.sleep(15)
                        with Session() as ws2:
                            ws2.open()
                            try:
                                r = fetch_one(ws2, w, names)
                            except Mismatch as e2:
                                out["errors"] += 1
                                out["per_dataset"].setdefault(w.dataset, {"downloads": 0, "rows": 0, "inserted": 0})["error"] = str(e2)
                                log.warning("✗ CSV %s %s: 다시 받아도 다른 파일 — 이 창만 건너뜀", names.get(w.dataset, w.dataset), w.label)
                                continue
            except SiteError as e:
                out["errors"] += 1
                stop_for_today(str(e), blocked=isinstance(e, Blocked))
                out["stopped"] = (BLOCKED_LABEL + ": " if isinstance(e, Blocked) else "") + str(e)
                pd = out["per_dataset"].setdefault(w.dataset, {"downloads": 0, "rows": 0, "inserted": 0})
                pd["error"] = str(e)
                log.warning("✗ CSV %s %s: %s", names.get(w.dataset, w.dataset), w.label, e)
                break
            pd = out["per_dataset"].setdefault(w.dataset, {"downloads": 0, "rows": 0, "inserted": 0})
            if r["status"] == "empty":
                out["empty"] += 1
                continue
            out["downloads"] += 1
            out["rows"] += r["rows"]
            out["inserted"] += r["inserted"]
            pd["downloads"] += 1
            pd["rows"] += r["rows"]
            pd["inserted"] += r["inserted"]
    out["today"] = downloads_today()
    out["requests"] = requests_made() - start_req
    log.info("■ CSV 자동 다운로드: %d건 받아 %s행 → 새로 %s행 · 요청 %d번 · 오늘 %d/%d건%s", out["downloads"],
             f"{out['rows']:,}", f"{out['inserted']:,}", out["requests"], out["today"], cap,
             f" · {out['stopped']}" if out["stopped"] else "")
    return out


def run_single(dataset: str, scope: str, date_from: str, date_to: str, scope_name: str | None = None) -> dict:
    """창 하나만 받는다 (시험·수동 확인용). 하루 상한·멈춤을 지킨다."""
    if stopped_today():
        raise LimitReached(f"오늘은 멈춤 상태: {stopped_today()}")
    if downloads_today() >= daily_cap():
        raise LimitReached("오늘 상한을 다 씀")
    d0, d1 = date.fromisoformat(date_from), date.fromisoformat(date_to)
    months, m = [], _ym(d0)
    while m <= _ym(d1):
        months.append(m)
        m = re_store.shift_ymd(m, 1)
    names = {d["key"]: d["name"] for d in re_store.datasets()}
    start_req = requests_made()
    with Session() as s:
        s.open()
        if scope != "전국" and not scope_name:
            sid = s.load_sidos()
            scope_name = next((n for c, n in sid.values() if c == scope), scope)
        w = Window(dataset, scope, scope_name or "전국", date_from, date_to, months, "test")
        try:
            r = fetch_one(s, w, names)
        except SiteError as e:
            stop_for_today(str(e), blocked=isinstance(e, Blocked))
            raise
    r["requests"] = requests_made() - start_req
    return r


__all__ = ["CODES", "Session", "Window", "plan", "run", "run_single", "summary", "downloads_today", "daily_cap",
           "stopped_today", "SiteError", "LimitReached", "Blocked", "BLOCKED_LABEL"]
