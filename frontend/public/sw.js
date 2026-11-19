/* 집보미 서비스 워커 — 설치 가능(PWA)과 '연결 없음' 안내 화면만 맡는다.
   · 화면 이동(navigate)만 가로채 네트워크 우선으로 보내고, 실패하면 offline.html 을 보여 준다.
   · /api 등 그 밖의 요청은 건드리지 않는다 — 사람마다 다른 응답(로그인·내 공간)을 이 기기에 저장하지 않는다.
   · 파일 내용을 바꾸면 VERSION 도 올려 이전 저장분을 지운다. */
const VERSION = "zipbomi-sw-2";
const OFFLINE = "/offline.html";
const PRECACHE = [OFFLINE, "/icon-192.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(VERSION).then((c) => c.addAll(PRECACHE)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== VERSION).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.mode !== "navigate" || req.method !== "GET") return;
  e.respondWith(
    fetch(req).catch(() => caches.open(VERSION).then((c) => c.match(OFFLINE)).then((r) => r || Response.error())),
  );
});

/* 웹 푸시 (2026-11-19) — 서버가 보낸 제목·한 줄을 알림으로 띄우고, 누르면 해당 화면을 연다.
   내용은 알림 문구뿐이며 이 기기에 따로 저장하지 않는다. 주소는 같은 사이트 안 경로만 연다. */
self.addEventListener("push", (e) => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch (_) { d = {}; }
  const title = String(d.title || "집보미");
  e.waitUntil(self.registration.showNotification(title, {
    body: String(d.body || ""), icon: "/icon-192.png", badge: "/icon-192.png", tag: String(d.tag || "zipbomi"),
    data: { url: typeof d.url === "string" && d.url.charAt(0) === "/" ? d.url : "/my" },
  }));
});

self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  const url = (e.notification.data && e.notification.data.url) || "/my";
  e.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((list) => {
    for (const c of list) { if ("focus" in c) { c.navigate(url).catch(() => {}); return c.focus(); } }
    return self.clients.openWindow(url);
  }));
});
