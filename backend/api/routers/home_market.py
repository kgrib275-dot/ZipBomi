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

from fastapi import APIRouter, Query

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


def _kst(at: str | None) -> datetime | None:
    """기사 시각 → 한국 시각. 수집처마다 UTC(+00:00)·한국 시각(+09:00)·시각대 없음이 섞여 있어, 글자 그대로 자르면 9시간 어긋났다 (2026-11-03)."""
    if not at:
        return None
    try:
        d = datetime.fromisoformat(str(at).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (d.replace(tzinfo=db.KST) if d.tzinfo is None else d).astimezone(db.KST)


def _articles() -> list[dict]:
    # 글자 비교는 시각대가 섞여 틀리므로 넉넉히(4일) 고른 뒤 한국 시각으로 바꿔 거르고 정렬한다
    since_dt = datetime.now(db.KST) - timedelta(days=3)
    rows = _rows("SELECT title, source, url, published_at, llm_score FROM articles WHERE llm_score >= 3 AND published_at >= ? "
                 "ORDER BY published_at DESC LIMIT 120", ((since_dt - timedelta(days=1)).isoformat(),))
    rows = [dict(r, _k=_kst(r["published_at"])) for r in rows]
    rows = sorted((r for r in rows if r["_k"] and r["_k"] >= since_dt), key=lambda r: r["_k"], reverse=True)
    seen, out = set(), []
    for r in rows:
        key = (r["title"] or "")[:18]
        if key in seen or not str(r.get("url") or "").startswith("http"):
            continue
        seen.add(key)
        out.append({"title": r["title"], "source": r["source"], "url": r["url"], "at": r["_k"].strftime("%Y-%m-%d %H:%M"), "score": r["llm_score"]})
        if len(out) >= 8:
            break
    return out


def _series_kpi(series: str, label: str, mode: str, src: str, href: str = "/now") -> dict | None:
    """ECOS 시계열 한 개 → 지표 칸. mode: idx(지수, 전월 대비 %) · pt(지수, 전월 대비 p) · pct(값이 %)."""
    rs = _rows("SELECT period, value FROM re_econ_series WHERE series=? AND value IS NOT NULL ORDER BY period DESC LIMIT 2", (series,))
    if len(rs) < 2:
        return None
    v, pv = rs[0]["value"], rs[1]["value"]
    per = f"{rs[0]['period'][:4]}.{rs[0]['period'][4:]}"
    if mode == "idx":
        ch = round((v / pv - 1) * 100, 2) if pv else 0
        return {"label": label, "value": f"{v:.1f}", "sub": f"전월 대비 {ch:+.2f}% · {per}", "dir": "up" if ch > 0 else "down" if ch < 0 else "", "href": href, "src": src}
    if mode == "pt":
        ch = round(v - pv, 1)
        return {"label": label, "value": f"{v:.1f}", "sub": f"전월 대비 {ch:+.1f}p · {per}", "dir": "up" if ch > 0 else "down" if ch < 0 else "", "href": href, "src": src}
    ch = round(v - pv, 2)
    return {"label": label, "value": f"{v:+.2f}%", "sub": f"전월 {pv:+.2f}% · {per}", "dir": "up" if v > 0 else "down" if v < 0 else "", "href": href, "src": src}


def _cmpet_kpi() -> dict | None:
    """전국 아파트 청약 경쟁률 (청약홈 통계, 최근 월)."""
    try:
        from pipeline import apply_stats
        rows = apply_stats.load("cmpet_area", "")
    except Exception:  # noqa: BLE001
        return None
    by: dict[str, list[float]] = {}
    for r in rows:
        try:
            req, hh = float(r.get("SUPLY_REQ_CNT") or 0), float(r.get("SUPLY_HSHLDCO") or 0)
        except (TypeError, ValueError):
            continue
        a = by.setdefault(r["ym"], [0.0, 0.0]); a[0] += req; a[1] += hh
    ms = [m for m in sorted(by) if by[m][1] > 0]
    if len(ms) < 2:
        return None
    cur, prev = by[ms[-1]][0] / by[ms[-1]][1], by[ms[-2]][0] / by[ms[-2]][1]
    return {"label": "전국 아파트 청약 경쟁률", "value": f"{cur:.1f} : 1", "sub": f"전월 {prev:.1f} : 1 · {ms[-1][:4]}.{ms[-1][4:]}",
            "dir": "up" if cur > prev else "down" if cur < prev else "", "href": "/calendar?tab=scores", "src": "청약홈"}


def _extra_kpis() -> list[dict]:
    """지표 5칸 추가 (2026-11-02) — 집 살 사람·팔 사람·중개 실무자가 자주 보는 숫자."""
    # 칸마다 출처 (2026-11-03 — 운영 기준 '숫자에는 출처·기준일', KB 는 '자료: KB부동산')
    out = [_series_kpi("kb_sale_apt", "KB 전국 아파트 매매지수", "idx", "자료: KB부동산"), _series_kpi("kb_jeonse_apt", "KB 전국 아파트 전세지수", "idx", "자료: KB부동산"),
           _series_kpi("consumer_csi", "소비자심리지수", "pt", "한국은행"), _series_kpi("land_chg_seoul", "서울 지가변동률", "pct", "한국부동산원"), _cmpet_kpi()]
    return [x for x in out if x]


def _market() -> dict:
    pm = policy.public_map()
    ind = [pm[k] for k in ("base_rate", "mortgage_rate", "house_outlook_csi", "housing_loan_balance") if k in pm]
    return {"indicators": ind, "kb_seoul": _kb_seoul(), "extra": _extra_kpis(), "trades": _trades(), "apply": _apply(), "articles": _articles(),
            "at": datetime.now(db.KST).isoformat(timespec="minutes")}


@router.get("/home/market")
def home_market() -> dict:
    return cached("home:market", _market, TTL)


# ───────── 가장 비싼 거래 — 지역(전국·서울·경기·부산)·종류(아파트·오피스텔·상가) 고르기, 10건 (2026-11-02) ─────────
_TOP_TABLES = {"apt": ("rtms_apt_trade", "아파트"), "offi": ("rtms_offi_trade", "오피스텔"), "nrg": ("rtms_nrg_trade", "상가·업무용")}
_TOP_SIDO = {"all": "", "11": "11", "41": "41", "26": "26"}


def _top(kind: str, sido: str, limit: int) -> dict:
    table, label = _TOP_TABLES[kind]
    today = date.today()
    cur_ym = f"{today.year}{today.month:02d}"
    pre = _TOP_SIDO[sido]
    months = [r["deal_ymd"] for r in _rows(f"SELECT DISTINCT deal_ymd FROM {table} WHERE deal_ymd < ? ORDER BY deal_ymd DESC LIMIT 1", (cur_ym,))]
    if not months:
        return {"ym": None, "label": "", "kind": label, "rows": []}
    m = months[0]
    rows = _rows(f"SELECT lawd_cd, umd, name, kind, area, floor, amount, deal_date FROM {table} "
                 "WHERE deal_ymd=? AND COALESCE(cancelled,0)=0 AND amount IS NOT NULL AND lawd_cd LIKE ? ORDER BY amount DESC LIMIT ?",
                 (m, f"{pre}%", limit))
    return {"ym": m, "label": _ym_label(m), "kind": label, "source": f"국토교통부 {label} 매매 실거래가 신고 자료",
            "rows": [{"lawd": r["lawd_cd"], "region": regions_kr.NAMES.get(r["lawd_cd"], r["lawd_cd"]), "umd": r["umd"] or "",
                      "name": r["name"] or (f"{r['kind']}용 건물" if r["kind"] else label), "area": r["area"], "floor": r["floor"],
                      "amount": r["amount"], "date": r["deal_date"]} for r in rows]}


@router.get("/home/top")
def home_top(kind: str = Query("apt", pattern="^(apt|offi|nrg)$"), sido: str = Query("all", pattern="^(all|11|41|26)$"),
             limit: int = Query(10, ge=1, le=20)) -> dict:
    return cached(f"home:top:{kind}:{sido}:{limit}", lambda: _top(kind, sido, limit), 600)


# ───────── 지난달 거래 요약 — 지역·종류 고르기, 거래 많은 지역 10곳 (2026-11-02) ─────────
def _volume(kind: str, sido: str) -> dict:
    table, label = _TOP_TABLES[kind]
    pre = _TOP_SIDO[sido]
    t = date.today()
    cur = f"{t.year}{t.month:02d}"
    months = [r["deal_ymd"] for r in _rows(f"SELECT DISTINCT deal_ymd FROM {table} WHERE deal_ymd < ? ORDER BY deal_ymd DESC LIMIT 2", (cur,))]
    if not months:
        return {"ym": None, "label": "", "kind": label, "count": 0, "regions": []}
    m = months[0]
    rows = _rows(f"SELECT lawd_cd, amount FROM {table} WHERE deal_ymd=? AND COALESCE(cancelled,0)=0 AND amount IS NOT NULL AND lawd_cd LIKE ?", (m, f"{pre}%"))
    prev = None
    if len(months) > 1:
        pa = [r["amount"] for r in _rows(f"SELECT amount FROM {table} WHERE deal_ymd=? AND COALESCE(cancelled,0)=0 AND amount IS NOT NULL "
                                         "AND lawd_cd LIKE ?", (months[1], f"{pre}%"))]
        if pa:
            prev = {"label": _ym_label(months[1]), "count": len(pa), "median": median(pa)}
    by: dict[str, list[int]] = {}
    for r in rows:
        by.setdefault(r["lawd_cd"], []).append(r["amount"])
    top = sorted(by.items(), key=lambda kv: len(kv[1]), reverse=True)[:10]
    y, mo = int(m[:4]), int(m[4:])
    month_end = date(y + (mo == 12), mo % 12 + 1, 1) - timedelta(days=1)
    return {"ym": m, "label": _ym_label(m), "kind": label, "count": len(rows), "median": median(r["amount"] for r in rows) if rows else None,
            "prev": prev, "reporting": (t - month_end).days < 30, "source": f"국토교통부 {label} 매매 실거래가 신고 자료",
            "regions": [{"lawd": k, "name": regions_kr.NAMES.get(k, k), "count": len(v), "median": median(v)} for k, v in top]}


@router.get("/home/volume")
def home_volume(kind: str = Query("apt", pattern="^(apt|offi|nrg)$"), sido: str = Query("all", pattern="^(all|11|41|26)$")) -> dict:
    return cached(f"home:vol:{kind}:{sido}", lambda: _volume(kind, sido), 600)
