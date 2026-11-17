// 일정 잇기 (2026-11-17) — 보미AI 답변 글에서 날짜 후보를 찾고(규칙만, AI 호출 없음), 바깥 캘린더로 보낸다.
// - 구글 캘린더: 일정 추가 화면 주소만 만든다. 사용자가 눌렀을 때만 그 브라우저에서 구글로 간다 (집보미 서버는 아무것도 보내지 않음).
// - .ics: 브라우저에서 파일을 만들어 내려받는다 (아이폰·아웃룩·삼성 캘린더). 종일 일정으로 넣는다.

export type CalEvent = { date: string; title: string; memo?: string };
export type DateHit = { date: string; title: string; raw: string; line: string; url?: string };

const pad = (n: number) => String(n).padStart(2, "0");
const isoOf = (y: number, m: number, d: number) => `${y}-${pad(m)}-${pad(d)}`;

function valid(y: number, m: number, d: number): boolean {
  if (m < 1 || m > 12 || d < 1 || d > 31) return false;
  const t = new Date(y, m - 1, d);
  return t.getFullYear() === y && t.getMonth() === m - 1 && t.getDate() === d;
}

/** 마크다운 기호를 걷어 낸 보통 글 — 링크는 글자만 남긴다 */
export function plain(s: string): string {
  return s.replace(/!?\[([^\]]*)\]\([^)]*\)/g, "$1").replace(/\*\*|__|`/g, "").replace(/^\s*(?:#{1,4}|[-*•]|\d+[.)])\s+/, "").replace(/\s+/g, " ").trim();
}

// 연도 있는 날짜: 2026.11.20 · 2026-11-20 · 2026/11/20 · 2026년 11월 20일
const FULL = /(20\d{2})\s*(?:[.\-/]|년)\s*(\d{1,2})\s*(?:[.\-/]|월)\s*(\d{1,2})\s*일?(?![\d%])/g;
// 연도 없는 날짜: 11월 20일 (가장 흔함) · 11/20 — '1/3'(비율)과 헷갈리지 않게 요일 '(목)'이나 기간 '~'이 붙을 때만
// 정규식 뒤보기((?<=…))는 iOS 16.3 이하 사파리에서 문법 오류라 화면 전체가 멈춘다 → 앞 글자는 scan 에서 직접 본다
const KMD = /(\d{1,2})\s*월\s*(\d{1,2})\s*일/g;
const SLASH = /(\d{1,2})\/(\d{1,2})(?![\d/%])/g;
const WEEKDAY_AFTER = /^\s*\(\s*[월화수목금토일]\s*\)/;
const RANGE_AFTER = /^\s*[~–]/;
const RANGE_BEFORE = /[~–]\s*$/;

/** 답변 글에서 날짜 후보 찾기. 연도가 없으면 오늘 기준 30일 전보다 이르면 다음 해로 본다. */
export function findDates(text: string, today = new Date(), max = 12): DateHit[] {
  const ty = today.getFullYear();
  const floor = new Date(today.getFullYear(), today.getMonth(), today.getDate() - 30);
  const out: DateHit[] = [];
  const seen = new Set<string>();
  for (const src of text.split(/\r?\n/)) {
    const line = plain(src);
    if (!line) continue;
    // 그 줄의 첫 링크(근거 노트·기사)를 일정 메모에 붙인다 — 사이트 안 경로와 http(s)만
    const url = /\]\((https?:\/\/[^)\s]+|\/(?![/\\])[^)\s]*)\)/.exec(src)?.[1];
    // 한 문장 안의 날짜는 같은 문장을 제목으로 쓴다. 이미 잡힌 글자 범위는 다시 잡지 않는다 (2026.11.20 의 11/20 등)
    const taken: [number, number][] = [];
    const hits: { idx: number; y: number; m: number; d: number; raw: string }[] = [];
    const scan = (re: RegExp, pick: (m: RegExpExecArray) => [number | null, number, number], ok?: (before: string, after: string) => boolean) => {
      re.lastIndex = 0;
      for (let m = re.exec(line); m; m = re.exec(line)) {
        const a = m.index, b = a + m[0].length;
        if (taken.some(([s, e]) => a < e && b > s)) continue;
        if (ok && !ok(line.slice(0, a), line.slice(b))) continue;
        const [y0, mo, d] = pick(m);
        let y = y0 ?? ty;
        if (y0 == null && new Date(y, mo - 1, d) < floor) y += 1;
        if (!valid(y, mo, d)) continue;
        taken.push([a, b]);
        hits.push({ idx: a, y, m: mo, d, raw: m[0] });
      }
    };
    scan(FULL, (m) => [Number(m[1]), Number(m[2]), Number(m[3])]);
    scan(KMD, (m) => [null, Number(m[1]), Number(m[2])], (bf) => !/[\d.]$/.test(bf));
    // 11/20 은 '1/3'(비율)과 헷갈리지 않게 요일 '(목)'이나 기간 '~'이 붙을 때만
    scan(SLASH, (m) => [null, Number(m[1]), Number(m[2])],
      (bf, af) => !/[\d./]$/.test(bf) && (WEEKDAY_AFTER.test(af) || RANGE_AFTER.test(af) || RANGE_BEFORE.test(bf)));
    hits.sort((a, b) => a.idx - b.idx);
    for (const h of hits) {
      const date = isoOf(h.y, h.m, h.d);
      const title = makeTitle(line, h.raw);
      const key = date + "|" + title;
      if (seen.has(key)) continue;
      seen.add(key);
      out.push({ date, title, raw: h.raw, line: line.slice(0, 200), url });
      if (out.length >= max) return out;
    }
  }
  return out;
}

/** 날짜가 든 문장에서 제목 만들기 — 날짜 글자와 군더더기를 빼고 60자 안으로 */
function makeTitle(line: string, raw: string): string {
  // 날짜가 든 문장 → 그 안에서 날짜가 든 마디(쉼표·슬래시로 나눔)
  const sentences = line.replace(/([.!?。])\s+/g, "$1\u0000").split(/\u0000|\s*[;·|]\s*/);
  const s = sentences.find((x) => x.includes(raw)) || line;
  const clauses = s.split(/\s*,\s*|\s+\/\s+/);
  const ci = Math.max(0, clauses.findIndex((x) => x.includes(raw)));
  let t = clean(clauses[ci] || s, raw);
  // 마디가 너무 짧으면('1순위' 등) 문장 첫 마디를 앞에 붙여 무슨 일정인지 알게 한다
  if (t.length < 8 && ci > 0) {
    const head = clean(clauses[0], "");
    if (head) t = `${head} · ${t}`.trim();
  }
  if (t.length > 60) t = t.slice(0, 59) + "…";
  return t || clean(s, raw) || "보미AI에서 찾은 일정";
}

/** 날짜·요일·기간 기호·끝맺음 말을 걷어 낸 짧은 제목 */
function clean(x: string, raw: string): string {
  let t = raw ? x.replace(raw, " ") : x;
  // 같은 마디의 다른 날짜(기간 '11월 20일~22일', '12-15~12-17' 등)도 뺀다
  t = [FULL, KMD].reduce((acc, re) => acc.replace(new RegExp(re.source, "g"), " "), t)
    .replace(/\d{1,2}\/\d{1,2}(?=\s*(?:\(\s*[월화수목금토일]\s*\)|[~–]))/g, " ")
    .replace(/[~\-–—]\s*(?:\d{1,2}\s*[.\-/월]\s*\d{1,2}\s*일?|\d{1,2}\s*일)(?!\d)/g, " ")
    .replace(/\(\s*[월화수목금토일]\s*\)/g, " ")
    .replace(/\s*[~\-–—]\s*(?=\s|$)/g, " ")
    .replace(/\s+/g, " ").trim()
    .replace(/(?:입니다|이에요|예요|예정입니다|이며|이고|까지|부터)[.!]?$/, "").trim()
    .replace(/^[\s:,~\-–—]+|[\s:,~\-–—.]+$/g, "")
    .replace(/(\S)(?:은|는)$/, "$1").trim();
  return t;
}

const ymd = (iso: string) => iso.replace(/-/g, "");
function nextDay(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  const t = new Date(y, m - 1, d + 1);
  return isoOf(t.getFullYear(), t.getMonth() + 1, t.getDate());
}

/** 구글 캘린더 '일정 추가' 화면 주소 (종일 일정) */
export function googleCalUrl(ev: CalEvent): string {
  const p = new URLSearchParams({ action: "TEMPLATE", text: ev.title, dates: `${ymd(ev.date)}/${ymd(nextDay(ev.date))}` });
  if (ev.memo) p.set("details", ev.memo);
  return `https://calendar.google.com/calendar/render?${p.toString()}`;
}

const esc = (s: string) => s.replace(/\\/g, "\\\\").replace(/;/g, "\\;").replace(/,/g, "\\,").replace(/\r?\n/g, "\\n");

/** iCalendar 줄 접기 — 75바이트(UTF-8)를 넘으면 다음 줄을 공백으로 시작 (한글이 깨지지 않게 글자 단위로 자름) */
function fold(line: string): string {
  const enc = new TextEncoder();
  if (enc.encode(line).length <= 75) return line;
  const parts: string[] = [];
  let cur = "", size = 0;
  for (const ch of line) {
    const n = enc.encode(ch).length;
    if (size + n > (parts.length ? 74 : 75)) { parts.push(cur); cur = ""; size = 0; }
    cur += ch; size += n;
  }
  parts.push(cur);
  return parts.join("\r\n ");
}

export function buildIcs(events: CalEvent[], now = new Date()): string {
  const stamp = now.toISOString().replace(/[-:]/g, "").replace(/\.\d{3}/, "");
  const lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//ZIPBOMI//My Calendar//KO", "CALSCALE:GREGORIAN", "METHOD:PUBLISH"];
  events.forEach((ev, i) => {
    lines.push("BEGIN:VEVENT",
      `UID:${ymd(ev.date)}-${i}-${Math.random().toString(36).slice(2, 10)}@zipbomi`,
      `DTSTAMP:${stamp}`,
      `DTSTART;VALUE=DATE:${ymd(ev.date)}`,
      `DTEND;VALUE=DATE:${ymd(nextDay(ev.date))}`,
      `SUMMARY:${esc(ev.title)}`);
    if (ev.memo) lines.push(`DESCRIPTION:${esc(ev.memo)}`);
    lines.push("END:VEVENT");
  });
  lines.push("END:VCALENDAR");
  return lines.map(fold).join("\r\n") + "\r\n";
}

/** .ics 파일 내려받기 */
export function downloadIcs(events: CalEvent[], name = "zipbomi-calendar.ics"): void {
  if (!events.length) return;
  const blob = new Blob([buildIcs(events)], { type: "text/calendar;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
