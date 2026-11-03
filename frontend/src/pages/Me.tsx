// 내 프로필 (/me) — 로그인 없이 쓰는 개인화 기준값. 이 브라우저(방문자 상태 + localStorage)에 저장되고,
// 확인된 구독자 브라우저라면 뉴스레터 맞춤 구성용 사본도 서버에 둔다 (backend/pipeline/profile.py).
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Alert } from "../components/ui";
import { useMe } from "../me";
import { ACCT_OPTS, FAM_OPTS, HOME_OPTS, Profile, RegionPicker, TYPES, TypeKey, hasCore, man, useProfile } from "../profile";
import "../styles/profile.css";

type Form = Omit<Profile, "tests" | "updated_at">;
const pickForm = (p: Profile | null): Form => {
  const { tests: _t, updated_at: _u, ...rest } = p || {};
  return rest;
};

function dday(iso?: string): string {
  if (!iso) return "";
  const d = new Date(iso + "T00:00:00");
  if (isNaN(d.getTime())) return "";
  const t = new Date(); t.setHours(0, 0, 0, 0);
  const n = Math.round((d.getTime() - t.getTime()) / 86400000);
  return n === 0 ? "D-day" : n > 0 ? `D-${n}` : `만기 ${-n}일 지남`;
}

function MoneyField({ id, label, value, onChange, hint }: { id: string; label: string; value?: number; onChange: (v?: number) => void; hint?: string }) {
  return (
    <div className="field">
      <label htmlFor={id}>{label} <span className="caption">(만원)</span></label>
      <input id={id} type="number" inputMode="numeric" min={0} step={100} value={value ?? ""} placeholder="비워 둬도 돼요"
        onChange={(e) => onChange(e.target.value === "" ? undefined : Math.max(0, Math.round(Number(e.target.value))))} />
      <span className="hint">{value !== undefined ? man(value) : hint || ""}</span>
    </div>
  );
}

export default function MePage() {
  const { me, state, setState } = useMe();
  const { ready, profile, save, clear } = useProfile();
  const [f, setF] = useState<Form>(() => pickForm(profile));
  const [dirty, setDirty] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(() => { document.title = "내 프로필 — 집보미"; }, []);
  // 서버 값이 늦게 도착하면 (아직 고치지 않았을 때만) 폼에 반영
  useEffect(() => { if (!dirty) setF(pickForm(profile)); }, [profile, dirty]);

  const up = (patch: Partial<Form>) => { setF((cur) => ({ ...cur, ...patch })); setDirty(true); setMsg(null); };
  const submit = () => {
    const out: Partial<Profile> = { ...f };
    if (out.type !== "tenant") out.lease_end = undefined;
    if (!out.lease_end) out.alert_lease = undefined;
    // 지운 칸은 undefined → save 가 키를 지운다
    for (const k of ["budget_min", "budget_max", "income", "debt", "sub_home", "sub_fam", "sub_acct", "lease_end", "alert_lease", "type", "regions"] as const) {
      if (!(k in out)) (out as Record<string, unknown>)[k] = undefined;
    }
    save(out);
    setDirty(false);
    setMsg("저장했어요. 홈의 '이번 주 나에게 영향 있는 것'과 노트 '내 조건' 보기에 바로 반영됩니다.");
  };
  const wipe = () => {
    if (!window.confirm("이 브라우저에 저장한 내 프로필(테스트 결과 요약 포함)을 지울까요?")) return;
    clear();
    setF({});
    setDirty(false);
    setMsg("프로필을 지웠어요.");
  };

  const tests = profile?.tests || {};
  const testCards: [string, string, string, string | null][] = [
    ["부동산 성향 16유형", "/type", "유형 테스트 해 보기", tests.type16 ? `${tests.type16.emoji || ""} ${tests.type16.name || ""} (${tests.type16.code || ""})` : null],
    ["내 집 마련 준비도", "/diagnosis", "준비도 진단하기", tests.diagnosis ? `${tests.diagnosis.score ?? "-"}점 · ${tests.diagnosis.level || ""} 단계` : null],
    ["내 집 마련 전략", "/career", "전략 찾기", tests.career ? `${tests.career.emoji || ""} ${tests.career.name || ""}` : null],
    ["부동산 공부 습관", "/habit", "습관 진단하기", tests.habit ? `${tests.habit.emoji || ""} ${tests.habit.name || ""} · ${tests.habit.score ?? "-"}점` : null],
  ];
  const at = (k: keyof NonNullable<Profile["tests"]>) => tests[k]?.at;

  return (
    <div className="me-page">
      <div>
        <div className="eyebrow">내 프로필</div>
        <h2 className="sec-h">나에게 맞춘 <span className="grad">부동산 흐름</span></h2>
        <p className="sec-p" style={{ margin: 0 }}>
          유형과 관심 지역을 정해 두면 홈에서 이번 주 나에게 영향 있는 노트를 먼저 골라 드리고, 노트마다 내 유형에 해당하는 부분을 먼저 펼쳐 둡니다.
          모든 칸은 선택이에요. {me?.account ? "로그인한 계정에 저장돼 휴대폰·PC 어디서든 같게 보여요." : "지금은 이 브라우저에 저장되고, 메일로 로그인하면 계정으로 옮겨져 다른 기기에서도 보여요."}
        </p>
      </div>

      {!ready && <div className="caption">불러오는 중…</div>}

      <section className="box me-sec">
        <h3>1. 나는 지금</h3>
        <p className="caption">하나만 고르세요. 노트의 '나에게 미치는 영향'에서 이 유형을 먼저 보여 드려요.</p>
        <div className="type-pick" role="radiogroup" aria-label="유형">
          {TYPES.map(([k, l, d]) => (
            <button key={k} type="button" role="radio" aria-checked={f.type === k} className={f.type === k ? "on" : ""}
              onClick={() => up({ type: f.type === k ? undefined : (k as TypeKey) })}><b>{l}</b><span>{d}</span></button>
          ))}
        </div>
        {f.type === "tenant" && (
          <div className="field" style={{ marginTop: 14, maxWidth: 320 }}>
            <label htmlFor="me-lease">전세 계약 만기일 {f.lease_end && <span className="dday">{dday(f.lease_end)}</span>}</label>
            <input id="me-lease" type="date" value={f.lease_end || ""} onChange={(e) => up({ lease_end: e.target.value || undefined })} />
            {f.lease_end && (
              <label className="check" style={{ marginTop: 8 }}>
                <input type="checkbox" checked={!!f.alert_lease} onChange={(e) => up({ alert_lease: e.target.checked || undefined })} />
                {" "}만기 90일·30일 전에 메일로 알려 주세요
              </label>
            )}
            {f.lease_end && f.alert_lease && !me?.subscribed && (
              <p className="caption" style={{ margin: "4px 0 0" }}>알림 메일은 뉴스레터 구독을 확인한 브라우저에서만 보내요. 구독하면 같은 설정으로 메일이 갑니다.</p>
            )}
          </div>
        )}
      </section>

      <section className="box me-sec">
        <h3>2. 관심 지역 <span className="caption">(최대 3곳)</span></h3>
        <p className="caption">이 시군구가 나온 노트를 먼저 골라 드려요. 실거래가 조회와 같은 시군구 목록입니다.</p>
        <RegionPicker id="me-regions" value={f.regions || []} onChange={(v) => up({ regions: v })} max={3} />
      </section>

      <section className="box me-sec">
        <h3>3. 자금</h3>
        <p className="caption">내 집 계산기(대출 한도·DSR)의 빈 칸을 이 값으로 채워 드려요. 모르면 비워 두세요.</p>
        <div className="me-money">
          <MoneyField id="me-bmin" label="예산 하한" value={f.budget_min} onChange={(v) => up({ budget_min: v })} />
          <MoneyField id="me-bmax" label="예산 상한" value={f.budget_max} onChange={(v) => up({ budget_max: v })} />
          <MoneyField id="me-income" label="연소득 (세전)" value={f.income} onChange={(v) => up({ income: v })} />
          <MoneyField id="me-debt" label="기존 부채 연 원리금" value={f.debt} onChange={(v) => up({ debt: v })} hint="신용대출·할부 등 1년 상환액" />
        </div>
        {f.budget_min !== undefined && f.budget_max !== undefined && f.budget_min > f.budget_max && (
          <p className="caption">하한이 상한보다 커요 — 저장할 때 서로 바꿔 저장합니다.</p>
        )}
      </section>

      <section className="box me-sec">
        <h3>4. 청약</h3>
        <p className="caption">청약 가점 계산(84점 만점)에 쓰는 세 항목입니다. 계산기 '청약 가점' 탭과 같은 구간이에요.</p>
        <div className="me-sub">
          <div className="field"><label htmlFor="me-home">무주택 기간</label>
            <select id="me-home" value={f.sub_home ?? ""} onChange={(e) => up({ sub_home: e.target.value === "" ? undefined : Number(e.target.value) })}>
              <option value="">선택 안 함</option>{HOME_OPTS.map((t, i) => <option key={t} value={i}>{t}</option>)}
            </select></div>
          <div className="field"><label htmlFor="me-fam">부양가족 수 (본인 제외)</label>
            <select id="me-fam" value={f.sub_fam ?? ""} onChange={(e) => up({ sub_fam: e.target.value === "" ? undefined : Number(e.target.value) })}>
              <option value="">선택 안 함</option>{FAM_OPTS.map((t, i) => <option key={t} value={i}>{t}</option>)}
            </select></div>
          <div className="field"><label htmlFor="me-acct">청약통장 가입 기간</label>
            <select id="me-acct" value={f.sub_acct ?? ""} onChange={(e) => up({ sub_acct: e.target.value === "" ? undefined : Number(e.target.value) })}>
              <option value="">선택 안 함</option>{ACCT_OPTS.map((t, i) => <option key={t} value={i}>{t}</option>)}
            </select></div>
        </div>
      </section>

      <section className="box me-sec">
        <h3>테스트 결과</h3>
        <p className="caption">테스트를 마치면 여기에 자동으로 기록돼요. 다시 하면 새 결과로 바뀝니다.</p>
        <div className="me-tests">
          {testCards.map(([k, to, cta, v], i) => {
            const key = (["type16", "diagnosis", "career", "habit"] as const)[i];
            return (
              <div className="me-test" key={k}>
                <span className="k">{k}{at(key) ? ` · ${at(key)}` : ""}</span>
                {v ? <b>{v}</b> : <span className="empty">아직 안 했어요</span>}
                <Link to={to}>{v ? "다시 하기 →" : `${cta} →`}</Link>
              </div>
            );
          })}
        </div>
      </section>

      <section className="me-sec">
        <div className="btn-row">
          <Link className="btn" to="/calc">내 집 계산기에서 이 값으로 계산 →</Link>
          <Link className="btn" to="/notes" onClick={() => setState({ notes_mine: true })}>내 조건에 맞는 노트 보기 →</Link>
          {hasCore(profile) && <Link className="btn" to="/#mine">이번 주 나에게 영향 있는 것 →</Link>}
        </div>
        <p className="caption" style={{ marginTop: 10 }}>
          저장 위치: {me?.account ? "로그인한 계정(서버)." : "이 브라우저(쿠키로 구분한 방문자 기록) — 로그인하면 계정으로 옮겨져요."} 구독을 확인한 경우 뉴스레터를 맞춤으로 구성하기 위해 구독 이메일 기준으로도
          함께 보관하고, 구독을 해지하면 바로 지웁니다. 보관 기간·항목은 <Link to="/privacy">개인정보 처리방침</Link>을 확인하세요.
          {state.subscribed === true ? " 지금 이 브라우저는 구독자로 연결돼 있어요." : ""}
        </p>
      </section>

      {msg && <Alert kind="ok">{msg}</Alert>}
      <div className="me-bar">
        <button className="btn primary" type="button" onClick={submit} disabled={!dirty}>{dirty ? "저장" : "저장됨"}</button>
        {dirty && <span className="caption">고친 내용이 아직 저장되지 않았어요.</span>}
        <span className="grow" />
        {profile && <button className="btn ghost sm" type="button" onClick={wipe}>프로필 지우기</button>}
      </div>
    </div>
  );
}
