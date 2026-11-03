"""뉴스레터 메일 발송 (SMTP). 접속 정보는 .env의 SMTP_* 값을 쓴다.

메일 본문의 참여 블록(오늘의 퀴즈·내일 예측·용어 맞히기·유형 테스트·연속 참여·지난 예측 결과):
- 메일은 JS 를 못 돌리니 모든 보기는 사이트로 가는 링크다. 링크는 전부 /m/{장치}?t=해지토큰&to=사이트경로&s=발송일 을 거쳐
  클릭을 세고 구독자↔브라우저를 이은 뒤 to 로 보낸다 (api/routers/mail_link.py). 링크를 연 것만으로는 답이 기록되지 않는다 —
  메일 보안 검사기가 링크를 미리 열어 보므로, 화면이 한 번 더 눌러 확정한다.
- 한 호의 수신자 전원이 같은 문제를 받는다 (random.Random(send_key)). 개인 블록(연속 참여·지난 예측·내 유형)은
  subscribers.visitor 가 이어진 구독자에게만, 아니면 누구에게나 같은 안내문.
- 공통 블록은 호마다 한 번만 만들고(prepare), 수신자마다는 토큰 치환과 개인 블록만 만든다(render). LLM 호출 없음.
"""
from __future__ import annotations

import hashlib
import os
import random
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, parseaddr
from html import escape
from urllib.parse import urlencode

from . import editorial, engage

DEVICES = ("quiz", "poll", "type", "streak", "term", "note", "flow")  # /m/{device} — api/routers/mail_link.py 와 같은 목록
_TOKEN_SLOT = "__TOKEN__"  # 공통 블록 속 링크의 토큰 자리 — 수신자마다 치환 (urlencode 가 '_' 를 그대로 두므로 안전)


def smtp_config() -> dict:
    return {
        "host": os.environ.get("SMTP_HOST", ""),
        "port": int(os.environ.get("SMTP_PORT", "587") or 587),
        "user": os.environ.get("SMTP_USER", ""),
        "password": os.environ.get("SMTP_PASS", ""),
        # SMTP_FROM 이 "집보미 <a@b.com>" 꼴이어도 주소만 쓴다 (표시 이름은 보낼 때 붙인다) — 봉투 발신자에 이름이 섞이면 거부하는 서버가 있다
        "sender": parseaddr(os.environ.get("SMTP_FROM", "") or os.environ.get("SMTP_USER", ""))[1],
        "tls": os.environ.get("SMTP_TLS", "starttls").lower(),  # starttls / ssl / none
    }


def is_configured() -> bool:
    cfg = smtp_config()
    return bool(cfg["host"] and cfg["sender"])


def _plain(html_text: str) -> str:
    """HTML 메일 → 글자 본문 (링크는 '글자 (주소)' 로)."""
    import html as _h
    import re as _re
    t = _re.sub(r"(?is)<(style|script)[^>]*>.*?</\1>", "", html_text)
    t = _re.sub(r'(?is)<a [^>]*href="([^"]+)"[^>]*>(.*?)</a>', lambda m: f"{_re.sub('<[^>]+>', '', m.group(2)).strip()} ({m.group(1)})", t)
    t = _re.sub(r"(?i)<br\s*/?>|</p>|</tr>|</h\d>|</div>|</li>", "\n", t)
    t = _h.unescape(_re.sub(r"<[^>]+>", "", t))
    return "\n".join(ln.strip() for ln in t.splitlines() if ln.strip())


def _sender_line() -> str:
    """뉴스레터 바닥 '보낸 곳' — 처리방침의 운영자·보호책임자 연락처 (정보통신망법: 전송자 명칭·연락처)."""
    from html import escape
    try:
        from . import privacy
        s = privacy.settings()
        name = s.get("officer_name") or s.get("operator") or ""
        mail = s.get("officer_email") or ""
        return escape(" · ".join(x for x in (name, mail) if x)) or "사이트 '문의하기'"
    except Exception:  # noqa: BLE001
        return "사이트 '문의하기'"


def site_url() -> str:
    return os.environ.get("SITE_URL", "http://localhost:5030").rstrip("/")


def mail_link(base: str, device: str, to: str, send_date: str, token: str = _TOKEN_SLOT) -> str:
    """메일 속 사이트 링크 — 전부 /m 을 거친다 (클릭 집계·구독자↔브라우저 연결). href 에 바로 넣을 수 있게 escape 한 값."""
    return escape(f"{base}/m/{device}?{urlencode({'t': token, 'to': to, 's': send_date})}")


# ───────────────────────── 블록 조각 (인라인 스타일 표 — 메일 클라이언트용) ─────────────────────────

def _box(label: str, title: str, body: str, sub: str = "") -> str:
    sub_html = f'<div style="font-size:12px;color:#B8AB8A;margin:2px 0 8px">{escape(sub)}</div>' if sub else '<div style="height:6px"></div>'
    return f"""
<tr><td style="padding:10px 32px 2px">
  <div style="border:1px solid #3A3220;border-radius:12px;padding:16px 18px;background:#1C180F">
    <div style="font:11px monospace;letter-spacing:2px;color:#FFD54A">{escape(label)}</div>
    <div style="margin:6px 0 0;font-size:15px;font-weight:700;line-height:1.5;color:#FBF6E9">{escape(title)}</div>
    {sub_html}{body}
  </div></td></tr>"""


def _pill(href: str, text: str) -> str:
    return (f'<a href="{href}" style="display:inline-block;margin:0 6px 8px 0;padding:8px 14px;border:1px solid #F5B800;'
            f'border-radius:999px;color:#FBF6E9;text-decoration:none;font-size:13px;line-height:1.4">{escape(text)}</a>')


def _button(href: str, text: str) -> str:
    return (f'<a href="{href}" style="display:inline-block;background:#F5B800;color:#1A1405;text-decoration:none;font-weight:700;'
            f'font-size:13px;padding:10px 18px;border-radius:999px">{escape(text)}</a>')


def _strip(text: str, href: str, link_text: str, color: str = "#FFD54A") -> str:
    """한 줄짜리 개인 띠 (연속 참여·지난 예측)."""
    return f"""
<tr><td style="padding:10px 32px 0">
  <div style="border-left:3px solid {color};background:#1C180F;border-radius:0 10px 10px 0;padding:10px 14px;font-size:13px;line-height:1.7;color:#FBF6E9">
    {text} <a href="{href}" style="color:{color};text-decoration:none;white-space:nowrap">{escape(link_text)}</a></div></td></tr>"""


def leader_block(issue: dict | None, notes: list[dict], base: str, send_date: str = "") -> str:
    """'이번 주 꼭 알아야 할 3가지' + 에디터 코멘트 (pipeline/editorial.py, 규칙 기반). 노트 링크는 note 장치를 거친다."""
    three = editorial.leader_three(notes, (issue or {}).get("picks", ""))
    if not three:
        return ""
    lz = editorial.lens()
    rows = "".join(f"""
  <tr><td style="padding:12px 0;border-top:1px solid #3A3220;vertical-align:top;width:34px">
    <div style="width:26px;height:26px;border-radius:50%;background:#F5B800;color:#1A1405;font:700 13px/26px sans-serif;text-align:center">{i}</div></td>
  <td style="padding:12px 0;border-top:1px solid #3A3220">
    <a href="{mail_link(base, 'note', f"/notes?id={t['id']}", send_date)}" style="text-decoration:none;font-size:15px;font-weight:700;line-height:1.5;color:#FFFFFF">{escape(t['point'])}</a>
    <div style="font-size:12px;color:#B8AB8A;margin-top:3px">{escape(t['title'][:70])}</div>
  </td></tr>""" for i, t in enumerate(three, 1))
    note = (issue or {}).get("editor_note", "").strip()
    note_html = f"""
<tr><td style="padding:6px 32px 4px">
  <div style="border-left:3px solid #FFD54A;background:#1C180F;border-radius:0 10px 10px 0;padding:12px 16px">
    <div style="font:11px monospace;letter-spacing:1.5px;color:#FFD54A">EDITOR'S NOTE</div>
    <div style="margin-top:6px;font-size:14px;line-height:1.75;color:#FBF6E9">{editorial.highlight(note, mail=True)}</div>
  </div></td></tr>""" if note else ""
    return f"""{note_html}
<tr><td style="padding:22px 32px 2px">
  <div style="font:12px monospace;letter-spacing:2px;color:#FFD54A">MUST KNOW 3</div>
  <h3 style="margin:6px 0 2px;font-size:17px;color:#FBF6E9">이번 주 꼭 알아야 할 3가지</h3>
  <div style="font-size:12px;color:#B8AB8A">{escape(lz.get('stance', ''))}</div>
  <table width="100%" cellpadding="0" cellspacing="0" style="margin-top:8px">{rows}</table>
</td></tr>"""


def _card(base: str, n: dict, send_date: str = "") -> str:
    return f"""
<tr><td style="padding:10px 32px">
  <a href="{mail_link(base, 'note', f"/notes?id={n['id']}", send_date)}" style="display:block;text-decoration:none;border:1px solid #3A3220;border-radius:12px;padding:16px 18px;background:#1C180F">
    <div style="font:11px monospace;color:#FFD54A">{escape(n['category'])} · {escape(n['kind'])}</div>
    <div style="margin:6px 0;font-size:15px;font-weight:700;line-height:1.5;color:#FBF6E9">{escape(n['title'])}</div>
    <div style="font-size:13px;line-height:1.7;color:#E8DEC6">{escape(n['summary'])}</div>
  </a>
</td></tr>"""


# ───────────────────────── 공통 블록 (호마다 한 번) ─────────────────────────

def _quiz_block(base: str, sd: str, rng: random.Random, day) -> str:
    """오늘의 퀴즈 3문항 중 하나 — 보기마다 /today?mq={문항}:{보기 번호} 로. 화면이 그 보기를 미리 고른 채 '답 확정'을 받는다."""
    quiz = engage.daily_quiz(day)
    if not quiz:
        return ""
    i = rng.randrange(len(quiz))
    q = quiz[i]
    pills = "".join(_pill(mail_link(base, "quiz", f"/today?mq={i}:{j}", sd), o) for j, o in enumerate(q["options"]))
    return _box("오늘의 퀴즈", q["q"], f"<div>{pills}</div>", q.get("sub", ""))


def _poll_block(base: str, sd: str, day) -> str:
    poll = engage.daily_poll(day)
    pills = "".join(_pill(mail_link(base, "poll", f"/today?mp={j}#poll", sd), o) for j, o in enumerate(poll["options"]))
    return _box("내일의 키워드 예측", poll["question"], f"<div>{pills}</div>", f"{poll['target_day']} 기사로 채점 · 맞히면 다음 호에 알려 드립니다")


def _term_block(base: str, sd: str, rng: random.Random, send_key: str) -> str:
    """용어 1개 맞히기 — 화면 /api/terms 와 같은 세트(glossary.quiz_set)의 0번 문항. 링크의 question_key 는 그 세트의 seed(8자리 hex)."""
    from app import glossary  # 순환 참조 피하기 (app → pipeline)
    track = rng.choice(sorted(glossary.TERMS))
    seed = hashlib.sha256(f"zgmail-term:{send_key}".encode()).hexdigest()[:8]
    q = glossary.quiz_set(track, seed)[0]
    pills = "".join(_pill(mail_link(base, "term", f"/terms?mt={track}:{seed}:{j}", sd), o) for j, o in enumerate(q["options"]))
    return _box("용어 1개 맞히기", q["q"], f"<div>{pills}</div>", f"{glossary.TRACKS[track][1]} · {q['prompt']}")


def prepare(issue: dict | None, notes: list[dict], pdf_url: str | None = None, preview: bool = False, send_key: str = "") -> dict:
    """한 호의 공통 재료 — 발송 전 한 번만 만든다. send_key 가 같으면 누가 받아도 같은 문제 (jobs.newsletter 의 send_key)."""
    from app import ax_types  # 순환 참조 피하기
    day = engage.today()
    sd = day.isoformat()
    send_key = send_key or sd
    rng = random.Random(f"zgmail:{send_key}")
    base = site_url()
    s = {"issue": issue, "notes": notes, "pdf_url": pdf_url, "preview": preview, "base": base, "send_date": sd, "send_key": send_key}
    s["quiz_html"] = _quiz_block(base, sd, rng, day)
    s["poll_html"] = _poll_block(base, sd, day)
    s["term_html"] = _term_block(base, sd, rng, send_key)
    s["leader_html"] = leader_block(issue, notes, base, sd)
    s["last_poll"] = engage.latest_poll_result()  # 없으면 '지난 예측' 블록 생략
    if s["last_poll"]:
        votes = s["last_poll"]["votes"]
        total = sum(votes.values())
        s["last_poll_pct"] = round(votes[s["last_poll"]["winner"]] / total * 100) if total else 0
    s["type_counts"] = engage.item_counts("type_test")  # '같은 유형 n명' — 수신자마다 세지 않게
    s["type_names"] = {k: f"{v[0]} {v[1]}" for k, v in ax_types.TYPES.items()}
    from . import db
    s["pub_notes"] = db.notes("published")[:300]  # 맞춤 블록 ②(내 유형에 영향 있는 노트) 채점용 — 호마다 한 번
    return s


# ───────────────────────── 맞춤 블록 (프로필·관심 단지가 있는 구독자, Phase 2) ─────────────────────────

def has_personal(prof: dict | None) -> bool:
    """프로필(유형·관심 지역) 또는 단지 단위 관심 목록이 있으면 맞춤 구성."""
    if not isinstance(prof, dict):
        return False
    return bool(prof.get("type") or prof.get("regions") or any((w or {}).get("apt") for w in prof.get("watch") or []))


def _man(v) -> str:
    if not v:
        return "-"
    n = int(round(v))
    eok, rest = divmod(abs(n), 10000)
    return (f"{eok}억 {rest:,}만원" if rest else f"{eok}억원") if eok else f"{rest:,}만원"


def _pct_html(v) -> str:
    if v is None:
        return '<span style="color:#B8AB8A">비교 거래 부족</span>'
    color = "#FF8A65" if v > 0 else "#7FD1A8" if v < 0 else "#E8DEC6"
    return f'<b style="color:{color}">{"+" if v > 0 else ""}{v:.1f}%</b>'


def _watch_block(s: dict, prof: dict) -> str:
    """① 내 관심 단지 이번 주 변동 — 최근 30일 계약 건수·최근가·직전 분기 대비 중위가 변동률 (저장된 실거래 표, 최대 5곳)."""
    from . import re_trend
    base, sd = s["base"], s["send_date"]
    items = [w for w in prof.get("watch") or [] if (w or {}).get("apt")][:5]
    if not items:
        return _box("① 내 관심 단지", "아직 담아 둔 단지가 없습니다",
                    _button(mail_link(base, "flow", "/deals", sd), "실거래가에서 ☆로 담기"),
                    "관심 단지를 담으면 다음 호부터 거래 건수·최근가·변동률을 여기서 알려 드립니다")
    rows, as_of = [], ""
    for w in items:
        try:
            x = re_trend.watch_week(w)
        except Exception:  # noqa: BLE001 - 한 단지 집계 실패가 메일 전체를 막지 않게
            x = None
        if not x:
            continue
        as_of = max(as_of, x["as_of"] or "")
        lt = x["last_trade"]
        last = (f'{_man(lt["amount"])} <span style="color:#B8AB8A">({escape(lt["date"][5:].replace("-", "."))} · '
                f'{lt["area"]:.0f}㎡)</span>') if lt else "거래 없음"
        jr = f' · 전세가율 {x["jeonse_ratio"]:.0f}%' if x.get("jeonse_ratio") else ""
        q = urlencode({"lawd": x["lawd"], "dong": x["dong"], "apt": x["apt"]})
        band = escape(" · " + x["main_band"]) if x["main_band"] else ""
        rows.append(f"""
  <tr><td style="padding:10px 0;border-top:1px solid #3A3220">
    <a href="{mail_link(base, 'flow', f'/my-homes?{q}', sd)}" style="text-decoration:none;font-size:14px;font-weight:700;color:#FBF6E9">{escape(x['apt'])}</a>
    <span style="font-size:12px;color:#B8AB8A"> {escape(x['region'])} {escape(x['dong'])}</span>
    <div style="font-size:13px;line-height:1.7;color:#E8DEC6">최근 30일 계약 <b>{x['count_30d']}건</b> · 최근가 {last}<br>
      직전 분기 대비 중위가 {_pct_html(x['change_pct'])}{band}{jr}</div>
  </td></tr>""")
    if not rows:
        return ""
    src = f"{re_trend.SOURCE}{' · ' + as_of + ' 계약분까지' if as_of else ''}"
    body = f'<table width="100%" cellpadding="0" cellspacing="0">{"".join(rows)}</table>'
    return _box("① 내 관심 단지 이번 주", f"관심 단지 {len(rows)}곳의 거래 흐름", body, src)


def _mine_block(s: dict, prof: dict) -> str:
    """② 내 유형·관심 지역에 영향 있는 노트 3편 — 홈 '나에게 영향 있는 3가지'와 같은 채점(profile.personal_three)."""
    from . import profile
    base, sd = s["base"], s["send_date"]
    if not (prof.get("type") or prof.get("regions")):
        return _box("② 내 조건에 맞는 노트", "유형과 관심 지역을 정하면 노트를 골라 드립니다",
                    _button(mail_link(base, "flow", "/me", sd), "내 프로필 정하기 (1분)"))
    res = profile.personal_three(s.get("pub_notes") or [], prof)
    if not res["items"]:
        return ""
    rows = "".join(f"""
  <tr><td style="padding:10px 0;border-top:1px solid #3A3220">
    <a href="{mail_link(base, 'note', f"/notes?id={x['note']['id']}", sd)}" style="text-decoration:none;font-size:14px;font-weight:700;line-height:1.5;color:#FBF6E9">{escape(x['note']['title'])}</a>
    <div style="font-size:12px;color:#FFD54A;margin-top:2px">{escape(x['reason'])}</div>
  </td></tr>""" for x in res["items"])
    who = " · ".join(filter(None, [profile.TYPES.get(prof.get("type") or "", ""),
                                   "·".join(profile.short_name(r) for r in prof.get("regions") or [])]))
    return _box("② 내 조건에 영향 있는 노트", "이번 주 나에게 영향 있는 3가지",
                f'<table width="100%" cellpadding="0" cellspacing="0">{rows}</table>', f"기준: {who}" if who else "")


def _flow_line(s: dict) -> str:
    """③ 전체 주간 흐름 한 줄."""
    issue = s["issue"]
    if not issue:
        return ""
    line = f"{issue.get('headline_em', '')} {issue.get('headline', '')}".strip()
    return _strip(f'<span style="color:#B8AB8A">③ 이번 주 전체 흐름 · {escape(issue.get("week", ""))}</span><br><b>{escape(line)}</b>',
                  mail_link(s["base"], "flow", "/", s["send_date"]), "전체 흐름 보기 →")


# ───────────────────────── 수신자별 ─────────────────────────

def _personal(s: dict, visitor: str) -> tuple[str, str, str]:
    """(지난 예측 결과, 연속 참여 띠, 유형 테스트 블록). visitor 가 없으면 누구에게나 같은 안내 문구."""
    base, sd = s["base"], s["send_date"]
    today_link = mail_link(base, "streak", "/today", sd)
    type_link = mail_link(base, "type", "/type", sd)
    # 지난 예측
    lp = s["last_poll"]
    result = ""
    if lp:
        x = escape(lp["winner"])
        my = next((r["value"] for r in engage.mine("poll", visitor, lp["day"]) if r["item"] == lp["day"]), None) if visitor else None
        if my:
            hit = my == lp["winner"]
            text = (f"지난 예측: 당신은 <b style=\"color:{'#FFD54A' if hit else '#FF8A65'}\">{'맞혔습니다' if hit else '틀렸습니다'}</b> "
                    f"(정답 <b>{x}</b>, 참여자 {s['last_poll_pct']}%가 맞힘)")
        else:
            text = f"지난 예측 정답은 <b>{x}</b> · 이번엔 참여해 보세요"
        result = _strip(text, today_link, "오늘의 예측 →", "#FF8A65" if my and my != lp["winner"] else "#FFD54A")
    # 연속 참여
    n = engage.streak(visitor) if visitor else 0
    streak = (_strip(f"🔥 <b>{n}일 연속</b> 참여 중", today_link, "오늘도 이어가기 →") if n
              else _strip("이번 주 참여하면 연속 기록이 시작됩니다", today_link, "오늘의 퀴즈 풀기 →"))
    # 유형 테스트
    mine = engage.mine("type_test", visitor) if visitor else []
    code = mine[-1]["item"] if mine else ""
    if code in s["type_names"]:
        body = (f'<div style="font-size:14px;color:#FBF6E9">내 유형 <b>{escape(s["type_names"][code])}</b> · 같은 유형 {s["type_counts"].get(code, 0)}명 '
                f'<a href="{type_link}" style="color:#FFD54A;text-decoration:none">자세히 →</a></div>')
        type_html = _box("나의 부동산 성향", "지난번 결과를 다시 볼까요?", body)
    else:
        type_html = _box("부동산 성향 테스트", "12문항으로 보는 나의 부동산 성향", _button(type_link, "1분 · 16가지 중 내 유형은?"))
    return result, streak, type_html


def render(s: dict, unsubscribe_token: str = "", industries: list[str] | None = None, refer_key: str = "", visitor: str = "",
           prof: dict | None = None) -> str:
    """prepare() 재료로 수신자 한 명의 본문. preview=True: 사이트 안 미리보기 — 링크를 새 탭으로 연다(미리보기 틀 안에서 사이트가 열리지 않게).
    industries: 구독자가 고른 지역 — 그 지역 노트를 'OO 소식'으로 먼저 싣고, 나머지 새 노트는 3편까지만.
    prof: 구독자 사본(profile.for_subscriber — 프로필 + watch). 맞춤 정보가 있으면 ③전체 흐름 한 줄 + ①관심 단지 + ②내 조건 노트 구성,
    없으면 기존 구성 그대로."""
    from . import industry
    issue, notes, base, sd = s["issue"], s["notes"], s["base"], s["send_date"]
    token = unsubscribe_token or ""
    issue_html = ""
    if issue:
        issue_html = f"""
<tr><td style="padding:22px 32px 8px">
  <div style="font:12px monospace;letter-spacing:2px;color:#FFD54A">THIS WEEK · {escape(issue['week'])} · {escape(issue['range'])}</div>
  <h2 style="margin:10px 0 12px;font-size:20px;line-height:1.5;color:#FBF6E9">
    <span style="color:#FFD54A">{escape(issue['headline_em'])}</span> {escape(issue['headline'])}</h2>
  <p style="margin:0;font-size:14px;line-height:1.8;color:#E8DEC6">{editorial.highlight(issue['body'], mail=True)}</p>
</td></tr>"""
    result_html, streak_html, type_html = _personal(s, visitor or "")
    shared = s["quiz_html"] + s["poll_html"] + s["term_html"]
    head = lambda t: f'<tr><td style="padding:24px 32px 4px;font:12px monospace;letter-spacing:2px;color:#B8AB8A">{escape(t)}</td></tr>'  # noqa: E731
    mine = industry.filter_notes(notes, industries) if industries else []
    if mine:
        rest = [n for n in notes if n not in mine][:3]
        cards = (head(f"{' · '.join(industries)} 소식") + "".join(_card(base, n, sd) for n in mine)
                 + (head("그 밖의 새 노트") + "".join(_card(base, n, sd) for n in rest) if rest else ""))
    else:
        cards = head("NEW NOTES") + "".join(_card(base, n, sd) for n in notes)
    cards = s["leader_html"] + cards
    if has_personal(prof):
        # 맞춤 구성: 주간 흐름 본문·새 노트 카드 대신 맨 위에 ① 관심 단지 ② 내 조건 노트 ③ 전체 흐름 한 줄 (월요일 아침 3분 분량)
        issue_html = _watch_block(s, prof) + _mine_block(s, prof) + _flow_line(s)
        cards = ""
        type_html = ""
    unsub = f"{base}/unsubscribe?token={token}" if token else f"{base}/"
    # 내 추천 링크: 본인만 받는 메일에만 (주소에 해지 토큰이 들어가므로 미리보기·공개 화면에는 견본 주소)
    refer_url = f"{base}/refer?k={refer_key}" if refer_key else f"{base}/letter"
    refer = f"""
<tr><td style="padding:18px 32px 0">
  <div style="border:1px dashed #F5B800;border-radius:12px;padding:14px 18px;font-size:13px;line-height:1.7;color:#E8DEC6">
    <b style="color:#FBF6E9">친구 3명을 초대하면 지난 호 주간 PDF 전체가 열립니다.</b><br>
    <a href="{refer_url}" style="color:#FFD54A">내 추천 링크 받기 · 추천 현황 보기 →</a></div></td></tr>"""
    pdf_link = f'<a href="{s["pdf_url"]}" style="color:#FFD54A">주간 리포트 PDF</a> · ' if s["pdf_url"] else ""
    head_tag = '<head><base target="_blank"></head>' if s["preview"] else ""
    # 모든 /m 링크의 토큰 자리를 이 수신자의 해지 토큰으로 (미리보기·테스트 발송은 빈 토큰 — /m 은 그래도 to 로 보낸다)
    return f"""<!doctype html><html>{head_tag}<body style="margin:0;background:#120F08;font-family:'Malgun Gothic',sans-serif">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#120F08"><tr><td align="center">
<table width="640" cellpadding="0" cellspacing="0" style="max-width:640px;width:100%">
<tr><td style="padding:28px 32px;background:linear-gradient(120deg,#1C180F,#3A3220);border-bottom:3px solid #F5B800;border-radius:0 0 18px 18px">
  <div style="font-size:22px;font-weight:800;color:#FBF6E9">ZIP<span style="color:#FFD54A">BOMI</span> <span style="font-size:13px;font-weight:600;color:#B8AB8A">집보미</span></div>
  <div style="font-size:12px;color:#FFE89A;margin-top:4px">집에 관한 모든 것 — 시세·청약·대출·세금·정책</div>
</td></tr>
{result_html}
{streak_html}
{issue_html}
{shared}
{type_html}
{cards}
{refer}
<tr><td style="padding:24px 32px 36px;font-size:12px;color:#B8AB8A;line-height:1.7">
  <a href="{mail_link(base, 'flow', '/', sd, token)}" style="color:#FFD54A">사이트에서 보기</a> · {pdf_link}
  <a href="{unsub}" style="color:#B8AB8A">구독 해지</a><br>
  노트는 생성형 AI가 원문을 읽고 쓴 초안을 운영자가 검토해 정리한 것입니다. 투자·세무 자문이 아니며, 수치·일정은 원문과 공고로 꼭 확인하세요.<br>
  보낸 곳: 집보미 (운영자 {_sender_line()}) · 이 메일은 구독을 신청하신 분께만 보냅니다.<br>© 집보미
</td></tr>
</table></td></tr></table></body></html>""".replace(_TOKEN_SLOT, token)


def build_html(issue: dict | None, notes: list[dict], unsubscribe_token: str = "",
               pdf_url: str | None = None, preview: bool = False, industries: list[str] | None = None,
               refer_key: str = "", send_key: str = "", visitor: str = "", prof: dict | None = None) -> str:
    """한 사람분을 한 번에 (미리보기·테스트 발송). 여러 명에게 보낼 때는 prepare() 한 번 + render() 수신자별 (jobs.newsletter)."""
    return render(prepare(issue, notes, pdf_url, preview, send_key), unsubscribe_token, industries, refer_key, visitor, prof)


def confirm_html(confirm_token: str) -> str:
    base = site_url()
    return f"""<!doctype html><html><body style="margin:0;background:#120F08;font-family:'Malgun Gothic',sans-serif;color:#FBF6E9">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#120F08" style="background:#120F08"><tr><td>
<div style="max-width:560px;margin:0 auto;padding:36px 28px;background:#120F08;color:#FBF6E9">
  <div style="font-size:22px;font-weight:800">ZIP<span style="color:#FFD54A">BOMI</span> <span style="font-size:13px;font-weight:600;color:#B8AB8A">집보미</span></div>
  <h2 style="font-size:19px;margin:22px 0 10px">구독 신청을 확인해 주세요</h2>
  <p style="color:#E8DEC6;line-height:1.7;font-size:14px">아래 버튼을 누르면 구독이 완료됩니다. 직접 신청하지 않았다면 이 메일을 무시하세요 — 아무것도 발송되지 않습니다.</p>
  <p style="margin:26px 0"><a href="{base}/confirm?t={confirm_token}" style="background:#F5B800;color:#1A1405;text-decoration:none;font-weight:700;padding:12px 22px;border-radius:999px">구독 확인하기</a></p>
  <p style="color:#B8AB8A;font-size:12px">확인하지 않은 신청은 7일 뒤 자동으로 지워집니다.</p>
</div></td></tr></table></body></html>"""


def _shell(title: str, body: str) -> str:
    return f"""<!doctype html><html><body style="margin:0;background:#120F08;font-family:'Malgun Gothic',sans-serif;color:#FBF6E9">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#120F08" style="background:#120F08"><tr><td>
<div style="max-width:560px;margin:0 auto;padding:36px 28px;background:#120F08;color:#FBF6E9">
  <div style="font-size:22px;font-weight:800">ZIP<span style="color:#FFD54A">BOMI</span> <span style="font-size:13px;font-weight:600;color:#B8AB8A">집보미</span></div>
  <h2 style="font-size:19px;margin:22px 0 10px">{title}</h2>
  {body}
</div></td></tr></table></body></html>"""


def login_html(token: str, code: str) -> str:
    """메일 링크 로그인 (api/routers/auth.py) — 30분, 한 번만. 요청한 화면에 코드를 넣거나, 링크를 누른다(다른 기기면 코드도 필요)."""
    base = site_url()
    return _shell("집보미에 로그인합니다", f"""
  <p style="color:#E8DEC6;line-height:1.7;font-size:14px">아래 버튼을 누르면 이 메일 주소로 로그인됩니다. 직접 요청하지 않았다면 이 메일을 무시하세요 — 링크와 코드가 함께 없으면 로그인되지 않습니다.</p>
  <p style="margin:26px 0"><a href="{base}/login?t={token}" style="background:#F5B800;color:#1A1405;text-decoration:none;font-weight:700;padding:12px 22px;border-radius:999px">로그인하기</a></p>
  <p style="color:#E8DEC6;font-size:14px">또는 로그인을 요청한 화면에 아래 확인 코드를 넣어도 됩니다. 요청한 기기가 아닌 곳에서 버튼을 눌렀을 때도 이 코드를 넣어 주세요.</p>
  <p style="font-size:28px;font-weight:800;letter-spacing:8px;color:#FFD54A;margin:6px 0 18px">{code}</p>
  <p style="color:#B8AB8A;font-size:12px">링크와 코드는 30분 동안, 한 번만 쓸 수 있습니다. 코드를 5번 틀리면 링크가 무효가 됩니다. 이 메일을 다른 사람에게 전달하지 마세요.</p>""")


def send_login_link(email: str, token: str, code: str) -> bool:
    if not is_configured():
        return False
    ok, _ = send([(email, "")], f"[집보미] 로그인 링크 (확인 코드 {code})", lambda _t: login_html(token, code))
    return ok == 1


def send_login_notice(email: str, revoke_token: str, ua: str = "") -> bool:
    """로그인 알림 — 본인이 아니면 '모든 기기에서 로그아웃'."""
    if not is_configured():
        return False
    from datetime import datetime as _dt
    from html import escape as _esc
    base = site_url()
    body = f"""
  <p style="color:#E8DEC6;line-height:1.7;font-size:14px">{_dt.now().strftime('%Y-%m-%d %H:%M')}에 이 메일 주소로 집보미에 로그인했습니다.<br>
  <span style="color:#B8AB8A;font-size:12px">브라우저: {_esc(ua) or '-'}</span></p>
  <p style="color:#E8DEC6;font-size:14px">본인이 맞다면 아무것도 하지 않아도 됩니다. 본인이 아니라면 아래 버튼으로 모든 기기에서 로그아웃하세요.</p>
  <p style="margin:22px 0"><a href="{base}/login?revoke={revoke_token}" style="background:#2A2416;color:#FFD54A;border:1px solid #FFD54A;text-decoration:none;font-weight:700;padding:11px 20px;border-radius:999px">내가 아니에요 — 모든 기기에서 로그아웃</a></p>"""
    ok, _ = send([(email, "")], "[집보미] 새 로그인 알림", lambda _t: _shell("새 로그인 알림", body))
    return ok == 1


def ask_link_html(link_token: str) -> str:
    """'질문하기 연결' 메일 — 구독한 주소로 이 브라우저를 잇는 링크 (api/routers/ask.py link). 링크를 연 것만으로 잇지 않고 화면의 버튼으로 확정."""
    base = site_url()
    return f"""<!doctype html><html><body style="margin:0;background:#120F08;font-family:'Malgun Gothic',sans-serif;color:#FBF6E9">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#120F08" style="background:#120F08"><tr><td>
<div style="max-width:560px;margin:0 auto;padding:36px 28px;background:#120F08;color:#FBF6E9">
  <div style="font-size:22px;font-weight:800">ZIP<span style="color:#FFD54A">BOMI</span> <span style="font-size:13px;font-weight:600;color:#B8AB8A">집보미</span></div>
  <h2 style="font-size:19px;margin:22px 0 10px">질문하기를 이 구독자로 연결합니다</h2>
  <p style="color:#E8DEC6;line-height:1.7;font-size:14px">아래 버튼을 누르면 지금 쓰는 브라우저가 이 구독 주소와 이어져 남은 질문 횟수를 쓸 수 있습니다. 직접 요청하지 않았다면 이 메일을 무시하세요.</p>
  <p style="margin:26px 0"><a href="{base}/ask?link={link_token}" style="background:#F5B800;color:#1A1405;text-decoration:none;font-weight:700;padding:12px 22px;border-radius:999px">질문하기 연결하기</a></p>
  <p style="color:#B8AB8A;font-size:12px">링크는 1시간 동안, 한 번만 쓸 수 있습니다.</p>
</div></td></tr></table></body></html>"""


def ask_credits_html(n: int) -> str:
    """관리자가 질문 횟수를 충전했을 때 구독자에게 보내는 짧은 안내."""
    base = site_url()
    return f"""<!doctype html><html><body style="margin:0;background:#120F08;font-family:'Malgun Gothic',sans-serif;color:#FBF6E9">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#120F08" style="background:#120F08"><tr><td>
<div style="max-width:560px;margin:0 auto;padding:36px 28px;background:#120F08;color:#FBF6E9">
  <div style="font-size:22px;font-weight:800">ZIP<span style="color:#FFD54A">BOMI</span> <span style="font-size:13px;font-weight:600;color:#B8AB8A">집보미</span></div>
  <h2 style="font-size:19px;margin:22px 0 10px">질문 {int(n)}회가 충전되었습니다</h2>
  <p style="color:#E8DEC6;line-height:1.7;font-size:14px">연결해 둔 브라우저에서 바로 이어서 질문할 수 있습니다. 다른 브라우저라면 질문하기 화면에서 구독한 주소로 다시 연결해 주세요.</p>
  <p style="margin:26px 0"><a href="{base}/ask" style="background:#F5B800;color:#1A1405;text-decoration:none;font-weight:700;padding:12px 22px;border-radius:999px">질문하기 열기</a></p>
</div></td></tr></table></body></html>"""


def send_confirmation(email: str, confirm_token: str) -> bool:
    """구독 확인 메일. SMTP가 없으면 False (관리 > 구독·발송에서 나중에 다시 보낼 수 있다)."""
    if not is_configured():
        return False
    ok, _ = send([(email, "")], "[집보미] 구독 신청을 확인해 주세요", lambda _t: confirm_html(confirm_token))
    return ok == 1


def send(recipients: list[tuple[str, str]], subject: str, html_for, on_sent=None, claim=None,
         release=None) -> tuple[int, list[str]]:
    """recipients: (email, unsubscribe_token) 목록. html_for(token) -> 본문.
    (성공 건수, 실패 주소 목록)을 반환한다. 연결은 한 번 열어 재사용한다.
    claim(email) -> bool: 보내기 직전 '이 사람은 내가 보낸다'를 DB에 먼저 잡는다 — 서버 두 개가 같은 호를 동시에 보내도
    한 사람이 두 번 받지 않게. False 면 건너뛴다. 보내다 실패하면 release(email)로 풀어 다음 실행에서 다시 보낸다."""
    cfg = smtp_config()
    if not is_configured():
        raise RuntimeError("SMTP 설정이 없습니다 (.env의 SMTP_HOST / SMTP_FROM)")
    smtp_cls = smtplib.SMTP_SSL if cfg["tls"] == "ssl" else smtplib.SMTP
    ok, failed = 0, []
    with smtp_cls(cfg["host"], cfg["port"], timeout=30) as server:
        if cfg["tls"] == "starttls":
            server.starttls()
        if cfg["user"]:
            server.login(cfg["user"], cfg["password"])
        for email, token in recipients:
            if claim and not claim(email):
                continue  # 다른 실행이 이미 보냈거나 보내는 중
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = formataddr(("집보미", cfg["sender"]))
            msg["To"] = email
            body = html_for(token)
            # 2026-11-03: 글자만 보는 메일 앱용 본문 + 구독 메일은 메일 앱의 '수신 거부' 단추(RFC 8058 원클릭)를 쓸 수 있게
            if token:
                msg["List-Unsubscribe"] = f"<{site_url()}/api/unsubscribe/one-click?token={token}>"
                msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
            msg.attach(MIMEText(_plain(body), "plain", "utf-8"))
            msg.attach(MIMEText(body, "html", "utf-8"))
            try:
                server.sendmail(cfg["sender"], [email], msg.as_string())
                ok += 1
                if on_sent:
                    on_sent(email)  # 수신자별 기록 — 중간에 끊겨 다시 보낼 때 이미 받은 사람은 건너뛴다
            except smtplib.SMTPServerDisconnected:
                if release:
                    release(email)
                failed.extend(e for e, _ in recipients[recipients.index((email, token)):])
                break  # 연결이 끊기면 나머지는 실패로 두고 다음 실행에서 이어 보낸다
            except (smtplib.SMTPException, OSError):
                if release:
                    release(email)
                failed.append(email)
    return ok, failed
