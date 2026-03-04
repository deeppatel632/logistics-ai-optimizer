"use client";

import { useState } from "react";
import { useMutation, useQuery } from "react-query";
import { workerService, TaskResponse } from "@/services/api";
import {
  Route,
  Play,
  Loader2,
  CheckCircle,
  XCircle,
  Clock,
} from "lucide-react";

const DEPOT = "51.5074,-0.1278";
const VEHICLE_OPTIONS = Array.from({ length: 20 }, (_, i) => `V-${String(i + 1).padStart(3, "0")}`);

function TaskStatusBadge({ status }: { status: TaskResponse["status"] }) {
  const map = {
    PENDING: { icon: Clock, cls: "text-amber-600 bg-amber-50", label: "Pending" },
    PROGRESS: { icon: Loader2, cls: "text-blue-600 bg-blue-50", label: "Running" },
    SUCCESS: { icon: CheckCircle, cls: "text-green-600 bg-green-50", label: "Complete" },
    FAILURE: { icon: XCircle, cls: "text-red-600 bg-red-50", label: "Failed" },
  };
  const { icon: Icon, cls, label } = map[status];
  return (
    <span className={`inline-flex items-center gap-1 text-xs font-medium px-2.5 py-0.5 rounded-full ${cls}`}>
      <Icon className="h-3.5 w-3.5" />
      {label}
    </span>
  );
}

export default function RouteOptimizationPage() {
  const [selectedVehicles, setSelectedVehicles] = useState<string[]>(
    VEHICLE_OPTIONS.slice(0, 5)
  );
  const [tasks, setTasks] = useState<
    { id: string; vehicles: number; submitted: string }[]
  >([]);
  const [pollingTaskId, setPollingTaskId] = useState<string | null>(null);

  const dispatchMutation = useMutation(
    (vehicleIds: string[]) =>
      workerService.optimizeRoutes({
        vehicle_ids: vehicleIds,
        depot_location: DEPOT,
        constraints: { max_hours_per_vehicle: 8, vehicle_capacity_kg: 1000 },
      }),
    {
      onSuccess: (res) => {
        const taskId = res.data.task_id;
        setTasks((prev) => [
          {
            id: taskId,
            vehicles: selectedVehicles.length,
            submitted: new Date().toLocaleTimeString(),
          },
          ...prev.slice(0, 9),
        ]);
        setPollingTaskId(taskId);
      },
    }
  );

  const { data: taskStatus } = useQuery(
    ["task", pollingTaskId],
    () => workerService.getTaskStatus(pollingTaskId!),
    {
      enabled: !!pollingTaskId,
      refetchInterval: (data) =>
        data?.data.status === "PENDING" || data?.data.status === "PROGRESS"
          ? 2000
          : false,
    }
  );

  const toggleVehicle = (id: string) => {
    setSelectedVehicles((prev) =>
      prev.includes(id) ? prev.filter((v) => v !== id) : [...prev, id]
    );
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Route Optimization</h1>
        <p className="text-slate-500 text-sm mt-0.5">
          Dispatch Celery tasks to run OR-Tools VRP solver
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Config panel */}
        <div className="lg:col-span-1 bg-white rounded-xl border border-slate-200 shadow-sm p-5 space-y-5">
          <h2 className="text-sm font-semibold text-slate-700">
            Job Configuration
          </h2>

          <div>
            <label className="text-xs font-medium text-slate-500 uppercase tracking-wider block mb-2">
              Select Vehicles ({selectedVehicles.length} selected)
            </label>
            <div className="grid grid-cols-4 gap-1 max-h-48 overflow-y-auto">
              {VEHICLE_OPTIONS.map((id) => (
                <button
                  key={id}
                  onClick={() => toggleVehicle(id)}
                  className={`text-xs py-1 px-1.5 rounded border transition-colors ${
                    selectedVehicles.includes(id)
                      ? "bg-brand-600 text-white border-brand-600"
                      : "bg-white text-slate-600 border-slate-200 hover:border-brand-400"
                  }`}
                >
                  {id}
                </button>
              ))}
            </div>
          </div>

          <div>
            <label className="text-xs font-medium text-slate-500 uppercase tracking-wider block mb-1">
              Depot Location
            </label>
            <input
              type="text"
              value={DEPOT}
              readOnly
              className="w-full px-3 py-2 border border-slate-200 rounded-lg text-xs text-slate-500 bg-slate-50"
            />
          </div>

          <button
            onClick={() => dispatchMutation.mutate(selectedVehicles)}
            disabled={selectedVehicles.length === 0 || dispatchMutation.isLoading}
            className="w-full flex items-center justify-center gap-2 bg-brand-600 hover:bg-brand-700 disabled:opacity-60 text-white font-medium py-2.5 rounded-lg text-sm transition-colors"
          >
            {dispatchMutation.isLoading ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Play className="h-4 w-4" />
            )}
            {dispatchMutation.isLoading ? "Dispatching..." : "Run Optimization"}
          </button>

          {/* Latest task status */}
          {pollingTaskId && taskStatus && (
            <div className="border border-slate-200 rounded-lg p-3 space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs text-slate-500">Latest task</span>
                <TaskStatusBadge status={taskStatus.data.status} />
              </div>
              <p className="font-mono text-xs text-slate-400 truncate">
                {pollingTaskId}
              </p>
              {taskStatus.data.status === "SUCCESS" && taskStatus.data.result && (
                <div className="bg-green-50 rounded p-2 text-xs text-green-700">
                  Optimization complete — check results below.
                </div>
              )}
              {taskStatus.data.status === "FAILURE" && (
                <div className="bg-red-50 rounded p-2 text-xs text-red-600">
                  {taskStatus.data.error ?? "Task failed."}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Task history */}
        <div className="lg:col-span-2 bg-white rounded-xl border border-slate-200 shadow-sm">
          <div className="px-5 py-4 border-b border-slate-100 flex items-center gap-2">
            <Route className="h-4 w-4 text-brand-500" />
            <h2 className="text-sm font-semibold text-slate-700">
              Task History
            </h2>
          </div>
          {tasks.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 text-slate-400">
              <Route className="h-10 w-10 mb-3 opacity-30" />
              <p className="text-sm">No tasks dispatched yet</p>
              <p className="text-xs mt-1">
                Select vehicles and click Run Optimization
              </p>
            </div>
          ) : (
            <div className="divide-y divide-slate-50">
              {tasks.map((t) => (
                <div key={t.id} className="px-5 py-3 flex items-center gap-4">
                  <div className="flex-1 min-w-0">
                    <p className="font-mono text-xs text-slate-500 truncate">
                      {t.id}
                    </p>
                    <p className="text-sm text-slate-700 mt-0.5">
                      {t.vehicles} vehicles · submitted {t.submitted}
                    </p>
                  </div>
                  {pollingTaskId === t.id && taskStatus ? (
                    <TaskStatusBadge status={taskStatus.data.status} />
                  ) : (
                    <TaskStatusBadge status="PENDING" />
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
