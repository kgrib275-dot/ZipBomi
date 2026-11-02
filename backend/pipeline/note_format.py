"""노트 형식 (Phase 4, 2026-11-02) — brief(3분 요약) · deep(깊이 읽기) · data(숫자로 보기).

notes.format 이 비어 있으면(NULL) 본문 길이·표·숫자 밀도로 정한다 (LLM 없음). 관리자가 노트 검토에서 바꿀 수 있다.
"""
from __future__ import annotations

import re

from pipeline import db

FORMATS = {"brief": "3분 요약", "deep": "깊이 읽기", "data": "숫자로 보기"}
_NUM = re.compile(r"\d[\d,.]*\s*(%|%p|억|만\s*원|만원|건|배|㎡|포인트)")
_DATA_WORDS = re.compile(r"실거래|거래량|통계|지수|경쟁률|가점|변동률|시세|전세가율|금리")


def detect(n: dict) -> str:
    body = n.get("body") or ""
    title = n.get("title") or ""
    nums = len(_NUM.findall(body))
    table = bool(re.search(r"^\s*\|.*\|\s*$\n^\s*\|?\s*:?-{3,}", body, re.M))
    if table or (nums >= 12 and _DATA_WORDS.search(title + " " + (n.get("tags") or ""))):
        return "data"
    if len(body) >= 2500 or (n.get("kind") == "정책 해설" and len(body) >= 1500):
        return "deep"
    return "brief"


def of(n: dict) -> str:
    f = n.get("format")
    return f if f in FORMATS else detect(n)


def backfill(force: bool = False) -> dict:
    conn = db.connect()
    try:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(notes)")}
        if "format" not in cols:
            return {"checked": 0}
        where = "" if force else "WHERE format IS NULL OR format = ''"
        rows = [dict(r) for r in conn.execute(f"SELECT id, title, tags, kind, body FROM notes {where}")]
        counts: dict[str, int] = {}
        with conn:
            for r in rows:
                f = detect(r)
                counts[f] = counts.get(f, 0) + 1
                conn.execute("UPDATE notes SET format=? WHERE id=?", (f, r["id"]))
        return {"checked": len(rows), **counts}
    finally:
        conn.close()
