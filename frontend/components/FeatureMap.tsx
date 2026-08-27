"use client";

import { useEffect, useRef } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { FeatureDetail } from "@/lib/api";

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

/** Every coordinate in a geometry, flattened — enough to fit the view. */
function positions(geometry: GeoJSON.Geometry | null): [number, number][] {
  if (!geometry) return [];
  if (geometry.type === "Point") return [geometry.coordinates as [number, number]];
  if (geometry.type === "LineString") return geometry.coordinates as [number, number][];
  if (geometry.type === "MultiLineString") {
    return (geometry.coordinates as [number, number][][]).flat();
  }
  if (geometry.type === "Polygon") {
    return (geometry.coordinates as [number, number][][]).flat();
  }
  return [];
}

export default function FeatureMap({ feature }: { feature: FeatureDetail }) {
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);

  const geometry = (feature.geometry ?? null) as GeoJSON.Geometry | null;
  const points = positions(geometry);

  useEffect(() => {
    if (!container.current || map.current || points.length === 0) return;

    const colour =
      feature.season?.value && feature.season.value !== "unknown"
        ? COLOURS[feature.season.value] ?? COLOURS.unknown
        : COLOURS.unknown;
    const isLine = geometry?.type !== "Point";

    const lons = points.map((p) => p[0]);
    const lats = points.map((p) => p[1]);
    const bounds = new maplibregl.LngLatBounds(
      [Math.min(...lons), Math.min(...lats)],
      [Math.max(...lons), Math.max(...lats)],
    );

    const instance = new maplibregl.Map({
      container: container.current,
      style: {
        version: 8,
        sources: {
          ign: {
            type: "raster",
            tiles: [IGN_PLAN],
            tileSize: 256,
            attribution: "© IGN Géoplateforme · routes © camptocamp.org",
          },
        },
        layers: [{ id: "ign", type: "raster", source: "ign" }],
      },
      // A single point has no extent to fit, so it gets a sensible zoom
      // instead; a line gets fitted with padding once the style is up.
      center: bounds.getCenter(),
      zoom: isLine ? 11 : 14,
    });
    map.current = instance;
    instance.addControl(new maplibregl.NavigationControl(), "top-right");

    if (!isLine) {
      const marker = document.createElement("div");
      Object.assign(marker.style, {
        width: "16px",
        height: "16px",
        borderRadius: "50%",
        background: colour,
        border: "2px solid #0e1116",
        boxShadow: `0 0 0 4px ${colour}33`,
      });
      new maplibregl.Marker({ element: marker })
        .setLngLat(points[0])
        .addTo(instance);
    }

    instance.on("load", () => {
      if (isLine) {
        instance.addSource("feature", {
          type: "geojson",
          data: { type: "Feature", geometry, properties: {} },
        });
        instance.addLayer({
          id: "feature-casing",
          type: "line",
          source: "feature",
          layout: { "line-cap": "round", "line-join": "round" },
          paint: { "line-color": "#ffffff", "line-width": 8, "line-opacity": 0.9 },
        });
        instance.addLayer({
          id: "feature-line",
          type: "line",
          source: "feature",
          layout: { "line-cap": "round", "line-join": "round" },
          paint: { "line-color": colour, "line-width": 4 },
        });
        instance.fitBounds(bounds, { padding: 48, duration: 0, maxZoom: 14 });
      }
    });

    return () => {
      instance.remove();
      map.current = null;
    };
  }, [feature, geometry, points]);

  if (points.length === 0) {
    return (
      <p className="meta" style={{ marginTop: 12 }}>
        No geometry for this feature yet — we would rather show nothing than
        put it in the wrong place.
      </p>
    );
  }

  return <div className="feature-map" ref={container} />;
}
