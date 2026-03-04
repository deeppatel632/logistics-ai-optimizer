/**
 * Logistics AI Optimizer — k6 Load Test Suite
 *
 * Scenarios:
 *   smoke  : 10 VUs for 30s  — sanity check, no errors expected
 *   load   : 100 VUs for 2m  — normal production load
 *   stress : 500 VUs for 3m  — above normal, find the breaking point
 *   spike  : ramp 0→1000→0   — sudden traffic burst
 *
 * Run individual scenario:
 *   k6 run --env SCENARIO=load load-tests/k6_tests.js
 *
 * Run all scenarios sequentially:
 *   k6 run load-tests/k6_tests.js
 */

import http from "k6/http";
import { check, group, sleep } from "k6";
import { Counter, Rate, Trend } from "k6/metrics";
import { SharedArray } from "k6/data";

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------
const BASE_URL = __ENV.BASE_URL || "http://localhost:8000";
const SCENARIO = __ENV.SCENARIO || "all";

// ---------------------------------------------------------------------------
// Custom metrics
// ---------------------------------------------------------------------------
const locationEventErrors = new Counter("location_event_errors");
const routeOptimizationErrors = new Counter("route_optimization_errors");
const authErrors = new Counter("auth_errors");

const locationEventDuration = new Trend("location_event_duration", true);
const routeOptDuration = new Trend("route_optimization_duration", true);
const inferenceDispatchDuration = new Trend("inference_dispatch_duration", true);

const errorRate = new Rate("error_rate");

// ---------------------------------------------------------------------------
// Test data
// ---------------------------------------------------------------------------
const vehicles = new SharedArray("vehicles", function () {
  return Array.from({ length: 100 }, (_, i) => ({
    id: `v_load_${String(i).padStart(3, "0")}`,
    lat: 51.5 + Math.random() * 0.2,
    lon: -0.1 + Math.random() * 0.2,
  }));
});

const tenants = ["tenant-alpha", "tenant-beta", "tenant-gamma"];

// ---------------------------------------------------------------------------
// Scenario definitions
// ---------------------------------------------------------------------------
export const options = {
  scenarios:
    SCENARIO === "smoke"
      ? {
          smoke: {
            executor: "constant-vus",
            vus: 10,
            duration: "30s",
          },
        }
      : SCENARIO === "load"
      ? {
          load: {
            executor: "ramping-vus",
            startVUs: 0,
            stages: [
              { duration: "30s", target: 100 },
              { duration: "90s", target: 100 },
              { duration: "30s", target: 0 },
            ],
          },
        }
      : SCENARIO === "stress"
      ? {
          stress: {
            executor: "ramping-vus",
            startVUs: 0,
            stages: [
              { duration: "30s", target: 100 },
              { duration: "60s", target: 300 },
              { duration: "60s", target: 500 },
              { duration: "60s", target: 300 },
              { duration: "30s", target: 0 },
            ],
          },
        }
      : SCENARIO === "spike"
      ? {
          spike: {
            executor: "ramping-vus",
            startVUs: 0,
            stages: [
              { duration: "10s", target: 10 },
              { duration: "5s", target: 1000 }, // sudden spike
              { duration: "30s", target: 1000 },
              { duration: "10s", target: 10 }, // recovery
              { duration: "5s", target: 0 },
            ],
          },
        }
      : {
          // all — runs smoke → load → stress sequentially
          smoke: {
            executor: "constant-vus",
            vus: 10,
            duration: "30s",
            startTime: "0s",
          },
          load: {
            executor: "ramping-vus",
            startVUs: 0,
            startTime: "40s",
            stages: [
              { duration: "30s", target: 100 },
              { duration: "90s", target: 100 },
              { duration: "30s", target: 0 },
            ],
          },
          stress: {
            executor: "ramping-vus",
            startVUs: 0,
            startTime: "3m30s",
            stages: [
              { duration: "30s", target: 200 },
              { duration: "60s", target: 500 },
              { duration: "60s", target: 200 },
              { duration: "30s", target: 0 },
            ],
          },
        },

  thresholds: {
    // Global HTTP thresholds
    http_req_failed: ["rate<0.01"], // < 1 % error rate
    http_req_duration: ["p(95)<500", "p(99)<1000"], // p95 < 500 ms, p99 < 1 s

    // Per-endpoint thresholds
    location_event_duration: ["p(95)<200"], // streaming must be fast
    route_optimization_duration: ["p(95)<800"], // dispatch only, not execution
    inference_dispatch_duration: ["p(95)<400"],

    // Custom error counters — fail if any errors above threshold
    error_rate: ["rate<0.01"],
  },
};

// ---------------------------------------------------------------------------
// Helper: login and get token (cached per VU)
// ---------------------------------------------------------------------------
let cachedToken = null;

function getToken() {
  if (cachedToken) return cachedToken;

  const tenantId = tenants[Math.floor(Math.random() * tenants.length)];
  const payload = JSON.stringify({
    email: `loadtest+${__VU}@example.com`,
    password: "LoadTest123!",
  });

  const res = http.post(`${BASE_URL}/auth/login`, payload, {
    headers: { "Content-Type": "application/json" },
    tags: { endpoint: "auth_login" },
  });

  const ok = check(res, {
    "login status 200": (r) => r.status === 200,
    "has access_token": (r) => {
      try {
        return JSON.parse(r.body).access_token !== undefined;
      } catch {
        return false;
      }
    },
  });

  if (!ok) {
    authErrors.add(1);
    errorRate.add(1);
    return null;
  }

  errorRate.add(0);
  cachedToken = JSON.parse(res.body).access_token;
  return cachedToken;
}

function authHeaders(token) {
  return {
    "Content-Type": "application/json",
    Authorization: `Bearer ${token}`,
  };
}

// ---------------------------------------------------------------------------
// Test groups
// ---------------------------------------------------------------------------

function testHealthEndpoints() {
  group("Health Checks", function () {
    const liveRes = http.get(`${BASE_URL}/health/live`, {
      tags: { endpoint: "health_live" },
    });
    check(liveRes, {
      "liveness 200": (r) => r.status === 200,
    });

    const readyRes = http.get(`${BASE_URL}/health/ready`, {
      tags: { endpoint: "health_ready" },
    });
    check(readyRes, {
      "readiness 200": (r) => r.status === 200,
    });
  });
}

function testVehicleLocationEvents(token) {
  group("Vehicle Location Events (Kafka Streaming)", function () {
    const vehicle = vehicles[Math.floor(Math.random() * vehicles.length)];

    const payload = JSON.stringify({
      vehicle_id: vehicle.id,
      latitude: vehicle.lat + (Math.random() - 0.5) * 0.01,
      longitude: vehicle.lon + (Math.random() - 0.5) * 0.01,
      speed_kmh: 20 + Math.random() * 80,
      heading_degrees: Math.floor(Math.random() * 360),
      timestamp: new Date().toISOString(),
    });

    const start = Date.now();
    const res = http.post(
      `${BASE_URL}/streaming/vehicle-location`,
      payload,
      {
        headers: authHeaders(token),
        tags: { endpoint: "vehicle_location" },
      }
    );
    locationEventDuration.add(Date.now() - start);

    const ok = check(res, {
      "vehicle location 200": (r) => r.status === 200,
      "event published": (r) => {
        try {
          return JSON.parse(r.body).status === "published";
        } catch {
          return false;
        }
      },
    });

    if (!ok) {
      locationEventErrors.add(1);
      errorRate.add(1);
    } else {
      errorRate.add(0);
    }
  });
}

function testRouteOptimization(token) {
  group("Route Optimization (Celery Task Dispatch)", function () {
    const vehicleCount = 3 + Math.floor(Math.random() * 5);
    const vehicleIds = Array.from(
      { length: vehicleCount },
      (_, i) => vehicles[(i * 7 + __VU) % vehicles.length].id
    );

    const payload = JSON.stringify({
      vehicle_ids: vehicleIds,
      depot_location: "51.5074,-0.1278",
      constraints: {
        max_hours_per_vehicle: 8,
        vehicle_capacity_kg: 1000,
      },
    });

    const start = Date.now();
    const res = http.post(
      `${BASE_URL}/workers/optimize-routes`,
      payload,
      {
        headers: authHeaders(token),
        tags: { endpoint: "optimize_routes" },
      }
    );
    routeOptDuration.add(Date.now() - start);

    const ok = check(res, {
      "optimize-routes 200 or 202": (r) =>
        r.status === 200 || r.status === 202,
      "has task_id": (r) => {
        try {
          return JSON.parse(r.body).task_id !== undefined;
        } catch {
          return false;
        }
      },
    });

    if (!ok) {
      routeOptimizationErrors.add(1);
      errorRate.add(1);
    } else {
      errorRate.add(0);
    }
  });
}

function testAIPrediction(token) {
  group("AI Prediction Dispatch", function () {
    const vehicle = vehicles[Math.floor(Math.random() * vehicles.length)];

    const payload = JSON.stringify({
      vehicle_id: vehicle.id,
      route_distance_km: 10 + Math.random() * 100,
    });

    const start = Date.now();
    const res = http.post(
      `${BASE_URL}/workers/run-ai-prediction`,
      payload,
      {
        headers: authHeaders(token),
        tags: { endpoint: "ai_prediction" },
      }
    );
    inferenceDispatchDuration.add(Date.now() - start);

    check(res, {
      "ai-prediction 200 or 202": (r) =>
        r.status === 200 || r.status === 202,
    });
  });
}

function testWarehouseRead(token) {
  group("Warehouse List (DB Read)", function () {
    const res = http.get(`${BASE_URL}/warehouses/`, {
      headers: authHeaders(token),
      tags: { endpoint: "warehouse_list" },
    });

    check(res, {
      "warehouse list 200": (r) => r.status === 200,
      "response is array": (r) => {
        try {
          return Array.isArray(JSON.parse(r.body));
        } catch {
          return false;
        }
      },
    });
  });
}

function testTaskStatusPoll(token, taskId) {
  if (!taskId) return;

  group("Task Status Poll", function () {
    const res = http.get(
      `${BASE_URL}/workers/task-status/${taskId}`,
      {
        headers: authHeaders(token),
        tags: { endpoint: "task_status" },
      }
    );

    check(res, {
      "task status 200": (r) => r.status === 200,
    });
  });
}

// ---------------------------------------------------------------------------
// Main VU function
// ---------------------------------------------------------------------------
export default function () {
  // Health checks are cheap — run every iteration
  testHealthEndpoints();

  const token = getToken();
  if (!token) {
    sleep(1);
    return;
  }

  // Weight the test mix to reflect real traffic patterns:
  //   60% vehicle location events (high-freq IoT)
  //   20% route optimization dispatch
  //   10% AI prediction dispatch
  //   10% warehouse reads
  const roll = Math.random();

  if (roll < 0.6) {
    testVehicleLocationEvents(token);
  } else if (roll < 0.8) {
    testRouteOptimization(token);
  } else if (roll < 0.9) {
    testAIPrediction(token);
  } else {
    testWarehouseRead(token);
  }

  // Think time: 0.1–0.5s between requests (simulates realistic pacing)
  sleep(0.1 + Math.random() * 0.4);
}

// ---------------------------------------------------------------------------
// Setup: create load-test users (runs once before VUs start)
// ---------------------------------------------------------------------------
export function setup() {
  console.log(`Starting load test against: ${BASE_URL}`);
  console.log(`Scenario: ${SCENARIO}`);

  // Verify the API is reachable before starting the test
  const res = http.get(`${BASE_URL}/health/live`);
  if (res.status !== 200) {
    throw new Error(
      `API health check failed (status ${res.status}). Aborting test.`
    );
  }

  console.log("API is healthy. Starting VUs...");
  return { baseUrl: BASE_URL };
}

// ---------------------------------------------------------------------------
// Teardown: log summary (runs once after all VUs finish)
// ---------------------------------------------------------------------------
export function teardown(data) {
  console.log(`Load test complete against: ${data.baseUrl}`);
}
