// Tiny DOM helpers: build elements declaratively without a framework.
//   h("div", { class: "row", onClick: fn }, child, "text", [more, children])
// Conventions (also relied on by the export bundler): one-line imports, `export function|const|class`.

export const SVG_NS = "http://www.w3.org/2000/svg";

function setProp(el, key, value, isSvg) {
  if (value === null || value === undefined || value === false) return;
  if (key === "class") {
    if (isSvg) el.setAttribute("class", value);
    else el.className = value;
  } else if (key === "style" && typeof value === "object") {
    for (const [k, v] of Object.entries(value)) {
      if (v === null || v === undefined) continue;
      if (k.startsWith("--")) el.style.setProperty(k, v);
      else el.style[k] = v;
    }
  } else if (key === "dataset") {
    for (const [k, v] of Object.entries(value)) if (v !== null && v !== undefined) el.dataset[k] = v;
  } else if (key.startsWith("on") && typeof value === "function") {
    el.addEventListener(key.slice(2).toLowerCase(), value);
  } else if (key === "text") {
    el.textContent = value;
  } else if (!isSvg && (key === "value" || key === "checked" || key === "selected")) {
    el[key] = value;
  } else if (value === true) {
    el.setAttribute(key, "");
  } else {
    el.setAttribute(key, String(value));
  }
}

export function append(el, children) {
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false || child === true) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

export function h(tag, props, ...children) {
  const el = document.createElement(tag);
  if (props) for (const [k, v] of Object.entries(props)) setProp(el, k, v, false);
  return append(el, children);
}

export function s(tag, props, ...children) {
  const el = document.createElementNS(SVG_NS, tag);
  if (props) for (const [k, v] of Object.entries(props)) setProp(el, k, v, true);
  return append(el, children);
}

export function clear(el) {
  while (el.firstChild) el.removeChild(el.firstChild);
  return el;
}

export function mount(el, ...children) {
  clear(el);
  return append(el, children);
}

export function qs(selector, root) {
  return (root || document).querySelector(selector);
}

export function qsa(selector, root) {
  return Array.from((root || document).querySelectorAll(selector));
}

// Keep a scroll container's position across a full re-render.
export function keepScroll(el, render) {
  const top = el.scrollTop;
  render();
  el.scrollTop = top;
}

export function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

export function storageGet(key, fallback) {
  try {
    const raw = window.localStorage.getItem("printready." + key);
    return raw === null ? fallback : JSON.parse(raw);
  } catch (e) {
    return fallback;
  }
}

export function storageSet(key, value) {
  try {
    window.localStorage.setItem("printready." + key, JSON.stringify(value));
  } catch (e) {
    /* private mode or blocked storage: preferences just do not persist */
  }
}
