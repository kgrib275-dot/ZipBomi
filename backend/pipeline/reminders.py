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
from datetime import date, datetime, timedelta

from pipeline import accounts, db, mailer, profile, pubdata, webpush

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
                + f'<p style="font-size:13px"><a href="{base}/calendar" style="color:#FFD54A">청약 일정 전체 보기 →</a> · '
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
    digests = plan_digests(today, dry_run=dry_run)
    out = {"planned": len(items) + len(digests), "sent": 0, "skipped": 0, "failed": 0, "kinds": {}}
    if dry_run or not (items or digests):
        out["items"] = [{k: v for k, v in i.items() if k not in ("token", "notice")} | {"email": i["email"][:3] + "…"} for i in items]
        out["items"] += [{"kind": d["kind"], "count": len(d["rows"]), "email": d["email"][:3] + "…"} for d in digests]
        return out
    mail_ok = mailer.is_configured()
    if not mail_ok:
        out["error"] = "SMTP 설정이 없어 메일은 보내지 못했습니다 (웹 푸시만 보냄)"
    for d in digests:
        _send_digest(d, out, mail_ok)
    for it in items if mail_ok else []:
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



# ───────────────────────── 내 일정·관심 단지 새 거래 (2026-11-17) ─────────────────────────
# 로그인 계정만 — 일정·관심 단지는 계정의 visitor_state('c:'+raw)에 있다. 내 공간에서 직접 켠 사람만(profile.alert_my·alert_watch).
# 한 사람에게 하루 한 통씩 묶어 보낸다(Gmail 하루 한도). 항목마다 reminder_log 에 먼저 잡아 같은 것은 다시 보내지 않는다.

MY_DAYS = 1           # 내 일정·알림·할 일: 하루 전 아침(놓쳤으면 당일)
MAX_MY_ROWS = 30
WATCH_MONTHS = 3      # 관심 단지 새 거래: 계약월이 최근 3개월 안인 거래만 본다 (신고는 계약 뒤 30일 안)
MAX_WATCH_ITEMS = 20  # 단지 수
MAX_WATCH_ROWS = 30   # 한 통에 싣는 거래 수


def _account_states() -> list[tuple[str, dict]]:
    """(계정 이메일, 계정 저장값) — 내 일정 또는 관심 단지 메일을 켠 계정만."""
    import json
    c = db.connect()
    try:
        try:
            rows = c.execute("SELECT a.email, v.data FROM accounts a JOIN visitor_state v ON v.visitor = 'c:' || a.raw").fetchall()
        except sqlite3.Error as e:
            log.warning("계정 저장값 조회 실패(내 일정·관심 단지 알림 건너뜀): %s", e)
            return []
    finally:
        c.close()
    out = []
    for r in rows:
        try:
            st = json.loads(r[1]) or {}
        except (ValueError, TypeError):
            continue
        prof = st.get("profile") if isinstance(st, dict) else None
        if isinstance(prof, dict) and (prof.get("alert_my") or prof.get("alert_watch") or prof.get("alert_week") or prof.get("alert_newapply")):
            out.append((r[0], st))
    return out


def my_rows(st: dict, today: date, days: int = MY_DAYS) -> list[dict]:
    """오늘~days 일 뒤의 내 일정(my_events)·항목 알림(my_items)·할 일 마감(my_todos). ref 에 날짜를 넣어 날짜를 바꾸면 다시 알린다."""
    out: list[dict] = []

    def add(ref: str, title, when, note) -> None:
        d = _d(when)
        if not d:
            return
        left = (d - today).days
        if 0 <= left <= days:
            out.append({"ref": f"{ref}:{d.isoformat()}", "date": d.isoformat(), "left": left, "title": str(title)[:80], "note": str(note or "")[:120]})

    for ev in st.get("my_events") or [] if isinstance(st.get("my_events"), list) else []:
        if isinstance(ev, dict) and ev.get("date"):
            add("ev:" + str(ev.get("id") or ""), ev.get("title") or "내 일정", ev["date"], "")
    for key, v in (st.get("my_items") or {}).items() if isinstance(st.get("my_items"), dict) else []:
        if isinstance(v, dict) and v.get("remind"):
            add("it:" + str(key)[:60], v.get("title") or "내 알림", v["remind"], v.get("remind_note") or "")
    for td in st.get("my_todos") or [] if isinstance(st.get("my_todos"), list) else []:
        if isinstance(td, dict) and td.get("due") and not td.get("done"):
            add("td:" + str(td.get("id") or ""), "할 일 · " + str(td.get("text") or ""), td["due"], "마감")
    out.sort(key=lambda x: x["date"])
    return out[:MAX_MY_ROWS]


def _ym_back(today: date, n: int) -> str:
    y, m = today.year, today.month - n
    while m <= 0:
        y, m = y - 1, m + 12
    return f"{y}{m:02d}"


def _h(s: str) -> str:
    import hashlib
    return hashlib.sha1(s.encode()).hexdigest()[:20]


def cond_ok(w: dict, d: dict) -> bool:
    """관심 단지에 평형(㎡±3)·상한가(만원) 조건이 있으면 맞는 거래만 (2026-11-19). 조건이 없으면 모두."""
    area, mx = w.get("cond_area"), w.get("cond_max")
    if isinstance(mx, (int, float)) and mx and (d.get("amount") is None or d["amount"] > mx):
        return False
    if isinstance(area, (int, float)) and area and (d.get("area") is None or abs(float(d["area"]) - float(area)) > 3):
        return False
    return True


def watch_deals(watch: list, today: date) -> list[tuple[str, dict, list[dict]]]:
    """관심 '단지'(apt 가 있는 항목)마다 (단지 키, 관심 항목, 최근 거래들). 거래 키는 계약일·층·면적·금액 —
    표를 다시 받을 때 바뀌는 uid·fetched_at 대신 거래 자체로 같은지 본다."""
    items = [w for w in watch if isinstance(w, dict) and w.get("apt") and w.get("lawd")][:MAX_WATCH_ITEMS]
    if not items:
        return []
    out = []
    c = db.connect()
    try:
        for w in items:
            lawd, apt, dong = str(w["lawd"]), str(w["apt"]), str(w.get("dong") or "")
            try:
                rows = c.execute("SELECT deal_date, floor, area, amount, umd FROM rtms_apt_trade WHERE lawd_cd=? AND name=? AND (?='' OR umd=?) "
                                 "AND deal_ymd>=? AND COALESCE(cancelled,0)=0 AND amount IS NOT NULL ORDER BY deal_date DESC LIMIT 200",
                                 (lawd, apt, dong, dong, _ym_back(today, WATCH_MONTHS - 1))).fetchall()
            except sqlite3.Error as e:
                log.warning("관심 단지 거래 조회 실패: %s", e)
                return out
            wkey = f"{lawd}|{dong}|{apt}"
            deals = [{"key": _h(f"{wkey}|{r['deal_date']}|{r['floor']}|{r['area']}|{r['amount']}"), "date": r["deal_date"] or "",
                      "floor": r["floor"], "area": r["area"], "amount": r["amount"], "dong": r["umd"] or dong} for r in rows]
            out.append((wkey, w, deals))
    finally:
        c.close()
    return out


def _seen(email: str, kind: str, refs: list[str]) -> set[str]:
    if not refs:
        return set()
    c = _conn()
    try:
        got: set[str] = set()
        for i in range(0, len(refs), 500):
            part = refs[i:i + 500]
            got |= {r[0] for r in c.execute(f"SELECT ref FROM reminder_log WHERE email=? AND kind=? AND ref IN ({','.join('?' * len(part))})",
                                             (email, kind, *part))}
        return got
    finally:
        c.close()


def _mark(email: str, kind: str, refs: list[tuple[str, str]]) -> None:
    """보내지 않고 '본 것'으로만 기록 (관심 단지를 처음 켰을 때 지난 거래를 한꺼번에 보내지 않게)."""
    c = _conn()
    try:
        with c:
            now = datetime.now().isoformat(timespec="seconds")
            c.executemany("INSERT OR IGNORE INTO reminder_log (email, kind, ref, due, sent_at) VALUES (?,?,?,?,?)",
                          [(email, kind, ref, due, now) for ref, due in refs])
    finally:
        c.close()


NEWAPPLY_MAX_ROWS = 10
NEWAPPLY_FIRST_ROWS = 8


def newapply_candidates(prof: dict, today: date) -> list[dict]:
    """내 관심 지역(시도)의 최근 2주 공고 중 알림 종류(분양·무순위·재공급)에 맞는 것 — 최신 공고순 (2026-11-20).
    open = 아직 접수가 안 끝났거나 곧 시작하는 공고. 처음 켠 날은 open 인 것만 한 번 보내고 나머지는 '본 것'으로만 남긴다."""
    kinds = set(prof.get("alert_newapply") or [])
    sidos = {profile._SIDO_OF.get(str(c)) for c in (prof.get("regions") or [])} - {None}
    if not kinds or not sidos:
        return []
    since = (today - timedelta(days=14)).isoformat()
    c = db.connect()
    try:
        rows = c.execute(f"SELECT notice_id, name, region, house_type, category, receipt_start, receipt_end, notice_date FROM re_apply_notice "
                         f"WHERE region IN ({','.join('?' * len(sidos))}) AND COALESCE(notice_date, receipt_start, '') >= ? ORDER BY notice_date DESC LIMIT 200",
                         (*sorted(sidos), since)).fetchall()
    except sqlite3.Error as e:
        log.warning("새 공고 조회 실패: %s", e)
        return []
    finally:
        c.close()
    out = []
    for r in rows:
        n = dict(r)
        sup = pubdata.supply_kind(n)
        if not ((sup == "" and "sale" in kinds) or (sup == "lottery" and "lottery" in kinds) or (sup == "resale" and ({"resale", "lottery"} & kinds))):
            continue
        end = _d(n.get("receipt_end")) or _d(n.get("receipt_start"))
        out.append({"ref": n["notice_id"], "nid": n["notice_id"], "name": n["name"] or "청약 공고", "region": n.get("region") or "", "supply": sup,
                    "start": (n.get("receipt_start") or "")[:10], "end": (n.get("receipt_end") or "")[:10], "date": (n.get("notice_date") or "")[:10] or today.isoformat(),
                    "open": bool(end and end >= today)})
    return out


def week_rows(watch: list, today: date) -> list[dict]:
    """관심 단지·지역의 지난 7일 vs 그 전 7일 매매 거래 건수와 3.3㎡당 중위가 (계약일 기준 — 신고가 늦어 최근 며칠은 덜 잡힐 수 있다). 거래가 한 건도 없으면 뺀다."""
    items = [w for w in watch if isinstance(w, dict) and w.get("lawd")][:MAX_WATCH_ITEMS]
    if not items:
        return []
    c = db.connect()
    out: list[dict] = []
    try:
        lo = (today - timedelta(days=14)).isoformat()
        mid = (today - timedelta(days=7)).isoformat()
        for w in items:
            lawd, apt, dong = str(w["lawd"]), str(w.get("apt") or ""), str(w.get("dong") or "")
            try:
                rows = c.execute("SELECT deal_date, area, amount FROM rtms_apt_trade WHERE lawd_cd=? AND (?='' OR name=?) AND (?='' OR ?='' OR umd=?) "
                                 "AND deal_ymd>=? AND deal_date>? AND deal_date<=? AND COALESCE(cancelled,0)=0 AND amount>0 AND area>0",
                                 (lawd, apt, apt, apt, dong, dong, _ym_back(today, 1), lo, today.isoformat())).fetchall()
            except sqlite3.Error as e:
                log.warning("주간 요약 조회 실패: %s", e)
                return out
            cur = [r for r in rows if r["deal_date"] > mid]
            prev = [r for r in rows if r["deal_date"] <= mid]
            if not rows:
                continue
            med = lambda v: round(sorted(x["amount"] / x["area"] * 3.3 for x in v)[len(v) // 2]) if v else None  # noqa: E731
            out.append({"ref": f"wk:{today.isocalendar()[0]}-{today.isocalendar()[1]:02d}:{lawd}|{dong}|{apt}", "date": today.isoformat(), "apt": apt or str(w.get("region") or lawd),
                        "region": str(w.get("region") or ""), "n": len(cur), "prev_n": len(prev), "pp": med(cur), "prev_pp": med(prev)})
    finally:
        c.close()
    return out


def plan_digests(today: date | None = None, dry_run: bool = False) -> list[dict]:
    """계정마다 하루 한 통 — kind 'my'(내 일정 하루 전), 'watch'(관심 단지 새 거래). 이미 보낸 항목은 뺀다.
    처음 보는 관심 단지(기준선 표시가 없으면)는 지금 거래를 '본 것'으로만 남기고 보내지 않는다 (dry_run 이면 기록도 하지 않음)."""
    today = today or date.today()
    out: list[dict] = []
    for email, st in _account_states():
        prof = st.get("profile") or {}
        if prof.get("alert_my"):
            rows = my_rows(st, today)
            done = _seen(email, "my", [r["ref"] for r in rows])
            rows = [r for r in rows if r["ref"] not in done]
            if rows:
                out.append({"email": email, "kind": "my", "rows": rows})
        if prof.get("alert_newapply") and prof.get("regions"):
            cands = newapply_candidates(prof, today)
            base = "base:newapply"
            if cands and base not in _seen(email, "newapply", [base]):
                if not dry_run:
                    _mark(email, "newapply", [(c["ref"], c["date"]) for c in cands if not c["open"]] + [(base, today.isoformat())])
                cands = [c for c in cands if c["open"]][:NEWAPPLY_FIRST_ROWS]
            done = _seen(email, "newapply", [c["ref"] for c in cands])
            rows = [c for c in cands if c["ref"] not in done][:NEWAPPLY_MAX_ROWS]
            if rows:
                out.append({"email": email, "kind": "newapply", "rows": rows})
        if prof.get("alert_week") and today.weekday() == 0:  # 월요일 아침 — 지난 한 주 요약
            rows = week_rows(st.get("re_watch") or [], today)
            done = _seen(email, "week", [r["ref"] for r in rows])
            rows = [r for r in rows if r["ref"] not in done]
            if rows:
                out.append({"email": email, "kind": "week", "rows": rows})
        if prof.get("alert_watch"):
            fresh: list[dict] = []
            for wkey, w, deals in watch_deals(st.get("re_watch") or [], today):
                base = "base:" + _h(wkey)
                if base not in _seen(email, "watch", [base]):
                    if not dry_run:
                        _mark(email, "watch", [(d["key"], d["date"]) for d in deals] + [(base, today.isoformat())])
                    continue
                done = _seen(email, "watch", [d["key"] for d in deals])
                for d in deals:
                    if d["key"] not in done and cond_ok(w, d):
                        fresh.append({**d, "ref": d["key"], "apt": str(w["apt"]), "region": str(w.get("region") or "")})
            if fresh:
                fresh.sort(key=lambda x: x["date"], reverse=True)
                out.append({"email": email, "kind": "watch", "rows": fresh[:MAX_WATCH_ROWS]})
    return out


def _man(v) -> str:
    if v is None:
        return "-"
    eok, rest = divmod(int(v), 10000)
    return f"{eok}억 {rest:,}만" if eok and rest else f"{eok}억" if eok else f"{rest:,}만"


_TD = 'style="padding:6px 12px 6px 0;border-bottom:1px solid #2A2414;vertical-align:top"'
_SUB = 'style="color:#B8AB8A"'


def render_digest(d: dict) -> tuple[str, str]:
    base = mailer.site_url()
    esc = html.escape
    if d["kind"] == "my":
        rows = "".join(
            f'<tr><td {_TD}><b>{"오늘" if r["left"] == 0 else "내일"}</b><br><span {_SUB}>{r["date"][5:].replace("-", ".")}</span></td>'
            f'<td {_TD}>{esc(r["title"])}' + (f'<br><span {_SUB}>{esc(r["note"])}</span>' if r["note"] else "") + "</td></tr>"
            for r in d["rows"])
        body = (f'<p style="color:#E8DEC6;line-height:1.7;font-size:14px">내 공간 달력에 넣어 둔 일정 {len(d["rows"])}건이 다가왔어요.</p>'
                f'<table style="font-size:14px;border-collapse:collapse;width:100%">{rows}</table>'
                + _btn(f"{base}/my", "내 일정 달력 열기"))
        first = d["rows"][0]
        subj = f"[집보미] {'오늘' if first['left'] == 0 else '내일'} 일정 — {first['title'][:30]}" + (f" 외 {len(d['rows']) - 1}건" if len(d["rows"]) > 1 else "")
        return subj, _wrap_acc("다가오는 내 일정", body, "내 공간 달력의 '하루 전 메일 알림'")
    if d["kind"] == "newapply":
        tagof = {"resale": "🔁 재공급", "lottery": "무순위·잔여"}
        rows = "".join(
            f'<tr><td {_TD}><a href="{base}/c/{esc(r["nid"])}" style="color:#FFD54A"><b>{esc(r["name"])}</b></a><br><span {_SUB}>{esc(r["region"])}'
            + (f' · {tagof[r["supply"]]}' if r["supply"] else "") + f'</span></td><td {_TD}>접수<br><span {_SUB}>{esc(r["start"][5:] or "-")}'
            + (f' ~ {esc(r["end"][5:])}' if r["end"] and r["end"] != r["start"] else "") + "</span></td></tr>" for r in d["rows"])
        body = (f'<p style="color:#E8DEC6;line-height:1.7;font-size:14px">내 관심 지역에 새로 올라온 청약 공고 {len(d["rows"])}건이에요. 청약홈·LH 공개 자료 기준이니 자격과 일정은 공고문에서 꼭 확인하세요.</p>'
                f'<table style="font-size:14px;border-collapse:collapse;width:100%">{rows}</table>' + _btn(f"{base}/calendar", "청약 일정 달력 열기"))
        first = d["rows"][0]
        subj = f"[집보미] 내 지역 새 청약 공고 {len(d['rows'])}건 — {first['name'][:28]}" + (f" 외 {len(d['rows']) - 1}건" if len(d["rows"]) > 1 else "")
        return subj, _wrap_acc("내 지역 새 청약 공고", body, "청약 달력의 '내 지역 새 공고 알림'")
    if d["kind"] == "week":
        def _pp(r):
            return f"{r['pp']:,}만원" if r["pp"] else "-"

        def _chg(r):
            if r["pp"] and r["prev_pp"]:
                x = (r["pp"] - r["prev_pp"]) / r["prev_pp"] * 100
                return f"{x:+.1f}%"
            return "-"
        rows = "".join(
            f'<tr><td {_TD}><b>{esc(r["apt"])}</b><br><span {_SUB}>{esc(r["region"])}</span></td>'
            f'<td {_TD}>거래 {r["n"]}건<br><span {_SUB}>지난주 {r["prev_n"]}건</span></td>'
            f'<td {_TD} align="right">{_pp(r)}<br><span {_SUB}>3.3㎡당 · {_chg(r)}</span></td></tr>' for r in d["rows"])
        body = (f'<p style="color:#E8DEC6;line-height:1.7;font-size:14px">관심 단지·지역의 지난 7일 매매 거래를 그 전 7일과 비교했어요. 계약일 기준이고 신고가 늦어 최근 며칠은 덜 잡힐 수 있어요.</p>'
                f'<table style="font-size:14px;border-collapse:collapse;width:100%">{rows}</table>' + _btn(f"{base}/my-homes", "관심 단지 열기"))
        return f"[집보미] 이번 주 관심 단지·지역 거래 요약 {len(d['rows'])}곳", _wrap_acc("주간 거래 요약", body, "관심 단지 화면의 '주간 요약'")
    rows = "".join(
        f'<tr><td {_TD}><b>{esc(r["apt"])}</b><br><span {_SUB}>{esc(r["region"])} {esc(r["dong"] or "")}</span></td>'
        f'<td {_TD}>{esc(r["date"])}<br><span {_SUB}>{round(r["area"] or 0)}㎡ · {r["floor"] if r["floor"] is not None else "-"}층</span></td>'
        f'<td {_TD} align="right"><b>{_man(r["amount"])}원</b></td></tr>' for r in d["rows"])
    body = (f'<p style="color:#E8DEC6;line-height:1.7;font-size:14px">관심 단지에 새로 올라온 매매 실거래 {len(d["rows"])}건이 있어요. '
            f'국토교통부 실거래가 공개 자료 기준이고, 계약 뒤 30일 안에 신고돼 계약일이 며칠 전일 수 있어요.</p>'
            f'<table style="font-size:14px;border-collapse:collapse;width:100%">{rows}</table>'
            + _btn(f"{base}/my-homes", "관심 단지 열기"))
    names = list(dict.fromkeys(r["apt"] for r in d["rows"]))
    subj = f"[집보미] 관심 단지 새 실거래 {len(d['rows'])}건 — {names[0][:24]}" + (f" 외 {len(names) - 1}곳" if len(names) > 1 else "")
    return subj, _wrap_acc("관심 단지 새 실거래", body, "관심 단지 화면의 '새 거래 메일 알림'")


def _wrap_acc(title: str, body: str, where: str) -> str:
    """계정 알림용 — 구독 해지 링크 대신 끄는 곳을 적는다."""
    base = mailer.site_url()
    old = f'내 프로필에서 알림을 켜 두셔서 보내 드렸어요. 알림은 <a href="{base}/me" style="color:#B8AB8A">내 프로필</a>에서 끌 수 있어요.'
    return _wrap(title, body, "").replace(old, f"직접 켠 알림이라 로그인한 계정 메일로 보내 드렸어요. {html.escape(where)}에서 끌 수 있어요.")


def push_text(d: dict) -> tuple[str, str, str]:
    """웹 푸시용 제목·한 줄·열 주소."""
    rows = d["rows"]
    if d["kind"] == "my":
        first = rows[0]
        when = "오늘" if first["left"] == 0 else "내일"
        return f"{when} 일정 {len(rows)}건", first["title"][:60] + (f" 외 {len(rows) - 1}건" if len(rows) > 1 else ""), "/my"
    if d["kind"] == "newapply":
        return f"내 지역 새 청약 공고 {len(rows)}건", rows[0]["name"][:40] + (f" 외 {len(rows) - 1}건" if len(rows) > 1 else ""), f"/c/{rows[0]['nid']}"
    if d["kind"] == "week":
        return f"이번 주 거래 요약 {len(rows)}곳", " · ".join(f"{r['apt'][:14]} {r['n']}건" for r in rows[:3]), "/my-homes"
    names = list(dict.fromkeys(r["apt"] for r in rows))
    return f"관심 단지 새 실거래 {len(rows)}건", names[0][:40] + (f" 외 {len(names) - 1}곳" if len(names) > 1 else ""), "/my-homes"


def _push_digest(d: dict) -> int:
    """계정에 등록된 기기(웹 푸시)로도 보낸다 — 기기를 등록한 것이 동의. 실패해도 메일에는 영향 없음."""
    try:
        acc = accounts.by_email(d["email"])
        if not acc:
            return 0
        title, body, url = push_text(d)
        return webpush.send_account(acc["id"], title, body, url, "zipbomi-" + d["kind"])
    except Exception:  # noqa: BLE001
        log.exception("웹 푸시 실패")
        return 0


def _send_digest(d: dict, out: dict, mail_ok: bool = True) -> None:
    claimed = [r for r in d["rows"] if _claim(d["email"], d["kind"], r["ref"], r.get("date") or "")]
    if not claimed:
        out["skipped"] += 1
        return
    subject, body = render_digest({**d, "rows": claimed})
    pushed = _push_digest({**d, "rows": claimed})
    ok = 0
    if mail_ok:
        try:
            ok, _failed = mailer.send([(d["email"], "")], subject, lambda _t, b=body: b)
        except Exception:  # noqa: BLE001 - 한 사람 실패가 나머지를 막지 않게
            log.exception("내 일정·관심 단지 알림 메일 실패")
            ok = 0
    ok = ok or pushed
    if ok:
        out["sent"] += 1
        out["kinds"][d["kind"]] = out["kinds"].get(d["kind"], 0) + 1
    else:
        for r in claimed:
            _release(d["email"], d["kind"], r["ref"])
        out["failed"] += 1
