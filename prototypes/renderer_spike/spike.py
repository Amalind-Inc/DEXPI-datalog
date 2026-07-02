"""THROWAWAY renderer spike for bead pydexpi-datalog-1-2ki.2.

Question: can C01/C02/C03 render recognizably from source geometry alone
(catalogue shapes + Position/Reference/Scale transforms + CenterLines)?

Not production code. No tests, no error budget beyond runnability.
Run:  python prototypes/renderer_spike/spike.py
Out:  prototypes/renderer_spike/out/<fixture>.svg + scene.json + gate stats.
"""

from __future__ import annotations

import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FIXTURES = {
    "C01": REPO / "TrainingTestCases/dexpi 1.3/example pids/C01 DEXPI Reference P&ID/C01V04-VER.EX01.xml",
    "C02": REPO / "TrainingTestCases/dexpi 1.3/example pids/C02 Process Column (BASF)/C02V03-VER.EX02.xml",
    "C03": REPO / "TrainingTestCases/dexpi 1.3/example pids/C03 Piping (Equinor)/C03V04-VER.EX02.xml",
}
OUT = Path(__file__).resolve().parent / "out"

NON_ITEM_TAGS = {
    "GenericAttributes", "GenericAttribute", "Presentation", "Position",
    "Location", "Axis", "Reference", "ConnectionPoints", "Node",
    "PersistentID", "Extent", "Min", "Max", "Scale", "Connection",
    "Association", "ObjectAttributesReference", "TextStringFormatSpecification",
    "PlantInformation", "UnitsOfMeasure", "MetaData",
}


# ---------- geometry helpers ----------

def fnum(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def read_position(el):
    """Position -> (tx, ty, angle_deg, mirrored). Reference = local +X direction."""
    pos = el.find("Position")
    if pos is None:
        return None
    loc = pos.find("Location")
    ref = pos.find("Reference")
    axis = pos.find("Axis")
    tx, ty = fnum(loc.attrib.get("X")), fnum(loc.attrib.get("Y"))
    rx, ry = (fnum(ref.attrib.get("X"), 1.0), fnum(ref.attrib.get("Y"))) if ref is not None else (1.0, 0.0)
    angle = math.degrees(math.atan2(ry, rx))
    mirrored = axis is not None and fnum(axis.attrib.get("Z"), 1.0) < 0
    return tx, ty, angle, mirrored


def read_text(el):
    """Text -> prim fields. Angle = Position/Reference angle + explicit TextAngle."""
    pos = read_position(el) or (0, 0, 0, False)
    return {"x": pos[0], "y": pos[1],
            "angle": pos[2] + fnum(el.attrib.get("TextAngle")),
            "string": el.attrib.get("String", ""),
            "height": fnum(el.attrib.get("Height"), 3.0),
            "font": el.attrib.get("Font", "Calibri"),
            "just": el.attrib.get("Justification", "LeftBottom")}


def read_scale(el):
    sc = el.find("Scale")
    if sc is None:
        return 1.0, 1.0
    return fnum(sc.attrib.get("X"), 1.0), fnum(sc.attrib.get("Y"), 1.0)


def presentation_style(el):
    p = el.find("Presentation")
    if p is None:
        return {"stroke": "#333", "width": 0.25, "dash": None}
    r, g, b = (fnum(p.attrib.get(k)) for k in ("R", "G", "B"))
    color = "#%02x%02x%02x" % (round(r * 255), round(g * 255), round(b * 255))
    line_type = p.attrib.get("LineType", "0")
    dash = {"1": "4 2", "2": "1 2", "3": "6 2 1 2", "4": "6 2 1 2 1 2"}.get(line_type)
    return {"stroke": color, "width": fnum(p.attrib.get("LineWeight"), 0.25) or 0.25, "dash": dash}


# ---------- catalogue shape -> local primitives ----------

def shape_primitives(shape_el):
    """Flatten one catalogue shape into local-coordinate primitives."""
    prims = []
    for el in shape_el:
        tag = el.tag
        if tag == "PolyLine":
            pts = [(fnum(c.attrib.get("X")), fnum(c.attrib.get("Y"))) for c in el.findall("Coordinate")]
            prims.append({"kind": "polyline", "points": pts, **presentation_style(el)})
        elif tag == "Circle":
            pos = read_position(el) or (0, 0, 0, False)
            prims.append({"kind": "circle", "cx": pos[0], "cy": pos[1],
                          "r": fnum(el.attrib.get("Radius")),
                          "filled": el.attrib.get("Filled") == "Solid", **presentation_style(el)})
        elif tag == "TrimmedCurve":
            circ = el.find("Circle")
            if circ is None:
                continue
            pos = read_position(circ) or (0, 0, 0, False)
            prims.append({
                "kind": "arc", "cx": pos[0], "cy": pos[1], "r": fnum(circ.attrib.get("Radius")),
                "start": fnum(el.attrib.get("StartAngle")), "end": fnum(el.attrib.get("EndAngle")),
                **presentation_style(circ),
            })
        elif tag == "Text":
            prims.append({"kind": "text", **read_text(el)})
        elif tag == "Shape":
            # Polygon: direct Coordinate children, optional Filled="Solid".
            pts = [(fnum(c.attrib.get("X")), fnum(c.attrib.get("Y"))) for c in el.findall("Coordinate")]
            prims.append({"kind": "polygon", "points": pts,
                          "filled": el.attrib.get("Filled") == "Solid", **presentation_style(el)})
    return prims


def build_catalogue(root):
    cat = {}
    sc = root.find("ShapeCatalogue")
    if sc is None:
        return cat
    for shape in sc:
        name = shape.attrib.get("ComponentName") or shape.attrib.get("ComponentClass")
        if name:
            cat[name] = shape_primitives(shape)
    return cat


# ---------- scene assembly ----------

def build_scene(root, name):
    catalogue = build_catalogue(root)
    scene = {"name": name, "units": root.find("PlantInformation").attrib.get("Units", "mm"),
             "symbols": [], "polylines": [], "polygons": [], "texts": [], "report": {}}
    stats = {"items_with_shape": 0, "items_missing_shape": 0, "items_missing_position": 0,
             "segments": 0, "segments_with_centerline": 0}

    drawing = root.find("Drawing")
    catalogue_el = root.find("ShapeCatalogue")

    def walk(el, in_drawing=False):
        for child in el:
            if child is catalogue_el:
                continue
            tag = child.tag
            if tag in NON_ITEM_TAGS or tag == "Label":
                if tag == "Label":
                    walk_label(child)
                continue
            comp = child.attrib.get("ComponentName")
            cid = child.attrib.get("ID", "")
            if tag == "CenterLine":
                pts = [(fnum(c.attrib.get("X")), fnum(c.attrib.get("Y"))) for c in child.findall("Coordinate")]
                kind = "signal" if el.tag in ("ProcessInstrumentationFunction", "InformationFlow", "SignalConveyingFunction", "ActuatingFunction", "SignalLine") else "pipe"
                scene["polylines"].append({"id": el.attrib.get("ID", ""), "kind": kind,
                                           "points": pts, **presentation_style(child)})
                continue
            if tag == "Text":
                if read_position(child):
                    scene["texts"].append(read_text(child))
                continue
            if tag == "PolyLine" and in_drawing:
                pts = [(fnum(c.attrib.get("X")), fnum(c.attrib.get("Y"))) for c in child.findall("Coordinate")]
                scene["polylines"].append({"id": "drawing", "kind": "frame", "points": pts,
                                           **presentation_style(child)})
                continue
            if tag == "Shape":
                # World-coordinate polygon (PNS label arrows, title-block fills).
                pts = [(fnum(c.attrib.get("X")), fnum(c.attrib.get("Y"))) for c in child.findall("Coordinate")]
                scene["polygons"].append({"points": pts,
                                          "filled": child.attrib.get("Filled") == "Solid",
                                          **presentation_style(child)})
                continue
            # plant item?
            if comp:
                pos = read_position(child)
                if comp not in catalogue:
                    stats["items_missing_shape"] += 1
                elif pos is None:
                    stats["items_missing_position"] += 1
                else:
                    sx, sy = read_scale(child)
                    stats["items_with_shape"] += 1
                    scene["symbols"].append({"id": cid, "class": child.attrib.get("ComponentClass", ""),
                                             "shape": comp, "tx": pos[0], "ty": pos[1], "angle": pos[2],
                                             "mirror": pos[3], "sx": sx, "sy": sy})
            if tag == "PipingNetworkSegment":
                stats["segments"] += 1
                if child.find("CenterLine") is not None:
                    stats["segments_with_centerline"] += 1
            walk(child, in_drawing or tag == "Drawing")

    def walk_label(label):
        # A Label may itself reference a catalogue symbol (e.g. the ESD funnel:
        # ComponentName="ACTUATING_SYSTEM_LABEL_SHAPE") positioned like any item.
        comp = label.attrib.get("ComponentName")
        pos = read_position(label)
        if comp and pos and comp in catalogue:
            sx, sy = read_scale(label)
            scene["symbols"].append({"id": label.attrib.get("ID", ""), "class": "Label",
                                     "shape": comp, "tx": pos[0], "ty": pos[1], "angle": pos[2],
                                     "mirror": pos[3], "sx": sx, "sy": sy})
        for child in label:
            if child.tag == "Text":
                if read_position(child):
                    scene["texts"].append(read_text(child))
            elif child.tag == "PolyLine":
                pts = [(fnum(c.attrib.get("X")), fnum(c.attrib.get("Y"))) for c in child.findall("Coordinate")]
                scene["polylines"].append({"id": "label", "kind": "leader", "points": pts,
                                           **presentation_style(child)})
            elif child.tag == "Shape":
                pts = [(fnum(c.attrib.get("X")), fnum(c.attrib.get("Y"))) for c in child.findall("Coordinate")]
                scene["polygons"].append({"points": pts,
                                          "filled": child.attrib.get("Filled") == "Solid",
                                          **presentation_style(child)})

    walk(root)
    # Drawing frame: some exports draw the border (C01); all carry Extent.
    if drawing is not None:
        ext = drawing.find("Extent")
        if ext is not None and ext.find("Min") is not None:
            mn, mx = ext.find("Min").attrib, ext.find("Max").attrib
            x0, y0 = fnum(mn.get("X")), fnum(mn.get("Y"))
            x1, y1 = fnum(mx.get("X")), fnum(mx.get("Y"))
            scene["polylines"].append({"id": "sheet", "kind": "frame",
                                       "points": [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)],
                                       "stroke": "#999", "width": 0.0005 if scene["units"] == "m" else 0.5,
                                       "dash": None})
    scene["report"] = stats
    return scene, catalogue


# ---------- SVG emission ----------

def _text_anchor(just):
    h = just.replace("Bottom", "").replace("Top", "").replace("Center", "Center").lower()
    if just.lower().startswith("left"):
        return "start"
    if just.lower().startswith("right"):
        return "end"
    return "middle"


def _prim_svg(p):
    if p["kind"] == "polyline":
        pts = " ".join(f"{x:.4f},{y:.4f}" for x, y in p["points"])
        dash = f' stroke-dasharray="{p["dash"]}"' if p.get("dash") else ""
        return f'<polyline points="{pts}" fill="none" stroke="{p["stroke"]}" stroke-width="{p["width"]}"{dash}/>'
    if p["kind"] == "circle":
        fill = p["stroke"] if p.get("filled") else "none"
        return (f'<circle cx="{p["cx"]:.4f}" cy="{p["cy"]:.4f}" r="{p["r"]:.4f}" fill="{fill}" '
                f'stroke="{p["stroke"]}" stroke-width="{p["width"]}"/>')
    if p["kind"] == "arc":
        a0, a1 = math.radians(p["start"]), math.radians(p["end"])
        x0, y0 = p["cx"] + p["r"] * math.cos(a0), p["cy"] + p["r"] * math.sin(a0)
        x1, y1 = p["cx"] + p["r"] * math.cos(a1), p["cy"] + p["r"] * math.sin(a1)
        sweep = (p["end"] - p["start"]) % 360
        large = 1 if sweep > 180 else 0
        return (f'<path d="M {x0:.4f} {y0:.4f} A {p["r"]:.4f} {p["r"]:.4f} 0 {large} 1 {x1:.4f} {y1:.4f}" '
                f'fill="none" stroke="{p["stroke"]}" stroke-width="{p["width"]}"/>')
    if p["kind"] == "polygon":
        pts = " ".join(f"{x:.4f},{y:.4f}" for x, y in p["points"])
        fill = p["stroke"] if p.get("filled") else "none"
        return (f'<polygon points="{pts}" fill="{fill}" '
                f'stroke="{p["stroke"]}" stroke-width="{p["width"]}"/>')
    if p["kind"] == "text":
        anchor = _text_anchor(p["just"])
        # Un-flip text inside the Y-flipped world group, then rotate about the
        # anchor point (SVG rotates clockwise; source angle is CCW in Y-up space).
        rot = f' rotate({-p.get("angle", 0):.1f} {p["x"]:.4f} {-p["y"]:.4f})' if p.get("angle") else ""
        return (f'<text x="{p["x"]:.4f}" y="{-p["y"]:.4f}" transform="scale(1,-1){rot}" '
                f'font-size="{p["height"]:.4f}" font-family="{p.get("font", "Calibri")}, sans-serif" '
                f'text-anchor="{anchor}">{_esc(p["string"])}</text>')
    return ""


def _esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def scene_to_svg(scene, catalogue):
    xs, ys = [], []
    for pl in scene["polylines"]:
        for x, y in pl["points"]:
            xs.append(x); ys.append(y)
    for pg in scene["polygons"]:
        for x, y in pg["points"]:
            xs.append(x); ys.append(y)
    for s in scene["symbols"]:
        xs.append(s["tx"]); ys.append(s["ty"])
    for t in scene["texts"]:
        xs.append(t["x"]); ys.append(t["y"])
    if not xs:
        return "<svg xmlns='http://www.w3.org/2000/svg'/>", (0, 0, 1, 1)
    pad = 0.03 * max(max(xs) - min(xs), max(ys) - min(ys))
    x0, y0, x1, y1 = min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad
    w, h = x1 - x0, y1 - y0

    defs, seen = [], set()
    for s in scene["symbols"]:
        if s["shape"] in seen:
            continue
        seen.add(s["shape"])
        body = "".join(_prim_svg(p) for p in catalogue[s["shape"]])
        defs.append(f'<g id="sym-{s["shape"]}">{body}</g>')

    body = []
    for pl in scene["polylines"]:
        cls = pl["kind"]
        pts = " ".join(f"{x:.4f},{y:.4f}" for x, y in pl["points"])
        dash = f' stroke-dasharray="{pl["dash"]}"' if pl.get("dash") else ""
        body.append(f'<polyline class="{cls}" points="{pts}" fill="none" '
                    f'stroke="{pl["stroke"]}" stroke-width="{pl["width"]}"{dash}/>')
    for pg in scene["polygons"]:
        body.append(_prim_svg({"kind": "polygon", **pg}))
    for s in scene["symbols"]:
        t = f'translate({s["tx"]:.4f} {s["ty"]:.4f}) rotate({s["angle"]:.1f})'
        if s["mirror"]:
            t += " scale(1,-1)"
        if (s["sx"], s["sy"]) != (1.0, 1.0):
            t += f' scale({s["sx"]} {s["sy"]})'
        body.append(f'<use href="#sym-{s["shape"]}" transform="{t}" data-id="{_esc(s["id"])}"/>')
    for t in scene["texts"]:
        body.append(_prim_svg({"kind": "text", **t}))

    px_scale = 1600.0 / w  # render ~1600px wide regardless of source units (mm vs m)
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w:.4f} {h:.4f}" '
        f'width="{w * px_scale:.0f}" height="{h * px_scale:.0f}" font-family="sans-serif">'
        f'<rect width="100%" height="100%" fill="white"/>'
        f'<defs>{"".join(defs)}</defs>'
        # Flip Y: Proteus is Y-up, SVG is Y-down.
        f'<g transform="translate({-x0:.4f} {y1:.4f}) scale(1,-1)">{"".join(body)}</g>'
        f"</svg>"
    )
    return svg, (x0, y0, x1, y1)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name, path in FIXTURES.items():
        root = ET.parse(path).getroot()
        scene, catalogue = build_scene(root, name)
        svg, extent = scene_to_svg(scene, catalogue)
        (OUT / f"{name}.svg").write_text(svg, encoding="utf-8")
        (OUT / f"{name}.scene.json").write_text(
            json.dumps({k: v for k, v in scene.items()}, indent=1, default=list)[:400000], encoding="utf-8")
        r = scene["report"]
        cov = r["segments_with_centerline"] / r["segments"] if r["segments"] else 0
        print(f"{name}: units={scene['units']} extent={extent[2]-extent[0]:.0f}x{extent[3]-extent[1]:.0f} "
              f"symbols={len(scene['symbols'])} polylines={len(scene['polylines'])} texts={len(scene['texts'])} | "
              f"shape-hit={r['items_with_shape']} miss-shape={r['items_missing_shape']} "
              f"miss-pos={r['items_missing_position']} | pipe-cov={cov:.0%}")


if __name__ == "__main__":
    main()
