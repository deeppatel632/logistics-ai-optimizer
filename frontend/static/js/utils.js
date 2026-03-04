/**
 * frontend/static/js/utils.js
 *
 * Shared utilities for the Logistics AI dashboard.
 * Included by base.html so every page can use them without repeating code.
 *
 * Exports (module-free; attached to window.LogisticsUtils):
 *   apiFetch(path, options?)       — authenticated JSON fetch wrapper
 *   statusBadge(status)            — returns Tailwind class string for a status
 *   statusDot(status)              — returns hex colour for Leaflet / charts
 *   formatNumber(n)                — locale-aware number formatter
 *   relativeTime(isoString)        — "2 h ago" style relative time
 *   showToast(message, type?)      — transient toast notification
 *   confirmAction(message)         — async confirm dialog (returns bool)
 */

(function (global) {
  "use strict";

  // ── Status helpers ────────────────────────────────────────────────

  const STATUS_BADGE = {
    Pending:     "bg-yellow-900/50 text-yellow-300 border border-yellow-700/40",
    InTransit:   "bg-blue-900/50   text-blue-300   border border-blue-700/40",
    Delivered:   "bg-green-900/50  text-green-300  border border-green-700/40",
    Cancelled:   "bg-red-900/50    text-red-300    border border-red-700/40",
    Available:   "bg-green-900/50  text-green-300  border border-green-700/40",
    Unavailable: "bg-red-900/50    text-red-300    border border-red-700/40",
    ready:       "bg-green-900/50  text-green-300  border border-green-700/40",
    degraded:    "bg-yellow-900/50 text-yellow-300 border border-yellow-700/40",
    unknown:     "bg-gray-800      text-gray-400   border border-gray-700/40",
  };

  const STATUS_COLOR = {
    Pending:     "#f59e0b",
    InTransit:   "#3b82f6",
    Delivered:   "#22c55e",
    Cancelled:   "#ef4444",
    Available:   "#22c55e",
    Unavailable: "#ef4444",
  };

  /**
   * Returns a Tailwind class string for a pill badge.
   * @param {string} status
   * @returns {string}
   */
  function statusBadge(status) {
    return (
      "inline-flex items-center px-2 py-0.5 rounded text-xs font-medium " +
      (STATUS_BADGE[status] || STATUS_BADGE.unknown)
    );
  }

  /**
   * Returns a hex colour suitable for Chart.js / Leaflet markers.
   * @param {string} status
   * @returns {string}
   */
  function statusDot(status) {
    return STATUS_COLOR[status] || "#94a3b8";
  }

  // ── Number / date formatters ──────────────────────────────────────

  /**
   * Format a number with locale-aware thousands separators.
   * @param {number|null|undefined} n
   * @returns {string}
   */
  function formatNumber(n) {
    if (n == null || isNaN(n)) return "—";
    return Number(n).toLocaleString();
  }

  /**
   * Format a percentage with one decimal place.
   * @param {number|null|undefined} n
   * @returns {string}
   */
  function formatPct(n) {
    if (n == null || isNaN(n)) return "—";
    return Number(n).toFixed(1) + "%";
  }

  /**
   * Convert an ISO 8601 date string to "X minutes/hours/days ago".
   * @param {string} isoString
   * @returns {string}
   */
  function relativeTime(isoString) {
    if (!isoString) return "—";
    const diff = Date.now() - new Date(isoString).getTime();
    const seconds = Math.floor(diff / 1000);
    if (seconds < 60)   return `${seconds}s ago`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
    return `${Math.floor(seconds / 86400)}d ago`;
  }

  // ── Toast notifications ──────────────────────────────────────────

  let _toastContainer = null;

  function _ensureContainer() {
    if (_toastContainer) return _toastContainer;
    _toastContainer = document.createElement("div");
    _toastContainer.style.cssText =
      "position:fixed;bottom:1.5rem;right:1.5rem;z-index:9999;" +
      "display:flex;flex-direction:column;gap:0.5rem;pointer-events:none;";
    document.body.appendChild(_toastContainer);
    return _toastContainer;
  }

  const TOAST_STYLES = {
    success: "bg-green-900 border border-green-700 text-green-200",
    error:   "bg-red-900   border border-red-700   text-red-200",
    info:    "bg-blue-900  border border-blue-700  text-blue-200",
    warning: "bg-yellow-900 border border-yellow-700 text-yellow-200",
  };

  /**
   * Display a transient toast notification.
   * @param {string} message
   * @param {"success"|"error"|"info"|"warning"} [type="info"]
   * @param {number} [durationMs=3500]
   */
  function showToast(message, type = "info", durationMs = 3500) {
    const container = _ensureContainer();
    const el = document.createElement("div");
    el.className =
      "px-4 py-3 rounded-lg shadow-2xl text-sm max-w-xs pointer-events-auto " +
      "transition-all duration-300 opacity-0 translate-y-2 " +
      (TOAST_STYLES[type] || TOAST_STYLES.info);
    el.textContent = message;
    container.appendChild(el);

    // Animate in
    requestAnimationFrame(() => {
      el.classList.remove("opacity-0", "translate-y-2");
      el.classList.add("opacity-100", "translate-y-0");
    });

    // Animate out and remove
    setTimeout(() => {
      el.classList.add("opacity-0", "translate-y-2");
      el.addEventListener("transitionend", () => el.remove(), { once: true });
    }, durationMs);
  }

  // ── Confirm dialog ──────────────────────────────────────────────

  /**
   * Show a styled async confirm dialog.
   * Returns a Promise<boolean>.
   * @param {string} message
   * @returns {Promise<boolean>}
   */
  function confirmAction(message) {
    return new Promise((resolve) => {
      // Fallback to window.confirm if no modal library loaded
      resolve(window.confirm(message));
    });
  }

  // ── Authenticated fetch wrapper ──────────────────────────────────

  /**
   * Wrapper around fetch() that:
   *   - Always requests JSON
   *   - Redirects to /login on 401
   *   - Returns parsed JSON or throws an Error with .status
   *
   * @param {string} path   — Flask proxy path e.g. "/api/vehicles"
   * @param {RequestInit} [options]
   * @returns {Promise<any>}
   */
  async function apiFetch(path, options = {}) {
    const defaults = {
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    };
    const merged = { ...defaults, ...options, headers: { ...defaults.headers, ...(options.headers || {}) } };

    const response = await fetch(path, merged);

    if (response.status === 401) {
      window.location.href = "/login";
      return;
    }

    if (!response.ok) {
      let detail = response.statusText;
      try {
        const body = await response.json();
        detail = body.detail || body.error || detail;
      } catch (_) {}
      const err = new Error(`API error ${response.status}: ${detail}`);
      err.status = response.status;
      throw err;
    }

    const ct = response.headers.get("content-type") || "";
    return ct.includes("application/json") ? response.json() : response.text();
  }

  // ── Utilisation bar builder ──────────────────────────────────────

  /**
   * Build a colour-coded utilisation bar HTML string.
   * @param {number} pct   0-100
   * @param {string} [id]  optional DOM id for the inner bar
   * @returns {string}
   */
  function utilisationBar(pct, id = "") {
    const clamped = Math.min(100, Math.max(0, pct || 0));
    const color =
      clamped > 85 ? "#ef4444" : clamped > 60 ? "#f59e0b" : "#22c55e";
    const idAttr = id ? `id="${id}"` : "";
    return `
      <div class="flex items-center gap-2">
        <div class="flex-1 h-1.5 bg-gray-800 rounded-full overflow-hidden">
          <div ${idAttr} class="h-full rounded-full transition-all duration-500"
               style="width:${clamped}%;background:${color}"></div>
        </div>
        <span class="text-xs text-gray-400 w-9 text-right">${clamped.toFixed(1)}%</span>
      </div>`;
  }

  // ── Public API ───────────────────────────────────────────────────

  global.LogisticsUtils = {
    apiFetch,
    statusBadge,
    statusDot,
    formatNumber,
    formatPct,
    relativeTime,
    showToast,
    confirmAction,
    utilisationBar,
  };
})(window);
