import type { PidView } from "@/components/pid/types";

// Given the topology ids the chat highlighted (equipment, nozzles, internal
// piping nodes, segments...), decide which compressed units and lines should
// glow. A unit lights up if it or any of its ports is cited; a line lights up
// if it or any of its collapsed member ids is cited.
export function highlightSets(
  pidView: PidView,
  highlighted: string[],
): { units: Set<string>; lines: Set<string> } {
  const set = new Set(highlighted);
  const units = new Set<string>();
  for (const unit of pidView.units) {
    if (set.has(unit.id) || unit.ports.some((p) => set.has(p.id))) units.add(unit.id);
  }
  const lines = new Set<string>();
  for (const line of pidView.lines) {
    if (line.id && (set.has(line.id) || line.memberTopologyIds.some((m) => set.has(m)))) {
      lines.add(line.id);
    }
  }
  return { units, lines };
}
