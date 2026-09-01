// Shared map symbology, so the overview map and the feature map cannot drift
// apart in what a hut looks like.

export const COLOURS: Record<string, string> = {
  open: "#3d8f63",
  closed: "#b23c31",
  restricted: "#b3831d",
  unknown: "#6e757e",
};

/** IGN's own refuge symbol, redrawn.
 *
 *  #246138 was sampled from their tiles rather than guessed: 1164 pixels of it
 *  across three tiles at z15 and z16, nothing else close.
 *
 *  We draw this at EVERY zoom, on every hut. The first version faded it out at
 *  z13 on the theory that IGN's own glyph took over — but IGN draws only SOME
 *  huts, and which ones is not predictable from anything we hold. Sampling the
 *  exact pixels around eight huts: Goûter, Cosmiques and Torino get a glyph;
 *  Charpoua, Gonella, Monzino, Trient and Orny get nothing, across both France
 *  and abroad. Deferring to a symbol that is not there left five Swiss huts and
 *  several others invisible at exactly the zoom where you look for them.
 *
 *  Matching their symbol exactly is what makes always-drawing safe: where IGN
 *  does draw one, two identical glyphs land on the same point and read as one.
 *  That was the whole problem with the earlier ring — a different shape on top
 *  of theirs could only ever look like two things. */
export const HUT_GLYPH =
  '<svg viewBox="0 0 16 16" width="15" height="15" aria-hidden="true">' +
  '<path d="M8 1.7 14.6 7.3V14.4H1.4V7.3Z" fill="#246138" ' +
  'stroke="#ffffff" stroke-width="1.1" stroke-linejoin="round"/>' +
  "</svg>";

/** The status pip that hangs off a symbol's corner.
 *
 *  IGN's glyph cannot be recoloured, so a closed hut and an open one look
 *  identical on their cartography. This is the answer: an annotation on the
 *  corner, never over the symbol, so it stays subordinate to it. */
export function pipElement(colour: string, notable: boolean): HTMLElement {
  const pip = document.createElement("div");
  Object.assign(pip.style, {
    position: "absolute",
    top: "-3px",
    right: "-3px",
    width: notable ? "9px" : "8px",
    height: notable ? "9px" : "8px",
    borderRadius: "50%",
    background: colour,
    border: "1.5px solid #ffffff",
    boxShadow: "0 1px 2px rgba(34,40,46,0.45)",
  });
  return pip;
}
