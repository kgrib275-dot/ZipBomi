// 수집 건강 (2026-11-20) — 수집·알림이 빠짐없이 도는지 한 화면에서. GET /api/admin/health (읽기 전용).
// 맨 위 신호등 → 서비스 가동(꺼져 있던 구간) → 배치별 14일 칸 → 부동산 데이터 → 청약 공고 → 뉴스 소스 순.
import { Alert, Metric, useLoad } from "../../components/ui";
import { A, AdminHead, Row, asArray, num, str } from "./common";

const LV: Record<string, { icon: string; label: string; cls: string }> = {
  ok: { icon: "🟢", label: "정상", cls: "" }, warn: { icon: "🟡", label: "주의", cls: "orange" }, bad: { icon: "🔴", label: "문제", cls: "red" },
};
const fmt = (s: unknown) => str(s).slice(0, 16).replace("T", " ");
const span = (m: number) => { const h = Math.floor(m / 60), d = Math.floor(h / 24); return d ? `${d}일 ${h % 24}시간` : h ? `${h}시간 ${m % 60}분` : `${m}분`; };
const WD = "월화수목금토일";

function Dots({ days }: { days: { date: string; ok: number; fail: number }[] }) {
  return (
    <span className="hl-dots" role="img" aria-label="지난 14일 실행 결과">
      {days.map((d) => (
        <i key={d.date} className={d.ok ? "ok" : d.fail ? "fail" : "none"} title={`${d.date.slice(5)} · 성공 ${d.ok} · 실패 ${d.fail}`} />
      ))}
    </span>
  );
}

export default function Health() {
  const { data, error, reload } = useLoad(() => A.get<Row>("health"), []);
  const sum = (data?.summary || {}) as Row;
  const lv = LV[str(sum.level)] || LV.ok;
  const svc = (data?.service || {}) as Row;
  const jobs = asArray(data, "jobs");
  const ds = asArray(data, "datasets");
  const ap = (data?.apply || {}) as Row;
  const nw = (data?.news || {}) as Row;
  const gaps = asArray(svc, "gaps");
  const reasons = asArray(sum, "reasons");
  const setup = ds.filter((d) => str(d.level) === "setup");
  const days = asArray(ap, "days");
  const max = Math.max(1, ...days.map((d) => num(d.count)));
  return (
    <div>
      <AdminHead title="수집 건강" note="수집·알림 배치가 빠짐없이 도는지, 서버가 꺼졌던 때는 언제였는지, 자료가 끊긴 곳은 없는지 한눈에 봅니다. 읽기 전용이에요." />
      {error && <Alert kind="err">{error}</Alert>}
      <div className={`hl-top lv-${str(sum.level)}`}>
        <b>{lv.icon} {lv.label}</b>
        <span className="caption">{fmt(data?.now)} 기준 · 서버 가동률(30일) {num(svc.uptime_pct_30d, 100)}% · 스케줄러 {svc.alive ? "작동 중" : "멈춤"}</span>
        <button type="button" className="btn sm ghost" onClick={reload}>새로 고침</button>
      </div>
      {reasons.length ? (
        <ul className="hl-reasons">{reasons.map((r, i) => <li key={i}><span className={`badge ${LV[str(r.level)]?.cls || ""}`}>{LV[str(r.level)]?.label}</span> {str(r.text)}</li>)}</ul>
      ) : <p className="caption">지금 확인된 문제가 없어요.</p>}

      <h3>서버 가동</h3>
      <div className="metrics">
        <Metric k="가동률 (30일)" v={`${num(svc.uptime_pct_30d, 100)}%`} />
        <Metric k="꺼져 있던 시간 (30일)" v={span(num(svc.down_minutes_30d))} />
        <Metric k="마지막 확인" v={fmt(svc.tick) || "-"} />
      </div>
      {gaps.length ? (
        <table className="table"><thead><tr><th>꺼져 있던 구간</th><th>길이</th><th>그동안 못 돈 배치</th></tr></thead>
          <tbody>{gaps.map((g, i) => (
            <tr key={i}><td>{fmt(g.start)} ~ {fmt(g.end)}</td><td>{span(num(g.minutes))}</td>
              <td className="caption">{Object.entries((g.missed || {}) as Record<string, number>).map(([k, n]) => `${(jobs.find((j) => str(j.kind) === k)?.label as string) || k} ${n}회`).join(" · ") || "-"}</td></tr>
          ))}</tbody></table>
      ) : <p className="caption">기록된 꺼짐 구간이 없어요. {str(svc.note)}</p>}

      <h3>배치 (지난 14일)</h3>
      <div className="table-wrap"><table className="table">
        <thead><tr><th>작업</th><th>예정</th><th>14일 (●성공 ✕실패 ·없음)</th><th>마지막 성공</th><th>다음</th></tr></thead>
        <tbody>{jobs.map((j) => (
          <tr key={str(j.kind)} className={j.enabled ? "" : "dim"}>
            <td><b>{str(j.label)}</b>{!j.enabled && <span className="badge" style={{ marginLeft: 6 }}>꺼짐</span>}{!!j.last_failed && <span className="badge red" style={{ marginLeft: 6 }} title={str(j.last_message)}>마지막 실패</span>}</td>
            <td className="caption">{str(j.schedule)}</td>
            <td><Dots days={asArray(j, "days") as { date: string; ok: number; fail: number }[]} />{num(j.missed_days) > 0 && <span className="caption"> 놓친 날 {num(j.missed_days)}</span>}</td>
            <td className="caption">{fmt(j.last_ok) || "-"}</td>
            <td className="caption">{str(j.next) || "-"}</td>
          </tr>))}</tbody></table></div>

      <h3>부동산 데이터</h3>
      <div className="table-wrap"><table className="table">
        <thead><tr><th>데이터</th><th>상태</th><th>마지막 성공</th><th>내용</th></tr></thead>
        <tbody>{ds.map((d) => (
          <tr key={str(d.key)}><td><b>{str(d.key)}</b></td>
            <td><span className={`badge ${d.level === "bad" ? "red" : d.level === "setup" || d.stale ? "orange" : ""}`}>{d.level === "ok" ? (d.stale ? "오래됨" : "정상") : d.level === "setup" ? "설정 필요" : "오류"}</span></td>
            <td className="caption">{fmt(d.last_ok_at) || "-"}</td>
            <td className="caption">{str(d.level === "bad" ? d.last_error || d.message : d.message)}</td></tr>))}</tbody></table></div>
      {setup.length > 0 && <p className="caption">설정 필요 {setup.length}개는 공공데이터포털 활용신청이나 관리 → 부동산 데이터에서 켜면 풀려요.</p>}

      <h3>청약 공고 <small className="caption">(공고일 기준 최근 3주 · 전체 {num(ap.total).toLocaleString()}건 · LH {num(ap.lh_total).toLocaleString()}건 · 마지막 수집 {fmt(ap.last_fetched) || "-"})</small></h3>
      {!!ap.zero_weekdays && <Alert kind="warn">최근 평일 3일 이상 공고가 한 건도 없어요 — 수집이 막혔는지 확인하세요.</Alert>}
      <div className="hl-bars" role="img" aria-label="공고일별 건수">
        {days.map((d) => (
          <div key={str(d.date)} className={`hl-bar${num(d.weekday) >= 5 ? " we" : ""}`} title={`${str(d.date)} (${WD[num(d.weekday)]}) · ${num(d.count)}건 (LH ${num(d.lh)})`}>
            <i style={{ height: `${Math.max(3, (num(d.count) / max) * 56)}px` }} /><span>{str(d.date).slice(8)}</span>
          </div>))}
      </div>

      <h3>뉴스 소스</h3>
      <div className="metrics">
        <Metric k="최근 7일 기사" v={num(nw.articles_7d).toLocaleString()} />
        <Metric k="기사가 들어온 소스" v={num(nw.sources_active)} />
        <Metric k="갑자기 끊긴 소스" v={num(nw.dried_count)} />
      </div>
      {asArray(nw, "dried").length > 0 ? (
        <>
          <p className="caption">그 전 7일에는 기사가 있었는데 최근 7일은 0건인 소스예요(주소 변경·차단·휴간일 수 있어요). 관리 → 수집 설정에서 확인하세요.</p>
          <ul className="hl-dried">{asArray(nw, "dried").map((s) => <li key={str(s.source)}>{str(s.source)} <span className="caption">(그 전 7일 {num(s.before)}건)</span></li>)}</ul>
        </>
      ) : <p className="caption">끊긴 소스는 없어요.</p>}
    </div>
  );
}
