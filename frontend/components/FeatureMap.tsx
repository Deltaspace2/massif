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
  open: "#3d8f63",
  closed: "#b23c31",
  restricted: "#b3831d",
  unknown: "#6e757e",
};

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
      center: bounds ? bounds.getCenter() : MASSIF_CENTRE,
      zoom: bounds ? (isLine ? 11 : 14) : MASSIF_ZOOM,
    });
    map.current = instance;
    instance.addControl(new maplibregl.NavigationControl(), "top-right");

    if (plotted && !isLine) {
      const marker = document.createElement("div");
      // This map shows ONE feature and is centred on it, so there is no
      // question which building the page is about — the basemap's own symbol
      // is already sitting there saying so. A second icon on top of it adds
      // nothing and reads as a duplicate, which is exactly what it is.
      //
      // A soft halo instead: it draws the eye to the right point without
      // claiming to be the symbol for it. Where a source has actually
      // published something the halo takes that status colour, so the one
      // piece of information we hold is the one thing we draw.
      Object.assign(marker.style, {
        width: "30px",
        height: "30px",
        borderRadius: "50%",
        background: `radial-gradient(circle, ${colour}00 42%, ${colour}44 60%, ${colour}00 78%)`,
      });
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
