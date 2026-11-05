"""알림 메일 (Phase 4, 2026-11-02) — 청약 접수 D-3, 전세 만기 D-90·D-30.

- 대상: 확인을 마친 활성 구독자 중 내 프로필에서 알림을 직접 켠 사람만 (subscriber_profile 사본을 읽는다).
  · alert_apply: 알림 받기를 누른 청약 공고 id 목록 → 접수 시작 3일 전(시작일이 없는 LH 공고는 마감 3일 전)
  · alert_lease + lease_end: 전세 만기 90일·30일 전 (임차인 유형일 때만 프로필에 lease_end 가 남는다)
- 같은 알림은 한 번만: reminder_log(email, kind, ref) 를 보내기 직전에 먼저 잡고, 실패하면 풀어 다음 실행에서 다시.
- 놓친 날 보정: 서버가 꺼져 있던 날이 있어도 기한(0일 이상 남음) 안이면 다음 실행에서 보낸다.
LLM 없음. 메일 본문에는 공고 이름·날짜·링크와 해지 링크만 넣는다.
"""
from __future__ import annotations

import html
import logging
import sqlite3
from datetime import date, datetime

from pipeline import db, mailer, profile

log = logging.getLogger("zipgenie.reminders")

APPLY_DAYS = 3
LEASE_DAYS = (90, 30)
MAX_APPLY_ALERTS = 20

_SQL = ("CREATE TABLE IF NOT EXISTS reminder_log (email TEXT NOT NULL, kind TEXT NOT NULL, ref TEXT NOT NULL, "
        "due TEXT, sent_at TEXT NOT NULL, PRIMARY KEY (email, kind, ref))")


def _conn():
    c = db.connect()
    c.execute(_SQL)
    return c


def _claim(email: str, kind: str, ref: str, due: str) -> bool:
    c = _conn()
    try:
        with c:
            return c.execute("INSERT OR IGNORE INTO reminder_log (email, kind, ref, due, sent_at) VALUES (?,?,?,?,?)",
                             (email, kind, ref, due, datetime.now().isoformat(timespec="seconds"))).rowcount > 0
    finally:
        c.close()


def _release(email: str, kind: str, ref: str) -> None:
    c = _conn()
    try:
        with c:
            c.execute("DELETE FROM reminder_log WHERE email=? AND kind=? AND ref=?", (email, kind, ref))
    finally:
        c.close()


def forget(email: str) -> None:
    """구독 해지·삭제 때 발송 기록도 지운다."""
    c = _conn()
    try:
        with c:
            c.execute("DELETE FROM reminder_log WHERE email=?", (email,))
    finally:
        c.close()


def _d(s) -> date | None:
    try:
        return date.fromisoformat(str(s)[:10]) if s else None
    except ValueError:
        return None


def apply_target(n: dict) -> tuple[date | None, str]:
    """(알림 기준일, '접수 시작'·'접수 마감')."""
    st = _d(n.get("receipt_start"))
    if st:
        return st, "접수 시작"
    return _d(n.get("receipt_end")), "접수 마감"


def _notices(ids: list[str]) -> dict[str, dict]:
    if not ids:
        return {}
    c = db.connect()
    try:
        rows = c.execute(f"SELECT notice_id, name, region, house_type, category, receipt_start, receipt_end, winner_date, url "
                         f"FROM re_apply_notice WHERE notice_id IN ({','.join('?' * len(ids))})", ids).fetchall()
        return {r["notice_id"]: dict(r) for r in rows}
    except sqlite3.Error as e:  # 표가 아직 없거나 DB 가 잠긴 경우 — 알림은 건너뛰되 흔적은 남긴다
        log.warning("청약 공고 조회 실패(알림 건너뜀): %s", e)
        return {}
    finally:
        c.close()


def _account_profiles() -> list[tuple[str, dict]]:
    """(계정 이메일, 계정에 저장된 내 프로필) — 알림을 하나라도 켠 계정만."""
    import json
    c = db.connect()
    try:
        try:
            rows = c.execute("SELECT a.email, v.data FROM accounts a JOIN visitor_state v ON v.visitor = 'c:' || a.raw").fetchall()
        except sqlite3.Error as e:  # 표가 아직 없거나 DB 가 잠긴 경우 — 계정 알림은 건너뛰되 흔적은 남긴다
            log.warning("계정 프로필 조회 실패(계정 알림 건너뜀): %s", e)
            return []
    finally:
        c.close()
    out = []
    for r in rows:
        try:
            prof = (json.loads(r[1]) or {}).get("profile") or {}
        except (ValueError, TypeError):
            continue
        if isinstance(prof, dict) and (prof.get("alert_apply") or prof.get("alert_lease")):
            out.append((r[0], prof))
    return out


def plan(today: date | None = None) -> list[dict]:
    """오늘 보낼 알림 목록 (보낸 기록은 아직 보지 않는다)."""
    today = today or date.today()
    out: list[dict] = []
    subs = {s["email"]: s for s in db.subscribers(active_only=True)}
    # 로그인 계정도 받는다 (2026-11-03) — 예전엔 🔔·전세 만기 알림을 켜도 뉴스레터 구독자가 아니면 메일이 가지 않았다.
    # 이용자가 직접 켠 알림이라 계정 메일로 보내고, 끄는 곳(내 프로필·🔔)을 메일 아래에 적는다. 구독 해지 링크는 없다(구독이 아니므로).
    people: list[tuple[str, str, dict]] = [(email, s["token"], profile.for_subscriber(email) or {}) for email, s in subs.items()]
    seen = {e.lower() for e in subs}
    for email, prof in _account_profiles():
        if email.lower() not in seen:
            people.append((email, "", prof))
    for email, token, prof in people:
        s = {"token": token}
        ids = [i for i in (prof.get("alert_apply") or []) if isinstance(i, str)][:MAX_APPLY_ALERTS]
        for nid, n in _notices(ids).items():
            due, what = apply_target(n)
            if not due:
                continue
            left = (due - today).days
            if 0 <= left <= APPLY_DAYS:
                out.append({"email": email, "token": s["token"], "kind": "apply", "ref": f"{nid}:{due.isoformat()}",
                            "due": due.isoformat(), "left": left, "what": what, "notice": n})
        lease = _d(prof.get("lease_end"))
        if prof.get("alert_lease") and lease:
            left = (lease - today).days
            # 가장 가까운 단계 하나만 (90일 알림을 놓치고 25일 남았으면 30일 알림만)
            step = next((d for d in sorted(LEASE_DAYS) if 0 <= left <= d), None)
            if step is not None:
                out.append({"email": email, "token": s["token"], "kind": f"lease{step}", "ref": lease.isoformat(),
                            "due": lease.isoformat(), "left": left, "step": step})
    return out


def _wrap(title: str, body: str, unsub_token: str) -> str:
    base = mailer.site_url()
    unsub = f'<a href="{base}/unsubscribe?token={html.escape(unsub_token)}" style="color:#B8AB8A">구독 해지</a>' if unsub_token else ""
    return f"""<!doctype html><html><body style="margin:0;background:#120F08;font-family:'Malgun Gothic',sans-serif;color:#FBF6E9">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#120F08" style="background:#120F08"><tr><td>
<div style="max-width:560px;margin:0 auto;padding:36px 28px;background:#120F08;color:#FBF6E9">
  <div style="font-size:22px;font-weight:800">ZIP<span style="color:#FFD54A">BOMI</span> <span style="font-size:13px;font-weight:600;color:#B8AB8A">집보미</span></div>
  <h2 style="font-size:19px;margin:22px 0 10px">{title}</h2>
  {body}
  <p style="color:#B8AB8A;font-size:12px;line-height:1.6;margin-top:28px">내 프로필에서 알림을 켜 두셔서 보내 드렸어요. 알림은 <a href="{base}/me" style="color:#B8AB8A">내 프로필</a>에서 끌 수 있어요. {unsub}</p>
</div></td></tr></table></body></html>"""


def _btn(href: str, text: str) -> str:
    return (f'<p style="margin:22px 0"><a href="{html.escape(href)}" style="background:#F5B800;color:#1A1405;text-decoration:none;'
            f'font-weight:700;padding:12px 22px;border-radius:999px">{html.escape(text)}</a></p>')


def render(item: dict) -> tuple[str, str]:
    """(제목, 본문)."""
    base = mailer.site_url()
    left = item["left"]
    dday = "오늘" if left == 0 else f"D-{left}"
    if item["kind"] == "apply":
        n = item["notice"]
        name = html.escape(n.get("name") or "청약 공고")
        when = "오늘" if left == 0 else f"{left}일 뒤({item['due']})"
        rows = [("지역", n.get("region")), ("공급 유형", n.get("category") or n.get("house_type")),
                ("접수 시작", n.get("receipt_start")), ("접수 마감", n.get("receipt_end")), ("당첨자 발표", n.get("winner_date"))]
        table = "".join(f'<tr><td style="color:#B8AB8A;padding:4px 12px 4px 0">{k}</td><td>{html.escape(str(v))}</td></tr>'
                        for k, v in rows if v)
        body = (f'<p style="color:#E8DEC6;line-height:1.7;font-size:14px"><b>{name}</b> {item["what"]}이 '
                f'{when}예요. 청약홈·LH 공고문에서 자격과 준비 서류를 다시 확인하세요.</p>'
                f'<table style="font-size:14px;border-collapse:collapse">{table}</table>'
                + (_btn(n["url"], "공고 원문 보기") if str(n.get("url") or "").startswith("http") else "")
                + f'<p style="font-size:13px"><a href="{base}/calendar" style="color:#FFD54A">분양 일정 전체 보기 →</a> · '
                  f'<a href="{base}/calc" style="color:#FFD54A">내 청약 가점 계산 →</a></p>')
        return f"[집보미] {dday} 청약 {item['what']} — {n.get('name', '')[:40]}", _wrap(f"{dday} · 청약 {item['what']} 알림", body, item["token"])
    step = item["step"]
    tips = ("집주인에게 계약 갱신 여부를 알릴 수 있는 기간이에요(만기 6개월~2개월 전). 계약갱신요구권 사용 여부와 새 집 시세를 함께 보세요."
            if step == 90 else
            "만기가 한 달 남았어요. 이사한다면 보증금 반환 일정·전입신고·확정일자를, 연장한다면 계약서와 보증보험 갱신을 확인하세요.")
    body = (f'<p style="color:#E8DEC6;line-height:1.7;font-size:14px">내 프로필에 적어 둔 전세 만기일은 <b>{item["due"]}</b>로, '
            f'{left}일 남았어요.</p><p style="color:#E8DEC6;line-height:1.7;font-size:14px">{tips}</p>'
            + _btn(f"{base}/deals", "우리 동네 전월세 실거래가 보기")
            + f'<p style="font-size:13px"><a href="{base}/calc" style="color:#FFD54A">전세가율·갭 계산 →</a></p>')
    return f"[집보미] 전세 만기 {dday} 알림", _wrap(f"전세 만기 {dday}", body, item["token"])


def run(today: date | None = None, dry_run: bool = False) -> dict:
    items = plan(today)
    out = {"planned": len(items), "sent": 0, "skipped": 0, "failed": 0, "kinds": {}}
    if dry_run or not items:
        out["items"] = [{k: v for k, v in i.items() if k not in ("token", "notice")} | {"email": i["email"][:3] + "…"} for i in items]
        return out
    if not mailer.is_configured():
        out["error"] = "SMTP 설정이 없어 보내지 못했습니다"
        return out
    for it in items:
        if not _claim(it["email"], it["kind"], it["ref"], it["due"]):
            out["skipped"] += 1  # 이미 보냄
            continue
        subject, body = render(it)
        try:
            ok, failed = mailer.send([(it["email"], it["token"])], subject, lambda _t, b=body: b)
        except Exception:  # noqa: BLE001 - 한 사람 실패가 나머지를 막지 않게
            log.exception("알림 메일 실패")
            ok, failed = 0, [it["email"]]
        if ok:
            out["sent"] += 1
            out["kinds"][it["kind"]] = out["kinds"].get(it["kind"], 0) + 1
        else:
            _release(it["email"], it["kind"], it["ref"])
            out["failed"] += 1
    log.info("알림 메일: 대상 %d · 보냄 %d · 이미 보냄 %d · 실패 %d", out["planned"], out["sent"], out["skipped"], out["failed"])
    return out


def status_for(email: str) -> list[dict]:
    c = _conn()
    try:
        return [dict(r) for r in c.execute("SELECT kind, ref, due, sent_at FROM reminder_log WHERE email=? ORDER BY sent_at DESC "
                                           "LIMIT 20", (email,))]
    finally:
        c.close()


def summary() -> dict:
    """관리 화면용 — 알림을 켠 구독자 수와 최근 발송 수 (이메일은 내보내지 않는다)."""
    n_apply = n_lease = 0
    for s in db.subscribers(active_only=True):
        p = profile.for_subscriber(s["email"]) or {}
        n_apply += bool(p.get("alert_apply"))
        n_lease += bool(p.get("alert_lease") and p.get("lease_end"))
    c = _conn()
    try:
        recent = c.execute("SELECT kind, COUNT(*) n FROM reminder_log WHERE sent_at >= date('now','-30 day') GROUP BY kind").fetchall()
    finally:
        c.close()
    return {"apply_subscribers": n_apply, "lease_subscribers": n_lease, "sent_30d": {r["kind"]: r["n"] for r in recent},
            "plan_today": len(plan())}

