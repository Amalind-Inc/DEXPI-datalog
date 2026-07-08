"""Build a tier-1 (drawing-faithful) schematic scene from Proteus geometry.

Production port of the renderer spike (bead pydexpi-datalog-1-2ki.2; decisions
in prototypes/renderer_spike/NOTES.md). A DEXPI/Proteus export that carries
source geometry (catalogue shapes, as-drawn positions, drawn centerlines) can
be painted as a schematic scene that shows the drawing as authored, rather
than an auto-laid-out topology diagram (see ADR 0004). Scene preparation is
backend-owned (ADR 0005); the frontend paints the scene verbatim.

Every plant-item / segment scene object carries the same stable topology id
the rest of the review workflow uses (via the Proteus `ID` attribute, which
equals the `proteusId` graph-fact attribute), so hit-testing a schematic
object and selecting a topology object are the same identity. Objects with no
topology counterpart (drawing frame, catalogue-referenced label leaders, world
polygons) fall back to a namespace-qualified id so scene ids never collide
across sources sharing an artifact root (1.2 exports reuse raw ids like
`TaggedPlantItemShape-1` across files).
"""
from __future__ import annotations

import math
from pathlib import Path
import xml.etree.ElementTree as ET

from .bundled_symbols import BUNDLED_SYMBOLS, GENERIC_PLACEHOLDER

_NON_ITEM_TAGS = frozenset(
    {
        "GenericAttributes", "GenericAttribute", "Presentation", "Position",
        "Location", "Axis", "Reference", "ConnectionPoints", "Node",
        "PersistentID", "Extent", "Min", "Max", "Scale", "Connection",
        "Association", "ObjectAttributesReference",
        "TextStringFormatSpecification", "PlantInformation", "UnitsOfMeasure",
        "MetaData",
    }
)

_SIGNAL_PARENT_TAGS = frozenset(
    {
        "ProcessInstrumentationFunction", "InformationFlow",
        "SignalConveyingFunction", "ActuatingFunction", "SignalLine",
    }
)

_LINE_TYPE_DASH = {"1": "4 2", "2": "1 2", "3": "6 2 1 2", "4": "6 2 1 2 1 2"}


def build_schematic_scene(
    *,
    dexpi_xml_path: Path,
    proteus_id_to_topology_id: dict[str, str],
    namespace: str,
) -> dict[str, object] | None:
    """Return a schematic scene, or None if the source carries no geometry.

    `proteus_id_to_topology_id` maps the Proteus `ID`/`proteusId` value of a
    plant item, nozzle, or segment to the stable topology id already used by
    the rest of the review workflow (see `build_stable_node_id_map`).
    """
    scene = build_schematic_scene_report(
        dexpi_xml_path=dexpi_xml_path,
        proteus_id_to_topology_id=proteus_id_to_topology_id,
        namespace=namespace,
    )
    if not has_drawable_geometry(scene):
        return None
    return scene


def build_schematic_scene_report(
    *,
    dexpi_xml_path: Path,
    proteus_id_to_topology_id: dict[str, str],
    namespace: str,
) -> dict[str, object]:
    """Return the raw scene (with its geometry diagnostics report) unfiltered.

    Unlike `build_schematic_scene`, this never returns None -- callers that
    need the diagnostics report even for sources with no drawable content
    (the geometry sanity gate, bead pydexpi-datalog-1-2ki.5) use this instead.
    """
    root = ET.parse(dexpi_xml_path).getroot()
    builder = _SceneBuilder(proteus_id_to_topology_id, namespace)
    return builder.build(root)


def has_drawable_geometry(scene: dict[str, object]) -> bool:
    """Distinguish real geometry from pedagogical fixtures with empty stubs.

    Some fixtures declare a CenterLine or Shape element with zero coordinates
    (a placeholder, not drawn geometry). A scene with only such stubs has
    nothing to paint, so it is equivalent to no geometry at all -- final
    presence thresholds are the sanity gate's job (2ki.5), this is just "is
    there anything to draw".
    """
    if scene["symbols"]:
        return True
    if any(len(polyline["points"]) >= 2 for polyline in scene["polylines"]):
        return True
    if any(len(polygon["points"]) >= 3 for polygon in scene["polygons"]):
        return True
    return False


class _SceneBuilder:
    def __init__(self, proteus_id_to_topology_id: dict[str, str], namespace: str) -> None:
        self._topology_id_of = proteus_id_to_topology_id
        self._namespace = namespace
        self._fallback_seq = 0
        self._position_by_raw_id: dict[str, tuple[float, float]] = {}
        self._connection_index: dict[str, list[str]] = {}
        self._pending_shelf: list[dict[str, object]] = []

    def build(self, root: ET.Element) -> dict[str, object]:
        plant_info = root.find("PlantInformation")
        units = plant_info.attrib.get("Units", "mm") if plant_info is not None else "mm"
        scene: dict[str, object] = {
            "units": units,
            "extent": None,
            "catalogue": _build_catalogue(root),
            "symbols": [],
            "polylines": [],
            "polygons": [],
            "texts": [],
            "report": {
                "items_with_shape": 0,
                "items_with_bundled_shape": 0,
                "items_missing_position": 0,
                "segments": 0,
                "segments_with_centerline": 0,
                "routed_pipe_runs": [],
                "shelved_equipment": [],
                "generic_placeholders": [],
            },
        }
        self._position_by_raw_id = _index_positions(root)
        self._connection_index = _index_connections(root)
        catalogue_el = root.find("ShapeCatalogue")
        self._walk(root, scene, catalogue_el, in_drawing=False)

        drawing = root.find("Drawing")
        if drawing is not None:
            extent_el = drawing.find("Extent")
            if extent_el is not None and extent_el.find("Min") is not None:
                mn, mx = extent_el.find("Min").attrib, extent_el.find("Max").attrib
                scene["extent"] = {
                    "x0": _fnum(mn.get("X")), "y0": _fnum(mn.get("Y")),
                    "x1": _fnum(mx.get("X")), "y1": _fnum(mx.get("Y")),
                }
        self._finalize_shelf(scene)
        return scene

    def _walk(
        self,
        el: ET.Element,
        scene: dict[str, object],
        catalogue_el: ET.Element | None,
        *,
        in_drawing: bool,
    ) -> None:
        for child in el:
            if child is catalogue_el:
                continue
            tag = child.tag
            if tag == "Label":
                self._emit_label(child, scene)
                continue
            if tag in _NON_ITEM_TAGS:
                continue
            if tag == "CenterLine":
                self._emit_centerline(el, child, scene)
                continue
            if tag == "Text":
                if _read_position(child) is not None:
                    scene["texts"].append(_read_text(child))
                continue
            if tag == "PolyLine" and in_drawing:
                scene["polylines"].append(
                    {
                        "id": self._fallback_id("frame"),
                        "topology_id": None,
                        "kind": "frame",
                        "points": _read_points(child),
                        "inferred": False,
                        **_presentation_style(child),
                    }
                )
                continue
            if tag == "Shape":
                scene["polygons"].append(
                    {
                        "points": _read_points(child),
                        "filled": child.attrib.get("Filled") == "Solid",
                        **_presentation_style(child),
                    }
                )
                continue

            component_name = child.attrib.get("ComponentName")
            raw_id = child.attrib.get("ID", "")
            if component_name:
                self._emit_symbol(
                    scene,
                    catalogue=scene["catalogue"],
                    component_name=component_name,
                    class_name=child.attrib.get("ComponentClass", ""),
                    raw_id=raw_id,
                    element=child,
                )
            if tag == "PipingNetworkSegment":
                report = scene["report"]
                report["segments"] += 1
                if child.find("CenterLine") is not None:
                    report["segments_with_centerline"] += 1
                else:
                    self._emit_routed_pipe(child, scene)
            self._walk(child, scene, catalogue_el, in_drawing=in_drawing or tag == "Drawing")

    def _emit_symbol(
        self,
        scene: dict[str, object],
        *,
        catalogue: dict[str, object],
        component_name: str,
        class_name: str,
        raw_id: str,
        element: ET.Element,
    ) -> None:
        report = scene["report"]
        position = _read_position(element)
        shape_key = self._resolve_shape_key(
            scene,
            catalogue=catalogue,
            component_name=component_name,
            class_name=class_name,
            raw_id=raw_id,
        )
        if position is None:
            report["items_missing_position"] += 1
            self._defer_shelf(
                shape_key=shape_key,
                class_name=class_name,
                raw_id=raw_id,
                element=element,
            )
            return
        report["items_with_shape"] += 1
        tx, ty, angle, mirrored = position
        sx, sy = _read_scale(element)
        scene["symbols"].append(
            {
                "id": self._identity(raw_id, kind="symbol"),
                "topology_id": self._topology_id_of.get(raw_id),
                "class_name": class_name,
                "shape": shape_key,
                "tx": tx, "ty": ty, "angle": angle, "mirror": mirrored,
                "sx": sx, "sy": sy,
                "shelved": False,
            }
        )

    def _resolve_shape_key(
        self,
        scene: dict[str, object],
        *,
        catalogue: dict[str, object],
        component_name: str,
        class_name: str,
        raw_id: str,
    ) -> str:
        """Resolve the shape to paint: file catalogue, then bundled, then generic.

        Never returns without a usable key (bead 2ki.15) -- a catalogue miss
        used to silently drop the item. A generic-placeholder resolution is
        recorded as a typed diagnostic so it stays distinguishable from a
        real (file or bundled) shape.
        """
        report = scene["report"]
        if component_name in catalogue:
            return component_name
        bundled = BUNDLED_SYMBOLS.get(class_name)
        if bundled is not None:
            shape_key = f"__bundled__:{class_name}"
            catalogue.setdefault(shape_key, bundled)
            report["items_with_bundled_shape"] += 1
            return shape_key
        shape_key = "__generic__"
        catalogue.setdefault(shape_key, GENERIC_PLACEHOLDER)
        report["generic_placeholders"].append(
            {
                "topology_id": self._topology_id_of.get(raw_id),
                "raw_id": raw_id,
                "class_name": class_name,
                "reason": "unknown_component_class",
            }
        )
        return shape_key

    def _defer_shelf(
        self,
        *,
        shape_key: str,
        class_name: str,
        raw_id: str,
        element: ET.Element,
    ) -> None:
        """Queue equipment lacking a source Position for the shelf (bead 2ki.7).

        Placement is deferred until `_finalize_shelf`, once the drawing
        extent is known -- the shelf sits just outside the frame, so its
        slots cannot be laid out until the frame's own bounds are read.
        """
        sx, sy = _read_scale(element)
        self._pending_shelf.append(
            {
                "raw_id": raw_id,
                "topology_id": self._topology_id_of.get(raw_id),
                "class_name": class_name,
                "shape": shape_key,
                "sx": sx,
                "sy": sy,
                "leader_target": self._find_connection_point(element, raw_id),
            }
        )

    def _find_connection_point(self, element: ET.Element, raw_id: str) -> tuple[float, float] | None:
        """Where this unplaced item's own ports actually sit in the drawing.

        A nozzle can carry its own authored Position even when its parent
        equipment has none -- that is a real connection point, not an
        invented one, so it is checked first. Only if no candidate id has
        its own Position do we fall back to the position of whatever it is
        piped to, as a best-effort anchor for the leader line.
        """
        candidates = [raw_id] + [
            nozzle.attrib.get("ID", "") for nozzle in element.findall("Nozzle") if nozzle.attrib.get("ID")
        ]
        for candidate in candidates:
            position = self._position_by_raw_id.get(candidate)
            if position is not None:
                return position
        for candidate in candidates:
            for other in self._connection_index.get(candidate, []):
                position = self._position_by_raw_id.get(other)
                if position is not None:
                    return position
        return None

    def _finalize_shelf(self, scene: dict[str, object]) -> None:
        if not self._pending_shelf:
            return
        origin_x, origin_y = self._shelf_origin(scene)
        margin = 20.0
        spacing = 30.0
        for index, item in enumerate(self._pending_shelf):
            tx = origin_x + index * spacing
            ty = origin_y - margin
            raw_id = str(item["raw_id"])
            topology_id = item["topology_id"]
            scene["symbols"].append(
                {
                    "id": self._identity(raw_id, kind="symbol"),
                    "topology_id": topology_id,
                    "class_name": item["class_name"],
                    "shape": item["shape"],
                    "tx": tx, "ty": ty, "angle": 0.0, "mirror": False,
                    "sx": item["sx"], "sy": item["sy"],
                    "shelved": True,
                }
            )
            leader_target = item["leader_target"]
            if leader_target is not None:
                lx, ly = leader_target
                scene["polylines"].append(
                    {
                        "id": self._fallback_id("shelf-leader"),
                        "topology_id": topology_id,
                        "kind": "leader",
                        "points": [[tx, ty], [lx, ly]],
                        "stroke": "#333333",
                        "width": 0.25,
                        "dash": None,
                        "inferred": True,
                    }
                )
            scene["report"]["shelved_equipment"].append(
                {"topology_id": topology_id, "raw_id": raw_id, "reason": "missing_position"}
            )

    def _shelf_origin(self, scene: dict[str, object]) -> tuple[float, float]:
        """Bottom-left corner the shelf row starts from: the drawing extent when
        known, otherwise the bounding box of whatever else is already drawn."""
        extent = scene.get("extent")
        if isinstance(extent, dict):
            return float(extent["x0"]), float(extent["y0"])
        xs: list[float] = []
        ys: list[float] = []
        for symbol in scene["symbols"]:
            xs.append(symbol["tx"])
            ys.append(symbol["ty"])
        for polyline in scene["polylines"]:
            for x, y in polyline["points"]:
                xs.append(x)
                ys.append(y)
        if xs and ys:
            return min(xs), min(ys)
        return 0.0, 0.0

    def _emit_routed_pipe(self, segment: ET.Element, scene: dict[str, object]) -> None:
        """Route a pipe run whose source carries no CenterLine (bead 2ki.6).

        The segment's own `Connection` children name its boundary items by
        the same `FromID`/`ToID` the source author used to wire the run --
        these are the "true source-stated endpoints", resolved to wherever
        those items' own `Position` is authored elsewhere in the document.
        Equipment demotion stays all-or-nothing (the geometry gate); this is
        purely a per-pipe fallback so one missing centerline in an otherwise
        geometry-bearing drawing does not erase the run entirely.
        """
        connections = segment.findall("Connection")
        if not connections:
            return
        from_id = connections[0].attrib.get("FromID")
        to_id = connections[-1].attrib.get("ToID")
        start = self._position_by_raw_id.get(from_id or "")
        end = self._position_by_raw_id.get(to_id or "")
        if start is None or end is None:
            return
        raw_id = segment.attrib.get("ID", "")
        topology_id = self._topology_id_of.get(raw_id)
        scene["polylines"].append(
            {
                "id": self._identity(raw_id, kind="polyline"),
                "topology_id": topology_id,
                "kind": "pipe",
                "points": [[start[0], start[1]], [end[0], end[1]]],
                "stroke": "#333333",
                "width": 0.25,
                "dash": None,
                "inferred": True,
            }
        )
        scene["report"]["routed_pipe_runs"].append(
            {"topology_id": topology_id, "raw_id": raw_id, "reason": "missing_centerline"}
        )

    def _emit_centerline(self, parent: ET.Element, centerline: ET.Element, scene: dict[str, object]) -> None:
        kind = "signal" if parent.tag in _SIGNAL_PARENT_TAGS else "pipe"
        raw_id = parent.attrib.get("ID", "")
        scene["polylines"].append(
            {
                "id": self._identity(raw_id, kind="polyline"),
                "topology_id": self._topology_id_of.get(raw_id),
                "kind": kind,
                "points": _read_points(centerline),
                "inferred": False,
                **_presentation_style(centerline),
            }
        )

    def _emit_label(self, label: ET.Element, scene: dict[str, object]) -> None:
        component_name = label.attrib.get("ComponentName")
        raw_id = label.attrib.get("ID", "")
        position = _read_position(label)
        if component_name and position is not None and component_name in scene["catalogue"]:
            tx, ty, angle, mirrored = position
            sx, sy = _read_scale(label)
            scene["symbols"].append(
                {
                    "id": self._identity(raw_id, kind="symbol"),
                    "topology_id": self._topology_id_of.get(raw_id),
                    "class_name": "Label",
                    "shape": component_name,
                    "tx": tx, "ty": ty, "angle": angle, "mirror": mirrored,
                    "sx": sx, "sy": sy,
                    "shelved": False,
                }
            )
        for child in label:
            if child.tag == "Text":
                if _read_position(child) is not None:
                    scene["texts"].append(_read_text(child))
            elif child.tag == "PolyLine":
                scene["polylines"].append(
                    {
                        "id": self._fallback_id("label-leader"),
                        "topology_id": None,
                        "kind": "leader",
                        "points": _read_points(child),
                        "inferred": False,
                        **_presentation_style(child),
                    }
                )
            elif child.tag == "Shape":
                scene["polygons"].append(
                    {
                        "points": _read_points(child),
                        "filled": child.attrib.get("Filled") == "Solid",
                        **_presentation_style(child),
                    }
                )

    def _identity(self, raw_id: str, *, kind: str) -> str:
        topology_id = self._topology_id_of.get(raw_id)
        if topology_id is not None:
            return topology_id
        if raw_id:
            return f"{self._namespace}:{raw_id}"
        return self._fallback_id(kind)

    def _fallback_id(self, kind: str) -> str:
        self._fallback_seq += 1
        return f"{self._namespace}:{kind}-{self._fallback_seq}"


def _index_positions(root: ET.Element) -> dict[str, tuple[float, float]]:
    """Map every authored `ID` in the document to its own `Position` location.

    Used to resolve routed-pipe endpoints (bead 2ki.6): a segment's
    `Connection/@FromID`/`@ToID` name items that may be authored anywhere in
    the document, not just inside that segment's own element.
    """
    positions: dict[str, tuple[float, float]] = {}
    for el in root.iter():
        raw_id = el.attrib.get("ID")
        if not raw_id or raw_id in positions:
            continue
        position = _read_position(el)
        if position is not None:
            positions[raw_id] = (position[0], position[1])
    return positions


def _index_connections(root: ET.Element) -> dict[str, list[str]]:
    """Map every id named by a segment `Connection` to the ids it connects to.

    Undirected: a shelved item's own id (or a nozzle id) may appear as either
    `FromID` or `ToID` depending on how the source authored the run.
    """
    index: dict[str, list[str]] = {}
    for segment in root.iter("PipingNetworkSegment"):
        for connection in segment.findall("Connection"):
            from_id = connection.attrib.get("FromID")
            to_id = connection.attrib.get("ToID")
            if not from_id or not to_id:
                continue
            index.setdefault(from_id, []).append(to_id)
            index.setdefault(to_id, []).append(from_id)
    return index


def _build_catalogue(root: ET.Element) -> dict[str, list[dict[str, object]]]:
    catalogue: dict[str, list[dict[str, object]]] = {}
    shape_catalogue = root.find("ShapeCatalogue")
    if shape_catalogue is None:
        return catalogue
    for shape in shape_catalogue:
        name = shape.attrib.get("ComponentName") or shape.attrib.get("ComponentClass")
        if name:
            catalogue[name] = _shape_primitives(shape)
    return catalogue


def _shape_primitives(shape_el: ET.Element) -> list[dict[str, object]]:
    prims: list[dict[str, object]] = []
    for el in shape_el:
        tag = el.tag
        if tag == "PolyLine":
            prims.append({"kind": "polyline", "points": _read_points(el), **_presentation_style(el)})
        elif tag == "Circle":
            position = _read_position(el) or (0.0, 0.0, 0.0, False)
            prims.append(
                {
                    "kind": "circle", "cx": position[0], "cy": position[1],
                    "r": _fnum(el.attrib.get("Radius")),
                    "filled": el.attrib.get("Filled") == "Solid",
                    **_presentation_style(el),
                }
            )
        elif tag == "TrimmedCurve":
            circle = el.find("Circle")
            if circle is None:
                continue
            position = _read_position(circle) or (0.0, 0.0, 0.0, False)
            prims.append(
                {
                    "kind": "arc", "cx": position[0], "cy": position[1],
                    "r": _fnum(circle.attrib.get("Radius")),
                    "start": _fnum(el.attrib.get("StartAngle")),
                    "end": _fnum(el.attrib.get("EndAngle")),
                    **_presentation_style(circle),
                }
            )
        elif tag == "Text":
            prims.append({"kind": "text", **_read_text(el)})
        elif tag == "Shape":
            prims.append(
                {
                    "kind": "polygon", "points": _read_points(el),
                    "filled": el.attrib.get("Filled") == "Solid",
                    **_presentation_style(el),
                }
            )
    return prims


def _fnum(value: object, default: float = 0.0) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _read_points(el: ET.Element) -> list[list[float]]:
    return [[_fnum(c.attrib.get("X")), _fnum(c.attrib.get("Y"))] for c in el.findall("Coordinate")]


def _read_position(el: ET.Element) -> tuple[float, float, float, bool] | None:
    """Position -> (tx, ty, angle_deg, mirrored). Reference = local +X direction."""
    position = el.find("Position")
    if position is None:
        return None
    location = position.find("Location")
    reference = position.find("Reference")
    axis = position.find("Axis")
    tx, ty = _fnum(location.attrib.get("X")), _fnum(location.attrib.get("Y"))
    if reference is not None:
        rx, ry = _fnum(reference.attrib.get("X"), 1.0), _fnum(reference.attrib.get("Y"))
    else:
        rx, ry = 1.0, 0.0
    angle = math.degrees(math.atan2(ry, rx))
    mirrored = axis is not None and _fnum(axis.attrib.get("Z"), 1.0) < 0
    return tx, ty, angle, mirrored


def _read_text(el: ET.Element) -> dict[str, object]:
    """Text -> prim fields. Angle = Position/Reference angle + explicit TextAngle.

    TextAngle is explicit and additive to the position angle -- vertical
    pipe-run labels rely on it; never infer rotation from geometry.
    """
    position = _read_position(el) or (0.0, 0.0, 0.0, False)
    return {
        "x": position[0], "y": position[1],
        "angle": position[2] + _fnum(el.attrib.get("TextAngle")),
        "string": el.attrib.get("String", ""),
        "height": _fnum(el.attrib.get("Height"), 3.0),
        "font": el.attrib.get("Font", "Calibri"),
        "just": el.attrib.get("Justification", "LeftBottom"),
    }


def _read_scale(el: ET.Element) -> tuple[float, float]:
    scale = el.find("Scale")
    if scale is None:
        return 1.0, 1.0
    return _fnum(scale.attrib.get("X"), 1.0), _fnum(scale.attrib.get("Y"), 1.0)


def _presentation_style(el: ET.Element) -> dict[str, object]:
    presentation = el.find("Presentation")
    if presentation is None:
        return {"stroke": "#333333", "width": 0.25, "dash": None}
    r, g, b = (_fnum(presentation.attrib.get(k)) for k in ("R", "G", "B"))
    color = "#%02x%02x%02x" % (round(r * 255), round(g * 255), round(b * 255))
    line_type = presentation.attrib.get("LineType", "0")
    return {
        "stroke": color,
        "width": _fnum(presentation.attrib.get("LineWeight"), 0.25) or 0.25,
        "dash": _LINE_TYPE_DASH.get(line_type),
    }
