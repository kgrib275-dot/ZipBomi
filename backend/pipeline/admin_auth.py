"""관리자 인증·접속기록 (2026-11-03, ISMS-P 기술 통제).

ISMS-P 2.5(인증·권한), 2.9.4(로그·접속기록), 개인정보 안전성 확보조치 기준 제5·6·8조에 맞춘 것:
- 관리자 로그인 세션: .env ADMIN_TOKEN(+ ADMIN_TOTP_SECRET 이 있으면 OTP 6자리)으로 로그인하면 HttpOnly·SameSite=Strict 쿠키(zga)를 준다.
  브라우저 저장소(localStorage)에 토큰을 두지 않는다 — 화면 스크립트 취약점이 생겨도 관리 권한을 꺼내 갈 수 없게.
  30분 동안 쓰지 않거나 로그인 8시간이 지나면 끊긴다 (개인정보처리시스템 일정 시간 미사용 시 접속 차단).
- 로그인 실패: 같은 IP 에서 30분 안에 5번 틀리면 30분 잠금 (DB 기록이라 프로세스가 여러 개여도 같다).
- 접속기록(admin_audit): 누가(관리자 세션)·언제·어디서(IP)·무엇을(요청·대상·결과)·왜(다운로드·전체 보기 사유).
  행마다 바로 앞 행과 이은 해시(hash chain)를 남겨 중간을 고치거나 지우면 verify() 가 찾아낸다. 2년 보관.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import struct
import time
from datetime import datetime, timedelta

from . import db

IDLE_SEC = 30 * 60          # 이 시간 동안 요청이 없으면 로그아웃
MAX_SEC = 8 * 3600          # 로그인 뒤 최대 유지 시간
FAIL_LIMIT, FAIL_WINDOW_MIN = 5, 30
AUDIT_KEEP_DAYS = 730       # 접속기록 2년 보관
COOKIE = "zga"
_SEEN_EVERY = 60            # last_seen 은 1분에 한 번만 고친다
_SQL = (
    "CREATE TABLE IF NOT EXISTS admin_sessions (sid_hash TEXT PRIMARY KEY, created REAL NOT NULL, last_seen REAL NOT NULL, "
    "ip TEXT, ua TEXT NOT NULL DEFAULT '')",
    "CREATE TABLE IF NOT EXISTS admin_audit (id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, actor TEXT NOT NULL, ip TEXT, "
    "method TEXT NOT NULL DEFAULT '', path TEXT NOT NULL DEFAULT '', query TEXT NOT NULL DEFAULT '', status INTEGER, "
    "kind TEXT NOT NULL DEFAULT 'request', detail TEXT NOT NULL DEFAULT '', prev_hash TEXT NOT NULL, hash TEXT NOT NULL)",
    "CREATE INDEX IF NOT EXISTS ix_admin_audit_at ON admin_audit(at)",
    "CREATE INDEX IF NOT EXISTS ix_admin_audit_kind_ip ON admin_audit(kind, ip, at)",
)
_ready: list = []


def _conn():
    c = db.connect()
    if not _ready:
        for q in _SQL:
            c.execute(q)
        c.commit()
        _ready.append(True)
    return c


def _h(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


# ───────── OTP (RFC 6238 TOTP, 30초·6자리) — Google OTP·Microsoft Authenticator 등에 ADMIN_TOTP_SECRET 을 등록해 쓴다 ─────────
def totp_secret() -> str:
    return os.environ.get("ADMIN_TOTP_SECRET", "").strip().replace(" ", "").upper()


def _totp(secret: str, step: int) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    mac = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    o = mac[-1] & 0x0F
    return f"{(struct.unpack('>I', mac[o:o + 4])[0] & 0x7FFFFFFF) % 1_000_000:06d}"


def otp_ok(code: str | None, now: float | None = None) -> bool:
    secret = totp_secret()
    if not secret:
        return True
    if not code or not code.isdigit() or len(code) != 6:
        return False
    step = int((now or time.time()) // 30)
    try:
        return any(hmac.compare_digest(_totp(secret, step + d), code) for d in (-1, 0, 1))  # 앞뒤 30초 시계 차이 허용
    except (ValueError, base64.binascii.Error):
        return False


def new_totp_secret() -> str:
    """처음 설정할 때 쓸 무작위 비밀값 (base32, 160비트)."""
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


# ───────── 로그인 ─────────
def locked(ip: str | None) -> bool:
    since = (datetime.now() - timedelta(minutes=FAIL_WINDOW_MIN)).isoformat(timespec="seconds")
    c = _conn()
    try:
        n = c.execute("SELECT COUNT(*) FROM admin_audit WHERE kind='login_fail' AND ip IS ? AND at >= ?", (ip, since)).fetchone()[0]
    finally:
        c.close()
    return n >= FAIL_LIMIT


def login(token: str, otp: str | None, ip: str | None, ua: str) -> tuple[str | None, str]:
    """(세션 원값, 결과). 결과: ok · locked · bad · not_configured."""
    expect = os.environ.get("ADMIN_TOKEN", "").strip()
    if not expect:
        return None, "not_configured"
    if locked(ip):
        audit("-", ip, "POST", "/api/auth/admin-login", 429, kind="login_locked")
        return None, "locked"
    ok = bool(token) and hmac.compare_digest(token.encode(), expect.encode()) and otp_ok(otp)
    if not ok:
        audit("-", ip, "POST", "/api/auth/admin-login", 401, kind="login_fail", detail="토큰 또는 OTP 불일치")
        return None, "bad"
    sid = secrets.token_hex(32)
    now = time.time()
    c = _conn()
    try:
        c.execute("DELETE FROM admin_sessions WHERE last_seen < ? OR created < ?", (now - IDLE_SEC, now - MAX_SEC))
        c.execute("INSERT INTO admin_sessions (sid_hash, created, last_seen, ip, ua) VALUES (?,?,?,?,?)",
                  (_h(sid), now, now, ip, (ua or "")[:200]))
        c.commit()
    finally:
        c.close()
    audit(actor_of(sid), ip, "POST", "/api/auth/admin-login", 200, kind="login", detail=(ua or "")[:120])
    return sid, "ok"


def actor_of(sid: str | None) -> str:
    return "admin:" + _h(sid)[:10] if sid else "-"


def check(sid: str | None) -> bool:
    """세션이 살아 있는지 — 쓰지 않은 지 30분, 로그인 8시간이 지나면 지운다."""
    if not sid or len(sid) != 64:
        return False
    now = time.time()
    c = _conn()
    try:
        r = c.execute("SELECT created, last_seen FROM admin_sessions WHERE sid_hash=?", (_h(sid),)).fetchone()
        if not r:
            return False
        if now - r["last_seen"] > IDLE_SEC or now - r["created"] > MAX_SEC:
            c.execute("DELETE FROM admin_sessions WHERE sid_hash=?", (_h(sid),))
            c.commit()
            return False
        if now - r["last_seen"] > _SEEN_EVERY:
            c.execute("UPDATE admin_sessions SET last_seen=? WHERE sid_hash=?", (now, _h(sid)))
            c.commit()
        return True
    finally:
        c.close()


def logout(sid: str | None, ip: str | None) -> None:
    if not sid:
        return
    c = _conn()
    try:
        c.execute("DELETE FROM admin_sessions WHERE sid_hash=?", (_h(sid),))
        c.commit()
    finally:
        c.close()
    audit(actor_of(sid), ip, "POST", "/api/auth/admin-logout", 200, kind="logout")


# ───────── 접속기록 ─────────
def _row_hash(prev: str, row: dict) -> str:
    body = json.dumps([row[k] for k in ("at", "actor", "ip", "method", "path", "query", "status", "kind", "detail")], ensure_ascii=False)
    return _h(prev + body)


def audit(actor: str, ip: str | None, method: str, path: str, status: int | None, query: str = "", kind: str = "request",
          detail: str = "") -> None:
    """접속기록 한 줄. 앞 행 해시를 읽고 쓰는 사이에 다른 프로세스가 끼지 않게 BEGIN IMMEDIATE 로 묶는다."""
    row = {"at": datetime.now().isoformat(timespec="seconds"), "actor": actor, "ip": ip, "method": method, "path": path[:200],
           "query": (query or "")[:300], "status": status, "kind": kind, "detail": (detail or "")[:500]}
    c = _conn()
    c.isolation_level = None
    try:
        c.execute("BEGIN IMMEDIATE")
        last = c.execute("SELECT hash FROM admin_audit ORDER BY id DESC LIMIT 1").fetchone()
        prev = last["hash"] if last else "0" * 64
        c.execute("INSERT INTO admin_audit (at, actor, ip, method, path, query, status, kind, detail, prev_hash, hash) "
                  "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                  (row["at"], actor, ip, method, row["path"], row["query"], status, kind, row["detail"], prev, _row_hash(prev, row)))
        c.execute("COMMIT")
    except BaseException:
        if c.in_transaction:
            c.execute("ROLLBACK")
        raise
    finally:
        c.close()


def recent(limit: int = 300, kind: str = "", q: str = "") -> list[dict]:
    where, params = [], []
    if kind:
        where.append("kind = ?"); params.append(kind)
    if q:
        where.append("(path LIKE ? OR detail LIKE ? OR ip LIKE ?)"); params += [f"%{q}%"] * 3
    sql = "SELECT id, at, actor, ip, method, path, query, status, kind, detail FROM admin_audit"
    sql += (" WHERE " + " AND ".join(where)) if where else ""
    c = _conn()
    try:
        return [dict(r) for r in c.execute(sql + " ORDER BY id DESC LIMIT ?", (*params, max(1, min(limit, 2000))))]
    finally:
        c.close()


def verify() -> dict:
    """해시 사슬 검사 — 남아 있는 첫 행의 prev_hash 부터 차례로 다시 계산해 맞지 않는 첫 행을 알려 준다."""
    c = _conn()
    try:
        rows = c.execute("SELECT * FROM admin_audit ORDER BY id").fetchall()
    finally:
        c.close()
    prev = rows[0]["prev_hash"] if rows else "0" * 64
    for r in rows:
        d = dict(r)
        if d["prev_hash"] != prev or _row_hash(prev, d) != d["hash"]:
            return {"ok": False, "rows": len(rows), "broken_at": d["id"], "at": d["at"]}
        prev = d["hash"]
    return {"ok": True, "rows": len(rows), "first": rows[0]["at"] if rows else None, "last": rows[-1]["at"] if rows else None}


def purge() -> int:
    """2년 지난 접속기록·끝난 세션 정리 (하루 한 번 db.purge_expired 에서)."""
    cut = (datetime.now() - timedelta(days=AUDIT_KEEP_DAYS)).isoformat(timespec="seconds")
    now = time.time()
    c = _conn()
    try:
        n = c.execute("DELETE FROM admin_audit WHERE at < ?", (cut,)).rowcount
        c.execute("DELETE FROM admin_sessions WHERE last_seen < ? OR created < ?", (now - IDLE_SEC, now - MAX_SEC))
        c.commit()
        return n
    finally:
        c.close()
