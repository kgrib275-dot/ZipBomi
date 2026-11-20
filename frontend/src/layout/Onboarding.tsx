// 첫 사용 안내 (2026-11-20) — 처음 온 사람에게 30초 3단계: ① 내 상황 ② 관심 지역 ③ 놓치지 않게 알림 켜기.
// 알림이 재방문의 핵심인데 로그인·설정을 해야 켜져서 대부분 못 썼다 — 여기서 한 번에 안내한다.
// 닫으면 7일 동안 다시 띄우지 않고(localStorage), 끝내면 다시 띄우지 않는다. 로그인 전에 끝냈으면 로그인한 뒤 3단계만 다시 권한다.
// 저장은 모두 내 프로필(useProfile) — 새 저장 항목: 알림 종류(alert_newapply)와 주간 요약용 관심 지역(re_watch 지역 항목).
import { useEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";
import { PushDevice } from "../components/CalSync";
import { useDialogs } from "../components/Dialogs";
import { Dialog } from "../components/ui";
import { useMe } from "../me";
import { RegionPicker, TYPES, type TypeKey, hasCore, useProfile, useRegions } from "../profile";

const SHOW = new Set(["/", "/home", "/calendar", "/deals", "/calc", "/notes", "/map", "/now", "/lab"]);
const K1 = "zg-onb", K3 = "zg-onb3";
const active = (k: string) => { try { return Date.now() < (Number(localStorage.getItem(k)) || 0); } catch { return false; } };
const hold = (k: string, days: number) => { try { localStorage.setItem(k, String(Date.now() + days * 864e5)); } catch { /* 저장이 막혀도 이번엔 닫힌다 */ } };

export default function Onboarding() {
  const { me, setState, state } = useMe();
  const { openLogin } = useDialogs();
  const { ready, profile, save } = useProfile();
  const { byCode } = useRegions();
  const loc = useLocation();
  const [step, setStep] = useState(0); // 0 닫힘
  const [type, setType] = useState<TypeKey | undefined>(undefined);
  const [regions, setRegions] = useState<string[]>([]);
  const [sale, setSale] = useState(true);
  const [lottery, setLottery] = useState(true);
  const [week, setWeek] = useState(true);
  const tried = useRef(false);
  const account = !!me?.account;

  useEffect(() => {
    if (!ready || !me || tried.current || step !== 0 || !SHOW.has(loc.pathname.replace(/\/+$/, "") || "/")) return;
    let next = 0;
    if (!hasCore(profile) && !active(K1)) next = 1;
    else if (hasCore(profile) && account && !profile?.alert_newapply && profile?.regions?.length && !active(K3)) next = 3;
    if (!next) return;
    const t = window.setTimeout(() => { tried.current = true; setStep(next); }, 6000); // 첫 화면을 먼저 보여 준 뒤 (그 사이 화면을 옮기면 다시 센다)
    return () => window.clearTimeout(t);
  }, [ready, me, profile, account, loc.pathname, step]);
  useEffect(() => { tried.current = false; }, [account]); // 로그인하면 3단계를 다시 권할 수 있게
  // 홈 '내 브리핑 만들기' 단추 등에서 바로 열기
  useEffect(() => {
    const open = () => setStep(hasCore(profile) && account ? 3 : 1);
    window.addEventListener("zg-open-onboarding", open);
    return () => window.removeEventListener("zg-open-onboarding", open);
  }, [profile, account]);

  if (!step) return null;
  const close = (days = 7) => { hold(step === 3 ? K3 : K1, days); setStep(0); };
  const regs = step === 3 ? profile?.regions || [] : regions;

  const finishAlerts = () => {
    const kinds = [...(sale ? ["sale"] : []), ...(lottery ? ["lottery"] : [])] as ("sale" | "lottery")[];
    save({ alert_newapply: kinds.length ? kinds : undefined, alert_my: true, alert_week: week || undefined });
    if (week && regs.length) {
      // 월요일 주간 요약은 관심 단지·지역(re_watch)을 본다 — 고른 지역을 지역 단위로 넣는다 (한 번에 합쳐 저장: 여러 번 따로 저장하면 마지막 것만 남는다)
      const have = Array.isArray(state.re_watch) ? (state.re_watch as { lawd: string; apt?: string }[]) : [];
      const add = regs.filter((c) => !have.some((w) => w.lawd === c && !w.apt)).map((c) => ({ lawd: c, region: byCode[c]?.label || c, dong: "", apt: "", note: "", added: new Date().toLocaleDateString("sv-SE") }));
      if (add.length) setState({ re_watch: [...have, ...add].slice(-50) });
    }
    hold(K3, 365); hold(K1, 365); setStep(0);
  };

  return (
    <Dialog title={step === 1 ? "내 상황에 맞게 시작해 볼까요? (1/3)" : step === 2 ? "관심 지역을 골라 주세요 (2/3)" : step === 4 ? "저장했어요" : "놓치지 않게 알려 드릴까요? (3/3)"} onClose={() => close()} noBackdropClose>
      {step === 1 && (
        <>
          <p className="caption" style={{ marginTop: 0 }}>30초면 끝나요. 고른 내용은 홈의 '내 브리핑'과 알림을 맞추는 데만 쓰고, 언제든 내 프로필에서 바꿀 수 있어요.</p>
          <div className="onb-types">
            {TYPES.map(([k, l, d]) => <button key={k} type="button" className={`onb-type${type === k ? " on" : ""}`} aria-pressed={type === k} onClick={() => setType(k)}><b>{l}</b><small>{d}</small></button>)}
          </div>
          <div className="btn-row">
            <button type="button" className="btn primary" disabled={!type} onClick={() => setStep(2)}>다음</button>
            <button type="button" className="btn ghost" onClick={() => close()}>나중에 할게요</button>
          </div>
        </>
      )}
      {step === 2 && (
        <>
          <p className="caption" style={{ marginTop: 0 }}>최대 3곳. 새 청약 공고와 거래 소식을 이 지역 기준으로 모아 드려요.</p>
          <RegionPicker value={regions} onChange={setRegions} max={3} placeholder="시군구 이름 일부 (예: 마포, 분당, 해운대)" />
          <div className="btn-row" style={{ marginTop: 12 }}>
            <button type="button" className="btn primary" onClick={() => { save({ type, regions: regions.length ? regions : undefined }); if (account && regions.length) setStep(3); else { hold(K1, 365); setStep(regions.length ? 4 : 0); } }}>
              {regions.length ? "저장하고 다음" : "지역 없이 저장"}</button>
            <button type="button" className="btn ghost" onClick={() => setStep(1)}>이전</button>
          </div>
        </>
      )}
      {step === 4 && (
        <>
          <p>저장했어요! 🎉 메일로 로그인하면 <b>내 지역 새 청약 공고</b>(무순위·재공급 포함)와 <b>일정 하루 전</b> 알림을 메일·휴대폰으로 받을 수 있어요. 비밀번호 없이 1분이면 돼요.</p>
          <div className="btn-row">
            <button type="button" className="btn primary" onClick={() => { setStep(0); openLogin(); }}>메일로 로그인하고 알림 켜기</button>
            <button type="button" className="btn ghost" onClick={() => setStep(0)}>나중에</button>
          </div>
        </>
      )}
      {step === 3 && (
        <>
          <p className="caption" style={{ marginTop: 0 }}>공고는 매일 아침 새로 모아요. 켜 두면 놓치지 않게 먼저 알려 드려요{profile?.regions?.length ? ` (${profile.regions.map((c) => byCode[c]?.name || c).join(", ")})` : ""}.</p>
          <label className="check"><input type="checkbox" checked={sale} onChange={(e) => setSale(e.target.checked)} /> 내 지역 <b>새 청약 공고</b> (분양·임대)</label>
          <label className="check"><input type="checkbox" checked={lottery} onChange={(e) => setLottery(e.target.checked)} /> <b>무순위·잔여·재공급</b> 공고도 (놓치기 쉬운 공고)</label>
          <label className="check"><input type="checkbox" checked={true} disabled readOnly /> 내가 넣은 일정·할 일 <b>하루 전</b> 알림</label>
          <label className="check"><input type="checkbox" checked={week} onChange={(e) => setWeek(e.target.checked)} /> 월요일 아침 <b>지난주 거래 요약</b> (내 지역)</label>
          <PushDevice />
          <div className="btn-row" style={{ marginTop: 12 }}>
            <button type="button" className="btn primary" onClick={finishAlerts}>알림 켜기</button>
            <button type="button" className="btn ghost" onClick={() => close(14)}>나중에</button>
          </div>
          <p className="caption">메일 {me?.account?.email}로 보내요. 휴대폰 알림은 위 버튼으로 이 기기를 등록하면 와요. 언제든 내 공간에서 끌 수 있어요.</p>
        </>
      )}
    </Dialog>
  );
}
