"""사용자 피드백 (2026-11-19) — 보미AI 답변 👍👎, 숫자·화면 오류 신고('이상해요'). 관리 > 피드백에서 본다. LLM 없음.

- ask_up: 👍 — 건수만 센다. 질문·답변 글은 저장하지 않는다.
- ask_down: 👎 — 질문 앞 200자·답변 앞 500자를 저장한다(누르기 전에 화면에 안내). 이메일·계정 정보는 저장하지 않는다.
- data: 오류 신고 — 화면 경로·본인이 쓴 설명(300자)·참고 값. 계정 정보는 저장하지 않는다.
180일이 지난 기록은 새 기록을 받을 때 함께 지운다. 방문자 식별값은 해시의 앞부분만 두어 같은 사람이 도배하는 것을 막는 데만 쓴다.
"""
from __future__ import annotations

import hashlib
import time
from datetime import datetime, timedelta

from . import db

KINDS = ("ask_up", "ask_down", "data")
KEEP_DAYS = 180
_SQL = ("CREATE TABLE IF NOT EXISTS user_feedback (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, page TEXT NOT NULL DEFAULT '', "
        "text TEXT NOT NULL DEFAULT '', extra TEXT NOT NULL DEFAULT '', who TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'open', created_at TEXT NOT NULL)",
        "CREATE INDEX IF NOT EXISTS idx_user_feedback_kind ON user_feedback(kind, status)")
_ready: list = []


def _conn():
    c = db.connect()
    if not _ready:
        for q in _SQL:
            c.execute(q)
        c.commit()
        _ready.append(True)
    return c


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def add(kind: str, visitor: str, page: str = "", text: str = "", extra: str = "") -> int:
    if kind not in KINDS:
        raise ValueError("kind")
    if kind == "ask_up":
        text = extra = ""
    who = hashlib.sha256(("fb:" + visitor).encode()).hexdigest()[:10]
    c = _conn()
    try:
        c.execute("DELETE FROM user_feedback WHERE created_at < ?", ((datetime.now() - timedelta(days=KEEP_DAYS)).strftime("%Y-%m-%dT%H:%M:%S"),))
        cur = c.execute("INSERT INTO user_feedback (kind, page, text, extra, who, created_at) VALUES (?,?,?,?,?,?)",
                        (kind, page[:120], text[:300 if kind == "data" else 200], extra[:500], who, _now()))
        c.commit()
        return cur.lastrowid
    finally:
        c.close()


def listing(kind: str = "", status: str = "", limit: int = 200) -> list[dict]:
    c = _conn()
    try:
        w, a = [], []
        if kind:
            w.append("kind=?"); a.append(kind)
        if status:
            w.append("status=?"); a.append(status)
        rows = c.execute(f"SELECT id, kind, page, text, extra, status, created_at FROM user_feedback{' WHERE ' + ' AND '.join(w) if w else ''} ORDER BY id DESC LIMIT ?", (*a, limit)).fetchall()
        return [dict(zip(("id", "kind", "page", "text", "extra", "status", "created_at"), r)) for r in rows]
    finally:
        c.close()


def counts() -> dict:
    c = _conn()
    try:
        d = {k: 0 for k in KINDS}
        for k, n in c.execute("SELECT kind, COUNT(*) FROM user_feedback GROUP BY kind"):
            d[k] = n
        d["open"] = c.execute("SELECT COUNT(*) FROM user_feedback WHERE status='open' AND kind<>'ask_up'").fetchone()[0]
        return d
    finally:
        c.close()


def set_status(fid: int, status: str) -> None:
    c = _conn()
    try:
        c.execute("UPDATE user_feedback SET status=? WHERE id=?", ("done" if status == "done" else "open", fid))
        c.commit()
    finally:
        c.close()


def delete(fid: int) -> None:
    c = _conn()
    try:
        c.execute("DELETE FROM user_feedback WHERE id=?", (fid,))
        c.commit()
    finally:
        c.close()
