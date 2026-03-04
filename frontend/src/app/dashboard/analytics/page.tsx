"use client";

import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  Legend,
} from "recharts";

// ── Mock analytics data ───────────────────────────────────────────────────────
const dailyDeliveries = Array.from({ length: 14 }, (_, i) => {
  const d = new Date();
  d.setDate(d.getDate() - (13 - i));
  return {
    date: d.toLocaleDateString("en-GB", { day: "2-digit", month: "short" }),
    delivered: Math.floor(12000 + Math.random() * 4000),
    failed: Math.floor(50 + Math.random() * 200),
    onTime: Math.floor(90 + Math.random() * 8),
  };
});

const statusBreakdown = [
  { name: "Delivered", value: 14291, color: "#22c55e" },
  { name: "In Transit", value: 2847, color: "#3b82f6" },
  { name: "Pending Pickup", value: 634, color: "#f59e0b" },
  { name: "Failed", value: 127, color: "#ef4444" },
];

const etaAccuracy = Array.from({ length: 7 }, (_, i) => {
  const d = new Date();
  d.setDate(d.getDate() - (6 - i));
  return {
    date: d.toLocaleDateString("en-GB", { day: "2-digit", month: "short" }),
    accuracy: 91 + Math.random() * 7,
    avgEtaHours: 2.1 + Math.random() * 0.8,
  };
});

const RADIAN = Math.PI / 180;
const renderCustomLabel = ({
  cx, cy, midAngle, innerRadius, outerRadius, percent,
}: {
  cx: number; cy: number; midAngle: number;
  innerRadius: number; outerRadius: number; percent: number;
}) => {
  const radius = innerRadius + (outerRadius - innerRadius) * 0.5;
  const x = cx + radius * Math.cos(-midAngle * RADIAN);
  const y = cy + radius * Math.sin(-midAngle * RADIAN);
  return (
    <text x={x} y={y} fill="white" textAnchor="middle" dominantBaseline="central" fontSize={11}>
      {`${(percent * 100).toFixed(0)}%`}
    </text>
  );
};

export default function AnalyticsPage() {
  const totalDeliveries = statusBreakdown.reduce((s, d) => s + d.value, 0);
  const successRate = ((statusBreakdown[0].value / totalDeliveries) * 100).toFixed(1);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Analytics</h1>
        <p className="text-slate-500 text-sm mt-0.5">
          Delivery performance and ML model accuracy
        </p>
      </div>

      {/* KPI row */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {[
          { label: "Total Deliveries", value: totalDeliveries.toLocaleString() },
          { label: "Success Rate", value: `${successRate}%` },
          { label: "Avg. ETA Accuracy", value: "94.7%" },
          { label: "Avg. Delivery Time", value: "2.4 hrs" },
        ].map(({ label, value }) => (
          <div key={label} className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
            <p className="text-sm text-slate-500">{label}</p>
            <p className="text-2xl font-bold text-slate-900 mt-1">{value}</p>
          </div>
        ))}
      </div>

      {/* Charts row 1 */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Daily deliveries */}
        <div className="lg:col-span-2 bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
          <h2 className="text-sm font-semibold text-slate-700 mb-4">
            Daily Deliveries (14 days)
          </h2>
          <ResponsiveContainer width="100%" height={240}>
            <LineChart data={dailyDeliveries}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
              <XAxis dataKey="date" tick={{ fontSize: 11 }} tickLine={false} axisLine={false} />
              <YAxis tick={{ fontSize: 11 }} tickLine={false} axisLine={false} />
              <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8 }} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Line type="monotone" dataKey="delivered" stroke="#22c55e" strokeWidth={2} dot={false} name="Delivered" />
              <Line type="monotone" dataKey="failed" stroke="#ef4444" strokeWidth={2} dot={false} name="Failed" />
            </LineChart>
          </ResponsiveContainer>
        </div>

        {/* Status breakdown pie */}
        <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
          <h2 className="text-sm font-semibold text-slate-700 mb-4">
            Status Breakdown
          </h2>
          <ResponsiveContainer width="100%" height={240}>
            <PieChart>
              <Pie
                data={statusBreakdown}
                cx="50%"
                cy="50%"
                outerRadius={90}
                dataKey="value"
                labelLine={false}
                label={renderCustomLabel}
              >
                {statusBreakdown.map((entry, idx) => (
                  <Cell key={idx} fill={entry.color} />
                ))}
              </Pie>
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8 }} />
            </PieChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* ETA Accuracy chart */}
      <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
        <h2 className="text-sm font-semibold text-slate-700 mb-4">
          ML Model — ETA Accuracy & Avg. Predicted Time (7 days)
        </h2>
        <ResponsiveContainer width="100%" height={220}>
          <LineChart data={etaAccuracy}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
            <XAxis dataKey="date" tick={{ fontSize: 11 }} tickLine={false} axisLine={false} />
            <YAxis yAxisId="left" domain={[85, 100]} tick={{ fontSize: 11 }} tickLine={false} axisLine={false} unit="%" />
            <YAxis yAxisId="right" orientation="right" domain={[1, 5]} tick={{ fontSize: 11 }} tickLine={false} axisLine={false} unit="h" />
            <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8 }} />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            <Line yAxisId="left" type="monotone" dataKey="accuracy" stroke="#3b82f6" strokeWidth={2} dot={false} name="ETA Accuracy %" />
            <Line yAxisId="right" type="monotone" dataKey="avgEtaHours" stroke="#f59e0b" strokeWidth={2} dot={false} name="Avg ETA (hrs)" />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
