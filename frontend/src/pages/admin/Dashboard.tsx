// 대시보드 — 숫자, Gemini/SMTP/배치 배지, Gemini 키 상태, 작업 실행 버튼, 실행 기록 (app_pages/admin/dashboard.py).
import { useState } from "react";
import { Alert, Metric, useLoad } from "../../components/ui";
import { A, AdminHead, Badge, DataTable, Expander, Row, asArray, bool, isObj, num, pick, str, useAct, useToast } from "./common";
import { JobStatus, RunLogTable, StartJob, useJobs } from "./JobRunner";

const COUNT_LABELS: Record<string, string> = {
  articles: "수집 기사", candidates: "초안 후보 (3점↑)", drafts: "검토 대기 초안", published: "게시 노트", subscribers: "활성 구독자",
  contacts_open: "처리 안 한 문의", contacts: "전체 문의",
};
const JOBS: [string, string, boolean, (cfg: Row) => string][] = [
  ["collect", "수집 실행", true, () => "활성 소스 수집 → 중복 제거 → 키워드 필터 → 부동산 중요도 채점"],
  ["draft", "노트 초안 생성", false, (s) => `${str(s.min_score) || "3"}점 이상 후보 중 상위 ${str(s.per_run) || "?"}건의 원문을 읽고 초안 작성`],
  ["weekly", "지난주 흐름 생성", false, () => "지난주 게시 노트로 '이번 주 부동산 흐름' 작성"],
  ["newsletter", "뉴스레터 발송", false, () => "최신 주간 흐름 + 새 노트를 활성 구독자에게 발송"],
  ["vectorize", "벡터화", false, () => "게시 노트·기사 임베딩 (의미 검색·질문하기)"],
  ["report", "주간 PDF 만들기", false, () => "최신 주간 흐름으로 PDF 리포트 생성"],
  ["teams", "Teams 발송", false, () => "최신 흐름 + 새 노트를 Teams 채널에 카드로"],
];

export default function Dashboard() {
  const { finished } = useJobs();
  const { data, error, reload } = useLoad(() => A.get<Row>("dashboard"), [finished]);
  const d = data || {};
  const counts = isObj(d.counts) ? d.counts : {};
  const gemini = pick<unknown>(d, "gemini", "gemini_keys");
  const geminiRows = asArray(gemini, "rows", "keys", "status");
  const geminiOk = pick<unknown>(d, "llm_ok", "gemini_ok") ?? (isObj(gemini) ? pick(gemini, "configured", "ok") : geminiRows.length > 0);
  const llmName = str(pick(d, "llm_name")) || "Gemini";
  const smtpOk = bool(pick(d, "smtp_ok", "smtp", "mailer"));
  const scheduleOn = asArray<string | Row>(pick(d, "schedules_on", "schedule_on", "schedules", "enabled_jobs")).map((x) => (isObj(x) ? str(pick(x, "label", "name", "kind")) : String(x)));
  const schedule = isObj(d.schedule) ? (d.schedule as Record<string, Row>) : {};
  const drafting = isObj(schedule.drafting) ? schedule.drafting : isObj(d.drafting) ? (d.drafting as Row) : {};
  const runLogs = pick<unknown>(d, "run_logs", "logs");
  const lab = isObj(d.lab_metrics) ? d.lab_metrics : {};
  const labKpi = asArray<{ label: string; value: number }>(lab.kpi);
  const labFunnel = asArray<{ label: string; value: number }>(lab.funnel);

  return (
    <div>
      <AdminHead title="대시보드" note="수집 → 노트 초안 → 검토·게시 → 주간 흐름 → 뉴스레터 순서로 운영합니다." />
      {error && <Alert kind="err">{error}</Alert>}
      <div className="metrics">
        {Object.keys(COUNT_LABELS).filter((k) => k in counts).map((k) => <Metric key={k} k={COUNT_LABELS[k]} v={num(counts[k])} />)}
        {Object.entries(counts).filter(([k]) => !(k in COUNT_LABELS)).map(([k, v]) => <Metric key={k} k={k} v={str(v)} />)}
      </div>
      <div className="badges">
        {geminiOk !== undefined && (
          <Badge color={bool(geminiOk) ? "green" : "red"}>🤖 {bool(geminiOk) ? `${llmName} 연결됨` : `${llmName} 키 없음 — 채점·초안 불가`}</Badge>
        )}
        {pick(d, "smtp_ok", "smtp", "mailer") !== undefined && (
          <Badge color={smtpOk ? "green" : "orange"}>✉ {smtpOk ? "SMTP 설정됨" : "SMTP 미설정 — 뉴스레터 발송 불가"}</Badge>
        )}
        <Badge color="blue">🕒 자동 배치: {scheduleOn.length ? scheduleOn.join(", ") : "꺼짐"}</Badge>
      </div>

      <Expander title="🔑 Gemini 키 상태 (키별로 병렬 배정)">
        <p className="caption">
          키마다 다른 프로젝트라 하루 한도도 따로입니다. 작업은 정상 키 수만큼 병렬로 나눠 돌고, 한도를 다 쓴 키는 그 모델에서만 자정까지 쉽니다.
          상태는 이 앱이 실제로 호출하며 알게 된 값입니다.
        </p>
        <DataTable rows={geminiRows} empty="등록된 키가 없습니다." />
      </Expander>

      <h3 style={{ margin: "18px 0 8px" }}>지금 실행</h3>
      <JobStatus />
      <div className="jobs-grid">
        {JOBS.map(([kind, text, primary, desc]) => (
          <div key={kind}>
            <StartJob kind={kind} text={text} primary={primary} block onStarted={reload} />
            <div className="caption">{desc(drafting)}</div>
          </div>
        ))}
      </div>

      <h3 style={{ margin: "18px 0 8px" }}>지난 기사로 채우기</h3>
      <Backfill onStarted={reload} />

      <h3 style={{ margin: "18px 0 8px" }}>데이터 랩 운영 지표 <span className="caption">· 공개 데이터 랩에서 옮겨 온 숫자 {str(lab.asof) && `(기준 ${str(lab.asof)})`}</span></h3>
      <div className="metrics">
        {labKpi.map((x) => <Metric key={x.label} k={x.label} v={num(x.value).toLocaleString()} />)}
      </div>
      {labFunnel.length > 0 && (
        <Expander title="수집 퍼널 — 원문이 노트가 되기까지 (누적)">
          <DataTable rows={labFunnel.map((x, i) => ({
            단계: x.label, 건수: num(x.value).toLocaleString(),
            "앞 단계 대비": i && num(labFunnel[i - 1].value) ? `${((num(x.value) / num(labFunnel[i - 1].value)) * 100).toFixed(1)}%` : "",
          }))} />
        </Expander>
      )}

      <h3 style={{ margin: "18px 0 8px" }}>실행 기록</h3>
      <RunLogTable rows={runLogs !== undefined ? asArray(runLogs) : undefined} />
    </div>
  );
}

/** 노트 초안 채우기(분류별 고르게, 노트 날짜 = 원문 발행일) + 지난 N주 주간 흐름 초안. 미리보기는 LLM 호출 없이 고를 기사만 센다. */
function Backfill({ onStarted }: { onStarted: () => void }) {
  const act = useAct();
  const toast = useToast();
  const [total, setTotal] = useState(30);
  const [perCat, setPerCat] = useState(8);
  const [weeks, setWeeks] = useState(3);
  const [preview, setPreview] = useState<Row | null>(null);
  const counts = isObj(preview?.counts) ? (preview!.counts as Record<string, number>) : {};
  const fallback = isObj(preview?.fallback) ? (preview!.fallback as Record<string, number>) : {};
  return (
    <div className="jobs-grid">
      <div>
        <div className="btn-row" style={{ gap: 6, marginBottom: 6 }}>
          <label className="caption">합계 <input type="number" min={1} max={100} value={total} onChange={(e) => setTotal(Number(e.target.value) || 30)} style={{ width: 64 }} /></label>
          <label className="caption">분류별 최소 <input type="number" min={0} max={50} value={perCat} onChange={(e) => setPerCat(Number(e.target.value) || 0)} style={{ width: 56 }} /></label>
          <button className="btn sm" onClick={async () => setPreview((await act(() => A.post<Row>("notes/backfill", { dry_run: true, total, per_category_min: perCat }))) || null)}>미리보기</button>
        </div>
        <button className="btn block" onClick={async () => {
          if (!window.confirm(`노트 초안 ${total}편을 지난 기사로 채울까요? (분류별 최소 ${perCat}편, 검토 큐에 초안으로 들어갑니다)`)) return;
          const r = await act(() => A.post<Row>("notes/backfill", { total, per_category_min: perCat }));
          if (r) { toast(str(r.message), bool(r.started) ? "ok" : "err"); onStarted(); }
        }}>노트 초안 채우기</button>
        <div className="caption">아직 노트가 없는 4점↑ 기사를 분류별로 고르게 골라 초안 작성 (모자란 분류는 3점까지). 노트 날짜 = 원문 발행일.</div>
        {preview && (
          <div className="caption" style={{ marginTop: 6 }}>
            미리보기: {Object.entries(counts).filter(([, n]) => n).map(([c, n]) => `${c} ${n}`).join(" · ") || "후보 없음"}
            {Object.keys(fallback).length > 0 && <> · 3점으로 채움: {Object.entries(fallback).map(([c, n]) => `${c} ${n}`).join(", ")}</>}
          </div>
        )}
      </div>
      <div>
        <div className="btn-row" style={{ gap: 6, marginBottom: 6 }}>
          <label className="caption">지난 <input type="number" min={1} max={12} value={weeks} onChange={(e) => setWeeks(Number(e.target.value) || 3)} style={{ width: 52 }} />주</label>
        </div>
        <button className="btn block" onClick={async () => {
          const r = await act(() => A.post<Row>("issues/backfill", { weeks }));
          if (r) { toast(str(r.message), bool(r.started) ? "ok" : "err"); onStarted(); }
        }}>지난 주간 흐름 초안 만들기</button>
        <div className="caption">주마다 그 주 날짜의 노트(초안 포함)로 흐름을 써서 초안으로 저장합니다. 이미 있는 주·노트 없는 주는 건너뜁니다.</div>
      </div>
    </div>
  );
}
