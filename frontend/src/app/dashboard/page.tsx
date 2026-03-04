"use client";

import { useQuery } from "react-query";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  BarChart,
  Bar,
  Legend,
} from "recharts";
import { healthService, warehouseService } from "@/services/api";
import {
  Truck,
  Package,
  TrendingUp,
  AlertCircle,
  CheckCircle,
  Clock,
  Zap,
} from "lucide-react";
import clsx from "clsx";

// ── Mock time-series data (replace with real API calls) ───────────────────────
const requestVolume = Array.from({ length: 24 }, (_, i) => ({
  hour: `${String(i).padStart(2, "0")}:00`,
  requests: Math.floor(200 + Math.random() * 800),
  errors: Math.floor(Math.random() * 20),
}));

const taskData = [
  { queue: "Route Opt.", pending: 12, processing: 4, completed: 189 },
  { queue: "AI Predict", pending: 3, processing: 2, completed: 421 },
  { queue: "Default", pending: 1, processing: 1, completed: 87 },
];

// ── Stat card ─────────────────────────────────────────────────────────────────
interface StatCardProps {
  title: string;
  value: string | number;
  subtitle?: string;
  icon: React.ElementType;
  trend?: "up" | "down" | "neutral";
  color: "blue" | "green" | "yellow" | "red";
}

function StatCard({
  title,
  value,
  subtitle,
  icon: Icon,
  color,
}: StatCardProps) {
  const colorMap = {
    blue: "bg-blue-50 text-blue-600",
    green: "bg-green-50 text-green-600",
    yellow: "bg-amber-50 text-amber-600",
    red: "bg-red-50 text-red-600",
  };

  return (
    <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-sm text-slate-500 font-medium">{title}</p>
          <p className="text-2xl font-bold text-slate-900 mt-1">{value}</p>
          {subtitle && (
            <p className="text-xs text-slate-400 mt-0.5">{subtitle}</p>
          )}
        </div>
        <div className={clsx("p-2.5 rounded-lg", colorMap[color])}>
          <Icon className="h-5 w-5" />
        </div>
      </div>
    </div>
  );
}

// ── Status badge ──────────────────────────────────────────────────────────────
function StatusBadge({ status }: { status: "ok" | "degraded" | "unknown" }) {
  if (status === "ok")
    return (
      <span className="inline-flex items-center gap-1 text-green-700 bg-green-50 border border-green-200 text-xs font-medium px-2 py-0.5 rounded-full">
        <CheckCircle className="h-3 w-3" /> Operational
      </span>
    );
  if (status === "degraded")
    return (
      <span className="inline-flex items-center gap-1 text-amber-700 bg-amber-50 border border-amber-200 text-xs font-medium px-2 py-0.5 rounded-full">
        <AlertCircle className="h-3 w-3" /> Degraded
      </span>
    );
  return (
    <span className="inline-flex items-center gap-1 text-slate-500 bg-slate-100 text-xs font-medium px-2 py-0.5 rounded-full">
      <Clock className="h-3 w-3" /> Unknown
    </span>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────
export default function DashboardPage() {
  const { data: healthData } = useQuery(
    "health",
    () => healthService.ready(),
    { refetchInterval: 30_000 }
  );

  const { data: warehousesData } = useQuery("warehouses", () =>
    warehouseService.list(0, 200)
  );

  const health = healthData?.data;
  const warehouseCount = warehousesData?.data?.length ?? 0;

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Dashboard</h1>
          <p className="text-slate-500 text-sm mt-0.5">
            Real-time platform overview
          </p>
        </div>
        <div className="flex items-center gap-3">
          <StatusBadge status={health?.status ?? "unknown"} />
          <span className="text-xs text-slate-400">
            Updated {new Date().toLocaleTimeString()}
          </span>
        </div>
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          title="Active Vehicles"
          value="2 847"
          subtitle="↑ 12% from yesterday"
          icon={Truck}
          color="blue"
        />
        <StatCard
          title="Deliveries Today"
          value="14 291"
          subtitle="↑ 8.3% from last week"
          icon={Package}
          color="green"
        />
        <StatCard
          title="Avg. ETA Accuracy"
          value="94.7%"
          subtitle="Model: eta_model v3"
          icon={Zap}
          color="yellow"
        />
        <StatCard
          title="Warehouses"
          value={warehouseCount}
          subtitle="Across all tenants"
          icon={TrendingUp}
          color="blue"
        />
      </div>

      {/* Charts row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* API request volume */}
        <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
          <h2 className="text-sm font-semibold text-slate-700 mb-4">
            API Request Volume (24h)
          </h2>
          <ResponsiveContainer width="100%" height={220}>
            <AreaChart data={requestVolume}>
              <defs>
                <linearGradient id="req" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.15} />
                  <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
                </linearGradient>
                <linearGradient id="err" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#ef4444" stopOpacity={0.15} />
                  <stop offset="95%" stopColor="#ef4444" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
              <XAxis
                dataKey="hour"
                tick={{ fontSize: 11 }}
                tickLine={false}
                axisLine={false}
              />
              <YAxis tick={{ fontSize: 11 }} tickLine={false} axisLine={false} />
              <Tooltip
                contentStyle={{
                  fontSize: 12,
                  border: "1px solid #e2e8f0",
                  borderRadius: 8,
                }}
              />
              <Area
                type="monotone"
                dataKey="requests"
                stroke="#3b82f6"
                strokeWidth={2}
                fill="url(#req)"
                name="Requests"
              />
              <Area
                type="monotone"
                dataKey="errors"
                stroke="#ef4444"
                strokeWidth={2}
                fill="url(#err)"
                name="Errors"
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>

        {/* Celery task queue */}
        <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
          <h2 className="text-sm font-semibold text-slate-700 mb-4">
            Celery Task Queues
          </h2>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={taskData} layout="vertical">
              <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
              <XAxis
                type="number"
                tick={{ fontSize: 11 }}
                tickLine={false}
                axisLine={false}
              />
              <YAxis
                dataKey="queue"
                type="category"
                tick={{ fontSize: 11 }}
                tickLine={false}
                axisLine={false}
                width={80}
              />
              <Tooltip
                contentStyle={{
                  fontSize: 12,
                  border: "1px solid #e2e8f0",
                  borderRadius: 8,
                }}
              />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Bar dataKey="completed" fill="#22c55e" name="Completed" radius={[0, 3, 3, 0]} />
              <Bar dataKey="processing" fill="#3b82f6" name="Processing" radius={[0, 3, 3, 0]} />
              <Bar dataKey="pending" fill="#f59e0b" name="Pending" radius={[0, 3, 3, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* System health table */}
      <div className="bg-white rounded-xl border border-slate-200 shadow-sm">
        <div className="px-5 py-4 border-b border-slate-100">
          <h2 className="text-sm font-semibold text-slate-700">
            Service Health
          </h2>
        </div>
        <div className="divide-y divide-slate-100">
          {[
            { name: "FastAPI (API)", status: health?.status ?? "unknown" },
            {
              name: "Azure SQL Edge (DB)",
              status: health?.db === "up" ? "ok" : "degraded",
            },
            {
              name: "Redis (Cache)",
              status: health?.redis === "up" ? "ok" : "degraded",
            },
            { name: "Kafka (Streaming)", status: "ok" as const },
            { name: "Triton (ML Serving)", status: "ok" as const },
            { name: "MinIO (Data Lake)", status: "ok" as const },
          ].map(({ name, status }) => (
            <div
              key={name}
              className="flex items-center justify-between px-5 py-3"
            >
              <span className="text-sm text-slate-700">{name}</span>
              <StatusBadge
                status={status as "ok" | "degraded" | "unknown"}
              />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
