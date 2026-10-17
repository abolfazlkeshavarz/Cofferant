/* Cofferant shared client helpers (no dependencies) */
(function () {
  "use strict";
  const $ = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));
  const FA = "۰۱۲۳۴۵۶۷۸۹";

  const safe = {
    get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* private mode */ } },
  };

  function fa(n) { return String(n).replace(/\d/g, d => FA[d]); }
  function money(n) { return fa(Number(n || 0).toLocaleString("en-US").replace(/,/g, "٬")); }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }
  function csrf() {
    const m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : (($("input[name=csrfmiddlewaretoken]") || {}).value || "");
  }

  /** fetch wrapper: JSON in/out, CSRF, timeout, friendly errors. Resolves {ok,status,data}. */
  async function api(url, opts) {
    opts = opts || {};
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), opts.timeout || 15000);
    const headers = { "X-CSRFToken": csrf(), "X-Requested-With": "XMLHttpRequest" };
    let body = opts.body;
    if (body && !(body instanceof FormData) && typeof body !== "string") {
      headers["Content-Type"] = "application/json";
      body = JSON.stringify(body);
    }
    try {
      const r = await fetch(url, { method: opts.method || (body ? "POST" : "GET"), headers, body, signal: ctrl.signal, credentials: "same-origin" });
      let data = null;
      try { data = await r.json(); } catch (e) { /* non-JSON (e.g. login redirect) */ }
      if (r.redirected && /login/.test(r.url)) return { ok: false, status: 401, data: { error: "نشست شما منقضی شده؛ دوباره وارد شوید." } };
      return { ok: r.ok && (!data || data.ok !== false), status: r.status, data: data || {} };
    } catch (e) {
      return { ok: false, status: 0, data: { error: "ارتباط با سرور برقرار نشد. اینترنت خود را بررسی کنید." } };
    } finally { clearTimeout(timer); }
  }

  function toast(msg, kind) {
    let box = $(".toasts");
    if (!box) {
      box = document.createElement("div");
      box.className = "toasts";
      box.setAttribute("role", "status");
      box.setAttribute("aria-live", "polite");
      document.body.appendChild(box);
    }
    const t = document.createElement("div");
    t.className = "toast " + (kind || "");
    t.textContent = msg;
    box.appendChild(t);
    setTimeout(() => { t.style.transition = "opacity .3s"; t.style.opacity = 0; setTimeout(() => t.remove(), 300); }, 3200);
  }

  function icon(name, cls) {
    return '<svg class="icon ' + (cls || "") + '" aria-hidden="true"><use href="#i-' + name + '"/></svg>';
  }

  /* ---- Theme ---- */
  function toggleTheme() {
    const next = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    safe.set("theme", next);
  }

  /* ---- Bottom sheet helpers ---- */
  function openSheet(id) {
    const el = document.getElementById(id), bd = $(".backdrop");
    if (!el) return;
    el.classList.add("is-open");
    if (bd) bd.classList.add("is-open");
    document.body.style.overflow = "hidden";
  }
  function closeSheet(id) {
    const el = id ? document.getElementById(id) : $(".sheet.is-open"), bd = $(".backdrop");
    if (el) el.classList.remove("is-open");
    if (bd) bd.classList.remove("is-open");
    document.body.style.overflow = "";
  }

  document.addEventListener("click", function (e) {
    if (e.target.closest("[data-theme-toggle]")) { toggleTheme(); return; }
    const o = e.target.closest("[data-open-sheet]");
    if (o) { openSheet(o.dataset.openSheet); return; }
    if (e.target.closest("[data-close-sheet]") || e.target.classList.contains("backdrop")) { closeSheet(); return; }

    // <button data-post="/url" data-confirm="..." data-reload> -> POST then reload
    const p = e.target.closest("[data-post]");
    if (p) {
      e.preventDefault();
      if (p.dataset.confirm && !confirm(p.dataset.confirm)) return;
      p.disabled = true;
      const fd = new FormData();
      if (p.dataset.fields) {
        try { const f = JSON.parse(p.dataset.fields); Object.keys(f).forEach(k => fd.append(k, f[k])); } catch (er) { /* ignore */ }
      }
      api(p.dataset.post, { body: fd }).then(r => {
        if (r.ok) { if (p.dataset.reload !== undefined) location.reload(); }
        else { toast((r.data && r.data.error) || "خطا در انجام عملیات", "bad"); p.disabled = false; }
      });
    }
  });
  document.addEventListener("keydown", e => { if (e.key === "Escape") closeSheet(); });

  window.addEventListener("DOMContentLoaded", () => {
    $$(".messages .msg").forEach((m, i) => setTimeout(() => {
      m.style.transition = "opacity .4s"; m.style.opacity = 0; setTimeout(() => m.remove(), 400);
    }, 4000 + i * 600));
    $$("[data-money]").forEach(el => { el.textContent = money(el.dataset.money); });
  });

  window.App = { $, $$, fa, money, esc, api, toast, icon, safe, openSheet, closeSheet, csrf };
})();
