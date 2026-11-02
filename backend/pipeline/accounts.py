"""계정 — 메일 링크 로그인 (2026-11-02).

비밀번호는 두지 않는다. 메일로 받은 링크(30분, 한 번만)를 누르면 그 브라우저가 계정에 묶인다.
계정은 '방문자 쿠키 원값(raw)' 하나를 가진다 — 로그인하면 브라우저 쿠키를 계정의 raw 로 바꿔 심으므로
지금까지의 방문자 상태(프로필·관심 단지·알림·필터·계산 입력, api/routers/me.py visitor_state)가 기기와 상관없이 그대로 이어진다.

보안 3중 (2026-11-02):
1) 메일 소유 — 1회용 링크(128비트, sha256 해시만 저장, 30분, 한 번만). 링크를 열기만 해서는 쓰이지 않고 화면 버튼으로 확정.
2) 요청 기기 — 링크를 요청한 브라우저(요청 때 심은 nonce 쿠키)면 바로, 다른 기기면 메일의 6자리 코드를 함께 넣어야 한다.
   코드는 5번 틀리면 그 링크를 무효로 한다. (링크만 새어 나가서는 로그인할 수 없다)
3) 탈취 대응 — 로그인할 때마다 알림 메일, 그 메일의 '모든 기기에서 로그아웃'(또는 내 공간 버튼)은 계정 raw 를 새로 바꿔
   다른 기기의 쿠키를 모두 무효로 만든다. 요청·확인 횟수 제한은 api/routers/auth.py.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta

from . import db

LINK_MINUTES = 30
CODE_TRIES = 5
_SQL = (
    "CREATE TABLE IF NOT EXISTS accounts (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT NOT NULL UNIQUE, raw TEXT NOT NULL UNIQUE, "
    "created_at TEXT NOT NULL, last_login_at TEXT)",
    "CREATE TABLE IF NOT EXISTS login_tokens (token_hash TEXT PRIMARY KEY, email TEXT NOT NULL, expires_at TEXT NOT NULL, used_at TEXT)",
)
_COLS = (("login_tokens", "code_hash", "TEXT"), ("login_tokens", "nonce_hash", "TEXT"), ("login_tokens", "tries", "INTEGER DEFAULT 0"),
         ("accounts", "revoke_hash", "TEXT"))
_ready: list = []


def _conn():
    c = db.connect()
    if not _ready:
        for q in _SQL:
            c.execute(q)
        for t, col, typ in _COLS:
            if col not in {r[1] for r in c.execute(f"PRAGMA table_info({t})")}:
                c.execute(f"ALTER TABLE {t} ADD COLUMN {col} {typ}")
        c.commit()
        _ready.append(True)
    return c


def _h(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def new_link(email: str) -> tuple[str, str, str]:
    """(링크 토큰, 6자리 코드, 요청 브라우저 nonce) — 원값은 메일·쿠키에만, DB 에는 해시."""
    token, nonce = secrets.token_hex(16), secrets.token_hex(16)
    code = f"{secrets.randbelow(1_000_000):06d}"
    c = _conn()
    try:
        c.execute("DELETE FROM login_tokens WHERE expires_at < ?", (_now(),))
        c.execute("INSERT INTO login_tokens (token_hash, email, expires_at, code_hash, nonce_hash, tries) VALUES (?,?,?,?,?,0)",
                  (_h(token), email, (datetime.now() + timedelta(minutes=LINK_MINUTES)).isoformat(timespec="seconds"),
                   _h(token + code), _h(nonce)))
        c.commit()
    finally:
        c.close()
    return token, code, nonce


def use_link(token: str, nonce: str | None, code: str | None) -> tuple[str | None, str]:
    """(이메일, 결과). 결과: ok · need_code(다른 기기 — 코드 필요) · bad_code · invalid(없음·만료·사용됨·시도 초과).
    맞으면 링크를 쓴 것으로 표시해 다시 못 쓴다."""
    c = _conn()
    c.isolation_level = None
    try:
        c.execute("BEGIN IMMEDIATE")
        row = c.execute("SELECT email, expires_at, used_at, code_hash, nonce_hash, tries FROM login_tokens WHERE token_hash=?",
                        (_h(token),)).fetchone()
        if not row or row["used_at"] or row["expires_at"] < _now() or (row["tries"] or 0) >= CODE_TRIES:
            c.execute("COMMIT")
            return None, "invalid"
        same_device = bool(nonce) and hmac.compare_digest(_h(nonce), row["nonce_hash"] or "")
        if not same_device:
            if not code:
                c.execute("COMMIT")
                return None, "need_code"
            if not hmac.compare_digest(_h(token + code), row["code_hash"] or ""):
                tries = (row["tries"] or 0) + 1
                c.execute("UPDATE login_tokens SET tries=? WHERE token_hash=?", (tries, _h(token)))
                c.execute("COMMIT")
                return None, "invalid" if tries >= CODE_TRIES else "bad_code"
        c.execute("UPDATE login_tokens SET used_at=? WHERE token_hash=?", (_now(), _h(token)))
        c.execute("COMMIT")
        return row["email"], "ok"
    except BaseException:
        if c.in_transaction:
            c.execute("ROLLBACK")
        raise
    finally:
        c.close()


def by_email(email: str) -> dict | None:
    c = _conn()
    try:
        r = c.execute("SELECT id, email, raw, created_at, last_login_at FROM accounts WHERE email=?", (email,)).fetchone()
        return dict(r) if r else None
    finally:
        c.close()


def by_raw(raw: str | None) -> dict | None:
    if not raw:
        return None
    c = _conn()
    try:
        r = c.execute("SELECT id, email, raw, created_at, last_login_at FROM accounts WHERE raw=?", (raw,)).fetchone()
        return dict(r) if r else None
    finally:
        c.close()


def login(email: str, current_raw: str) -> tuple[dict, bool, str]:
    """(계정, 새 계정인지, 모든 기기 로그아웃 링크 토큰). 새 계정이면 지금 브라우저 raw 를 계정 raw 로 삼는다."""
    revoke = secrets.token_hex(16)
    acc = by_email(email)
    c = _conn()
    try:
        if acc:
            c.execute("UPDATE accounts SET last_login_at=?, revoke_hash=? WHERE id=?", (_now(), _h(revoke), acc["id"]))
            c.commit()
            return acc, False, revoke
        raw = current_raw
        if by_raw(raw):  # 이 브라우저가 이미 다른 계정 — 새 raw 로 시작
            raw = secrets.token_hex(16)
        c.execute("INSERT INTO accounts (email, raw, created_at, last_login_at, revoke_hash) VALUES (?,?,?,?,?)",
                  (email, raw, _now(), _now(), _h(revoke)))
        c.commit()
    finally:
        c.close()
    return by_email(email) or {}, True, revoke


def rotate(acc: dict) -> str:
    """모든 기기에서 로그아웃 — 계정 raw 를 새 값으로 바꾸고 저장 자료(방문자 상태·참여 기록·구독 연결)를 새 값으로 옮긴다.
    예전 raw 쿠키를 가진 기기는 빈 익명 방문자가 된다. 새 raw 를 돌려준다."""
    old, new = "c:" + acc["raw"], secrets.token_hex(16)
    c = _conn()
    try:
        c.execute("UPDATE accounts SET raw=?, revoke_hash=NULL WHERE id=?", (new, acc["id"]))
        for table in ("visitor_state", "engagements", "subscribers", "profiles"):
            try:
                c.execute(f"UPDATE {table} SET visitor=? WHERE visitor=?", ("c:" + new, old))
            except Exception:  # noqa: BLE001 - 표·열이 없으면 건너뜀
                pass
        c.commit()
    finally:
        c.close()
    return new


def by_revoke(token: str) -> dict | None:
    c = _conn()
    try:
        r = c.execute("SELECT id, email, raw, created_at, last_login_at FROM accounts WHERE revoke_hash=?", (_h(token),)).fetchone()
        return dict(r) if r else None
    finally:
        c.close()


def delete_by_raw(raw: str) -> int:
    c = _conn()
    try:
        n = c.execute("DELETE FROM accounts WHERE raw=?", (raw,)).rowcount
        c.commit()
        return n
    finally:
        c.close()


def count() -> int:
    c = _conn()
    try:
        return c.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
    finally:
        c.close()
