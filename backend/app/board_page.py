"""함께 보기 공개 페이지 /g/<토큰> (2026-11-20) — 읽기 전용, 로그인 불필요, 검색에 잡히지 않음(noindex).

주인이 고른 관심 단지·관심 공고만 보여 준다(pipeline/board.snapshot). 주인이 누구인지·일정·메모·예산 등은 나오지 않는다.
받은 사람이 바로 쓸 수 있게 단지는 '관심 단지로 담기', 공고는 공고 페이지(/c)와 '내 가점 비교'로 잇는다.
"""
from __future__ import annotations

from html import escape
from urllib.parse import quote

from starlette.requests import Request
from starlette.responses import HTMLResponse, Response
from starlette.routing import Route

from pipeline import board
from pipeline.pubdata import man

_CSS = ("<style>table{border-collapse:collapse;width:100%;margin:8px 0 18px;font-size:15px}td,th{padding:7px 10px;border-bottom:1px solid #3A3220;text-align:left}"
        "th{color:#B8AB8A;font-weight:600}.box{border:1px solid #3A3220;border-left:3px solid #F5B800;border-radius:10px;padding:10px 14px;margin:14px 0;background:#1C180F}"
        ".small{font-size:13px;color:#B8AB8A}.ctas{display:flex;flex-wrap:wrap;gap:10px;margin:20px 0}.ctas a{padding:10px 18px;border-radius:999px;border:1px solid #F5B800;text-decoration:none}"
        ".ctas a.p{background:#F5B800;color:#1A1405;font-weight:700}</style>")


def board_view(request: Request) -> Response:
    from api.routers import me as me_state
    from app import web
    token = request.path_params["token"]
    b = board.lookup(token)
    if not b:
        return HTMLResponse("<meta charset='utf-8'><meta name='robots' content='noindex'><h1>이 링크는 만료됐거나 멈췄어요</h1><p>링크를 보내 준 분께 새 링크를 부탁해 보세요. "
                            "<a href='/'>집보미 홈</a></p>", status_code=404, headers={"Cache-Control": "no-store"})
    snap = board.snapshot(me_state.load_state(b["visitor"]), b["include"])
    site = web._site(request)
    apts = ""
    if snap["apts"]:
        rows = ""
        for a in snap["apts"]:
            i = a["info"]
            last = (f"{escape(man(i['bands'][0]['median']))} <span class='small'>(전용 {i['bands'][0]['area']}㎡ 중위 · 최근 6개월 {i['n']}건)</span>" if i else "<span class='small'>최근 6개월 거래 없음</span>")
            link = f"/my-homes?lawd={a['lawd']}&dong={quote(a['dong'])}&apt={quote(a['apt'])}"
            page = f"/a/{a['lawd']}/{quote(a['apt'])}" + (f"?d={quote(a['dong'])}" if a["dong"] else "")
            rows += (f"<tr><td><b>{escape(a['apt'])}</b><br><span class='small'>{escape(a['region'])} {escape(a['dong'])}</span></td><td>{last}</td>"
                     f"<td><a href='{escape(page)}'>거래 보기</a><br><a href='{escape(link)}'>내 관심에 담기</a></td></tr>")
        apts = f"<h2>관심 단지 {len(snap['apts'])}곳</h2><table><tr><th>단지</th><th>최근 거래</th><th></th></tr>{rows}</table>"
    notices = ""
    if snap["notices"]:
        rows = ""
        for n in snap["notices"]:
            sch = dict(n["schedule"])
            when = sch.get("접수") or sch.get("1순위 접수") or sch.get("특별공급 접수") or "-"
            tag = {"resale": " 🔁 재공급", "lottery": " 무순위·잔여"}.get(n["supply"], "")
            rows += (f"<tr><td><a href='/c/{escape(n['notice_id'])}'><b>{escape(n.get('name') or '')}</b></a><br><span class='small'>{escape(n.get('region') or '')}{tag}</span></td>"
                     f"<td>접수 {escape(when)}<br><span class='small'>발표 {escape(sch.get('당첨자 발표') or '-')}</span></td></tr>")
        notices = f"<h2>관심 청약 공고 {len(snap['notices'])}건</h2><table><tr><th>공고</th><th>일정</th></tr>{rows}</table>"
    empty = "" if (apts or notices) else "<div class='box'>아직 보여 줄 관심 단지·공고가 없어요.</div>"
    body = ("<div class='meta'>함께 보기 · 읽기 전용</div><h1>함께 보는 관심 보드</h1>"
            "<p class='sum'>링크를 보낸 분이 고른 관심 단지와 청약 공고예요. 일정·메모 같은 개인 정보는 보이지 않아요.</p>"
            f"{apts}{notices}{empty}<div class='ctas'><a class='p' href='/'>나도 관심 단지·공고 모아 보기</a><a href='/calc?tab=sub&s=1'>내 가점 계산하기</a></div>"
            "<p class='small'>거래는 국토교통부 실거래가, 공고는 청약홈·LH 공개 자료예요. 숫자·일정은 원문과 공고문으로 꼭 확인하세요. 이 링크는 보낸 분이 언제든 멈출 수 있고, 만든 지 30일 뒤 저절로 닫혀요.</p>")
    resp = web._page("함께 보는 관심 보드 | 집보미", "가족·친구가 공유한 관심 단지와 청약 공고를 읽기 전용으로 봅니다.", f"{site}/g/{token}", body,
                     f"{site}/app/static/og.png", "<meta name='robots' content='noindex,nofollow'>" + _CSS)
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["Referrer-Policy"] = "no-referrer"  # 링크의 토큰이 다른 사이트로 새지 않게
    return resp


def routes() -> list:
    return [Route("/g/{token}", board_view)]
