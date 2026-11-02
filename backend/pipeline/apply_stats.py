"""청약홈 청약 신청·당첨자 통계 (공공데이터포털 15110812, ApplyhomeStatSvc) — 2026-11-02.

월별·지역별 신청자, 연령별 신청자·당첨자, 지역별 경쟁률, 지역별 가점제 당첨 점수(최저·중위·평균·최고)를 받아
re_apply_stat 에 그대로 쌓는다(종류·월·지역·거주구분이 키, 나머지 값은 JSON). 매일 부동산 데이터 작업(jobs.re_data) 끝에 한 번.
화면: /calendar?tab=scores (api/routers/calendar.py /re/apply-stats).
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime

import httpx

from . import db, rtms

log = logging.getLogger(__name__)
BASE = "https://api.odcloud.kr/api/ApplyhomeStatSvc/v1/"
OPS = {
    "req_area": "getAPTReqstAreaStat",       # 지역별 신청자 (연령대별 수)
    "req_age": "getAPTReqstAgeStat",         # 연령별 신청자 (전국)
    "win_area": "getAPTPrzwnerAreaStat",     # 지역별 당첨자
    "win_age": "getAPTPrzwnerAgeStat",       # 연령별 당첨자 (전국)
    "cmpet_area": "getAPTCmpetrtAreaStat",   # 지역별 경쟁률
    "score_area": "getAPTApsPrzwnerStat",    # 지역별 가점제 당첨 점수
}
_SQL = ("CREATE TABLE IF NOT EXISTS re_apply_stat (kind TEXT NOT NULL, stat_de TEXT NOT NULL, area TEXT NOT NULL DEFAULT '', "
        "reside TEXT NOT NULL DEFAULT '', data TEXT NOT NULL, fetched_at TEXT NOT NULL, PRIMARY KEY (kind, stat_de, area, reside))")


def _conn():
    c = db.connect()
    c.execute(_SQL)
    return c


def refresh(per_page: int = 1000, delay: float = 0.2) -> dict:
    """모든 통계를 처음부터 다시 받아 덮어쓴다 (전체가 수천 건이라 한 번에)."""
    key = rtms.api_key()
    if not key:
        return {"status": "no_key"}
    out: dict = {}
    now = datetime.now().isoformat(timespec="seconds")
    with httpx.Client(timeout=30) as cl:
        for kind, op in OPS.items():
            rows, page = [], 1
            try:
                while True:
                    r = cl.get(BASE + op, params={"page": page, "perPage": per_page, "serviceKey": key})
                    if r.status_code in (401, 403):
                        out[kind] = "not_registered"
                        break
                    r.raise_for_status()
                    d = r.json()
                    rows += d.get("data") or []
                    if page * per_page >= int(d.get("totalCount") or 0):
                        break
                    page += 1
                    time.sleep(delay)
            except Exception as e:  # noqa: BLE001 - 한 종류 실패가 나머지를 막지 않게
                log.warning("청약 통계 %s 실패: %s", kind, e)
                out[kind] = "error"
                continue
            if out.get(kind):
                continue
            c = _conn()
            try:
                c.executemany("INSERT OR REPLACE INTO re_apply_stat (kind, stat_de, area, reside, data, fetched_at) VALUES (?,?,?,?,?,?)",
                              [(kind, str(x.get("STAT_DE") or ""), str(x.get("SUBSCRPT_AREA_CODE_NM") or ""), str(x.get("RESIDE_SECD_NM") or ""),
                                json.dumps(x, ensure_ascii=False), now) for x in rows if x.get("STAT_DE")])
                c.commit()
            finally:
                c.close()
            out[kind] = len(rows)
            log.info("청약 통계 %s %d건", kind, len(rows))
    return out


def load(kind: str, since: str = "") -> list[dict]:
    c = _conn()
    try:
        rows = c.execute("SELECT stat_de, area, reside, data FROM re_apply_stat WHERE kind=? AND stat_de>=? ORDER BY stat_de", (kind, since)).fetchall()
    finally:
        c.close()
    return [{"ym": r["stat_de"], "area": r["area"], "reside": r["reside"], **json.loads(r["data"])} for r in rows]
