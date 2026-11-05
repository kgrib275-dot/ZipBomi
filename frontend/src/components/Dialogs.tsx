// 구독·문의·월 구독 신청 대화상자 + 열기 함수를 주는 컨텍스트 (Layout 이 감싼다).
// 수집 시점 고지(항목·목적·보유·거부권)와 만 14세 동의는 Streamlit 판 app/dialogs.py 와 같다.
import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, post, track } from "../api";
import { useMe } from "../me";
import { Alert, Dialog } from "./ui";
import LoginDialog from "./LoginDialog";
import { scheduleText, useNewsletter } from "../newsletter";

export const INDUSTRIES = ["서울", "경기", "인천", "부산·울산·경남", "대구·경북", "대전·세종·충청", "광주·전라", "강원·제주"];
const BENEFITS: [string, string, string][] = [
  ["🗓️", "매주 3분", "이번 주 시세·정책·청약 흐름을 한 줄 헤드라인과 노트 5편으로"],
  ["🏠", "내 상황에 맞게", "무주택·갈아타기·임차인 등 누구에게 어떤 영향인지까지"],
  ["📎", "주간 PDF 리포트", "저장해 두고 다시 보기 좋은 카드형 요약 리포트"],
];

type Ctx = { openSubscribe: (source: string) => void; openContact: (preset?: string, kind?: string) => void; openMembership: () => void; openLogin: () => void };
const DlgCtx = createContext<Ctx>({ openSubscribe: () => undefined, openContact: () => undefined, openMembership: () => undefined, openLogin: () => undefined });
export const useDialogs = () => useContext(DlgCtx);

export function DialogProvider({ children }: { children: React.ReactNode }) {
  const [sub, setSub] = useState<string | null>(null);
  const [contact, setContact] = useState(false);
  const [member, setMember] = useState(false);
  const [login, setLogin] = useState(false);
  const openLogin = useCallback(() => { track("login_open"); setLogin(true); }, []);
  const openSubscribe = useCallback((source: string) => {
    track("subscribe_open", source);
    setSub(source);
  }, []);
  const [contactPreset, setContactPreset] = useState("");
  const [contactKind, setContactKind] = useState("");
  const openContact = useCallback((preset?: string, kind?: string) => {
    setContactPreset(typeof preset === "string" ? preset : ""); setContactKind(typeof kind === "string" ? kind : ""); setContact(true);
  }, []);
  const openMembership = useCallback(() => {
    track("member_request_open");
    setMember(true);
  }, []);
  return (
    <DlgCtx.Provider value={{ openSubscribe, openContact, openMembership, openLogin }}>
      {children}
      {sub && <SubscribeDialog source={sub} onClose={() => setSub(null)} />}
      {contact && <ContactDialog preset={contactPreset} kind={contactKind} onClose={() => setContact(false)} />}
      {member && <MembershipDialog onClose={() => setMember(false)} />}
      {login && <LoginDialog onClose={() => setLogin(false)} />}
    </DlgCtx.Provider>
  );
}

function SubscribeDialog({ source, onClose }: { source: string; onClose: () => void }) {
  const nl = useNewsletter();
  const { state, setState } = useMe();
  const [email, setEmail] = useState("");
  const [inds, setInds] = useState<string[]>([]);
  const [agree, setAgree] = useState(false);
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string; suggest?: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const msgRef = useRef<HTMLDivElement>(null);
  // 결과 문구가 대화상자 아래쪽(모바일에서 화면 밖)에 생겨 '아무 반응이 없는' 것처럼 보이지 않게 보이는 곳으로 옮긴다
  useEffect(() => { if (msg) msgRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" }); }, [msg]);
  const send = async (addr: string, typoOk = false) => {
    if (!agree) return setMsg({ kind: "err", text: "만 14세 이상인지와 개인정보 수집·이용 안내를 확인해 주세요." });
    setBusy(true);
    try {
      const r = await post<{ message: string }>("subscribe", { email: addr, industries: inds, agree, source, ref: state.ref || "", typo_ok: typoOk });
      setMsg({ kind: "ok", text: r.message });
      // 아직 '확인 대기' — 구독 완료(subscribed)는 메일의 '구독 확인하기'를 누른 뒤 Confirm 페이지가 기록한다
      setState({ sub_pending: true, pref_inds: inds });  // 주소는 방문자 상태에 남기지 않는다
    } catch (err) {
      const e = err as ApiError;
      setMsg({ kind: "err", text: e.message, suggest: typeof e.data?.suggest === "string" ? e.data.suggest : undefined });
    } finally {
      setBusy(false);
    }
  };
  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const addr = email.trim();
    // 브라우저 기본 검사는 'a@b' 도 통과시킨다 — 점 있는 도메인까지 먼저 확인
    if (!/^[^\s@]+@[^\s@]+\.[A-Za-z]{2,}$/.test(addr)) return setMsg({ kind: "err", text: "이메일 주소 형식을 확인해 주세요. 예: name@company.com" });
    return send(addr);
  };
  // 신청이 끝나면 입력란 대신 '다음에 할 일' 화면 — 전엔 안내문 아래 입력란·구독 버튼이 그대로 남아 끝난 건지 알 수 없었다 (2026-10-30)
  if (msg?.kind === "ok") {
    return (
      <Dialog title="확인 메일을 보냈습니다" onClose={onClose}>
        <div className="sub-done">
          <div className="sub-done-ic">📬</div>
          <p className="sub-done-mail"><b>{email.trim()}</b></p>
          <ol>
            <li>메일함에서 <b>"[집보미] 구독 신청을 확인해 주세요"</b>를 엽니다.</li>
            <li>메일 안의 <b>"구독 확인하기"</b> 버튼을 누르면 구독이 완료됩니다.</li>
          </ol>
          <p className="caption">메일이 안 보이면 스팸함·프로모션함도 확인해 주세요. 보낸 사람은 집보미입니다.</p>
          <button type="button" className="btn primary block" style={{ marginTop: 14 }} onClick={onClose}>확인</button>
        </div>
      </Dialog>
    );
  }
  return (
    <Dialog title="주간 맞춤 브리핑 받기" onClose={onClose}>
      <p className="sec-p" style={{ margin: "0 0 10px" }}>{scheduleText(nl)}, 내 관심 단지와 내 조건 기준으로 3분. 관심 단지 거래 흐름과 내 유형에 영향 있는 노트만 골라 보내 드립니다.
        {!nl.enabled && " 청약 D-3·전세 만기 알림 메일은 지금도 받을 수 있어요."}</p>
      <div style={{ display: "grid", gap: 8, margin: "2px 0 8px" }}>
        {BENEFITS.map(([i, t, d]) => (
          <div key={t} style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
            <span style={{ fontSize: "1.2rem" }}>{i}</span>
            <div><b style={{ fontSize: ".92rem" }}>{t}</b><div className="caption">{d}</div></div>
          </div>
        ))}
      </div>
      <Link to="/letter" onClick={onClose} className="more">✉ 받게 될 메일 미리 보기 →</Link>
      <form onSubmit={submit} style={{ marginTop: 12 }}>
        <div className="field"><label htmlFor="sb-email">이메일</label><input id="sb-email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="name@company.com" maxLength={254} /></div>
        <div className="field">
          <label>관심 지역 소식을 먼저 받기 (선택)</label>
          <div className="btn-row">
            {INDUSTRIES.map((n) => (
              <button type="button" key={n} className={`pill ${inds.includes(n) ? "on" : ""}`} onClick={() => setInds((s) => (s.includes(n) ? s.filter((x) => x !== n) : [...s, n]))}>{n}</button>
            ))}
          </div>
        </div>
        <p className="caption"><b>개인정보 수집·이용 안내</b> · 항목: 이메일(필수), 관심 지역(선택) · 목적: 주간 뉴스레터 발송·구독 확인 · 보유: 구독 해지 시까지(해지 후 30일 이내 파기) · 구독에 꼭 필요한 정보만 받으며, 입력하지 않으면 구독할 수 없습니다. 메일은 발송 업체에 위탁해 보냅니다. <Link to="/privacy" onClick={onClose}>개인정보 처리방침</Link></p>
        <label className="check"><input type="checkbox" checked={agree} onChange={(e) => setAgree(e.target.checked)} /> 만 14세 이상이며, 위 개인정보 수집·이용 안내를 확인했습니다 (필수)</label>
        <div ref={msgRef}>
          {msg && <Alert kind={msg.kind}>{msg.text}</Alert>}
          {msg?.suggest && (
            <div className="btn-row" style={{ marginTop: 6 }}>
              <button type="button" className="btn sm primary" disabled={busy} onClick={() => { setEmail(msg.suggest!); send(msg.suggest!); }}>{msg.suggest} 로 신청</button>
              <button type="button" className="btn sm" disabled={busy} onClick={() => send(email.trim(), true)}>입력한 주소 그대로 신청</button>
            </div>
          )}
        </div>
        <button className="btn primary block" style={{ marginTop: 12 }} disabled={busy}>{busy ? "확인 중…" : "무료로 구독하기 →"}</button>
      </form>
    </Dialog>
  );
}

// 문의 종류 — 백엔드 api/routers/subscribe.py CONTACT_KINDS 와 같아야 한다. 종류를 고르면 아래 안내가 바뀐다 (2026-11-05 고객센터).
export const CONTACT_KINDS = ["일반 문의", "오류·잘못된 정보 제보", "로그인·계정 문제", "보미AI 사용 신청", "개인정보 열람·정정·삭제 요청", "저작권·권리침해 신고", "보안 취약점 제보", "제휴·광고 문의"] as const;
const KIND_HINT: Record<string, string> = {
  "오류·잘못된 정보 제보": "어느 화면(주소)의 어떤 값이 어떻게 다른지, 알고 있는 올바른 값과 출처를 적어 주세요.",
  "로그인·계정 문제": "쓰는 기기·브라우저와 어디서 막히는지 적어 주세요. 비밀번호·코드 같은 값은 절대 적지 마세요.",
  "보미AI 사용 신청": "사용 목적과 희망 횟수를 적어 주세요.",
  "개인정보 열람·정정·삭제 요청": "본인 확인을 위해 로그인·구독에 쓴 이메일 주소로 보내 주세요. 무엇을 열람·정정·삭제하고 싶은지만 적고, 주민등록번호 같은 정보는 적지 마세요. 접수 뒤 10일 이내에 조치하고 결과를 알려 드려요.",
  "저작권·권리침해 신고": "① 침해를 주장하는 페이지 주소(URL) ② 권리자 성명과 권리를 가진 근거 ③ 침해 내용 ④ 연락처를 적어 주세요. 확인한 뒤 필요하면 고치거나 내립니다.",
  "보안 취약점 제보": "재현 방법만 간단히 적어 주세요. 다른 사람의 정보를 열어 보거나 서비스에 부담을 주는 시험은 하지 말아 주세요.",
  "제휴·광고 문의": "회사(단체)와 하고 싶은 일을 적어 주세요.",
};
function kindFor(preset: string, kind?: string): string {
  if ((CONTACT_KINDS as readonly string[]).includes(kind || "")) return kind as string;
  return preset.startsWith("[보미AI 사용 신청]") ? "보미AI 사용 신청" : "일반 문의";
}

/** 문의 입력 양식 — 대화상자(ContactDialog)와 고객센터 화면(/help)이 같이 쓴다. */
export function ContactForm({ preset = "", kind, onNavigate }: { preset?: string; kind?: string; onNavigate?: () => void }) {
  // 2026-11-03: 접수되면 완료 화면으로 바꾸고 보내는 동안 단추를 잠근다 — 예전엔 다시 누르면 같은 문의가 또 접수됐다.
  // '부서·직책' 칸은 회사용 서비스 시절 흔적이라 뺐다 (개인용 서비스 — 최소 수집).
  const [f, setF] = useState({ name: "", email: "", message: preset, agree: false, kind: kindFor(preset, kind), website: "" });
  useEffect(() => { if (kind) setF((x) => ({ ...x, kind: kindFor(x.message, kind) })); }, [kind]);
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true); setMsg(null);
    try {
      await post("contact", f);
      setSent(true);
    } catch (err) {
      setMsg({ kind: "err", text: (err as ApiError).message });
    } finally { setBusy(false); }
  };
  if (sent) return (
    <div role="status">
      <Alert kind="ok">문의가 접수됐어요. 확인 후 <b>{f.email}</b> 으로 답장 드릴게요. {f.kind === "개인정보 열람·정정·삭제 요청" ? "개인정보 요청은 10일 이내에 처리합니다." : "보통 1~2일 걸려요."}</Alert>
      <p className="caption">답장이 스팸함으로 갈 수 있으니 함께 확인해 주세요. 같은 내용을 다시 보내실 필요는 없어요.</p>
    </div>
  );
  const hint = KIND_HINT[f.kind];
  return (
    <form onSubmit={submit}>
      <div className="field"><label htmlFor="ct-kind">문의 종류</label>
        <select id="ct-kind" value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}>{CONTACT_KINDS.map((k) => <option key={k}>{k}</option>)}</select>
      </div>
      {hint && <Alert kind={f.kind === "개인정보 열람·정정·삭제 요청" || f.kind === "저작권·권리침해 신고" ? "warn" : "info"}>{hint}</Alert>}
      <div className="row2">
        <div className="field"><label htmlFor="ct-name">이름</label><input id="ct-name" type="text" required maxLength={100} autoComplete="name" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></div>
        <div className="field"><label htmlFor="ct-email">이메일 (답장 받을 주소)</label><input id="ct-email" type="email" required maxLength={254} autoComplete="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></div>
      </div>
      <div className="field"><label htmlFor="ct-msg">내용</label><textarea id="ct-msg" required rows={5} maxLength={5000} value={f.message} onChange={(e) => setF({ ...f, message: e.target.value })} /></div>
      {/* 사람 눈에는 안 보이는 칸 — 자동 입력 프로그램이 채우면 접수하지 않는다 */}
      <div aria-hidden="true" style={{ position: "absolute", left: -9999, width: 1, height: 1, overflow: "hidden" }}>
        <label>웹사이트<input type="text" tabIndex={-1} autoComplete="off" value={f.website} onChange={(e) => setF({ ...f, website: e.target.value })} /></label>
      </div>
      <p className="caption"><b>개인정보 수집·이용 안내</b> · 항목: 이름·이메일·문의 내용(필수) · 목적: 문의 확인 및 답변 · 보유: 접수 후 12개월 · 답변에 꼭 필요한 정보만 받으며, 입력하지 않으면 문의를 접수할 수 없습니다. <Link to="/privacy" onClick={onNavigate}>개인정보 처리방침</Link></p>
      <label className="check"><input type="checkbox" checked={f.agree} onChange={(e) => setF({ ...f, agree: e.target.checked })} /> 만 14세 이상이며, 위 개인정보 수집·이용 안내를 확인했습니다 (필수)</label>
      <button className="btn primary block" style={{ marginTop: 12 }} disabled={busy}>{busy ? "보내는 중…" : "보내기 →"}</button>
      {msg && <Alert kind={msg.kind}>{msg.text}</Alert>}
    </form>
  );
}

function ContactDialog({ onClose, preset = "", kind }: { onClose: () => void; preset?: string; kind?: string }) {
  return (
    <Dialog title="집보미에 문의하기" onClose={onClose} wide>
      <p className="caption">서비스 이용, 잘못된 정보 제보, 개인정보·권리침해 요청, 제휴 등 무엇이든 남겨 주세요. 먼저 <Link to="/help" onClick={onClose}>자주 묻는 질문</Link>에서 답을 찾을 수도 있어요.</p>
      <ContactForm preset={preset} kind={kind} onNavigate={onClose} />
    </Dialog>
  );
}

function MembershipDialog({ onClose }: { onClose: () => void }) {
  const [f, setF] = useState({ name: "", email: "", company: "", agree: false });
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await post("membership/request", f);
      setMsg({ kind: "ok", text: "신청이 접수됐습니다. 담당자가 메일로 안내해 드릴게요." });
    } catch (err) {
      setMsg({ kind: "err", text: (err as ApiError).message });
    }
  };
  return (
    <Dialog title="질문하기 월 구독 신청" onClose={onClose}>
      <ul style={{ margin: "0 0 10px", paddingLeft: 18, color: "var(--ink-2)", fontSize: ".9rem" }}>
        <li>하루 <b>30회</b>까지 질문 (무료는 3회)</li>
        <li>기간: 30일 · 가격·결제 방법은 담당자가 메일로 안내</li>
        <li>결제 확인 후 <b>구독 코드</b>를 메일로 보내 드리면, 질문하기 화면에 넣어 바로 씁니다</li>
      </ul>
      <form onSubmit={submit}>
        <div className="row2">
          <div className="field"><label>이름</label><input type="text" required maxLength={100} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></div>
          <div className="field"><label>이메일</label><input type="email" required maxLength={254} value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></div>
        </div>
        <div className="field"><label>부서 · 직책 (선택)</label><input type="text" maxLength={100} value={f.company} onChange={(e) => setF({ ...f, company: e.target.value })} /></div>
        <p className="caption"><b>개인정보 수집·이용 안내</b> · 항목: 이름·이메일(필수), 부서·직책(선택) · 목적: 월 구독 안내·구독 코드 발송 · 보유: 신청 정보 12개월, 이용 정보 종료 후 6개월 · 안내에 꼭 필요한 정보만 받으며, 입력하지 않으면 신청할 수 없습니다. <Link to="/privacy" onClick={onClose}>개인정보 처리방침</Link></p>
        <label className="check"><input type="checkbox" checked={f.agree} onChange={(e) => setF({ ...f, agree: e.target.checked })} /> 만 14세 이상이며, 위 개인정보 수집·이용 안내를 확인했습니다 (필수)</label>
        <button className="btn primary block" style={{ marginTop: 12 }}>신청하기 →</button>
      </form>
      {msg && <Alert kind={msg.kind}>{msg.text}</Alert>}
    </Dialog>
  );
}

/** 결과·콘텐츠 끝의 구독 유도 카드. */
export function SubscribeCTA({ source, headline, sub, button = "주간 맞춤 브리핑 받기 →" }: { source: string; headline: string; sub: string; button?: string }) {
  const { state } = useMe();
  const { openSubscribe } = useDialogs();
  if (state.subscribed) return <Alert kind="ok">구독 중입니다. 다음 호에서 만나요!</Alert>;
  if (state.sub_pending) return <Alert kind="info">📬 확인 메일을 보냈습니다. 메일의 '구독 확인하기'를 누르면 구독이 완료됩니다.</Alert>;
  return (
    <div className="cta-card">
      <span className="ic">📬</span>
      <div><b>{headline}</b><small>{sub}</small></div>
      <button className="btn primary" onClick={() => openSubscribe(source)}>{button}</button>
    </div>
  );
}
