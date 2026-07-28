from __future__ import annotations

import unittest

from pydexpi_datalog.workflow.render_bundle import (
    RENDER_BUNDLE_SCHEMA_VERSION,
    build_render_bundle,
)


class RenderBundleTests(unittest.TestCase):
    def test_bundle_is_source_versioned_and_excludes_session_mutable_overlays(self) -> None:
        topology = {
            "nodes": [{"id": "pump-1"}],
            "edges": [{"id": "edge-1", "source_id": "pump-1", "target_id": "valve-1"}],
            "pid_view": {"units": [{"id": "pump-1"}], "lines": [], "hidden_topology_ids": []},
            "schematic_scene": {"symbols": [{"id": "symbol-1"}]},
            "schematic_scene_kind": "as-drawn",
            "geometry_report": {"passed": True},
            "visible_source_scope": ["pump-1"],
            "evidence_highlight": {"matched_object_ids": ["pump-1"]},
        }

        bundle = build_render_bundle(source_bytes=b"<PlantItem ID='P-101'/>", topology=topology)

        self.assertEqual(bundle["schema_version"], RENDER_BUNDLE_SCHEMA_VERSION)
        self.assertEqual(len(bundle["source_digest"]), 64)
        self.assertEqual(
            bundle["render_data"],
            {
                "nodes": topology["nodes"],
                "edges": topology["edges"],
                "pid_view": topology["pid_view"],
                "schematic_scene": topology["schematic_scene"],
                "schematic_scene_kind": "as-drawn",
                "geometry_report": topology["geometry_report"],
            },
        )
        self.assertNotIn("visible_source_scope", bundle["render_data"])
        self.assertNotIn("evidence_highlight", bundle["render_data"])


if __name__ == "__main__":
    unittest.main()
