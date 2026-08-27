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

// "Nobody has said anything about this" and "this is shut because it is
// night" were both being painted the same grey, which made the whole map look
// dead and put a route with no information at the same visual weight as a
// live status. Anything without a statement is CONTEXT: thin, dashed, faded.
// Only things somebody has actually reported on get solid colour.
function hasStatus(feature: Feature): boolean {
  return (
    Boolean(feature.status.summary) ||
    (feature.season?.value ?? "unknown") !== "unknown"
  );
}

// Colour by SEASON, not by the hour. Colouring by operational status turned
// the whole map grey after the last lift of the day, which is useless to
// anyone planning a trip — and made a genuine seasonal closure look identical
// to nightfall.
function colourFor(feature: Feature): string {
  if (feature.season?.value && feature.season.value !== "unknown") {
    return COLOURS[feature.season.value] ?? COLOURS.unknown;
  }
  if (!hasStatus(feature)) return "#4a5563";
  return COLOURS.unknown;
}

function isLine(feature: Feature): boolean {
  const kind = feature.geometry?.type;
  return kind === "LineString" || kind === "MultiLineString";
}

export default function MassifMap({ features }: { features: Feature[] }) {
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);

  useEffect(() => {
    if (!container.current || map.current) return;

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
      center: [6.87, 45.9],
      zoom: 10.2,
    });
    map.current = instance;
    instance.addControl(new maplibregl.NavigationControl(), "top-right");

    // ---- points: huts, lift sectors, glaciers
    for (const feature of features) {
      if (feature.geometry?.type !== "Point") continue;
      const [lon, lat] = feature.geometry.coordinates as [number, number];

      const known = hasStatus(feature);
      // Notable now means notable to a PLANNER: shut this season, or under a
      // restriction. Not "shut because it is 3am".
      const notable =
        feature.season?.value === "closed" ||
        feature.season?.value === "restricted";

      const marker = document.createElement("div");
      Object.assign(marker.style, {
        width: notable ? "16px" : known ? "12px" : "8px",
        height: notable ? "16px" : known ? "12px" : "8px",
        borderRadius: "50%",
        background: known ? colourFor(feature) : "transparent",
        border: known
          ? "2px solid #0e1116"
          : "1.5px solid rgba(120,132,145,0.85)",
        boxShadow: notable ? `0 0 0 3px ${colourFor(feature)}33` : "none",
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
        .addTo(instance);
    }

    // ---- lines: routes and couloirs, from camptocamp
    const lines = features.filter(isLine);

    instance.on("load", () => {
      if (lines.length === 0) return;

      instance.addSource("routes", {
        type: "geojson",
        data: {
          type: "FeatureCollection",
          features: lines.map((feature) => ({
            type: "Feature" as const,
            geometry: feature.geometry as GeoJSON.Geometry,
            properties: {
              slug: feature.slug,
              name: feature.name,
              type: feature.type,
              colour: colourFor(feature),
              known: hasStatus(feature) ? 1 : 0,
              summary:
                feature.status.summary ?? "no notices — shown for context",
            },
          })),
        },
      });

      // A dark casing under the line keeps it readable over IGN's busy
      // contours and glacier hatching, where a bare 2px stroke disappears.
      // Casing only under lines that assert something. On a light basemap a
      // dark casing under a thin faded line swamps it — you see the casing,
      // not the route, which is why the context routes vanished.
      instance.addLayer({
        id: "routes-casing",
        type: "line",
        source: "routes",
        filter: ["==", ["get", "known"], 1],
        layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": "#ffffff", "line-width": 7, "line-opacity": 0.9 },
      });

      instance.addLayer({
        id: "routes-line",
        type: "line",
        source: "routes",
        layout: { "line-cap": "round", "line-join": "round" },
        paint: {
          "line-color": ["get", "colour"],
          // A zoom interpolate must be the OUTERMOST expression: it cannot
          // sit inside a case (one interpolate per expression) and it cannot
          // sit inside a multiply either. Since this layer is already
          // filtered to reported routes, per-feature width was never needed —
          // the two layers differ by filter, and each gets a plain
          // interpolate of its own.
          "line-width": ["interpolate", ["linear"], ["zoom"], 9, 2.6, 14, 5],
          "line-opacity": 1,
        },
        filter: ["==", ["get", "known"], 1],
      });

      // Separate layer for context routes: line-dasharray is a paint property
      // that cannot vary per feature, so "dashed when unreported" needs its
      // own layer rather than an expression.
      instance.addLayer({
        id: "routes-context",
        type: "line",
        source: "routes",
        filter: ["!=", ["get", "known"], 1],
        layout: { "line-cap": "butt", "line-join": "round" },
        paint: {
          "line-color": ["get", "colour"],
          "line-width": ["interpolate", ["linear"], ["zoom"], 9, 1.7, 14, 3.2],
          "line-opacity": 0.9,
          // a solid line reads as a claim about the route's condition, and we
          // are not making one
          "line-dasharray": [2, 1.6],
        },
      });

      // Invisible hit target. A 2px line demands pixel-perfect aim; this
      // gives routes the same click tolerance a 16px marker has.
      instance.addLayer({
        id: "routes-hit",
        type: "line",
        source: "routes",
        layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": "#000000", "line-width": 18, "line-opacity": 0 },
      });

      instance.on("click", "routes-hit", (event) => {
        const hit = event.features?.[0];
        if (!hit) return;
        const props = hit.properties as Record<string, string>;
        new maplibregl.Popup({ offset: 8 })
          .setLngLat(event.lngLat)
          .setHTML(
            `<strong>${props.name}</strong><br/>` +
              `<span style="color:#57606a">${props.summary}</span><br/>` +
              `<a href="/${props.type}/${props.slug}">details</a>`,
          )
          .addTo(instance);
      });

      instance.on("mouseenter", "routes-hit", () => {
        instance.getCanvas().style.cursor = "pointer";
      });
      instance.on("mouseleave", "routes-hit", () => {
        instance.getCanvas().style.cursor = "";
      });
    });

    return () => {
      instance.remove();
      map.current = null;
    };
  }, [features]);

  return <div id="map" ref={container} />;
}
