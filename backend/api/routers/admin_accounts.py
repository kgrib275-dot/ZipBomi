"""관리 > 회원 계정 (2026-11-02) — 메일 링크 로그인 계정(pipeline/accounts.py) 목록·저장 현황·강제 로그아웃·삭제.

- 로그인 토큰·쿠키 원값(raw)은 내려보내지 않는다 (계정 id 로만 다룬다).
- 삭제는 계정과 그 방문자 상태·참여 기록을 함께 지운다 (사용자의 '내 기록 지우기'와 같은 범위).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request

from api.deps import require_admin
from api.routers.admin_jobs import log_action
from pipeline import accounts, db, engage

router = APIRouter(prefix="/admin", tags=["admin-accounts"], dependencies=[Depends(require_admin)])


def _counts(data: str | None) -> dict:
    try:
        s = json.loads(data or "{}")
    except ValueError:
        s = {}
    p = s.get("profile") if isinstance(s.get("profile"), dict) else {}
    ln = lambda v: len(v) if isinstance(v, (list, dict)) else 0  # noqa: E731
    return {"watch": ln(s.get("re_watch")), "apply_fav": ln(s.get("apply_fav")), "alerts": ln(p.get("alert_apply")),
            "notes": ln(s.get("note_bm")), "calcs": ln(s.get("calc_saves")), "items": ln(s.get("my_items")), "events": ln(s.get("my_events")),
            "profile": bool(p.get("type") or p.get("regions")), "memo": bool(s.get("my_memo"))}


@router.get("/accounts")
def list_accounts(q: str = "") -> dict:
    accounts.count()  # 표 준비
    c = db.connect()
    try:
        rows = c.execute("SELECT a.id, a.email, a.created_at, a.last_login_at, v.data, v.updated_at, "
                         "(SELECT 1 FROM subscribers s WHERE s.email = a.email AND s.active = 1 AND s.confirmed_at IS NOT NULL) AS subscribed "
                         "FROM accounts a LEFT JOIN visitor_state v ON v.visitor = 'c:' || a.raw ORDER BY a.last_login_at DESC").fetchall()
        since = (datetime.now() - timedelta(days=1)).isoformat(timespec="seconds")
        mails = c.execute("SELECT COUNT(*) FROM access_logs WHERE action='login_mail' AND created_at >= ?", (since,)).fetchone()[0]
    finally:
        c.close()
    ql = q.strip().lower()
    out = [{"id": r["id"], "email": r["email"], "created_at": r["created_at"], "last_login_at": r["last_login_at"],
            "last_seen": r["updated_at"], "subscribed": bool(r["subscribed"]), **_counts(r["data"])}
           for r in rows if not ql or ql in r["email"].lower()]
    week = (datetime.now() - timedelta(days=7)).isoformat(timespec="seconds")
    return {"rows": out, "total": len(rows), "active_7d": sum(1 for r in rows if (r["last_login_at"] or "") >= week),
            "login_mails_24h": mails}


def _acc(acc_id: int) -> dict:
    c = db.connect()
    try:
        r = c.execute("SELECT id, email, raw, created_at, last_login_at FROM accounts WHERE id=?", (acc_id,)).fetchone()
    finally:
        c.close()
    if not r:
        raise HTTPException(404, "없는 계정입니다.")
    return dict(r)


@router.post("/accounts/{acc_id}/logout")
def force_logout(acc_id: int, request: Request) -> dict:
    """모든 기기에서 로그아웃 — 저장 자료는 그대로, 다시 로그인하면 이어진다."""
    a = _acc(acc_id)
    accounts.rotate(a)
    log_action(request, "계정 강제 로그아웃", f"id={acc_id}")
    return {"ok": True}


@router.delete("/accounts/{acc_id}")
def delete_account(acc_id: int, request: Request) -> dict:
    a = _acc(acc_id)
    n = engage.erase_visitor("c:" + a["raw"])
    accounts.delete_by_raw(a["raw"])
    log_action(request, "계정 삭제", f"id={acc_id}")
    return {"ok": True, "erased": n}
