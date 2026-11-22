import mantiWordmark from "./desk/manti-logo.png";
import React, { useMemo, useState } from "react";
import { geoGraticule10, geoInterpolate, geoNaturalEarth1, geoPath } from "d3-geo";
import { feature } from "topojson-client";
import land110 from "world-atlas/land-110m.json";
import type { Network } from "./api";

const W = 960;
const H = 440;

// Supply network on a world map: suppliers, live shipment positions and the Hamburg warehouse.
export function SupplyMap({ network: raw }: { network: Network }) {
  // One point per supplier, even if a data drop delivered the same supplier twice.
  const network = useMemo(() => ({ ...raw, suppliers: [...new Map(raw.suppliers.map((s) => [s.id, s])).values()] }), [raw]);
  const [hover, setHover] = useState<string>("");
  const { land, grid, projection } = useMemo(() => {
    const topo = land110 as unknown as Parameters<typeof feature>[0];
    const shape = feature(topo, (topo as any).objects.land) as any;
    // Zoom to the places in the data, with room for labels.
    const places = [...network.suppliers, ...network.shipments, ...(network.hub ? [network.hub] : [])].map((p) => [p.lon, p.lat]);
    const proj = geoNaturalEarth1().rotate([-30, 0]).fitExtent([[60, 50], [W - 60, H - 30]], { type: "MultiPoint", coordinates: places } as any);
    return { land: geoPath(proj)(shape) ?? "", grid: geoPath(proj)(geoGraticule10()) ?? "", projection: proj };
  }, [network]);

  const hub = network.hub;
  const point = (lon: number, lat: number) => projection([lon, lat]) ?? [0, 0];
  const arc = (lon: number, lat: number) => {
    if (!hub) return "";
    const interpolate = geoInterpolate([lon, lat], [hub.lon, hub.lat]);
    const coords = Array.from({ length: 41 }, (_, i) => point(...(interpolate(i / 40) as [number, number])));
    return "M" + coords.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join("L");
  };
  const moving = network.shipments.filter((s) => !["booked", "delivered"].includes(s.status));
  const late = network.shipments.filter((s) => s.status === "delayed").length;
  const atRisk = network.suppliers.filter((s) => s.atRisk).length;

  return <div className="map-wrap">
    <svg viewBox={`0 0 ${W} ${H}`} className="map" role="img" aria-label="Supplier and shipment map">
      <path d={grid} className="map-grid"/>
      <path d={land} className="map-land"/>
      {network.suppliers.map((s) => <path key={`arc-${s.id}`} d={arc(s.lon, s.lat)} className={s.atRisk ? "map-arc risk" : "map-arc"}/>)}
      {network.shipments.map((s) => {
        const [x, y] = point(s.lon, s.lat);
        return <circle key={s.id} cx={x} cy={y} r={s.status === "delayed" ? 4 : 3} className={`map-ship ${s.status === "delayed" ? "late" : ""} ${s.status === "booked" ? "booked" : ""}`}
          onMouseEnter={() => setHover(`${s.id} · ${s.mode} · ${s.status.replace("_", " ")}${s.eta ? ` · ETA ${s.eta}` : ""}`)} onMouseLeave={() => setHover("")}/>;
      })}
      {network.suppliers.map((s) => {
        const [x, y] = point(s.lon, s.lat);
        return <g key={s.id} onMouseEnter={() => setHover(`${s.name} · ${s.city}`)} onMouseLeave={() => setHover("")}>
          <circle cx={x} cy={y} r={6} className={s.atRisk ? "map-supplier risk" : "map-supplier"}/>
          {(() => {
            const [hx, hy] = hub ? point(hub.lon, hub.lat) : [-999, -999];
            const near = Math.hypot(hx - x, hy - y) < 40;
            return <text x={near ? x + 10 : x} y={near ? y + 20 : y - 11} className="map-label" textAnchor={near ? "start" : "middle"}>{s.city}</text>;
          })()}
        </g>;
      })}
      {hub && (() => {
        const [x, y] = point(hub.lon, hub.lat);
        return <g>
          <circle cx={x} cy={y} r={14} className="map-hub-pulse"/>
          <circle cx={x} cy={y} r={7} className="map-hub"/>
          <text x={x} y={y - 16} className="map-label hub" textAnchor="middle">{hub.name}</text>
        </g>;
      })()}
    </svg>
    <div className="map-foot">
      <span><i className="key hub"/>Warehouse</span>
      <span><i className="key risk"/>{atRisk} suppliers behind a shortage</span>
      <span><i className="key ship"/>{moving.length} shipments on the way{late ? ` · ${late} late` : ""}</span>
      <span className="map-hover">{hover}</span>
    </div>
  </div>;
}

export function MantiLogo() {
  return <div className="brand"><img className="manti-logo" src={mantiWordmark} alt="Manti" width="520" height="88"/></div>;
}
