"""공유·검색용 공개 페이지 (2026-11-20) — app/web.py ROUTES 에 이어 붙는다. 서버가 HTML 을 그려서 로그인·JS 없이 읽히고, 검색 엔진·메신저 미리보기가 내용을 읽는다.

- /c/{공고ID}          청약 공고 한 건 — 일정 표·주택형·재공급 설명·지난 당첨 가점과 '내 가점 비교'(브라우저 안에서만 계산)
- /a/{시군구코드}/{단지}  단지 최근 6개월 실거래 요약 (?d=동)
- /s/p?score=&r=       내 가점 카드 공유 주소 — 점수·지역별 미리보기 이미지, 사람은 계산기로 보낸다
- /g/{토큰}            함께 보기 (api/routers/board.py 에서 만든 읽기 전용 보드)
자료는 pipeline/pubdata.py(저장된 표만), 이미지는 app/og_cards.py. 모든 값은 이스케이프하고 주소 값은 정규식·목록으로 거른다.
"""
from __future__ import annotations

import json
import re
from html import escape
from urllib.parse import quote

from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response
from starlette.routing import Route

from pipeline import pubdata, regions_kr
from pipeline.pubdata import man

_SUPPLY_NOTE = {
    "resale": "🔁 <b>재공급</b>은 주택공급질서 교란 등 불법행위가 적발돼 계약이 취소된 주택을 다시 공급하는 공고예요. 보통 무순위(사후 접수)로 나오니 자격·접수 방법은 공고문에서 꼭 확인하세요.",
    "lottery": "<b>무순위·잔여세대·임의공급</b> 공고예요. 1·2순위 접수가 끝난 뒤 남은 물량이라 접수 조건이 일반 공급과 다를 수 있어요. 공고문에서 확인하세요.",
}
_EXTRA_CSS = ("<style>table{border-collapse:collapse;width:100%;margin:8px 0 18px;font-size:15px}td,th{padding:7px 10px;border-bottom:1px solid #3A3220;text-align:left}"
              "th{color:#B8AB8A;font-weight:600}.box{border:1px solid #3A3220;border-left:3px solid #F5B800;border-radius:10px;padding:10px 14px;margin:14px 0;background:#1C180F}"
              ".tag{display:inline-block;font-size:13px;padding:1px 10px;border-radius:999px;border:1px solid #F5B800;color:#FFE89A;margin-right:6px}"
              ".ctas{display:flex;flex-wrap:wrap;gap:10px;margin:22px 0}.ctas a{padding:10px 18px;border-radius:999px;border:1px solid #F5B800;text-decoration:none}"
              ".ctas a.p{background:#F5B800;color:#1A1405;font-weight:700}input.sc{width:84px;padding:6px 8px;border-radius:8px;border:1px solid #3A3220;background:#120F08;color:#FBF6E9;font:inherit}"
              ".small{font-size:13px;color:#B8AB8A}</style>")


def _w():
    from app import web  # 늦게 가져온다 — web.py 가 이 모듈의 ROUTES 를 가져가므로 순환을 피한다
    return web


def _not_found(what: str) -> Response:
    return HTMLResponse(f"<meta charset='utf-8'><h1>{escape(what)}을(를) 찾을 수 없습니다</h1><p><a href='/calendar'>청약 일정 달력</a> · <a href='/deals'>실거래가</a></p>", status_code=404)


# ───────────────────────── 공고 ─────────────────────────

def notice_page(request: Request) -> Response:
    from app import og_cards
    n = pubdata.notice(request.path_params["nid"])
    if not n:
        return _not_found("공고")
    w = _w()
    site = w._site(request)
    url = f"{site}/c/{n['notice_id']}"
    sch = dict(n["schedule"])
    when = sch.get("접수") or sch.get("1순위 접수") or sch.get("특별공급 접수") or ""
    parts = [f"{n.get('region') or ''}에서" + (f" {n['households']}세대를" if n.get("households") else ""), f"공급하는 {n.get('category') or n.get('house_type') or '청약'} 공고예요."]
    desc = " ".join(p for p in parts if p.strip()) + (f" 접수 {when}." if when else "") + (f" 당첨자 발표 {sch['당첨자 발표']}." if sch.get("당첨자 발표") else "")
    tag = {"resale": "🔁 재공급", "lottery": "무순위·잔여"}.get(n["supply"], "")
    rows = "".join(f"<tr><th>{escape(k)}</th><td>{escape(v)}</td></tr>" for k, v in n["schedule"])
    models = ""
    if n["models"]:
        models = ("<h2>주택형별 공급</h2><table><tr><th>주택형</th><th>공급 세대</th><th>특별공급</th><th>최고 분양가</th></tr>"
                  + "".join(f"<tr><td>{escape(str(m['type']))}</td><td>{m['households'] or '-'}</td><td>{m['special'] if m['special'] is not None else '-'}</td>"
                            f"<td>{escape(man(m['top'])) if m['top'] else '-'}</td></tr>" for m in n["models"]) + "</table>")
    sc = n["scores"]
    score_box = ""
    if sc:
        score_box = (f"<div class='box'><b>📈 {escape(sc['region'])} 지난 1년 당첨 최저 가점 중앙값 {sc['median']:g}점</b> <span class='small'>({sc['min']:g}~{sc['max']:g}점 · {sc['n']}건)</span>"
                     f"<p style='margin:8px 0 0'>내 가점 <input class='sc' id='ms' type='number' min='0' max='84' inputmode='numeric' aria-label='내 가점'> 점 "
                     f"<span id='mr' class='small'>을 넣으면 비교해 드려요 (이 브라우저에서만 계산해요).</span></p>"
                     f"<p class='small' style='margin:6px 0 0'>단지·주택형마다 당첨선은 크게 달라요. 참고용입니다.</p></div>"
                     f"<script>(function(){{var m={sc['median']},i=document.getElementById('ms'),o=document.getElementById('mr');"
                     f"i.addEventListener('input',function(){{var v=Number(i.value);if(i.value===''||isNaN(v)||v<0||v>84){{o.textContent='을 넣으면 비교해 드려요 (이 브라우저에서만 계산해요).';return}}"
                     f"var d=Math.round((v-m)*10)/10;o.textContent=d>=0?'중앙값보다 '+d+'점 높아요 (참고용)':'중앙값보다 '+(-d)+'점 낮아요 (참고용)'}})}})();</script>")
    src = (f"<p class='small'>출처: {'LH 청약플러스' if n.get('source') == 'lh' else '한국부동산원 청약홈'} 공개 자료. 일정·자격·분양가는 반드시 공고문에서 다시 확인하세요."
           + (f" <a href='{escape(n['url'])}' rel='nofollow noopener' target='_blank'>공고 원문 →</a>" if str(n.get('url') or '').startswith('http') else "") + "</p>")
    q = quote((n.get("name") or "")[:30])
    ctas = (f"<div class='ctas'><a class='p' href='/calc?tab=sub&s=1'>내 가점 계산하기</a><a href='/calendar'>청약 일정 달력</a>"
            f"<a href='/deals?tab=apply&q={q}'>공고 목록에서 보기</a></div>")
    body = (f"<div class='meta'>청약 공고 · {escape(n.get('region') or '')}{(' · <span class=tag>' + escape(tag) + '</span>') if tag else ''}</div><h1>{escape(n.get('name') or '')}</h1>"
            f"<p class='sum'>{escape(desc)}</p>{('<div class=box>' + _SUPPLY_NOTE[n['supply']] + '</div>') if n['supply'] else ''}"
            f"<h2>일정</h2><table>{rows}</table>{models}{score_box}{ctas}{src}"
            f"<p class='small'>주소: {escape(n.get('address') or '-')}{(' · 시공 ' + escape(n['builder'])) if n.get('builder') else ''}</p>")
    ld = {"@context": "https://schema.org", "@type": "Event", "name": n.get("name") or "", "eventStatus": "https://schema.org/EventScheduled",
          "startDate": (n.get("receipt_start") or n.get("notice_date") or "")[:10], "endDate": (n.get("receipt_end") or n.get("receipt_start") or n.get("notice_date") or "")[:10],
          "location": {"@type": "Place", "name": n.get("name") or "", "address": n.get("address") or n.get("region") or ""}, "url": url,
          "description": desc[:200]}
    path = og_cards.card_path("notice", n["notice_id"])
    og = f"{site}/app/static/og/{path.name}" if og_cards.card_fresh(path) else f"{site}/app/static/og.png"
    if not og_cards.card_fresh(path):
        og_cards.render_card_async(path, lambda n=n: og_cards.notice_html(n))
    title = f"{n.get('name')} 청약 일정·가점{' (재공급)' if n['supply'] == 'resale' else ''} | 집보미"
    ld_json = json.dumps(ld, ensure_ascii=False).replace("</", "<\\/")
    return w._page(title, desc[:150], url, body, og, f'<script type="application/ld+json">{ld_json}</script>{_EXTRA_CSS}')


# ───────────────────────── 단지 ─────────────────────────

def apt_page(request: Request) -> Response:
    from app import og_cards
    lawd, apt = request.path_params["lawd"], request.path_params["apt"]
    a = pubdata.apt_info(lawd, apt, request.query_params.get("d", "")[:20])
    if not a:
        return _not_found("단지")
    w = _w()
    site = w._site(request)
    d = quote(a["dong"]) if a["dong"] else ""
    url = f"{site}/a/{lawd}/{quote(apt)}" + (f"?d={d}" if d else "")
    b0 = a["bands"][0]
    desc = f"{a['region']} {a['dong']} {apt}의 최근 6개월 매매 실거래 {a['n']}건. 전용 {b0['area']}㎡ 중위 거래가 {man(b0['median'])}."
    bands = ("<table><tr><th>전용(㎡)</th><th>거래</th><th>중위가</th><th>범위</th></tr>"
             + "".join(f"<tr><td>{x['area']}</td><td>{x['n']}건</td><td><b>{escape(man(x['median']))}</b></td><td>{escape(man(x['min']))} ~ {escape(man(x['max']))}</td></tr>" for x in a["bands"]) + "</table>")
    recent = ("<table><tr><th>계약일</th><th>전용(㎡)</th><th>층</th><th>거래가</th></tr>"
              + "".join(f"<tr><td>{escape(r['date'])}</td><td>{r['area']}</td><td>{r['floor'] if r['floor'] is not None else '-'}</td><td>{escape(man(r['amount']))}</td></tr>" for r in a["recent"]) + "</table>")
    link = f"/my-homes?lawd={lawd}&dong={quote(a['dong'])}&apt={quote(apt)}"
    body = (f"<div class='meta'>아파트 실거래 · {escape(a['region'])} {escape(a['dong'])}</div><h1>{escape(apt)}</h1><p class='sum'>{escape(desc)}</p>"
            f"<h2>평형별 중위 거래가 (최근 6개월)</h2>{bands}<h2>최근 거래</h2>{recent}"
            f"<div class='ctas'><a class='p' href='{escape(link)}'>관심 단지로 담고 추이 보기</a><a href='/calc'>내 집 계산기</a><a href='/deals?lawd={lawd}'>{escape(a['region'])} 실거래가</a></div>"
            f"<p class='small'>출처: 국토교통부 아파트 매매 실거래가 공개 자료(저장본, {escape(a['as_of'])} 계약분까지). 계약 후 30일까지 신고가 늦을 수 있고 해제 거래는 뺐어요. "
            f"층·향·동에 따라 같은 평형도 값이 다르니 참고용으로 보세요.</p>")
    path = og_cards.card_path("apt", f"{lawd}|{a['dong']}|{apt}")
    og = f"{site}/app/static/og/{path.name}" if og_cards.card_fresh(path) else f"{site}/app/static/og.png"
    if not og_cards.card_fresh(path):
        og_cards.render_card_async(path, lambda a=a: og_cards.apt_html(a))
    return w._page(f"{apt} 실거래가 — 최근 6개월 | 집보미", desc[:150], url, body, og, _EXTRA_CSS)


# ───────────────────────── 내 가점 카드 ─────────────────────────

def share_score(request: Request) -> Response:
    from app import og_cards
    q = request.query_params
    try:
        score = int(q.get("score", ""))
    except ValueError:
        score = -1
    region = q.get("r", "")
    if not 0 <= score <= 84:
        return RedirectResponse("/calc?tab=sub")
    if region not in pubdata.SIDOS:
        region = ""
    sc = pubdata.region_scores(region) if region else None
    med = sc["median"] if sc else None
    w = _w()
    site = w._site(request)
    diff = f" · {region} 지난 1년 당첨 중앙값 {med:g}점" if med is not None else ""
    title = f"내 청약 가점 {score}점{diff}"
    desc = "참고용 비교예요. 단지·주택형마다 당첨선은 크게 달라요. 내 가점도 3분이면 계산해 볼 수 있어요."
    path = og_cards.card_path("score", f"{score}|{region}|{med}")
    og = f"{site}/app/static/og/{path.name}" if og_cards.card_fresh(path, 72) else f"{site}/app/static/og.png"
    if not og_cards.card_fresh(path, 72):
        og_cards.render_card_async(path, lambda: og_cards.score_html(score, region, med))
    dest = f"{site}/calc?tab=sub&s=1"
    head = f'<meta http-equiv="refresh" content="0;url={escape(dest)}"><script>location.replace({w._json_str(dest)})</script>'
    body = f"<h1>{escape(title)}</h1><p>{escape(desc)}</p><p><a class='btn' href='{escape(dest)}'>내 가점 계산해 보기 →</a></p>"
    return w._page(title, desc, f"{site}/s/p?score={score}" + (f"&r={quote(region)}" if region else ""), body, og, head)


def routes() -> list:
    out = [Route("/c/{nid}", notice_page), Route("/a/{lawd}/{apt}", apt_page), Route("/s/p", share_score)]
    try:  # 함께 보기(/g) 는 board_page 가 있으면 이어 붙인다
        from app import board_page
        out += board_page.routes()
    except ImportError:
        pass
    return out
