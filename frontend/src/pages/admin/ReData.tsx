// 부동산 데이터 — 데이터셋별 상태(키 없음/활용신청 필요/정상/꺼짐)·저장 행 수·적용 범위·마지막 실행/오류, 켜기/끄기, 과거 채우기 개월 수, 지금 실행.
// 백엔드: api/routers/admin_redata.py (GET/PUT admin/redata), 실행은 배치 작업 re_data (POST admin/jobs/re_data {only:[키]}).
// 실거래가 CSV 자동 다운로드(pipeline/rt_download.py): 데이터셋별 출처(API/CSV)·오늘 받은 수/상한·마지막 창·마지막 오류, 'CSV 자동 다운로드 지금 실행' = {csv_only:true}.
import { useMemo, useState } from "react";
import { Alert, Metric, useLoad } from "../../components/ui";
import { A, AdminHead, Badge, Check, DataTable, Expander, Row, asArray, bool, num, str, useAct, usePaged, useRemembered } from "./common";
import { JobStatus, RunLogTable, StartJob, useJobs } from "./JobRunner";
import ReUpload from "./ReUpload";

// API 로 못 받는 상태 — 실거래가 데이터셋이면 파일 업로드로 채울 수 있다고 알려 준다
const CSV_HINT = new Set(["not_registered", "error", "no_key"]);

const COLORS: Record<string, "green" | "red" | "orange" | "blue"> = {
  ok: "green", no_key: "orange", not_registered: "red", error: "red", off: "blue", pending: "blue", limit: "orange",
};
const GROUPS: Record<string, string> = {
  rtms: "실거래가", applyhome: "청약홈", applyhome_sub: "청약홈", bok: "금리", ecos: "지표", lh: "LH",
};
const CSV_STATUS: Record<string, string> = { ok: "정상", empty: "자료 없음", error: "오류", limit: "한도", blocked: "차단됨", running: "진행 중" };
const ym = (v: unknown) => (str(v) ? `${str(v).slice(0, 4)}.${str(v).slice(4)}` : "");
const at = (v: unknown) => str(v).slice(0, 16).replace("T", " ");

function Months({ row, onSave }: { row: Row; onSave: (v: number) => void }) {
  const [v, setV] = useState(num(row.backfill_months, 24));
  return (
    <span style={{ display: "inline-flex", gap: 4, alignItems: "center" }} onClick={(e) => e.stopPropagation()}>
      <input type="number" min={1} max={120} value={v} style={{ width: 64 }} onChange={(e) => setV(Number(e.target.value))} aria-label="과거 채우기 개월" />
      {v !== num(row.backfill_months, 24) && <button className="btn sm" onClick={() => onSave(v)}>저장</button>}
    </span>
  );
}

export default function ReData() {
  const { finished } = useJobs();
  const act = useAct();
  const { data, error, reload } = useLoad(() => A.get<Row>("redata"), [finished]);
  const d = data || {};
  const all = asArray(d.datasets);
  const [grp, setGrp] = useRemembered<string>("grp", "");
  const rows = useMemo(() => all.filter((r) => !grp || GROUPS[str(r.group)] === grp), [all, grp]);
  const paged = usePaged("ds", rows, grp, 50);
  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    all.forEach((r) => (c[str(r.status_label)] = (c[str(r.status_label)] || 0) + 1));
    return c;
  }, [all]);
  const save = async (key: string, body: Row, msg: string) => {
    await act(() => A.put(`redata/${key}`, body), msg);
    reload();
  };
  const needApply = all.filter((r) => str(r.status) === "not_registered" || (str(r.status) === "no_key" && r.enabled));
  const sched = (d.schedule || {}) as Row;
  const csv = (d.csv || {}) as Row;

  return (
    <div>
      <AdminHead title="부동산 데이터" note="실거래가(매매·전월세)·청약 공고·경쟁률·기준금리·KB 가격지수를 공공 API·공개 자료에서 받아 로컬 DB 에 저장합니다. AI 를 쓰지 않습니다."
        right={<div className="btn-row"><StartJob kind="re_data" text="전체 지금 실행" primary /><StartJob kind="re_data" text="최근 달만 갱신" kwargs={{ backfill: false }} /></div>} />
      {error && <Alert kind="err">{error}</Alert>}
      <div className="metrics">
        <Metric k="공공데이터포털 키" v={bool(d.key_configured) ? "있음" : "없음"} />
        <Metric k="ECOS 키" v={bool(d.ecos_key) ? "있음" : "sample"} />
        <Metric k="데이터셋" v={all.length} />
        <Metric k="스케줄" v={bool(sched.enabled) ? asArray<string>(sched.times).join(", ") : "꺼짐"} />
        <Metric k="CSV 오늘 받은 수" v={`${num(csv.today)} / ${num(csv.cap, 60)}`} />
      </div>
      <div className="badges">
        {Object.entries(counts).map(([k, n]) => <span key={k} className="badge">{k} {n}</span>)}
      </div>
      {!bool(d.key_configured) && (
        <Alert kind="warn">
          🔑 <b>DATA_GO_KR_KEY</b> 가 없어 실거래가·청약홈 데이터셋은 '키 없음'으로 건너뜁니다. 공공데이터포털에서 일반 인증키를 받아 <code>backend/.env</code> 에
          <code> DATA_GO_KR_KEY=…</code> 로 넣으면 서버를 다시 시작하지 않아도 다음 실행부터 받습니다. 키 하나로 되지만 아래 API 마다 [활용신청]이 필요합니다.
        </Alert>
      )}
      {!!needApply.length && (
        <Expander title={`활용신청이 필요한 API ${needApply.length}개`} open={bool(d.key_configured)}>
          <ul style={{ margin: "6px 0 0 18px" }}>
            {needApply.filter((r) => str(r.data_url)).map((r) => (
              <li key={str(r.key)}><a href={str(r.data_url)} target="_blank" rel="noreferrer">{str(r.name)}</a> <span className="caption">{str(r.status_label)}</span></li>
            ))}
          </ul>
        </Expander>
      )}
      <JobStatus only={["re_data"]} />

      <div className="box" style={{ margin: "14px 0" }}>
        <div className="btn-row" style={{ justifyContent: "space-between", flexWrap: "wrap" }}>
          <div>
            <b>실거래가 CSV 자동 다운로드</b> <span className="caption">rt.molit.go.kr 조건별 자료제공</span>
            <div className="caption" style={{ maxWidth: 640 }}>
              API 로 못 받는 실거래가 데이터셋(키 없음·활용신청 필요·오류, 또는 설정 source: csv)은 배치가 CSV 를 직접 받아 넣습니다.
              매일 전국 × 최근 3달(데이터셋마다 3건) + 남은 몫으로 시도 × 1년 창 과거 채우기. 오늘 {num(csv.today)}건 / 우리 상한 {num(csv.cap, 60)}건
              (사이트 한도 하루 {num(csv.site_cap, 100)}건 — 나머지는 손으로 받을 몫). 요청 사이 5초 이상 쉽니다.
            </div>
          </div>
          <div className="btn-row">
            <StartJob kind="re_data" text="CSV 자동 다운로드 지금 실행" kwargs={{ csv_only: true }} primary disabled={!!csv.stopped} />
            <StartJob kind="re_data" text="오늘 계획만 보기" kwargs={{ dry_run: true }} />
          </div>
        </div>
        {!!str(csv.stopped) && (
          <Alert kind={bool(csv.blocked) ? "err" : "warn"}>
            {bool(csv.blocked) ? <b>{str(csv.blocked_label)} — </b> : <b>오늘 CSV 자동 다운로드 멈춤 — </b>}
            {str(csv.stopped)} <span className="caption">(내일 다시 시도합니다. 보안문자·차단 화면은 우회하지 않습니다.)</span>
          </Alert>
        )}
      </div>

      <div className="btn-row" style={{ margin: "16px 0 8px" }}>
        <h3 style={{ margin: 0 }}>데이터셋</h3>
        <select value={grp} onChange={(e) => setGrp(e.target.value)} aria-label="구분">
          <option value="">전체</option>
          {[...new Set(Object.values(GROUPS))].map((g) => <option key={g}>{g}</option>)}
        </select>
        {paged.sizeSel}
        <span className="caption">{paged.info}</span>
      </div>
      <DataTable
        rows={paged.shown}
        cols={["name", "status", "source", "enabled", "rows", "coverage", "last", "backfill_months", "calls", "run"]}
        labels={{ name: "데이터셋", status: "상태", source: "출처 / CSV", enabled: "켜기", rows: "저장 행", coverage: "적용 범위", last: "마지막 실행 / 메시지", backfill_months: "과거(개월)", calls: "오늘 호출", run: "" }}
        render={{
          name: (_, r) => (
            <div style={{ minWidth: 150 }}>
              <b>{str(r.name)}</b> <span className="caption">{GROUPS[str(r.group)] || str(r.group)}{r.needs_key ? " · 키" : " · 키 없이"}</span>
              <div className="caption" style={{ maxWidth: 320 }}>{str(r.desc)}</div>
            </div>
          ),
          status: (_, r) => (
            <span style={{ whiteSpace: "nowrap" }}>
              <Badge color={COLORS[str(r.status)] || "blue"}>{str(r.status_label)}</Badge>
              {str(r.status) === "not_registered" && !!str(r.data_url) && <div><a className="caption" href={str(r.data_url)} target="_blank" rel="noreferrer">활용신청 →</a></div>}
              {!!r.uploadable && CSV_HINT.has(str(r.status)) && <div><a className="caption" href="#re-upload">CSV로 올릴 수 있어요 ↓</a></div>}
            </span>
          ),
          source: (_, r) => {
            if (!r.source) return <span className="caption">-</span>;
            const c = (r.csv || {}) as Row;
            return (
              <div style={{ minWidth: 150, maxWidth: 260 }}>
                <Badge color={str(r.source) === "CSV" ? "orange" : "green"}>{str(r.source)}</Badge>
                {str(r.source_setting) !== "auto" && <span className="caption"> (설정 {str(r.source_setting)})</span>}
                {!!str(c.last_window) && (
                  <div className="caption">마지막 창 {str(c.last_window)} · {CSV_STATUS[str(c.last_status)] || str(c.last_status)} · {at(c.last_at)}</div>
                )}
                {!!str(c.last_message) && str(c.last_status) === "ok" && <div className="caption">{str(c.last_message)}</div>}
                {num(c.downloads) > 0 && <div className="caption">누적 {num(c.downloads)}건 · 새로 {num(c.inserted).toLocaleString()}행 · 받은 달 {num(c.months)}</div>}
                {!!str(c.last_error) && <div className="caption" style={{ color: "var(--err-ink)" }}>CSV 오류 {at(c.last_error_at)}: {str(c.last_error)}</div>}
              </div>
            );
          },
          enabled: (_, r) => <Check label="" checked={bool(r.enabled)} onChange={(v) => save(str(r.key), { enabled: v }, `${str(r.name)} ${v ? "켬" : "끔"}`)} />,
          rows: (_, r) => (
            <span>{num(r.rows).toLocaleString()}
              {num(r.uploaded_rows) > 0 && <div className="caption">파일 업로드 {num(r.uploaded_rows).toLocaleString()}</div>}</span>
          ),
          coverage: (_, r) => r.parts_target ? (
            <span>{r.coverage_from ? `${ym(r.coverage_from)}~${ym(r.coverage_to)}` : "-"}<div className="caption">칸 {num(r.parts).toLocaleString()} / {num(r.parts_target).toLocaleString()} · 시군구 {num(r.regions)}</div></span>
          ) : <span className="caption">-</span>,
          last: (_, r) => (
            <div style={{ maxWidth: 360 }}>
              <span className="caption">{at(r.last_run_at) || "아직 없음"}{r.last_ok_at ? ` · 마지막 정상 ${at(r.last_ok_at)}` : ""}</span>
              {!!str(r.message) && <div style={{ fontSize: ".85rem" }}>{str(r.message)}</div>}
              {!!str(r.last_error) && str(r.status) !== "ok" && <div className="caption" style={{ color: "var(--err-ink)" }}>{str(r.last_error)}</div>}
            </div>
          ),
          backfill_months: (_, r) => <Months row={r} onSave={(v) => save(str(r.key), { backfill_months: v }, `${str(r.name)} 과거 ${v}개월`)} />,
          calls: (_, r) => r.daily_cap ? (
            <span>{num(r.calls_today).toLocaleString()}<span className="caption"> / {num(r.daily_cap).toLocaleString()}</span>
              {!!r.backfill_calls && <div className="caption">과거 채우기 ≈ {num(r.backfill_calls).toLocaleString()}번</div>}</span>
          ) : <span className="caption">-</span>,
          run: (_, r) => <StartJob kind="re_data" text="실행" kwargs={{ only: [str(r.key)] }} />,
        }}
        rowKey={(r) => str(r.key)}
      />
      {paged.pager}
      <p className="caption">실거래가는 시군구 {num(d.regions)}곳 × 달 단위로 받습니다. 매 실행 이번 달과 지난 2달을 다시 받고(신고 기한 30일·해제 신고 반영), 남은 시간·호출로 과거를 최근 달부터 채웁니다. 데이터셋마다 하루 호출 상한 {num((d.defaults as Row)?.daily_cap, 9000).toLocaleString()}번, 한 번 실행 최대 {num((d.defaults as Row)?.max_minutes_per_run, 150)}분.</p>

      <ReUpload datasets={all} onDone={reload} />

      <Expander title={`검토했지만 넣지 않은 출처 ${asArray(d.rejected).length}곳`}>
        <DataTable rows={asArray(d.rejected)} cols={["name", "reason", "url"]} labels={{ name: "출처", reason: "이유", url: "주소" }} />
      </Expander>

      <h3 style={{ margin: "18px 0 8px" }}>실행 기록</h3>
      <RunLogTable kind="re_data" limit={30} />
    </div>
  );
}
