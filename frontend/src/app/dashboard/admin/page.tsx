"use client";

import { useState } from "react";
import { useQuery } from "react-query";
import { warehouseService, auditService, Warehouse } from "@/services/api";
import {
  Plus,
  Trash2,
  Shield,
  Building2,
  ScrollText,
  Loader2,
} from "lucide-react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useMutation, useQueryClient } from "react-query";

const warehouseSchema = z.object({
  name: z.string().min(2, "Name is required"),
  location: z.string().min(3, "Location is required (lat,lon)"),
  capacity: z.number({ coerce: true }).positive("Must be positive"),
});

type WarehouseForm = z.infer<typeof warehouseSchema>;

export default function AdminPage() {
  const [tab, setTab] = useState<"warehouses" | "audit">("warehouses");
  const queryClient = useQueryClient();

  const { data: warehousesData, isLoading: loadingWH } = useQuery(
    "warehouses",
    () => warehouseService.list(0, 200)
  );

  const { data: auditData, isLoading: loadingAudit } = useQuery(
    "audit",
    () => auditService.list(0, 50),
    { enabled: tab === "audit" }
  );

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<WarehouseForm>({
    resolver: zodResolver(warehouseSchema),
  });

  const createMutation = useMutation(
    (payload: WarehouseForm) => warehouseService.create(payload),
    {
      onSuccess: () => {
        queryClient.invalidateQueries("warehouses");
        reset();
      },
    }
  );

  const deleteMutation = useMutation(
    (id: string) => warehouseService.delete(id),
    {
      onSuccess: () => queryClient.invalidateQueries("warehouses"),
    }
  );

  const warehouses: Warehouse[] = warehousesData?.data ?? [];

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-slate-900 flex items-center gap-2">
          <Shield className="h-6 w-6 text-brand-600" /> Admin Panel
        </h1>
        <p className="text-slate-500 text-sm mt-0.5">
          Manage warehouses and review audit logs
        </p>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 bg-slate-100 rounded-lg p-1 w-fit">
        {(["warehouses", "audit"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`flex items-center gap-2 px-4 py-1.5 rounded-md text-sm font-medium transition-colors ${
              tab === t
                ? "bg-white text-slate-900 shadow-sm"
                : "text-slate-500 hover:text-slate-700"
            }`}
          >
            {t === "warehouses" ? (
              <Building2 className="h-4 w-4" />
            ) : (
              <ScrollText className="h-4 w-4" />
            )}
            {t.charAt(0).toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>

      {tab === "warehouses" && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Create form */}
          <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-5">
            <h2 className="text-sm font-semibold text-slate-700 mb-4">
              Add Warehouse
            </h2>
            <form
              onSubmit={handleSubmit((d) => createMutation.mutate(d))}
              className="space-y-4"
            >
              {[
                { name: "name" as const, label: "Name", placeholder: "London DC" },
                { name: "location" as const, label: "Location (lat,lon)", placeholder: "51.5074,-0.1278" },
                { name: "capacity" as const, label: "Capacity (units)", placeholder: "5000", type: "number" },
              ].map(({ name, label, placeholder, type }) => (
                <div key={name}>
                  <label className="block text-xs font-medium text-slate-600 mb-1">
                    {label}
                  </label>
                  <input
                    type={type || "text"}
                    {...register(name, { valueAsNumber: type === "number" })}
                    placeholder={placeholder}
                    className="w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
                  />
                  {errors[name] && (
                    <p className="text-red-500 text-xs mt-0.5">
                      {errors[name]?.message}
                    </p>
                  )}
                </div>
              ))}
              <button
                type="submit"
                disabled={isSubmitting || createMutation.isLoading}
                className="w-full flex items-center justify-center gap-2 bg-brand-600 hover:bg-brand-700 disabled:opacity-60 text-white py-2 rounded-lg text-sm font-medium transition-colors"
              >
                {createMutation.isLoading ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Plus className="h-4 w-4" />
                )}
                Add Warehouse
              </button>
            </form>
          </div>

          {/* Warehouse list */}
          <div className="lg:col-span-2 bg-white rounded-xl border border-slate-200 shadow-sm">
            <div className="px-5 py-4 border-b border-slate-100">
              <h2 className="text-sm font-semibold text-slate-700">
                Warehouses ({warehouses.length})
              </h2>
            </div>
            {loadingWH ? (
              <div className="flex justify-center py-12">
                <Loader2 className="h-6 w-6 animate-spin text-slate-400" />
              </div>
            ) : (
              <div className="divide-y divide-slate-50">
                {warehouses.map((w) => (
                  <div
                    key={w.id}
                    className="flex items-center gap-4 px-5 py-3"
                  >
                    <Building2 className="h-4 w-4 text-brand-400 shrink-0" />
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-slate-800 truncate">
                        {w.name}
                      </p>
                      <p className="text-xs text-slate-400">
                        {w.location} · capacity {w.capacity.toLocaleString()}
                      </p>
                    </div>
                    <button
                      onClick={() => deleteMutation.mutate(w.id)}
                      disabled={deleteMutation.isLoading}
                      className="p-1.5 text-slate-400 hover:text-red-500 hover:bg-red-50 rounded-md transition-colors"
                      title="Delete warehouse"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                ))}
                {warehouses.length === 0 && (
                  <p className="text-center text-slate-400 text-sm py-8">
                    No warehouses yet
                  </p>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {tab === "audit" && (
        <div className="bg-white rounded-xl border border-slate-200 shadow-sm">
          <div className="px-5 py-4 border-b border-slate-100">
            <h2 className="text-sm font-semibold text-slate-700">
              Audit Log (last 50 events)
            </h2>
          </div>
          {loadingAudit ? (
            <div className="flex justify-center py-12">
              <Loader2 className="h-6 w-6 animate-spin text-slate-400" />
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-100 text-left">
                    {["Time", "Action", "Entity", "User", "IP"].map((h) => (
                      <th
                        key={h}
                        className="px-5 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wider"
                      >
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-50">
                  {(auditData?.data ?? []).map((log) => (
                    <tr key={log.id} className="hover:bg-slate-50 transition-colors">
                      <td className="px-5 py-3 text-xs text-slate-400 whitespace-nowrap">
                        {new Date(log.created_at).toLocaleString()}
                      </td>
                      <td className="px-5 py-3 font-mono text-xs text-brand-600">
                        {log.action}
                      </td>
                      <td className="px-5 py-3 text-xs text-slate-600">
                        {log.entity_type}
                      </td>
                      <td className="px-5 py-3 text-xs text-slate-600 truncate max-w-[120px]">
                        {log.user_id}
                      </td>
                      <td className="px-5 py-3 text-xs font-mono text-slate-400">
                        {log.ip_address}
                      </td>
                    </tr>
                  ))}
                  {(auditData?.data?.length ?? 0) === 0 && (
                    <tr>
                      <td colSpan={5} className="px-5 py-8 text-center text-slate-400 text-sm">
                        No audit events found
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
