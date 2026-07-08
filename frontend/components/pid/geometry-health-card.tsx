"use client";

import { usePidGraph } from "@/components/pid/graph-context";
import { describeSchematicTier } from "@/lib/schematic-scene";

const REASON_TEXT: Record<string, string> = {
  degenerate_extent: "the drawing extent is degenerate",
  low_pipe_coverage: "too few pipe runs carry a drawn centerline",
  unpositioned_equipment: "too much equipment has no source position",
  no_geometry_source: "the file carries no usable drawing geometry",
};

// Per-file geometry health summary (bead 2ki.8): describes, never repairs.
// Every stat below reads a field straight off the same typed geometry
// report the renderer badges (schematic-tier-badge / auto-layout-badge)
// derive their label from, via the shared describeSchematicTier helper --
// so the card and the badges can never disagree.
export function GeometryHealthCard() {
  const { geometryReport, schematicSceneKind } = usePidGraph();
  if (!geometryReport) return null;

  const { tier, label } = describeSchematicTier(schematicSceneKind, geometryReport);
  const placedCount = geometryReport.unpositionedEquipment.total - geometryReport.unpositionedEquipment.missing;

  return (
    <details className="geometry-health-card" data-testid="geometry-health-card">
      <summary className="geometry-health-summary" data-testid="geometry-health-summary" data-tier={tier}>
        {label}
      </summary>
      <ul className="geometry-health-stats">
        {geometryReport.unpositionedEquipment.total > 0 && (
          <li className="geometry-health-stat" data-testid="geometry-health-stat" data-kind="placed">
            {placedCount} of {geometryReport.unpositionedEquipment.total} equipment items placed as drawn
          </li>
        )}
        {geometryReport.pipeCoverage.segments > 0 && (
          <li className="geometry-health-stat" data-testid="geometry-health-stat" data-kind="routed">
            {geometryReport.pipeCoverage.segmentsWithCenterline} of {geometryReport.pipeCoverage.segments} pipe
            runs drawn as-drawn — {geometryReport.routedPipeRuns.length} routed from source-stated endpoints
          </li>
        )}
        {geometryReport.shelvedEquipment.length > 0 && (
          <li className="geometry-health-stat" data-testid="geometry-health-stat" data-kind="shelved">
            {geometryReport.shelvedEquipment.length} item{geometryReport.shelvedEquipment.length === 1 ? "" : "s"} on
            the shelf — position not in source
          </li>
        )}
        <li className="geometry-health-stat" data-testid="geometry-health-stat" data-kind="gate">
          {geometryReport.passed
            ? "Passed the geometry sanity gate"
            : `Did not pass the geometry sanity gate: ${geometryReport.reasons
                .map((reason) => REASON_TEXT[reason] ?? reason)
                .join(", ")}`}
        </li>
      </ul>
    </details>
  );
}
