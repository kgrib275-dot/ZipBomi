// 의미 검색·질문하기 — 벡터화 현황, 검색 테스트, 공개 '질문하기' 설정 (app_pages/admin/search.py).
import { useEffect, useState } from "react";
import { Alert, Metric, useLoad } from "../../components/ui";
import { A, AdminHead, Check, DataTable, Field, Row, asArray, bool, isObj, num, pick, str, useAct } from "./common";
import { JobStatus, StartJob, useJobs } from "./JobRunner";

// free_credits: 구독자가 가입(확인) 때 한 번 받는 무료 질문 횟수 — 예전 free_daily(하루 단위)는 더 쓰지 않는다
type Ask = { enabled: boolean; free_credits: number; member_daily: number; per_ip_daily: number; global_daily: number; plan_price: string; web_search: boolean };

export default function Search() {
  const { finished } = useJobs();
  const act = useAct();
  const { data, error, reload } = useLoad(() => A.get<Row>("ask-settings"), [finished]);
  const cfg = data && isObj(data.ask) ? (data.ask as Row) : data || {};
  // 벡터화 현황은 GET /admin/search 에 있다 (2026-11-03 — ask-settings 에서 찾아 늘 0/0 이었다)
  const status = useLoad(() => A.get<Row>("search"), [finished]);
  const emb = status.data && isObj(status.data.embeddings) ? (status.data.embeddings as Row) : {};
  const hasKeys = pick(status.data, "has_keys") ?? pick(data, "has_api_keys", "has_keys", "gemini_ok");
  const [f, setF] = useState<Ask>({ enabled: true, free_credits: 3, member_daily: 30, per_ip_daily: 10, global_daily: 300, plan_price: "", web_search: true });
  useEffect(() => {
    if (!data) return;
    setF({ enabled: bool(cfg.enabled), free_credits: num(cfg.free_credits, 3), member_daily: num(cfg.member_daily), per_ip_daily: num(cfg.per_ip_daily), global_daily: num(cfg.global_daily, 300), plan_price: str(cfg.plan_price), web_search: bool(cfg.web_search) });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);
  const [q, setQ] = useState("");
  const [res, setRes] = useState<Row | null>(null);
  const [busy, setBusy] = useState(false);
  const search = async () => {
    if (!q.trim()) return;
    setBusy(true);
    setRes((await act(() => A.post<Row>("search", { q: q.trim() }))) || null);
    setBusy(false);
  };
  const notes = asArray(res?.notes);
  const articles = asArray(res?.articles);
  const results = res ? (notes.length || articles.length ? [
    ...notes.map((r) => ({ 유사도: Math.round(num(r.similarity) * 1000) / 1000, 종류: "노트", 제목: str(r.title) })),
    ...articles.map((r) => ({ 유사도: Math.round(num(r.similarity) * 1000) / 1000, 종류: str(r.source), 제목: str(r.title) })),
  ] : asArray(res, "results", "rows")) : [];

  return (
    <div>
      <AdminHead title="의미 검색·질문하기" note="게시 노트와 3점 이상 기사를 Gemini 임베딩으로 벡터화해 노트 의미 검색과 '질문하기'에 씁니다." />
      {error && <Alert kind="err">{error}</Alert>}
      <div className="metrics" style={{ alignItems: "flex-end" }}>
        <Metric k="벡터화된 노트" v={`${num(emb.notes)} / ${num(emb.notes_total)}`} />
        <Metric k="벡터화된 기사" v={`${num(emb.articles)} / ${num(emb.articles_total)}`} />
        <StartJob kind="vectorize" text="지금 벡터화" primary />
      </div>
      <JobStatus />
      <p className="caption">노트를 게시하면 자동으로 벡터화가 시작됩니다. 기사는 배치 스케줄의 '벡터화'로 주기적으로 처리하세요.</p>

      <h3>검색 테스트</h3>
      <div className="inline">
        <Field label="질문"><input type="text" placeholder="예: 강남 재건축 초과이익환수 영향" value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && search()} /></Field>
        <button className="btn" disabled={busy || !q.trim()} onClick={search}>{busy ? "검색 중…" : "검색"}</button>
      </div>
      {res && (
        <div style={{ marginTop: 10 }}>
          {pick(res, "sufficient", "is_sufficient") !== undefined && (
            <p className="caption">근거 충분 여부(최고 유사도 ≥ {str(pick(res, "min_similarity")) || "기준"}): {bool(pick(res, "sufficient", "is_sufficient")) ? "충분" : "부족 — 질문하기에서 웹 검색 버튼이 뜹니다"}</p>
          )}
          <DataTable rows={results} />
        </div>
      )}

      <h3 style={{ marginTop: 20 }}>공개 '질문하기' 설정</h3>
      <Check label="사용" checked={f.enabled} onChange={(v) => setF({ ...f, enabled: v })} />
      <div className="row4" style={{ marginTop: 10 }}>
        {/* 2026-11-03: 보미AI 횟수는 로그인 계정 기준(계정마다 처음 1회) — 예전 '구독자 무료 횟수(3)' 칸은 실제 한도에 쓰이지 않아 헷갈렸다 */}
        <Field label="보미AI 무료 횟수"><p className="caption" style={{ margin: 0 }}>로그인 계정마다 처음 1회예요. 더 쓰게 하려면 관리 &gt; 회원 계정에서 +5·+30 으로 늘려 주세요.</p></Field>
        <Field label="월 구독 하루 질문 수"><input type="number" min={1} max={500} value={f.member_daily} onChange={(e) => setF({ ...f, member_daily: Number(e.target.value) })} /></Field>
        <Field label="무료 IP당 하루 질문 수"><input type="number" min={1} max={1000} title="쿠키를 지워 한도를 다시 받는 것을 막는 남용 상한. 월 구독자에게는 적용하지 않습니다." value={f.per_ip_daily} onChange={(e) => setF({ ...f, per_ip_daily: Number(e.target.value) })} /></Field>
        <Field label="전체 하루 질문 수"><input type="number" min={1} max={100000} title="Gemini 키 한도 보호. 관리자 제외 모든 질문의 합계" value={f.global_daily} onChange={(e) => setF({ ...f, global_daily: Number(e.target.value) })} /></Field>
      </div>
      <Field label="월 구독 가격 안내 (비우면 '담당자가 안내')"><input type="text" maxLength={80} placeholder="월 9,900원" value={f.plan_price} onChange={(e) => setF({ ...f, plan_price: e.target.value })} /></Field>
      <Check label="근거가 약할 때 '웹 검색으로 다시 답하기' 버튼 표시" checked={f.web_search} onChange={(v) => setF({ ...f, web_search: v })} />
      <div style={{ marginTop: 12 }}>
        <button className="btn primary" onClick={async () => { await act(() => A.put("ask-settings", { ...f, plan_price: f.plan_price.trim() }), "저장했습니다."); reload(); }}>저장</button>
      </div>
      {hasKeys === false && <Alert kind="warn">GEMINI_API_KEYS가 없어 의미 검색과 질문하기를 쓸 수 없습니다.</Alert>}
    </div>
  );
}
