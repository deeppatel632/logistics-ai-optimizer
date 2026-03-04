"use client";

import { MapContainer, TileLayer, Marker, Popup, Circle } from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

// Fix Leaflet default icon paths in Next.js
delete (L.Icon.Default.prototype as unknown as Record<string, unknown>)._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl:
    "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon-2x.png",
  iconUrl:
    "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon.png",
  shadowUrl:
    "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png",
});

const truckIcon = new L.DivIcon({
  className: "",
  html: `<div style="
    background:#2563eb;
    border:2px solid white;
    border-radius:50%;
    width:12px;
    height:12px;
    box-shadow:0 2px 4px rgba(0,0,0,0.4);
  "></div>`,
  iconSize: [12, 12],
  iconAnchor: [6, 6],
});

interface Vehicle {
  id: string;
  lat: number;
  lon: number;
  speed: number;
  heading: number;
}

interface VehicleMapProps {
  vehicles: Vehicle[];
}

export default function VehicleMap({ vehicles }: VehicleMapProps) {
  const center: [number, number] = [51.505, -0.09];

  return (
    <MapContainer
      center={center}
      zoom={12}
      style={{ height: "500px", width: "100%", borderRadius: "12px" }}
    >
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />

      {vehicles.map((v) => (
        <Marker key={v.id} position={[v.lat, v.lon]} icon={truckIcon}>
          <Popup>
            <div className="text-sm">
              <p className="font-bold">{v.id}</p>
              <p>Speed: {v.speed.toFixed(1)} km/h</p>
              <p>Heading: {v.heading}°</p>
              <p className="font-mono text-xs text-gray-500">
                {v.lat.toFixed(5)}, {v.lon.toFixed(5)}
              </p>
            </div>
          </Popup>
          <Circle
            center={[v.lat, v.lon]}
            radius={80}
            pathOptions={{ color: "#2563eb", fillOpacity: 0.08, weight: 1 }}
          />
        </Marker>
      ))}
    </MapContainer>
  );
}
