"use client";

import { useEffect, useRef } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { Feature } from "@/lib/api";

// IGN Géoplateforme: open, key-less, and the best alpine cartography there is.
const IGN_PLAN =
  "https://data.geopf.fr/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0" +
  "&LAYER=GEOGRAPHICALGRIDSYSTEMS.PLANIGNV2&STYLE=normal&TILEMATRIXSET=PM" +
  "&TILEMATRIX={z}&TILECOL={x}&TILEROW={y}&FORMAT=image/png";

const COLOURS: Record<string, string> = {
  open: "#3fb950",
  closed: "#f85149",
  restricted: "#d29922",
  unknown: "#6e7681",
};

function colourFor(feature: Feature): string {
  // A routine overnight closure is not an incident and must not be red.
  if (feature.status.closure_kind === "outside_hours") return COLOURS.unknown;
  return COLOURS[feature.status.value] ?? COLOURS.unknown;
}

export default function MassifMap({ features }: { features: Feature[] }) {
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);

  useEffect(() => {
    if (!container.current || map.current) return;

    map.current = new maplibregl.Map({
      container: container.current,
      style: {
        version: 8,
        sources: {
          ign: {
            type: "raster",
            tiles: [IGN_PLAN],
            tileSize: 256,
            attribution: "© IGN Géoplateforme",
          },
        },
        layers: [{ id: "ign", type: "raster", source: "ign" }],
      },
      center: [6.87, 45.9],
      zoom: 10.2,
    });

    map.current.addControl(new maplibregl.NavigationControl(), "top-right");

    for (const feature of features) {
      if (!feature.geometry || feature.geometry.type !== "Point") continue;
      const [lon, lat] = feature.geometry.coordinates as [number, number];

      const marker = document.createElement("div");
      Object.assign(marker.style, {
        width: "13px",
        height: "13px",
        borderRadius: "50%",
        background: colourFor(feature),
        border: "2px solid #0e1116",
        cursor: "pointer",
      });

      new maplibregl.Marker({ element: marker })
        .setLngLat([lon, lat])
        .setPopup(
          new maplibregl.Popup({ offset: 14 }).setHTML(
            `<strong>${feature.name}</strong><br/>` +
              `<span style="color:#57606a">${
                feature.status.summary ?? feature.status.value
              }</span><br/>` +
              `<a href="/${feature.type}/${feature.slug}">details</a>`,
          ),
        )
        .addTo(map.current);
    }

    return () => {
      map.current?.remove();
      map.current = null;
    };
  }, [features]);

  return <div id="map" ref={container} />;
}
