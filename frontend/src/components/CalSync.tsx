// 내 일정 바깥으로 잇기 (2026-11-17) — 내 공간 달력 아래.
// ① 하루 전 아침 메일(profile.alert_my, backend/pipeline/reminders.plan_digests) ② 캘린더 구독 주소(/api/me/cal-feed → /cal/<토큰>.ics).
// 둘 다 로그인 계정만 — 일정이 계정에 저장되고 메일·주소가 계정에 묶이기 때문.
import { useEffect, useState } from "react";
import { ApiError, del, get, post } from "../api";
import { useDialogs } from "./Dialogs";
import { useMe } from "../me";
import { useProfile } from "../profile";

type Feed = { account: boolean; on: boolean; created_at?: string | null; last_fetch_at?: string | null };

export function AlertToggle({ k, label, hint }: { k: "alert_my" | "alert_watch"; label: string; hint: string }) {
  const { me } = useMe();
  const { openLogin } = useDialogs();
  const { profile, save } = useProfile();
  const on = !!profile?.[k];
  if (!me?.account) {
    return <p className="caption alert-tg">📧 {label} — <button type="button" className="linkish" onClick={openLogin}>메일로 로그인</button>하면 켤 수 있어요.</p>;
  }
  return (
    <label className="check alert-tg" title={hint}>
      <input type="checkbox" checked={on} onChange={(e) => save({ [k]: e.target.checked || undefined })} /> 📧 {label}
      <span className="caption"> · {me.account.email}</span>
    </label>
  );
}

const b64d = (s: string) => Uint8Array.from(atob(s.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - (s.length % 4)) % 4)), (c) => c.charCodeAt(0));

/** 이 기기로 알림 받기 (웹 푸시) — 알림 메일을 켜 두면 같은 알림이 등록한 기기에도 와요. */
export function PushDevice() {
  const { me } = useMe();
  const [here, setHere] = useState(false);
  const [count, setCount] = useState(0);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const ok = typeof window !== "undefined" && "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
  const reg = () => navigator.serviceWorker.getRegistration().then((r) => r || undefined);
  useEffect(() => {
    if (!ok || !me?.account) return;
    (async () => {
      const r = await reg(); const sub = r ? await r.pushManager.getSubscription() : null;
      const st = await get<{ count?: number; here?: boolean }>(`me/push?endpoint=${encodeURIComponent(sub?.endpoint || "")}`).catch(() => null);
      setHere(!!sub && !!st?.here); setCount(st?.count || 0);
    })().catch(() => undefined);
  }, [ok, me?.account]);
  if (!me?.account) return null;
  if (!ok) return <p className="caption alert-tg">🔔 이 기기 알림 — 아이폰은 사파리에서 '홈 화면에 추가'한 앱으로 열면 켤 수 있어요.</p>;
  const on = async () => {
    setBusy(true); setMsg("");
    try {
      const r = await reg();
      if (!r) throw new Error("앱 알림은 보안 연결(https) 화면에서만 켤 수 있어요.");
      if ((await Notification.requestPermission()) !== "granted") throw new Error("브라우저에서 알림을 막아 두었어요. 주소창 옆 설정에서 허용해 주세요.");
      const k = await get<{ key: string }>("me/push");
      const sub = (await r.pushManager.getSubscription()) || (await r.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64d(k.key) }));
      const j = sub.toJSON();
      const res = await post<{ count: number }>("me/push", { endpoint: j.endpoint, keys: j.keys });
      setHere(true); setCount(res.count);
    } catch (e) { setMsg(e instanceof ApiError ? e.message : e instanceof Error ? e.message : "켜지 못했어요."); } finally { setBusy(false); }
  };
  const off = async () => {
    setBusy(true); setMsg("");
    try {
      const r = await reg(); const sub = r ? await r.pushManager.getSubscription() : null;
      if (sub) { await post("me/push/off", { endpoint: sub.endpoint }).catch(() => undefined); await sub.unsubscribe(); }
      setHere(false); setCount((c) => Math.max(0, c - 1));
    } catch { setMsg("끄지 못했어요."); } finally { setBusy(false); }
  };
  const test = async () => {
    setBusy(true); setMsg("");
    try { const r = await post<{ sent: number }>("me/push/test"); setMsg(r.sent ? "시험 알림을 보냈어요." : "보내지 못했어요. 껐다가 다시 켜 보세요."); }
    catch (e) { setMsg(e instanceof ApiError ? e.message : "보내지 못했어요."); } finally { setBusy(false); }
  };
  return (
    <div className="alert-tg push-dev">
      <div className="btn-row">
        <button type="button" className="btn sm" disabled={busy} onClick={here ? off : on}>{here ? "🔔 이 기기 알림 끄기" : "🔔 이 기기로 알림 받기"}</button>
        {here && <button type="button" className="btn sm ghost" disabled={busy} onClick={test}>시험 알림</button>}
      </div>
      <span className="caption">알림 메일(위)을 켜 두면 같은 알림이 등록한 기기 {count}대에도 와요. 알림에는 일정 제목만 담겨요.</span>
      {msg && <span className="caption" role="status"> {msg}</span>}
    </div>
  );
}

export default function CalSync() {
  const { me } = useMe();
  const { openLogin } = useDialogs();
  const [feed, setFeed] = useState<Feed | null>(null);
  const [url, setUrl] = useState<{ url: string; webcal: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [copied, setCopied] = useState(false);
  const [open, setOpen] = useState(false);
  useEffect(() => { if (open && me?.account) get<Feed>("me/cal-feed").then(setFeed).catch(() => undefined); }, [open, me?.account]);

  const make = async () => {
    if (feed?.on && !window.confirm("새 주소를 만들면 지금 쓰는 주소는 바로 멈춰요. 캘린더 앱에 새 주소로 다시 넣어야 해요. 만들까요?")) return;
    setBusy(true); setErr(""); setCopied(false);
    try {
      const r = await post<{ url: string; webcal: string }>("me/cal-feed");
      setUrl(r); setFeed({ account: true, on: true, created_at: new Date().toISOString().slice(0, 19) });
    } catch (e) { setErr(e instanceof ApiError ? e.message : "만들지 못했어요."); } finally { setBusy(false); }
  };
  const off = async () => {
    if (!window.confirm("구독 주소를 멈출까요? 캘린더 앱에서 집보미 일정이 더 이상 새로 고쳐지지 않아요.")) return;
    setBusy(true); setErr("");
    try { await del("me/cal-feed"); setUrl(null); setFeed({ account: true, on: false }); } catch (e) { setErr(e instanceof ApiError ? e.message : "멈추지 못했어요."); } finally { setBusy(false); }
  };
  const copy = async () => {
    if (!url) return;
    try { await navigator.clipboard.writeText(url.url); setCopied(true); } catch { setCopied(false); window.prompt("주소를 복사하세요", url.url); }
  };

  return (
    <div className="cal-sync">
      <AlertToggle k="alert_my" label="내 일정·알림·할 일을 하루 전 아침에 메일로 받기" hint="내 공간 달력의 일정·항목 알림·할 일 마감을 하루 전 아침 8시쯤 한 통으로 모아 보내요" />
      <PushDevice />
      <details className="expander" open={open} onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}>
        <summary>🔗 휴대폰·PC 캘린더에 구독으로 잇기 (자동으로 따라옴)</summary>
        <div className="body">
          {!me?.account ? (
            <p className="caption"><button type="button" className="linkish" onClick={openLogin}>메일로 로그인</button>하면 내 일정 구독 주소를 만들 수 있어요.</p>
          ) : (
            <>
              <p className="caption" style={{ marginTop: 0 }}>
                구독 주소를 캘린더 앱에 한 번 넣어 두면 내 일정·항목 알림·할 일·관심/알림 청약 공고·전세 만기가 저절로 따라와요. 앱이 몇 시간마다 새로 받아 가요.
                이 주소를 아는 사람은 누구나 내 일정 제목을 볼 수 있으니 남에게 보내지 마세요.
              </p>
              {url ? (
                <div className="cal-feed-url">
                  <input type="text" readOnly value={url.url} onFocus={(e) => e.target.select()} aria-label="구독 주소" />
                  <div className="btn-row">
                    <button type="button" className="btn sm primary" onClick={copy}>{copied ? "복사했어요" : "주소 복사"}</button>
                    <a className="btn sm" href={url.webcal}>아이폰·맥 캘린더로 열기</a>
                    <a className="btn sm" href={`https://calendar.google.com/calendar/r?cid=${encodeURIComponent(url.webcal)}`} target="_blank" rel="noopener noreferrer">구글 캘린더에 추가</a>
                  </div>
                  <p className="caption">이 주소는 지금 한 번만 보여 드려요. 잃어버리면 '새 주소 만들기'를 누르세요(예전 주소는 멈춰요).
                    아웃룩: 일정 → 캘린더 추가 → 인터넷에서 구독 → 주소 붙여 넣기.</p>
                </div>
              ) : feed?.on ? (
                <p className="caption">구독 주소를 쓰는 중이에요 · 만든 날 {String(feed.created_at || "").slice(0, 10)}
                  {feed.last_fetch_at ? ` · 캘린더 앱이 마지막으로 받아 간 때 ${String(feed.last_fetch_at).slice(0, 16).replace("T", " ")}` : " · 아직 받아 간 기록이 없어요"}</p>
              ) : null}
              <div className="btn-row">
                <button type="button" className="btn sm" disabled={busy} onClick={make}>{feed?.on ? "새 주소 만들기" : "구독 주소 만들기"}</button>
                {feed?.on && <button type="button" className="btn sm ghost" disabled={busy} onClick={off}>주소 멈추기</button>}
              </div>
              {err && <p className="caption" style={{ color: "var(--err-ink)" }}>{err}</p>}
              <p className="caption">'모든 기기에서 로그아웃'을 하면 구독 주소도 함께 멈춰요.</p>
            </>
          )}
        </div>
      </details>
    </div>
  );
}
