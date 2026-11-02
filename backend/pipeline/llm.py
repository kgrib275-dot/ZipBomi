"""Gemini 호출. 키 로테이션(GeminiKeyPool)은 AI_NEWS 그대로이고, 프롬프트는 ZipGenie용이다."""
from __future__ import annotations

import json
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor

from . import gemini_keys

log = logging.getLogger(__name__)

CATEGORIES = ["시장·시세", "정책·세금·대출", "청약·분양·개발"]
KINDS = ["뉴스 분석", "정책 해설", "리포트", "인터뷰"]
AUDIENCES = ["무주택 실수요자", "1주택 갈아타기", "다주택·투자자", "임대인", "임차인(전월세)", "중개·실무자"]


class AllKeysExhausted(Exception):
    pass


class GeminiKeyPool:
    """키 배정·상태는 gemini_keys(프로세스 공유)가 맡는다 — 병렬 작업 여러 개가 같은 풀을 써도
    정상 키에 라운드로빈으로 나뉘고, 소진·무효 키는 함께 건너뛴다."""

    def __init__(self, keys: list[str], client_factory=gemini_keys.client):
        if not keys:
            raise ValueError("GeminiKeyPool requires at least one API key")
        self.client_factory = client_factory

    def workers(self, model: str, cap: int = 5) -> int:
        """병렬 작업 수 = 이 모델에 쓸 수 있는 키 수 (키 하나에 동시 요청이 몰리지 않게)."""
        return max(1, min(cap, gemini_keys.healthy_count(model)))

    def generate(self, model: str, prompt: str, json_mode: bool = False,
                 rounds: int = 3, backoff_seconds: float = 20.0, thinking_budget: int | None = None) -> str:
        """thinking_budget=0: 2.5 계열의 '생각' 토큰을 끈다 — 채점처럼 판단이 단순한 일에서 토큰을 크게 줄인다."""
        last_exc = None
        config: dict | None = {"response_mime_type": "application/json"} if json_mode else None
        if thinking_budget is not None:
            config = {**(config or {}), "thinking_config": {"thinking_budget": thinking_budget}}
        for rnd in range(rounds):
            if gemini_keys.exhausted_today(model):
                break  # 모든 키가 오늘 한도 소진·무효 — 기다려도 소용없다
            if rnd:
                time.sleep(backoff_seconds * rnd)  # 분당 제한만 걸린 경우
            for key in gemini_keys.healthy_keys(model):
                client = self.client_factory(key)
                try:
                    resp = client.models.generate_content(model=model, contents=prompt, config=config)
                    gemini_keys.report_success(model, key)
                    return resp.text
                except Exception as exc:  # noqa: BLE001 - any provider error should rotate
                    last_exc = exc
                    gemini_keys.report_error(model, key, exc)
            log.warning("Gemini 정상 키 모두 실패 (%d/%d회차): %s", rnd + 1, rounds, str(last_exc)[:120])
        raise AllKeysExhausted(f"no usable Gemini key for {model}") from last_exc


class ClaudePool:
    """GeminiKeyPool 과 같은 모양(generate·workers)으로 Claude 를 부른다 — 채점·노트 초안·주간 흐름 코드를 그대로 쓰려고.
    model 인자(Gemini 모델 이름)는 무시하고 관리 화면에서 고른 Claude 모델을 쓴다.
    thinking_budget=0(채점처럼 단순한 일) → effort low."""

    def workers(self, model: str, cap: int = 5) -> int:
        return min(cap, 3)  # Claude 는 키 하나 — 동시 요청은 조금만

    def generate(self, model: str, prompt: str, json_mode: bool = False, rounds: int = 3,
                 backoff_seconds: float = 20.0, thinking_budget: int | None = None) -> str:
        from . import claude_llm
        try:
            return claude_llm.generate(prompt, json_mode=json_mode, effort="low" if thinking_budget == 0 else "medium")
        except claude_llm.ClaudeError as e:
            log.warning("Claude 호출 실패: %s", e)
            raise AllKeysExhausted(str(e)) from e


def pool_from_env() -> GeminiKeyPool | ClaudePool | None:
    """관리 > AI 모델 설정에서 Claude 를 골랐고 키가 있으면 Claude, 아니면 Gemini 키 풀."""
    from . import claude_llm
    if claude_llm.provider() == "claude":
        return ClaudePool()
    keys = [k.strip() for k in os.environ.get("GEMINI_API_KEYS", "").split(",") if k.strip()]
    return GeminiKeyPool(keys) if keys else None


def provider_name() -> str:
    """로그·경보 문구용 공급자 이름 ('Claude'/'Gemini') — 함수 이름은 그대로 두고 문구만 실제 공급자에 맞춘다."""
    from . import claude_llm
    return "Claude" if claude_llm.provider() == "claude" else "Gemini"


def _parse_json(raw: str, kind: type):
    pattern = r"\[.*\]" if kind is list else r"\{.*\}"
    match = re.search(pattern, raw, re.DOTALL)
    data = json.loads(match.group(0) if match else raw)
    if not isinstance(data, kind):
        raise TypeError(f"expected {kind.__name__}")
    return data


# ───────────────────────── 1) 수집 기사 부동산 관련도 채점 ─────────────────────────

SCORE_PROMPT = """너는 한국 부동산을 다루는 큐레이션 매체의 에디터다.
독자는 내 집 마련을 준비하는 실수요자와 투자자이고, 관심사는 매매·전월세 시세와 거래량, 지역별 동향,
부동산 정책·세금·대출 규제, 청약·분양 일정, 재건축·재개발과 교통·개발 호재다.
분양 광고성 홍보, 연예인 매입 가십, 해외 부동산 단신, 근거 없는 전망은 낮게 본다.

아래 기사 각각(i=번호, t=제목, e=발췌)에 대해
- k: 한국어 한 문장 요약, 60자 이내 (없는 내용 지어내지 말 것)
- s: 실수요자·투자자에게 '깊게 읽고 노트로 남길 가치' 1~5점 (5=시세·거래 수치, 정책 조건·시행일, 청약·공급 일정이 구체적이고 결정에 바로 쓰임)
를 매겨 모든 기사에 대해 [{{"i": 0, "s": 3, "k": "..."}}] JSON 배열로만 답하라.

기사 목록:
{articles_json}
"""


EXCERPT_CHARS = 240  # 채점용 발췌 길이 — 제목과 첫 두세 문장이면 관련도 판단에 충분하다


def _score_batch(batch, pool: GeminiKeyPool, model: str, split: bool = True) -> tuple[int, int, int]:
    """(채점 건수, 응답 파싱 실패로 못 매긴 건수, 호출 자체가 실패한 건수).
    세 값을 따로 세는 이유: 수집 작업 경고에서 '한도 소진'과 '응답 파싱 실패'를 구분해 보여 주기 위해."""
    # URL(평균 100자 안팎)을 입력·출력에 두 번 싣지 않고 번호로 주고받는다.
    articles_json = json.dumps(
        [{"i": n, "t": it.title, "e": " ".join(it.excerpt.split())[:EXCERPT_CHARS]} for n, it in enumerate(batch)],
        ensure_ascii=False, separators=(",", ":"))
    try:
        raw = pool.generate(model, SCORE_PROMPT.format(articles_json=articles_json), json_mode=True, thinking_budget=0)
    except AllKeysExhausted:
        return 0, 0, len(batch)  # 남은 기사는 다음 수집 채점 요청에 함께 실린다 (jobs.pending_items)
    try:
        by_i = {int(r["i"]): r for r in _parse_json(raw, list) if str(r.get("i", "")).isdigit()}
    except (json.JSONDecodeError, TypeError, KeyError, ValueError, AttributeError) as e:
        # 원인을 로그에서 볼 수 있게 응답 앞부분을 남긴다 (긴 배열이 중간에 잘리거나 설명문이 섞인 경우가 대부분).
        log.warning("%s 채점 배치 파싱 실패 (%d건): %s · 응답 앞부분 %r", provider_name(), len(batch), e, raw[:200])
        if split and len(batch) > 1:
            # 반으로 나눠 한 번만 다시 요청한다(각각 새 호출) — 출력이 짧아지면 잘림·형식 오류가 대개 사라진다.
            mid = len(batch) // 2
            a = _score_batch(batch[:mid], pool, model, split=False)
            b = _score_batch(batch[mid:], pool, model, split=False)
            return a[0] + b[0], a[1] + b[1], a[2] + b[2]
        log.warning("채점 배치 %d건 건너뜀 (다음 수집 때 다시 채점)", len(batch))  # 배치 하나가 깨져도 나머지는 계속 (AI_NEWS와 같은 방침)
        return 0, len(batch), 0
    scored = 0
    for n, it in enumerate(batch):
        r = by_i.get(n)
        if r:
            it.summary_ko = str(r.get("k", ""))
            it.llm_score = max(0, min(5, int(r.get("s", 0) or 0)))
            scored += 1
    log.info("채점 묶음 완료: %d/%d건", scored, len(batch))
    return scored, 0, 0


def score_items(items, pool: GeminiKeyPool, model: str, batch_size: int = 150, stats: dict | None = None) -> int:
    """items(Item 목록)에 summary_ko/llm_score를 채운다. 채점된 건수를 반환. 모든 키가 소진되면 AllKeysExhausted.
    stats(dict)를 주면 'unparsed'(파싱 실패 건수)·'failed'(호출 실패 건수)를 채운다 — 작업 경고 문구용.

    무료 등급은 요청 '횟수'가 하루 20회 안팎이라, 수집 한 번의 기사를 요청 한 번에 묶는다(batch_size건까지).
    그보다 많을 때만 나눠서 정상 키 수만큼 병렬로 보낸다."""
    batches = [items[i:i + batch_size] for i in range(0, len(items), batch_size)]
    if not batches:
        return 0
    with ThreadPoolExecutor(max_workers=pool.workers(model)) as ex:
        results = list(ex.map(lambda b: _score_batch(b, pool, model), batches))
    scored = sum(r[0] for r in results)
    unparsed, failed = sum(r[1] for r in results), sum(r[2] for r in results)
    if stats is not None:
        stats.update(unparsed=unparsed, failed=failed)
    # 호출이 전부 실패했거나(Claude 포함) Gemini 키가 오늘 모두 소진된 경우 — 파싱 실패는 한도 소진이 아니므로 올리지 않는다
    if not scored and ((failed and not unparsed) or gemini_keys.exhausted_today(model)):
        raise AllKeysExhausted(f"no usable {provider_name()} key for {model}")
    return scored


# ───────────────────────── 2) 노트 초안 작성 ─────────────────────────

NOTE_PROMPT = """너는 ZipGenie(집지니)의 에디터다. 아래 원문을 깊게 읽고, 내 집 마련을 준비하는 실수요자와
부동산 투자자를 위한 노트를 한국어로 쓴다. 원문에 없는 수치·사실·인용을 만들어 내지 말 것. 원문 정보가 부족하면 부족한
대로 짧게 쓰고, 추정은 '~로 보입니다'처럼 구분한다. 존댓말(~습니다)로 쓴다.

JSON 객체 하나로만 답하라:
{{
  "title": "핵심어: 한국어 명사구 한 줄 (콜론 뒤 45자 이내, '~하는 이유/구조/영향'처럼 끝내고 마침표·'~합니다' 금지. 예: '스트레스 DSR 3단계: 수도권 주담대 한도가 줄어드는 구조')",
  "category": {categories} 중 하나,
  "kind": {kinds} 중 하나,
  "audiences": {audiences} 중 2~3개 배열,
  "audience": {types} 중 이 노트가 직접 영향을 주는 유형 키 1~4개 배열 (first_home=무주택(첫 집), upgrade=1주택 갈아타기, tenant=임차인(전월세), investor=투자),
  "regions": 원문에 나온 시군구 이름 배열, 최대 5개 ('서울 마포구'·'성남시 분당구'처럼 시도나 시를 붙여서. 전국 단위 소식이면 빈 배열, 시군구가 아닌 '수도권'·'서울' 같은 넓은 이름은 넣지 말 것),
  "tags": 짧은 한국어 태그 2~3개 배열 (# 없이),
  "summary": "카드용 요약 2문장, 150자 이내. 무엇이 바뀌었고(시세·정책·공급) 숫자·시행 시점이 무엇인지. '본 노트는'으로 시작하지 말 것",
  "body": "마크다운 본문, 공백 포함 1,400자 이내(3분 안에 읽히게). 문장은 짧게, 같은 말을 반복하지 말 것. 반드시 다음 소제목을 순서대로: '### 요약'(2문장), '### 핵심 포인트'(- 불릿 3개, 각 한 문장), '### 시장·정책 디테일'(- 불릿 2~3개: 지역·가격·조건·시행일, 수치에는 기준 시점), '### 나에게 미치는 영향' — 이 아래에 유형별 소제목 네 개를 이 순서·이 이름 그대로: '#### 무주택', '#### 갈아타기', '#### 임차인', '#### 투자'. 각 소제목 아래 번호 목록 1~3줄로 그 유형이 확인·실행할 것을 쓰고, 영향이 거의 없으면 '- 직접 영향은 크지 않습니다.' 한 줄만"
}}

출처: {source}
제목: {title}
URL: {url}
원문:
{text}
"""


def write_note(article: dict, text: str, pool: GeminiKeyPool, model: str) -> dict:
    prompt = NOTE_PROMPT.format(
        categories=json.dumps(CATEGORIES, ensure_ascii=False), kinds=json.dumps(KINDS, ensure_ascii=False),
        audiences=json.dumps(AUDIENCES, ensure_ascii=False),
        types=json.dumps(["first_home", "upgrade", "tenant", "investor"]),
        source=article["source"], title=article["title"], url=article["url"], text=text,
    )
    data = _parse_json(pool.generate(model, prompt, json_mode=True), dict)
    category = data.get("category") if data.get("category") in CATEGORIES else CATEGORIES[1]
    kind = data.get("kind") if data.get("kind") in KINDS else KINDS[0]
    from . import profile  # 시군구 이름 → 코드, 유형 키 정리 (응답에 없으면 키워드·대상 독자 글자로 채운다)
    audiences = ",".join(a for a in data.get("audiences", []) if a in AUDIENCES)
    body = str(data.get("body", "")).strip()
    regions = profile.regions_from_names(data.get("regions"))
    if not isinstance(data.get("regions"), list):
        regions = profile.regions_from_text(f"{data.get('title', '')} {data.get('summary', '')}", body)
    audience = profile.audience_clean(data.get("audience")) or profile.audience_from_text(audiences)
    return {
        "title": str(data.get("title") or article["title"]).strip(),
        "category": category,
        "kind": kind,
        "audiences": audiences,
        "regions": json.dumps(regions),
        "audience": json.dumps(audience),
        "tags": ",".join(str(t).lstrip("#").strip() for t in data.get("tags", []) if str(t).strip()),
        "summary": str(data.get("summary", "")).strip(),
        "body": body,
    }


# ───────────────────────── 3) 주간 부동산 흐름 ─────────────────────────

WEEKLY_PROMPT = """너는 ZipGenie의 편집장이다. 이번 주({range}) 게시된 노트들을 읽고
'이번 주 부동산 흐름'을 쓴다. 노트 목록에 없는 사실을 만들지 말 것. 존댓말(~습니다)로 쓴다.
{prev}
JSON 객체 하나로만 답하라:
{{
  "headline_em": "흐름을 요약하는 앞 구절 (강조 표시됨, 15자 내외)",
  "headline": "이어지는 뒷 구절: 콜론 뒤에 어느 지역·시장·정책에서 무엇이 움직였는지",
  "body": "4~5문장. 지난주 대비 관심이 어디서 어디로 옮겨 갔는지(시세·정책·청약), 대표 지역·사례 묶음, 반대 신호까지. 핵심 구절 2개는 **굵게**"
}}

노트 목록:
{notes_json}
"""


def write_weekly(notes: list[dict], range_: str, prev_headline: str, pool: GeminiKeyPool, model: str) -> dict:
    prev = f"지난주 흐름은 '{prev_headline}'였다. 이와 비교해 무엇이 이동했는지 드러내라.\n" if prev_headline else ""
    notes_json = json.dumps(
        [{"title": n["title"], "category": n["category"], "summary": n["summary"]} for n in notes],
        ensure_ascii=False,
    )
    data = _parse_json(
        pool.generate(model, WEEKLY_PROMPT.format(range=range_, prev=prev, notes_json=notes_json), json_mode=True),
        dict,
    )
    return {
        # 제목 줄에는 굵게 표시가 필요 없다 — 모델이 붙인 ** 를 지운다(실측).
        "headline_em": str(data.get("headline_em", "")).replace("**", "").strip(),
        # 모델이 앞 구절과 이어 쓰며 콜론으로 시작하는 경우가 있다(실측) — 앞 구두점 제거.
        "headline": str(data.get("headline", "")).replace("**", "").strip().lstrip(":·- ").strip(),
        "body": str(data.get("body", "")).strip(),
    }
