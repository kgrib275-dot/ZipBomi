// 네이버·카카오(다음)·구글 지도로 같은 자료 보기 (2026-11-02). 각 회사 공식 JavaScript 지도 SDK 를 키가 있을 때만 불러온다.
// 키(.env): NAVER_MAP_CLIENT_ID (네이버 클라우드 Maps), KAKAO_JS_KEY (카카오 개발자 JavaScript 키 + 카카오맵 사용 설정), GOOGLE_MAPS_KEY.
// 세 키 모두 브라우저용 공개 키이며 각 콘솔에서 사이트 주소(도메인)를 등록해 보호한다. 키가 없으면 그 버튼은 꺼진 채 안내만.
// 그리는 것: 시세(시군구 원 — 3.3㎡ 중위가 색), 분양 공고(점), 매물(점). 누르면 정보 창.
import { useEffect, useRef, useState } from "react";

export type Engine = "naver" | "kakao" | "google";
export type MapPoint = { id: string; lat: number; lng: number; kind: "price" | "apply" | "listing"; color: string; radius?: number; html: string; title: string };

declare global { interface Window { naver?: any; kakao?: any; __zgMapCb?: () => void } } // eslint-disable-line @typescript-eslint/no-explicit-any
const gmaps = () => (window as unknown as { google: { maps: any } }).google.maps; // eslint-disable-line @typescript-eslint/no-explicit-any

const loaded: Partial<Record<Engine, Promise<void>>> = {};
function loadSdk(engine: Engine, key: string): Promise<void> {
  if (loaded[engine]) return loaded[engine]!;
  const src = engine === "naver" ? `https://oapi.map.naver.com/openapi/v3/maps.js?ncpKeyId=${encodeURIComponent(key)}`
    : engine === "kakao" ? `https://dapi.kakao.com/v2/maps/sdk.js?appkey=${encodeURIComponent(key)}&autoload=false`
    : `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(key)}&callback=__zgMapCb&loading=async`;
  loaded[engine] = new Promise<void>((resolve, reject) => {
    const s = document.createElement("script");
    s.src = src; s.async = true;
    if (engine === "google") window.__zgMapCb = () => resolve();
    s.onload = () => { if (engine === "kakao") window.kakao.maps.load(() => resolve()); else if (engine === "naver") resolve(); };
    s.onerror = () => { delete loaded[engine]; reject(new Error("지도를 불러오지 못했습니다.")); };
    document.head.appendChild(s);
  });
  return loaded[engine]!;
}

export default function ExternalMap({ engine, apiKey, points, center, zoom }: { engine: Engine; apiKey: string; points: MapPoint[]; center: [number, number]; zoom: number }) {
  const box = useRef<HTMLDivElement>(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    let cancelled = false;
    const cleanups: (() => void)[] = [];
    setErr("");
    loadSdk(engine, apiKey).then(() => {
      if (cancelled || !box.current) return;
      box.current.innerHTML = "";
      const [lat, lng] = center;
      if (engine === "naver") {
        const N = window.naver.maps;
        const map = new N.Map(box.current, { center: new N.LatLng(lat, lng), zoom: Math.min(19, zoom + 1) });
        const info = new N.InfoWindow({ content: "", borderWidth: 0, backgroundColor: "transparent", disableAnchor: true });
        for (const p of points) {
          const pos = new N.LatLng(p.lat, p.lng);
          const shape = p.kind === "price"
            ? new N.Circle({ map, center: pos, radius: (p.radius || 10) * 120, fillColor: p.color, fillOpacity: 0.55, strokeColor: "#5c4300", strokeWeight: 1, clickable: true })
            : new N.Marker({ map, position: pos, title: p.title, icon: { content: `<span class="xm-dot" style="background:${p.color}"></span>`, anchor: new N.Point(7, 7) } });
          N.Event.addListener(shape, "click", () => { info.setContent(`<div class="xm-pop">${p.html}</div>`); info.open(map, pos); });
        }
        cleanups.push(() => map.destroy && map.destroy());
      } else if (engine === "kakao") {
        const K = window.kakao.maps;
        const map = new K.Map(box.current, { center: new K.LatLng(lat, lng), level: Math.max(1, 14 - zoom) });
        const ov = new K.CustomOverlay({ yAnchor: 1.15, zIndex: 3 });
        for (const p of points) {
          const pos = new K.LatLng(p.lat, p.lng);
          const show = () => { ov.setContent(`<div class="xm-pop">${p.html}</div>`); ov.setPosition(pos); ov.setMap(map); };
          if (p.kind === "price") {
            const c = new K.Circle({ center: pos, radius: (p.radius || 10) * 120, strokeWeight: 1, strokeColor: "#5c4300", fillColor: p.color, fillOpacity: 0.55 });
            c.setMap(map); K.event.addListener(c, "click", show);
          } else {
            const el = document.createElement("span"); el.className = "xm-dot"; el.style.background = p.color; el.title = p.title; el.onclick = show;
            new K.CustomOverlay({ position: pos, content: el, yAnchor: 0.5, xAnchor: 0.5 }).setMap(map);
          }
        }
        K.event.addListener(map, "click", () => ov.setMap(null));
      } else {
        const G = gmaps();
        const map = new G.Map(box.current, { center: { lat, lng }, zoom, mapTypeControl: true, streetViewControl: false });
        const info = new G.InfoWindow();
        for (const p of points) {
          const pos = { lat: p.lat, lng: p.lng };
          const shape = p.kind === "price"
            ? new G.Circle({ map, center: pos, radius: (p.radius || 10) * 120, fillColor: p.color, fillOpacity: 0.55, strokeColor: "#5c4300", strokeWeight: 1, clickable: true })
            : new G.Marker({ map, position: pos, title: p.title, icon: { path: G.SymbolPath.CIRCLE, scale: 7, fillColor: p.color, fillOpacity: 1, strokeColor: "#fff", strokeWeight: 1.5 } });
          shape.addListener("click", () => { info.setContent(`<div class="xm-pop">${p.html}</div>`); info.setPosition(pos); info.open({ map }); });
        }
      }
    }).catch((e) => !cancelled && setErr(e instanceof Error ? e.message : "지도를 불러오지 못했습니다."));
    return () => { cancelled = true; cleanups.forEach((f) => f()); };
  }, [engine, apiKey, points, center[0], center[1], zoom]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="xm-wrap">
      <div ref={box} className="mp-map xm-map" aria-label={`${{ naver: "네이버", kakao: "카카오", google: "구글" }[engine]} 지도`} />
      {err && <div className="xm-err">{err} 키와 사이트 주소 등록을 확인해 주세요.</div>}
    </div>
  );
}
