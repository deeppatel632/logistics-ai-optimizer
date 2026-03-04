"use client";

import dynamic from "next/dynamic";
import { useState, useEffect } from "react";
import { streamingService } from "@/services/api";
import { MapPin, Send, RefreshCw } from "lucide-react";

// Leaflet must be loaded client-side only (no SSR)
const VehicleMap = dynamic(() => import("@/components/maps/VehicleMap"), {
  ssr: false,
  loading: () => (
    <div className="w-full h-[500px] bg-slate-100 rounded-xl flex items-center justify-center">
      <RefreshCw className="h-6 w-6 animate-spin text-slate-400" />
    </div>
  ),
});

interface SimVehicle {
  id: string;
  lat: number;
  lon: number;
  speed: number;
  heading: number;
}

function randomDrift(base: number, range = 0.005): number {
  return base + (Math.random() - 0.5) * range;
}

export default function VehicleTrackingPage() {
  const [vehicles, setVehicles] = useState<SimVehicle[]>(() =>
    Array.from({ length: 8 }, (_, i) => ({
      id: `V-${String(i + 1).padStart(3, "0")}`,
      lat: 51.5 + (Math.random() - 0.5) * 0.15,
      lon: -0.12 + (Math.random() - 0.5) * 0.15,
      speed: 30 + Math.random() * 60,
      heading: Math.floor(Math.random() * 360),
    }))
  );
  const [publishing, setPublishing] = useState(false);
  const [lastPublished, setLastPublished] = useState<string | null>(null);

  // Simulate vehicle movement every 3 seconds
  useEffect(() => {
    const interval = setInterval(() => {
      setVehicles((prev) =>
        prev.map((v) => ({
          ...v,
          lat: randomDrift(v.lat),
          lon: randomDrift(v.lon),
          speed: Math.max(10, Math.min(120, v.speed + (Math.random() - 0.5) * 10)),
          heading: (v.heading + Math.floor(Math.random() * 20 - 10) + 360) % 360,
        }))
      );
    }, 3000);
    return () => clearInterval(interval);
  }, []);

  // Publish all current vehicle positions to Kafka
  const publishAll = async () => {
    setPublishing(true);
    try {
      await Promise.all(
        vehicles.map((v) =>
          streamingService.publishLocation({
            vehicle_id: v.id,
            latitude: v.lat,
            longitude: v.lon,
            speed_kmh: v.speed,
            heading_degrees: v.heading,
            timestamp: new Date().toISOString(),
          })
        )
      );
      setLastPublished(new Date().toLocaleTimeString());
    } catch (err) {
      console.error("Failed to publish locations", err);
    } finally {
      setPublishing(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">
            Vehicle Tracking
          </h1>
          <p className="text-slate-500 text-sm mt-0.5">
            Live GPS positions — updates every 3 seconds
          </p>
        </div>
        <button
          onClick={publishAll}
          disabled={publishing}
          className="flex items-center gap-2 bg-brand-600 hover:bg-brand-700 disabled:opacity-60 text-white text-sm font-medium px-4 py-2 rounded-lg transition-colors"
        >
          <Send className="h-4 w-4" />
          {publishing ? "Publishing..." : "Publish to Kafka"}
        </button>
      </div>

      {lastPublished && (
        <p className="text-xs text-green-600">
          ✓ Positions published at {lastPublished}
        </p>
      )}

      {/* Map */}
      <VehicleMap vehicles={vehicles} />

      {/* Vehicle table */}
      <div className="bg-white rounded-xl border border-slate-200 shadow-sm">
        <div className="px-5 py-4 border-b border-slate-100">
          <h2 className="text-sm font-semibold text-slate-700">
            Fleet Status ({vehicles.length} vehicles)
          </h2>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-100 text-left">
                <th className="px-5 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wider">
                  Vehicle
                </th>
                <th className="px-5 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wider">
                  Latitude
                </th>
                <th className="px-5 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wider">
                  Longitude
                </th>
                <th className="px-5 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wider">
                  Speed
                </th>
                <th className="px-5 py-3 text-xs font-semibold text-slate-500 uppercase tracking-wider">
                  Heading
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-50">
              {vehicles.map((v) => (
                <tr key={v.id} className="hover:bg-slate-50 transition-colors">
                  <td className="px-5 py-3 font-medium text-slate-900">
                    <div className="flex items-center gap-2">
                      <MapPin className="h-4 w-4 text-brand-500" />
                      {v.id}
                    </div>
                  </td>
                  <td className="px-5 py-3 text-slate-600 font-mono text-xs">
                    {v.lat.toFixed(5)}
                  </td>
                  <td className="px-5 py-3 text-slate-600 font-mono text-xs">
                    {v.lon.toFixed(5)}
                  </td>
                  <td className="px-5 py-3 text-slate-700">
                    {v.speed.toFixed(1)} km/h
                  </td>
                  <td className="px-5 py-3 text-slate-700">{v.heading}°</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
