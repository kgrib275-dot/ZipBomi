"""홈 시장 요약 (/api/home/market) — 노트가 적어도 첫 화면이 비지 않게, 이미 모은 자료로 '지금 시장'을 보여 준다 (2026-11-02).

- 지표: 현행 수치(pipeline/policy.py)의 기준금리·주담대 금리·주택가격전망지수·주택관련 대출 잔액 + KB 서울 아파트 매매지수 전월 대비
- 거래: 저장된 국토교통부 아파트 매매 신고(rtms_apt_trade) — 전국 시군구가 다 모인 최근 두 달의 거래 수·중위가,
  거래가 많은 시군구 5곳, 가장 비싼 거래 5건. 계약 뒤 30일 안 신고라 최근 달은 '신고 진행 중'으로 적는다.
- 청약: 앞으로 14일 안의 접수·마감·발표 (re_apply_notice, 상시 공고 마감 제외)
- 기사: 최근 3일 안 부동산 관련도 3점 이상 기사 제목·출처·링크 (원문으로 보낸다)
모든 방문자가 10분 동안 같은 결과를 나눠 쓴다. LLM·외부 호출 없음.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from statistics import median

from fastapi import APIRouter

from api.common import cached
from pipeline import db, policy, re_store, regions_kr

router = APIRouter(tags=["home"])
TTL = 600
MIN_REGIONS = 100  # 이만큼 시군구가 들어 있어야 '전국' 달로 본다 (일부 시도만 받은 과거 달 제외)


def _rows(sql: str, params: tuple = ()) -> list[dict]:
    re_store.ensure_schema()
    c = db.connect()
    try:
        return [dict(r) for r in c.execute(sql, params)]
    finally:
        c.close()


def _ym_label(ym: str) -> str:
    return f"{ym[:4]}년 {int(ym[4:])}월"


def _trades() -> dict | None:
    months = [r["deal_ymd"] for r in _rows(
        "SELECT deal_ymd, COUNT(DISTINCT lawd_cd) n FROM rtms_apt_trade GROUP BY deal_ymd HAVING n >= ? ORDER BY deal_ymd DESC LIMIT 3",
        (MIN_REGIONS,))]
    today = date.today()
    cur_ym = f"{today.year}{today.month:02d}"
    months = [m for m in months if m < cur_ym][:2]  # 이번 달은 며칠치뿐이라 뺀다
    if not months:
        return None
    m = months[0]
    rows = _rows("SELECT lawd_cd, umd, name, area, floor, amount, deal_date FROM rtms_apt_trade "
                 "WHERE deal_ymd=? AND COALESCE(cancelled,0)=0 AND amount IS NOT NULL", (m,))
    if not rows:
        return None
    prev = None
    if len(months) > 1:
        p_amts = [r["amount"] for r in _rows("SELECT amount FROM rtms_apt_trade WHERE deal_ymd=? AND COALESCE(cancelled,0)=0 "
                                             "AND amount IS NOT NULL", (months[1],))]
        if p_amts:
            prev = {"ym": months[1], "label": _ym_label(months[1]), "count": len(p_amts), "median": median(p_amts)}
    by: dict[str, list[int]] = {}
    for r in rows:
        by.setdefault(r["lawd_cd"], []).append(r["amount"])
    top_regions = sorted(by.items(), key=lambda kv: len(kv[1]), reverse=True)[:5]
    top_deals = sorted(rows, key=lambda r: r["amount"], reverse=True)[:5]
    y, mo = int(m[:4]), int(m[4:])
    month_end = date(y + (mo == 12), mo % 12 + 1, 1) - timedelta(days=1)
    return {
        "ym": m, "label": _ym_label(m), "count": len(rows), "median": median(r["amount"] for r in rows), "prev": prev,
        "reporting": (today - month_end).days < 30,  # 신고 기한(계약 후 30일)이 아직 안 지남
        "regions": [{"lawd": k, "name": regions_kr.NAMES.get(k, k), "count": len(v), "median": median(v)} for k, v in top_regions],
        "top": [{"lawd": r["lawd_cd"], "region": regions_kr.NAMES.get(r["lawd_cd"], r["lawd_cd"]), "umd": r["umd"], "name": r["name"],
                 "area": r["area"], "floor": r["floor"], "amount": r["amount"], "date": r["deal_date"]} for r in top_deals],
        "source": "국토교통부 아파트 매매 실거래가 신고 자료",
    }


def _kb_seoul() -> dict | None:
    rs = _rows("SELECT period, value FROM re_econ_series WHERE series='kb_sale_apt_seoul' AND value IS NOT NULL "
               "ORDER BY period DESC LIMIT 2")
    if len(rs) < 2 or not rs[1]["value"]:
        return None
    return {"label": "KB 서울 아파트 매매지수", "value": rs[0]["value"], "period": f"{rs[0]['period'][:4]}-{rs[0]['period'][4:]}",
            "mom": round((rs[0]["value"] / rs[1]["value"] - 1) * 100, 2), "source": "KB국민은행 (한국은행 ECOS 재게시)"}


def _apply() -> list[dict]:
    t = date.today()
    end = (t + timedelta(days=14)).isoformat()
    rows = _rows("SELECT notice_id, name, region, notice_date, receipt_start, receipt_end, winner_date, url FROM re_apply_notice "
                 "WHERE (receipt_start BETWEEN ? AND ?) OR (receipt_end BETWEEN ? AND ?) OR (winner_date BETWEEN ? AND ?)",
                 (t.isoformat(), end) * 3)
    out = []
    for r in rows:
        nd, ed = r.get("notice_date"), r.get("receipt_end")
        long_open = bool(nd and ed and (date.fromisoformat(ed[:10]) - date.fromisoformat(nd[:10])).days > 120)
        for col, label in (("receipt_start", "접수 시작"), ("receipt_end", "접수 마감"), ("winner_date", "당첨 발표")):
            d = (r.get(col) or "")[:10]
            if d and t.isoformat() <= d <= end and not (col == "receipt_end" and long_open):
                out.append({"date": d, "label": label, "name": r["name"], "region": r.get("region") or "", "id": r["notice_id"],
                            "url": r["url"] if str(r.get("url") or "").startswith("http") else ""})
    out.sort(key=lambda x: x["date"])
    return out[:6]


def _articles() -> list[dict]:
    since = (datetime.now(db.KST) - timedelta(days=3)).isoformat()
    rows = _rows("SELECT title, source, url, published_at, llm_score FROM articles WHERE llm_score >= 3 AND published_at >= ? "
                 "ORDER BY published_at DESC LIMIT 40", (since,))
    seen, out = set(), []
    for r in rows:
        key = (r["title"] or "")[:18]
        if key in seen or not str(r.get("url") or "").startswith("http"):
            continue
        seen.add(key)
        out.append({"title": r["title"], "source": r["source"], "url": r["url"], "at": r["published_at"], "score": r["llm_score"]})
        if len(out) >= 8:
            break
    return out


def _market() -> dict:
    pm = policy.public_map()
    ind = [pm[k] for k in ("base_rate", "mortgage_rate", "house_outlook_csi", "housing_loan_balance") if k in pm]
    return {"indicators": ind, "kb_seoul": _kb_seoul(), "trades": _trades(), "apply": _apply(), "articles": _articles(),
            "at": datetime.now(db.KST).isoformat(timespec="minutes")}


@router.get("/home/market")
def home_market() -> dict:
    return cached("home:market", _market, TTL)
