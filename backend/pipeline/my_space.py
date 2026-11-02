"""내 공간 — 한 방문자(로그인하면 계정)의 저장 값을 모아 요약하고, 질문하기에 넘길 '내 상황' 글을 만든다 (2026-11-02).

방문자 상태(api/routers/me.py visitor_state)에 있는 값만 쓴다:
profile(유형·지역·소득·전세 만기·청약 가점), re_watch(관심 단지·지역), apply_fav(관심 공고), profile.alert_apply(알림 공고),
note_bm(저장한 노트), calc_saves(저장한 계산), my_memo(메모).
관심 단지는 저장된 실거래(rtms_apt_trade)에서 최근 6개월을 바로 읽는다.
"""
from __future__ import annotations

from datetime import date
from statistics import median

from . import db, regions_kr

PYEONG = 3.305785


def _ym_back(n: int) -> str:
    t = date.today()
    y, m = t.year, t.month - n
    while m <= 0:
        y, m = y - 1, m + 12
    return f"{y}{m:02d}"


def watch_stats(watch: list[dict], limit: int = 20) -> list[dict]:
    """관심 단지(apt 가 있는 항목)마다 최근 6개월 거래 — 건수·마지막 거래·최근 3개월과 그 전 3개월 3.3㎡당 중위가."""
    out: list[dict] = []
    c = db.connect()
    try:
        for w in watch[:limit]:
            lawd, apt, dong = str(w.get("lawd") or ""), str(w.get("apt") or ""), str(w.get("dong") or "")
            name = regions_kr.NAMES.get(lawd, lawd)
            if not lawd:
                continue
            if not apt:  # 지역 관심 — 시군구 전체
                rows = c.execute("SELECT deal_ymd, deal_date, amount, area, name, floor FROM rtms_apt_trade WHERE lawd_cd=? AND deal_ymd>=? "
                                 "AND COALESCE(cancelled,0)=0 AND amount IS NOT NULL", (lawd, _ym_back(5))).fetchall()
            else:
                rows = c.execute("SELECT deal_ymd, deal_date, amount, area, name, floor FROM rtms_apt_trade WHERE lawd_cd=? AND name=? "
                                 "AND (?='' OR umd=?) AND deal_ymd>=? AND COALESCE(cancelled,0)=0 AND amount IS NOT NULL",
                                 (lawd, apt, dong, dong, _ym_back(5))).fetchall()
            cut = _ym_back(2)
            pp = lambda r: r["amount"] / r["area"] * PYEONG if r["area"] else None  # noqa: E731
            recent = [v for r in rows if r["deal_ymd"] >= cut and (v := pp(r))]
            before = [v for r in rows if r["deal_ymd"] < cut and (v := pp(r))]
            last = max(rows, key=lambda r: r["deal_date"] or "", default=None)
            rm, bm = (median(recent) if recent else None), (median(before) if before else None)
            out.append({
                "lawd": lawd, "region": name, "apt": apt, "dong": dong, "note": str(w.get("note") or "")[:200],
                "deals_6m": len(rows), "pp_recent": round(rm) if rm else None, "pp_before": round(bm) if bm else None,
                "change_pct": round((rm - bm) / bm * 100, 1) if rm and bm else None,
                "last": {"date": last["deal_date"], "amount": last["amount"], "area": last["area"], "floor": last["floor"],
                         "name": last["name"]} if last else None,
            })
    finally:
        c.close()
    return out


def notices(ids: list[str]) -> list[dict]:
    ids = [i for i in ids if isinstance(i, str)][:50]
    if not ids:
        return []
    c = db.connect()
    try:
        rows = c.execute(f"SELECT notice_id, name, region, house_type, category, receipt_start, receipt_end, winner_date, url "
                         f"FROM re_apply_notice WHERE notice_id IN ({','.join('?' * len(ids))})", ids).fetchall()
    except Exception:  # noqa: BLE001 - 표가 아직 없으면
        return []
    finally:
        c.close()
    order = {k: i for i, k in enumerate(ids)}
    return sorted((dict(r) for r in rows), key=lambda r: order.get(r["notice_id"], 999))


def saved_notes(ids: list) -> list[dict]:
    ids = [int(i) for i in ids if isinstance(i, int) or (isinstance(i, str) and i.isdigit())][:100]
    if not ids:
        return []
    c = db.connect()
    try:
        rows = c.execute(f"SELECT id, title, category, published, summary FROM notes WHERE status='published' AND id IN ({','.join('?' * len(ids))})",
                         ids).fetchall()
    finally:
        c.close()
    return [dict(r) for r in rows]


def summary(state: dict) -> dict:
    prof = state.get("profile") if isinstance(state.get("profile"), dict) else {}
    watch = state.get("re_watch") if isinstance(state.get("re_watch"), list) else []
    fav = state.get("apply_fav") if isinstance(state.get("apply_fav"), list) else []
    alerts = prof.get("alert_apply") if isinstance(prof.get("alert_apply"), list) else []
    return {
        "profile": prof,
        "watch": watch_stats([w for w in watch if isinstance(w, dict)]),
        "apply": notices(list(dict.fromkeys([*alerts, *fav]))),
        "apply_alert": alerts, "apply_fav": fav,
        "notes": saved_notes(state.get("note_bm") if isinstance(state.get("note_bm"), list) else []),
        "calcs": [x for x in (state.get("calc_saves") or []) if isinstance(x, dict)][:30],
        "memo": str(state.get("my_memo") or "")[:2000],
    }


def _man(v) -> str:
    if v is None:
        return "-"
    v = int(round(v))
    eok, rest = divmod(v, 10000)
    return f"{eok}억 {rest:,}만원" if eok and rest else f"{eok}억원" if eok else f"{rest:,}만원"


def context_text(state: dict) -> str:
    """질문하기에 넘길 '내 상황' — 사용자가 이 사이트에 저장한 것만, 짧게."""
    s = summary(state)
    lines: list[str] = []
    p = s["profile"]
    TYPES = {"first_home": "무주택(첫 집 마련)", "upgrade": "1주택 갈아타기", "tenant": "임차인(전월세)", "investor": "투자 관심"}
    if p:
        bits = []
        if p.get("type"):
            bits.append(f"유형 {TYPES.get(p['type'], p['type'])}")
        if p.get("regions"):
            bits.append("관심 지역 " + ", ".join(regions_kr.NAMES.get(r, r) for r in p["regions"][:5]))
        if p.get("income"):
            bits.append(f"연소득 약 {_man(p['income'])}")
        if p.get("lease_end"):
            bits.append(f"전세 만기 {p['lease_end']}")
        if p.get("sub_home") is not None and p.get("sub_fam") is not None and p.get("sub_acct") is not None:
            try:
                score = (0 if p["sub_home"] == 0 else 2 * p["sub_home"]) + (5 + 5 * p["sub_fam"]) + (p["sub_acct"] + 1)
                bits.append(f"청약 가점 약 {score}점")
            except TypeError:
                pass
        if bits:
            lines.append("- 프로필: " + " · ".join(bits))
    for w in s["watch"][:12]:
        nm = f"{w['region']} {w['dong']} {w['apt']}".strip() if w["apt"] else f"{w['region']} 전체"
        last = w["last"]
        t = f"- 관심 {'단지' if w['apt'] else '지역'} {nm}: 최근 6개월 거래 {w['deals_6m']}건"
        if w["pp_recent"]:
            t += f", 최근 3개월 3.3㎡당 중위 {_man(w['pp_recent'])}"
        if w["change_pct"] is not None:
            t += f"(그 전 3개월 대비 {w['change_pct']:+.1f}%)"
        if last:
            t += f", 마지막 거래 {last['date']} {_man(last['amount'])} {round(last['area'] or 0)}㎡"
        if w["note"]:
            t += f", 내 메모: {w['note'][:80]}"
        lines.append(t)
    for n in s["apply"][:10]:
        tag = "알림 켬" if n["notice_id"] in s["apply_alert"] else "관심"
        lines.append(f"- {tag} 청약 공고: {n['name']} ({n.get('region') or ''}) 접수 {n.get('receipt_start') or '-'}~{n.get('receipt_end') or '-'}, 발표 {n.get('winner_date') or '-'}")
    for n in s["notes"][:8]:
        lines.append(f"- 저장한 노트: {n['title']} ({n['published'][:10]})")
    for x in s["calcs"][:5]:
        lines.append(f"- 저장한 계산: {str(x.get('label') or '')[:40]} {str(x.get('summary') or '')[:120]}")
    if s["memo"]:
        lines.append(f"- 내 메모: {s['memo'][:300]}")
    if not lines:
        return ""
    return "[이 사용자가 집보미에 저장한 내 상황 — 답할 때 이 사람 기준으로 적용하되, 숫자는 아래 그대로만 인용]\n" + "\n".join(lines)
