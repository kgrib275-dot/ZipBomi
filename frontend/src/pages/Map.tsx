// 지도 (/map) — 분양 공고·직접 등록한 매물·지역 시세를 한 지도에서 본다 (backend /api/re/map/*, api/routers/re_map.py).
// 지도: Leaflet + OpenStreetMap 타일(다크 테마는 CSS 필터로 어둡게). 매물 포털을 긁어 오지 않는다.
// 매물은 관리자(이 PC)만 등록·수정·이동·삭제한다. 방문자는 공개 매물만 보고, 메모는 안 보이며 연락처는 공개로 표시한 것만 보인다.
// 켠 레이어는 localStorage "zipgenie-map-layers", 마지막 화면 위치는 "zipgenie-map-view" 에 기억한다.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { del, get, post, put } from "../api";
import { Alert, Dialog, useLoad } from "../components/ui";
import { useMe } from "../me";
import ExternalMap, { type Engine, type MapPoint } from "./ExternalMap";
import "./Map.css";

const ENGINE_LABEL: Record<Engine, string> = { naver: "네이버", kakao: "카카오", google: "구글" };

// ───────── 자료형 ─────────
type Sgg = { code: string; name: string; lat: number; lng: number };
type SidoGeo = { sido: string; lat: number; lng: number; zoom: number; items: Sgg[] };
type PriceItem = { lawd_cd: string; region: string; sigungu: string; deals: number; median_price_manwon: number | null; median_per_3_3m2_manwon: number | null; lat: number; lng: number };
type RegionsRes = { groups: SidoGeo[]; items: PriceItem[]; months: number };
type Status = "접수중" | "예정" | "마감";
type Notice = {
  id: string; name: string; house_type: string; address: string; lawd_cd: string; region: string; households: number | null;
  notice_date: string; receipt_start: string; receipt_end: string; winner_date: string; url: string; status: Status; lat: number; lng: number; approx: boolean;
};
type ApplyRes = { items: Notice[]; today: string };
type Listing = {
  id: number; title: string; deal_type: string; house_type: string; price_manwon: number | null; deposit_manwon: number | null; monthly_manwon: number | null;
  area_m2: number | null; floor: number | null; address: string; lat: number; lng: number; updated_at: string; is_public: boolean;
  memo?: string; contact?: string; contact_public?: boolean;
};
type ListingsRes = { admin: boolean; items: Listing[] };
type Layers = { price: boolean; apply: boolean; listing: boolean };
type Tab = "분양" | "매물" | "시세";

const LS_LAYERS = "zipgenie-map-layers";
const LS_VIEW = "zipgenie-map-view";
const PYEONG = 3.305785;
const KOREA: [number, number] = [36.4, 127.8];
// 바탕지도: OpenStreetMap 표준 타일 (키 없음, 출처 표기 필수, 대량 내려받기 금지 — https://operations.osmfoundation.org/policies/tiles/).
// CARTO 무료 래스터(light_all·dark_all)는 2026-11 확인 시 키 없이 'API KEY REQUIRED' 워터마크만 돌려줘 쓰지 않는다.
// 다크 테마는 같은 타일을 CSS 필터로 어둡게 뒤집는다 (Map.css .mp-dark).
const TILE = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
// 바탕지도 고르기 (2026-11-02) — 네이버·구글 지도를 사이트 안에 띄우려면 각 회사 API 키·도메인 등록이 필요해, 키 없이 쓸 수 있는
// 일반 지도·위성 사진을 고르게 하고 네이버·구글 지도는 지금 보는 위치 그대로 새 창으로 연다.
const BASES = {
  osm: { label: "일반 지도", url: TILE, attr: "", max: 19 },
  sat: { label: "위성 사진", url: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
         attr: 'Tiles &copy; <a href="https://www.esri.com/" target="_blank" rel="noopener">Esri</a>', max: 18 },
} as const;
type BaseKey = keyof typeof BASES;
const ATTR = '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors';
const PRICE_COLORS = ["#FFE89A", "#FFD54A", "#F5B800", "#D9A100", "#9A6F00"]; // 연노랑 → 짙은 황토
const STATUS_COLOR: Record<Status, string> = { 접수중: "#16a34a", 예정: "#F5B800", 마감: "#8a8170" };
const STATUS_LABEL: Record<Status, string> = { 접수중: "접수 중", 예정: "접수 예정", 마감: "마감" };
const DEAL_TYPES = ["매매", "전세", "월세"] as const;
const HOUSE_TYPES = ["아파트", "오피스텔", "빌라", "단독", "상가", "토지"] as const;

// ───────── 작은 도구 ─────────
const esc = (s: unknown) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c] as string);

/** 만원 → '12억 3,400만원' */
function man(v: number | null | undefined): string {
  if (v === null || v === undefined || !isFinite(v)) return "-";
  const n = Math.round(v);
  const eok = Math.floor(n / 10000);
  const rest = n % 10000;
  if (!eok) return `${rest.toLocaleString("ko-KR")}만원`;
  return `${eok}억${rest ? ` ${rest.toLocaleString("ko-KR")}만` : ""}원`;
}
const areaText = (m2: number | null) => (m2 ? `${m2.toLocaleString("ko-KR", { maximumFractionDigits: 1 })}㎡ (${(m2 / PYEONG).toFixed(1)}평)` : "-");
function priceText(l: Listing): string {
  if (l.deal_type === "매매") return `매매 ${man(l.price_manwon)}`;
  if (l.deal_type === "전세") return `전세 ${man(l.deposit_manwon)}`;
  return `월세 ${man(l.deposit_manwon)} / 월 ${man(l.monthly_manwon)}`;
}
const dot = (d: string) => (d ? d.replace(/-/g, ".") : "");
const period = (n: Notice) => (n.receipt_start || n.receipt_end ? `${dot(n.receipt_start) || "?"} ~ ${dot(n.receipt_end) || "?"}` : "미정");

function readJSON<T>(k: string, fallback: T): T {
  try {
    const v = JSON.parse(localStorage.getItem(k) || "null");
    return v && typeof v === "object" ? { ...fallback, ...v } : fallback;
  } catch {
    return fallback;
  }
}
function writeJSON(k: string, v: unknown) {
  try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* 저장소를 못 쓰면 기억만 안 한다 */ }
}

function isDarkTheme(): boolean {
  const t = document.documentElement.getAttribute("data-theme");
  if (t === "dark") return true;
  if (t === "light") return false;
  return !window.matchMedia?.("(prefers-color-scheme: light)").matches;
}
function useDarkTheme(): boolean {
  const [dark, setDark] = useState(isDarkTheme);
  useEffect(() => {
    const upd = () => setDark(isDarkTheme());
    const mo = new MutationObserver(upd);
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    const mq = window.matchMedia?.("(prefers-color-scheme: light)");
    mq?.addEventListener?.("change", upd);
    return () => { mo.disconnect(); mq?.removeEventListener?.("change", upd); };
  }, []);
  return dark;
}

/** 3.3㎡당 가격 → 5단계 구간 (자료의 분위수 기준) */
function priceBins(items: PriceItem[]): number[] {
  const v = items.map((i) => i.median_per_3_3m2_manwon).filter((x): x is number => x != null).sort((a, b) => a - b);
  if (!v.length) return [];
  return [0.2, 0.4, 0.6, 0.8].map((q) => v[Math.min(v.length - 1, Math.floor(q * v.length))]);
}
const binColor = (bins: number[], v: number | null) => {
  if (v == null || !bins.length) return PRICE_COLORS[0];
  let i = 0;
  while (i < bins.length && v >= bins[i]) i++;
  return PRICE_COLORS[i];
};

// ───────── 팝업 HTML ─────────
function noticePopup(n: Notice): string {
  return `<div class="mp-pop">
    <div class="mp-pop-tag" style="--c:${STATUS_COLOR[n.status]}">${STATUS_LABEL[n.status]}</div>
    <b class="mp-pop-h">${esc(n.name)}</b>
    <dl>
      <dt>공급위치</dt><dd>${esc(n.address || n.region)}${n.approx ? ' <small>(지도 위치는 시군구 중심 · 대략)</small>' : ""}</dd>
      ${n.house_type ? `<dt>주택 구분</dt><dd>${esc(n.house_type)}</dd>` : ""}
      <dt>공급 세대</dt><dd>${n.households != null ? `${n.households.toLocaleString("ko-KR")}세대` : "-"}</dd>
      <dt>접수 기간</dt><dd>${esc(period(n))}</dd>
      <dt>당첨 발표</dt><dd>${esc(dot(n.winner_date) || "-")}</dd>
    </dl>
    ${n.url ? `<a class="mp-pop-link" href="${esc(n.url)}" target="_blank" rel="noopener noreferrer">청약홈에서 공고 보기 ↗</a>` : ""}
  </div>`;
}
function listingPopup(l: Listing, admin: boolean): string {
  return `<div class="mp-pop">
    <div class="mp-pop-tag" style="--c:#D9A100">${esc(l.house_type)} · ${esc(l.deal_type)}${admin && !l.is_public ? " · 비공개" : ""}</div>
    <b class="mp-pop-h">${esc(l.title)}</b>
    <div class="mp-pop-price">${esc(priceText(l))}</div>
    <dl>
      <dt>면적</dt><dd>${esc(areaText(l.area_m2))}</dd>
      ${l.floor != null ? `<dt>층</dt><dd>${l.floor < 0 ? `지하 ${-l.floor}` : l.floor}층</dd>` : ""}
      ${l.address ? `<dt>주소</dt><dd>${esc(l.address)}</dd>` : ""}
      ${l.contact ? `<dt>연락처</dt><dd>${esc(l.contact)}${admin && !l.contact_public ? " <small>(비공개)</small>" : ""}</dd>` : ""}
      ${admin && l.memo ? `<dt>메모</dt><dd class="mp-pop-memo">${esc(l.memo)}</dd>` : ""}
    </dl>
    ${admin ? `<div class="mp-pop-btns"><button type="button" data-act="edit" data-id="${l.id}">수정</button><button type="button" data-act="toggle" data-id="${l.id}">${l.is_public ? "비공개로" : "공개로"}</button><button type="button" data-act="delete" data-id="${l.id}" class="danger">삭제</button></div><small class="mp-pop-hint">핀을 끌어 위치를 옮길 수 있어요</small>` : ""}
  </div>`;
}
function pricePopup(p: PriceItem, months: number): string {
  return `<div class="mp-pop">
    <div class="mp-pop-tag" style="--c:#F5B800">최근 ${months}개월 아파트 매매</div>
    <b class="mp-pop-h">${esc(p.region)} ${esc(p.sigungu)}</b>
    <dl>
      <dt>중위 거래가</dt><dd>${esc(man(p.median_price_manwon))}</dd>
      <dt>3.3㎡당 중위</dt><dd>${esc(man(p.median_per_3_3m2_manwon))}</dd>
      <dt>거래 건수</dt><dd>${p.deals.toLocaleString("ko-KR")}건</dd>
    </dl>
    <a class="mp-pop-link" href="/deals?lawd=${esc(p.lawd_cd)}" data-act="deals" data-lawd="${esc(p.lawd_cd)}">실거래가 자세히 →</a>
  </div>`;
}
const listingIcon = (l: Listing, admin: boolean) => L.divIcon({
  className: "",
  html: `<div class="mp-pin ${admin && !l.is_public ? "private" : ""}"><span>${esc(l.deal_type[0])}</span></div>`,
  iconSize: [30, 38], iconAnchor: [15, 36], popupAnchor: [0, -32],
});

// ───────── 매물 입력 양식 ─────────
type Form = {
  id?: number; title: string; deal_type: string; house_type: string; price: string; deposit: string; monthly: string;
  area: string; floor: string; address: string; memo: string; contact: string; contact_public: boolean; is_public: boolean; lat: number; lng: number;
};
const emptyForm = (lat: number, lng: number): Form => ({
  title: "", deal_type: "매매", house_type: "아파트", price: "", deposit: "", monthly: "", area: "", floor: "", address: "",
  memo: "", contact: "", contact_public: false, is_public: false, lat, lng,
});
const toForm = (l: Listing): Form => ({
  id: l.id, title: l.title, deal_type: l.deal_type, house_type: l.house_type, price: l.price_manwon?.toString() ?? "",
  deposit: l.deposit_manwon?.toString() ?? "", monthly: l.monthly_manwon?.toString() ?? "", area: l.area_m2?.toString() ?? "",
  floor: l.floor?.toString() ?? "", address: l.address, memo: l.memo ?? "", contact: l.contact ?? "",
  contact_public: !!l.contact_public, is_public: l.is_public, lat: l.lat, lng: l.lng,
});
const intOrNull = (s: string) => (s.trim() === "" ? null : Math.round(Number(s.replace(/,/g, ""))));
const numOrNull = (s: string) => (s.trim() === "" ? null : Number(s.replace(/,/g, "")));

export default function MapPage() {
  const nav = useNavigate();
  const dark = useDarkTheme();
  const [layers, setLayers] = useState<Layers>(() => readJSON(LS_LAYERS, { price: true, apply: true, listing: true }));
  const [tab, setTab] = useState<Tab>("분양");
  const [applyRegion, setApplyRegion] = useState("");
  const [applyStatus, setApplyStatus] = useState<"" | Status>("");
  const [jump, setJump] = useState("");
  const [placing, setPlacing] = useState(false);
  const [form, setForm] = useState<Form | null>(null);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  const regions = useLoad(() => get<RegionsRes>("re/map/regions"), []);
  const apply = useLoad(() => get<ApplyRes>(`re/map/apply?region=${encodeURIComponent(applyRegion)}&status=${encodeURIComponent(applyStatus)}`), [applyRegion, applyStatus]);
  const listings = useLoad(() => get<ListingsRes>("re/map/listings"), []);
  const admin = !!listings.data?.admin;
  const isAdmin = !!useMe().me?.is_admin || admin;

  const boxRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const tileRef = useRef<L.TileLayer | null>(null);
  const [base, setBase] = useState<BaseKey>(() => { try { return localStorage.getItem("zg-map-base") === "sat" ? "sat" : "osm"; } catch { return "osm"; } });
  // 네이버·카카오·구글 지도로 보기 (2026-11-02) — 키가 있는 회사만 켜진다 (ExternalMap.tsx)
  const mapKeys = useMe().me?.map_keys || { naver: "", kakao: "", google: "" };
  const [engine, setEngineRaw] = useState<Engine | null>(() => { try { const v = localStorage.getItem("zg-map-engine"); return v === "naver" || v === "kakao" || v === "google" ? v : null; } catch { return null; } });
  const setEngine = (e: Engine | null) => {
    const m = mapRef.current;
    if (m) { const c = m.getCenter(); setExtCenter([c.lat, c.lng]); setExtZoom(m.getZoom()); }
    setEngineRaw(e); try { localStorage.setItem("zg-map-engine", e || ""); } catch { /* 무시 */ }
  };
  const [extCenter, setExtCenter] = useState<[number, number]>([37.5665, 126.978]);
  const [extZoom, setExtZoom] = useState(11);
  const openOuter = (who: "naver" | "google") => {
    const m = mapRef.current;
    if (!m) return;
    const c = m.getCenter(), z = m.getZoom();
    const url = who === "naver" ? `https://map.naver.com/p?c=${c.lng.toFixed(6)},${c.lat.toFixed(6)},${Math.min(z, 19)},0,0,0,dh`
      : `https://www.google.com/maps/@${c.lat.toFixed(6)},${c.lng.toFixed(6)},${z}z`;
    window.open(url, "_blank", "noopener");
  };
  const groups = useRef<{ price: L.LayerGroup; apply: L.LayerGroup; listing: L.LayerGroup } | null>(null);
  const markers = useRef<{ apply: Map<string, L.CircleMarker>; listing: Map<number, L.Marker>; price: Map<string, L.CircleMarker> }>({ apply: new Map(), listing: new Map(), price: new Map() });
  const placingRef = useRef(false);
  const actRef = useRef<(act: string, el: HTMLElement) => void>(() => undefined);
  placingRef.current = placing;

  useEffect(() => writeJSON(LS_LAYERS, layers), [layers]);
  useEffect(() => {
    if (!msg) return;
    const t = window.setTimeout(() => setMsg(null), 4000);
    return () => window.clearTimeout(t);
  }, [msg]);

  // ── 지도 만들기 (한 번) ──
  useEffect(() => {
    if (!boxRef.current || mapRef.current) return;
    const v = readJSON<{ lat?: number; lng?: number; zoom?: number }>(LS_VIEW, {});
    const okView = typeof v.lat === "number" && typeof v.lng === "number" && typeof v.zoom === "number" && v.lat > 32 && v.lat < 40 && v.lng > 123 && v.lng < 133;
    const map = L.map(boxRef.current, { zoomControl: true, minZoom: 6, maxZoom: 19, maxBounds: L.latLngBounds([30, 120], [42, 136]), worldCopyJump: false })
      .setView(okView ? [v.lat!, v.lng!] : KOREA, okView ? Math.min(18, Math.max(6, v.zoom!)) : 7);
    map.attributionControl.setPrefix(false);
    const g = { price: L.layerGroup(), apply: L.layerGroup(), listing: L.layerGroup() };
    groups.current = g;
    map.on("moveend", () => {
      const c = map.getCenter();
      writeJSON(LS_VIEW, { lat: +c.lat.toFixed(5), lng: +c.lng.toFixed(5), zoom: map.getZoom() });
    });
    map.on("click", (e: L.LeafletMouseEvent) => {
      if (!placingRef.current) return;
      setPlacing(false);
      setForm(emptyForm(+e.latlng.lat.toFixed(6), +e.latlng.lng.toFixed(6)));
    });
    // 팝업 안 버튼 — Leaflet 은 팝업의 클릭을 지도 밖으로 흘려보내지 않으므로 열릴 때마다 팝업 요소에 직접 건다
    map.on("popupopen", (e: L.PopupEvent) => {
      const el = e.popup.getElement();
      if (!el || el.dataset.bound) return;
      el.dataset.bound = "1";
      el.addEventListener("click", (ev) => {
        const t = (ev.target as HTMLElement).closest<HTMLElement>("[data-act]");
        if (!t) return;
        ev.preventDefault();
        actRef.current(t.dataset.act || "", t);
      });
    });
    mapRef.current = map;
    const ro = new ResizeObserver(() => map.invalidateSize());
    ro.observe(boxRef.current);
    return () => { ro.disconnect(); map.remove(); mapRef.current = null; tileRef.current = null; };
  }, []);

  // ── 바탕지도 (한 번) — 라이트/다크 전환은 상자의 .mp-dark 클래스(CSS 필터)로 ──
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    tileRef.current?.remove();
    const b = BASES[base];
    tileRef.current = L.tileLayer(b.url, { attribution: b.attr || ATTR, maxZoom: b.max }).addTo(map);
    tileRef.current.bringToBack();
    boxRef.current?.classList.toggle("mp-sat", base === "sat");
    try { localStorage.setItem("zg-map-base", base); } catch { /* 무시 */ }
  }, [base]);

  // ── 레이어 켜고 끄기 ──
  useEffect(() => {
    const map = mapRef.current, g = groups.current;
    if (!map || !g) return;
    (Object.keys(g) as (keyof Layers)[]).forEach((k) => (layers[k] ? g[k].addTo(map) : g[k].remove()));
  }, [layers]);

  // ── 시세 원 ──
  const bins = useMemo(() => priceBins(regions.data?.items || []), [regions.data]);
  useEffect(() => {
    const g = groups.current?.price;
    if (!g) return;
    g.clearLayers();
    markers.current.price.clear();
    const items = regions.data?.items || [];
    const maxDeals = Math.max(1, ...items.map((i) => i.deals));
    for (const p of items) {
      const m = L.circleMarker([p.lat, p.lng], {
        radius: 8 + 22 * Math.sqrt(p.deals / maxDeals), color: "#5c4300", weight: 1, fillColor: binColor(bins, p.median_per_3_3m2_manwon), fillOpacity: 0.72,
      }).bindPopup(pricePopup(p, regions.data?.months || 3), { maxWidth: 280 })
        .bindTooltip(`${p.region} ${p.sigungu} · ${man(p.median_per_3_3m2_manwon)}/3.3㎡`, { direction: "top" });
      m.addTo(g);
      markers.current.price.set(p.lawd_cd, m);
    }
  }, [regions.data, bins]);

  // ── 분양 표시 ──
  useEffect(() => {
    const g = groups.current?.apply;
    if (!g) return;
    g.clearLayers();
    markers.current.apply.clear();
    for (const n of apply.data?.items || []) {
      const m = L.circleMarker([n.lat, n.lng], {
        radius: 9, color: dark ? "#120F08" : "#ffffff", weight: 2, fillColor: STATUS_COLOR[n.status], fillOpacity: n.status === "마감" ? 0.6 : 0.95,
        dashArray: n.approx ? "3 3" : undefined,
      }).bindPopup(noticePopup(n), { maxWidth: 300 }).bindTooltip(n.name, { direction: "top" });
      m.addTo(g);
      markers.current.apply.set(n.id, m);
    }
  }, [apply.data, dark]);

  // ── 매물 핀 ──
  const saveMove = useCallback(async (id: number, lat: number, lng: number, back: () => void) => {
    try {
      await put(`re/map/listings/${id}`, { lat: +lat.toFixed(6), lng: +lng.toFixed(6) });
      setMsg({ kind: "ok", text: "위치를 옮겼습니다." });
      listings.reload();
    } catch (e) {
      back();
      setMsg({ kind: "err", text: (e as Error).message });
    }
  }, [listings]);
  useEffect(() => {
    const g = groups.current?.listing;
    if (!g) return;
    g.clearLayers();
    markers.current.listing.clear();
    for (const l of listings.data?.items || []) {
      const m = L.marker([l.lat, l.lng], { icon: listingIcon(l, admin), draggable: admin, title: l.title, riseOnHover: true })
        .bindPopup(listingPopup(l, admin), { maxWidth: 300 });
      if (admin) {
        m.on("dragend", () => {
          const p = m.getLatLng();
          if (p.lat < 33 || p.lat > 39 || p.lng < 124 || p.lng > 132) {
            m.setLatLng([l.lat, l.lng]);
            setMsg({ kind: "err", text: "국내 범위 밖으로는 옮길 수 없습니다." });
            return;
          }
          saveMove(l.id, p.lat, p.lng, () => m.setLatLng([l.lat, l.lng]));
        });
      }
      m.addTo(g);
      markers.current.listing.set(l.id, m);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [listings.data, admin]);

  // ── 팝업 버튼 동작 ──
  actRef.current = (act, el) => {
    if (act === "deals") {
      const code = el.dataset.lawd || "";
      const sido = regions.data?.groups.find((s) => s.items.some((i) => i.code === code))?.sido;
      // 실거래가 화면은 마지막 지역을 localStorage 에서 읽는다 — 그 값을 이 지역으로 맞춰 두고 이동
      const prev = readJSON<Record<string, string>>("zipgenie-deals", {});
      writeJSON("zipgenie-deals", { ...prev, lawd: code, ...(sido ? { sido } : {}) });
      nav(`/deals?lawd=${code}`);
      return;
    }
    const id = Number(el.dataset.id);
    const l = listings.data?.items.find((x) => x.id === id);
    if (!l) return;
    if (act === "edit") setForm(toForm(l));
    if (act === "toggle") {
      put(`re/map/listings/${id}`, { is_public: !l.is_public })
        .then(() => { setMsg({ kind: "ok", text: l.is_public ? "비공개로 바꿨습니다." : "공개했습니다. 방문자에게도 보입니다." }); listings.reload(); })
        .catch((e: Error) => setMsg({ kind: "err", text: e.message }));
    }
    if (act === "delete" && window.confirm(`'${l.title}' 매물을 삭제할까요? 되돌릴 수 없습니다.`)) {
      del(`re/map/listings/${id}`)
        .then(() => { mapRef.current?.closePopup(); setMsg({ kind: "ok", text: "삭제했습니다." }); listings.reload(); })
        .catch((e: Error) => setMsg({ kind: "err", text: e.message }));
    }
  };

  const focus = (kind: keyof Layers, key: string | number, lat: number, lng: number) => {
    const map = mapRef.current;
    if (!map) return;
    if (!layers[kind]) setLayers((s) => ({ ...s, [kind]: true }));
    const m = kind === "apply" ? markers.current.apply.get(key as string) : kind === "listing" ? markers.current.listing.get(key as number) : markers.current.price.get(key as string);
    let done = false;
    const open = () => { if (!done) { done = true; m?.openPopup(); } };
    map.once("moveend", open);
    map.flyTo([lat, lng], Math.max(map.getZoom(), kind === "price" ? 12 : 15), { duration: 0.8 });
    window.setTimeout(open, 1200);
    if (window.matchMedia("(max-width: 900px)").matches) boxRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
  };

  const onJump = (v: string) => {
    setJump(v);
    const map = mapRef.current;
    if (!map || !v) return;
    const gs = regions.data?.groups || [];
    if (v === "all") { map.flyTo(KOREA, 7); return; }
    const [t, key] = v.split(":");
    if (t === "s") {
      const s = gs.find((x) => x.sido === key);
      if (s) map.flyTo([s.lat, s.lng], s.zoom);
    } else {
      for (const s of gs) for (const i of s.items) if (i.code === key) map.flyTo([i.lat, i.lng], 13);
    }
  };

  // ── 매물 저장 ──
  const submit = async () => {
    if (!form) return;
    const body = {
      title: form.title.trim(), deal_type: form.deal_type, house_type: form.house_type,
      price_manwon: form.deal_type === "매매" ? intOrNull(form.price) : null,
      deposit_manwon: form.deal_type === "매매" ? null : intOrNull(form.deposit),
      monthly_manwon: form.deal_type === "월세" ? intOrNull(form.monthly) : null,
      area_m2: numOrNull(form.area), floor: intOrNull(form.floor), address: form.address.trim(), lat: form.lat, lng: form.lng,
      memo: form.memo, contact: form.contact.trim(), contact_public: form.contact_public, is_public: form.is_public,
    };
    for (const [k, v] of Object.entries(body)) {
      if (typeof v === "number" && !isFinite(v)) { setMsg({ kind: "err", text: `숫자를 확인해 주세요 (${k}).` }); return; }
    }
    setSaving(true);
    try {
      if (form.id) await put(`re/map/listings/${form.id}`, body);
      else await post("re/map/listings", body);
      setForm(null);
      setMsg({ kind: "ok", text: form.id ? "수정했습니다." : body.is_public ? "등록했습니다 (공개)." : "등록했습니다 (비공개 — 나만 보입니다)." });
      listings.reload();
    } catch (e) {
      setMsg({ kind: "err", text: (e as Error).message });
    } finally {
      setSaving(false);
    }
  };

  const priceItems = useMemo(() => [...(regions.data?.items || [])].sort((a, b) => (b.median_per_3_3m2_manwon ?? 0) - (a.median_per_3_3m2_manwon ?? 0)), [regions.data]);
  // 네이버·카카오·구글 지도에 같은 자료를 그릴 점 (켠 레이어만)
  const extPoints = useMemo<MapPoint[]>(() => {
    if (!engine) return [];
    const out: MapPoint[] = [];
    const items = regions.data?.items || [];
    const maxDeals = Math.max(1, ...items.map((i) => i.deals));
    if (layers.price) for (const p of items) out.push({ id: "p" + p.lawd_cd, lat: p.lat, lng: p.lng, kind: "price", color: binColor(bins, p.median_per_3_3m2_manwon),
      radius: 8 + 22 * Math.sqrt(p.deals / maxDeals), html: pricePopup(p, regions.data?.months || 3), title: `${p.region} ${p.sigungu}` });
    if (layers.apply) for (const n of apply.data?.items || []) out.push({ id: "a" + n.id, lat: n.lat, lng: n.lng, kind: "apply", color: STATUS_COLOR[n.status], html: noticePopup(n), title: n.name });
    if (layers.listing) for (const l of listings.data?.items || []) out.push({ id: "l" + l.id, lat: l.lat, lng: l.lng, kind: "listing", color: "#5AB2FF", html: listingPopup(l, !!listings.data?.admin), title: l.title });
    return out;
  }, [engine, regions.data, apply.data, listings.data, layers, bins]);
  const notices = apply.data?.items || [];
  const listItems = listings.data?.items || [];
  const sgroups = regions.data?.groups || [];
  const counts = useMemo(() => {
    const c: Record<Status, number> = { 접수중: 0, 예정: 0, 마감: 0 };
    notices.forEach((n) => c[n.status]++);
    return c;
  }, [notices]);
  const noPrice = regions.data && !regions.data.items.length;

  return (
    <div className="mp-page">
      <div className="mp-head">
        <div>
          <div className="eyebrow">지도</div>
          <h2 className="sec-h">한눈에 보는 <span className="grad">분양·매물·시세</span></h2>
          <p className="sec-p">청약 공고, 등록된 매물, 지역별 아파트 시세를 지도에서 함께 봅니다. 목록을 누르면 그 위치로 이동해요.</p>
        </div>
      </div>

      <div className="mp-bar">
        <div className="mp-chips" role="group" aria-label="지도 레이어">
          {([["apply", "분양", "●"], ["listing", "매물", "⌂"], ["price", "시세", "◍"]] as const).map(([k, label, ic]) => (
            <button key={k} type="button" className={`pill mp-chip ${layers[k] ? "on" : ""}`} aria-pressed={layers[k]}
              onClick={() => setLayers((s) => ({ ...s, [k]: !s[k] }))}><span aria-hidden="true" className={`mp-ic ${k}`}>{ic}</span>{label}</button>
          ))}
        </div>
        <div className="mp-bar-r">
          <div className="seg mp-base" role="group" aria-label="바탕지도">
            {(Object.keys(BASES) as BaseKey[]).map((k) => <button key={k} type="button" className={!engine && base === k ? "on" : ""} onClick={() => { setBase(k); setEngine(null); }}>{BASES[k].label}</button>)}
          </div>
          <div className="seg mp-base" role="group" aria-label="지도 회사">
            {(["naver", "kakao", "google"] as Engine[]).map((k) => (
              <button key={k} type="button" className={engine === k ? "on" : ""} disabled={!mapKeys[k]} onClick={() => setEngine(engine === k ? null : k)}
                title={mapKeys[k] ? `${ENGINE_LABEL[k]}로 보기` : `${ENGINE_LABEL[k]} — 관리자가 지도 키를 등록하면 쓸 수 있어요`}>{ENGINE_LABEL[k]}</button>
            ))}
          </div>
          <label className="sr-only" htmlFor="mp-jump">지역 바로가기</label>
          <select id="mp-jump" className="mp-jump" value={jump} onChange={(e) => onJump(e.target.value)}>
            <option value="">지역 바로가기</option>
            <option value="all">전국</option>
            {sgroups.map((s) => (
              <optgroup key={s.sido} label={s.sido}>
                <option value={`s:${s.sido}`}>{s.sido} 전체</option>
                {s.items.map((i) => <option key={i.code} value={`c:${i.code}`}>{s.sido} {i.name}</option>)}
              </optgroup>
            ))}
          </select>
          {admin && (
            <button type="button" className={`btn ${placing ? "" : "primary"} sm`} onClick={() => setPlacing((p) => !p)}>
              {placing ? "등록 취소" : "+ 매물 등록"}
            </button>
          )}
        </div>
      </div>

      {msg && <Alert kind={msg.kind === "ok" ? "ok" : "err"}>{msg.text}</Alert>}
      {layers.price && noPrice && (isAdmin
        ? <Alert kind="info">[관리자] 실거래가 데이터가 없습니다 — 공공데이터포털 키(DATA_GO_KR_KEY)·활용신청 상태를 관리 &gt; 부동산 데이터에서 확인하세요.</Alert>
        : <Alert kind="info">데이터 갱신 중입니다 — 곧 지역별 실거래가가 보입니다. 그동안 <Link to="/calc">내 집 계산기</Link>·<Link to="/deals?tab=apply">청약 공고</Link>를 확인해 보세요.</Alert>)}

      <div className="mp-wrap">
        <div className={`mp-map-box ${placing ? "placing" : ""} ${dark ? "mp-dark" : ""}`}>
          <div ref={boxRef} className="mp-map" aria-label="부동산 지도" />
          {engine && mapKeys[engine] && <ExternalMap engine={engine} apiKey={mapKeys[engine]} points={extPoints} center={extCenter} zoom={extZoom} />}
          {placing && <div className="mp-placing">매물 위치를 지도에서 클릭하세요</div>}
          <div className="mp-legend" aria-label="범례">
            {layers.apply && (
              <div className="mp-lg-row">
                {(Object.keys(STATUS_COLOR) as Status[]).map((s) => <span key={s}><i style={{ background: STATUS_COLOR[s] }} />{STATUS_LABEL[s]}</span>)}
              </div>
            )}
            {layers.price && bins.length > 0 && (
              <div className="mp-lg-row mp-lg-price">
                <span className="mp-lg-t">3.3㎡당</span>
                {PRICE_COLORS.map((c, i) => (
                  <span key={c} title={i === 0 ? `${man(bins[0])} 미만` : i === PRICE_COLORS.length - 1 ? `${man(bins[i - 1])} 이상` : `${man(bins[i - 1])} ~ ${man(bins[i])}`}>
                    <i style={{ background: c }} />
                    {i === 0 ? `~${Math.round(bins[0] / 100) / 100}억` : i === PRICE_COLORS.length - 1 ? `${Math.round(bins[i - 1] / 100) / 100}억~` : ""}
                  </span>
                ))}
                <span className="mp-lg-t">원 크기 = 거래 건수</span>
              </div>
            )}
          </div>
        </div>

        <aside className="mp-side">
          <div className="tabs" role="tablist">
            {(["분양", "매물", "시세"] as Tab[]).map((t) => (
              <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? "on" : ""} onClick={() => setTab(t)}>
                {t} <small>{t === "분양" ? notices.length : t === "매물" ? listItems.length : priceItems.length}</small>
              </button>
            ))}
          </div>

          {tab === "분양" && (
            <div className="mp-pane">
              <div className="mp-filters">
                <select aria-label="분양 지역" value={applyRegion} onChange={(e) => setApplyRegion(e.target.value)}>
                  <option value="">전체 지역</option>
                  {sgroups.map((s) => <option key={s.sido} value={s.sido}>{s.sido}</option>)}
                </select>
                <div className="mp-seg">
                  {(["", "접수중", "예정", "마감"] as const).map((s) => (
                    <button key={s || "all"} type="button" className={`pill ${applyStatus === s ? "on" : ""}`} onClick={() => setApplyStatus(s)}>
                      {s ? STATUS_LABEL[s] : "전체"}{s && !applyStatus ? ` ${counts[s]}` : ""}
                    </button>
                  ))}
                </div>
              </div>
              {apply.loading && !apply.data ? <div className="re-empty">불러오는 중…</div>
                : apply.error ? <Alert kind="err">{apply.error}</Alert>
                : !notices.length ? <div className="mp-empty">조건에 맞는 청약 공고가 아직 없습니다. 공고는 청약홈 자료를 주기적으로 받아 채웁니다.</div>
                : (
                  <ul className="mp-list">
                    {notices.map((n) => (
                      <li key={n.id}>
                        <button type="button" onClick={() => focus("apply", n.id, n.lat, n.lng)}>
                          <span className="mp-st" style={{ background: STATUS_COLOR[n.status] }}>{STATUS_LABEL[n.status]}</span>
                          <b>{n.name}</b>
                          <small>{n.region || n.address}{n.households != null ? ` · ${n.households.toLocaleString("ko-KR")}세대` : ""}</small>
                          <small>접수 {period(n)}</small>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
            </div>
          )}

          {tab === "매물" && (
            <div className="mp-pane">
              {admin && <p className="mp-note">관리자 화면 — 비공개 매물과 메모·연락처는 나에게만 보입니다. 방문자에게는 공개한 매물만, 연락처는 ‘연락처 공개’를 켠 것만 보여요.</p>}
              {listings.loading && !listings.data ? <div className="re-empty">불러오는 중…</div>
                : listings.error ? <Alert kind="err">{listings.error}</Alert>
                : !listItems.length ? <div className="mp-empty">{admin ? "아직 등록한 매물이 없습니다. ‘+ 매물 등록’을 누르고 지도에서 위치를 찍어 보세요." : "공개된 매물이 아직 없습니다."}</div>
                : (
                  <ul className="mp-list">
                    {listItems.map((l) => (
                      <li key={l.id}>
                        <button type="button" onClick={() => focus("listing", l.id, l.lat, l.lng)}>
                          <span className="mp-st listing">{l.house_type} · {l.deal_type}</span>
                          {admin && !l.is_public && <span className="mp-st private">비공개</span>}
                          <b>{l.title}</b>
                          <small>{priceText(l)}{l.area_m2 ? ` · ${areaText(l.area_m2)}` : ""}</small>
                          {l.address && <small>{l.address}</small>}
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
            </div>
          )}

          {tab === "시세" && (
            <div className="mp-pane">
              <p className="mp-note">최근 {regions.data?.months || 3}개월 아파트 매매 실거래가 기준 · 3.3㎡당 중위가 높은 순</p>
              {regions.loading && !regions.data ? <div className="re-empty">불러오는 중…</div>
                : regions.error ? <Alert kind="err">{regions.error}</Alert>
                : !priceItems.length ? <div className="mp-empty">{isAdmin ? "[관리자] 실거래가 데이터가 없습니다 — 관리 > 부동산 데이터에서 키·활용신청 상태를 확인하세요." : "데이터 갱신 중입니다 — 곧 지역별 실거래가가 보입니다."}</div>
                : (
                  <ul className="mp-list">
                    {priceItems.map((p) => (
                      <li key={p.lawd_cd}>
                        <button type="button" onClick={() => focus("price", p.lawd_cd, p.lat, p.lng)}>
                          <span className="mp-sw" style={{ background: binColor(bins, p.median_per_3_3m2_manwon) }} />
                          <b>{p.region} {p.sigungu}</b>
                          <small>3.3㎡당 {man(p.median_per_3_3m2_manwon)} · 중위 {man(p.median_price_manwon)} · {p.deals.toLocaleString("ko-KR")}건</small>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
            </div>
          )}
        </aside>
      </div>

      <p className="caption mp-foot">지도 © OpenStreetMap contributors ·분양 공고 위치가 표시되지 않은 곳은 시군구 중심에 대략 찍습니다(점선 테두리). 시세는 국토교통부 실거래가 신고 자료입니다.</p>

      {form && <ListingDialog form={form} setForm={setForm} saving={saving} onSave={submit} />}
    </div>
  );
}

function ListingDialog({ form, setForm, saving, onSave }: { form: Form; setForm: (f: Form | null) => void; saving: boolean; onSave: () => void }) {
  const set = (patch: Partial<Form>) => setForm({ ...form, ...patch });
  const area = Number(form.area);
  const preview = (s: string) => (s.trim() && isFinite(Number(s)) ? man(Number(s)) : "");
  return (
    <Dialog title={form.id ? "매물 수정" : "매물 등록"} onClose={() => setForm(null)} wide>
      <form className="mp-form" onSubmit={(e) => { e.preventDefault(); onSave(); }}>
        <div className="field">
          <label htmlFor="mf-title">제목 *</label>
          <input type="text" id="mf-title" maxLength={80} required value={form.title} placeholder="예: 래미안 84㎡ 남향 로열층" onChange={(e) => set({ title: e.target.value })} />
        </div>
        <div className="mp-form-row">
          <div className="field">
            <label htmlFor="mf-deal">거래 유형</label>
            <select id="mf-deal" value={form.deal_type} onChange={(e) => set({ deal_type: e.target.value })}>
              {DEAL_TYPES.map((d) => <option key={d}>{d}</option>)}
            </select>
          </div>
          <div className="field">
            <label htmlFor="mf-house">주택 유형</label>
            <select id="mf-house" value={form.house_type} onChange={(e) => set({ house_type: e.target.value })}>
              {HOUSE_TYPES.map((d) => <option key={d}>{d}</option>)}
            </select>
          </div>
        </div>
        <div className="mp-form-row">
          {form.deal_type === "매매" ? (
            <div className="field">
              <label htmlFor="mf-price">매매가 (만원) *</label>
              <input type="text" id="mf-price" inputMode="numeric" value={form.price} placeholder="예: 125000" onChange={(e) => set({ price: e.target.value })} />
              <span className="calc-hint">{preview(form.price)}</span>
            </div>
          ) : (
            <div className="field">
              <label htmlFor="mf-dep">보증금 (만원) *</label>
              <input type="text" id="mf-dep" inputMode="numeric" value={form.deposit} placeholder={form.deal_type === "전세" ? "예: 60000" : "예: 3000"} onChange={(e) => set({ deposit: e.target.value })} />
              <span className="calc-hint">{preview(form.deposit)}</span>
            </div>
          )}
          {form.deal_type === "월세" && (
            <div className="field">
              <label htmlFor="mf-mon">월세 (만원) *</label>
              <input type="text" id="mf-mon" inputMode="numeric" value={form.monthly} placeholder="예: 120" onChange={(e) => set({ monthly: e.target.value })} />
              <span className="calc-hint">{preview(form.monthly)}</span>
            </div>
          )}
        </div>
        <div className="mp-form-row">
          <div className="field">
            <label htmlFor="mf-area">전용면적 (㎡)</label>
            <input type="text" id="mf-area" inputMode="decimal" value={form.area} placeholder="예: 84.97" onChange={(e) => set({ area: e.target.value })} />
            <span className="calc-hint">{form.area && isFinite(area) && area > 0 ? `약 ${(area / PYEONG).toFixed(1)}평` : ""}</span>
          </div>
          <div className="field">
            <label htmlFor="mf-floor">층 (지하는 음수)</label>
            <input type="text" id="mf-floor" inputMode="numeric" value={form.floor} placeholder="예: 12" onChange={(e) => set({ floor: e.target.value })} />
          </div>
        </div>
        <div className="field">
          <label htmlFor="mf-addr">주소</label>
          <input type="text" id="mf-addr" maxLength={200} value={form.address} placeholder="예: 서울 강남구 대치동 000" onChange={(e) => set({ address: e.target.value })} />
        </div>
        <div className="mp-form-row">
          <div className="field">
            <label htmlFor="mf-contact">연락처</label>
            <input type="text" id="mf-contact" maxLength={100} value={form.contact} placeholder="예: 010-0000-0000" onChange={(e) => set({ contact: e.target.value })} />
          </div>
          <div className="field mp-checks">
            <label><input type="checkbox" checked={form.contact_public} disabled={!form.contact.trim()} onChange={(e) => set({ contact_public: e.target.checked })} /> 연락처를 방문자에게 공개</label>
            <label><input type="checkbox" checked={form.is_public} onChange={(e) => set({ is_public: e.target.checked })} /> 이 매물을 공개 (끄면 나만 보임)</label>
          </div>
        </div>
        <div className="field">
          <label htmlFor="mf-memo">메모 (나만 보임)</label>
          <textarea id="mf-memo" maxLength={1000} rows={3} value={form.memo} onChange={(e) => set({ memo: e.target.value })} />
        </div>
        <p className="caption">위치: {form.lat.toFixed(5)}, {form.lng.toFixed(5)} — 저장한 뒤 지도에서 핀을 끌어 옮길 수 있어요.</p>
        <div className="btn-row">
          <button type="submit" className="btn primary" disabled={saving}>{saving ? "저장 중…" : form.id ? "수정 저장" : "등록"}</button>
          <button type="button" className="btn" onClick={() => setForm(null)}>취소</button>
        </div>
      </form>
    </Dialog>
  );
}
