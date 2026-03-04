/**
 * analytics.js
 *
 * Data flow:
 *   Chart.js  ←  analytics.js  ←  Flask /api/analytics/data
 *                                       ↕
 *                               FastAPI /shipments
 *                               FastAPI /streaming/vehicles
 *                               FastAPI /analytics/kpis
 *
 * On page load:
 *   1. loadAnalytics() fires, calling GET /api/analytics/data
 *   2. Flask aggregates shipments + vehicles + warehouse_load into chart-ready JSON
 *   3. renderCharts() receives the payload and builds / rebuilds four Chart.js charts:
 *        - shipmentsOverTimeChart  (line)
 *        - statusDistributionChart (doughnut)
 *        - vehicleUtilizationChart (horizontal bar)
 *        - inventoryActivityChart  (grouped bar)
 *   4. KPI stat cards are already server-side rendered via Jinja; charts update live.
 *   5. "Refresh" button re-calls loadAnalytics() to fetch fresh data.
 */

'use strict';

// ── Chart.js global defaults for dark theme ──────────────────────────────────
Chart.defaults.color          = '#9ca3af';   // gray-400
Chart.defaults.borderColor    = 'rgba(75, 85, 99, 0.35)';
Chart.defaults.font.family    = "'Inter', sans-serif";
Chart.defaults.font.size      = 11;

// ── Chart registry (prevents duplicate canvas errors on refresh) ──────────────
const _charts = {};

function _destroyIfExists(id) {
  if (_charts[id]) {
    _charts[id].destroy();
    delete _charts[id];
  }
}

// ── Colour palettes ───────────────────────────────────────────────────────────
const PALETTE_STATUS = {
  CREATED:    { bg: 'rgba(96,  165, 250, 0.75)', border: '#60a5fa' },   // blue-400
  IN_TRANSIT: { bg: 'rgba(251, 191,  36, 0.75)', border: '#fbbf24' },   // yellow-400
  DELIVERED:  { bg: 'rgba(52,  211, 153, 0.75)', border: '#34d399' },   // emerald-400
  CANCELLED:  { bg: 'rgba(248, 113, 113, 0.75)', border: '#f87171' },   // red-400
};
const PALETTE_DEFAULT = [
  'rgba(96,  165, 250, 0.75)',  // blue-400
  'rgba(52,  211, 153, 0.75)',  // emerald-400
  'rgba(251, 191,  36, 0.75)',  // yellow-400
  'rgba(248, 113, 113, 0.75)',  // red-400
  'rgba(167, 139, 250, 0.75)',  // violet-400
  'rgba( 45, 212, 191, 0.75)',  // teal-400
  'rgba(251, 146,  60, 0.75)',  // orange-400
  'rgba(129, 140, 248, 0.75)',  // indigo-400
];

function _pickColors(labels, paletteMap) {
  return labels.map((l, i) =>
    paletteMap && paletteMap[l]
      ? paletteMap[l].bg
      : PALETTE_DEFAULT[i % PALETTE_DEFAULT.length]
  );
}
function _pickBorders(labels, paletteMap) {
  return labels.map((l, i) =>
    paletteMap && paletteMap[l]
      ? paletteMap[l].border
      : PALETTE_DEFAULT[i % PALETTE_DEFAULT.length].replace('0.75', '1')
  );
}

// ── Shared axis/grid styling ───────────────────────────────────────────────────
const GRID_OPTS = {
  color: 'rgba(75, 85, 99, 0.3)',
  drawBorder: false,
};
const TICK_OPTS = { color: '#6b7280', maxRotation: 45 };

// ── Helper: show/hide empty-state message ─────────────────────────────────────
function _showEmpty(id, empty) {
  const canvas = document.getElementById(id);
  const msg    = document.getElementById(id.replace('Chart', '') + '-empty');
  if (!canvas) return;
  canvas.style.display  = empty ? 'none' : 'block';
  if (msg) msg.classList.toggle('hidden', !empty);
}

// ─────────────────────────────────────────────────────────────────────────────
// 1. Shipments Over Time — Line chart
// ─────────────────────────────────────────────────────────────────────────────
function renderShipmentsOverTime(data) {
  const id = 'shipmentsOverTimeChart';
  _destroyIfExists(id);

  const empty = !data.labels || data.labels.length === 0;
  _showEmpty(id, empty);
  if (empty) return;

  const ctx = document.getElementById(id).getContext('2d');

  // Gradient fill under line
  const gradient = ctx.createLinearGradient(0, 0, 0, 280);
  gradient.addColorStop(0,   'rgba(96, 165, 250, 0.35)');
  gradient.addColorStop(1,   'rgba(96, 165, 250, 0.00)');

  _charts[id] = new Chart(ctx, {
    type: 'line',
    data: {
      labels: data.labels,
      datasets: [{
        label:           'Shipments',
        data:            data.data,
        borderColor:     '#60a5fa',
        backgroundColor: gradient,
        borderWidth:     2,
        pointRadius:     3,
        pointHoverRadius: 5,
        pointBackgroundColor: '#60a5fa',
        fill:            true,
        tension:         0.35,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: '#1f2937',
          titleColor:      '#e5e7eb',
          bodyColor:       '#9ca3af',
          borderColor:     '#374151',
          borderWidth:     1,
        },
      },
      scales: {
        x: { grid: GRID_OPTS, ticks: { ...TICK_OPTS, maxTicksLimit: 10 } },
        y: {
          grid:       GRID_OPTS,
          ticks:      { ...TICK_OPTS, stepSize: 1 },
          beginAtZero: true,
          title: { display: true, text: 'Shipments', color: '#6b7280', font: { size: 10 } },
        },
      },
    },
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// 2. Shipment Status Distribution — Doughnut chart
// ─────────────────────────────────────────────────────────────────────────────
function renderStatusDistribution(data) {
  const id = 'statusDistributionChart';
  _destroyIfExists(id);

  const empty = !data.labels || data.labels.length === 0 ||
                data.data.every(v => v === 0);
  _showEmpty(id, empty);
  if (empty) return;

  const ctx = document.getElementById(id).getContext('2d');
  _charts[id] = new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels: data.labels,
      datasets: [{
        data:            data.data,
        backgroundColor: _pickColors(data.labels,  PALETTE_STATUS),
        borderColor:     _pickBorders(data.labels, PALETTE_STATUS),
        borderWidth:     2,
        hoverOffset:     8,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      cutout: '62%',
      plugins: {
        legend: {
          position: 'right',
          labels: {
            color:     '#9ca3af',
            boxWidth:  12,
            boxHeight: 12,
            padding:   14,
            font: { size: 11 },
          },
        },
        tooltip: {
          backgroundColor: '#1f2937',
          titleColor:      '#e5e7eb',
          bodyColor:       '#9ca3af',
          borderColor:     '#374151',
          borderWidth:     1,
          callbacks: {
            label: ctx => {
              const total = ctx.dataset.data.reduce((a, b) => a + b, 0);
              const pct   = total ? ((ctx.raw / total) * 100).toFixed(1) : 0;
              return ` ${ctx.raw} (${pct}%)`;
            },
          },
        },
      },
    },
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// 3. Vehicle Utilisation — Horizontal bar chart
// ─────────────────────────────────────────────────────────────────────────────
function renderVehicleUtilization(data) {
  const id = 'vehicleUtilizationChart';
  _destroyIfExists(id);

  const empty = !data.labels || data.labels.length === 0;
  _showEmpty(id, empty);
  if (empty) return;

  const ctx = document.getElementById(id).getContext('2d');
  _charts[id] = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: data.labels,
      datasets: [{
        label:           'Shipments Handled',
        data:            data.data,
        backgroundColor: data.labels.map((_, i) => PALETTE_DEFAULT[i % PALETTE_DEFAULT.length]),
        borderColor:     data.labels.map((_, i) =>
          PALETTE_DEFAULT[i % PALETTE_DEFAULT.length].replace('0.75', '1')),
        borderWidth:     1,
        borderRadius:    4,
      }],
    },
    options: {
      indexAxis: 'y',           // horizontal bars
      responsive: true,
      maintainAspectRatio: true,
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: '#1f2937',
          titleColor:      '#e5e7eb',
          bodyColor:       '#9ca3af',
          borderColor:     '#374151',
          borderWidth:     1,
        },
      },
      scales: {
        x: {
          grid:        GRID_OPTS,
          ticks:       { ...TICK_OPTS, stepSize: 1 },
          beginAtZero: true,
          title: { display: true, text: 'Shipments', color: '#6b7280', font: { size: 10 } },
        },
        y: {
          grid:  { display: false },
          ticks: { color: '#9ca3af', font: { size: 10 } },
        },
      },
    },
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// 4. Inventory Activity — Grouped bar chart (stock vs capacity)
// ─────────────────────────────────────────────────────────────────────────────
function renderInventoryActivity(data) {
  const id = 'inventoryActivityChart';
  _destroyIfExists(id);

  const empty = !data.labels || data.labels.length === 0;
  _showEmpty(id, empty);
  if (empty) return;

  const ctx = document.getElementById(id).getContext('2d');
  _charts[id] = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: data.labels,
      datasets: [
        {
          label:           'Stock Quantity',
          data:            data.stock,
          backgroundColor: 'rgba(52, 211, 153, 0.70)',   // emerald-400
          borderColor:     '#34d399',
          borderWidth:     1,
          borderRadius:    3,
        },
        {
          label:           'Capacity',
          data:            data.capacity,
          backgroundColor: 'rgba(96, 165, 250, 0.30)',   // blue-400 (faded)
          borderColor:     'rgba(96, 165, 250, 0.70)',
          borderWidth:     1,
          borderRadius:    3,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: {
          labels: {
            color:     '#9ca3af',
            boxWidth:  12,
            boxHeight: 12,
            padding:   14,
            font: { size: 11 },
          },
        },
        tooltip: {
          backgroundColor: '#1f2937',
          titleColor:      '#e5e7eb',
          bodyColor:       '#9ca3af',
          borderColor:     '#374151',
          borderWidth:     1,
        },
      },
      scales: {
        x: {
          grid:  { display: false },
          ticks: { ...TICK_OPTS, maxRotation: 30 },
        },
        y: {
          grid:        GRID_OPTS,
          ticks:       TICK_OPTS,
          beginAtZero: true,
          title: { display: true, text: 'Units', color: '#6b7280', font: { size: 10 } },
        },
      },
    },
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// Master render function
// ─────────────────────────────────────────────────────────────────────────────
function renderCharts(payload) {
  renderShipmentsOverTime(payload.shipments_over_time   || {});
  renderStatusDistribution(payload.status_distribution  || {});
  renderVehicleUtilization(payload.vehicle_utilization  || {});
  renderInventoryActivity(payload.inventory_activity    || {});
}

// ─────────────────────────────────────────────────────────────────────────────
// Data fetch
// ─────────────────────────────────────────────────────────────────────────────
function setRefreshStatus(ok, msg) {
  const el = document.getElementById('refresh-status');
  if (!el) return;
  const dot  = ok ? 'bg-green-400' : 'bg-red-400';
  const text = ok ? 'text-gray-400' : 'text-red-400';
  el.innerHTML = `<span class="inline-block w-2 h-2 rounded-full ${dot}"></span>
                  <span class="${text}">${msg}</span>`;
}

async function loadAnalytics() {
  const statusEl     = document.getElementById('refresh-status');
  const lastUpdated  = document.getElementById('last-updated');

  if (statusEl) {
    statusEl.innerHTML = `<span class="inline-block w-2 h-2 rounded-full bg-yellow-400 animate-pulse"></span>
                          <span class="text-gray-400">Fetching data…</span>`;
  }

  try {
    const resp = await fetch('/api/analytics/data', {
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
    });

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.error || `HTTP ${resp.status}`);
    }

    const payload = await resp.json();
    renderCharts(payload);

    setRefreshStatus(true, 'Charts updated');
    if (lastUpdated) {
      lastUpdated.textContent = 'Last updated: ' + new Date().toLocaleTimeString();
    }
  } catch (err) {
    console.error('[analytics] fetch failed:', err);
    setRefreshStatus(false, 'Failed to fetch data — ' + err.message);
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Boot
// ─────────────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', loadAnalytics);
