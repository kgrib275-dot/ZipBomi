"""함께 보기 — 내 관심 단지·관심 공고를 가족·친구에게 읽기 전용 링크(/g/<토큰>)로 보여 준다 (2026-11-20).

- 토큰은 128비트 무작위, DB 에는 해시만(복원 불가) — 링크는 만들 때 한 번만 보여 주고, 새로 만들면 예전 링크는 멈춘다(주인당 하나).
- 주인이 고른 것(관심 단지·관심 공고)만 보인다. 내 일정·할 일·메모·예산·소득·가점·이메일은 절대 나가지 않는다.
- 30일 뒤 저절로 만료, 언제든 멈출 수 있다. 모든 기기 로그아웃·탈퇴 때 함께 지운다. 검색에 잡히지 않는다(noindex).
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import time
from datetime import datetime, timedelta

from . import db

INCLUDE = ("apts", "notices")
TTL_DAYS = 30
TOKEN_RE = re.compile(r"^[0-9a-f]{32}$")
_SQL = ("CREATE TABLE IF NOT EXISTS share_board (token_hash TEXT PRIMARY KEY, visitor TEXT NOT NULL UNIQUE, include TEXT NOT NULL, created_at TEXT NOT NULL, "
        "expires_at TEXT NOT NULL, views INTEGER NOT NULL DEFAULT 0, last_view_at TEXT)",)
_ready: list = []


def _conn():
    c = db.connect()
    if not _ready:
        for q in _SQL:
            c.execute(q)
        c.commit()
        _ready.append(True)
    return c


def _h(token: str) -> str:
    return hashlib.sha256(("board:" + token).encode()).hexdigest()


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def create(visitor: str, include: list[str]) -> str:
    """새 링크 — 예전 링크는 멈춘다. 토큰을 돌려준다(DB 에는 해시만)."""
    inc = [x for x in dict.fromkeys(include or []) if x in INCLUDE] or list(INCLUDE)
    token = secrets.token_hex(16)
    c = _conn()
    try:
        c.execute("DELETE FROM share_board WHERE visitor=?", (visitor,))
        c.execute("INSERT INTO share_board (token_hash, visitor, include, created_at, expires_at) VALUES (?,?,?,?,?)",
                  (_h(token), visitor, json.dumps(inc), _now(), (datetime.now() + timedelta(days=TTL_DAYS)).isoformat(timespec="seconds")))
        c.execute("DELETE FROM share_board WHERE expires_at < ?", (_now(),))  # 만료된 것은 새로 만들 때 정리
        c.commit()
    finally:
        c.close()
    return token


def status(visitor: str) -> dict | None:
    c = _conn()
    try:
        r = c.execute("SELECT include, created_at, expires_at, views, last_view_at FROM share_board WHERE visitor=? AND expires_at >= ?", (visitor, _now())).fetchone()
    finally:
        c.close()
    return {"include": json.loads(r[0]), "created_at": r[1], "expires_at": r[2], "views": r[3], "last_view_at": r[4]} if r else None


def stop(visitor: str) -> None:
    c = _conn()
    try:
        c.execute("DELETE FROM share_board WHERE visitor=?", (visitor,))
        c.commit()
    finally:
        c.close()


def lookup(token: str, count_view: bool = True) -> dict | None:
    """토큰 → {visitor, include}. 형식이 틀리거나 없거나 만료면 None. 열람 수를 센다."""
    if not TOKEN_RE.match(token or ""):
        return None
    c = _conn()
    try:
        r = c.execute("SELECT visitor, include, expires_at FROM share_board WHERE token_hash=?", (_h(token),)).fetchone()
        if not r or r[2] < _now():
            return None
        if count_view:
            c.execute("UPDATE share_board SET views = views + 1, last_view_at=? WHERE token_hash=?", (_now(), _h(token)))
            c.commit()
        return {"visitor": r[0], "include": json.loads(r[1])}
    finally:
        c.close()


def snapshot(st: dict, include: list[str]) -> dict:
    """주인 저장값에서 공유할 것만 뽑는다 — 관심 단지(최대 10)·관심 공고(최대 10). 그 밖의 값은 읽지도 않는다."""
    from . import pubdata
    out: dict = {"apts": [], "notices": []}
    if "apts" in include:
        for w in (st.get("re_watch") or [])[:30]:
            if isinstance(w, dict) and w.get("apt") and w.get("lawd") and len(out["apts"]) < 10:
                a = pubdata.apt_info(str(w["lawd"]), str(w["apt"]), str(w.get("dong") or ""))
                out["apts"].append({"lawd": str(w["lawd"]), "dong": str(w.get("dong") or ""), "apt": str(w["apt"]), "region": str(w.get("region") or ""),
                                    "info": a})
    if "notices" in include:
        ids: list[str] = []
        prof = st.get("profile") if isinstance(st.get("profile"), dict) else {}
        for x in list(prof.get("alert_apply") or []) + list(st.get("apply_fav") or []):
            nid = x.get("notice_id") if isinstance(x, dict) else x
            if isinstance(nid, str) and nid not in ids:
                ids.append(nid)
        for nid in ids[:20]:
            n = pubdata.notice(nid)
            if n and len(out["notices"]) < 10:
                out["notices"].append(n)
    return out


def remove_visitor(visitor: str) -> None:
    stop(visitor)
