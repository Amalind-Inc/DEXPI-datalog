// Hand-drawn, P&ID-flavoured SVG symbols rendered as Cytoscape node
// background-images. Kept behind a single `symbolFor` lookup keyed off the
// backend `category`/`class_name`, so the authentic DEXPI shape-catalogue
// symbols can later be swapped in without touching the graph code.

const STROKE = "#334155"; // slate-700
const FILL = "#ffffff";

// Explicit width/height (matching the viewBox) is required: Cytoscape renders
// these as `background-image` with `background-fit: contain`, and without an
// intrinsic size the browser clips the symbol instead of scaling it to fit.
function svg(body: string, viewBox = "0 0 64 64"): string {
  const doc = `<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="${viewBox}" fill="none" stroke="${STROKE}" stroke-width="2.25" stroke-linecap="round" stroke-linejoin="round">${body}</svg>`;
  return `data:image/svg+xml;utf8,${encodeURIComponent(doc)}`;
}

// Centrifugal pump: circle with an impeller triangle.
const PUMP = svg(
  `<circle cx="32" cy="32" r="20" fill="${FILL}"/><path d="M32 16 L32 32 L48 32" /><path d="M22 44 L42 44" />`,
);

// Heat exchanger: circle with an internal zig-zag (exchange element).
const EXCHANGER = svg(
  `<circle cx="32" cy="32" r="22" fill="${FILL}"/><path d="M12 32 L22 24 L32 40 L42 24 L52 32" stroke-linejoin="round"/>`,
);

// Vessel / tank / drum: vertical capsule.
const VESSEL = svg(
  `<rect x="18" y="8" width="28" height="48" rx="14" fill="${FILL}"/>`,
);

// Column / tower: tall vessel with internal trays.
const COLUMN = svg(
  `<rect x="20" y="6" width="24" height="52" rx="12" fill="${FILL}"/><path d="M20 22 L44 22"/><path d="M20 34 L44 34"/><path d="M20 46 L44 46"/>`,
);

// Valve: bow-tie.
const VALVE = svg(
  `<path d="M14 18 L14 46 L32 32 Z" fill="${FILL}"/><path d="M50 18 L50 46 L32 32 Z" fill="${FILL}"/>`,
);

// Instrument: balloon circle with a centre line.
const INSTRUMENT = svg(
  `<circle cx="32" cy="32" r="20" fill="${FILL}"/><path d="M12 32 L52 32"/>`,
);

// Generic tagged item fallback.
const GENERIC = svg(`<rect x="10" y="16" width="44" height="32" rx="6" fill="${FILL}"/>`);

export type SymbolKey =
  | "pump"
  | "exchanger"
  | "vessel"
  | "column"
  | "valve"
  | "instrument"
  | "generic";

const SYMBOLS: Record<SymbolKey, string> = {
  pump: PUMP,
  exchanger: EXCHANGER,
  vessel: VESSEL,
  column: COLUMN,
  valve: VALVE,
  instrument: INSTRUMENT,
  generic: GENERIC,
};

export function symbolKeyFor(category: string, className: string): SymbolKey {
  const c = className.toLowerCase();
  if (c.includes("pump")) return "pump";
  if (c.includes("exchanger") || c.includes("cooler") || c.includes("heater")) return "exchanger";
  if (c.includes("column") || c.includes("tower")) return "column";
  if (c.includes("tank") || c.includes("vessel") || c.includes("drum") || c.includes("separator"))
    return "vessel";
  if (c.includes("valve")) return "valve";
  if (category === "instrument") return "instrument";
  return "generic";
}

export function symbolDataUri(key: SymbolKey): string {
  return SYMBOLS[key];
}

export function symbolFor(category: string, className: string): string {
  return SYMBOLS[symbolKeyFor(category, className)];
}
