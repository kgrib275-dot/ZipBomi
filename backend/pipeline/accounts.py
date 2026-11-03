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
import time
from datetime import datetime, timedelta

from . import db

LINK_MINUTES = 30
CODE_TRIES = 5
_SQL = (
    "CREATE TABLE IF NOT EXISTS accounts (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT NOT NULL UNIQUE, raw TEXT NOT NULL UNIQUE, "
    "created_at TEXT NOT NULL, last_login_at TEXT)",
    "CREATE TABLE IF NOT EXISTS login_tokens (token_hash TEXT PRIMARY KEY, email TEXT NOT NULL, expires_at TEXT NOT NULL, used_at TEXT)",
    # 기기별 로그인 (2026-11-03) — 브라우저 쿠키에는 계정 raw 대신 이 기기만의 값(sid 원값)을 심는다. DB 에는 해시만.
    "CREATE TABLE IF NOT EXISTS account_sessions (sid_hash TEXT PRIMARY KEY, account_id INTEGER NOT NULL, created_at TEXT NOT NULL, "
    "last_seen TEXT NOT NULL, ua TEXT NOT NULL DEFAULT '')",
    "CREATE INDEX IF NOT EXISTS idx_account_sessions_acc ON account_sessions(account_id)",
)
_COLS = (("login_tokens", "code_hash", "TEXT"), ("login_tokens", "nonce_hash", "TEXT"), ("login_tokens", "tries", "INTEGER DEFAULT 0"),
         ("login_tokens", "ncode_hash", "TEXT"), ("login_tokens", "code_used_at", "TEXT"),
         ("accounts", "revoke_hash", "TEXT"), ("accounts", "ask_credits", "INTEGER DEFAULT 1"), ("accounts", "ask_used", "INTEGER DEFAULT 0"))
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
        c.execute("INSERT INTO login_tokens (token_hash, email, expires_at, code_hash, nonce_hash, tries, ncode_hash) VALUES (?,?,?,?,?,0,?)",
                  (_h(token), email, (datetime.now() + timedelta(minutes=LINK_MINUTES)).isoformat(timespec="seconds"),
                   _h(token + code), _h(nonce), _h(nonce + code)))
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


def use_code(nonce: str | None, code: str) -> tuple[str | None, str]:
    """로그인 창에 바로 넣은 6자리 코드로 확정 (2026-11-03). 링크를 요청한 브라우저(nonce 쿠키) + 메일의 코드 = 링크와 같은 2가지 확인.
    휴대폰에서 메일 앱이 링크를 앱 안 브라우저로 열어 요청 기기로 인정되지 않던 문제를 피한다. (이메일, ok·bad_code·invalid)
    링크 사용(used_at)과 코드 사용(code_used_at)은 따로 센다 — 메일 앱에서 링크를 눌러 그쪽에서 로그인한 뒤에도, 처음 요청한 창에
    코드를 넣어 그 창도 로그인할 수 있게 (둘 다 메일함을 가진 사람만 할 수 있고, 각각 한 번만)."""
    if not nonce:
        return None, "invalid"
    c = _conn()
    c.isolation_level = None
    try:
        c.execute("BEGIN IMMEDIATE")
        row = c.execute("SELECT token_hash, email, expires_at, code_used_at, ncode_hash, tries FROM login_tokens WHERE nonce_hash=?",
                        (_h(nonce),)).fetchone()
        if not row or row["code_used_at"] or row["expires_at"] < _now() or (row["tries"] or 0) >= CODE_TRIES or not row["ncode_hash"]:
            c.execute("COMMIT")
            return None, "invalid"
        if not hmac.compare_digest(_h(nonce + code), row["ncode_hash"]):
            tries = (row["tries"] or 0) + 1
            c.execute("UPDATE login_tokens SET tries=? WHERE token_hash=?", (tries, row["token_hash"]))
            c.execute("COMMIT")
            return None, "invalid" if tries >= CODE_TRIES else "bad_code"
        c.execute("UPDATE login_tokens SET code_used_at=? WHERE token_hash=?", (_now(), row["token_hash"]))
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
        c.execute("DELETE FROM account_sessions WHERE account_id=?", (acc["id"],))  # 기기별 로그인도 모두 끊는다
        for table in ("visitor_state", "engagements", "subscribers", "profiles"):
            try:
                c.execute(f"UPDATE {table} SET visitor=? WHERE visitor=?", ("c:" + new, old))
            except Exception:  # noqa: BLE001 - 표·열이 없으면 건너뜀
                pass
        c.commit()
    finally:
        c.close()
    return new


# ───────── 기기별 로그인 (2026-11-03) ─────────
# 예전에는 로그인한 모든 기기의 쿠키가 계정 raw 하나였다 → 한 기기만 끊을 수 없고, 쿠키 하나가 새면 '모든 기기 로그아웃' 말고는 막을 길이 없었다.
# 이제 로그인할 때마다 그 기기만의 무작위 값(sid)을 쿠키에 심고, 요청마다 sid → 계정 raw 로 바꿔 쓴다(resolve, api/deps.py).
# 예전 방식 쿠키(계정 raw 그대로)도 그대로 받는다 — 다음 로그인 때 sid 로 바뀐다.
SESSION_IDLE_DAYS = 365  # 1년 동안 안 쓴 기기는 로그아웃 (쿠키 수명과 같음)
_SEEN_EVERY = 3600       # last_seen 은 1시간에 한 번만 고친다 (요청마다 쓰지 않게)
_SESS_CACHE_SEC = 5      # 다른 프로세스에서 끊은 기기도 늦어도 5초 안에 끊기게
_sess_cache: dict[str, tuple[float, str | None]] = {}


def new_session(acc_id: int, ua: str = "") -> str:
    sid = secrets.token_hex(16)
    c = _conn()
    try:
        c.execute("INSERT INTO account_sessions (sid_hash, account_id, created_at, last_seen, ua) VALUES (?,?,?,?,?)",
                  (_h(sid), acc_id, _now(), _now(), (ua or "")[:200]))
        c.commit()
    finally:
        c.close()
    return sid


def resolve(cookie_raw: str | None) -> tuple[str | None, str | None]:
    """쿠키 원값 → (이 요청이 쓸 방문자 raw, 기기 sid). 기기 로그인 값이면 계정 raw 로 바꾸고, 아니면 그대로(익명·예전 쿠키)."""
    if not cookie_raw:
        return cookie_raw, None
    now = time.monotonic()
    hit = _sess_cache.get(cookie_raw)
    if hit and now - hit[0] < _SESS_CACHE_SEC:
        return (hit[1], cookie_raw) if hit[1] else (cookie_raw, None)
    raw = None
    c = _conn()
    try:
        r = c.execute("SELECT s.last_seen, a.raw FROM account_sessions s JOIN accounts a ON a.id = s.account_id WHERE s.sid_hash=?",
                      (_h(cookie_raw),)).fetchone()
        if r:
            idle = (datetime.now() - datetime.fromisoformat(r["last_seen"])).total_seconds()
            if idle > SESSION_IDLE_DAYS * 86400:
                c.execute("DELETE FROM account_sessions WHERE sid_hash=?", (_h(cookie_raw),))
                c.commit()
            else:
                raw = r["raw"]
                if idle > _SEEN_EVERY:
                    try:
                        c.execute("UPDATE account_sessions SET last_seen=? WHERE sid_hash=?", (_now(), _h(cookie_raw)))
                        c.commit()
                    except Exception:  # noqa: BLE001 - DB 가 바쁘면 다음에
                        pass
    finally:
        c.close()
    if len(_sess_cache) > 20000:
        _sess_cache.clear()
    _sess_cache[cookie_raw] = (now, raw)
    return (raw, cookie_raw) if raw else (cookie_raw, None)


def end_session(sid: str | None) -> None:
    """이 기기만 로그아웃."""
    if not sid:
        return
    _sess_cache.pop(sid, None)
    c = _conn()
    try:
        c.execute("DELETE FROM account_sessions WHERE sid_hash=?", (_h(sid),))
        c.commit()
    finally:
        c.close()


def sessions(acc_id: int, current_sid: str | None) -> list[dict]:
    """내 공간 '로그인한 기기' 목록 — 기기 표시는 sid 해시 앞 12자리(원값은 내보내지 않는다)."""
    cur = _h(current_sid)[:12] if current_sid else ""
    c = _conn()
    try:
        rows = c.execute("SELECT sid_hash, created_at, last_seen, ua FROM account_sessions WHERE account_id=? ORDER BY last_seen DESC",
                         (acc_id,)).fetchall()
    finally:
        c.close()
    return [{"id": r["sid_hash"][:12], "created_at": r["created_at"], "last_seen": r["last_seen"], "ua": r["ua"],
             "current": r["sid_hash"][:12] == cur} for r in rows]


def end_session_by_id(acc_id: int, short_id: str) -> bool:
    """목록의 기기 하나를 로그아웃 — 그 계정의 기기만 지울 수 있다."""
    c = _conn()
    try:
        rows = c.execute("SELECT sid_hash FROM account_sessions WHERE account_id=?", (acc_id,)).fetchall()
        hit = [r["sid_hash"] for r in rows if r["sid_hash"][:12] == short_id]
        if len(hit) != 1:
            return False
        c.execute("DELETE FROM account_sessions WHERE sid_hash=?", (hit[0],))
        c.commit()
        return True
    finally:
        c.close()


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
        c.execute("DELETE FROM account_sessions WHERE account_id IN (SELECT id FROM accounts WHERE raw=?)", (raw,))
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


# ───────── 보미AI 횟수 (2026-11-02) — 계정마다 처음 1회 무료, 더 쓰려면 관리자가 늘려 준다 ─────────
def ask_state(acc_id: int) -> tuple[int, int]:
    c = _conn()
    try:
        r = c.execute("SELECT COALESCE(ask_credits, 1), COALESCE(ask_used, 0) FROM accounts WHERE id=?", (acc_id,)).fetchone()
        return (r[0], r[1]) if r else (0, 0)
    finally:
        c.close()


def ask_consume(acc_id: int) -> bool:
    """남은 횟수가 있을 때만 1 쓴다 (조건부 UPDATE — 동시에 두 번 와도 넘지 않게)."""
    c = _conn()
    try:
        n = c.execute("UPDATE accounts SET ask_used = COALESCE(ask_used, 0) + 1 WHERE id=? AND COALESCE(ask_used, 0) < COALESCE(ask_credits, 1)",
                      (acc_id,)).rowcount
        c.commit()
        return n == 1
    finally:
        c.close()


def ask_refund(acc_id: int) -> None:
    c = _conn()
    try:
        c.execute("UPDATE accounts SET ask_used = MAX(COALESCE(ask_used, 0) - 1, 0) WHERE id=?", (acc_id,))
        c.commit()
    finally:
        c.close()


def ask_grant(acc_id: int, n: int) -> tuple[int, int]:
    """관리자가 횟수를 늘린다 (음수면 줄인다, 쓴 수보다 아래로는 안 내려간다)."""
    c = _conn()
    try:
        c.execute("UPDATE accounts SET ask_credits = MAX(COALESCE(ask_credits, 1) + ?, COALESCE(ask_used, 0)) WHERE id=?", (n, acc_id))
        c.commit()
    finally:
        c.close()
    return ask_state(acc_id)
