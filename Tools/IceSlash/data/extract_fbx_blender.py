"""Headless Blender extractor for the ice-slash FBX sources.

Reads each FBX twice:
  1. raw, through Blender's own FBX parser (io_scene_fbx.parse_fbx), to get
     the file's GlobalSettings axis/unit block and every Model's Lcl
     Translation / Rotation / Scaling exactly as written in the file;
  2. through the normal Blender importer (automatic axis handling), to get
     each object's Blender world location / rotation / scale, local bounds,
     polygon / triangle counts and (for slash ribbons) the centre-line and
     edge vertices keyed by UV.

Nothing is written next to the FBX; the result goes to the JSON path given
on the command line.

Run:
  /Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup \
      -P Tools/IceSlash/data/extract_fbx_blender.py -- <out.json> <a.fbx> [<b.fbx> ...]
"""

import json
import math
import os
import sys

import bpy

from io_scene_fbx import parse_fbx


def script_args():
    argv = sys.argv
    if "--" not in argv:
        raise SystemExit("usage: blender -b -P extract_fbx_blender.py -- out.json in.fbx [...]")
    return argv[argv.index("--") + 1:]


def decode(value):
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return value


def find_first(elem, ident):
    for child in elem.elems:
        if child.id == ident:
            return child
    return None


def props70(elem):
    """Return {name: [values]} for a Properties70 block."""
    out = {}
    block = find_first(elem, b"Properties70")
    if block is None:
        return out
    for prop in block.elems:
        if prop.id != b"P" or not prop.props:
            continue
        name = decode(prop.props[0])
        values = [decode(v) for v in prop.props[4:]]
        out[name] = values
    return out


def split_name(raw):
    text = raw if isinstance(raw, bytes) else bytes(raw)
    if b"\x00\x01" in text:
        name, cls = text.split(b"\x00\x01", 1)
        return name.decode("utf-8", "replace"), cls.decode("utf-8", "replace")
    return text.decode("utf-8", "replace"), ""


def raw_fbx(path):
    root, version = parse_fbx.parse(path)
    result = {"fbx_version": version, "global_settings": {}, "models": {}, "geometries": {}}

    settings = find_first(root, b"GlobalSettings")
    if settings is not None:
        props = props70(settings)
        for key in ("UpAxis", "UpAxisSign", "FrontAxis", "FrontAxisSign", "CoordAxis",
                    "CoordAxisSign", "OriginalUpAxis", "OriginalUpAxisSign",
                    "UnitScaleFactor", "OriginalUnitScaleFactor"):
            if key in props:
                result["global_settings"][key] = props[key][0] if props[key] else None

    objects = find_first(root, b"Objects")
    geom_by_id = {}
    model_by_id = {}
    if objects is not None:
        for elem in objects.elems:
            if elem.id == b"Model":
                uid = elem.props[0]
                name, _ = split_name(elem.props[1])
                kind = decode(elem.props[2])
                props = props70(elem)
                model_by_id[uid] = name
                result["models"][name] = {
                    "type": kind,
                    "lcl_translation": props.get("Lcl Translation", [0.0, 0.0, 0.0]),
                    "lcl_rotation": props.get("Lcl Rotation", [0.0, 0.0, 0.0]),
                    "lcl_scaling": props.get("Lcl Scaling", [1.0, 1.0, 1.0]),
                    "pre_rotation": props.get("PreRotation"),
                    "rotation_order": props.get("RotationOrder"),
                    "geometric_translation": props.get("GeometricTranslation"),
                }
            elif elem.id == b"Geometry":
                uid = elem.props[0]
                name, _ = split_name(elem.props[1])
                verts = find_first(elem, b"Vertices")
                index = find_first(elem, b"PolygonVertexIndex")
                coords = list(verts.props[0]) if verts is not None else []
                indices = list(index.props[0]) if index is not None else []
                polys = 0
                tris = 0
                corner = 0
                for value in indices:
                    corner += 1
                    if value < 0:
                        polys += 1
                        tris += max(0, corner - 2)
                        corner = 0
                xs = coords[0::3]
                ys = coords[1::3]
                zs = coords[2::3]
                geom_by_id[uid] = name
                result["geometries"][name] = {
                    "vertices": len(xs),
                    "polygons": polys,
                    "triangles": tris,
                    "local_min": [min(xs), min(ys), min(zs)] if xs else None,
                    "local_max": [max(xs), max(ys), max(zs)] if xs else None,
                }

    links = []
    connections = find_first(root, b"Connections")
    if connections is not None:
        for conn in connections.elems:
            if conn.id != b"C" or len(conn.props) < 3:
                continue
            child, parent = conn.props[1], conn.props[2]
            if child in geom_by_id and parent in model_by_id:
                links.append([model_by_id[parent], geom_by_id[child]])
            elif child in model_by_id:
                links.append([model_by_id[child], "parent:" + (model_by_id.get(parent) or str(parent))])
    result["connections"] = links
    return result


def clear_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def mesh_info(obj):
    mesh = obj.data
    coords = [v.co for v in mesh.vertices]
    low = [min(c[i] for c in coords) for i in range(3)]
    high = [max(c[i] for c in coords) for i in range(3)]
    tris = sum(max(0, len(p.vertices) - 2) for p in mesh.polygons)
    info = {
        "location": list(obj.location),
        "rotation_euler_deg": [math.degrees(a) for a in obj.rotation_euler],
        "rotation_mode": obj.rotation_mode,
        "scale": list(obj.scale),
        "parent": obj.parent.name if obj.parent else None,
        "matrix_world": [list(row) for row in obj.matrix_world],
        "local_min": low,
        "local_max": high,
        "vertices": len(mesh.vertices),
        "polygons": len(mesh.polygons),
        "triangles": tris,
        "uv_layers": [layer.name for layer in mesh.uv_layers],
    }

    # Per-vertex UV (first UV layer, first loop that touches the vertex).
    if mesh.uv_layers:
        layer = mesh.uv_layers[0]
        vert_uv = {}
        for loop in mesh.loops:
            if loop.vertex_index not in vert_uv:
                uv = layer.data[loop.index].uv
                vert_uv[loop.vertex_index] = (float(uv[0]), float(uv[1]))
        rows = []
        for index, vert in enumerate(mesh.vertices):
            if index in vert_uv:
                world = obj.matrix_world @ vert.co
                rows.append([vert_uv[index][0], vert_uv[index][1],
                             float(vert.co.x), float(vert.co.y), float(vert.co.z),
                             float(world.x), float(world.y), float(world.z)])
        info["uv_vertices"] = rows
    return info


def imported_fbx(path, keep_uv_vertices):
    clear_scene()
    bpy.ops.import_scene.fbx(filepath=path)
    scene = bpy.context.scene
    out = {
        "scene_unit_scale": scene.unit_settings.scale_length,
        "objects": {},
    }
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            out["objects"][obj.name] = {"type": obj.type, "location": list(obj.location)}
            continue
        info = mesh_info(obj)
        if not keep_uv_vertices:
            info.pop("uv_vertices", None)
        out["objects"][obj.name] = info
    return out


def main():
    args = script_args()
    out_path = os.path.abspath(args[0])
    result = {"blender_version": bpy.app.version_string, "files": {}}
    for fbx in args[1:]:
        path = os.path.abspath(fbx)
        keep_uv = "SlashArc" in os.path.basename(path)
        print("EXTRACT", path)
        result["files"][os.path.basename(path)] = {
            "path": path,
            "raw": raw_fbx(path),
            "imported": imported_fbx(path, keep_uv),
        }
    with open(out_path, "w") as handle:
        json.dump(result, handle, indent=1)
    print("WROTE", out_path)


main()
