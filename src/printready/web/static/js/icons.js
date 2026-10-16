// Hand-drawn stroke icons on a 24 px grid (rendered at 16 px by default). No icon font, no CDN.

import { s } from "./dom.js";

const P = (d) => ["path", { d }];
const C = (cx, cy, r) => ["circle", { cx, cy, r }];
const R = (x, y, w, h, rx) => ["rect", { x, y, width: w, height: h, rx }];

const ICONS = {
  upload: [P("M12 15V4"), P("M7.5 8.5 12 4l4.5 4.5"), P("M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3")],
  image: [R(3, 4, 18, 16, 2.5), C(9, 10, 1.8), P("M21 16l-5-5-9 9")],
  play: [P("M7.5 5.5v13l10.5-6.5z")],
  sun: [C(12, 12, 4), P("M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M5.3 18.7l1.4-1.4M17.3 6.7l1.4-1.4")],
  moon: [P("M20 14.5A8.5 8.5 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z")],
  auto: [R(3, 4, 18, 12, 2), P("M8 20h8M12 16v4")],
  keyboard: [R(2.5, 6, 19, 12, 2.5), P("M6.5 10h.01M10 10h.01M13.5 10h.01M17 10h.01M7.5 14h9")],
  help: [C(12, 12, 9), P("M9.6 9.3a2.5 2.5 0 0 1 4.8.9c0 1.7-2.4 2.1-2.4 3.6"), P("M12 17h.01")],
  download: [P("M12 4v11"), P("M7.5 10.5 12 15l4.5-4.5"), P("M5 20h14")],
  check: [P("M5 12.5l4.5 4.5L19 7.5")],
  x: [P("M6.5 6.5l11 11M17.5 6.5l-11 11")],
  alert: [P("M10.3 4.3 2.6 18a2 2 0 0 0 1.7 3h15.4a2 2 0 0 0 1.7-3L13.7 4.3a2 2 0 0 0-3.4 0z"), P("M12 9.5v4.5"), P("M12 17.5h.01")],
  user: [C(12, 8, 3.8), P("M4.5 20.5c1.2-3.8 4.2-5.8 7.5-5.8s6.3 2 7.5 5.8")],
  wand: [P("M4 20 14.5 9.5"), P("M13 8l3 3"), P("M17 3v3M15.5 4.5h3M20 9v2.5M18.8 10.2h2.5M9 3.5v2M8 4.5h2")],
  cut: [C(6, 6.5, 2.6), C(6, 17.5, 2.6), P("M8.2 8.2 20 18.5"), P("M8.2 15.8 20 5.5")],
  boxes: [P("M4 8.5V5a1 1 0 0 1 1-1h3.5M15.5 4H19a1 1 0 0 1 1 1v3.5M20 15.5V19a1 1 0 0 1-1 1h-3.5M8.5 20H5a1 1 0 0 1-1-1v-3.5"), R(9, 9, 6, 6, 1)],
  border: [R(3, 3, 18, 18, 6), R(7.5, 7.5, 9, 9, 2.5)],
  ruler: [R(2.5, 8, 19, 8, 1.5), P("M6.5 8v3M10.5 8v4M14.5 8v3M18.5 8v4")],
  zoomIn: [C(11, 11, 6.5), P("M20 20l-4.4-4.4"), P("M11 8v6M8 11h6")],
  zoomOut: [C(11, 11, 6.5), P("M20 20l-4.4-4.4"), P("M8 11h6")],
  fit: [P("M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5")],
  layers: [P("M12 3.5 3 8.5l9 5 9-5z"), P("M3 13l9 5 9-5")],
  compare: [R(3, 4, 18, 16, 2.5), P("M12 4v16")],
  bot: [R(4.5, 8, 15, 11.5, 3.5), P("M12 4.5V8"), C(12, 3.5, 1.2), C(9.3, 13.5, 1.1), C(14.7, 13.5, 1.1), P("M2.5 13v2M21.5 13v2")],
  tool: [P("M14.7 6.3a4 4 0 0 0-5.4 5.4L4 17l3 3 5.3-5.3a4 4 0 0 0 5.4-5.4l-2.6 2.6-2.4-.4-.4-2.4z")],
  eye: [P("M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"), C(12, 12, 3)],
  text: [P("M5 7V4.5h14V7"), P("M12 4.5v15"), P("M9 19.5h6")],
  flag: [P("M5.5 21V4"), P("M5.5 4.5h11l-2 4 2 4h-11")],
  handoff: [C(8.5, 8, 3.3), P("M2.5 20c1-3.4 3.4-5.2 6-5.2 1.6 0 3.1.6 4.2 1.8"), P("M15 12.5h6.5M18.5 9.5l3 3-3 3")],
  shield: [P("M12 3 4.5 6v5.6c0 4.4 3.2 8.3 7.5 9.4 4.3-1.1 7.5-5 7.5-9.4V6z"), P("M8.8 12.2l2.2 2.2 4.2-4.4")],
  clock: [C(12, 12, 8.8), P("M12 7.5V12l3 2")],
  coin: [C(12, 12, 8.8), P("M14.6 9.2c-.4-1-1.4-1.6-2.6-1.6-1.6 0-2.7.8-2.7 2s1 1.7 2.7 2.1 2.9.9 2.9 2.2-1.2 2.1-2.9 2.1c-1.3 0-2.4-.6-2.8-1.7"), P("M12 6v1.6M12 16.4V18")],
  tokens: [P("M4.5 7h15M4.5 12h15M4.5 17h9")],
  file: [P("M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"), P("M14 3v5h5")],
  history: [P("M3.5 12a8.5 8.5 0 1 0 2.6-6.1"), P("M3.5 4v4.5H8"), P("M12 8v4.2l3 1.8")],
  book: [P("M5 4.5A1.5 1.5 0 0 1 6.5 3H19v15H6.5A1.5 1.5 0 0 0 5 19.5z"), P("M5 19.5A1.5 1.5 0 0 0 6.5 21H19v-3"), P("M9 7.5h6")],
  chevronLeft: [P("M14.5 6 8.5 12l6 6")],
  chevronRight: [P("M9.5 6l6 6-6 6")],
  chevronDown: [P("M6 9.5l6 6 6-6")],
  arrows: [P("M8.5 7 3.5 12l5 5"), P("M15.5 7l5 5-5 5")],
  info: [C(12, 12, 8.8), P("M12 11v5.2"), P("M12 7.8h.01")],
  sparkle: [P("M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z"), P("M19 16l.7 1.8 1.8.7-1.8.7L19 21l-.7-1.8-1.8-.7 1.8-.7z")],
  rules: [P("M4 6.5l1.5 1.5L8 5.5M4 12.5l1.5 1.5L8 11.5M4 18.5l1.5 1.5L8 17.5"), P("M11.5 6.5h8.5M11.5 12.5h8.5M11.5 18.5h8.5")],
  grid: [R(4, 4, 6.5, 6.5, 1.5), R(13.5, 4, 6.5, 6.5, 1.5), R(4, 13.5, 6.5, 6.5, 1.5), R(13.5, 13.5, 6.5, 6.5, 1.5)],
  external: [P("M14 4h6v6"), P("M20 4l-8.5 8.5"), P("M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5")],
  undo: [P("M9 14 4 9l5-5"), P("M4 9h10.5a5.5 5.5 0 0 1 0 11H11")],
  lock: [R(5, 10.5, 14, 10, 2.5), P("M8 10.5V7.5a4 4 0 0 1 8 0v3")],
  code: [P("M8.5 7 3.5 12l5 5"), P("M15.5 7l5 5-5 5"), P("M13.5 4.5l-3 15")],
  target: [C(12, 12, 8.5), C(12, 12, 4), C(12, 12, 0.6)],
  dot: [C(12, 12, 3.5)],
  minus: [P("M6 12h12")],
  refresh: [P("M20 11a8 8 0 0 0-14.5-4.5L3.5 9"), P("M3.5 4v5h5"), P("M4 13a8 8 0 0 0 14.5 4.5l2-2.5"), P("M20.5 20v-5h-5")],
};

const FILLED = new Set(["play", "dot"]);

export function icon(name, size = 16, extra) {
  const parts = ICONS[name] || ICONS.dot;
  const filled = FILLED.has(name);
  return s(
    "svg",
    {
      class: "icon" + (extra ? " " + extra : ""),
      width: size,
      height: size,
      viewBox: "0 0 24 24",
      fill: filled ? "currentColor" : "none",
      stroke: filled ? "none" : "currentColor",
      "stroke-width": 1.8,
      "stroke-linecap": "round",
      "stroke-linejoin": "round",
      "aria-hidden": "true",
      focusable: "false",
    },
    parts.map(([tag, attrs]) => s(tag, attrs))
  );
}

// The printready mark: an ink sticker inside a dashed magenta die-cut line.
export function logoMark(size = 24, extra) {
  return s(
    "svg",
    { class: "mark" + (extra ? " " + extra : ""), width: size, height: size, viewBox: "0 0 32 32", "aria-hidden": "true" },
    s("path", {
      d: "M16 2.8c5.2 0 7.6 1.6 9.6 3.6s3.6 4.4 3.6 9.6-1.6 7.6-3.6 9.6-4.4 3.6-9.6 3.6-7.6-1.6-9.6-3.6S2.8 21.2 2.8 16s1.6-7.6 3.6-9.6S10.8 2.8 16 2.8z",
      fill: "none",
      stroke: "var(--cut)",
      "stroke-width": 1.7,
      "stroke-dasharray": "3.2 2.2",
      "stroke-linecap": "round",
    }),
    s("path", {
      d: "M16 7.5c3.6 0 5.2 1 6.5 2.3s2.2 2.8 2.2 6.2-1 5-2.2 6.2-2.9 2.3-6.5 2.3-5.2-1-6.5-2.3S7.3 19.4 7.3 16s1-5 2.2-6.2S12.4 7.5 16 7.5z",
      fill: "var(--ink)",
    }),
    s("path", { d: "M12.6 19.6v-7.2h3.6a2.3 2.3 0 0 1 0 4.6h-3.6", fill: "none", stroke: "var(--bg)", "stroke-width": 2, "stroke-linecap": "round", "stroke-linejoin": "round" })
  );
}
