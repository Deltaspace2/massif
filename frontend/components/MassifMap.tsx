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
  open: "#3d8f63",
  closed: "#b23c31",
  restricted: "#b3831d",
  unknown: "#6e757e",
};

// IGN's own refuge symbol, redrawn. Sampled from their tiles rather than
// guessed: #246138 is the glyph green, 1164 pixels of it across three tiles at
// z15 and z16, with nothing else close.
//
// Matching them exactly is the point. This is shown only BELOW z13, where IGN
// draws no hut at all, and it disappears at z13 as theirs appears — so the
// same green house is on the same spot the whole way in and the handover is
// invisible. Drawing our own shape here would have reintroduced the two
// symbols problem in slow motion.
//
// The one risk, noted because it is this project's failure mode: green is also
// the open colour. A green hut is a MAP symbol meaning "hut", exactly as it is
// on IGN's own cartography, and never a claim that it is open — status is the
// separate coloured dot, drawn at every zoom. The white outline is ours, and
// only so the glyph survives glacier hatching and shaded slopes.
const HUT_GLYPH =
  '<svg viewBox="0 0 16 16" width="15" height="15" aria-hidden="true">' +
  '<path d="M8 1.7 14.6 7.3V14.4H1.4V7.3Z" fill="#246138" ' +
  'stroke="#ffffff" stroke-width="1.1" stroke-linejoin="round"/>' +
  "</svg>";

// Context routes on the light basemap. This has now been wrong twice: #4a5563
// was chosen against a near-black page and read as a claim on IGN's pale
// cartography; #9aa2ab fixed that and went too far the other way — at 2.51:1
// it is the token this project explicitly marks "never text", and a 1.7px
// dashed line in it is invisible over contour lines and glacier hatching.
// #6e757e is the same grey the unknown status uses, at 4.53:1. The dash is
// what says "we are not claiming anything about this route"; the weight and
// the casing are what make it findable. Those are separate jobs.
const CONTEXT = "#6e757e";

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
  if (!hasStatus(feature)) return CONTEXT;
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

    // Locator dots for features nothing has been published about. Collected
    // so a zoom handler can stand them down once IGN starts drawing its own
    // hut symbols.
    const contextDots: HTMLElement[] = [];

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
      const isUnknown = !known || feature.season?.value === "unknown";
      const isHut = feature.type === "hut";

      // The outer element is only ever a hit area: constant size, never
      // styled, so a feature stays clickable at every zoom regardless of what
      // is drawn inside it. position:relative so the status pip can hang off
      // the corner rather than sitting on top of the symbol.
      Object.assign(marker.style, {
        width: "18px",
        height: "18px",
        cursor: "pointer",
        position: "relative",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      });

      // ---- the symbol: what the thing IS
      const dot = document.createElement("div");
      if (isHut) {
        // Ours below z13, IGN's from z13 up, same green house either way.
        contextDots.push(dot);
        dot.innerHTML = HUT_GLYPH;
        Object.assign(dot.style, {
          width: "15px",
          height: "15px",
          lineHeight: "0",
          transition: "opacity 120ms linear",
        });
      } else if (isUnknown) {
        // Lift sectors and glaciers keep a dot: a house would be a lie about
        // what they are, and IGN draws no glyph we could defer to.
        Object.assign(dot.style, {
          width: "8px",
          height: "8px",
          borderRadius: "50%",
          background: "rgba(255,255,255,0.92)",
          border: `1.5px solid ${COLOURS.unknown}`,
        });
      } else {
        Object.assign(dot.style, {
          width: notable ? "16px" : "14px",
          height: notable ? "16px" : "14px",
          borderRadius: "50%",
          background: colourFor(feature),
          border: "2px solid #ffffff",
          boxShadow: `0 0 0 1px ${colourFor(feature)}55, 0 1px 3px rgba(34,40,46,0.35)`,
        });
      }
      marker.appendChild(dot);

      // ---- the pip: what a source has SAID about it
      //
      // IGN's hut glyph is theirs and cannot be removed or recoloured, so a
      // closed hut and an open one look identical on their cartography. This
      // is the answer to that: a small status pip on the corner of the symbol,
      // never over it. It is subordinate by construction — an annotation on
      // someone else's icon rather than a second icon competing with it, which
      // is what made the earlier ring look wrong.
      //
      // Drawn at EVERY zoom, and in the same corner whether the house beneath
      // it is ours or IGN's, so a closure does not blink out of existence at
      // the handover. Only for features something has actually been published
      // about: a pip on all 59 huts would be 57 pips meaning "no news".
      if (isHut && !isUnknown) {
        const pip = document.createElement("div");
        Object.assign(pip.style, {
          position: "absolute",
          top: "-3px",
          right: "-3px",
          width: notable ? "9px" : "8px",
          height: notable ? "9px" : "8px",
          borderRadius: "50%",
          background: colourFor(feature),
          border: "1.5px solid #ffffff",
          boxShadow: "0 1px 2px rgba(34,40,46,0.45)",
        });
        marker.appendChild(pip);
      }

      new maplibregl.Marker({ element: marker })
        .setLngLat([lon, lat])
        .setPopup(
          new maplibregl.Popup({ offset: 14 }).setHTML(
            `<strong>${feature.name}</strong><br/>` +
              `<span style="color:#5f6873">${
                feature.status.summary ?? feature.status.value
              }</span><br/>` +
              `<a href="/${feature.type}/${feature.slug}">details</a>`,
          ),
        )
        .addTo(instance);
    }

    // ---- lines: routes and couloirs, from camptocamp
    const lines = features.filter(isLine);

    // IGN's PLANIGNV2 begins drawing its refuge glyph at z13 — measured by
    // fetching tiles over the Goûter and the Cosmiques at z11 to z16 and
    // counting the glyph's green: nothing at 11 or 12, present from 13 on.
    // This map opens at 10.2, which is why removing our dots outright made
    // every hut disappear from the default view.
    const BASEMAP_DRAWS_HUTS_FROM = 13;
    const syncContextDots = () => {
      const ours = instance.getZoom() < BASEMAP_DRAWS_HUTS_FROM;
      for (const dot of contextDots) dot.style.opacity = ours ? "1" : "0";
    };
    // Opacity, not display: the hit area is the parent and is untouched, so a
    // hut stays clickable at high zoom even though our dot has stepped aside.
    instance.on("zoom", syncContextDots);
    syncContextDots();

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
        paint: { "line-color": "#ffffff", "line-width": 8.5, "line-opacity": 0.95 },
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
          "line-width": ["interpolate", ["linear"], ["zoom"], 9, 3.2, 14, 6],
          "line-opacity": 1,
        },
        filter: ["==", ["get", "known"], 1],
      });

      // Separate layer for context routes: line-dasharray is a paint property
      // that cannot vary per feature, so "dashed when unreported" needs its
      // own layer rather than an expression.
      // Context routes get a white casing of their own. An earlier note here
      // said casing swamped them — that was a DARK casing, from the dark-theme
      // era. On a pale basemap a white casing does the opposite: it clears a
      // gap around the dashes so they survive contour lines underneath.
      instance.addLayer({
        id: "routes-context-casing",
        type: "line",
        source: "routes",
        filter: ["!=", ["get", "known"], 1],
        layout: { "line-cap": "butt", "line-join": "round" },
        paint: {
          "line-color": "#ffffff",
          "line-width": ["interpolate", ["linear"], ["zoom"], 9, 5, 14, 8],
          "line-opacity": 0.85,
        },
      });

      instance.addLayer({
        id: "routes-context",
        type: "line",
        source: "routes",
        filter: ["!=", ["get", "known"], 1],
        layout: { "line-cap": "butt", "line-join": "round" },
        paint: {
          "line-color": ["get", "colour"],
          "line-width": ["interpolate", ["linear"], ["zoom"], 9, 2.6, 14, 4.4],
          "line-opacity": 1,
          // A solid line would read as a claim about the route's condition and
          // we are not making one. Longer dashes with a wider gap read as
          // deliberately provisional at a glance, where the old [2, 1.6] at
          // 1.7px just read as a faint smudge.
          "line-dasharray": [2.6, 2],
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
              `<span style="color:#5f6873">${props.summary}</span><br/>` +
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

  return <div className="map-canvas" ref={container} />;
}
