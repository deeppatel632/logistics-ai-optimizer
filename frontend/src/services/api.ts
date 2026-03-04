import axios, { AxiosInstance, AxiosError } from "axios";
import Cookies from "js-cookie";

const BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

const api: AxiosInstance = axios.create({
  baseURL: BASE_URL,
  headers: { "Content-Type": "application/json" },
  timeout: 15000,
});

// ── Request interceptor: attach JWT ───────────────────────────────────────────
api.interceptors.request.use((config) => {
  const token = Cookies.get("access_token");
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// ── Response interceptor: handle 401 globally ────────────────────────────────
api.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
    if (error.response?.status === 401) {
      Cookies.remove("access_token");
      if (typeof window !== "undefined") {
        window.location.href = "/login";
      }
    }
    return Promise.reject(error);
  }
);

export default api;

// ── Auth ──────────────────────────────────────────────────────────────────────
export interface LoginPayload {
  email: string;
  password: string;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
}

export interface RegisterPayload {
  email: string;
  password: string;
  tenant_id: string;
}

export const authService = {
  login: (payload: LoginPayload) =>
    api.post<LoginResponse>("/auth/login", payload),
  register: (payload: RegisterPayload) =>
    api.post("/auth/register", payload),
};

// ── Warehouses ────────────────────────────────────────────────────────────────
export interface Warehouse {
  id: string;
  name: string;
  location: string;
  capacity: number;
  tenant_id: string;
  created_at: string;
}

export const warehouseService = {
  list: (skip = 0, limit = 100) =>
    api.get<Warehouse[]>(`/warehouses/?skip=${skip}&limit=${limit}`),
  create: (payload: Omit<Warehouse, "id" | "tenant_id" | "created_at">) =>
    api.post<Warehouse>("/warehouses/", payload),
  get: (id: string) => api.get<Warehouse>(`/warehouses/${id}`),
  delete: (id: string) => api.delete(`/warehouses/${id}`),
};

// ── Workers ───────────────────────────────────────────────────────────────────
export interface TaskResponse {
  task_id: string;
  status: "PENDING" | "PROGRESS" | "SUCCESS" | "FAILURE";
  result?: unknown;
  error?: string;
  progress?: number;
}

export const workerService = {
  optimizeRoutes: (payload: {
    vehicle_ids: string[];
    depot_location: string;
    constraints?: Record<string, unknown>;
  }) => api.post<TaskResponse>("/workers/optimize-routes", payload),

  runAiPrediction: (payload: {
    vehicle_id: string;
    route_distance_km: number;
  }) => api.post<TaskResponse>("/workers/run-ai-prediction", payload),

  getTaskStatus: (taskId: string) =>
    api.get<TaskResponse>(`/workers/task-status/${taskId}`),
};

// ── Streaming ─────────────────────────────────────────────────────────────────
export interface VehicleLocationEvent {
  vehicle_id: string;
  latitude: number;
  longitude: number;
  speed_kmh: number;
  heading_degrees: number;
  timestamp: string;
}

export const streamingService = {
  publishLocation: (payload: VehicleLocationEvent) =>
    api.post("/streaming/vehicle-location", payload),
  triggerRouteOptimization: (payload: {
    tenant_id: string;
    vehicle_fleet: string[];
    priority?: string;
  }) => api.post("/streaming/trigger-route-optimization", payload),
};

// ── Health ────────────────────────────────────────────────────────────────────
export interface HealthStatus {
  status: "ok" | "degraded";
  db?: string;
  redis?: string;
}

export const healthService = {
  ready: () => api.get<HealthStatus>("/health/ready"),
};

// ── Audit ─────────────────────────────────────────────────────────────────────
export interface AuditLog {
  id: string;
  tenant_id: string;
  user_id: string;
  action: string;
  entity_type: string;
  entity_id: string;
  changes: Record<string, unknown>;
  ip_address: string;
  created_at: string;
}

export const auditService = {
  list: (skip = 0, limit = 50) =>
    api.get<AuditLog[]>(`/audit/?skip=${skip}&limit=${limit}`),
};
