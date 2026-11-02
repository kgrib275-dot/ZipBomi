"""부동산 데이터 출처별 받기 — 청약홈(공공데이터포털 odcloud), 한국은행 기준금리, 한국은행 ECOS, LH 청약플러스 공고 목록.

- 국토교통부 실거래가(RTMS)는 rtms.py, 저장은 re_store.py, 순서·이어 받기는 redata.py.
- 모두 한 번에 하나씩(순차) 부르고, 요청 사이에 쉬고, 타임아웃·재시도(물러서기)를 둔다. 로그인·캡차가 필요한 곳은 다루지 않는다.
- 웹 페이지(한국은행·LH)는 robots.txt 가 허용하는 경로만 쓴다 (2026-11-02 확인 — 한국은행 Allow: /portal/, LH 는 목록 경로 금지 없음).
- 키 값은 로그·오류 문구에 넣지 않는다.
"""
from __future__ import annotations

import html
import json
import logging
import re
import time
from datetime import date, timedelta

import httpx

from pipeline import re_store, rtms

log = logging.getLogger("zipgenie.redata")
UA = "Mozilla/5.0 (compatible; ZipBomiBot/1.0; +real-estate public data)"
ODCLOUD = "https://api.odcloud.kr/api"


def client() -> httpx.Client:
    return httpx.Client(timeout=httpx.Timeout(25, connect=10), follow_redirects=True, headers={"User-Agent": UA})


def _get(c: httpx.Client, url: str, params: dict | None = None, retries: int = 3, headers: dict | None = None) -> httpx.Response:
    """GET + 네트워크 오류·5xx 는 1.5s→3s→6s 물러서며 다시."""
    for attempt in range(retries):
        try:
            r = c.get(url, params=params, headers=headers)
            if r.status_code >= 500:
                raise httpx.HTTPStatusError("server error", request=r.request, response=r)
            return r
        except httpx.HTTPError:
            if attempt == retries - 1:
                raise rtms.RtmsError("서버에 연결하지 못했습니다 (재시도 후 실패).")
            time.sleep(1.5 * (2 ** attempt))
    raise rtms.RtmsError("서버에 연결하지 못했습니다.")


# ───────────────────────── 청약홈 (api.odcloud.kr) ─────────────────────────

# 상세 조회 op → (짧은 코드, 주택 구분 기본값, 주택형별 op, 경쟁률 op)
APPLY_OPS = {
    "ApplyhomeInfoDetailSvc/v1/getAPTLttotPblancDetail":
        ("APT", "APT", "ApplyhomeInfoDetailSvc/v1/getAPTLttotPblancMdl", "ApplyhomeInfoCmpetRtSvc/v1/getAPTLttotPblancCmpet"),
    "ApplyhomeInfoDetailSvc/v1/getUrbtyOfctlLttotPblancDetail":
        ("URB", "오피스텔·도시형", "ApplyhomeInfoDetailSvc/v1/getUrbtyOfctlLttotPblancMdl",
         "ApplyhomeInfoCmpetRtSvc/v1/getUrbtyOfctlLttotPblancCmpet"),
    "ApplyhomeInfoDetailSvc/v1/getRemndrLttotPblancDetail":
        ("RMD", "APT 무순위·잔여", "ApplyhomeInfoDetailSvc/v1/getRemndrLttotPblancMdl",
         "ApplyhomeInfoCmpetRtSvc/v1/getRemndrLttotPblancCmpet"),
    "ApplyhomeInfoDetailSvc/v1/getPblPvtRentLttotPblancDetail":
        ("PPR", "공공지원민간임대", "ApplyhomeInfoDetailSvc/v1/getPblPvtRentLttotPblancMdl",
         "ApplyhomeInfoCmpetRtSvc/v1/getPblPvtRentLttotPblancCmpet"),
    "ApplyhomeInfoDetailSvc/v1/getOPTLttotPblancDetail":
        ("OPT", "임의공급", "ApplyhomeInfoDetailSvc/v1/getOPTLttotPblancMdl", "ApplyhomeInfoCmpetRtSvc/v1/getOPTLttotPblancCmpet"),
}
SCORE_OP = "ApplyhomeInfoCmpetRtSvc/v1/getAptLttotPblancScore"


def odcloud_page(c: httpx.Client, op: str, api: str, cap: int, page: int = 1, per_page: int = 500,
                 cond: dict | None = None) -> dict:
    """odcloud 한 쪽. 키 없음 → KeyMissing, 401/403 → NotRegistered(활용신청 필요), 429 → LimitExceeded."""
    key = rtms.api_key()
    if not key:
        raise rtms.KeyMissing("API 키(DATA_GO_KR_KEY)가 없습니다.")
    rtms.count_call(api, cap)
    params = {"page": page, "perPage": per_page, "returnType": "JSON", "serviceKey": key}
    params.update(cond or {})
    r = _get(c, f"{ODCLOUD}/{op}", params=params)
    if r.status_code in (401, 403):
        raise rtms.NotRegistered("활용신청이 필요하거나(승인 대기 포함) 키가 이 API 에 등록되지 않았습니다.")
    if r.status_code == 429:
        raise rtms.LimitExceeded("하루 호출 한도를 다 썼습니다. 다음 실행에 이어서 받습니다.")
    if r.status_code != 200:
        raise rtms.RtmsError(f"청약홈 API 오류 (HTTP {r.status_code})")
    try:
        d = r.json()
    except ValueError as e:
        raise rtms.RtmsError("청약홈 API 응답을 읽지 못했습니다.") from e
    if isinstance(d, dict) and d.get("code") is not None and not d.get("data"):
        code = d.get("code")
        if code in (-4, -401, -3):
            raise rtms.NotRegistered("활용신청이 필요하거나 키가 이 API 에 등록되지 않았습니다.")
        raise rtms.RtmsError(f"청약홈 API 오류 ({code})")
    return d


def odcloud_all(c: httpx.Client, op: str, api: str, cap: int, cond: dict | None = None, per_page: int = 500,
                max_pages: int = 40, delay: float = 0.3) -> list[dict]:
    out: list[dict] = []
    for page in range(1, max_pages + 1):
        d = odcloud_page(c, op, api, cap, page, per_page, cond)
        rows = d.get("data") or []
        out.extend(x for x in rows if isinstance(x, dict))
        total = int(d.get("matchCount") or d.get("totalCount") or 0)
        if not rows or page * per_page >= total:
            break
        time.sleep(delay)
    return out


def notice_from_applyhome(op: str, it: dict) -> dict | None:
    code, default_type, *_ = APPLY_OPS[op]
    hmn, pn = str(it.get("HOUSE_MANAGE_NO") or "").strip(), str(it.get("PBLANC_NO") or "").strip()
    if not hmn:
        return None
    addr = (it.get("HSSPLY_ADRES") or "").strip()
    lawd, sido = re_store.lawd_from_address(addr, it.get("SUBSCRPT_AREA_CODE_NM"))
    house_type = default_type
    if code == "URB":
        house_type = (it.get("HOUSE_DTL_SECD_NM") or it.get("HOUSE_SECD_NM") or default_type).strip()
    return {
        "notice_id": f"AH-{code}-{hmn}-{pn}", "name": (it.get("HOUSE_NM") or "").strip(), "house_type": house_type,
        "address": addr, "lawd_cd": lawd, "region": sido or (it.get("SUBSCRPT_AREA_CODE_NM") or None),
        "households": re_store.to_int(it.get("TOT_SUPLY_HSHLDCO")),
        "notice_date": re_store.to_date(it.get("RCRIT_PBLANC_DE")),
        "receipt_start": re_store.to_date(it.get("RCEPT_BGNDE") or it.get("SUBSCRPT_RCEPT_BGNDE")),
        "receipt_end": re_store.to_date(it.get("RCEPT_ENDDE") or it.get("SUBSCRPT_RCEPT_ENDDE")),
        "winner_date": re_store.to_date(it.get("PRZWNER_PRESNATN_DE")),
        "url": (it.get("PBLANC_URL") or it.get("HMPG_ADRES") or "").strip() or None,
        "raw": json.dumps(it, ensure_ascii=False), "source": "applyhome",
        "category": (it.get("HOUSE_DTL_SECD_NM") or it.get("HOUSE_SECD_NM") or "").strip() or None, "status": None,
        "contract_start": re_store.to_date(it.get("CNTRCT_CNCLS_BGNDE")),
        "contract_end": re_store.to_date(it.get("CNTRCT_CNCLS_ENDDE")),
        "move_in_ym": (str(it.get("MVN_PREARNGE_YM") or "").strip() or None),
        "builder": (it.get("CNSTRCT_ENTRPS_NM") or it.get("BSNS_MBY_NM") or "").strip() or None,
        "house_manage_no": hmn, "pblanc_no": pn, "op": op,
    }


def model_rows(notice_id: str, items: list[dict], at: str) -> list[tuple]:
    out = []
    for it in items:
        ty = str(it.get("HOUSE_TY") or it.get("TP") or "").strip()
        area = re_store.to_float(it.get("SUPLY_AR") or it.get("EXCLUSE_AR"))
        special = re_store.to_int(it.get("SPSPLY_HSHLDCO"))
        amount = re_store.to_int(it.get("LTTOT_TOP_AMOUNT") or it.get("SUPLY_AMOUNT"))
        out.append((notice_id, str(it.get("MODEL_NO") or ""), ty, area, re_store.to_int(it.get("SUPLY_HSHLDCO")), special, amount,
                    json.dumps(it, ensure_ascii=False), at))
    return out


def cmpet_rows(notice_id: str, items: list[dict], at: str) -> list[tuple]:
    out = []
    for it in items:
        out.append((notice_id, str(it.get("MODEL_NO") or ""), str(it.get("HOUSE_TY") or ""),
                    str(it.get("SUBSCRPT_RANK_CODE") or it.get("SPSPLY_KND_NM") or it.get("RESIDNT_PRIOR_SENM")
                        or it.get("REMNDR_HSHLD_PBLANC_TYCD") or ""),
                    str(it.get("RESIDE_SENM") or it.get("RESIDE_SECD") or ""),
                    re_store.to_int(it.get("SUPLY_HSHLDCO")), re_store.to_int(it.get("REQ_CNT")),
                    str(it.get("CMPET_RATE") or "").strip() or None, json.dumps(it, ensure_ascii=False), at))
    return out


def score_rows(notice_id: str, items: list[dict], at: str) -> list[tuple]:
    return [(notice_id, str(it.get("MODEL_NO") or ""), str(it.get("HOUSE_TY") or ""),
             str(it.get("RESIDE_SENM") or it.get("RESIDE_SECD") or ""), re_store.to_float(it.get("LWET_SCORE")),
             re_store.to_float(it.get("TOP_SCORE")), re_store.to_float(it.get("AVRG_SCORE")),
             json.dumps(it, ensure_ascii=False), at) for it in items]


# ───────────────────────── 한국은행 기준금리 (웹 표) ─────────────────────────

BOK_URL = "https://www.bok.or.kr/portal/singl/baseRate/list.do?dataSeCd=01&menuNo=200643"
_TR = re.compile(r"<tr>\s*<td[^>]*>\s*(\d{4})\s*</td>\s*<td[^>]*>\s*(\d{1,2})월\s*(\d{1,2})일\s*</td>\s*<td[^>]*>\s*([\d.]+)\s*</td>",
                 re.S)


def bok_base_rate(c: httpx.Client) -> list[tuple[str, float]]:
    r = _get(c, BOK_URL)
    if r.status_code != 200:
        raise rtms.RtmsError(f"한국은행 페이지 HTTP {r.status_code}")
    rows = [(f"{y}-{int(m):02d}-{int(d):02d}", float(v)) for y, m, d, v in _TR.findall(r.text)]
    if not rows:
        raise rtms.RtmsError("한국은행 기준금리 표를 찾지 못했습니다 (페이지 구조가 바뀌었을 수 있음).")
    return rows


# ───────────────────────── 한국은행 ECOS (통계 API) ─────────────────────────

ECOS = "https://ecos.bok.or.kr/api/StatisticSearch"


def ecos_key() -> tuple[str, bool]:
    """(키, 공개 sample 키 여부). sample 키는 요청 한 번에 10건까지만 준다."""
    k = rtms.env_value("ECOS_API_KEY")
    return (k, False) if k else ("sample", True)


def ecos_series(c: httpx.Client, stat: str, item: str, cycle: str, start: str, end: str, delay: float = 0.4,
                max_calls: int = 12) -> list[dict]:
    """월 단위(YYYYMM) start~end 값 [{TIME, DATA_VALUE, ITEM_NAME1, UNIT_NAME, STAT_NAME}]."""
    key, sample = ecos_key()
    out: list[dict] = []
    windows: list[tuple[str, str]] = []
    if sample:  # 10개월씩 끊어 부른다
        s = start
        while s <= end and len(windows) < max_calls:
            e = min(re_store.shift_ymd(s, 9), end)
            windows.append((s, e))
            s = re_store.shift_ymd(e, 1)
    else:
        windows.append((start, end))
    for i, (s, e) in enumerate(windows):
        if i:
            time.sleep(delay)
        n = 10 if sample else 1000
        r = _get(c, f"{ECOS}/{key}/json/kr/1/{n}/{stat}/{cycle}/{s}/{e}/{item}")
        if r.status_code != 200:
            raise rtms.RtmsError(f"ECOS HTTP {r.status_code}")
        d = r.json()
        if "StatisticSearch" in d:
            out.extend(d["StatisticSearch"].get("row") or [])
            continue
        res = d.get("RESULT") or {}
        code = str(res.get("CODE") or "")
        if code == "INFO-200":  # 해당 데이터 없음
            continue
        if code.startswith("INFO-1") or code in ("ERROR-300", "ERROR-301"):
            raise rtms.NotRegistered("ECOS 인증키가 맞지 않습니다.")
        raise rtms.RtmsError(f"ECOS 오류 {code} {str(res.get('MESSAGE') or '')[:80]}")
    return out


# ───────────────────────── LH 청약플러스 공고 목록 (웹 표) ─────────────────────────

LH_LIST = "https://apply.lh.or.kr/lhapply/apply/wt/wrtanc/selectWrtancList.do"
LH_INFO = "https://apply.lh.or.kr/lhapply/apply/wt/wrtanc/selectWrtancInfo.do"
LH_MENUS = {"1026": "임대주택", "1027": "분양주택"}
_LH_ROW = re.compile(r"<tr>(.*?)</tr>", re.S)
_TAG = re.compile(r"<[^>]+>")


def _txt(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(_TAG.sub(" ", s))).strip()


def lh_notices(c: httpx.Client, delay: float = 1.0) -> list[dict]:
    """LH 청약플러스 공고 목록 1쪽(최대 50건)씩, 임대·분양 두 메뉴. 로그인 없는 공개 목록만 읽는다."""
    out: list[dict] = []
    for i, (mi, menu) in enumerate(LH_MENUS.items()):
        if i:
            time.sleep(delay)
        r = _get(c, LH_LIST, params={"mi": mi})
        if r.status_code != 200:
            raise rtms.RtmsError(f"LH 목록 HTTP {r.status_code}")
        body = r.text
        n = 0
        for tr in _LH_ROW.findall(body):
            if "wrtancInfoBtn" not in tr:
                continue
            m = re.search(r'data-id1="([^"]*)"\s+data-id2="([^"]*)"\s+data-id3="([^"]*)"\s+data-id4="([^"]*)"', tr)
            if not m:
                continue
            pan_id, sys_cd, upp, ais = m.groups()
            tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
            if len(tds) < 8:
                continue
            title_html = tds[2]
            title = _txt(re.sub(r"<em[^>]*>.*?</em>", "", title_html, flags=re.S))
            cat, region_txt = _txt(tds[1]), _txt(tds[3])
            posted, deadline, status = re_store.to_date(_txt(tds[5])), re_store.to_date(_txt(tds[6])), _txt(tds[7])
            sido = re_store.sido_of(region_txt)
            url = (f"{LH_INFO}?panId={pan_id}&ccrCnntSysDsCd={sys_cd}&uppAisTpCd={upp}&aisTpCd={ais}&mi={mi}")
            out.append({
                "notice_id": f"LH-{pan_id}", "name": title, "house_type": "LH", "address": region_txt,
                "lawd_cd": re_store.lawd_from_address(region_txt)[0], "region": sido, "households": None,
                "notice_date": posted, "receipt_start": None, "receipt_end": deadline, "winner_date": None, "url": url,
                "raw": json.dumps({"panId": pan_id, "ccrCnntSysDsCd": sys_cd, "uppAisTpCd": upp, "aisTpCd": ais, "menu": menu,
                                   "type": cat, "region": region_txt, "posted": posted, "deadline": deadline, "status": status},
                                  ensure_ascii=False),
                "source": "lh", "category": f"{menu} · {cat}" if cat else menu, "status": status, "contract_start": None,
                "contract_end": None, "move_in_ym": None, "builder": "LH", "house_manage_no": pan_id, "pblanc_no": None,
                "op": f"lh:{mi}",
            })
            n += 1
        log.info("✓ LH 공고 %s %d건", menu, n)
    return out


def months_back(n: int) -> tuple[str, str]:
    """(n 개월 전 YYYYMM, 지난달 YYYYMM) — 월별 통계는 보통 지난달까지 나온다."""
    end = re_store.shift_ymd(re_store.this_ymd(), -1)
    return re_store.shift_ymd(end, -(max(1, n) - 1)), end


def today_minus(days: int) -> str:
    return (date.today() - timedelta(days=days)).isoformat()
