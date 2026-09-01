"use client";

import { useEffect, useRef } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { FeatureDetail } from "@/lib/api";
import {
  COLOURS,
  HUT_GLYPH,
  IGN_ATTRIBUTION,
  IGN_VECTOR_STYLE,
  dropIgnHutSymbols,
  pipElement,
} from "./mapSymbols";

// Fallback view when a feature has no geometry: the massif, not a guess at
// where the feature is.
const MASSIF_CENTRE: [number, number] = [6.87, 45.9];
const MASSIF_ZOOM = 10.2;

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

  const plotted = points.length > 0;

  useEffect(() => {
    if (!container.current || map.current) return;

    const colour =
      feature.season?.value && feature.season.value !== "unknown"
        ? COLOURS[feature.season.value] ?? COLOURS.unknown
        : COLOURS.unknown;
    const isLine = geometry?.type !== "Point";

    const lons = points.map((p) => p[0]);
    const lats = points.map((p) => p[1]);
    const bounds = plotted
      ? new maplibregl.LngLatBounds(
          [Math.min(...lons), Math.min(...lats)],
          [Math.max(...lons), Math.max(...lats)],
        )
      : null;

    const instance = new maplibregl.Map({
      container: container.current,
      style: IGN_VECTOR_STYLE,
      attributionControl: false,
      // A single point has no extent to fit, so it gets a sensible zoom
      // instead; a line gets fitted with padding once the style is up.
      center: bounds ? bounds.getCenter() : MASSIF_CENTRE,
      zoom: bounds ? (isLine ? 11 : 14) : MASSIF_ZOOM,
    });
    map.current = instance;
    instance.addControl(new maplibregl.NavigationControl(), "top-right");
    instance.addControl(
      new maplibregl.AttributionControl({ customAttribution: IGN_ATTRIBUTION }),
    );
    instance.on("style.load", () => dropIgnHutSymbols(instance));

    if (plotted && !isLine) {
      const marker = document.createElement("div");
      // The page said "hut · 3170 m" and then showed a pale ring on a glacier.
      // A halo marks a spot; it does not say what is standing on it, and on
      // light cartography it read as an empty circle.
      //
      // The same green house as the overview map, from the same module so the
      // two cannot drift. Drawn whatever IGN does here: sampling the pixels
      // around eight huts showed IGN symbolises only some of them — Trient and
      // Orny get nothing at any zoom — so deferring to their glyph left Swiss
      // huts with no symbol at all on their own page.
      //
      // Never set `position` on this element: MapLibre owns it and positions
      // it with a class plus a transform. The pip hangs off the wrapper.
      Object.assign(marker.style, {
        width: "22px",
        height: "22px",
        cursor: "default",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      });

      const holder = document.createElement("div");
      Object.assign(holder.style, {
        position: "relative",
        width: "100%",
        height: "100%",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      });

      const symbol = document.createElement("div");
      if (feature.type === "hut") {
        symbol.innerHTML = HUT_GLYPH;
        Object.assign(symbol.style, {
          width: "18px",
          height: "18px",
          lineHeight: "0",
        });
      } else {
        // Not a hut, so a house would be a lie about what it is.
        Object.assign(symbol.style, {
          width: "14px",
          height: "14px",
          borderRadius: "50%",
          background: colour,
          border: "2px solid #ffffff",
          boxShadow: `0 0 0 1px ${colour}55, 0 1px 3px rgba(34,40,46,0.35)`,
        });
      }
      holder.appendChild(symbol);

      // Status on the corner, exactly as on the overview map — and only when a
      // source has actually said something, so an unknown hut does not wear a
      // grey badge implying we checked.
      const known =
        feature.season?.value && feature.season.value !== "unknown";
      if (feature.type === "hut" && known) {
        holder.appendChild(
          pipElement(
            colour,
            feature.season?.value === "closed" ||
              feature.season?.value === "restricted",
          ),
        );
      }
      marker.appendChild(holder);
      new maplibregl.Marker({ element: marker })
        .setLngLat(points[0])
        .addTo(instance);
    }

    instance.on("load", () => {
      // `geometry` is nullable — the Goûter route and the Grand Couloir have
      // none on purpose, because nobody has surveyed them and a drawn line
      // would claim a precision that does not exist. Narrow it rather than
      // asserting: an unsurveyed feature simply has no line.
      if (plotted && isLine && geometry) {
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
        if (bounds) instance.fitBounds(bounds, { padding: 48, duration: 0, maxZoom: 14 });
      }
    });

    return () => {
      instance.remove();
      map.current = null;
    };
  }, [feature, geometry, points, plotted]);

  // Every feature page gets a map, including the ones we cannot draw. Showing
  // the massif with an explicit "not plotted" band is more honest than showing
  // nothing — nothing reads as "not tracked", and it is not: the Goûter route
  // and the Grand Couloir are tracked carefully and simply have no surveyed
  // line, because inventing one would claim a precision that does not exist.
  return (
    <figure className="feature-map-wrap">
      <div className="feature-map" ref={container} />
      {!plotted && (
        <figcaption className="feature-map-note">
          <b>Not plotted.</b> Nobody has surveyed a line for this, so the map
          shows the massif rather than a guess. It is tracked all the same —
          everything below is about this feature.
        </figcaption>
      )}
    </figure>
  );
}
