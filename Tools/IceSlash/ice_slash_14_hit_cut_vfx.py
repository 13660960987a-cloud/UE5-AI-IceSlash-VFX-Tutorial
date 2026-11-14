"""IceSlash step 14: Authentic Stylized Target-Hit VFX (NS_IceSlash_Hit).

Replaces the placeholder comic-book orange starburst with the true reference hit effect:
  1. Hit_FrostMist   : Subtle translucent ice-cyan/white mist puff behind the impact point (SortOrder 16).
  2. Hit_CutBeam     : Razor-sharp, anti-aliased needle-tapered piercing cut beam
                       (left = sapphire/electric ice-cyan, center = incandescent pure white,
                        right = radiant warm golden-yellow; SortOrder 25).
  3. Hit_IceShards   : Crisp cel-shaded faceted cyan-blue polygonal ice fragments bursting from the hit (SortOrder 26).
  4. Hit_FineGlints  : Tiny crisp 4-pt white/gold star glints at the impact core (SortOrder 27).

Triggered strictly on target hit (never baked into NS_IceSlash_Slash and never fired when swinging at empty air).
"""
import importlib
import os
import sys
import unreal
import vibeue

TOOLS_DIR = "/Users/mengmeile/Downloads/lianxi/m/Tools/IceSlash"
if TOOLS_DIR not in sys.path:
    sys.path.insert(0, TOOLS_DIR)

import ice_slash_common as C  # noqa: E402
import ice_slash_05_niagara as m05  # noqa: E402

importlib.reload(C)
importlib.reload(m05)

EAL = unreal.EditorAssetLibrary
MEL = unreal.MaterialEditingLibrary
NTS = m05.NTS
SPRITE_SRC_DIR = "/Users/mengmeile/Downloads/lianxi/m/SourceAssets/VFXSprites"


def import_hit_textures(report):
    at = unreal.AssetToolsHelpers.get_asset_tools()
    # IMPORTANT:
    # - M_VFX_Sprite_Additive uses SAMPLERTYPE_LinearColor -> requires srgb=False!
    #   Use TC_VECTOR_DISPLACEMENTMAP (uncompressed RGBA8, srgb=False) + TMGS_NO_MIPMAPS + never_stream=True
    #   so there is ZERO DXT 4x4 blockiness and ZERO mip-streaming stair-step jaggedness!
    # - M_VFX_Sprite_Translucent uses SAMPLERTYPE_Color -> requires srgb=True!
    #   Because T_VFX_IceShard_A is cyan-blue (high B channel), UE5's PNG importer otherwise misdetects it
    #   as TC_NORMALMAP (which breaks the shader into neon-green DefaultMaterial!). Force TC_EDITOR_ICON
    #   (uncompressed RGBA8, srgb=True) + TMGS_NO_MIPMAPS + never_stream=True!
    tex_configs = [
        (
            "T_VFX_HitCutBeam_A",
            False,
            unreal.TextureCompressionSettings.TC_VECTOR_DISPLACEMENTMAP,
        ),
        (
            "T_VFX_IceShard_A",
            True,
            unreal.TextureCompressionSettings.TC_EDITOR_ICON,
        ),
    ]
    for tex_name, use_srgb, comp_setting in tex_configs:
        src_png = os.path.join(SPRITE_SRC_DIR, f"{tex_name}.png")
        dest_pkg = f"{C.TEX_DIR}/{tex_name}"
        t = unreal.AssetImportTask()
        t.filename = src_png
        t.destination_path = C.TEX_DIR
        t.destination_name = tex_name
        t.automated = True
        t.replace_existing = True
        t.replace_existing_settings = True
        t.save = False
        t.async_ = False
        at.import_asset_tasks([t])

        tex = EAL.load_asset(dest_pkg)
        tex.set_editor_property("compression_settings", comp_setting)
        tex.set_editor_property("mip_gen_settings", unreal.TextureMipGenSettings.TMGS_NO_MIPMAPS)
        tex.set_editor_property("never_stream", True)
        tex.set_editor_property("srgb", use_srgb)
        tex.set_editor_property("filter", unreal.TextureFilter.TF_BILINEAR)
        tex.set_editor_property("address_x", unreal.TextureAddress.TA_CLAMP)
        tex.set_editor_property("address_y", unreal.TextureAddress.TA_CLAMP)
        EAL.save_asset(dest_pkg, False)
        report.modified(dest_pkg, f"imported uncompressed RGBA8 (srgb={use_srgb}, never_stream=True)")

    # Also disable mip-streaming drops on hero slash & sprite textures so frame-1 captures are always razor-sharp
    for hero_tex_name in (
        "T_SlashBlade_Painted",
        "T_SlashBlade_BodyMask",
        "T_SlashOuterGlow",
        "T_VFX_FogPuff_A",
        "T_VFX_GoldStar_A",
        "T_VFX_HexSnowflake_A",
    ):
        hp = f"{C.TEX_DIR}/{hero_tex_name}"
        if EAL.does_asset_exist(hp):
            ht = EAL.load_asset(hp)
            if ht and not ht.get_editor_property("never_stream"):
                ht.set_editor_property("never_stream", True)
                EAL.save_asset(hp, False)


def build_hit_materials(report):
    at = unreal.AssetToolsHelpers.get_asset_tools()
    mif = unreal.MaterialInstanceConstantFactoryNew()

    specs = [
        ("MI_VFX_HitCutBeam", "M_VFX_Sprite_Additive", "T_VFX_HitCutBeam_A", (1.0, 1.0, 1.0, 1.0), 2.65, {}),
        ("MI_VFX_IceShard", "M_VFX_Sprite_Translucent", "T_VFX_IceShard_A", (1.0, 1.0, 1.0, 1.0), 1.95, {"OpacityBoost": 0.96, "FadeDistance": 3.0}),
    ]
    for mi_name, parent_name, tex_name, tint, boost, extra in specs:
        mi_path = f"{C.MAT_DIR}/{mi_name}"
        parent = EAL.load_asset(f"{C.MAT_DIR}/{parent_name}")
        tex = EAL.load_asset(f"{C.TEX_DIR}/{tex_name}")
        if not EAL.does_asset_exist(mi_path):
            mi = at.create_asset(mi_name, C.MAT_DIR, unreal.MaterialInstanceConstant, mif)
            report.created(mi_path)
        else:
            mi = EAL.load_asset(mi_path)
        MEL.set_material_instance_parent(mi, parent)
        MEL.clear_all_material_instance_parameters(mi)
        MEL.set_material_instance_texture_parameter_value(mi, "SpriteTex", tex)
        MEL.set_material_instance_vector_parameter_value(mi, "TintColor", unreal.LinearColor(*tint))
        MEL.set_material_instance_scalar_parameter_value(mi, "EmissiveBoost", boost)
        for k, v in extra.items():
            MEL.set_material_instance_scalar_parameter_value(mi, k, v)
        MEL.update_material_instance(mi)
        EAL.save_asset(mi_path, False)
        report.modified(mi_path, f"configured {mi_name}")


def rebuild_ns_hit(report):
    hit_pkg = f"{C.NS_DIR}/NS_IceSlash_Hit"
    hit_ref = f"{hit_pkg}.NS_IceSlash_Hit"

    summary = vibeue.exec_tool(NTS, "GetSystemSummary", {"system": {"refPath": hit_ref}})
    for old_em in [e["emitterName"] for e in summary.get("emitters", [])]:
        vibeue.exec_tool(NTS, "RemoveEmitter", {"emitterRef": {"system": {"refPath": hit_ref}, "emitterName": old_em}})

    emitters = [
        ("Hit_FrostMist", m05.TMP_EM_OMNI),
        ("Hit_CutBeam", m05.TMP_EM_OMNI),
        ("Hit_IceShards", m05.TMP_EM_OMNI),
        ("Hit_FineGlints", m05.TMP_EM_OMNI),
    ]
    for em_name, em_tmp in emitters:
        vibeue.exec_tool(
            NTS,
            "AddEmitter",
            {"system": {"refPath": hit_ref}, "templateEmitter": {"refPath": em_tmp}, "emitterName": em_name},
        )

    # 1. Hit_FrostMist: soft translucent icy mist puff right at the hit core (SortOrder 16, below CutBeam)
    m05._configure_omni_timed(
        hit_ref, "Hit_FrostMist", spawn_time=0.0, count=3, life_min=0.20, life_max=0.30,
        pos_offset=(0.0, 0.0, 0.0), sphere_radius=12.0,
        vel_min=40.0, vel_max=115.0, gravity=(0.0, 0.0, 0.0), drag=3.5,
        size_curve=[(0.0, 0.55), (0.30, 1.05), (1.0, 1.28)],
        alpha_curve=[(0.0, 0.80), (0.35, 0.60), (1.0, 0.0)],
    )
    m05._set_input(hit_ref, "Hit_FrostMist", "EmitterUpdateScript", "EmitterState", "Loop Duration", m05._val_float(0.8))
    m05._set_color_range(hit_ref, "Hit_FrostMist", (0.55, 0.88, 1.0, 0.25), (0.85, 0.96, 1.0, 0.32))
    m05._set_sprite_uniform_range(hit_ref, "Hit_FrostMist", 115.0, 155.0, 0.0, 360.0)
    m05._update_sprite_renderer(
        hit_ref, "Hit_FrostMist", f"{C.MAT_DIR}/MI_VFX_FogPuff", "Unaligned", "FaceCamera", sort_hint=16
    )

    # 2. Hit_CutBeam: Hero razor-sharp bi-colored (left cyan -> white core -> right gold) piercing cut beam!
    #    Uses VelocityAligned + FaceCamera with deterministic local +Y velocity so Actor Rotation sets exact 3D cut angle!
    m05._set_once_burst(hit_ref, "Hit_CutBeam", spawn_time=0.0, count=1, life_max=0.24)
    m05._set_input(hit_ref, "Hit_CutBeam", "EmitterUpdateScript", "EmitterState", "Loop Duration", m05._val_float(0.8))
    m05._set_input(hit_ref, "Hit_CutBeam", "ParticleSpawnScript", "InitializeParticle", "Lifetime Min", m05._val_float(0.22))
    m05._set_input(hit_ref, "Hit_CutBeam", "ParticleSpawnScript", "InitializeParticle", "Lifetime Max", m05._val_float(0.24))
    # -35 cm along local -Y places y_core=0.38 (incandescent white impact flare) right on (0,0,0) target while keeping both needle tips inside frame!
    m05._set_input(hit_ref, "Hit_CutBeam", "ParticleSpawnScript", "InitializeParticle", "UsePositionOffset", m05._val_bool(True))
    m05._set_input(hit_ref, "Hit_CutBeam", "ParticleSpawnScript", "InitializeParticle", "Position Offset", m05._val_vec3(0.0, -35.0, 0.0))
    m05._set_input(hit_ref, "Hit_CutBeam", "ParticleSpawnScript", "ShapeLocation", "UseOwnerScale", m05._val_bool(False))
    m05._set_input(hit_ref, "Hit_CutBeam", "ParticleSpawnScript", "ShapeLocation", "Sphere Radius", m05._val_float(0.05))
    m05._set_color_direct(hit_ref, "Hit_CutBeam", (1.0, 1.0, 1.0, 1.0))
    m05._set_sprite_nonuniform_range(hit_ref, "Hit_CutBeam", (52.0, 560.0), (54.0, 580.0))
    m05._set_input(
        hit_ref, "Hit_CutBeam", "ParticleSpawnScript", "AddVelocity", "Velocity Mode",
        m05._val_enum("/Niagara/Enums/Utility/ENiagara_VelocityMode.ENiagara_VelocityMode", "NewEnumerator0"),
    )
    m05._set_input(hit_ref, "Hit_CutBeam", "ParticleSpawnScript", "AddVelocity", "Velocity", m05._val_vec3(0.0, 40.0, 0.0))
    m05._set_input(hit_ref, "Hit_CutBeam", "ParticleUpdateScript", "GravityForce", "Gravity", m05._val_vec3(0.0, 0.0, 0.0))
    m05._set_input(hit_ref, "Hit_CutBeam", "ParticleUpdateScript", "Drag", "Drag", m05._val_float(0.8))
    m05._set_input(
        hit_ref, "Hit_CutBeam", "ParticleUpdateScript", "ScaleSpriteSize",
        ["Scale Factor", "Value", "FloatCurve"],
        m05._val_curve([(0.0, 0.65), (0.18, 1.05), (0.55, 0.92), (1.0, 0.25)]),
    )
    m05._set_input(
        hit_ref, "Hit_CutBeam", "ParticleUpdateScript", "ScaleColor",
        ["Scale Alpha", "FloatCurve"],
        m05._val_curve([(0.0, 1.0), (0.52, 0.94), (1.0, 0.0)]),
    )
    m05._update_sprite_renderer(
        hit_ref, "Hit_CutBeam", f"{C.MAT_DIR}/MI_VFX_HitCutBeam", "VelocityAligned", "FaceCamera", sort_hint=25
    )

    # 3. Hit_IceShards: 5 crisp cel-shaded cyan crystal fragments flying out from the cut (SortOrder 26)
    m05._configure_omni_timed(
        hit_ref, "Hit_IceShards", spawn_time=0.0, count=5, life_min=0.24, life_max=0.36,
        pos_offset=(0.0, 0.0, 0.0), sphere_radius=14.0,
        vel_min=260.0, vel_max=520.0, gravity=(0.0, 0.0, -420.0), drag=2.2,
        size_curve=[(0.0, 0.78), (0.25, 1.05), (1.0, 0.15)],
        alpha_curve=[(0.0, 1.0), (0.68, 0.92), (1.0, 0.0)],
    )
    m05._set_input(hit_ref, "Hit_IceShards", "EmitterUpdateScript", "EmitterState", "Loop Duration", m05._val_float(0.8))
    m05._set_color_range(hit_ref, "Hit_IceShards", (0.85, 0.97, 1.0, 0.95), (1.0, 1.0, 1.0, 1.0))
    m05._set_sprite_uniform_range(hit_ref, "Hit_IceShards", 18.0, 30.0, 0.0, 360.0)
    m05._update_sprite_renderer(
        hit_ref, "Hit_IceShards", f"{C.MAT_DIR}/MI_VFX_IceShard", "Unaligned", "FaceCamera", sort_hint=26
    )

    # 4. Hit_FineGlints: 4 small crisp 4-pt star glints around the impact point (SortOrder 27)
    m05._configure_omni_timed(
        hit_ref, "Hit_FineGlints", spawn_time=0.0, count=4, life_min=0.16, life_max=0.26,
        pos_offset=(0.0, 0.0, 0.0), sphere_radius=20.0,
        vel_min=180.0, vel_max=390.0, gravity=(0.0, 0.0, -180.0), drag=3.2,
        size_curve=[(0.0, 0.65), (0.25, 1.10), (1.0, 0.0)],
        alpha_curve=[(0.0, 1.0), (0.55, 0.85), (1.0, 0.0)],
    )
    m05._set_input(hit_ref, "Hit_FineGlints", "EmitterUpdateScript", "EmitterState", "Loop Duration", m05._val_float(0.8))
    m05._set_color_range(hit_ref, "Hit_FineGlints", (0.72, 0.95, 1.0, 1.0), (1.0, 0.90, 0.45, 1.0))
    m05._set_sprite_uniform_range(hit_ref, "Hit_FineGlints", 13.0, 22.0, -15.0, 15.0)
    m05._update_sprite_renderer(
        hit_ref, "Hit_FineGlints", f"{C.MAT_DIR}/MI_VFX_GoldStar", "Unaligned", "FaceCamera", sort_hint=27
    )

    EAL.save_asset(hit_pkg, False)
    report.modified(hit_pkg, "rebuilt authentic NS_IceSlash_Hit (Hit_FrostMist + Hit_CutBeam + Hit_IceShards + Hit_FineGlints)")


def cleanup_stray_level_niagara(report):
    sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    removed = []
    for a in list(sub.get_all_level_actors()):
        lbl = a.get_actor_label()
        if lbl in ("NiagaraActor", "NiagaraActor2"):
            sub.destroy_actor(a)
            removed.append(lbl)
    if removed:
        report.info(f"Removed stray transient NiagaraActors from level: {removed}")


def main():
    report = C.Report("ice_slash_14_hit_cut_vfx")
    with report.step("Import uncompressed HitCutBeam & IceShard textures"):
        import_hit_textures(report)
    with report.step("Build MI_VFX_HitCutBeam & MI_VFX_IceShard"):
        build_hit_materials(report)
    with report.step("Rebuild NS_IceSlash_Hit with piercing bi-color cut beam & ice shards"):
        rebuild_ns_hit(report)
    with report.step("Clean stray NiagaraActors in L_IceSlash_v2"):
        cleanup_stray_level_niagara(report)
    unreal.EditorLoadingAndSavingUtils.save_dirty_packages(True, True)
    return report.finish()


if __name__ == "__main__":
    main()
