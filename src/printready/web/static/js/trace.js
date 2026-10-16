// The agent trace, streaming live: what the model was given, then one card per turn with its
// text, each tool call (arguments, result, time, the JSON it got back), any model call made inside
// a tool (read_text's vision call), the image it looked at, tokens, cost and latency, and a running
// cost total. A compact timeline sits on top. The outcome is never the model's: the end card says
// how it was computed. Errors (for example an API out of credit) read as plain explanations.

import { h, clear } from "./dom.js";
import { icon } from "./icons.js";
import { OUTCOMES, TOOLS, explainError, ms, tokens, usd } from "./format.js";
import { codeJSON, dots, lightbox, outcomeChip } from "./ui.js";

const open = new Set(); // expanded JSON blocks and the system prompt (survive re-renders)
const FIX_TOOLS = ["remove_background", "pad_canvas", "add_border", "bridge_islands", "fit_shape"];

function callKind(call) {
  const r = String(call.result || "").toLowerCase();
  if (call.name === "handoff") return "handoff";
  if (call.name === "finish") return r.startsWith("finished") ? "ok" : "refused";
  if (r.startsWith("refused") || r.includes(": refused") || r.startsWith("error") || r.startsWith("bad") || r.startsWith("unknown") || r.includes("damaged")) return "refused";
  if (!FIX_TOOLS.includes(call.name)) return "neutral";
  return "ok";
}

function argsInline(args) {
  if (!args || typeof args !== "object") return args ? String(args) : "()";
  const keys = Object.keys(args);
  if (!keys.length) return "()";
  if (keys.length === 1 && typeof args[keys[0]] === "string" && args[keys[0]].length < 24) return `(${keys[0]}="${args[keys[0]]}")`;
  return `(${keys.join(", ")})`;
}

function toggle(key, labelOpen, labelClosed, onChange) {
  const expanded = open.has(key);
  return h(
    "button",
    {
      class: "link-btn",
      type: "button",
      "aria-expanded": String(expanded),
      onClick: (e) => {
        if (open.has(key)) open.delete(key);
        else open.add(key);
        const now = open.has(key);
        e.currentTarget.setAttribute("aria-expanded", String(now));
        e.currentTarget.textContent = now ? labelOpen : labelClosed;
        onChange(now);
      },
    },
    expanded ? labelOpen : labelClosed
  );
}

// The model call(s) a tool made itself, e.g. read_text's vision call.
function subCall(c) {
  const failed = c.status && c.status !== "ok";
  return h(
    "div",
    { class: "subcall" + (failed ? " failed" : "") },
    h("span", { class: "subcall-arrow", "aria-hidden": "true" }, "↳"),
    h("span", null, h("b", null, `${c.purpose || "model"} call`), c.model ? ` · ${String(c.model).replace(/^xai:/, "")}` : ""),
    failed
      ? h("span", { class: "subcall-err" }, c.error || c.status)
      : h(
          "span",
          { class: "subcall-meta" },
          `${tokens(c.tokens_in)} in`,
          c.tokens_cached ? ` (${tokens(c.tokens_cached)} cached)` : "",
          ` · ${tokens(c.tokens_out)} out · ${usd(c.cost_usd || 0)} · ${ms(c.latency_ms)}`
        )
  );
}

function renderCall(turn, call, idx, subcalls) {
  const kind = callKind(call);
  const meta = TOOLS[call.name] || { icon: "tool" };
  const key = `json:${turn.n}:${idx}`;
  const statusText = { ok: "ok", refused: "refused", handoff: "handoff", neutral: "done" }[kind];
  const statusIcon = { ok: "check", refused: "x", handoff: "handoff", neutral: "check" }[kind];
  const args = call.arguments && typeof call.arguments === "object" ? call.arguments : null;
  const quote =
    call.name === "finish" && args && args.customer_message
      ? h("blockquote", { class: "message-quote" }, args.customer_message)
      : call.name === "handoff" && args
        ? h("blockquote", { class: "message-quote handoff" }, h("b", null, args.reason || "handoff"), args.person_notes ? h("div", { style: { marginTop: "4px" } }, Array.isArray(args.person_notes) ? args.person_notes.join(" ") : args.person_notes) : null)
        : null;
  const details = call.content !== undefined ? call.content : null;
  const jsonBox = details ? h("div", { class: "call-args", hidden: !open.has(key) }, h("div", { class: "hint", style: { margin: "6px 0 4px" } }, "The tool result as the model received it"), codeJSON(details)) : null;
  return h(
    "div",
    { class: "call", "data-kind": kind },
    h(
      "div",
      { class: "call-head" },
      h("span", { class: "call-icon" }, icon(meta.icon, 13)),
      h("code", { class: "call-name" }, call.name),
      call.name === "finish" || call.name === "handoff" ? null : h("span", { class: "call-args-inline", title: args ? JSON.stringify(args) : "" }, argsInline(args)),
      h("span", { class: "call-right" }, call.ms !== undefined && call.ms !== null ? h("span", { class: "call-ms" }, ms(call.ms)) : null, h("span", { class: "call-status", "data-kind": kind }, icon(statusIcon, 12), statusText))
    ),
    quote ? h("div", { class: "call-quote" }, quote) : null,
    h("div", { class: "call-result" }, h("span", { class: "arrow" }, "→"), h("span", { class: "grow" }, call.result || "(no result)"), details ? toggle(key, "Hide JSON", "JSON", (now) => (jsonBox.hidden = !now)) : null),
    subcalls.length ? h("div", { class: "subcalls" }, subcalls.map(subCall)) : null,
    jsonBox
  );
}

function endKind(turn) {
  const calls = turn.tool_calls || [];
  if (calls.some((c) => c.name === "handoff")) return "handoff";
  if (calls.some((c) => c.name === "finish" && callKind(c) === "ok")) return "finish";
  return null;
}

function errorBlock(turn) {
  const e = explainError(turn.error);
  const key = `err:${turn.n}`;
  const rawBox = h("pre", { class: "code", hidden: !open.has(key) }, e.raw);
  return h(
    "div",
    { class: "turn-error", role: "status" },
    h("div", { class: "turn-error-head" }, icon("alert", 16), h("b", null, e.title)),
    h("p", null, e.body),
    h("div", null, toggle(key, "Hide the message", "Show the API message", (now) => (rawBox.hidden = !now))),
    rawBox
  );
}

function turnCost(t) {
  return (t.cost_usd || 0) + (t.sub_calls || []).reduce((a, c) => a + (c.cost_usd || 0), 0);
}

function renderTurn(turn, running) {
  const t = turn.tokens || {};
  const end = endKind(turn);
  const image = turn.image;
  const calls = turn.tool_calls || [];
  const subs = turn.sub_calls || [];
  const card = h(
    "li",
    { class: "turn", id: `turn-${turn.n}`, "data-end": end, "data-error": turn.error ? "true" : null },
    h("div", { class: "turn-n", "aria-hidden": "true" }, turn.error ? icon("alert", 14) : turn.n),
    h(
      "article",
      { class: "turn-card", "aria-label": `Turn ${turn.n}` },
      h(
        "header",
        { class: "turn-head" },
        h("span", { class: "who" }, `Turn ${turn.n}`),
        end === "finish" ? h("span", { class: "pill pill-accent" }, "finish") : end === "handoff" ? h("span", { class: "pill" }, "handoff") : null,
        h(
          "span",
          { class: "turn-meta" },
          turn.tokens
            ? h("span", { "data-tip": "Prompt tokens (of which cached) · output tokens" }, icon("tokens", 12), h("b", null, tokens(t.in)), t.cached ? h("span", null, `(${tokens(t.cached)} cached)`) : null, "·", h("b", null, tokens(t.out)))
            : null,
          turn.latency_ms !== undefined && turn.latency_ms !== null ? h("span", { "data-tip": "Model latency for this turn" }, icon("clock", 12), h("b", null, ms(turn.latency_ms))) : null,
          h("span", { "data-tip": subs.length ? "This turn, including the model call inside a tool" : "Cost of this turn" }, icon("coin", 12), h("b", null, usd(turnCost(turn)))),
          h("span", { class: "running", "data-tip": "Running total for the run so far", "data-tip-pos": "left" }, "Σ ", usd(running))
        )
      ),
      h(
        "div",
        { class: "turn-body" },
        turn.error ? errorBlock(turn) : turn.text ? h("p", { class: "turn-text" }, turn.text) : null,
        calls.map((c, i) => renderCall(turn, c, i, c.name === "read_text" ? subs : [])),
        subs.length && !calls.some((c) => c.name === "read_text") ? h("div", { class: "subcalls" }, subs.map(subCall)) : null,
        !calls.length && !turn.error ? h("div", { class: "turn-nudge" }, icon("info", 14), h("span", null, "The model answered without calling a tool, so the loop reminded it: call a tool, or end with finish or handoff.")) : null,
        image && image.url
          ? h(
              "figure",
              { class: "turn-image" },
              h("button", { class: "checker checker-sm", type: "button", "aria-label": "Enlarge the image the model saw", onClick: () => lightbox(image.url, `Shown to the model after turn ${turn.n}`) }, h("img", { src: image.url, alt: `Image shown to the model: ${image.name || ""}`, loading: "lazy" })),
              h(
                "figcaption",
                null,
                h("b", null, "What the model looked at"),
                h("span", null, "Sent as a user message after the tool results (tool messages cannot carry images), downscaled to 768 px."),
                h("span", { class: "mono" }, image.name || "")
              )
            )
          : null,
        turn.model || turn.request_sha256 || turn.finish_reason
          ? h(
              "div",
              { class: "turn-foot" },
              turn.model ? h("span", { class: "mono" }, turn.model) : null,
              turn.finish_reason ? h("span", null, turn.finish_reason) : null,
              turn.request_sha256 ? h("span", { class: "mono", title: `request sha256 ${turn.request_sha256}` }, "req " + String(turn.request_sha256).slice(0, 10)) : null
            )
          : null
      )
    )
  );
  return card;
}

// What the model was given before turn 1: the system prompt, the order and the uploaded image.
function contextCard(ctx, run) {
  if (!ctx) return null;
  const tools = Array.isArray(ctx.tools) ? ctx.tools : [];
  const promptBox = h("pre", { class: "code prompt-text", hidden: !open.has("prompt") }, ctx.system_prompt || "");
  return h(
    "li",
    { class: "turn context" },
    h("div", { class: "turn-n", "aria-hidden": "true" }, icon("book", 14)),
    h(
      "article",
      { class: "turn-card", "aria-label": "What the model was given" },
      h("header", { class: "turn-head" }, h("span", { class: "who" }, "What the model was given"), h("span", { class: "turn-meta" }, h("span", null, `${String(ctx.model || run.model || "").replace(/^xai:/, "")} · up to ${ctx.max_turns || 8} turns · temperature 0`))),
      h(
        "div",
        { class: "turn-body" },
        h(
          "div",
          { class: "context-grid" },
          ctx.image && ctx.image.url
            ? h("button", { class: "context-img checker checker-sm", type: "button", "aria-label": "Enlarge the uploaded image as sent", onClick: () => lightbox(ctx.image.url, "The upload, as sent to the model") }, h("img", { src: ctx.image.url, alt: "" }))
            : null,
          h(
            "div",
            { class: "context-text" },
            h("p", null, h("b", null, "The order"), ` · a ${(run.spec && run.spec.size_in) || 3} in die-cut sticker, the deterministic check report on the upload, and the upload itself at 768 px.`),
            h("p", null, h("b", null, "Tools"), " · ", tools.length ? tools.map((t) => h("code", { class: "tool-chip" }, t)) : "–"),
            ctx.system_prompt
              ? h("p", null, h("b", null, "System prompt"), ` · ${ctx.system_prompt.length.toLocaleString()} characters, the profile's rules filled in with their sources. `, toggle("prompt", "Hide", "Read it", (now) => (promptBox.hidden = !now)))
              : null
          )
        ),
        promptBox
      )
    )
  );
}

function stat(label, value, unit, sub) {
  return h("div", { class: "stat" }, h("div", { class: "stat-label" }, label), h("div", { class: "stat-value" }, value, unit ? h("small", null, unit) : null), sub ? h("div", { class: "stat-sub" }, sub) : null);
}

function timeline(turns, host) {
  const parts = turns.map((t) => ({ t, w: (t.latency_ms || 0) + (t.tool_calls || []).reduce((a, c) => a + (c.ms || 0), 0) }));
  const total = parts.reduce((a, p) => a + p.w, 0) || 1;
  return h(
    "div",
    { class: "tl-strip", role: "group", "aria-label": "Turns over time" },
    parts.map(({ t, w }) =>
      h(
        "button",
        {
          type: "button",
          class: "tl-seg",
          "data-end": endKind(t),
          "data-error": t.error ? "true" : null,
          style: { flexGrow: String(Math.max(w, total * 0.05)) },
          "data-tip": `Turn ${t.n} · ${ms(t.latency_ms)} model${(t.tool_calls || []).length ? " · " + t.tool_calls.map((c) => c.name).join(", ") : ""}`,
          "aria-label": `Turn ${t.n}`,
          onClick: () => {
            const el = host.querySelector(`#turn-${t.n}`);
            if (el) {
              el.scrollIntoView({ behavior: "smooth", block: "center" });
              el.classList.add("highlight");
              setTimeout(() => el.classList.remove("highlight"), 1200);
            }
          },
        },
        h("span", { class: "tl-seg-n" }, t.error ? "!" : t.n),
        h("span", { class: "tl-seg-tools" }, (t.tool_calls || []).slice(0, 3).map((c) => icon((TOOLS[c.name] || { icon: "tool" }).icon, 12)))
      )
    )
  );
}

let pendingTimer = null;

export function renderTrace(host, run, opts = {}) {
  const nearBottom = host.scrollHeight - host.scrollTop - host.clientHeight < 80;
  const prevTop = host.scrollTop;
  clear(host);
  if (pendingTimer) {
    clearInterval(pendingTimer);
    pendingTimer = null;
  }
  const turns = run.turns || [];
  const live = run.status === "running" || run.status === "queued";
  const res = run.result;
  const totIn = turns.reduce((a, t) => a + ((t.tokens && t.tokens.in) || 0), 0);
  const totCached = turns.reduce((a, t) => a + ((t.tokens && t.tokens.cached) || 0), 0);
  const totOut = turns.reduce((a, t) => a + ((t.tokens && t.tokens.out) || 0), 0);
  const runningCost = turns.reduce((a, t) => a + turnCost(t), 0);
  const totalCost = res && typeof res.cost_usd === "number" ? res.cost_usd : runningCost;
  const modelTime = turns.reduce((a, t) => a + (t.latency_ms || 0), 0);
  const scripted = turns.some((t) => t.model === "demo-script");
  const ended = turns.length ? endKind(turns[turns.length - 1]) : null;
  const errored = turns.find((t) => t.error);
  const ctx = run.trace_context;
  const inner = h("div", { class: "trace-inner" });

  inner.append(
    h(
      "div",
      { class: "trace-head" },
      h(
        "div",
        null,
        h("h2", null, "Agent trace"),
        h(
          "p",
          null,
          scripted
            ? "Scripted demo model over the real tools: every tool result, fix and the outcome are real; the model's tokens are scripted, cost is at grok-4.3 prices, nothing is charged."
            : `${String((ctx && ctx.model) || run.model || "The model").replace(/^xai:/, "")} with tools, temperature 0. Every call is written to log.jsonl before its result is used.` +
              (turns.length && !turns.some((t) => t.text) ? " This model answers with tool calls only, no text between them." : "")
        )
      ),
      res
        ? h("div", { class: "trace-verdict" }, outcomeChip(res.outcome), h("span", { class: "hint" }, "computed by the rules, not the model"))
        : live
          ? h("span", { class: "pill pill-accent" }, h("span", { class: "spinner", style: { width: "10px", height: "10px" } }), "live")
          : null
    )
  );
  inner.append(
    h(
      "div",
      { class: "trace-stats" },
      stat("Turns", String(turns.length), ` / ${(ctx && ctx.max_turns) || 8}`, errored ? "stopped by an error" : ended === "handoff" ? "ended in a handoff" : ended === "finish" ? "ended in finish" : live ? "streaming" : ""),
      stat("Prompt tokens", tokens(totIn), null, totCached ? `${Math.round((totCached / Math.max(1, totIn)) * 100)}% from cache` : "no cache hits yet"),
      stat("Output tokens", tokens(totOut)),
      stat("Cost", usd(totalCost), null, scripted ? "simulated, not charged" : turns.some((t) => (t.sub_calls || []).length) ? "turns + calls inside tools" : "all turns"),
      // a replay's wall clock is the replay's; the saved run's own elapsed time is the real one
      stat("Model time", ms(modelTime), null, res && res.elapsed_s ? `${ms(res.elapsed_s * 1000)} for the whole run` : run.duration_ms && !run.demo ? `${ms(run.duration_ms)} wall clock` : "")
    )
  );
  if (turns.length) inner.append(timeline(turns, host));

  const list = h("ol", { class: "turns" });
  const ctxCard = contextCard(ctx, run);
  if (ctxCard) list.append(ctxCard);
  if (!turns.length && !live) {
    list.append(
      h(
        "li",
        { class: "turn system" },
        h("div", { class: "turn-n" }, icon("info", 14)),
        h("div", { class: "turn-card" }, h("div", { class: "turn-body" }, h("p", { class: "turn-text notext" }, run.status === "error" ? "The run failed before the model answered." : "No model call was made for this run (for example, the file could not be opened).")))
      )
    );
  }
  let running = 0;
  for (const t of turns) {
    running += turnCost(t);
    list.append(renderTurn(t, running));
  }
  if (live) {
    const since = h("span", { class: "mono" }, "");
    const started = Date.now();
    list.append(
      h(
        "li",
        { class: "turn pending" },
        h("div", { class: "turn-n" }, turns.length + 1),
        h("div", { class: "turn-card" }, h("div", { class: "turn-body" }, dots(), h("span", null, turns.length ? "Running the tools, then waiting for the model" : "Sending the order, the check report and the image to the model"), since))
      )
    );
    pendingTimer = setInterval(() => {
      if (!since.isConnected) {
        clearInterval(pendingTimer);
        pendingTimer = null;
        return;
      }
      since.textContent = `${((Date.now() - started) / 1000).toFixed(1)} s`;
    }, 200);
  } else if (res) {
    const meta = OUTCOMES[res.outcome];
    const text = (res.after && res.after.findings) || [];
    list.append(
      h(
        "li",
        { class: "turn system end" },
        h("div", { class: "turn-n" }, icon("flag", 14)),
        h(
          "div",
          { class: "turn-card" },
          h(
            "div",
            { class: "turn-body" },
            h(
              "p",
              { class: "turn-text" },
              h("b", null, `Outcome: ${meta ? meta.label : res.outcome}. `),
              res.handoff_reason ? `The run ended in a handoff (${res.handoff_reason}). ` : "",
              "The same outcome rule as rules mode ran on the final checks",
              text.some((f) => f.check === "text_garbled") ? ", the text check" : "",
              " and whether the run handed off. ",
              h("span", { class: "muted" }, `Total ${usd(totalCost)}.`)
            )
          )
        )
      )
    );
  }
  inner.append(list);
  host.append(inner);
  if (opts.live !== false && live && nearBottom) host.scrollTop = host.scrollHeight;
  else host.scrollTop = prevTop;
}
