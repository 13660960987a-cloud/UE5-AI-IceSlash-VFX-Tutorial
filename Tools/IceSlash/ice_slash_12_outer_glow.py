"""IceSlash step 12: Outer-rim emissive strip material (M_SlashOuterGlow) + Niagara Blade_OuterGlow layer.

Builds:
  1. /Game/VFX/IceSlash/Materials/M_SlashOuterGlow
     - Unlit, BLEND_Additive, TwoSided=True
     - UV0 samples T_SlashOuterGlow (2048x256 incandescent golden-amber outer-rim strip, 16px Alpha=0 border)
     - UV1.x drives the exact same sqrt(ParticleRelativeTime) sweep reveal window as M_SlashArc_v2
     - EmissiveColor = GlowStripTex.RGB * GlowTint.RGB * (GlowStripTex.A * Reveal * ParticleColor.A * EmissiveBoost)
  2. MI_SlashOuterGlow_01..05 (static mesh preview instances, assigned to SM_SlashOuterGlow_01..05 slot 0)
     MI_SlashOuterGlowNS_01..05 (Niagara instances with UseParticleTime=1.0, SlashWidth=1.35, TailSoftness=0.35)
  3. Updates NS_IceSlash_Slash (/Game/VFX/IceSlash/Niagara/NS_IceSlash_Slash):
     - Updates Mist, Smoke, Blade to the flat Z=0 canonical transform (canon_rot=(0,90,0), exact R=270cm)
     - Adds & configures Blade_OuterGlow (SM_SlashOuterGlow_01 + MI_SlashOuterGlowNS_01, SortOrderHint=13)
"""
import importlib
import json
import sys

import unreal
import vibeue

TOOLS_DIR = "/Users/mengmeile/Downloads/lianxi/m/Tools/IceSlash"
if TOOLS_DIR not in sys.path:
    sys.path.insert(0, TOOLS_DIR)
import ice_slash_common as C  # noqa: E402
importlib.reload(C)
import ice_slash_05_niagara as N5  # noqa: E402
importlib.reload(N5)

SCRIPT_NAME = "ice_slash_12_outer_glow"
REBUILD_MAT = True

MAT_NAME = "M_SlashOuterGlow"
MAT_PATH = f"{C.MAT_DIR}/{MAT_NAME}"
TEX_PATH = f"{C.TEX_DIR}/T_SlashOuterGlow"

MS = unreal.MaterialService
MNS = unreal.MaterialNodeService
MEL = unreal.MaterialEditingLibrary
EAL = unreal.EditorAssetLibrary
NTS = "NiagaraToolsets.NiagaraToolset_System"
TMP_EM_MESH = "/Niagara/DefaultAssets/Templates/Emitters/UpwardMeshBurst.UpwardMeshBurst"

MATERIAL_PROPERTIES = [
    ("MaterialDomain", "MD_Surface"),
    ("BlendMode", "BLEND_Additive"),
    ("ShadingModel", "MSM_Unlit"),
    ("TwoSided", "true"),
]

SCALAR_PARAMS = [
    ("SlashProgress", 0.50, 0.0, 1.2, "SlashControl"),
    ("SlashWidth", 1.35, 0.05, 2.0, "SlashControl"),
    ("SlashSoftness", 0.05, 0.001, 0.35, "SlashControl"),
    ("TailSoftness", 0.35, 0.001, 1.0, "SlashControl"),
    ("UseParticleTime", 0.0, 0.0, 1.0, "Niagara"),
    ("EmissiveBoost", 0.92, 0.0, 30.0, "Glow"),
]

VECTOR_PARAMS = [
    ("GlowTint", (1.0, 0.95, 0.84, 1.0), "Glow"),
]

NODES = [
    ("TexCoord0", "TextureCoordinate", -2200, -220),
    ("T_GlowStripTex", "TextureSampleParameter2D", -1850, -220),
    ("P_GlowTint", "VectorParameter", -1850, 60),
    ("P_EmissiveBoost", "ScalarParameter", -1400, 220),
    # Sweep reveal along UV1.x (identical timing math to M_SlashArc_v2)
    ("TexCoord1", "TextureCoordinate", -2600, -900),
    ("Sweep", "ComponentMask", -2380, -900),
    ("PRT", "ParticleRelativeTime", -2800, -720),
    ("PRTpow", "Power", -2580, -720),
    ("P_SlashProgress", "ScalarParameter", -2800, -580),
    ("P_UseParticleTime", "ScalarParameter", -2800, -460),
    ("ProgSel", "LinearInterpolate", -2350, -640),
    ("P_SlashWidth", "ScalarParameter", -2580, -340),
    ("WidthPlusOne", "Add", -2350, -340),
    ("Head", "Multiply", -2120, -560),
    ("Tail", "Subtract", -1920, -460),
    ("HeadDist", "Subtract", -1720, -680),
    ("TailDist", "Subtract", -1720, -500),
    ("P_SlashSoftness", "ScalarParameter", -2120, -780),
    ("SoftClamp", "Max", -1920, -780),
    ("P_TailSoftness", "ScalarParameter", -2120, -320),
    ("TailSoftClamp", "Max", -1920, -320),
    ("HeadMask", "SmoothStep", -1480, -680),
    ("TailMask", "SmoothStep", -1480, -500),
    ("Reveal", "Multiply", -1240, -590),
    # Combine RGB * Tint * (TexAlpha * Reveal * ParticleAlpha * EmissiveBoost)
    ("PCol", "ParticleColor", -1480, 380),
    ("ColTint", "Multiply", -1480, -120),
    ("AlphaRev", "Multiply", -1020, -320),
    ("AlphaPC", "Multiply", -820, -180),
    ("AlphaBoost", "Multiply", -620, -80),
    ("EmissiveOut", "Multiply", -360, -120),
]

CONST_SETS = [
    ("TexCoord0", "CoordinateIndex", "0"),
    ("TexCoord1", "CoordinateIndex", "1"),
    ("Sweep", "R", "True"), ("Sweep", "G", "False"), ("Sweep", "B", "False"), ("Sweep", "A", "False"),
    ("PRTpow", "ConstExponent", "0.5"),
    ("WidthPlusOne", "ConstB", "1.0"),
    ("SoftClamp", "ConstB", "0.001"),
    ("TailSoftClamp", "ConstB", "0.001"),
    ("HeadMask", "ConstMin", "0.0"),
    ("TailMask", "ConstMin", "0.0"),
]

CONNECTIONS = [
    ("TexCoord0", "", "T_GlowStripTex", "UVs"),
    ("TexCoord1", "", "Sweep", ""),
    ("PRT", "", "PRTpow", "Base"),
    ("P_SlashProgress", "", "ProgSel", "A"),
    ("PRTpow", "", "ProgSel", "B"),
    ("P_UseParticleTime", "", "ProgSel", "Alpha"),
    ("P_SlashWidth", "", "WidthPlusOne", "A"),
    ("ProgSel", "", "Head", "A"),
    ("WidthPlusOne", "", "Head", "B"),
    ("Head", "", "Tail", "A"),
    ("P_SlashWidth", "", "Tail", "B"),
    ("Head", "", "HeadDist", "A"),
    ("Sweep", "", "HeadDist", "B"),
    ("Sweep", "", "TailDist", "A"),
    ("Tail", "", "TailDist", "B"),
    ("P_SlashSoftness", "", "SoftClamp", "A"),
    ("SoftClamp", "", "HeadMask", "Max"),
    ("HeadDist", "", "HeadMask", "Value"),
    ("P_TailSoftness", "", "TailSoftClamp", "A"),
    ("TailSoftClamp", "", "TailMask", "Max"),
    ("TailDist", "", "TailMask", "Value"),
    ("HeadMask", "", "Reveal", "A"),
    ("TailMask", "", "Reveal", "B"),
    # Emissive combine
    ("T_GlowStripTex", "RGB", "ColTint", "A"),
    ("P_GlowTint", "RGB", "ColTint", "B"),
    ("T_GlowStripTex", "A", "AlphaRev", "A"),
    ("Reveal", "", "AlphaRev", "B"),
    ("AlphaRev", "", "AlphaPC", "A"),
    ("PCol", "A", "AlphaPC", "B"),
    ("AlphaPC", "", "AlphaBoost", "A"),
    ("P_EmissiveBoost", "", "AlphaBoost", "B"),
    ("ColTint", "", "EmissiveOut", "A"),
    ("AlphaBoost", "", "EmissiveOut", "B"),
]


def _color_text(rgba):
    return "(R=%.4f,G=%.4f,B=%.4f,A=%.4f)" % tuple(rgba)


def build_outer_glow_material(report):
    C.ensure_dir(C.MAT_DIR)
    if not EAL.does_asset_exist(MAT_PATH):
        fac = unreal.MaterialFactoryNew()
        mat = unreal.AssetToolsHelpers.get_asset_tools().create_asset(MAT_NAME, C.MAT_DIR, unreal.Material, fac)
        report.created(MAT_PATH)
    else:
        mat = EAL.load_asset(MAT_PATH)

    for prop, want in MATERIAL_PROPERTIES:
        MS.set_property(MAT_PATH, prop, want)

    if REBUILD_MAT:
        MEL.delete_all_material_expressions(mat)

    infos = MNS.batch_create_expressions(
        MAT_PATH, [n[1] for n in NODES], [n[2] for n in NODES], [n[3] for n in NODES]
    )
    nodes = {n[0]: info for n, info in zip(NODES, infos)}

    sets = []
    for name, default, smin, smax, group in SCALAR_PARAMS:
        k = "P_" + name
        sets += [
            (k, "ParameterName", name),
            (k, "Group", group),
            (k, "DefaultValue", "%.6f" % default),
            (k, "SliderMin", "%.6f" % smin),
            (k, "SliderMax", "%.6f" % smax),
        ]
    for name, rgba, group in VECTOR_PARAMS:
        k = "P_" + name
        sets += [
            (k, "ParameterName", name),
            (k, "Group", group),
            (k, "DefaultValue", _color_text(rgba)),
        ]
    sets += [("T_GlowStripTex", "ParameterName", "GlowStripTex"), ("T_GlowStripTex", "Group", "Textures")]
    sets += CONST_SETS

    MNS.batch_set_properties(MAT_PATH, [nodes[s[0]].id for s in sets], [s[1] for s in sets], [s[2] for s in sets])

    tex = EAL.load_asset(TEX_PATH)
    expr = unreal.find_object(None, nodes["T_GlowStripTex"].object_path)
    expr.set_editor_property("texture", tex)
    MNS.set_expression_property(MAT_PATH, nodes["T_GlowStripTex"].id, "SamplerType", "SAMPLERTYPE_Color")

    cnt = MNS.batch_connect_expressions(
        MAT_PATH,
        [nodes[c[0]].id for c in CONNECTIONS],
        [c[1] for c in CONNECTIONS],
        [nodes[c[2]].id for c in CONNECTIONS],
        [c[3] for c in CONNECTIONS],
    )
    if cnt != len(CONNECTIONS):
        for c in CONNECTIONS:
            ok1 = MNS.batch_connect_expressions(MAT_PATH, [nodes[c[0]].id], [c[1]], [nodes[c[2]].id], [c[3]])
            if ok1 != 1:
                report.error(f"Wire failed: {c}")

    if not MNS.connect_expression_to_output(MAT_PATH, nodes["EmissiveOut"].id, "", "EmissiveColor"):
        report.error("Failed connecting EmissiveOut -> EmissiveColor")

    MEL.set_material_usage(mat, unreal.MaterialUsage.MATUSAGE_NIAGARA_MESH_PARTICLES)
    MEL.layout_material_expressions(mat)
    MEL.recompile_material(mat)
    EAL.save_asset(MAT_PATH, False)
    report.modified(MAT_PATH, f"compiled {MAT_NAME} ({len(NODES)} nodes, {cnt}/{len(CONNECTIONS)} wires)")

    # Build static & Niagara Material Instances + assign slot 0 on SM_SlashOuterGlow_01..05
    at = unreal.AssetToolsHelpers.get_asset_tools()
    mif = unreal.MaterialInstanceConstantFactoryNew()
    for i in range(1, 6):
        for prefix, use_pt in (("MI_SlashOuterGlow_", 0.0), ("MI_SlashOuterGlowNS_", 1.0)):
            mi_name = f"{prefix}{i:02d}"
            mi_path = f"{C.MAT_DIR}/{mi_name}"
            if not EAL.does_asset_exist(mi_path):
                mi = at.create_asset(mi_name, C.MAT_DIR, unreal.MaterialInstanceConstant, mif)
                report.created(mi_path)
            else:
                mi = EAL.load_asset(mi_path)
            MEL.set_material_instance_parent(mi, mat)
            MEL.set_material_instance_scalar_parameter_value(mi, "UseParticleTime", use_pt)
            MEL.set_material_instance_scalar_parameter_value(mi, "SlashProgress", 0.50)
            MEL.set_material_instance_scalar_parameter_value(mi, "SlashWidth", 1.35)
            MEL.set_material_instance_scalar_parameter_value(mi, "SlashSoftness", 0.05)
            MEL.set_material_instance_scalar_parameter_value(mi, "TailSoftness", 0.35)
            MEL.set_material_instance_scalar_parameter_value(mi, "EmissiveBoost", 0.92)
            MEL.set_material_instance_vector_parameter_value(
                mi, "GlowTint", unreal.LinearColor(1.0, 0.95, 0.84, 1.0)
            )
            MEL.update_material_instance(mi)
            EAL.save_asset(mi_path, False)

        sm_path = f"{C.MESH_DIR}/SM_SlashOuterGlow_{i:02d}"
        if EAL.does_asset_exist(sm_path):
            sm = EAL.load_asset(sm_path)
            mi_static = EAL.load_asset(f"{C.MAT_DIR}/MI_SlashOuterGlow_{i:02d}")
            sm.set_material(0, mi_static)
            EAL.save_asset(sm_path, False)


def update_niagara_slash_outer_glow(report):
    slash_pkg = f"{C.NS_DIR}/NS_IceSlash_Slash"
    slash_ref = f"{slash_pkg}.NS_IceSlash_Slash"
    summary = vibeue.exec_tool(NTS, "GetSystemSummary", {"system": {"refPath": slash_ref}})
    existing_set = {e["emitterName"] for e in summary.get("emitters", [])}

    # Exact flat Z=0 canonical transform derived from flat_slash_canon.json:
    # SM_SlashArc_01 & SM_SlashOuterGlow_01 have R=244.536cm, center=(4.568, -1.782, 71.39), extent.z=0.0!
    s = 270.0 / 244.536
    canon_scale = (s, s, s)
    canon_rot = (0.0, 90.0, 0.0)
    canon_pos = (-1.97, -5.04, -78.82)

    # 1. Update Mist, Smoke, Blade to the flat Z=0 canonical transform
    N5._configure_static_blade_emitter(
        slash_ref, "Mist", "SM_SlashMist_01", "MI_SlashMist_01",
        spawn_time=0.02, lifetime=0.72, loop_dur=1.4,
        pos_offset=canon_pos, mesh_scale=canon_scale, mesh_rot=canon_rot,
        alpha_curve=[(0.0, 0.82), (0.45, 0.72), (1.0, 0.0)], sort_hint=1,
    )
    N5._configure_static_blade_emitter(
        slash_ref, "Smoke", "SM_SlashArc_01", "MI_SlashSmoke_01",
        spawn_time=0.005, lifetime=0.78, loop_dur=1.4,
        pos_offset=(canon_pos[0], canon_pos[1], canon_pos[2] - 22.0),
        mesh_scale=canon_scale, mesh_rot=canon_rot,
        alpha_curve=[(0.0, 0.62), (0.50, 0.48), (1.0, 0.0)], sort_hint=3,
    )
    N5._configure_static_blade_emitter(
        slash_ref, "Blade", "SM_SlashArc_01", "MI_SlashArcNS_01",
        spawn_time=0.005, lifetime=0.44, loop_dur=1.4,
        pos_offset=canon_pos, mesh_scale=canon_scale, mesh_rot=canon_rot,
        alpha_curve=[(0.0, 1.0), (0.74, 1.0), (1.0, 0.0)], sort_hint=12,
    )

    # 2. Add & configure Blade_OuterGlow right on top of Blade's golden outer rim (SortOrderHint=13)
    N5._ensure_skill_emitter(slash_ref, "Blade_OuterGlow", TMP_EM_MESH, existing_set)
    N5._configure_static_blade_emitter(
        slash_ref, "Blade_OuterGlow", "SM_SlashOuterGlow_01", "MI_SlashOuterGlowNS_01",
        spawn_time=0.005, lifetime=0.44, loop_dur=1.4,
        pos_offset=canon_pos, mesh_scale=canon_scale, mesh_rot=canon_rot,
        alpha_curve=[(0.0, 1.0), (0.74, 1.0), (1.0, 0.0)], sort_hint=13,
    )
    EAL.save_asset(slash_pkg, False)
    after = vibeue.exec_tool(NTS, "GetSystemSummary", {"system": {"refPath": slash_ref}})
    em_names = [e["emitterName"] for e in after.get("emitters", [])]
    report.modified(slash_pkg, f"updated flat Z=0 + added Blade_OuterGlow; emitters={em_names}")
    return em_names


def main():
    report = C.Report(SCRIPT_NAME)
    with report.step("Build M_SlashOuterGlow and Material Instances"):
        build_outer_glow_material(report)
    with report.step("Update NS_IceSlash_Slash flat transform + Blade_OuterGlow emitter"):
        ems = update_niagara_slash_outer_glow(report)
    return {"status": "ok", "emitters": ems}


if __name__ == "__main__":
    main()
