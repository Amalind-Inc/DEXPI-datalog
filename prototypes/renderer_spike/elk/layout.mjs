// THROWAWAY tier-2 auto-layout sample (bead 2ki.2).
// pid_view JSON (backend compressed topology) -> ELK layered layout -> SVG.
// Run: node prototypes/renderer_spike/elk/layout.mjs
import ELK from "elkjs/lib/elk.bundled.js";
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const out = join(here, "..", "out");
const elk = new ELK();

const UNIT_W = 120, UNIT_H = 80;

async function layout(name) {
  const pv = JSON.parse(readFileSync(join(out, `${name}-pidview.json`), "utf8"));
  const known = new Set(pv.units.flatMap((u) => [u.id, ...u.ports.map((p) => p.id)]));
  // Lines may end at ids outside the unit set (off-page connectors, junction
  // nodes the compression didn't fold into a unit). Give those endpoints small
  // pseudo-nodes so connectivity stays complete — mirrors the production plan
  // where such endpoints become explicit connector glyphs.
  const pseudo = new Map();
  const endpoint = (id, fallback) => {
    const want = id ?? fallback;
    if (want == null) return null;
    if (known.has(want)) return want;
    if (!pseudo.has(want)) pseudo.set(want, { id: want, width: 26, height: 26, labels: [{ text: "\u2299" }] });
    return want;
  };
  const edges = [];
  for (const l of pv.lines) {
    const s = endpoint(l.source_port, l.source_unit);
    const t = endpoint(l.target_port, l.target_unit);
    if (s == null || t == null || s === t) continue;
    edges.push({ id: l.id, sources: [s], targets: [t], labels: l.label ? [{ text: l.label }] : [] });
  }
  const graph = {
    id: "root",
    layoutOptions: {
      "elk.algorithm": "layered",
      "elk.direction": "RIGHT",
      "elk.edgeRouting": "ORTHOGONAL",
      "elk.layered.spacing.nodeNodeBetweenLayers": "90",
      "elk.spacing.nodeNode": "60",
      "elk.portConstraints": "FIXED_SIDE",
    },
    children: [
      ...pv.units.map((u) => ({
        id: u.id,
        width: UNIT_W,
        height: UNIT_H,
        labels: [{ text: u.label }],
        ports: u.ports.map((p, i) => ({
          id: p.id,
          width: 6,
          height: 6,
          layoutOptions: { "elk.port.side": i % 2 === 0 ? "WEST" : "EAST" },
        })),
      })),
      ...pseudo.values(),
    ],
    edges,
  };
  const res = await elk.layout(graph);

  // SVG emission: labeled boxes + orthogonal runs, uniform "inferred" styling.
  const cls = Object.fromEntries(pv.units.map((u) => [u.id, u.class_name]));
  const parts = [];
  for (const n of res.children) {
    parts.push(
      `<rect x="${n.x}" y="${n.y}" width="${n.width}" height="${n.height}" rx="6" fill="white" stroke="#334" stroke-width="1.5"/>`,
      `<text x="${n.x + n.width / 2}" y="${n.y + n.height / 2 - 6}" text-anchor="middle" font-size="13" font-weight="600">${n.labels?.[0]?.text ?? n.id}</text>`,
      `<text x="${n.x + n.width / 2}" y="${n.y + n.height / 2 + 12}" text-anchor="middle" font-size="10" fill="#667">${cls[n.id] ?? ""}</text>`,
    );
    for (const p of n.ports ?? []) {
      parts.push(`<circle cx="${n.x + p.x + 3}" cy="${n.y + p.y + 3}" r="3" fill="#334"/>`);
    }
  }
  for (const e of res.edges ?? []) {
    for (const sec of e.sections ?? []) {
      const pts = [sec.startPoint, ...(sec.bendPoints ?? []), sec.endPoint]
        .map((p) => `${p.x},${p.y}`).join(" ");
      // dashed = the uniform inferred-routing cue
      parts.push(`<polyline points="${pts}" fill="none" stroke="#556" stroke-width="1.5" stroke-dasharray="6 3"/>`);
    }
    const lbl = e.labels?.[0];
    if (lbl && lbl.x != null) {
      parts.push(`<text x="${lbl.x}" y="${lbl.y}" font-size="9" fill="#889">${lbl.text}</text>`);
    }
  }
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="-20 -20 ${res.width + 40} ${res.height + 40}" width="${res.width + 40}" height="${res.height + 40}"><rect x="-20" y="-20" width="100%" height="100%" fill="white"/>${parts.join("")}</svg>`;
  writeFileSync(join(out, `${name}-elk.svg`), svg);
  console.log(`${name}: ${res.children.length} units, ${res.edges?.length ?? 0} lines -> ${res.width}x${res.height}`);
}

await layout("e06");
await layout("c01");
