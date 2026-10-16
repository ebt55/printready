// Blind labelling. One image, a caption (pass 1 only), a few keys. Nothing from any tool is
// visible: no findings, no mode, no file names (images are served by content hash).
// Pass 1: 1 Ready, 2 Fixable, 3 Needs a person. Pass 2 (proof only): y Acceptable, n Not.
// Every key is saved before the next image shows; Backspace moves back and the next key
// replaces that label (labels.jsonl is append-only; the last line per image wins).

import { h, clear } from "./dom.js";
import { icon, logoMark } from "./icons.js";
import { api } from "./api.js";
import { store } from "./store.js";
import { empty, kbd, spinner, toast } from "./ui.js";

export function createLabel(root) {
  const screen = h("div", { class: "label-screen" });
  root.append(screen);
  const s = { session: null, index: 0, saving: false, error: null, pass: null, flash: null, intro: false };

  const labelMode = () => store.get().app && store.get().app.mode === "label";

  // Fit the image into the space above the caption and keys (CSS percentages cannot here).
  function fitImage() {
    const box = screen.querySelector(".label-img");
    const img = box && box.querySelector("img");
    if (!img) return;
    img.style.maxHeight = Math.max(80, box.clientHeight) + "px";
    img.style.maxWidth = Math.min(box.clientWidth, 1000) + "px";
  }
  window.addEventListener("resize", fitImage);

  async function load(pass) {
    s.session = null;
    s.error = null;
    render();
    try {
      s.session = await api.labelSession(pass);
      s.pass = s.session.pass;
      s.index = s.session.start;
      s.intro = false;
      preload();
    } catch (e) {
      s.error = e.status === 404 ? "none" : e.message;
    }
    render();
  }

  function current() {
    return s.session && s.session.items[s.index];
  }

  function preload() {
    const items = s.session ? s.session.items : [];
    for (const it of items.slice(s.index + 1, s.index + 3)) {
      const img = new Image();
      img.src = it.url;
    }
  }

  function nextUnlabelled(from) {
    const items = s.session.items;
    for (let i = from + 1; i < items.length; i++) if (!items[i].label) return i;
    for (let i = 0; i < items.length; i++) if (!items[i].label) return i;
    return items.length; // all done
  }

  async function choose(label) {
    const item = current();
    if (!item || s.saving) return;
    const keyEl = screen.querySelector(`[data-label="${label}"]`);
    if (keyEl) {
      keyEl.classList.add("flash");
      setTimeout(() => keyEl.classList.remove("flash"), 160);
    }
    s.saving = true;
    s.error = null;
    renderFlag();
    try {
      const res = await api.label({ index: item.index, label, pass: s.pass });
      item.label = label;
      s.session.done = res.done;
      s.saving = false;
      const img = screen.querySelector(".label-img");
      if (img) img.classList.add("swap");
      setTimeout(() => {
        s.index = nextUnlabelled(s.index);
        preload();
        render();
      }, 120);
    } catch (e) {
      s.saving = false;
      s.error = e.message;
      toast(`Not saved: ${e.message}`, "error", 6000);
      render();
    }
  }

  function undo() {
    if (!s.session || s.saving) return;
    s.index = Math.max(0, Math.min(s.index, s.session.items.length) - 1);
    render();
  }

  function renderFlag() {
    const flag = screen.querySelector(".saved-flag");
    if (!flag) return;
    clear(flag);
    if (s.saving) {
      flag.dataset.state = "saving";
      flag.append(spinner(), "Saving");
    } else if (s.error) {
      flag.dataset.state = "error";
      flag.append(icon("alert", 13), "Not saved");
    } else if (s.session && s.session.done) {
      flag.dataset.state = "ok";
      flag.append(icon("check", 13), "Saved");
    } else {
      flag.dataset.state = "idle";
    }
  }

  function top(extra) {
    const sess = s.session;
    const pct = sess && sess.total ? (sess.done / sess.total) * 100 : 0;
    return h(
      "div",
      { class: "label-top" },
      labelMode() ? h("span", { class: "brand", "aria-label": "printready" }, logoMark(22), "printready") : null,
      h("span", { class: "pill" }, icon("lock", 11), sess ? `Blind labelling · pass ${sess.pass}` : "Blind labelling"),
      sess
        ? h(
            "div",
            { class: "label-progress", "aria-label": `${sess.done} of ${sess.total} labelled` },
            h("div", { class: "bar", role: "progressbar", "aria-valuemin": "0", "aria-valuemax": String(sess.total), "aria-valuenow": String(sess.done) }, h("i", { style: { width: pct + "%" } })),
            h("span", { class: "count" }, `${sess.done} / ${sess.total}`)
          )
        : h("span", { class: "grow" }),
      extra || null,
      h("span", { class: "saved-flag", "aria-live": "polite" })
    );
  }

  function render() {
    clear(screen);
    const demo = !labelMode();
    if (s.error === "none" || (demo && !(store.get().app || {}).demo && !s.session)) {
      // not in label mode and not in demo: explain how to start it
      screen.append(
        top(),
        h(
          "div",
          { class: "label-stage" },
          h(
            "div",
            { class: "label-intro" },
            empty(
              "lock",
              "Label mode starts from the command line",
              "Blind labelling runs in its own server so nothing from the tools is visible while you label. Run one of these, then label by keypress:"
            ),
            h("code", { class: "code", style: { textAlign: "left" } }, "printready realset label --split test --pass 1\nprintready realset label --split test --pass 2")
          )
        ),
        h("div")
      );
      return;
    }
    if (demo && !s.session && !s.intro) {
      s.intro = true;
    }
    if (demo && s.intro && !s.session) {
      screen.append(
        top(),
        h(
          "div",
          { class: "label-stage" },
          h(
            "div",
            { class: "label-intro" },
            h("div", { class: "hero-mark" }, logoMark(56)),
            h("h2", { style: { fontSize: "24px" } }, "Blind labelling (demo)"),
            h(
              "p",
              { class: "muted" },
              "This is the page Ebin labels the real set with: one image, one keypress, saved immediately. Pass 1 asks for an outcome; pass 2 shows proofs only. In this demo the labels go to out/demo-labels.jsonl."
            ),
            h(
              "div",
              { class: "row", style: { gap: "8px", justifyContent: "center" } },
              h("button", { class: "btn btn-primary btn-lg", type: "button", onClick: () => load(1) }, "Try pass 1 · outcomes"),
              h("button", { class: "btn btn-lg", type: "button", onClick: () => load(2) }, "Try pass 2 · proofs")
            )
          )
        ),
        h("div")
      );
      return;
    }
    if (!s.session) {
      screen.append(top(), h("div", { class: "label-stage" }, s.error ? empty("alert", "Could not load the labelling session", s.error, [h("button", { class: "btn", type: "button", onClick: () => load(s.pass) }, "Try again")]) : h("div", { class: "row hint" }, spinner(), "Loading")), h("div"));
      return;
    }
    const sess = s.session;
    const back = demo ? h("button", { class: "btn btn-ghost btn-sm", type: "button", onClick: () => ((s.session = null), (s.intro = true), render()) }, icon("chevronLeft", 14), "Passes") : null;
    if (s.index >= sess.items.length) {
      screen.append(
        top(back),
        h(
          "div",
          { class: "label-stage" },
          h(
            "div",
            { class: "label-done" },
            h("div", { class: "empty-icon", style: { width: "56px", height: "56px", background: "var(--pass-bg)", color: "var(--pass-ink)" } }, icon("check", 26)),
            h("h2", null, `Pass ${sess.pass} complete`),
            h("p", null, `${sess.done} of ${sess.total} labelled. Every label is already saved to`),
            h("code", null, sess.labels_file),
            h("p", null, sess.pass === 1 ? "Next: run both modes, then `printready realset label --pass 2`." : "Next: `printready realset eval`. You can close this tab."),
            h("button", { class: "btn", type: "button", onClick: undo }, icon("undo", 14), "Back to the last image")
          )
        ),
        h("div")
      );
      renderFlag();
      return;
    }
    const item = current();
    const keys = sess.keys || [];
    screen.append(
      top(back),
      h(
        "div",
        { class: "label-stage" },
        h(
          "figure",
          { class: "label-frame" },
          h("div", { class: "label-img" }, h("img", { class: "checker", src: item.url, alt: sess.pass === 1 ? "Artwork to label" : "Proof to label", decoding: "async" })),
          sess.caption ? h("figcaption", { class: "label-caption" }, sess.caption) : null,
          h("div", { class: "label-current", "aria-live": "polite" }, item.label ? `Labelled ${keys.find((k) => k.label === item.label).text.toLowerCase()} · press a key to change it` : `Image ${s.index + 1} of ${sess.total}`)
        )
      ),
      h(
        "div",
        { class: "label-keys", role: "group", "aria-label": "Labels" },
        keys.map((k) =>
          h(
            "button",
            { class: "label-key", type: "button", "data-label": k.label, "data-current": String(item.label === k.label), "aria-keyshortcuts": k.key, "aria-label": `${k.text}: ${k.hint || ""}`, onClick: () => choose(k.label) },
            kbd(k.key.toUpperCase()),
            h("span", { class: "label-key-text" }, h("b", null, k.text), k.hint ? h("small", null, k.hint) : null)
          )
        ),
        h("button", { class: "label-key undo", type: "button", "aria-keyshortcuts": "Backspace", disabled: s.index === 0, onClick: undo }, kbd("⌫"), "Undo")
      )
    );
    renderFlag();
    fitImage();
  }

  // keys: handled here directly (label mode has no other shortcuts competing)
  document.addEventListener("keydown", (e) => {
    if (store.get().screen !== "label" || !s.session || e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.target && ["INPUT", "SELECT", "TEXTAREA"].includes(e.target.tagName)) return;
    if (e.key === "Backspace") {
      e.preventDefault();
      undo();
      return;
    }
    const k = (s.session.keys || []).find((x) => x.key === e.key.toLowerCase());
    if (k && s.index < s.session.items.length) {
      e.preventDefault();
      choose(k.label);
    }
  });

  return {
    show(route) {
      if (labelMode()) {
        if (!s.session) load();
        else render();
        return;
      }
      if (route && route.pass && (!s.session || s.session.pass !== route.pass)) load(route.pass);
      else render();
    },
  };
}
