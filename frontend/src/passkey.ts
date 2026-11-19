// 패스키(WebAuthn) 브라우저 쪽 (2026-11-19) — 서버는 /api/auth/passkey/* (backend/api/routers/passkey.py).
// 생체 정보는 기기 밖으로 나가지 않고, 서버에는 공개키만 저장된다.
import { post } from "./api";

type Opts = { cid: string; publicKey: Record<string, unknown> };
const b64d = (s: string): ArrayBuffer => {
  const bin = atob(s.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - (s.length % 4)) % 4));
  const u = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) u[i] = bin.charCodeAt(i);
  return u.buffer;
};
const b64e = (b: ArrayBuffer | null | undefined): string => {
  if (!b) return "";
  let s = "";
  new Uint8Array(b).forEach((c) => { s += String.fromCharCode(c); });
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
};

export const passkeySupported = () => typeof window !== "undefined" && !!window.PublicKeyCredential && !!navigator.credentials;

/** 브라우저 오류 → 사람이 읽을 문구 (취소·시간 초과는 조용히 안내) */
export function passkeyMessage(e: unknown): string {
  const name = (e as { name?: string })?.name;
  if (name === "NotAllowedError") return "취소했거나 시간이 지났어요. 다시 눌러 주세요.";
  if (name === "InvalidStateError") return "이 기기의 패스키가 이미 등록돼 있어요.";
  if (name === "SecurityError") return "이 주소에서는 패스키를 쓸 수 없어요 (보안 연결 필요).";
  if (name === "NotSupportedError") return "이 기기는 패스키를 지원하지 않아요.";
  return e instanceof Error && e.message ? e.message : "패스키를 쓰지 못했어요.";
}

/** 패스키로 로그인 — 성공하면 서버가 쿠키를 심는다. 실패하면 throw */
export async function loginWithPasskey(): Promise<void> {
  const o = await post<Opts>("auth/passkey/login/options");
  const pk = o.publicKey as { challenge: string; rpId: string; timeout: number; userVerification: UserVerificationRequirement };
  const cred = (await navigator.credentials.get({ publicKey: { challenge: b64d(pk.challenge), rpId: pk.rpId, timeout: pk.timeout, userVerification: pk.userVerification, allowCredentials: [] } })) as PublicKeyCredential | null;
  if (!cred) throw new Error("패스키를 받지 못했어요.");
  const r = cred.response as AuthenticatorAssertionResponse;
  await post("auth/passkey/login/verify", {
    cid: o.cid,
    credential: { id: cred.id, type: cred.type, response: { clientDataJSON: b64e(r.clientDataJSON), authenticatorData: b64e(r.authenticatorData), signature: b64e(r.signature), userHandle: b64e(r.userHandle) } },
  });
}

/** 이 기기에 패스키 만들기(로그인한 계정) — 이름은 목록에서 알아보기 위한 것 */
export async function registerPasskey(label: string): Promise<void> {
  const o = await post<Opts>("auth/passkey/register/options");
  const pk = o.publicKey as { challenge: string; rp: PublicKeyCredentialRpEntity; user: { id: string; name: string; displayName: string }; pubKeyCredParams: PublicKeyCredentialParameters[];
    excludeCredentials: { type: "public-key"; id: string }[]; timeout: number; attestation: AttestationConveyancePreference; authenticatorSelection: AuthenticatorSelectionCriteria };
  const cred = (await navigator.credentials.create({ publicKey: {
    challenge: b64d(pk.challenge), rp: pk.rp, user: { id: b64d(pk.user.id), name: pk.user.name, displayName: pk.user.displayName }, pubKeyCredParams: pk.pubKeyCredParams,
    excludeCredentials: pk.excludeCredentials.map((x) => ({ type: x.type, id: b64d(x.id) })), timeout: pk.timeout, attestation: pk.attestation, authenticatorSelection: pk.authenticatorSelection,
  } })) as PublicKeyCredential | null;
  if (!cred) throw new Error("패스키를 만들지 못했어요.");
  const r = cred.response as AuthenticatorAttestationResponse;
  await post("auth/passkey/register/verify", {
    cid: o.cid, label,
    credential: { id: cred.id, type: cred.type, response: { clientDataJSON: b64e(r.clientDataJSON), attestationObject: b64e(r.attestationObject) } },
  });
}
