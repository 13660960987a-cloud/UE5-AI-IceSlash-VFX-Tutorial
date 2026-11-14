"""ice_slash_05_niagara.py - Build Niagara particle materials & 6 v3 Niagara systems.

Run inside the UE 5.9 editor:
    import runpy; runpy.run_path('/Users/mengmeile/Downloads/lianxi/m/Tools/IceSlash/ice_slash_05_niagara.py', run_name='__main__')

Creates / updates in /Game/VFX/IceSlash/Materials (strictly never touches M_SlashArc_v2 / MI_SlashArc_*):
    - M_VFX_Sprite_Translucent, M_VFX_Sprite_Additive, M_VFX_ShockwaveRing, M_VFX_Debris_Toon
    - MI_VFX_ImpactStarburst, MI_VFX_LightRay, MI_VFX_SmokePuff, MI_VFX_Snowflake,
      MI_VFX_GoldStar, MI_VFX_SnowDome, MI_VFX_GroundStreak

Creates / updates in /Game/VFX/IceSlash/Niagara:
    1. NS_IceSlash_Impact      - Spiky yellow-white starburst + cyan/white/gold radial rays + sparks (0.2-0.3s)
    2. NS_IceSlash_Smoke       - 8 soft slate/ice-blue mist puffs (130-220 cm, 0.65-0.9s fade)
    3. NS_IceSlash_Snow        - Crisp 6-pt snowflakes (32-58 cm) + upright 4-pt gold stars + ice dust (~1.2s)
    4. NS_IceSlash_GroundFlash - 3.25s landing snow-dome flash + giant starburst + radial light rays + ground disc
    5. NS_IceSlash_Debris      - 3.50s outward flying cel-shaded ice shards with gravity & spin (0.45-0.85s)
    6. NS_IceSlash_Shockwave   - 3.25-3.75s rapid horizontal expanding shockwave ring on floor
"""

import asyncio
import importlib
import json
import math
import sys
import unreal
import vibeue

TOOLS_DIR = '/Users/mengmeile/Downloads/lianxi/m/Tools/IceSlash'
if TOOLS_DIR not in sys.path:
    sys.path.insert(0, TOOLS_DIR)
import ice_slash_common as C  # noqa: E402
importlib.reload(C)

SCRIPT_NAME = 'ice_slash_05_niagara'
NTS = 'NiagaraToolsets.NiagaraToolset_System'

MNS = unreal.MaterialNodeService
MS = unreal.MaterialService
MEL = unreal.MaterialEditingLibrary
EAL = unreal.EditorAssetLibrary

REBUILD_MATS = False
REBUILD_SYSTEMS = False
REBUILD_SKILL_EMITTERS = False
MAT_VERSION = 'vfx_niagara_v3.3'
MAT_TAG = 'IceSlashVFXMatVersion'
SYS_VERSION = 'vfx_niagara_sys_v3.3'
SYS_TAG = 'IceSlashVFXSysVersion'
SKILL_SYS_NAME = 'NS_IceSlash_Skill'
SLASH_SYS_NAME = 'NS_IceSlash_Slash'
HIT_SYS_NAME = 'NS_IceSlash_Hit'
LAND_SYS_NAME = 'NS_IceSlash_Land'
BURST_SYS_NAME = 'NS_IceSlash_Burst'
ALLOW_SLASH_OVERLAY = False   # Legacy #141 flag; canonical NS_IceSlash_Slash is built directly below
REBUILD_MODULAR = False
MODULAR_VERSION = 'vfx_modular_v3.1'
MODULAR_TAG = 'IceSlashModularVersion'
SKILL_EMITTER_VERSION = 'vfx_skill_emitters_v3.0'
SKILL_EMITTER_TAG = 'IceSlashSkillOverlayVersion'
OUR_SLASH_PREFIXES = ('Fog_', 'Deco_')
PROTECTED_SLASH_PREFIXES = ('Blade', 'Smoke', 'Mist')
OUR_SKILL_PREFIXES = ('S1_', 'S2_', 'S3_', 'S4_', 'S5_', 'Land_', 'Burst_')
PROTECTED_SKILL_PREFIXES = ('Blade_', 'Mist_', 'Smoke_', 'Hit')

TMP_SYS_MINIMAL = '/Niagara/DefaultAssets/Templates/Systems/MinimalLightweight.MinimalLightweight'
TMP_EM_OMNI = '/Niagara/DefaultAssets/Templates/Emitters/OmnidirectionalBurst.OmnidirectionalBurst'
TMP_EM_MESH = '/Niagara/DefaultAssets/Templates/Emitters/UpwardMeshBurst.UpwardMeshBurst'

MOD_SPAWNRATE = '/Niagara/Modules/Emitter/SpawnRate.SpawnRate'
MOD_GRAVITY = '/Niagara/Modules/Update/Forces/GravityForce.GravityForce'
MOD_SHAPELOC = '/Niagara/Modules/Spawn/Location/V2/ShapeLocation.ShapeLocation'
MOD_MESH_ROTRATE = '/Niagara/Modules/Update/Orientation/MeshRotationRate.MeshRotationRate'
MOD_INIT_MESH_ROT = '/Niagara/Modules/Spawn/Orientation/InitialMeshRotation.InitialMeshRotation'
MOD_SPRITE_ROTRATE = '/Niagara/Modules/Update/Orientation/SpriteRotationRate.SpriteRotationRate'

DYN_FLOAT_CURVE = '/Niagara/DynamicInputs/ValueFromCurve/FloatFromCurve.FloatFromCurve'
DYN_VEC_CURVE = '/Niagara/DynamicInputs/ValueFromCurve/VectorFromCurve.VectorFromCurve'
DYN_RAND_FLOAT = '/Niagara/DynamicInputs/UniformRange/V2/RandomRangeFloat.RandomRangeFloat'


# --------------------------------------------------------------------------------------
# Helpers for Material Creation
# --------------------------------------------------------------------------------------
def _color_str(c):
    r, g, b = c[0], c[1], c[2]
    a = c[3] if len(c) > 3 else 1.0
    return '(R=%.6f,G=%.6f,B=%.6f,A=%.6f)' % (r, g, b, a)


def _ensure_mat_asset(report, name, props):
    path = f'{C.MAT_DIR}/{name}'
    C.ensure_dir(C.MAT_DIR)
    if C.asset_exists(path):
        mat = C.load(path)
        report.skipped(path, 'material exists')
    else:
        tools = unreal.AssetToolsHelpers.get_asset_tools()
        mat = tools.create_asset(name, C.MAT_DIR, unreal.Material, unreal.MaterialFactoryNew())
        if mat is None:
            raise RuntimeError(f'Failed to create material {path}')
        report.created(path)

    for pname, pval in props:
        info = MS.get_property_info(path, pname)
        cur = info.current_value if info is not None else None
        if cur is None or cur.strip().lower() != pval.lower():
            if not MS.set_property(path, pname, pval):
                report.error(f'set_property {pname}={pval} failed on {path}')
            else:
                report.modified(path, f'{pname}={pval}')
    return mat, path


def _own_expressions(mat, path):
    prefix = mat.get_path_name() + ':'
    return [e for e in MNS.list_expressions(path) if e.object_path.startswith(prefix)]


_MP_ENUM_MAP = {
    'BaseColor': unreal.MaterialProperty.MP_BASE_COLOR,
    'EmissiveColor': unreal.MaterialProperty.MP_EMISSIVE_COLOR,
    'Opacity': unreal.MaterialProperty.MP_OPACITY,
    'OpacityMask': unreal.MaterialProperty.MP_OPACITY_MASK,
    'Roughness': unreal.MaterialProperty.MP_ROUGHNESS,
}


def _verify_and_repair_mat_wires(report, mat, path, specs, conns, outputs, expr_by_key=None, read_only=False):
    """Audit material expression inputs via MEL.get_inputs_for_material_expression (#138 item 2).
    Never trusts MNS.batch_connect_expressions return count alone; wires missing pins via MEL.
    """
    if expr_by_key is None:
        own = _own_expressions(mat, path)
        if len(own) != len(specs):
            report.info(f'WIRE_AUDIT {path}: expression count {len(own)} != spec {len(specs)} (custom layout, checking DepthFade/outputs)')
            for info in own:
                ex = unreal.find_object(None, info.object_path)
                if ex is not None and ex.get_class().get_name() == 'MaterialExpressionDepthFade':
                    inps = list(MEL.get_inputs_for_material_expression(mat, ex))
                    report.info(f'WIRE_AUDIT {path} DepthFade inputs={[x.get_name() if x else None for x in inps]}')
            return 0
        expr_by_key = {}
        for (key, _cls, _x, _y, _p), info in zip(specs, own):
            ex = unreal.find_object(None, info.object_path)
            if ex is None:
                return 0
            expr_by_key[key] = ex

    # Count expected (src_key -> dst_key) links so multi-pin links like Dot(Sub, Sub) are checked accurately.
    pair_expected = {}
    for s_k, _s_p, d_k, _d_p in conns:
        pair_expected[(s_k, d_k)] = pair_expected.get((s_k, d_k), 0) + 1

    repaired = 0
    missing = []
    for s_k, s_pin, d_k, d_pin in conns:
        s_ex = expr_by_key.get(s_k)
        d_ex = expr_by_key.get(d_k)
        if s_ex is None or d_ex is None:
            continue
        cur_inputs = list(MEL.get_inputs_for_material_expression(mat, d_ex))
        actual_cnt = sum(1 for x in cur_inputs if x == s_ex)
        if actual_cnt < pair_expected[(s_k, d_k)]:
            if read_only:
                missing.append(f'{s_k}->{d_k}.{d_pin}')
                continue
            ok = MEL.connect_material_expressions(s_ex, s_pin, d_ex, d_pin)
            if not ok:
                # Fallback: match against actual UMaterialExpression input names (e.g. InOpacity vs Opacity)
                in_names = [str(n) for n in MEL.get_material_expression_input_names(d_ex)]
                for cand in in_names:
                    if d_pin.lower() in cand.lower() or cand.lower() in d_pin.lower():
                        if MEL.connect_material_expressions(s_ex, s_pin, d_ex, cand):
                            ok = True
                            break
            if ok:
                repaired += 1
                report.modified(path, f'MEL repaired missing wire {s_k}({s_pin}) -> {d_k}({d_pin})')
            else:
                missing.append(f'{s_k}->{d_k}.{d_pin}')
                report.error(f'{path}: failed to wire {s_k}({s_pin}) -> {d_k}({d_pin})')

    for k, out_pin, mat_prop in outputs:
        ex = expr_by_key.get(k)
        mp = _MP_ENUM_MAP.get(mat_prop)
        if ex is None or mp is None:
            continue
        cur_out = MEL.get_material_property_input_node(mat, mp)
        if cur_out != ex:
            if read_only:
                missing.append(f'{k}->Material.{mat_prop}')
                continue
            if MEL.connect_material_property(ex, out_pin, mp):
                repaired += 1
                report.modified(path, f'MEL repaired output wire {k}({out_pin}) -> {mat_prop}')
            else:
                missing.append(f'{k}->Material.{mat_prop}')
                report.error(f'{path}: failed output wire {k} -> {mat_prop}')

    if repaired > 0 and not read_only:
        errs = list(MEL.recompile_material(mat))
        if errs:
            for err in errs:
                report.error(f'RECOMPILE {path}: {err}')
        else:
            report.modified(path, f'recompiled cleanly after repairing {repaired} wire(s)')
    else:
        report.info(f'WIRE_AUDIT {path}: verified {len(conns)} expr wires + {len(outputs)} outputs OK (missing={missing})')
    return repaired


def _build_mat_graph(report, mat, path, specs, conns, outputs):
    tag = EAL.get_metadata_tag(mat, MAT_TAG)
    existing = _own_expressions(mat, path)
    if existing and not REBUILD_MATS and tag == MAT_VERSION:
        _verify_and_repair_mat_wires(
            report, mat, path, specs, conns, outputs,
            read_only=path.endswith('/M_VFX_Sprite_Translucent'),
        )
        report.skipped(path, f'graph {MAT_VERSION} up to date')
        return
    if existing:
        MEL.delete_all_material_expressions(mat)

    infos = MNS.batch_create_expressions(
        path,
        [s[1] for s in specs],
        [s[2] for s in specs],
        [s[3] for s in specs],
    )
    if len(infos) != len(specs):
        raise RuntimeError(f'{path}: created {len(infos)}/{len(specs)} expressions')
    nodes = {}
    expr_by_key = {}
    for spec, info in zip(specs, infos):
        nodes[spec[0]] = info
        expr_by_key[spec[0]] = unreal.find_object(None, info.object_path)

    ids, names, vals = [], [], []
    for key, _cls, _x, _y, pdict in specs:
        for pk, pv in pdict.items():
            ids.append(nodes[key].id)
            names.append(pk)
            vals.append(str(pv))
    if ids:
        n_set = MNS.batch_set_properties(path, ids, names, vals)
        if n_set != len(ids):
            report.error(f'{path}: batch_set_properties {n_set}/{len(ids)}')

    if conns:
        MNS.batch_connect_expressions(
            path,
            [nodes[c[0]].id for c in conns],
            [c[1] for c in conns],
            [nodes[c[2]].id for c in conns],
            [c[3] for c in conns],
        )

    for key, out_pin, mat_prop in outputs:
        if not MNS.connect_expression_to_output(path, nodes[key].id, out_pin, mat_prop):
            report.error(f'{path}: connect_expression_to_output {key}->{mat_prop} failed')

    _verify_and_repair_mat_wires(report, mat, path, specs, conns, outputs, expr_by_key=expr_by_key, read_only=False)
    MEL.layout_material_expressions(mat)
    errs = list(MEL.recompile_material(mat))
    if errs:
        for err in errs:
            report.error(f'COMPILE {path}: {err}')
    else:
        EAL.set_metadata_tag(mat, MAT_TAG, MAT_VERSION)
        report.modified(path, f'compiled {MAT_VERSION} cleanly')


def _ensure_mi(report, parent_mat, name, tex_params=None, vec_params=None, scalar_params=None):
    path = f'{C.MAT_DIR}/{name}'
    if C.asset_exists(path):
        mi = C.load(path)
    else:
        tools = unreal.AssetToolsHelpers.get_asset_tools()
        mi = tools.create_asset(
            name, C.MAT_DIR, unreal.MaterialInstanceConstant, unreal.MaterialInstanceConstantFactoryNew()
        )
        report.created(path)

    cur_parent = mi.get_editor_property('parent')
    if cur_parent is None or cur_parent.get_path_name() != parent_mat.get_path_name():
        MEL.set_material_instance_parent(mi, parent_mat)

    for pname, tpath in (tex_params or {}).items():
        if C.asset_exists(tpath):
            tex = C.load(tpath)
            MEL.set_material_instance_texture_parameter_value(mi, pname, tex)
        else:
            report.error(f'{path}: missing texture {tpath}')

    for pname, col in (vec_params or {}).items():
        MEL.set_material_instance_vector_parameter_value(mi, pname, unreal.LinearColor(*col))

    for pname, val in (scalar_params or {}).items():
        MEL.set_material_instance_scalar_parameter_value(mi, pname, float(val))

    MEL.update_material_instance(mi)
    report.modified(path, 'updated MI overrides')
    return mi, path


def build_vfx_materials(report):
    default_tex = f'{C.TEX_DIR}/T_VFX_HexSnowflake_A.T_VFX_HexSnowflake_A'

    # 1. M_VFX_Sprite_Translucent
    m_trans, p_trans = _ensure_mat_asset(report, 'M_VFX_Sprite_Translucent', [
        ('MaterialDomain', 'MD_Surface'),
        ('ShadingModel', 'MSM_Unlit'),
        ('BlendMode', 'BLEND_Translucent'),
        ('TwoSided', 'true'),
        ('bUsedWithNiagaraSprites', 'true'),
        ('bUsedWithNiagaraMeshParticles', 'true'),
    ])
    specs_trans = [
        ('PC', 'ParticleColor', -900, 0, {}),
        ('Tex', 'TextureSampleParameter2D', -900, 220, {
            'ParameterName': 'SpriteTex',
            'Group': 'Sprite',
            'Texture': default_tex,
        }),
        ('Tint', 'VectorParameter', -900, 480, {
            'ParameterName': 'TintColor',
            'Group': 'Sprite',
            'DefaultValue': _color_str((1.0, 1.0, 1.0, 1.0)),
        }),
        ('EBoost', 'ScalarParameter', -900, 680, {
            'ParameterName': 'EmissiveBoost',
            'Group': 'Sprite',
            'DefaultValue': '2.5',
        }),
        ('OBoost', 'ScalarParameter', -900, 820, {
            'ParameterName': 'OpacityBoost',
            'Group': 'Sprite',
            'DefaultValue': '1.0',
        }),
        ('FadeDist', 'ScalarParameter', -900, 960, {
            'ParameterName': 'FadeDistance',
            'Group': 'Sprite',
            'DefaultValue': '20.0',
        }),
        ('MulCol1', 'Multiply', -600, 80, {}),
        ('MulCol2', 'Multiply', -420, 180, {}),
        ('MulEmis', 'Multiply', -220, 220, {}),
        ('MulAlpha1', 'Multiply', -600, 740, {}),
        ('MulAlpha2', 'Multiply', -420, 780, {}),
        ('SatAlpha', 'Saturate', -260, 780, {}),
        ('DFade', 'DepthFade', -100, 820, {}),
    ]
    conns_trans = [
        ('PC', 'RGB', 'MulCol1', 'A'),
        ('Tex', 'RGB', 'MulCol1', 'B'),
        ('MulCol1', '', 'MulCol2', 'A'),
        ('Tint', 'RGB', 'MulCol2', 'B'),
        ('MulCol2', '', 'MulEmis', 'A'),
        ('EBoost', '', 'MulEmis', 'B'),
        ('PC', 'A', 'MulAlpha1', 'A'),
        ('Tex', 'A', 'MulAlpha1', 'B'),
        ('MulAlpha1', '', 'MulAlpha2', 'A'),
        ('OBoost', '', 'MulAlpha2', 'B'),
        ('MulAlpha2', '', 'SatAlpha', 'Input'),
        ('SatAlpha', '', 'DFade', 'Opacity'),
        ('FadeDist', '', 'DFade', 'FadeDistance'),
    ]
    _build_mat_graph(report, m_trans, p_trans, specs_trans, conns_trans, [
        ('MulEmis', '', 'EmissiveColor'),
        ('DFade', '', 'Opacity'),
    ])

    # 2. M_VFX_Sprite_Additive
    m_add, p_add = _ensure_mat_asset(report, 'M_VFX_Sprite_Additive', [
        ('MaterialDomain', 'MD_Surface'),
        ('ShadingModel', 'MSM_Unlit'),
        ('BlendMode', 'BLEND_Additive'),
        ('TwoSided', 'true'),
        ('bUsedWithNiagaraSprites', 'true'),
        ('bUsedWithNiagaraMeshParticles', 'true'),
    ])
    specs_add = [
        ('PC', 'ParticleColor', -900, 0, {}),
        ('Tex', 'TextureSampleParameter2D', -900, 220, {
            'ParameterName': 'SpriteTex',
            'Group': 'Sprite',
            'Texture': f'{C.TEX_DIR}/T_VFX_RadialLightRays_A.T_VFX_RadialLightRays_A',
            'SamplerType': 'SAMPLERTYPE_LinearColor',
        }),
        ('Tint', 'VectorParameter', -900, 480, {
            'ParameterName': 'TintColor',
            'Group': 'Sprite',
            'DefaultValue': _color_str((1.0, 1.0, 1.0, 1.0)),
        }),
        ('EBoost', 'ScalarParameter', -900, 680, {
            'ParameterName': 'EmissiveBoost',
            'Group': 'Sprite',
            'DefaultValue': '5.0',
        }),
        ('MulCol1', 'Multiply', -620, 80, {}),
        ('MulCol2', 'Multiply', -450, 160, {}),
        ('MulAlpha', 'Multiply', -620, 400, {}),
        ('MulColA', 'Multiply', -280, 240, {}),
        ('MulEmis', 'Multiply', -120, 280, {}),
    ]
    conns_add = [
        ('PC', 'RGB', 'MulCol1', 'A'),
        ('Tex', 'RGB', 'MulCol1', 'B'),
        ('MulCol1', '', 'MulCol2', 'A'),
        ('Tint', 'RGB', 'MulCol2', 'B'),
        ('PC', 'A', 'MulAlpha', 'A'),
        ('Tex', 'A', 'MulAlpha', 'B'),
        ('MulCol2', '', 'MulColA', 'A'),
        ('MulAlpha', '', 'MulColA', 'B'),
        ('MulColA', '', 'MulEmis', 'A'),
        ('EBoost', '', 'MulEmis', 'B'),
    ]
    _build_mat_graph(report, m_add, p_add, specs_add, conns_add, [
        ('MulEmis', '', 'EmissiveColor'),
    ])

    # 3. M_VFX_ShockwaveRing (procedural crisp anime ring on UV [0..1])
    m_ring, p_ring = _ensure_mat_asset(report, 'M_VFX_ShockwaveRing', [
        ('MaterialDomain', 'MD_Surface'),
        ('ShadingModel', 'MSM_Unlit'),
        ('BlendMode', 'BLEND_Translucent'),
        ('TwoSided', 'true'),
        ('bUsedWithNiagaraSprites', 'true'),
        ('bUsedWithNiagaraMeshParticles', 'true'),
    ])
    specs_ring = [
        ('PC', 'ParticleColor', -1200, -120, {}),
        ('UV', 'TextureCoordinate', -1400, 150, {}),
        ('Half', 'Constant2Vector', -1400, 280, {'R': '0.5', 'G': '0.5'}),
        ('Sub', 'Subtract', -1200, 180, {}),
        ('Dot', 'DotProduct', -1040, 180, {}),
        ('Sqrt', 'SquareRoot', -880, 180, {}),
        ('Rad', 'Multiply', -720, 180, {'ConstB': '2.0'}),
        # Outer sharp shockwave ring: smoothstep(0.82, 0.93, r) * (1 - smoothstep(0.93, 0.985, r))
        ('OutIn', 'SmoothStep', -520, 80, {'ConstMin': '0.82', 'ConstMax': '0.93'}),
        ('OutOut', 'SmoothStep', -520, 220, {'ConstMin': '0.93', 'ConstMax': '0.985'}),
        ('InvOut', 'OneMinus', -360, 220, {}),
        ('OuterRing', 'Multiply', -200, 140, {}),
        # Inner soft mist wake: smoothstep(0.58, 0.82, r) * (1 - smoothstep(0.82, 0.93, r)) * 0.24
        ('InIn', 'SmoothStep', -520, 380, {'ConstMin': '0.58', 'ConstMax': '0.82'}),
        ('InvIn', 'OneMinus', -360, 380, {}),
        ('InnerRaw', 'Multiply', -200, 340, {}),
        ('InnerRing', 'Multiply', -60, 340, {'ConstB': '0.24'}),
        ('SumRing', 'Add', 80, 220, {}),
        ('SatRing', 'Saturate', 220, 220, {}),
        ('Tint', 'VectorParameter', -600, -240, {
            'ParameterName': 'RingColor',
            'Group': 'Ring',
            'DefaultValue': _color_str((0.82, 0.95, 1.0, 1.0)),
        }),
        ('EBoost', 'ScalarParameter', -600, -60, {
            'ParameterName': 'EmissiveBoost',
            'Group': 'Ring',
            'DefaultValue': '4.4',
        }),
        ('Col1', 'Multiply', -320, -180, {}),
        ('Col2', 'Multiply', -120, -120, {}),
        ('Op1', 'Multiply', 360, 180, {}),
        ('OpSat', 'Saturate', 500, 180, {}),
    ]
    conns_ring = [
        ('UV', '', 'Sub', 'A'),
        ('Half', '', 'Sub', 'B'),
        ('Sub', '', 'Dot', 'A'),
        ('Sub', '', 'Dot', 'B'),
        ('Dot', '', 'Sqrt', 'Input'),
        ('Sqrt', '', 'Rad', 'A'),
        ('Rad', '', 'OutIn', 'Value'),
        ('Rad', '', 'OutOut', 'Value'),
        ('OutOut', '', 'InvOut', 'Input'),
        ('OutIn', '', 'OuterRing', 'A'),
        ('InvOut', '', 'OuterRing', 'B'),
        ('Rad', '', 'InIn', 'Value'),
        ('OutIn', '', 'InvIn', 'Input'),
        ('InIn', '', 'InnerRaw', 'A'),
        ('InvIn', '', 'InnerRaw', 'B'),
        ('InnerRaw', '', 'InnerRing', 'A'),
        ('OuterRing', '', 'SumRing', 'A'),
        ('InnerRing', '', 'SumRing', 'B'),
        ('SumRing', '', 'SatRing', 'Input'),
        ('PC', 'RGB', 'Col1', 'A'),
        ('Tint', 'RGB', 'Col1', 'B'),
        ('Col1', '', 'Col2', 'A'),
        ('EBoost', '', 'Col2', 'B'),
        ('PC', 'A', 'Op1', 'A'),
        ('SatRing', '', 'Op1', 'B'),
        ('Op1', '', 'OpSat', 'Input'),
    ]
    _build_mat_graph(report, m_ring, p_ring, specs_ring, conns_ring, [
        ('Col2', '', 'EmissiveColor'),
        ('OpSat', '', 'Opacity'),
    ])

    # 4. M_VFX_Debris_Toon (cel-shaded faceted cyan/blue ice shard with dark cobalt anime ink outline)
    m_deb, p_deb = _ensure_mat_asset(report, 'M_VFX_Debris_Toon', [
        ('MaterialDomain', 'MD_Surface'),
        ('ShadingModel', 'MSM_Unlit'),
        ('BlendMode', 'BLEND_Masked'),
        ('OpacityMaskClipValue', '0.25'),
        ('TwoSided', 'true'),
        ('bUsedWithNiagaraMeshParticles', 'true'),
    ])
    specs_deb = [
        ('PC', 'ParticleColor', -1000, -180, {}),
        ('VN', 'VertexNormalWS', -1200, 80, {}),
        ('LDir', 'Constant3Vector', -1200, 220, {'Constant': _color_str((-0.38, -0.52, 0.76, 0.0))}),
        ('NdotL', 'DotProduct', -1000, 120, {}),
        ('StepLit', 'Step', -820, 120, {'ConstY': '0.25'}),
        ('ColShadow', 'Constant3Vector', -1000, 320, {'Constant': _color_str((0.14, 0.46, 0.88, 1.0))}),
        ('ColLit', 'Constant3Vector', -1000, 460, {'Constant': _color_str((0.84, 0.97, 1.0, 1.0))}),
        ('ColInk', 'Constant3Vector', -820, 620, {'Constant': _color_str((0.03, 0.10, 0.28, 1.0))}),
        ('ToneLerp', 'LinearInterpolate', -620, 260, {}),
        ('TonePC', 'Multiply', -420, 180, {}),
        ('ToneBoost', 'Multiply', -240, 180, {'ConstB': '2.1'}),
        ('Fres', 'Fresnel', -820, 760, {'Exponent': '2.8', 'BaseReflectFraction': '0.0'}),
        ('RimStep', 'Step', -620, 760, {'ConstY': '0.58'}),
        ('FinalCol', 'LinearInterpolate', -60, 360, {}),
    ]
    conns_deb = [
        ('VN', '', 'NdotL', 'A'),
        ('LDir', '', 'NdotL', 'B'),
        ('NdotL', '', 'StepLit', 'X'),
        ('ColShadow', '', 'ToneLerp', 'A'),
        ('ColLit', '', 'ToneLerp', 'B'),
        ('StepLit', '', 'ToneLerp', 'Alpha'),
        ('ToneLerp', '', 'TonePC', 'A'),
        ('PC', 'RGB', 'TonePC', 'B'),
        ('TonePC', '', 'ToneBoost', 'A'),
        ('VN', '', 'Fres', 'Normal'),
        ('Fres', '', 'RimStep', 'X'),
        ('ToneBoost', '', 'FinalCol', 'A'),
        ('ColInk', '', 'FinalCol', 'B'),
        ('RimStep', '', 'FinalCol', 'Alpha'),
    ]
    _build_mat_graph(report, m_deb, p_deb, specs_deb, conns_deb, [
        ('FinalCol', '', 'EmissiveColor'),
        ('PC', 'A', 'OpacityMask'),
    ])

    # 5. M_ArenaFloor_Tiled (dark diagonal-grid stone arena floor with center spotlight pool matching ref_vfx)
    m_flr, p_flr = _ensure_mat_asset(report, 'M_ArenaFloor_Tiled', [
        ('MaterialDomain', 'MD_Surface'),
        ('ShadingModel', 'MSM_DefaultLit'),
        ('BlendMode', 'BLEND_Opaque'),
        ('TwoSided', 'false'),
    ])
    specs_flr = [
        ('WP', 'WorldPosition', -1500, 120, {}),
        ('XY', 'ComponentMask', -1320, 120, {'R': 'true', 'G': 'true', 'B': 'false', 'A': 'false'}),
        ('TileDiv', 'Divide', -1140, 40, {'ConstB': '125.0'}),
        # Rotate XY by 45 deg: u = (x + y)*0.7071, v = (x - y)*0.7071
        ('MaskX', 'ComponentMask', -960, -40, {'R': 'true', 'G': 'false', 'B': 'false', 'A': 'false'}),
        ('MaskY', 'ComponentMask', -960, 100, {'R': 'false', 'G': 'true', 'B': 'false', 'A': 'false'}),
        ('AddXY', 'Add', -780, -40, {}),
        ('SubXY', 'Subtract', -780, 100, {}),
        ('RotU', 'Multiply', -620, -40, {'ConstB': '0.7071'}),
        ('RotV', 'Multiply', -620, 100, {'ConstB': '0.7071'}),
        ('FracU', 'Frac', -460, -40, {}),
        ('FracV', 'Frac', -460, 100, {}),
        ('StepU1', 'SmoothStep', -300, -100, {'ConstMin': '0.0', 'ConstMax': '0.042'}),
        ('StepU2', 'SmoothStep', -300, -10, {'ConstMin': '0.958', 'ConstMax': '1.0'}),
        ('InvU2', 'OneMinus', -140, -10, {}),
        ('EdgeU', 'Multiply', 20, -60, {}),
        ('StepV1', 'SmoothStep', -300, 100, {'ConstMin': '0.0', 'ConstMax': '0.042'}),
        ('StepV2', 'SmoothStep', -300, 190, {'ConstMin': '0.958', 'ConstMax': '1.0'}),
        ('InvV2', 'OneMinus', -140, 190, {}),
        ('EdgeV', 'Multiply', 20, 140, {}),
        ('TileMask', 'Multiply', 180, 40, {}),
        # Radial spotlight falloff from origin (0,0): r = sqrt(dot(XY, XY))
        ('DotWP', 'DotProduct', -1140, 320, {}),
        ('DistWP', 'SquareRoot', -960, 320, {}),
        ('SpotFall', 'SmoothStep', -760, 320, {'ConstMin': '180.0', 'ConstMax': '960.0'}),
        ('SpotMask', 'OneMinus', -580, 320, {}),
        # Mortar vs stone tile color
        ('ColMortar', 'Constant3Vector', 0, -260, {'Constant': _color_str((0.005, 0.007, 0.012, 1.0))}),
        ('ColStone', 'Constant3Vector', 0, -160, {'Constant': _color_str((0.048, 0.056, 0.076, 1.0))}),
        ('GridCol', 'LinearInterpolate', 340, -120, {}),
        ('ColDark', 'Constant3Vector', 340, 260, {'Constant': _color_str((0.002, 0.003, 0.006, 1.0))}),
        ('FinalBase', 'LinearInterpolate', 560, 80, {}),
        ('EmisSubtle', 'Multiply', 740, 160, {'ConstB': '0.85'}),
        ('Rough', 'Constant', 560, 320, {'R': '0.62'}),
    ]
    conns_flr = [
        ('WP', '', 'XY', 'Input'),
        ('XY', '', 'TileDiv', 'A'),
        ('TileDiv', '', 'MaskX', 'Input'),
        ('TileDiv', '', 'MaskY', 'Input'),
        ('MaskX', '', 'AddXY', 'A'),
        ('MaskY', '', 'AddXY', 'B'),
        ('MaskX', '', 'SubXY', 'A'),
        ('MaskY', '', 'SubXY', 'B'),
        ('AddXY', '', 'RotU', 'A'),
        ('SubXY', '', 'RotV', 'A'),
        ('RotU', '', 'FracU', 'Input'),
        ('RotV', '', 'FracV', 'Input'),
        ('FracU', '', 'StepU1', 'Value'),
        ('FracU', '', 'StepU2', 'Value'),
        ('StepU2', '', 'InvU2', 'Input'),
        ('StepU1', '', 'EdgeU', 'A'),
        ('InvU2', '', 'EdgeU', 'B'),
        ('FracV', '', 'StepV1', 'Value'),
        ('FracV', '', 'StepV2', 'Value'),
        ('StepV2', '', 'InvV2', 'Input'),
        ('StepV1', '', 'EdgeV', 'A'),
        ('InvV2', '', 'EdgeV', 'B'),
        ('EdgeU', '', 'TileMask', 'A'),
        ('EdgeV', '', 'TileMask', 'B'),
        ('XY', '', 'DotWP', 'A'),
        ('XY', '', 'DotWP', 'B'),
        ('DotWP', '', 'DistWP', 'Input'),
        ('DistWP', '', 'SpotFall', 'Value'),
        ('SpotFall', '', 'SpotMask', 'Input'),
        ('ColMortar', '', 'GridCol', 'A'),
        ('ColStone', '', 'GridCol', 'B'),
        ('TileMask', '', 'GridCol', 'Alpha'),
        ('ColDark', '', 'FinalBase', 'A'),
        ('GridCol', '', 'FinalBase', 'B'),
        ('SpotMask', '', 'FinalBase', 'Alpha'),
        ('FinalBase', '', 'EmisSubtle', 'A'),
    ]
    _build_mat_graph(report, m_flr, p_flr, specs_flr, conns_flr, [
        ('FinalBase', '', 'BaseColor'),
        ('EmisSubtle', '', 'EmissiveColor'),
        ('Rough', '', 'Roughness'),
    ])

    # Material Instances
    mis = {}
    mis['ArenaFloor'] = p_flr
    mis['ImpactStarburst'] = _ensure_mi(
        report, m_trans, 'MI_VFX_ImpactStarburst',
        tex_params={'SpriteTex': f'{C.TEX_DIR}/T_VFX_ImpactStarburst_A'},
        vec_params={'TintColor': (1.0, 0.98, 0.90, 1.0)},
        scalar_params={'EmissiveBoost': 6.0, 'OpacityBoost': 1.45, 'FadeDistance': 8.0},
    )[1]
    mis['LightRay'] = _ensure_mi(
        report, m_add, 'MI_VFX_LightRay',
        tex_params={'SpriteTex': f'{C.TEX_DIR}/T_VFX_RadialLightRays_A'},
        vec_params={'TintColor': (1.0, 1.0, 1.0, 1.0)},
        scalar_params={'EmissiveBoost': 18.0},
    )[1]
    mis['SmokePuff'] = _ensure_mi(
        report, m_trans, 'MI_VFX_SmokePuff',
        tex_params={'SpriteTex': f'{C.TEX_DIR}/T_VFX_SmokePuff_A'},
        vec_params={'TintColor': (0.94, 0.96, 1.0, 1.0)},
        scalar_params={'EmissiveBoost': 1.15, 'OpacityBoost': 0.82, 'FadeDistance': 55.0},
    )[1]
    fog_tex_path = f'{C.TEX_DIR}/T_VFX_FogPuff_A'
    if C.asset_exists(fog_tex_path):
        mis['FogPuff'] = _ensure_mi(
            report, m_trans, 'MI_VFX_FogPuff',
            tex_params={'SpriteTex': fog_tex_path},
            vec_params={'TintColor': (0.82, 0.86, 0.94, 1.0)},
            scalar_params={'EmissiveBoost': 0.85, 'OpacityBoost': 0.34, 'FadeDistance': 48.0},
        )[1]
    else:
        fog_mi_path = f'{C.MAT_DIR}/MI_VFX_FogPuff'
        mis['FogPuff'] = fog_mi_path if C.asset_exists(fog_mi_path) else mis['SmokePuff']
    report.info(f"FogPuff material resolved to: {mis['FogPuff']}")
    mis['Snowflake'] = _ensure_mi(
        report, m_trans, 'MI_VFX_Snowflake',
        tex_params={'SpriteTex': f'{C.TEX_DIR}/T_VFX_HexSnowflake_A'},
        vec_params={'TintColor': (0.90, 0.98, 1.0, 1.0)},
        scalar_params={'EmissiveBoost': 2.3, 'OpacityBoost': 1.10, 'FadeDistance': 8.0},
    )[1]
    mis['GoldStar'] = _ensure_mi(
        report, m_trans, 'MI_VFX_GoldStar',
        tex_params={'SpriteTex': f'{C.TEX_DIR}/T_VFX_GoldStar4Pt_A'},
        vec_params={'TintColor': (1.0, 0.90, 0.42, 1.0)},
        scalar_params={'EmissiveBoost': 3.2, 'OpacityBoost': 1.15, 'FadeDistance': 8.0},
    )[1]
    mis['FrostSpeck'] = _ensure_mi(
        report, m_trans, 'MI_VFX_FrostSpeck',
        tex_params={'SpriteTex': f'{C.TEX_DIR}/T_VFX_ToonSnowMistDisc_A'},
        vec_params={'TintColor': (0.80, 0.95, 1.0, 1.0)},
        scalar_params={'EmissiveBoost': 2.2, 'OpacityBoost': 0.78, 'FadeDistance': 6.0},
    )[1]
    mis['SnowDome'] = _ensure_mi(
        report, m_trans, 'MI_VFX_SnowDome',
        tex_params={'SpriteTex': f'{C.TEX_DIR}/T_VFX_ToonSnowMistDisc_A'},
        vec_params={'TintColor': (0.92, 0.98, 1.0, 1.0)},
        scalar_params={'EmissiveBoost': 2.9, 'OpacityBoost': 0.96, 'FadeDistance': 65.0},
    )[1]
    mis['GroundStreak'] = _ensure_mi(
        report, m_trans, 'MI_VFX_GroundStreak',
        tex_params={'SpriteTex': f'{C.TEX_DIR}/T_VFX_GroundBrushTrail_A'},
        vec_params={'TintColor': (0.10, 0.36, 0.88, 1.0)},
        scalar_params={'EmissiveBoost': 1.35, 'OpacityBoost': 0.95, 'FadeDistance': 6.0},
    )[1]
    mis['ShockwaveRing'] = p_ring
    mis['DebrisToon'] = p_deb
    return mis


# --------------------------------------------------------------------------------------
# Helpers for Niagara Stack Inputs & Renderers
# --------------------------------------------------------------------------------------
def _val_float(v):
    return {'struct': {'refPath': '/Script/Niagara.NiagaraFloat'}, 'value': {'value': float(v)}}


def _val_int(v):
    return {'struct': {'refPath': '/Script/Niagara.NiagaraInt32'}, 'value': {'value': int(v)}}


def _val_bool(b):
    return {'struct': {'refPath': '/Script/Niagara.NiagaraBool'}, 'value': {'value': -1 if b else 0}}


def _val_vec2(x, y):
    return {'struct': {'refPath': '/Script/CoreUObject.Vector2f'}, 'value': {'x': float(x), 'y': float(y)}}


def _val_vec3(x, y, z):
    return {'struct': {'refPath': '/Script/CoreUObject.Vector3f'}, 'value': {'x': float(x), 'y': float(y), 'z': float(z)}}


def _val_color(r, g, b, a=1.0):
    return {
        'struct': {'refPath': '/Script/CoreUObject.LinearColor'},
        'value': {'r': float(r), 'g': float(g), 'b': float(b), 'a': float(a)},
    }


def _val_enum(enum_path, enum_elem):
    short = enum_path.split('.')[-1]
    full_elem = enum_elem if '::' in enum_elem else f'{short}::{enum_elem}'
    return {
        'struct': {'refPath': '/Script/NiagaraEditor.NiagaraExt_StackInputData_Enum'},
        'value': {'enum': {'refPath': enum_path}, 'enumName': full_elem},
    }


def _val_quat(x, y, z, w):
    return {
        'struct': {'refPath': '/Script/CoreUObject.Quat4f'},
        'value': {'x': float(x), 'y': float(y), 'z': float(z), 'w': float(w)},
    }


def _val_dyn_input(asset_ref):
    return {
        'struct': {'refPath': '/Script/NiagaraEditor.NiagaraExt_StackInputData_DynamicInput'},
        'value': {'dynamicInputAsset': {'refPath': asset_ref}},
    }


def _val_linked_float(var_name):
    return {
        'struct': {'refPath': '/Script/NiagaraEditor.NiagaraExt_StackInputData_Linked'},
        'value': {
            'linkedVariable': {
                'name': str(var_name),
                'type': {'classStructOrEnum': {'refPath': '/Script/Niagara.NiagaraFloat'}, 'bIsStatic': False},
            }
        },
    }


def _make_rich_keys(points, interp='RCIM_Cubic'):
    keys = []
    for t, v in points:
        keys.append({
            'interpMode': interp,
            'tangentMode': 'RCTM_Auto',
            'tangentWeightMode': 'RCTWM_WeightedNone',
            'time': float(t),
            'value': float(v),
            'arriveTangent': 0.0,
            'arriveTangentWeight': 0.0,
            'leaveTangent': 0.0,
            'leaveTangentWeight': 0.0,
        })
    return {
        'keys': keys,
        'preInfinityExtrap': 'RCCE_Constant',
        'postInfinityExtrap': 'RCCE_Constant',
    }


def _val_curve(points, interp='RCIM_Cubic'):
    payload = {'Curve': _make_rich_keys(points, interp=interp)}
    return {
        'struct': {'refPath': '/Script/NiagaraEditor.NiagaraExt_StackInputData_DataInterface'},
        'value': {'propertyValues': json.dumps(payload)},
    }


def _val_vec3_curve(points_txyz, interp='RCIM_Cubic'):
    payload = {
        'XCurve': _make_rich_keys([(t, x) for t, x, _y, _z in points_txyz], interp=interp),
        'YCurve': _make_rich_keys([(t, y) for t, _x, y, _z in points_txyz], interp=interp),
        'ZCurve': _make_rich_keys([(t, z) for t, _x, _y, z in points_txyz], interp=interp),
    }
    return {
        'struct': {'refPath': '/Script/NiagaraEditor.NiagaraExt_StackInputData_DataInterface'},
        'value': {'propertyValues': json.dumps(payload)},
    }


_NTS_TOOL_SCHEMAS = {}
_EM_INPUT_CACHE = {}
_EM_MOD_CACHE = {}
_INPUT_STATS = {'written': 0, 'skipped': 0, 'renderer_written': 0, 'renderer_skipped': 0}

_DYNAMIC_CHAIN_ROOTS = {
    ('SpawnRate', 'SpawnRate', 'EmitterUpdateScript'),
    ('InitializeParticle', 'Position Offset', 'ParticleSpawnScript'),
    ('ShapeLocation', 'U Position', 'ParticleSpawnScript'),
    ('ShapeLocation', 'V Position', 'ParticleSpawnScript'),
    ('AddVelocity', 'Velocity Speed', 'ParticleSpawnScript'),
    ('ScaleSpriteSize', 'Scale Factor', 'ParticleUpdateScript'),
    ('ScaleMeshSize', 'Scale Factor', 'ParticleUpdateScript'),
    ('ScaleColor', 'Scale Alpha', 'ParticleUpdateScript'),
    ('SpriteRotationRate', 'Rotation Rate', 'ParticleUpdateScript'),
}


def _ntool(tool_name, args=None):
    """Cached NiagaraToolset_System invoker (avoids parsing 3MB engine schema on every call)."""
    args = dict(args or {})
    key = tool_name.lower()
    if not _NTS_TOOL_SCHEMAS:
        tschema = vibeue.get_toolset_schema(NTS)
        for entry in (tschema.get('tools') or tschema.get('functions') or []):
            parsed = vibeue._parse_schema_entry(entry)
            if parsed:
                nm = (parsed.get('name') or parsed.get('toolName') or '')
                short = nm.rsplit('.', 1)[-1].lower()
                if short:
                    _NTS_TOOL_SCHEMAS[short] = parsed
    t_entry = _NTS_TOOL_SCHEMAS.get(key)
    if t_entry is not None:
        vibeue._fill_args_from_schema(t_entry, args)
    res = unreal.ToolsetRegistry.execute_tool(NTS, tool_name, json.dumps(args))
    if res.error:
        raise RuntimeError(f'{NTS}::{tool_name} failed: {res.error}')
    if not res.is_complete:
        return res
    out = vibeue._decode_stable(res.get_value_as_json_string())
    if isinstance(out, dict) and 'returnValue' in out:
        return vibeue._decode_stable(out['returnValue'])
    return out


def _walk_dyn_chain(mod_name, prefix_tuple, node, dest):
    if not isinstance(node, dict):
        return
    inner = node.get('value') if ('struct' in node and isinstance(node.get('value'), dict) and 'name' in node['value']) else node
    nm = inner.get('name')
    if not nm:
        return
    cur_stack = prefix_tuple + (str(nm),) if prefix_tuple else (str(nm),)
    if 'value' in inner and isinstance(inner['value'], dict):
        dest[(mod_name, cur_stack)] = inner['value']
    for child in (inner.get('inputs') or []):
        _walk_dyn_chain(mod_name, cur_stack, child, dest)


def _load_emitter_cache(sys_ref, em_name):
    """Fetch all resolved inputs on em_name in ONE GetEmitterInputValues call (+ dynamic chains)."""
    ckey = (sys_ref, em_name)
    inp_map = {}
    mod_set = set()
    rows = _ntool('GetEmitterInputValues', {'emitterRef': {'system': {'refPath': sys_ref}, 'emitterName': em_name}})
    if isinstance(rows, dict):
        rows = rows.get('returnValue') or rows.get('values') or []
    dyn_roots = []
    for mrow in (rows or []):
        mname = str(mrow.get('moduleName', ''))
        if not mname:
            continue
        mod_set.add(mname)
        for entry in (mrow.get('inputs') or []):
            iname = str(entry.get('name', ''))
            ival = entry.get('value')
            if iname and isinstance(ival, dict):
                inp_map[(mname, (iname,))] = ival
                sref = (ival.get('struct') or {}).get('refPath', '')
                if sref.endswith('NiagaraExt_StackInputData_DynamicInput'):
                    dyn_roots.append((mname, iname))
    for mname, iname in dyn_roots:
        for cand_m, cand_i, cand_script in _DYNAMIC_CHAIN_ROOTS:
            if cand_m == mname and cand_i == iname:
                try:
                    chain = _ntool('GetDynamicInputChain', {
                        'stackInputRef': {
                            'system': {'refPath': sys_ref},
                            'emitterName': em_name,
                            'scriptName': cand_script,
                            'moduleName': mname,
                            'inputNameStack': [iname],
                        }
                    })
                    _walk_dyn_chain(mname, (), chain, inp_map)
                except Exception:
                    pass
    _EM_INPUT_CACHE[ckey] = inp_map
    _EM_MOD_CACHE[ckey] = mod_set
    return inp_map, mod_set


def _floats_close(a, b, tol=1e-4):
    try:
        return abs(float(a) - float(b)) <= tol
    except Exception:
        return False


def _input_equals(cur, tgt):
    if not isinstance(cur, dict) or not isinstance(tgt, dict):
        return False
    cs = (cur.get('struct') or {}).get('refPath', '')
    ts = (tgt.get('struct') or {}).get('refPath', '')
    if cs != ts:
        return False
    cv = cur.get('value') or {}
    tv = tgt.get('value') or {}
    if cs.endswith('NiagaraFloat'):
        return _floats_close(cv.get('value'), tv.get('value'))
    if cs.endswith('NiagaraInt32'):
        return cv.get('value') == tv.get('value') and isinstance(cv.get('value'), int)
    if cs.endswith('NiagaraBool'):
        return bool(cv.get('value')) == bool(tv.get('value')) and ('value' in cv)
    if cs.endswith('Vector2f') or cs.endswith('Vector2D'):
        return all(_floats_close(cv.get(k), tv.get(k)) for k in ('x', 'y'))
    if cs.endswith('Vector3f') or cs.endswith('Vector') or cs.endswith('NiagaraPosition'):
        return all(_floats_close(cv.get(k), tv.get(k)) for k in ('x', 'y', 'z'))
    if cs.endswith('Quat4f') or cs.endswith('Quat'):
        return all(_floats_close(cv.get(k), tv.get(k)) for k in ('x', 'y', 'z', 'w'))
    if cs.endswith('LinearColor'):
        return all(_floats_close(cv.get(k), tv.get(k)) for k in ('r', 'g', 'b', 'a'))
    if cs.endswith('NiagaraExt_StackInputData_Enum'):
        ce = str(cv.get('enumName', ''))
        te = str(tv.get('enumName', ''))
        return ce == te or (ce.split('::')[-1] == te.split('::')[-1] and ce != '')
    if cs.endswith('NiagaraExt_StackInputData_Linked'):
        cn = str((cv.get('linkedVariable') or {}).get('name', ''))
        tn = str((tv.get('linkedVariable') or {}).get('name', ''))
        return cn == tn and cn != ''
    if cs.endswith('NiagaraExt_StackInputData_DynamicInput'):
        ca = (cv.get('dynamicInputAsset') or {}).get('refPath', '')
        ta = (tv.get('dynamicInputAsset') or {}).get('refPath', '')
        return ca == ta and ca != ''
    if cs.endswith('NiagaraExt_StackInputData_DataInterface'):
        try:
            co = json.loads(cv.get('propertyValues') or '{}')
            to = json.loads(tv.get('propertyValues') or '{}')
            for cname in ('Curve', 'XCurve', 'YCurve', 'ZCurve'):
                if cname in to:
                    ck = (co.get(cname) or {}).get('keys') or []
                    tk = (to.get(cname) or {}).get('keys') or []
                    if len(ck) != len(tk) or not ck:
                        return False
                    if not all(
                        _floats_close(a.get('time'), b.get('time'))
                        and _floats_close(a.get('value'), b.get('value'))
                        and a.get('interpMode') == b.get('interpMode')
                        for a, b in zip(ck, tk)
                    ):
                        return False
            return any(cname in to for cname in ('Curve', 'XCurve', 'YCurve', 'ZCurve'))
        except Exception:
            return False
    return False


def _set_input(sys_ref, em_name, script_name, mod_name, stack, data):
    stack_list = [stack] if isinstance(stack, str) else list(stack)
    stack_tup = tuple(str(x) for x in stack_list)
    ckey = (sys_ref, em_name)
    cache = _EM_INPUT_CACHE.get(ckey)
    if cache is not None:
        cur = cache.get((mod_name, stack_tup))
        if cur is not None and _input_equals(cur, data):
            _INPUT_STATS['skipped'] += 1
            return cur
    out = _ntool('SetStackInputData', {
        'stackInputRef': {
            'system': {'refPath': sys_ref},
            'emitterName': em_name,
            'scriptName': script_name,
            'moduleName': mod_name,
            'inputNameStack': stack_list,
        },
        'inputData': data,
    })
    _INPUT_STATS['written'] += 1
    if cache is not None:
        cache[(mod_name, stack_tup)] = out if isinstance(out, dict) else data
    return out


def _update_sprite_renderer(
    sys_ref, em_name, mat_path, alignment='Unaligned', facing='FaceCamera', pivot=(0.5, 0.5), sort_hint=0
):
    mat_name = mat_path.split('/')[-1]
    mat_ref = f'{mat_path}.{mat_name}' if '.' not in mat_path else mat_path
    rref = {'system': {'refPath': sys_ref}, 'emitterName': em_name, 'rendererIndex': 0}
    cur = _ntool('GetRendererData', {'rendererRef': rref})
    props = json.loads(cur['propertyValues'])
    cur_piv = props.get('PivotInUVSpace') or {}
    if (
        (props.get('Material') or {}).get('refPath') == mat_ref
        and props.get('Alignment') == alignment
        and props.get('FacingMode') == facing
        and _floats_close(cur_piv.get('x'), pivot[0])
        and _floats_close(cur_piv.get('y'), pivot[1])
        and props.get('SortOrderHint') == int(sort_hint)
        and props.get('bCastShadows') is False
    ):
        _INPUT_STATS['renderer_skipped'] += 1
        return
    props['Material'] = {'refPath': mat_ref}
    props['Alignment'] = alignment
    props['FacingMode'] = facing
    props['PivotInUVSpace'] = {'x': float(pivot[0]), 'y': float(pivot[1])}
    props['SortOrderHint'] = int(sort_hint)
    props['bCastShadows'] = False
    _ntool('SetRendererData', {
        'rendererRef': rref,
        'rendererData': {'propertyValues': json.dumps(props)},
    })
    _INPUT_STATS['renderer_written'] += 1


def _update_mesh_renderer(
    sys_ref, em_name, mesh_refs, mat_path, facing='Velocity',
    mesh_scale=(1.0, 1.0, 1.0), mesh_rot=(0.0, 0.0, 0.0), sort_hint=0
):
    mat_name = mat_path.split('/')[-1]
    mat_ref = f'{mat_path}.{mat_name}' if '.' not in mat_path else mat_path
    rref = {'system': {'refPath': sys_ref}, 'emitterName': em_name, 'rendererIndex': 0}
    cur = _ntool('GetRendererData', {'rendererRef': rref})
    props = json.loads(cur['propertyValues'])
    cur_meshes = props.get('Meshes') or []
    cur_ov = (props.get('OverrideMaterials') or [{}])[0]
    same_meshes = (
        len(cur_meshes) == len(mesh_refs)
        and all(
            (cm.get('mesh') or {}).get('refPath') == mref
            and _floats_close((cm.get('scale') or {}).get('x'), mesh_scale[0])
            and _floats_close((cm.get('scale') or {}).get('y'), mesh_scale[1])
            and _floats_close((cm.get('scale') or {}).get('z'), mesh_scale[2])
            and _floats_close((cm.get('rotation') or {}).get('pitch'), mesh_rot[0])
            and _floats_close((cm.get('rotation') or {}).get('yaw'), mesh_rot[1])
            and _floats_close((cm.get('rotation') or {}).get('roll'), mesh_rot[2])
            for cm, mref in zip(cur_meshes, mesh_refs)
        )
    )
    if (
        same_meshes
        and props.get('FacingMode') == facing
        and props.get('SortOrderHint') == int(sort_hint)
        and props.get('bOverrideMaterials') is True
        and props.get('bCastShadows') is False
        and (cur_ov.get('explicitMat') or {}).get('refPath') == mat_ref
    ):
        _INPUT_STATS['renderer_skipped'] += 1
        return
    base_entry = cur_meshes[0] if cur_meshes else {}
    new_meshes = []
    for mref in mesh_refs:
        entry = json.loads(json.dumps(base_entry))
        entry['mesh'] = {'refPath': mref}
        entry['scale'] = {'x': float(mesh_scale[0]), 'y': float(mesh_scale[1]), 'z': float(mesh_scale[2])}
        entry['rotation'] = {'pitch': float(mesh_rot[0]), 'yaw': float(mesh_rot[1]), 'roll': float(mesh_rot[2])}
        new_meshes.append(entry)
    props['Meshes'] = new_meshes
    props['FacingMode'] = facing
    props['SortOrderHint'] = int(sort_hint)
    props['bOverrideMaterials'] = True
    props['bCastShadows'] = False
    if props.get('OverrideMaterials'):
        props['OverrideMaterials'][0]['explicitMat'] = {'refPath': mat_ref}
    _ntool('SetRendererData', {
        'rendererRef': rref,
        'rendererData': {'propertyValues': json.dumps(props)},
    })
    _INPUT_STATS['renderer_written'] += 1


def _system_is_current(sys_pkg, expected_emitters):
    if REBUILD_SYSTEMS or not C.asset_exists(sys_pkg):
        return False
    obj = C.load(sys_pkg)
    if EAL.get_metadata_tag(obj, SYS_TAG) != SYS_VERSION:
        return False
    name = sys_pkg.split('/')[-1]
    summary = vibeue.exec_tool(NTS, 'GetSystemSummary', {'system': {'refPath': f'{sys_pkg}.{name}'}})
    got = [e['emitterName'] for e in summary.get('emitters', [])]
    return got == [e[0] for e in expected_emitters]


def _stamp_system(sys_pkg):
    obj = C.load(sys_pkg)
    EAL.set_metadata_tag(obj, SYS_TAG, SYS_VERSION)


def _reset_system_emitters(report, sys_name, emitter_specs):
    """Ensure NiagaraSystem exists and has exact clean emitters from emitter_specs."""
    C.ensure_dir(C.NS_DIR)
    sys_pkg = f'{C.NS_DIR}/{sys_name}'
    sys_ref = f'{sys_pkg}.{sys_name}'

    if not C.asset_exists(sys_pkg):
        vibeue.exec_tool(NTS, 'CreateNiagaraSystem', {
            'assetName': sys_name,
            'assetPath': C.NS_DIR,
            'templateSystem': {'refPath': TMP_SYS_MINIMAL},
        })
        report.created(sys_pkg)
    else:
        report.info(f'Reconfiguring existing system {sys_pkg}')

    summary = vibeue.exec_tool(NTS, 'GetSystemSummary', {'system': {'refPath': sys_ref}})
    existing_names = [e['emitterName'] for e in summary.get('emitters', [])]

    for old_em in existing_names:
        vibeue.exec_tool(NTS, 'RemoveEmitter', {
            'emitterRef': {'system': {'refPath': sys_ref}, 'emitterName': old_em}
        })

    for em_name, em_tmp in emitter_specs:
        vibeue.exec_tool(NTS, 'AddEmitter', {
            'system': {'refPath': sys_ref},
            'templateEmitter': {'refPath': em_tmp},
            'emitterName': em_name,
        })
    return sys_pkg, sys_ref


def _configure_omni_common(
    sys_ref, em_name, count, life_min, life_max,
    sphere_radius=20.0, shape_scale=(1.0, 1.0, 1.0),
    vel_min=50.0, vel_max=200.0,
    gravity=(0.0, 0.0, 0.0), drag=1.5,
    size_curve=None, alpha_curve=None,
    loop_duration=2.0,
):
    _set_input(sys_ref, em_name, 'EmitterUpdateScript', 'EmitterState', 'Loop Duration', _val_float(loop_duration))
    _set_input(sys_ref, em_name, 'EmitterUpdateScript', 'SpawnBurst_Instantaneous', 'Spawn Count', _val_int(count))
    _set_input(sys_ref, em_name, 'ParticleSpawnScript', 'InitializeParticle', 'Lifetime Min', _val_float(life_min))
    _set_input(sys_ref, em_name, 'ParticleSpawnScript', 'InitializeParticle', 'Lifetime Max', _val_float(life_max))
    _set_input(sys_ref, em_name, 'ParticleSpawnScript', 'ShapeLocation', 'Sphere Radius', _val_float(sphere_radius))
    if shape_scale != (1.0, 1.0, 1.0):
        _set_input(
            sys_ref, em_name, 'ParticleSpawnScript', 'ShapeLocation', 'Non Uniform Scale',
            _val_vec3(*shape_scale)
        )
    _set_input(sys_ref, em_name, 'ParticleSpawnScript', 'AddVelocity', 'Origin Offset', _val_vec3(0.0, 0.0, 0.0))
    _set_input(sys_ref, em_name, 'ParticleSpawnScript', 'AddVelocity', ['Velocity Speed', 'Minimum'], _val_float(vel_min))
    _set_input(sys_ref, em_name, 'ParticleSpawnScript', 'AddVelocity', ['Velocity Speed', 'Maximum'], _val_float(vel_max))
    _set_input(sys_ref, em_name, 'ParticleUpdateScript', 'GravityForce', 'Gravity', _val_vec3(*gravity))
    _set_input(sys_ref, em_name, 'ParticleUpdateScript', 'Drag', 'Drag', _val_float(drag))
    if size_curve:
        _set_input(
            sys_ref, em_name, 'ParticleUpdateScript', 'ScaleSpriteSize',
            ['Scale Factor', 'Value', 'FloatCurve'], _val_curve(size_curve)
        )
    if alpha_curve:
        _set_input(
            sys_ref, em_name, 'ParticleUpdateScript', 'ScaleColor',
            ['Scale Alpha', 'FloatCurve'], _val_curve(alpha_curve)
        )


def _set_color_direct(sys_ref, em_name, rgba):
    _set_input(
        sys_ref, em_name, 'ParticleSpawnScript', 'InitializeParticle', 'Color Mode',
        _val_enum('/Niagara/Enums/ENiagara_ColorInitializationMode.ENiagara_ColorInitializationMode', 'NewEnumerator1')
    )
    _set_input(sys_ref, em_name, 'ParticleSpawnScript', 'InitializeParticle', 'Color', _val_color(*rgba))


def _set_color_range(sys_ref, em_name, rgba_min, rgba_max):
    _set_input(
        sys_ref, em_name, 'ParticleSpawnScript', 'InitializeParticle', 'Color Mode',
        _val_enum('/Niagara/Enums/ENiagara_ColorInitializationMode.ENiagara_ColorInitializationMode', 'NewEnumerator2')
    )
    _set_input(sys_ref, em_name, 'ParticleSpawnScript', 'InitializeParticle', 'Color Minimum', _val_color(*rgba_min))
    _set_input(sys_ref, em_name, 'ParticleSpawnScript', 'InitializeParticle', 'Color Maximum', _val_color(*rgba_max))


def _set_sprite_uniform_range(sys_ref, em_name, smin, smax, rot_min=0.0, rot_max=360.0):
    _set_input(
        sys_ref, em_name, 'ParticleSpawnScript', 'InitializeParticle', 'Sprite Size Mode',
        _val_enum('/Niagara/Enums/ENiagara_SizeScaleMode.ENiagara_SizeScaleMode', 'NewEnumerator1')
    )
    _set_input(sys_ref, em_name, 'ParticleSpawnScript', 'InitializeParticle', 'Uniform Sprite Size Min', _val_float(smin))
    _set_input(sys_ref, em_name, 'ParticleSpawnScript', 'InitializeParticle', 'Uniform Sprite Size Max', _val_float(smax))
    _set_input(sys_ref, em_name, 'ParticleSpawnScript', 'InitializeParticle', 'Sprite Rotation Angle Min', _val_float(rot_min))
    _set_input(sys_ref, em_name, 'ParticleSpawnScript', 'InitializeParticle', 'Sprite Rotation Angle Max', _val_float(rot_max))


def _set_sprite_nonuniform_range(sys_ref, em_name, min_xy, max_xy):
    _set_input(
        sys_ref, em_name, 'ParticleSpawnScript', 'InitializeParticle', 'Sprite Size Mode',
        _val_enum('/Niagara/Enums/ENiagara_SizeScaleMode.ENiagara_SizeScaleMode', 'NewEnumerator2')
    )
    _set_input(sys_ref, em_name, 'ParticleSpawnScript', 'InitializeParticle', 'Sprite Size Min', _val_vec2(*min_xy))
    _set_input(sys_ref, em_name, 'ParticleSpawnScript', 'InitializeParticle', 'Sprite Size Max', _val_vec2(*max_xy))


# --------------------------------------------------------------------------------------
# Build the 6 Niagara Systems
# --------------------------------------------------------------------------------------
def build_systems(report, mis):
    expected_all = {
        'Impact': ('NS_IceSlash_Impact', [('BlueInkSplash',), ('HeroBeams',), ('RadialRays',), ('StarburstCore',), ('WhiteCoreFlash',), ('HitSparks',)]),
        'Smoke': ('NS_IceSlash_Smoke', [('MistPuffs',)]),
        'Snow': ('NS_IceSlash_Snow', [('FrostDustArc',), ('HexSnowflakes',), ('GoldStars',), ('InkStars',)]),
        'GroundFlash': ('NS_IceSlash_GroundFlash', [('SnowDomeFlash',), ('GroundSnowDisc',), ('GroundLightRays',), ('BigStarburst',), ('BigWhiteCore',)]),
        'Debris': ('NS_IceSlash_Debris', [('IceShardBurst',), ('BurstStreaks',)]),
        'Shockwave': ('NS_IceSlash_Shockwave', [('ShockwaveOuter',), ('ShockwaveInner',)]),
        'GroundBrush': ('NS_IceSlash_GroundBrush', [('BrushStrip',), ('GroundSlashRays',)]),
    }
    if not REBUILD_SYSTEMS and all(_system_is_current(f'{C.NS_DIR}/{v[0]}', v[1]) for v in expected_all.values()):
        for v in expected_all.values():
            report.skipped(f'{C.NS_DIR}/{v[0]}', f'system {SYS_VERSION} up to date')
        return {k: f'{C.NS_DIR}/{v[0]}' for k, v in expected_all.items()}

    built = {}

    # 1. NS_IceSlash_Impact (Layers 3 & 4: blade-head starburst 150-260cm + white core + blue ink splash + 200-500cm radial rays)
    with report.step('NS_IceSlash_Impact'):
        pkg, ref = _reset_system_emitters(report, 'NS_IceSlash_Impact', [
            ('BlueInkSplash', TMP_EM_OMNI),
            ('HeroBeams', TMP_EM_OMNI),
            ('RadialRays', TMP_EM_OMNI),
            ('StarburstCore', TMP_EM_OMNI),
            ('WhiteCoreFlash', TMP_EM_OMNI),
            ('HitSparks', TMP_EM_OMNI),
        ])
        # BlueInkSplash (jagged deep-blue brush splash behind yellow starburst)
        _configure_omni_common(
            ref, 'BlueInkSplash', count=4, life_min=0.22, life_max=0.32,
            sphere_radius=12.0, vel_min=220.0, vel_max=480.0, gravity=(0, 0, 0), drag=3.0,
            size_curve=[(0.0, 0.45), (0.30, 1.05), (1.0, 0.35)],
            alpha_curve=[(0.0, 0.95), (0.50, 0.75), (1.0, 0.0)],
            loop_duration=0.7,
        )
        _set_color_range(ref, 'BlueInkSplash', (0.04, 0.25, 0.78, 0.92), (0.15, 0.65, 1.0, 0.95))
        _set_sprite_nonuniform_range(ref, 'BlueInkSplash', (65.0, 190.0), (95.0, 310.0))
        _update_sprite_renderer(ref, 'BlueInkSplash', mis['GroundStreak'], 'VelocityAligned', 'FaceCamera', pivot=(0.5, 0.42), sort_hint=8)

        # HeroBeams (2-3 bold cyan #6fe8ff & gold #ffd25a slash beams, 340-520cm long)
        _configure_omni_common(
            ref, 'HeroBeams', count=3, life_min=0.18, life_max=0.28,
            sphere_radius=8.0, shape_scale=(1.0, 1.0, 0.35),
            vel_min=450.0, vel_max=850.0, gravity=(0, 0, 0), drag=2.8,
            size_curve=[(0.0, 0.50), (0.28, 1.12), (1.0, 0.15)],
            alpha_curve=[(0.0, 1.0), (0.42, 0.90), (1.0, 0.0)],
            loop_duration=0.7,
        )
        _set_color_range(ref, 'HeroBeams', (0.43, 0.91, 1.0, 1.0), (1.0, 0.82, 0.35, 1.0))
        _set_sprite_nonuniform_range(ref, 'HeroBeams', (18.0, 340.0), (28.0, 520.0))
        _update_sprite_renderer(ref, 'HeroBeams', mis['LightRay'], 'VelocityAligned', 'FaceCamera', pivot=(0.5, 0.36), sort_hint=18)

        # RadialRays (Layer 4: 9 thin rays, 7-14cm wide, 210-480cm long, cyan #6fe8ff / white / gold #ffd25a, 0.16-0.29s)
        _configure_omni_common(
            ref, 'RadialRays', count=9, life_min=0.16, life_max=0.29,
            sphere_radius=12.0, vel_min=420.0, vel_max=920.0, gravity=(0, 0, 0), drag=2.5,
            size_curve=[(0.0, 0.55), (0.26, 1.15), (1.0, 0.18)],
            alpha_curve=[(0.0, 1.0), (0.38, 0.88), (1.0, 0.0)],
            loop_duration=0.7,
        )
        _set_color_range(ref, 'RadialRays', (0.43, 0.91, 1.0, 1.0), (1.0, 0.82, 0.35, 1.0))
        _set_sprite_nonuniform_range(ref, 'RadialRays', (7.0, 210.0), (14.0, 480.0))
        _update_sprite_renderer(ref, 'RadialRays', mis['LightRay'], 'VelocityAligned', 'FaceCamera', pivot=(0.5, 0.32), sort_hint=20)

        # StarburstCore (Layer 3: 1 starburst 210-255cm, 0.12s grow -> 0.15s shrink disappear)
        _configure_omni_common(
            ref, 'StarburstCore', count=1, life_min=0.26, life_max=0.28,
            sphere_radius=2.0, vel_min=0.0, vel_max=3.0, gravity=(0, 0, 0), drag=1.0,
            size_curve=[(0.0, 0.25), (0.44, 1.05), (1.0, 0.08)],
            alpha_curve=[(0.0, 1.0), (0.55, 0.95), (1.0, 0.0)],
            loop_duration=0.7,
        )
        _set_color_direct(ref, 'StarburstCore', (1.0, 0.95, 0.65, 1.0))
        _set_sprite_uniform_range(ref, 'StarburstCore', 210.0, 255.0, 0.0, 360.0)
        _update_sprite_renderer(ref, 'StarburstCore', mis['ImpactStarburst'], 'Unaligned', 'FaceCamera', sort_hint=25)

        # WhiteCoreFlash (hot white core flash inside StarburstCore)
        _configure_omni_common(
            ref, 'WhiteCoreFlash', count=1, life_min=0.18, life_max=0.22,
            sphere_radius=1.0, vel_min=0.0, vel_max=2.0, gravity=(0, 0, 0), drag=1.0,
            size_curve=[(0.0, 0.35), (0.40, 1.05), (1.0, 0.05)],
            alpha_curve=[(0.0, 1.0), (0.50, 0.92), (1.0, 0.0)],
            loop_duration=0.7,
        )
        _set_color_direct(ref, 'WhiteCoreFlash', (1.0, 1.0, 1.0, 1.0))
        _set_sprite_uniform_range(ref, 'WhiteCoreFlash', 120.0, 145.0, 0.0, 360.0)
        _update_sprite_renderer(ref, 'WhiteCoreFlash', mis['ImpactStarburst'], 'Unaligned', 'FaceCamera', sort_hint=30)

        # HitSparks
        _configure_omni_common(
            ref, 'HitSparks', count=10, life_min=0.22, life_max=0.36,
            sphere_radius=16.0, vel_min=420.0, vel_max=920.0, gravity=(0, 0, -420.0), drag=2.8,
            size_curve=[(0.0, 0.7), (0.3, 1.1), (1.0, 0.0)],
            alpha_curve=[(0.0, 1.0), (0.6, 0.85), (1.0, 0.0)],
            loop_duration=0.7,
        )
        _set_color_range(ref, 'HitSparks', (0.75, 0.95, 1.0, 1.0), (1.0, 0.88, 0.38, 1.0))
        _set_sprite_uniform_range(ref, 'HitSparks', 18.0, 34.0, -15.0, 15.0)
        _update_sprite_renderer(ref, 'HitSparks', mis['GoldStar'], 'Unaligned', 'FaceCamera', sort_hint=22)
        built['Impact'] = pkg

    # 2. NS_IceSlash_Smoke (3.25s landing burst: 11 large mist puffs 210-340cm, #9fb4c8, soft DepthFade)
    with report.step('NS_IceSlash_Smoke'):
        pkg, ref = _reset_system_emitters(report, 'NS_IceSlash_Smoke', [
            ('MistPuffs', TMP_EM_OMNI),
        ])
        _configure_omni_common(
            ref, 'MistPuffs', count=11, life_min=0.70, life_max=1.05,
            sphere_radius=110.0, shape_scale=(1.65, 1.65, 0.35),
            vel_min=110.0, vel_max=260.0, gravity=(0.0, 0.0, 45.0), drag=2.6,
            size_curve=[(0.0, 0.55), (0.32, 1.0), (1.0, 1.32)],
            alpha_curve=[(0.0, 0.0), (0.14, 0.72), (0.55, 0.48), (1.0, 0.0)],
            loop_duration=1.4,
        )
        _set_input(ref, 'MistPuffs', 'ParticleSpawnScript', 'InitializeParticle', 'UsePositionOffset', _val_bool(True))
        _set_input(ref, 'MistPuffs', 'ParticleSpawnScript', 'InitializeParticle', 'Position Offset', _val_vec3(0.0, 0.0, 70.0))
        _set_color_range(ref, 'MistPuffs', (0.56, 0.68, 0.78, 0.65), (0.74, 0.84, 0.93, 0.80))
        _set_sprite_uniform_range(ref, 'MistPuffs', 210.0, 340.0, 0.0, 360.0)
        _update_sprite_renderer(ref, 'MistPuffs', mis['SmokePuff'], 'Unaligned', 'FaceCamera', sort_hint=4)
        built['Smoke'] = pkg

    # 3. NS_IceSlash_Snow (Layer 2: 95 frost specks 4.5-10cm + Layer 5: 9 hex snowflakes 32-58cm + 4 gold stars + 3 ink stars)
    with report.step('NS_IceSlash_Snow'):
        pkg, ref = _reset_system_emitters(report, 'NS_IceSlash_Snow', [
            ('FrostDustArc', TMP_EM_OMNI),
            ('HexSnowflakes', TMP_EM_OMNI),
            ('GoldStars', TMP_EM_OMNI),
            ('InkStars', TMP_EM_OMNI),
        ])
        # FrostDustArc (Layer 2: 95 glowing white specks 4.5-10cm across arc disc, flung outward 0.5-0.8s)
        _configure_omni_common(
            ref, 'FrostDustArc', count=95, life_min=0.50, life_max=0.82,
            sphere_radius=225.0, shape_scale=(1.0, 1.0, 0.25),
            vel_min=95.0, vel_max=260.0, gravity=(0.0, 0.0, -35.0), drag=2.2,
            size_curve=[(0.0, 0.6), (0.20, 1.05), (0.75, 0.85), (1.0, 0.0)],
            alpha_curve=[(0.0, 0.0), (0.10, 1.0), (0.72, 0.90), (1.0, 0.0)],
            loop_duration=1.8,
        )
        _set_color_range(ref, 'FrostDustArc', (0.72, 0.94, 1.0, 0.95), (1.0, 1.0, 1.0, 1.0))
        _set_sprite_uniform_range(ref, 'FrostDustArc', 4.5, 10.0, 0.0, 360.0)
        _update_sprite_renderer(ref, 'FrostDustArc', mis['FrostSpeck'], 'Unaligned', 'FaceCamera', sort_hint=12)

        # HexSnowflakes (Layer 5a: 9 snowflakes 32-58cm, slow rotation/drift 1.0-1.45s)
        _configure_omni_common(
            ref, 'HexSnowflakes', count=9, life_min=1.00, life_max=1.45,
            sphere_radius=205.0, shape_scale=(1.0, 1.0, 0.35),
            vel_min=35.0, vel_max=115.0, gravity=(0.0, 0.0, -40.0), drag=2.8,
            size_curve=[(0.0, 0.30), (0.15, 1.0), (0.80, 0.95), (1.0, 0.0)],
            alpha_curve=[(0.0, 0.0), (0.12, 1.0), (0.78, 0.88), (1.0, 0.0)],
            loop_duration=1.8,
        )
        _set_color_direct(ref, 'HexSnowflakes', (0.94, 0.99, 1.0, 1.0))
        _set_sprite_uniform_range(ref, 'HexSnowflakes', 32.0, 58.0, 0.0, 360.0)
        _update_sprite_renderer(ref, 'HexSnowflakes', mis['Snowflake'], 'Unaligned', 'FaceCamera', sort_hint=14)

        # GoldStars (Layer 5b: 4 upright 4-pt gold stars, crisp twinkle)
        _configure_omni_common(
            ref, 'GoldStars', count=4, life_min=0.35, life_max=0.72,
            sphere_radius=200.0, shape_scale=(1.0, 1.0, 0.35),
            vel_min=25.0, vel_max=85.0, gravity=(0.0, 0.0, -15.0), drag=3.2,
            size_curve=[(0.0, 0.0), (0.22, 1.18), (0.55, 0.72), (0.80, 1.02), (1.0, 0.0)],
            alpha_curve=[(0.0, 0.0), (0.12, 1.0), (0.82, 0.92), (1.0, 0.0)],
            loop_duration=1.8,
        )
        _set_color_direct(ref, 'GoldStars', (1.0, 0.90, 0.42, 1.0))
        _set_sprite_uniform_range(ref, 'GoldStars', 28.0, 48.0, -8.0, 8.0)
        _update_sprite_renderer(ref, 'GoldStars', mis['GoldStar'], 'Unaligned', 'FaceCamera', sort_hint=16)

        # InkStars (dark navy/black 4-pt stars seen in ref_02.00 & ref_02.25)
        _configure_omni_common(
            ref, 'InkStars', count=3, life_min=0.45, life_max=0.85,
            sphere_radius=190.0, shape_scale=(1.0, 1.0, 0.35),
            vel_min=20.0, vel_max=70.0, gravity=(0.0, 0.0, -10.0), drag=3.2,
            size_curve=[(0.0, 0.0), (0.20, 1.05), (0.80, 0.90), (1.0, 0.0)],
            alpha_curve=[(0.0, 0.0), (0.15, 0.95), (0.80, 0.85), (1.0, 0.0)],
            loop_duration=1.8,
        )
        _set_color_direct(ref, 'InkStars', (0.01, 0.03, 0.10, 0.95))
        _set_sprite_uniform_range(ref, 'InkStars', 24.0, 38.0, -6.0, 6.0)
        _update_sprite_renderer(ref, 'InkStars', mis['GoldStar'], 'Unaligned', 'FaceCamera', sort_hint=15)
        built['Snow'] = pkg

    # 4. NS_IceSlash_GroundFlash (3.25s landing snow-dome + giant starburst + upward-outward crown rays + ground disc)
    with report.step('NS_IceSlash_GroundFlash'):
        pkg, ref = _reset_system_emitters(report, 'NS_IceSlash_GroundFlash', [
            ('SnowDomeFlash', TMP_EM_OMNI),
            ('GroundSnowDisc', TMP_EM_MESH),
            ('GroundLightRays', TMP_EM_OMNI),
            ('BigStarburst', TMP_EM_OMNI),
            ('BigWhiteCore', TMP_EM_OMNI),
        ])
        # SnowDomeFlash
        _configure_omni_common(
            ref, 'SnowDomeFlash', count=2, life_min=0.34, life_max=0.42,
            sphere_radius=12.0, vel_min=0.0, vel_max=10.0, gravity=(0, 0, 0), drag=1.0,
            size_curve=[(0.0, 0.35), (0.24, 1.05), (1.0, 1.28)],
            alpha_curve=[(0.0, 1.0), (0.38, 0.88), (1.0, 0.0)],
            loop_duration=0.9,
        )
        _set_input(ref, 'SnowDomeFlash', 'ParticleSpawnScript', 'InitializeParticle', 'UsePositionOffset', _val_bool(True))
        _set_input(ref, 'SnowDomeFlash', 'ParticleSpawnScript', 'InitializeParticle', 'Position Offset', _val_vec3(0.0, 0.0, 95.0))
        _set_color_direct(ref, 'SnowDomeFlash', (0.95, 0.99, 1.0, 0.96))
        _set_sprite_uniform_range(ref, 'SnowDomeFlash', 450.0, 530.0, 0.0, 360.0)
        _update_sprite_renderer(ref, 'SnowDomeFlash', mis['SnowDome'], 'Unaligned', 'FaceCamera', sort_hint=5)

        # GroundSnowDisc (flat horizontal Plane mesh on floor)
        _set_input(ref, 'GroundSnowDisc', 'EmitterUpdateScript', 'EmitterState', 'Loop Duration', _val_float(0.9))
        _set_input(ref, 'GroundSnowDisc', 'EmitterUpdateScript', 'SpawnBurst_Instantaneous', 'Spawn Count', _val_int(1))
        _set_input(ref, 'GroundSnowDisc', 'ParticleSpawnScript', 'InitializeParticle', 'Lifetime Min', _val_float(0.50))
        _set_input(ref, 'GroundSnowDisc', 'ParticleSpawnScript', 'InitializeParticle', 'Lifetime Max', _val_float(0.55))
        _set_input(ref, 'GroundSnowDisc', 'ParticleSpawnScript', 'InitializeParticle', 'UsePositionOffset', _val_bool(True))
        _set_input(ref, 'GroundSnowDisc', 'ParticleSpawnScript', 'InitializeParticle', 'Position Offset', _val_vec3(0.0, 0.0, 3.0))
        _set_color_direct(ref, 'GroundSnowDisc', (0.92, 0.98, 1.0, 0.94))
        _set_input(ref, 'GroundSnowDisc', 'ParticleSpawnScript', 'InitializeParticle', 'Mesh Uniform Scale Min', _val_float(6.6))
        _set_input(ref, 'GroundSnowDisc', 'ParticleSpawnScript', 'InitializeParticle', 'Mesh Uniform Scale Max', _val_float(7.0))
        _set_input(ref, 'GroundSnowDisc', 'ParticleSpawnScript', 'AddVelocity', ['Velocity Speed', 'Minimum'], _val_float(0.0))
        _set_input(ref, 'GroundSnowDisc', 'ParticleSpawnScript', 'AddVelocity', ['Velocity Speed', 'Maximum'], _val_float(0.1))
        _set_input(
            ref, 'GroundSnowDisc', 'ParticleUpdateScript', 'ScaleMeshSize',
            ['Scale Factor', 'Value', 'FloatCurve'],
            _val_curve([(0.0, 0.25), (0.28, 0.95), (1.0, 1.18)]),
        )
        _set_input(
            ref, 'GroundSnowDisc', 'ParticleUpdateScript', 'ScaleColor',
            ['Scale Alpha', 'FloatCurve'],
            _val_curve([(0.0, 0.95), (0.45, 0.75), (1.0, 0.0)]),
        )
        _update_mesh_renderer(
            ref, 'GroundSnowDisc', ['/Engine/BasicShapes/Plane.Plane'],
            mis['SnowDome'], facing='Default', mesh_scale=(1.0, 1.0, 1.0), sort_hint=3
        )

        # GroundLightRays (upward-outward crown fan via Origin Offset (0,0,-85) matching ref_03.25.jpg)
        _configure_omni_common(
            ref, 'GroundLightRays', count=20, life_min=0.26, life_max=0.40,
            sphere_radius=85.0, shape_scale=(1.0, 1.0, 0.22),
            vel_min=580.0, vel_max=1180.0, gravity=(0, 0, 0), drag=2.4,
            size_curve=[(0.0, 0.50), (0.25, 1.15), (1.0, 0.20)],
            alpha_curve=[(0.0, 1.0), (0.42, 0.88), (1.0, 0.0)],
            loop_duration=0.9,
        )
        _set_input(ref, 'GroundLightRays', 'ParticleSpawnScript', 'AddVelocity', 'Origin Offset', _val_vec3(0.0, 0.0, -85.0))
        _set_input(ref, 'GroundLightRays', 'ParticleSpawnScript', 'InitializeParticle', 'UsePositionOffset', _val_bool(True))
        _set_input(ref, 'GroundLightRays', 'ParticleSpawnScript', 'InitializeParticle', 'Position Offset', _val_vec3(0.0, 0.0, 35.0))
        _set_color_range(ref, 'GroundLightRays', (0.42, 0.92, 1.0, 1.0), (1.0, 0.92, 0.52, 1.0))
        _set_sprite_nonuniform_range(ref, 'GroundLightRays', (24.0, 420.0), (54.0, 760.0))
        _update_sprite_renderer(ref, 'GroundLightRays', mis['LightRay'], 'VelocityAligned', 'FaceCamera', pivot=(0.5, 0.30), sort_hint=20)

        # BigStarburst (renders IN FRONT of SnowDomeFlash via SortOrderHint=25)
        _configure_omni_common(
            ref, 'BigStarburst', count=2, life_min=0.26, life_max=0.32,
            sphere_radius=8.0, vel_min=0.0, vel_max=6.0, gravity=(0, 0, 0), drag=1.0,
            size_curve=[(0.0, 0.45), (0.26, 1.18), (1.0, 0.65)],
            alpha_curve=[(0.0, 1.0), (0.48, 0.95), (1.0, 0.0)],
            loop_duration=0.9,
        )
        _set_input(ref, 'BigStarburst', 'ParticleSpawnScript', 'InitializeParticle', 'UsePositionOffset', _val_bool(True))
        _set_input(ref, 'BigStarburst', 'ParticleSpawnScript', 'InitializeParticle', 'Position Offset', _val_vec3(0.0, 0.0, 110.0))
        _set_color_direct(ref, 'BigStarburst', (1.0, 0.96, 0.72, 1.0))
        _set_sprite_uniform_range(ref, 'BigStarburst', 500.0, 600.0, -25.0, 25.0)
        _update_sprite_renderer(ref, 'BigStarburst', mis['ImpactStarburst'], 'Unaligned', 'FaceCamera', sort_hint=25)

        # BigWhiteCore
        _configure_omni_common(
            ref, 'BigWhiteCore', count=1, life_min=0.20, life_max=0.25,
            sphere_radius=2.0, vel_min=0.0, vel_max=2.0, gravity=(0, 0, 0), drag=1.0,
            size_curve=[(0.0, 0.45), (0.30, 1.10), (1.0, 0.30)],
            alpha_curve=[(0.0, 1.0), (0.50, 0.92), (1.0, 0.0)],
            loop_duration=0.9,
        )
        _set_input(ref, 'BigWhiteCore', 'ParticleSpawnScript', 'InitializeParticle', 'UsePositionOffset', _val_bool(True))
        _set_input(ref, 'BigWhiteCore', 'ParticleSpawnScript', 'InitializeParticle', 'Position Offset', _val_vec3(0.0, 0.0, 105.0))
        _set_color_direct(ref, 'BigWhiteCore', (1.0, 1.0, 1.0, 1.0))
        _set_sprite_uniform_range(ref, 'BigWhiteCore', 290.0, 330.0, 0.0, 360.0)
        _update_sprite_renderer(ref, 'BigWhiteCore', mis['ImpactStarburst'], 'Unaligned', 'FaceCamera', sort_hint=30)
        built['GroundFlash'] = pkg

    # 5. NS_IceSlash_Debris (3.50s flying cel-shaded ice shard meshes + radial burst streaks)
    with report.step('NS_IceSlash_Debris'):
        pkg, ref = _reset_system_emitters(report, 'NS_IceSlash_Debris', [
            ('IceShardBurst', TMP_EM_MESH),
            ('BurstStreaks', TMP_EM_OMNI),
        ])
        debris_candidates = [
            f'{C.CLUSTER_DIR}/SM_IceDebris_01.SM_IceDebris_01',
            f'{C.CLUSTER_DIR}/SM_IceDebris_02.SM_IceDebris_02',
            f'{C.CLUSTER_DIR}/SM_IceDebris_03.SM_IceDebris_03',
            f'{C.MESH_DIR}/SM_IceDebris_01.SM_IceDebris_01',
            f'{C.MESH_DIR}/SM_IceDebris_02.SM_IceDebris_02',
            f'{C.MESH_DIR}/SM_IceDebris_03.SM_IceDebris_03',
        ]
        found_debris = [p for p in debris_candidates if C.asset_exists(p.split('.')[0])]
        if found_debris:
            mesh_refs = found_debris
            base_mesh_scale = (1.0, 1.0, 1.0)
            base_mesh_rot = (0.0, 0.0, 0.0)
            s_min, s_max = 0.85, 1.55
        else:
            mesh_refs = ['/Engine/BasicShapes/Cube.Cube']
            base_mesh_scale = (0.56, 0.24, 0.18)  # chunky faceted cel-shaded ice polyhedron
            base_mesh_rot = (18.0, 12.0, 42.0)
            s_min, s_max = 0.75, 1.55

        _set_input(ref, 'IceShardBurst', 'EmitterUpdateScript', 'EmitterState', 'Loop Duration', _val_float(1.2))
        _set_input(ref, 'IceShardBurst', 'EmitterUpdateScript', 'SpawnBurst_Instantaneous', 'Spawn Count', _val_int(20))
        _set_input(ref, 'IceShardBurst', 'ParticleSpawnScript', 'InitializeParticle', 'Lifetime Min', _val_float(0.52))
        _set_input(ref, 'IceShardBurst', 'ParticleSpawnScript', 'InitializeParticle', 'Lifetime Max', _val_float(0.90))
        _set_color_range(ref, 'IceShardBurst', (0.72, 0.92, 1.0, 1.0), (1.0, 1.0, 1.0, 1.0))
        _set_input(ref, 'IceShardBurst', 'ParticleSpawnScript', 'InitializeParticle', 'Mesh Uniform Scale Min', _val_float(s_min))
        _set_input(ref, 'IceShardBurst', 'ParticleSpawnScript', 'InitializeParticle', 'Mesh Uniform Scale Max', _val_float(s_max))
        if len(mesh_refs) > 1:
            _set_input(
                ref, 'IceShardBurst', 'ParticleSpawnScript', 'InitializeParticle',
                'Mesh Renderer Array Visibility Mode',
                _val_enum('/Niagara/Enums/Ribbons/ENiagara_UnsetDirectSetRandom.ENiagara_UnsetDirectSetRandom', 'NewEnumerator3')
            )

        _set_input(ref, 'IceShardBurst', 'ParticleSpawnScript', 'AddVelocity', 'Cone Axis', _val_vec3(0.0, 0.0, 1.0))
        _set_input(ref, 'IceShardBurst', 'ParticleSpawnScript', 'AddVelocity', 'Cone Angle', _val_float(122.0))
        _set_input(ref, 'IceShardBurst', 'ParticleSpawnScript', 'AddVelocity', 'Inner Cone Angle', _val_float(34.0))
        _set_input(ref, 'IceShardBurst', 'ParticleSpawnScript', 'AddVelocity', ['Velocity Speed', 'Minimum'], _val_float(720.0))
        _set_input(ref, 'IceShardBurst', 'ParticleSpawnScript', 'AddVelocity', ['Velocity Speed', 'Maximum'], _val_float(1280.0))

        vibeue.exec_tool(NTS, 'AddModule', {
            'moduleLocationRef': {'system': {'refPath': ref}, 'emitterName': 'IceShardBurst', 'scriptName': 'ParticleSpawnScript'},
            'moduleAsset': {'refPath': MOD_SHAPELOC},
        })
        _set_input(ref, 'IceShardBurst', 'ParticleSpawnScript', 'ShapeLocation', 'Sphere Radius', _val_float(110.0))
        _set_input(
            ref, 'IceShardBurst', 'ParticleSpawnScript', 'ShapeLocation', 'Scale Mode',
            _val_enum('/Niagara/Enums/Transforms/ENiagara_ScaleMode.ENiagara_ScaleMode', 'NewEnumerator0')
        )
        _set_input(ref, 'IceShardBurst', 'ParticleSpawnScript', 'ShapeLocation', 'Non Uniform Scale', _val_vec3(1.0, 1.0, 0.55))

        vibeue.exec_tool(NTS, 'AddModule', {
            'moduleLocationRef': {
                'system': {'refPath': ref},
                'emitterName': 'IceShardBurst',
                'scriptName': 'ParticleUpdateScript',
                'moduleName': 'SolveForcesAndVelocity',
            },
            'moduleAsset': {'refPath': MOD_GRAVITY},
        })
        _set_input(ref, 'IceShardBurst', 'ParticleUpdateScript', 'GravityForce', 'Gravity', _val_vec3(0.0, 0.0, -1350.0))

        _set_input(
            ref, 'IceShardBurst', 'ParticleUpdateScript', 'ScaleMeshSize',
            ['Scale Factor', 'Value', 'FloatCurve'],
            _val_curve([(0.0, 0.65), (0.12, 1.0), (0.78, 0.90), (1.0, 0.0)]),
        )
        _set_input(
            ref, 'IceShardBurst', 'ParticleUpdateScript', 'ScaleColor',
            ['Scale Alpha', 'FloatCurve'],
            _val_curve([(0.0, 1.0), (0.80, 1.0), (1.0, 0.0)]),
        )
        _update_mesh_renderer(
            ref, 'IceShardBurst', mesh_refs,
            mis['DebrisToon'], facing='Velocity', mesh_scale=base_mesh_scale, mesh_rot=base_mesh_rot, sort_hint=18
        )

        # BurstStreaks (crisp white/cyan lines shooting out between erupting crystals in ref_03.50.jpg)
        _configure_omni_common(
            ref, 'BurstStreaks', count=16, life_min=0.22, life_max=0.38,
            sphere_radius=85.0, shape_scale=(1.0, 1.0, 0.55),
            vel_min=550.0, vel_max=1150.0, gravity=(0, 0, 0), drag=2.5,
            size_curve=[(0.0, 0.50), (0.25, 1.15), (1.0, 0.15)],
            alpha_curve=[(0.0, 1.0), (0.45, 0.85), (1.0, 0.0)],
            loop_duration=1.2,
        )
        _set_input(ref, 'BurstStreaks', 'ParticleSpawnScript', 'AddVelocity', 'Origin Offset', _val_vec3(0.0, 0.0, -70.0))
        _set_color_range(ref, 'BurstStreaks', (0.65, 0.95, 1.0, 1.0), (1.0, 1.0, 1.0, 1.0))
        _set_sprite_nonuniform_range(ref, 'BurstStreaks', (8.0, 180.0), (18.0, 360.0))
        _update_sprite_renderer(ref, 'BurstStreaks', mis['LightRay'], 'VelocityAligned', 'FaceCamera', pivot=(0.5, 0.35), sort_hint=22)
        built['Debris'] = pkg

    # 6. NS_IceSlash_Shockwave (3.25-3.75s horizontal expanding ground shockwave ring)
    with report.step('NS_IceSlash_Shockwave'):
        pkg, ref = _reset_system_emitters(report, 'NS_IceSlash_Shockwave', [
            ('ShockwaveOuter', TMP_EM_MESH),
            ('ShockwaveInner', TMP_EM_MESH),
        ])
        for em_name, life, max_scale, curve_pts, col in [
            ('ShockwaveOuter', 0.48, 11.2, [(0.0, 0.14), (0.35, 0.72), (1.0, 1.0)], (0.82, 0.96, 1.0, 0.95)),
            ('ShockwaveInner', 0.56, 8.2, [(0.0, 0.12), (0.40, 0.68), (1.0, 1.0)], (0.62, 0.88, 1.0, 0.72)),
        ]:
            _set_input(ref, em_name, 'EmitterUpdateScript', 'EmitterState', 'Loop Duration', _val_float(0.8))
            _set_input(ref, em_name, 'EmitterUpdateScript', 'SpawnBurst_Instantaneous', 'Spawn Count', _val_int(1))
            _set_input(ref, em_name, 'ParticleSpawnScript', 'InitializeParticle', 'Lifetime Min', _val_float(life))
            _set_input(ref, em_name, 'ParticleSpawnScript', 'InitializeParticle', 'Lifetime Max', _val_float(life + 0.02))
            _set_input(ref, em_name, 'ParticleSpawnScript', 'InitializeParticle', 'UsePositionOffset', _val_bool(True))
            _set_input(ref, em_name, 'ParticleSpawnScript', 'InitializeParticle', 'Position Offset', _val_vec3(0.0, 0.0, 4.0))
            _set_color_direct(ref, em_name, col)
            _set_input(ref, em_name, 'ParticleSpawnScript', 'InitializeParticle', 'Mesh Uniform Scale Min', _val_float(max_scale))
            _set_input(ref, em_name, 'ParticleSpawnScript', 'InitializeParticle', 'Mesh Uniform Scale Max', _val_float(max_scale))
            _set_input(ref, em_name, 'ParticleSpawnScript', 'AddVelocity', ['Velocity Speed', 'Minimum'], _val_float(0.0))
            _set_input(ref, em_name, 'ParticleSpawnScript', 'AddVelocity', ['Velocity Speed', 'Maximum'], _val_float(0.1))
            _set_input(
                ref, em_name, 'ParticleUpdateScript', 'ScaleMeshSize',
                ['Scale Factor', 'Value', 'FloatCurve'], _val_curve(curve_pts)
            )
            _set_input(
                ref, em_name, 'ParticleUpdateScript', 'ScaleColor',
                ['Scale Alpha', 'FloatCurve'],
                _val_curve([(0.0, 0.95), (0.45, 0.68), (1.0, 0.0)]),
            )
            _update_mesh_renderer(
                ref, em_name, ['/Engine/BasicShapes/Plane.Plane'],
                mis['ShockwaveRing'], facing='Default', mesh_scale=(1.0, 1.0, 1.0), sort_hint=6
            )
        built['Shockwave'] = pkg

    # 7. NS_IceSlash_GroundBrush (Layer 6: deep-blue jagged brush strip on floor below each blade, 0.5s fade-out)
    with report.step('NS_IceSlash_GroundBrush'):
        pkg, ref = _reset_system_emitters(report, 'NS_IceSlash_GroundBrush', [
            ('BrushStrip', TMP_EM_MESH),
            ('GroundSlashRays', TMP_EM_OMNI),
        ])
        _set_input(ref, 'BrushStrip', 'EmitterUpdateScript', 'EmitterState', 'Loop Duration', _val_float(0.8))
        _set_input(ref, 'BrushStrip', 'EmitterUpdateScript', 'SpawnBurst_Instantaneous', 'Spawn Count', _val_int(1))
        _set_input(ref, 'BrushStrip', 'ParticleSpawnScript', 'InitializeParticle', 'Lifetime Min', _val_float(0.48))
        _set_input(ref, 'BrushStrip', 'ParticleSpawnScript', 'InitializeParticle', 'Lifetime Max', _val_float(0.52))
        _set_input(ref, 'BrushStrip', 'ParticleSpawnScript', 'InitializeParticle', 'UsePositionOffset', _val_bool(True))
        _set_input(ref, 'BrushStrip', 'ParticleSpawnScript', 'InitializeParticle', 'Position Offset', _val_vec3(0.0, 0.0, 3.0))
        _set_color_direct(ref, 'BrushStrip', (0.04, 0.22, 0.68, 0.92))
        _set_input(ref, 'BrushStrip', 'ParticleSpawnScript', 'InitializeParticle', 'Mesh Uniform Scale Min', _val_float(1.0))
        _set_input(ref, 'BrushStrip', 'ParticleSpawnScript', 'InitializeParticle', 'Mesh Uniform Scale Max', _val_float(1.0))
        _set_input(ref, 'BrushStrip', 'ParticleSpawnScript', 'AddVelocity', ['Velocity Speed', 'Minimum'], _val_float(0.0))
        _set_input(ref, 'BrushStrip', 'ParticleSpawnScript', 'AddVelocity', ['Velocity Speed', 'Maximum'], _val_float(0.1))
        _set_input(
            ref, 'BrushStrip', 'ParticleUpdateScript', 'ScaleMeshSize',
            ['Scale Factor', 'Value', 'FloatCurve'],
            _val_curve([(0.0, 0.55), (0.20, 1.0), (1.0, 1.05)]),
        )
        _set_input(
            ref, 'BrushStrip', 'ParticleUpdateScript', 'ScaleColor',
            ['Scale Alpha', 'FloatCurve'],
            _val_curve([(0.0, 0.95), (0.38, 0.80), (1.0, 0.0)]),
        )
        _update_mesh_renderer(
            ref, 'BrushStrip', ['/Engine/BasicShapes/Plane.Plane'],
            mis['GroundStreak'], facing='Default', mesh_scale=(4.6, 1.5, 1.0), sort_hint=2
        )

        # GroundSlashRays (low skimming cyan/gold streaks hugging the floor under the slash)
        _configure_omni_common(
            ref, 'GroundSlashRays', count=4, life_min=0.22, life_max=0.36,
            sphere_radius=35.0, shape_scale=(1.0, 1.0, 0.05),
            vel_min=380.0, vel_max=720.0, gravity=(0, 0, 0), drag=2.8,
            size_curve=[(0.0, 0.55), (0.25, 1.10), (1.0, 0.15)],
            alpha_curve=[(0.0, 1.0), (0.45, 0.85), (1.0, 0.0)],
            loop_duration=0.8,
        )
        _set_input(ref, 'GroundSlashRays', 'ParticleSpawnScript', 'InitializeParticle', 'UsePositionOffset', _val_bool(True))
        _set_input(ref, 'GroundSlashRays', 'ParticleSpawnScript', 'InitializeParticle', 'Position Offset', _val_vec3(0.0, 0.0, 12.0))
        _set_color_range(ref, 'GroundSlashRays', (0.38, 0.90, 1.0, 1.0), (1.0, 0.84, 0.35, 1.0))
        _set_sprite_nonuniform_range(ref, 'GroundSlashRays', (8.0, 220.0), (14.0, 420.0))
        _update_sprite_renderer(ref, 'GroundSlashRays', mis['LightRay'], 'VelocityAligned', 'FaceCamera', pivot=(0.5, 0.35), sort_hint=10)
        built['GroundBrush'] = pkg

    return built


# --------------------------------------------------------------------------------------
# Unified Single-System Builder: /Game/VFX/IceSlash/Niagara/NS_IceSlash_Skill
# (Strictly preserves Blade_* / Mist_* emitters owned by NobleShore; only manages
#  S1_..S5_ / Land_ / Burst_ emitters sequenced via SpawnBurst_Instantaneous Spawn Time)
# --------------------------------------------------------------------------------------
# Exact UE StaticMesh local-space coordinates measured from Saved/VFX/SlashSheets_v7_ue.fbx:
#   arc_center = centroid of outer rim, head_pos = UV1.x=1 blade head endpoint,
#   ray_pos = impact ray origin, ground_pos = floor projection (Z=3 cm).
SKILL_SLASH_TABLE = [
    {
        'prefix': 'S1',
        'spawn_time': 0.00,
        'impact_delay': 0.06,
        'arc_center': (95.0, 10.0, 68.0),
        'arc_radius': 225.0,
        'arc_shape': (1.0, 1.0, 0.28),
        'head_pos': (-55.0, 233.0, 102.0),
        'ray_pos': (-55.0, 233.0, 102.0),
        'ground_pos': (185.0, -60.0, 3.0),
        'ground_yaw': 85.0,
    },
    {
        'prefix': 'S2',
        'spawn_time': 0.50,
        'impact_delay': 0.06,
        'arc_center': (45.0, -75.0, 112.0),
        'arc_radius': 235.0,
        'arc_shape': (1.0, 1.0, 0.30),
        'head_pos': (-248.0, -78.0, 96.0),
        'ray_pos': (-248.0, -78.0, 96.0),
        'ground_pos': (145.0, -180.0, 3.0),
        'ground_yaw': -35.0,
    },
    {
        'prefix': 'S3',
        'spawn_time': 0.75,
        'impact_delay': 0.06,
        'arc_center': (15.0, -65.0, 48.0),
        'arc_radius': 265.0,
        'arc_shape': (1.0, 1.0, 0.24),
        'head_pos': (215.0, 195.0, 66.0),
        'ray_pos': (215.0, 195.0, 66.0),
        'ground_pos': (140.0, -210.0, 3.0),
        'ground_yaw': 35.0,
    },
    {
        'prefix': 'S4',
        'spawn_time': 1.25,
        'impact_delay': 0.06,
        'arc_center': (185.0, 35.0, 155.0),
        'arc_radius': 220.0,
        'arc_shape': (0.95, 0.28, 1.15),
        'head_pos': (210.0, 44.0, 315.0),
        'ray_pos': (242.0, 42.0, 52.0),
        'ground_pos': (235.0, 40.0, 3.0),
        'ground_yaw': 12.0,
    },
    {
        'prefix': 'S5',
        'spawn_time': 1.50,
        'impact_delay': 0.06,
        'arc_center': (195.0, -50.0, 190.0),
        'arc_radius': 230.0,
        'arc_shape': (0.95, 0.30, 1.18),
        'head_pos': (145.0, -25.0, 32.0),
        'ray_pos': (145.0, -25.0, 32.0),
        'ground_pos': (185.0, -45.0, 3.0),
        'ground_yaw': -18.0,
    },
]


def _detect_blade_coord_scale(report, sys_ref, existing_names):
    """Inspect Blade_01 in NS_IceSlash_Skill so S1..S5 match any Y-mirror scale on Blade_*."""
    blade_em = next((n for n in existing_names if n.startswith('Blade_')), None)
    if not blade_em:
        return (1.0, 1.0, 1.0)
    sx, sy, sz = 1.0, 1.0, 1.0
    try:
        rref = {'system': {'refPath': sys_ref}, 'emitterName': blade_em, 'rendererIndex': 0}
        cur = vibeue.exec_tool(NTS, 'GetRendererData', {'rendererRef': rref})
        props = json.loads(cur['propertyValues'])
        meshes = props.get('Meshes') or []
        if meshes and isinstance(meshes[0].get('scale'), dict):
            sc = meshes[0]['scale']
            sx = -1.0 if float(sc.get('x', 1.0)) < 0 else 1.0
            sy = -1.0 if float(sc.get('y', 1.0)) < 0 else 1.0
            sz = -1.0 if float(sc.get('z', 1.0)) < 0 else 1.0
    except Exception as exc:
        report.info(f'Blade renderer scale probe skipped ({exc})')
    try:
        mvals = vibeue.exec_tool(NTS, 'GetModuleInputValues', {
            'moduleRef': {
                'system': {'refPath': sys_ref},
                'emitterName': blade_em,
                'scriptName': 'ParticleSpawnScript',
                'moduleName': 'InitializeParticle',
            }
        })
        for inp in mvals.get('inputs', []):
            if inp.get('name') == 'Mesh Scale':
                v = inp.get('value', {}).get('value', {})
                if isinstance(v, dict) and 'y' in v and float(v.get('y', 1.0)) < 0:
                    sy = -1.0
    except Exception:
        pass
    report.info(f'Detected {blade_em} coordinate scale in {SKILL_SYS_NAME}: {(sx, sy, sz)}')
    return (sx, sy, sz)


def _scale_pt(pt, cscale):
    return (float(pt[0]) * cscale[0], float(pt[1]) * cscale[1], float(pt[2]) * cscale[2])


def _set_emitter_local_deterministic(sys_ref, em_name, bounds=950.0):
    eref = {'system': {'refPath': sys_ref}, 'emitterName': em_name}
    edata = json.loads(_ntool('GetEmitterData', {'emitterRef': eref})['propertyValues'])
    fb = edata.get('FixedBounds') or {}
    fb_min = fb.get('min') or {}
    fb_max = fb.get('max') or {}
    if (
        edata.get('bLocalSpace') is True
        and edata.get('bDeterminism') is True
        and edata.get('CalculateBoundsMode') == 'Fixed'
        and _floats_close(fb_min.get('x'), -bounds)
        and _floats_close(fb_max.get('x'), bounds)
    ):
        return
    edata['bLocalSpace'] = True
    edata['bDeterminism'] = True
    edata['CalculateBoundsMode'] = 'Fixed'
    edata['FixedBounds'] = {
        'min': {'x': -float(bounds), 'y': -float(bounds), 'z': -float(bounds)},
        'max': {'x': float(bounds), 'y': float(bounds), 'z': float(bounds)},
        'isValid': True,
    }
    _ntool('SetEmitterData', {
        'emitterRef': eref,
        'emitterData': {'propertyValues': json.dumps(edata)},
    })


def _ensure_skill_emitter(sys_ref, em_name, em_tmp, existing_set):
    """Add emitter only when missing, then prime per-emitter input cache for diffed writes."""
    if em_name not in existing_set:
        _ntool('AddEmitter', {
            'system': {'refPath': sys_ref},
            'templateEmitter': {'refPath': em_tmp},
            'emitterName': em_name,
        })
        existing_set.add(em_name)
    return _load_emitter_cache(sys_ref, em_name)


def _ensure_module_once(sys_ref, em_name, script_name, mod_asset, insert_before_mod=None):
    mod_short = mod_asset.split('.')[-1]
    ckey = (sys_ref, em_name)
    mod_set = _EM_MOD_CACHE.get(ckey) or set()
    if mod_short in mod_set:
        return False
    loc_ref = {'system': {'refPath': sys_ref}, 'emitterName': em_name, 'scriptName': script_name}
    if insert_before_mod:
        loc_ref['moduleName'] = insert_before_mod
    _ntool('AddModule', {
        'moduleLocationRef': loc_ref,
        'moduleAsset': {'refPath': mod_asset},
    })
    _load_emitter_cache(sys_ref, em_name)
    return True


def _set_random_range_float(sys_ref, em_name, script_name, mod_name, input_name, fmin, fmax):
    ckey = (sys_ref, em_name)
    cache = _EM_INPUT_CACHE.get(ckey) or {}
    cur_root = cache.get((mod_name, (input_name,)))
    want_root = _val_dyn_input(DYN_RAND_FLOAT)
    if not _input_equals(cur_root, want_root):
        _set_input(sys_ref, em_name, script_name, mod_name, input_name, want_root)
        _load_emitter_cache(sys_ref, em_name)
    _set_input(sys_ref, em_name, script_name, mod_name, [input_name, 'Minimum'], _val_float(fmin))
    _set_input(sys_ref, em_name, script_name, mod_name, [input_name, 'Maximum'], _val_float(fmax))


def _set_age_float_curve(sys_ref, em_name, script_name, mod_name, input_name, points, interp='RCIM_Linear'):
    ckey = (sys_ref, em_name)
    cache = _EM_INPUT_CACHE.get(ckey) or {}
    cur_root = cache.get((mod_name, (input_name,)))
    want_root = _val_dyn_input(DYN_FLOAT_CURVE)
    if not _input_equals(cur_root, want_root):
        _set_input(sys_ref, em_name, script_name, mod_name, input_name, want_root)
        _load_emitter_cache(sys_ref, em_name)
    _set_input(sys_ref, em_name, script_name, mod_name, [input_name, 'CurveIndex'], _val_linked_float('Emitter.LoopedAge'))
    _set_input(sys_ref, em_name, script_name, mod_name, [input_name, 'FloatCurve'], _val_curve(points, interp=interp))


def _set_age_vec3_curve(sys_ref, em_name, script_name, mod_name, input_name, points_txyz, interp='RCIM_Cubic'):
    ckey = (sys_ref, em_name)
    cache = _EM_INPUT_CACHE.get(ckey) or {}
    cur_root = cache.get((mod_name, (input_name,)))
    want_root = _val_dyn_input(DYN_VEC_CURVE)
    if not _input_equals(cur_root, want_root):
        _set_input(sys_ref, em_name, script_name, mod_name, input_name, want_root)
        _load_emitter_cache(sys_ref, em_name)
    _set_input(sys_ref, em_name, script_name, mod_name, [input_name, 'CurveIndex'], _val_linked_float('Emitter.LoopedAge'))
    _set_input(sys_ref, em_name, script_name, mod_name, [input_name, 'VectorCurve'], _val_vec3_curve(points_txyz, interp=interp))


def _ensure_sprite_spin(sys_ref, em_name, rate_deg=34.0, rate_max=None):
    try:
        _ensure_module_once(
            sys_ref, em_name, 'ParticleUpdateScript', MOD_SPRITE_ROTRATE,
            insert_before_mod='SolveForcesAndVelocity',
        )
        if rate_max is not None:
            _set_random_range_float(
                sys_ref, em_name, 'ParticleUpdateScript', 'SpriteRotationRate', 'Rotation Rate',
                float(rate_deg), float(rate_max),
            )
        else:
            cache = _EM_INPUT_CACHE.get((sys_ref, em_name)) or {}
            cur = cache.get(('SpriteRotationRate', ('Rotation Rate',)))
            if isinstance(cur, dict):
                sref = (cur.get('struct') or {}).get('refPath', '')
                if sref.endswith('NiagaraFloat'):
                    _set_input(sys_ref, em_name, 'ParticleUpdateScript', 'SpriteRotationRate', 'Rotation Rate', _val_float(rate_deg))
    except Exception:
        pass


def _save_skill_checkpoint(sys_pkg):
    EAL.save_asset(sys_pkg, False)


def _set_once_burst(sys_ref, em_name, spawn_time, count, life_max):
    loop_dur = 3.0
    _set_input(
        sys_ref, em_name, 'EmitterUpdateScript', 'EmitterState', 'Loop Behavior',
        _val_enum('/Niagara/Enums/ENiagara_EmitterStateOptions.ENiagara_EmitterStateOptions', 'NewEnumerator1')
    )
    _set_input(sys_ref, em_name, 'EmitterUpdateScript', 'EmitterState', 'Loop Duration', _val_float(loop_dur))
    _set_input(sys_ref, em_name, 'EmitterUpdateScript', 'SpawnBurst_Instantaneous', 'Spawn Time', _val_float(spawn_time))
    _set_input(sys_ref, em_name, 'EmitterUpdateScript', 'SpawnBurst_Instantaneous', 'Spawn Count', _val_int(count))
    _set_emitter_local_deterministic(sys_ref, em_name)


def _configure_omni_timed(
    sys_ref, em_name, spawn_time, count, life_min, life_max,
    pos_offset=(0.0, 0.0, 0.0), origin_delta=(0.0, 0.0, 0.0),
    sphere_radius=20.0, shape_scale=(1.0, 1.0, 1.0),
    vel_min=50.0, vel_max=200.0,
    gravity=(0.0, 0.0, 0.0), drag=1.5,
    size_curve=None, alpha_curve=None,
):
    _set_once_burst(sys_ref, em_name, spawn_time, count, life_max)
    _set_input(sys_ref, em_name, 'ParticleSpawnScript', 'InitializeParticle', 'Lifetime Min', _val_float(life_min))
    _set_input(sys_ref, em_name, 'ParticleSpawnScript', 'InitializeParticle', 'Lifetime Max', _val_float(life_max))
    _set_input(sys_ref, em_name, 'ParticleSpawnScript', 'InitializeParticle', 'UsePositionOffset', _val_bool(True))
    _set_input(sys_ref, em_name, 'ParticleSpawnScript', 'InitializeParticle', 'Position Offset', _val_vec3(*pos_offset))
    _set_input(sys_ref, em_name, 'ParticleSpawnScript', 'ShapeLocation', 'UseOwnerScale', _val_bool(False))
    _set_input(sys_ref, em_name, 'ParticleSpawnScript', 'ShapeLocation', 'Sphere Radius', _val_float(sphere_radius))
    if shape_scale != (1.0, 1.0, 1.0):
        _set_input(
            sys_ref, em_name, 'ParticleSpawnScript', 'ShapeLocation', 'Non Uniform Scale',
            _val_vec3(*shape_scale)
        )
    origin = (
        pos_offset[0] + origin_delta[0],
        pos_offset[1] + origin_delta[1],
        pos_offset[2] + origin_delta[2],
    )
    _set_input(sys_ref, em_name, 'ParticleSpawnScript', 'AddVelocity', 'Origin Offset', _val_vec3(*origin))
    _set_input(sys_ref, em_name, 'ParticleSpawnScript', 'AddVelocity', ['Velocity Speed', 'Minimum'], _val_float(vel_min))
    _set_input(sys_ref, em_name, 'ParticleSpawnScript', 'AddVelocity', ['Velocity Speed', 'Maximum'], _val_float(vel_max))
    _set_input(sys_ref, em_name, 'ParticleUpdateScript', 'GravityForce', 'Gravity', _val_vec3(*gravity))
    _set_input(sys_ref, em_name, 'ParticleUpdateScript', 'Drag', 'Drag', _val_float(drag))
    if size_curve:
        _set_input(
            sys_ref, em_name, 'ParticleUpdateScript', 'ScaleSpriteSize',
            ['Scale Factor', 'Value', 'FloatCurve'], _val_curve(size_curve)
        )
    if alpha_curve:
        _set_input(
            sys_ref, em_name, 'ParticleUpdateScript', 'ScaleColor',
            ['Scale Alpha', 'FloatCurve'], _val_curve(alpha_curve)
        )


def _configure_mesh_timed(
    sys_ref, em_name, spawn_time, count, life_min, life_max,
    pos_offset=(0.0, 0.0, 0.0), scale_min=1.0, scale_max=1.0,
    size_curve=None, alpha_curve=None,
):
    _set_once_burst(sys_ref, em_name, spawn_time, count, life_max)
    _set_input(sys_ref, em_name, 'ParticleSpawnScript', 'InitializeParticle', 'Lifetime Min', _val_float(life_min))
    _set_input(sys_ref, em_name, 'ParticleSpawnScript', 'InitializeParticle', 'Lifetime Max', _val_float(life_max))
    _set_input(sys_ref, em_name, 'ParticleSpawnScript', 'InitializeParticle', 'UsePositionOffset', _val_bool(True))
    _set_input(sys_ref, em_name, 'ParticleSpawnScript', 'InitializeParticle', 'Position Offset', _val_vec3(*pos_offset))
    _set_input(sys_ref, em_name, 'ParticleSpawnScript', 'InitializeParticle', 'Mesh Uniform Scale Min', _val_float(scale_min))
    _set_input(sys_ref, em_name, 'ParticleSpawnScript', 'InitializeParticle', 'Mesh Uniform Scale Max', _val_float(scale_max))
    _set_input(sys_ref, em_name, 'ParticleSpawnScript', 'AddVelocity', ['Velocity Speed', 'Minimum'], _val_float(0.0))
    _set_input(sys_ref, em_name, 'ParticleSpawnScript', 'AddVelocity', ['Velocity Speed', 'Maximum'], _val_float(0.1))
    if size_curve:
        _set_input(
            sys_ref, em_name, 'ParticleUpdateScript', 'ScaleMeshSize',
            ['Scale Factor', 'Value', 'FloatCurve'], _val_curve(size_curve)
        )
    if alpha_curve:
        _set_input(
            sys_ref, em_name, 'ParticleUpdateScript', 'ScaleColor',
            ['Scale Alpha', 'FloatCurve'], _val_curve(alpha_curve)
        )


def build_skill_system(report, mis, only_prefix=None):
    """Incrementally populate S1_..S5_ / Land_ / Burst_ emitters inside NS_IceSlash_Skill.
    Strictly NEVER deletes or touches Blade_* / Mist_* / Hit* emitters owned by NobleShore!
    Reuses existing emitters in-place, skips unchanged inputs via GetEmitterInputValues, and saves after EVERY emitter.
    """
    sys_pkg = f'{C.NS_DIR}/{SKILL_SYS_NAME}'
    sys_ref = f'{sys_pkg}.{SKILL_SYS_NAME}'
    if not C.asset_exists(sys_pkg):
        report.info(f'{sys_pkg} not yet created by NobleShore; skipping unified emitter injection for now')
        return None

    obj = C.load(sys_pkg)
    summary = _ntool('GetSystemSummary', {'system': {'refPath': sys_ref}})
    existing_names = [e['emitterName'] for e in summary.get('emitters', [])]
    existing_set = set(existing_names)
    preserved = [n for n in existing_names if not n.startswith(OUR_SKILL_PREFIXES)]
    ours_existing = [n for n in existing_names if n.startswith(OUR_SKILL_PREFIXES) and not n.startswith(PROTECTED_SKILL_PREFIXES)]

    # Expected emitter list (Small accents S1..S5 + Land_ + Burst_; Hit1..Hit5 owned by NobleShore)
    wanted_specs = []
    for s in SKILL_SLASH_TABLE:
        p = s['prefix']
        wanted_specs.extend([
            (f'{p}_FrostDust', TMP_EM_OMNI),
            (f'{p}_Snowflakes', TMP_EM_OMNI),
            (f'{p}_GoldStars', TMP_EM_OMNI),
            (f'{p}_Wisps', TMP_EM_OMNI),
        ])
    wanted_specs.extend([
        ('Land_GroundDisc', TMP_EM_MESH),
        ('Land_SnowDome', TMP_EM_OMNI),
        ('Land_Smoke', TMP_EM_OMNI),
        ('Land_Shockwave', TMP_EM_MESH),
        ('Land_CrownRays', TMP_EM_OMNI),
        ('Land_BigStarburst', TMP_EM_OMNI),
        ('Burst_IceDebris', TMP_EM_MESH),
        ('Burst_Streaks', TMP_EM_OMNI),
        ('Burst_Snowflakes', TMP_EM_OMNI),
        ('Burst_GoldStars', TMP_EM_OMNI),
    ])
    wanted_names_set = {w[0] for w in wanted_specs}

    if (only_prefix is None
            and not REBUILD_SKILL_EMITTERS
            and EAL.get_metadata_tag(obj, SKILL_EMITTER_TAG) == SKILL_EMITTER_VERSION
            and set(ours_existing) == wanted_names_set):
        report.skipped(sys_pkg, f'skill overlay emitters {SKILL_EMITTER_VERSION} up to date (preserved={preserved})')
        return sys_pkg

    target_specs = [w for w in wanted_specs if (only_prefix is None or w[0].startswith(only_prefix))]
    # Only remove obsolete emitters within OUR_SKILL_PREFIXES (e.g. legacy S*_Starburst / S*_LightRays / S*_GroundBrush)
    obsolete = [
        n for n in ours_existing
        if (only_prefix is None or n.startswith(only_prefix))
        and (REBUILD_SKILL_EMITTERS or n not in wanted_names_set)
    ]
    report.info(
        f'Updating {sys_pkg} (prefix={only_prefix}): preserving={preserved}, '
        f'removing_obsolete={obsolete}, target_count={len(target_specs)}'
    )

    for old_em in obsolete:
        if old_em.startswith(PROTECTED_SKILL_PREFIXES) or not old_em.startswith(OUR_SKILL_PREFIXES):
            raise RuntimeError(f'SAFETY ABORT: refused to remove non-owned emitter {old_em}')
        _ntool('RemoveEmitter', {
            'emitterRef': {'system': {'refPath': sys_ref}, 'emitterName': old_em}
        })
        existing_set.discard(old_em)
        _EM_INPUT_CACHE.pop((sys_ref, old_em), None)
        _EM_MOD_CACHE.pop((sys_ref, old_em), None)
    if obsolete:
        _save_skill_checkpoint(sys_pkg)

    before_w, before_s = _INPUT_STATS['written'], _INPUT_STATS['skipped']

    # Measure true Blade_01..05 mesh bounding-box centers in SlashRoot (= NS_IceSlash_Skill) local space.
    # Remember: SlashRoot is attached to SK_Guard with scale (1, -1, 1), so character forward is local -Y!
    blade_centers = {}
    for idx in range(1, 6):
        mpath = f'{C.MESH_DIR}/SM_SlashArc_0{idx}'
        if C.asset_exists(mpath):
            sm = C.load(mpath)
            bb = sm.get_bounding_box()
            blade_centers[f'S{idx}'] = (
                float(bb.min.x + bb.max.x) * 0.5,
                float(bb.min.y + bb.max.y) * 0.5,
                float(bb.min.z + bb.max.z) * 0.5,
            )

    # Resolve landing / crystal center in SlashRoot local space (falls back to (0, -185, 0) = 1.85m ahead of Guard).
    land_xy = (0.0, -185.0, 0.0)
    try:
        eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        s_root = None
        c_root = None
        for act in eas.get_all_level_actors():
            lbl = act.get_actor_label()
            if lbl == 'IceSlash_SlashRoot':
                s_root = act
            elif lbl == 'IceSlash_CrystalRoot':
                c_root = act
        if s_root is not None and c_root is not None:
            rel_c = s_root.get_actor_transform().inverse_transform_location(c_root.get_actor_location())
            # Guard sanity: if CrystalRoot is ahead of Guard (local Y < -50), use it directly.
            if float(rel_c.y) < -50.0:
                land_xy = (float(rel_c.x), float(rel_c.y), 0.0)
        report.info(f'Skill local land/crystal anchor: {land_xy}')
    except Exception as exc:
        report.info(f'Fallback land_xy={land_xy} ({exc})')

    # 1. Per-slash SMALL ACCENT emitters S1..S5 (slashes at 0.00 / 0.50 / 0.75 / 1.25 / 1.50s, accents +0.05..+0.08s)
    #    Hit feedback (Hit1_..Hit5_) is owned by NobleShore; S1..S5 own sparse small accents 1.5-3m around character & above blade.
    for s in SKILL_SLASH_TABLE:
        p = s['prefix']
        if only_prefix is not None and not f'{p}_'.startswith(only_prefix):
            continue
        t0 = float(s['spawn_time'])
        bc = blade_centers.get(p, (20.0, -140.0, 110.0))
        # Center above the blade & around character (1.5-3m spread = radius 220-250 cm, elevated so it never covers the blade)
        halo_c = (bc[0] * 0.55, bc[1] * 0.55 - 35.0, max(bc[2] + 55.0, 130.0))
        upper_c = (bc[0] * 0.55, bc[1] * 0.55 - 30.0, max(bc[2] + 75.0, 150.0))
        airy_shape = (1.05, 1.05, 0.68)

        # (a) FrostDust: 40-80 dim round frost specks (3-8 cm), sparsely scattered 1.5-3m
        em = f'{p}_FrostDust'
        _ensure_skill_emitter(sys_ref, em, TMP_EM_OMNI, existing_set)
        _configure_omni_timed(
            sys_ref, em, spawn_time=t0 + 0.05, count=52, life_min=0.60, life_max=1.05,
            pos_offset=halo_c, sphere_radius=235.0, shape_scale=airy_shape,
            vel_min=28.0, vel_max=95.0, gravity=(0.0, 0.0, -18.0), drag=2.8,
            size_curve=[(0.0, 0.65), (0.15, 1.02), (0.75, 0.82), (1.0, 0.0)],
            alpha_curve=[(0.0, 0.0), (0.12, 0.72), (0.70, 0.58), (1.0, 0.0)],
        )
        _set_color_range(sys_ref, em, (0.72, 0.92, 1.0, 0.55), (0.94, 0.99, 1.0, 0.78))
        _set_sprite_uniform_range(sys_ref, em, 3.5, 7.5, 0.0, 360.0)
        _update_sprite_renderer(sys_ref, em, mis['FrostSpeck'], 'Unaligned', 'FaceCamera', sort_hint=15)
        _save_skill_checkpoint(sys_pkg)

        # (b) Snowflakes: 5-8 crisp hex snowflakes (20-40 cm), slow drift + gentle spin, 0.8-1.4s fade
        em = f'{p}_Snowflakes'
        _ensure_skill_emitter(sys_ref, em, TMP_EM_OMNI, existing_set)
        _configure_omni_timed(
            sys_ref, em, spawn_time=t0 + 0.06, count=6, life_min=0.85, life_max=1.35,
            pos_offset=upper_c, sphere_radius=245.0, shape_scale=airy_shape,
            vel_min=18.0, vel_max=54.0, gravity=(0.0, 0.0, -16.0), drag=3.0,
            size_curve=[(0.0, 0.45), (0.12, 1.00), (0.80, 0.92), (1.0, 0.0)],
            alpha_curve=[(0.0, 0.0), (0.10, 0.92), (0.76, 0.80), (1.0, 0.0)],
        )
        _set_color_direct(sys_ref, em, (0.92, 0.98, 1.0, 0.92))
        _set_sprite_uniform_range(sys_ref, em, 20.0, 36.0, 0.0, 360.0)
        _ensure_sprite_spin(sys_ref, em, rate_deg=32.0)
        _update_sprite_renderer(sys_ref, em, mis['Snowflake'], 'Unaligned', 'FaceCamera', sort_hint=16)
        _save_skill_checkpoint(sys_pkg)

        # (c) GoldStars: 3-5 small 4-pt gold twinkle stars (10-25 cm), twinkle pulse & fade
        em = f'{p}_GoldStars'
        _ensure_skill_emitter(sys_ref, em, TMP_EM_OMNI, existing_set)
        _configure_omni_timed(
            sys_ref, em, spawn_time=t0 + 0.07, count=4, life_min=0.55, life_max=0.92,
            pos_offset=upper_c, sphere_radius=230.0, shape_scale=airy_shape,
            vel_min=14.0, vel_max=45.0, gravity=(0.0, 0.0, -8.0), drag=3.2,
            size_curve=[(0.0, 0.25), (0.18, 1.08), (0.48, 0.38), (0.74, 1.00), (1.0, 0.0)],
            alpha_curve=[(0.0, 0.0), (0.12, 0.95), (0.80, 0.85), (1.0, 0.0)],
        )
        _set_color_direct(sys_ref, em, (1.0, 0.90, 0.42, 0.95))
        _set_sprite_uniform_range(sys_ref, em, 11.0, 22.0, -6.0, 6.0)
        _update_sprite_renderer(sys_ref, em, mis['GoldStar'], 'Unaligned', 'FaceCamera', sort_hint=18)
        _save_skill_checkpoint(sys_pkg)

        # (d) Wisps (小团烟丝): sparse soft ice-mist wisps floating slowly above the blade & around character
        em = f'{p}_Wisps'
        _ensure_skill_emitter(sys_ref, em, TMP_EM_OMNI, existing_set)
        _configure_omni_timed(
            sys_ref, em, spawn_time=t0 + 0.08, count=5, life_min=0.75, life_max=1.15,
            pos_offset=upper_c, sphere_radius=220.0, shape_scale=airy_shape,
            vel_min=16.0, vel_max=52.0, gravity=(0.0, 0.0, 22.0), drag=2.9,
            size_curve=[(0.0, 0.60), (0.25, 1.00), (1.0, 1.24)],
            alpha_curve=[(0.0, 0.0), (0.18, 0.62), (0.58, 0.42), (1.0, 0.0)],
        )
        _set_color_range(sys_ref, em, (0.60, 0.75, 0.88, 0.22), (0.80, 0.90, 0.98, 0.34))
        _set_sprite_uniform_range(sys_ref, em, 70.0, 115.0, 0.0, 360.0)
        _update_sprite_renderer(sys_ref, em, mis['SmokePuff'], 'Unaligned', 'FaceCamera', sort_hint=3)
        _save_skill_checkpoint(sys_pkg)

    # 2. Landing combo at system time 1.75s (ref 3.25s; captured at t=1.80s -> age=0.05s)
    if only_prefix is None or only_prefix == 'Land_':
        _ensure_skill_emitter(sys_ref, 'Land_GroundDisc', TMP_EM_MESH, existing_set)
        _configure_mesh_timed(
            sys_ref, 'Land_GroundDisc', spawn_time=1.75, count=1, life_min=0.50, life_max=0.55,
            pos_offset=(land_xy[0], land_xy[1], 3.0), scale_min=6.6, scale_max=7.0,
            size_curve=[(0.0, 0.55), (0.10, 1.00), (1.0, 1.22)],
            alpha_curve=[(0.0, 0.95), (0.45, 0.78), (1.0, 0.0)],
        )
        _set_color_direct(sys_ref, 'Land_GroundDisc', (0.92, 0.98, 1.0, 0.94))
        _update_mesh_renderer(
            sys_ref, 'Land_GroundDisc', ['/Engine/BasicShapes/Plane.Plane'],
            mis['SnowDome'], facing='Default', mesh_scale=(1.0, 1.0, 1.0), sort_hint=3,
        )
        _save_skill_checkpoint(sys_pkg)

        _ensure_skill_emitter(sys_ref, 'Land_SnowDome', TMP_EM_OMNI, existing_set)
        _configure_omni_timed(
            sys_ref, 'Land_SnowDome', spawn_time=1.75, count=2, life_min=0.34, life_max=0.42,
            pos_offset=(land_xy[0], land_xy[1], 95.0), sphere_radius=12.0,
            vel_min=0.0, vel_max=10.0, gravity=(0, 0, 0), drag=1.0,
            size_curve=[(0.0, 0.65), (0.12, 1.08), (1.0, 1.28)],
            alpha_curve=[(0.0, 1.0), (0.45, 0.88), (1.0, 0.0)],
        )
        _set_color_direct(sys_ref, 'Land_SnowDome', (0.95, 0.99, 1.0, 0.96))
        _set_sprite_uniform_range(sys_ref, 'Land_SnowDome', 460.0, 540.0, 0.0, 360.0)
        _update_sprite_renderer(sys_ref, 'Land_SnowDome', mis['SnowDome'], 'Unaligned', 'FaceCamera', sort_hint=5)
        _save_skill_checkpoint(sys_pkg)

        _ensure_skill_emitter(sys_ref, 'Land_Smoke', TMP_EM_OMNI, existing_set)
        _configure_omni_timed(
            sys_ref, 'Land_Smoke', spawn_time=1.75, count=11, life_min=0.70, life_max=1.05,
            pos_offset=(land_xy[0], land_xy[1], 70.0), sphere_radius=125.0, shape_scale=(1.65, 1.65, 0.35),
            vel_min=140.0, vel_max=320.0, gravity=(0.0, 0.0, 55.0), drag=2.4,
            size_curve=[(0.0, 0.72), (0.12, 1.02), (1.0, 1.35)],
            alpha_curve=[(0.0, 0.45), (0.06, 0.78), (0.55, 0.50), (1.0, 0.0)],
        )
        _set_color_range(sys_ref, 'Land_Smoke', (0.56, 0.68, 0.78, 0.68), (0.74, 0.84, 0.93, 0.82))
        _set_sprite_uniform_range(sys_ref, 'Land_Smoke', 220.0, 350.0, 0.0, 360.0)
        _update_sprite_renderer(sys_ref, 'Land_Smoke', mis['SmokePuff'], 'Unaligned', 'FaceCamera', sort_hint=4)
        _save_skill_checkpoint(sys_pkg)

        _ensure_skill_emitter(sys_ref, 'Land_Shockwave', TMP_EM_MESH, existing_set)
        _configure_mesh_timed(
            sys_ref, 'Land_Shockwave', spawn_time=1.75, count=2, life_min=0.50, life_max=0.56,
            pos_offset=(land_xy[0], land_xy[1], 4.0), scale_min=8.8, scale_max=11.6,
            size_curve=[(0.0, 0.42), (0.12, 0.72), (1.0, 1.05)],
            alpha_curve=[(0.0, 0.95), (0.45, 0.68), (1.0, 0.0)],
        )
        _set_color_direct(sys_ref, 'Land_Shockwave', (0.82, 0.96, 1.0, 0.95))
        _update_mesh_renderer(
            sys_ref, 'Land_Shockwave', ['/Engine/BasicShapes/Plane.Plane'],
            mis['ShockwaveRing'], facing='Default', mesh_scale=(1.0, 1.0, 1.0), sort_hint=6,
        )
        _save_skill_checkpoint(sys_pkg)

        _ensure_skill_emitter(sys_ref, 'Land_CrownRays', TMP_EM_OMNI, existing_set)
        _configure_omni_timed(
            sys_ref, 'Land_CrownRays', spawn_time=1.75, count=22, life_min=0.26, life_max=0.40,
            pos_offset=(land_xy[0], land_xy[1], 35.0), origin_delta=(0.0, 0.0, -85.0),
            sphere_radius=85.0, shape_scale=(1.0, 1.0, 0.22),
            vel_min=620.0, vel_max=1220.0, gravity=(0, 0, 0), drag=2.3,
            size_curve=[(0.0, 0.72), (0.16, 1.18), (0.55, 0.92), (1.0, 0.20)],
            alpha_curve=[(0.0, 1.0), (0.48, 0.90), (1.0, 0.0)],
        )
        _set_color_range(sys_ref, 'Land_CrownRays', (0.42, 0.92, 1.0, 1.0), (1.0, 0.92, 0.52, 1.0))
        _set_sprite_nonuniform_range(sys_ref, 'Land_CrownRays', (26.0, 440.0), (56.0, 780.0))
        _update_sprite_renderer(sys_ref, 'Land_CrownRays', mis['LightRay'], 'VelocityAligned', 'FaceCamera', pivot=(0.5, 0.30), sort_hint=22)
        _save_skill_checkpoint(sys_pkg)

        _ensure_skill_emitter(sys_ref, 'Land_BigStarburst', TMP_EM_OMNI, existing_set)
        _configure_omni_timed(
            sys_ref, 'Land_BigStarburst', spawn_time=1.75, count=3, life_min=0.24, life_max=0.32,
            pos_offset=(land_xy[0], land_xy[1], 110.0), sphere_radius=6.0,
            vel_min=0.0, vel_max=6.0, gravity=(0, 0, 0), drag=1.0,
            size_curve=[(0.0, 0.72), (0.18, 1.18), (0.55, 0.90), (1.0, 0.45)],
            alpha_curve=[(0.0, 1.0), (0.52, 0.95), (1.0, 0.0)],
        )
        _set_color_range(sys_ref, 'Land_BigStarburst', (1.0, 0.96, 0.72, 1.0), (1.0, 1.0, 1.0, 1.0))
        _set_sprite_uniform_range(sys_ref, 'Land_BigStarburst', 360.0, 620.0, -25.0, 25.0)
        _update_sprite_renderer(sys_ref, 'Land_BigStarburst', mis['ImpactStarburst'], 'Unaligned', 'FaceCamera', sort_hint=28)
        _save_skill_checkpoint(sys_pkg)

    # 3. Crystal Burst at system time 2.00s (ref 3.50s)
    if only_prefix is None or only_prefix == 'Burst_':
        burst_pos = (land_xy[0], land_xy[1], 55.0)
        debris_candidates = [
            f'{C.CLUSTER_DIR}/SM_IceDebris_01.SM_IceDebris_01',
            f'{C.CLUSTER_DIR}/SM_IceDebris_02.SM_IceDebris_02',
            f'{C.CLUSTER_DIR}/SM_IceDebris_03.SM_IceDebris_03',
            f'{C.MESH_DIR}/SM_IceDebris_01.SM_IceDebris_01',
            f'{C.MESH_DIR}/SM_IceDebris_02.SM_IceDebris_02',
            f'{C.MESH_DIR}/SM_IceDebris_03.SM_IceDebris_03',
        ]
        found_debris = [p for p in debris_candidates if C.asset_exists(p.split('.')[0])]
        if found_debris:
            mesh_refs = found_debris
            base_mesh_scale = (1.0, 1.0, 1.0)
            base_mesh_rot = (0.0, 0.0, 0.0)
            s_min, s_max = 0.85, 1.55
        else:
            mesh_refs = ['/Engine/BasicShapes/Cube.Cube']
            base_mesh_scale = (0.56, 0.24, 0.18)
            base_mesh_rot = (18.0, 12.0, 42.0)
            s_min, s_max = 0.75, 1.55

        _ensure_skill_emitter(sys_ref, 'Burst_IceDebris', TMP_EM_MESH, existing_set)
        _set_once_burst(sys_ref, 'Burst_IceDebris', spawn_time=2.00, count=22, life_max=0.90)
        _set_input(sys_ref, 'Burst_IceDebris', 'ParticleSpawnScript', 'InitializeParticle', 'Lifetime Min', _val_float(0.52))
        _set_input(sys_ref, 'Burst_IceDebris', 'ParticleSpawnScript', 'InitializeParticle', 'Lifetime Max', _val_float(0.90))
        _set_input(sys_ref, 'Burst_IceDebris', 'ParticleSpawnScript', 'InitializeParticle', 'UsePositionOffset', _val_bool(True))
        _set_input(sys_ref, 'Burst_IceDebris', 'ParticleSpawnScript', 'InitializeParticle', 'Position Offset', _val_vec3(*burst_pos))
        _set_color_range(sys_ref, 'Burst_IceDebris', (0.72, 0.92, 1.0, 1.0), (1.0, 1.0, 1.0, 1.0))
        _set_input(sys_ref, 'Burst_IceDebris', 'ParticleSpawnScript', 'InitializeParticle', 'Mesh Uniform Scale Min', _val_float(s_min))
        _set_input(sys_ref, 'Burst_IceDebris', 'ParticleSpawnScript', 'InitializeParticle', 'Mesh Uniform Scale Max', _val_float(s_max))
        if len(mesh_refs) > 1:
            _set_input(
                sys_ref, 'Burst_IceDebris', 'ParticleSpawnScript', 'InitializeParticle',
                'Mesh Renderer Array Visibility Mode',
                _val_enum('/Niagara/Enums/Ribbons/ENiagara_UnsetDirectSetRandom.ENiagara_UnsetDirectSetRandom', 'NewEnumerator3')
            )
        _set_input(sys_ref, 'Burst_IceDebris', 'ParticleSpawnScript', 'AddVelocity', 'Cone Axis', _val_vec3(0.0, 0.0, 1.0))
        _set_input(sys_ref, 'Burst_IceDebris', 'ParticleSpawnScript', 'AddVelocity', 'Cone Angle', _val_float(122.0))
        _set_input(sys_ref, 'Burst_IceDebris', 'ParticleSpawnScript', 'AddVelocity', 'Inner Cone Angle', _val_float(34.0))
        _set_input(sys_ref, 'Burst_IceDebris', 'ParticleSpawnScript', 'AddVelocity', ['Velocity Speed', 'Minimum'], _val_float(720.0))
        _set_input(sys_ref, 'Burst_IceDebris', 'ParticleSpawnScript', 'AddVelocity', ['Velocity Speed', 'Maximum'], _val_float(1280.0))
        _ensure_module_once(sys_ref, 'Burst_IceDebris', 'ParticleSpawnScript', MOD_SHAPELOC)
        _set_input(sys_ref, 'Burst_IceDebris', 'ParticleSpawnScript', 'ShapeLocation', 'UseOwnerScale', _val_bool(False))
        _set_input(sys_ref, 'Burst_IceDebris', 'ParticleSpawnScript', 'ShapeLocation', 'Sphere Radius', _val_float(110.0))
        _set_input(sys_ref, 'Burst_IceDebris', 'ParticleSpawnScript', 'ShapeLocation', 'Non Uniform Scale', _val_vec3(1.0, 1.0, 0.55))
        _ensure_module_once(
            sys_ref, 'Burst_IceDebris', 'ParticleUpdateScript', MOD_GRAVITY,
            insert_before_mod='SolveForcesAndVelocity',
        )
        _set_input(sys_ref, 'Burst_IceDebris', 'ParticleUpdateScript', 'GravityForce', 'Gravity', _val_vec3(0.0, 0.0, -1350.0))
        _set_input(
            sys_ref, 'Burst_IceDebris', 'ParticleUpdateScript', 'ScaleMeshSize',
            ['Scale Factor', 'Value', 'FloatCurve'],
            _val_curve([(0.0, 0.65), (0.12, 1.0), (0.78, 0.90), (1.0, 0.0)]),
        )
        _set_input(
            sys_ref, 'Burst_IceDebris', 'ParticleUpdateScript', 'ScaleColor',
            ['Scale Alpha', 'FloatCurve'],
            _val_curve([(0.0, 1.0), (0.80, 1.0), (1.0, 0.0)]),
        )
        _update_mesh_renderer(
            sys_ref, 'Burst_IceDebris', mesh_refs,
            mis['DebrisToon'], facing='Velocity', mesh_scale=base_mesh_scale, mesh_rot=base_mesh_rot, sort_hint=18,
        )
        _save_skill_checkpoint(sys_pkg)

        _ensure_skill_emitter(sys_ref, 'Burst_Streaks', TMP_EM_OMNI, existing_set)
        _configure_omni_timed(
            sys_ref, 'Burst_Streaks', spawn_time=2.00, count=18, life_min=0.22, life_max=0.38,
            pos_offset=burst_pos, origin_delta=(0.0, 0.0, -70.0),
            sphere_radius=95.0, shape_scale=(1.0, 1.0, 0.55),
            vel_min=550.0, vel_max=1150.0, gravity=(0, 0, 0), drag=2.5,
            size_curve=[(0.0, 0.50), (0.25, 1.15), (1.0, 0.15)],
            alpha_curve=[(0.0, 1.0), (0.45, 0.85), (1.0, 0.0)],
        )
        _set_color_range(sys_ref, 'Burst_Streaks', (0.65, 0.95, 1.0, 1.0), (1.0, 1.0, 1.0, 1.0))
        _set_sprite_nonuniform_range(sys_ref, 'Burst_Streaks', (8.0, 180.0), (18.0, 360.0))
        _update_sprite_renderer(sys_ref, 'Burst_Streaks', mis['LightRay'], 'VelocityAligned', 'FaceCamera', pivot=(0.5, 0.35), sort_hint=22)
        _save_skill_checkpoint(sys_pkg)

        _ensure_skill_emitter(sys_ref, 'Burst_Snowflakes', TMP_EM_OMNI, existing_set)
        _configure_omni_timed(
            sys_ref, 'Burst_Snowflakes', spawn_time=1.98, count=12, life_min=0.95, life_max=1.45,
            pos_offset=(land_xy[0], land_xy[1], 115.0), origin_delta=(0.0, 0.0, -65.0),
            sphere_radius=190.0, shape_scale=(1.1, 1.1, 0.65),
            vel_min=150.0, vel_max=430.0, gravity=(0.0, 0.0, -55.0), drag=2.5,
            size_curve=[(0.0, 0.35), (0.16, 1.05), (0.80, 0.95), (1.0, 0.0)],
            alpha_curve=[(0.0, 0.0), (0.10, 1.0), (0.80, 0.88), (1.0, 0.0)],
        )
        _set_color_direct(sys_ref, 'Burst_Snowflakes', (0.94, 0.99, 1.0, 1.0))
        _set_sprite_uniform_range(sys_ref, 'Burst_Snowflakes', 22.0, 40.0, 0.0, 360.0)
        _ensure_sprite_spin(sys_ref, 'Burst_Snowflakes', rate_deg=30.0)
        _update_sprite_renderer(sys_ref, 'Burst_Snowflakes', mis['Snowflake'], 'Unaligned', 'FaceCamera', sort_hint=15)
        _save_skill_checkpoint(sys_pkg)

        _ensure_skill_emitter(sys_ref, 'Burst_GoldStars', TMP_EM_OMNI, existing_set)
        _configure_omni_timed(
            sys_ref, 'Burst_GoldStars', spawn_time=2.00, count=5, life_min=0.45, life_max=0.85,
            pos_offset=(land_xy[0], land_xy[1], 125.0), origin_delta=(0.0, 0.0, -60.0),
            sphere_radius=210.0, shape_scale=(1.1, 1.1, 0.65),
            vel_min=95.0, vel_max=290.0, gravity=(0.0, 0.0, -20.0), drag=2.8,
            size_curve=[(0.0, 0.20), (0.20, 1.15), (0.48, 0.45), (0.78, 1.05), (1.0, 0.0)],
            alpha_curve=[(0.0, 0.0), (0.12, 1.0), (0.82, 0.92), (1.0, 0.0)],
        )
        _set_color_direct(sys_ref, 'Burst_GoldStars', (1.0, 0.90, 0.42, 1.0))
        _set_sprite_uniform_range(sys_ref, 'Burst_GoldStars', 14.0, 26.0, -6.0, 6.0)
        _update_sprite_renderer(sys_ref, 'Burst_GoldStars', mis['GoldStar'], 'Unaligned', 'FaceCamera', sort_hint=17)
        _save_skill_checkpoint(sys_pkg)

    if only_prefix is None or only_prefix == 'Burst_':
        EAL.set_metadata_tag(obj, SKILL_EMITTER_TAG, SKILL_EMITTER_VERSION)
        _save_skill_checkpoint(sys_pkg)
    dw = _INPUT_STATS['written'] - before_w
    ds = _INPUT_STATS['skipped'] - before_s
    report.modified(
        sys_pkg,
        f'populated {len(target_specs)} overlay emitters (prefix={only_prefix}, preserved={preserved}, '
        f'inputs_written={dw}, inputs_skipped={ds})',
    )
    return sys_pkg


def _ensure_standalone_system(report, sys_name, wanted_specs):
    """Create or update a standalone modular Niagara system (e.g. NS_IceSlash_Land, NS_IceSlash_Burst)
    in-place with input diffing and per-emitter saves."""
    C.ensure_dir(C.NS_DIR)
    sys_pkg = f'{C.NS_DIR}/{sys_name}'
    sys_ref = f'{sys_pkg}.{sys_name}'
    if not C.asset_exists(sys_pkg):
        _ntool('CreateNiagaraSystem', {
            'assetName': sys_name,
            'assetPath': C.NS_DIR,
            'templateSystem': {'refPath': TMP_SYS_MINIMAL},
        })
        report.created(sys_pkg)
    obj = C.load(sys_pkg)
    summary = _ntool('GetSystemSummary', {'system': {'refPath': sys_ref}})
    existing_names = [e['emitterName'] for e in summary.get('emitters', [])]
    existing_set = set(existing_names)
    wanted_names_set = {w[0] for w in wanted_specs}

    for old_em in list(existing_names):
        if REBUILD_MODULAR or old_em not in wanted_names_set:
            _ntool('RemoveEmitter', {'emitterRef': {'system': {'refPath': sys_ref}, 'emitterName': old_em}})
            existing_set.discard(old_em)
            _EM_INPUT_CACHE.pop((sys_ref, old_em), None)
            _EM_MOD_CACHE.pop((sys_ref, old_em), None)
    return sys_pkg, sys_ref, obj, existing_set


def build_land_and_burst_systems(report, mis):
    """Build standalone modular NS_IceSlash_Land and NS_IceSlash_Burst (#141).
    Origin = (0,0,0) at the landing / crystal center; all emitters fire Once at Spawn Time 0.0s."""
    modular = {}

    # 1. NS_IceSlash_Land (triggered once at landing 3.25s)
    land_specs = [
        ('Land_GroundDisc', TMP_EM_MESH),
        ('Land_SnowDome', TMP_EM_OMNI),
        ('Land_Smoke', TMP_EM_OMNI),
        ('Land_Shockwave', TMP_EM_MESH),
        ('Land_CrownRays', TMP_EM_OMNI),
        ('Land_BigStarburst', TMP_EM_OMNI),
    ]
    land_pkg, land_ref, land_obj, land_set = _ensure_standalone_system(report, LAND_SYS_NAME, land_specs)

    _ensure_skill_emitter(land_ref, 'Land_GroundDisc', TMP_EM_MESH, land_set)
    _configure_mesh_timed(
        land_ref, 'Land_GroundDisc', spawn_time=0.0, count=1, life_min=0.50, life_max=0.55,
        pos_offset=(0.0, 0.0, 3.0), scale_min=6.4, scale_max=6.8,
        size_curve=[(0.0, 0.45), (0.14, 1.00), (1.0, 1.22)],
        alpha_curve=[(0.0, 0.92), (0.45, 0.75), (1.0, 0.0)],
    )
    _set_input(land_ref, 'Land_GroundDisc', 'EmitterUpdateScript', 'EmitterState', 'Loop Duration', _val_float(1.6))
    _set_color_direct(land_ref, 'Land_GroundDisc', (0.92, 0.98, 1.0, 0.94))
    _update_mesh_renderer(
        land_ref, 'Land_GroundDisc', ['/Engine/BasicShapes/Plane.Plane'],
        mis['SnowDome'], facing='Default', mesh_scale=(1.0, 1.0, 1.0), sort_hint=3,
    )
    _save_skill_checkpoint(land_pkg)

    _ensure_skill_emitter(land_ref, 'Land_SnowDome', TMP_EM_OMNI, land_set)
    _configure_omni_timed(
        land_ref, 'Land_SnowDome', spawn_time=0.0, count=1, life_min=0.22, life_max=0.28,
        pos_offset=(0.0, 0.0, 55.0), sphere_radius=8.0,
        vel_min=0.0, vel_max=6.0, gravity=(0, 0, 0), drag=1.0,
        size_curve=[(0.0, 0.45), (0.20, 1.00), (1.0, 1.18)],
        alpha_curve=[(0.0, 0.32), (0.35, 0.22), (1.0, 0.0)],
    )
    _set_input(land_ref, 'Land_SnowDome', 'EmitterUpdateScript', 'EmitterState', 'Loop Duration', _val_float(1.6))
    _set_color_direct(land_ref, 'Land_SnowDome', (0.90, 0.97, 1.0, 0.45))
    _set_sprite_uniform_range(land_ref, 'Land_SnowDome', 170.0, 210.0, 0.0, 360.0)
    _update_sprite_renderer(land_ref, 'Land_SnowDome', mis['SnowDome'], 'Unaligned', 'FaceCamera', sort_hint=5)
    _save_skill_checkpoint(land_pkg)

    # Land_Smoke: FaceCamera sprite fog puffs (#140/#141: 150-300cm, 0.7->1.0->1.5, alpha 0->0.45(0.2)->0, greyish-white (0.78,0.82,0.90))
    _ensure_skill_emitter(land_ref, 'Land_Smoke', TMP_EM_OMNI, land_set)
    _configure_omni_timed(
        land_ref, 'Land_Smoke', spawn_time=0.0, count=14, life_min=0.92, life_max=1.38,
        pos_offset=(0.0, 0.0, 65.0), sphere_radius=120.0, shape_scale=(1.60, 1.60, 0.35),
        vel_min=50.0, vel_max=135.0, gravity=(0.0, 0.0, 32.0), drag=1.8,
        size_curve=[(0.0, 0.70), (0.45, 1.00), (1.0, 1.50)],
        alpha_curve=[(0.0, 0.0), (0.20, 0.48), (1.0, 0.0)],
    )
    _set_input(land_ref, 'Land_Smoke', 'EmitterUpdateScript', 'EmitterState', 'Loop Duration', _val_float(1.6))
    _set_color_direct(land_ref, 'Land_Smoke', (0.78, 0.82, 0.90, 1.0))
    _set_sprite_uniform_range(land_ref, 'Land_Smoke', 175.0, 295.0, 0.0, 360.0)
    _ensure_sprite_spin(land_ref, 'Land_Smoke', -20.0, 20.0)
    _update_sprite_renderer(land_ref, 'Land_Smoke', mis['FogPuff'], 'Unaligned', 'FaceCamera', sort_hint=7)
    _save_skill_checkpoint(land_pkg)

    _ensure_skill_emitter(land_ref, 'Land_Shockwave', TMP_EM_MESH, land_set)
    _configure_mesh_timed(
        land_ref, 'Land_Shockwave', spawn_time=0.0, count=2, life_min=0.48, life_max=0.56,
        pos_offset=(0.0, 0.0, 4.0), scale_min=8.6, scale_max=11.4,
        size_curve=[(0.0, 0.22), (0.28, 0.75), (1.0, 1.05)],
        alpha_curve=[(0.0, 0.95), (0.45, 0.68), (1.0, 0.0)],
    )
    _set_input(land_ref, 'Land_Shockwave', 'EmitterUpdateScript', 'EmitterState', 'Loop Duration', _val_float(1.6))
    _set_color_direct(land_ref, 'Land_Shockwave', (0.82, 0.96, 1.0, 0.95))
    _update_mesh_renderer(
        land_ref, 'Land_Shockwave', ['/Engine/BasicShapes/Plane.Plane'],
        mis['ShockwaveRing'], facing='Default', mesh_scale=(1.0, 1.0, 1.0), sort_hint=6,
    )
    _save_skill_checkpoint(land_pkg)

    _ensure_skill_emitter(land_ref, 'Land_CrownRays', TMP_EM_OMNI, land_set)
    _configure_omni_timed(
        land_ref, 'Land_CrownRays', spawn_time=0.0, count=18, life_min=0.24, life_max=0.38,
        pos_offset=(0.0, 0.0, 35.0), origin_delta=(0.0, 0.0, -85.0),
        sphere_radius=80.0, shape_scale=(1.0, 1.0, 0.22),
        vel_min=580.0, vel_max=1150.0, gravity=(0, 0, 0), drag=2.3,
        size_curve=[(0.0, 0.72), (0.16, 1.18), (0.55, 0.92), (1.0, 0.20)],
        alpha_curve=[(0.0, 1.0), (0.48, 0.90), (1.0, 0.0)],
    )
    _set_input(land_ref, 'Land_CrownRays', 'EmitterUpdateScript', 'EmitterState', 'Loop Duration', _val_float(1.6))
    _set_color_range(land_ref, 'Land_CrownRays', (0.42, 0.92, 1.0, 1.0), (1.0, 0.92, 0.52, 1.0))
    _set_sprite_nonuniform_range(land_ref, 'Land_CrownRays', (22.0, 380.0), (48.0, 680.0))
    _update_sprite_renderer(land_ref, 'Land_CrownRays', mis['LightRay'], 'VelocityAligned', 'FaceCamera', pivot=(0.5, 0.30), sort_hint=22)
    _save_skill_checkpoint(land_pkg)

    _ensure_skill_emitter(land_ref, 'Land_BigStarburst', TMP_EM_OMNI, land_set)
    _configure_omni_timed(
        land_ref, 'Land_BigStarburst', spawn_time=0.0, count=2, life_min=0.24, life_max=0.32,
        pos_offset=(0.0, 0.0, 105.0), sphere_radius=6.0,
        vel_min=0.0, vel_max=6.0, gravity=(0, 0, 0), drag=1.0,
        size_curve=[(0.0, 0.72), (0.18, 1.18), (0.55, 0.90), (1.0, 0.45)],
        alpha_curve=[(0.0, 1.0), (0.52, 0.95), (1.0, 0.0)],
    )
    _set_input(land_ref, 'Land_BigStarburst', 'EmitterUpdateScript', 'EmitterState', 'Loop Duration', _val_float(1.6))
    _set_color_range(land_ref, 'Land_BigStarburst', (1.0, 0.96, 0.72, 1.0), (1.0, 1.0, 1.0, 1.0))
    _set_sprite_uniform_range(land_ref, 'Land_BigStarburst', 340.0, 540.0, -25.0, 25.0)
    _update_sprite_renderer(land_ref, 'Land_BigStarburst', mis['ImpactStarburst'], 'Unaligned', 'FaceCamera', sort_hint=26)
    EAL.set_metadata_tag(land_obj, MODULAR_TAG, MODULAR_VERSION)
    _save_skill_checkpoint(land_pkg)
    report.modified(land_pkg, 'configured standalone NS_IceSlash_Land (6 emitters)')
    modular['Land'] = land_pkg

    # 2. NS_IceSlash_Burst (triggered once at crystal eruption 3.50s)
    burst_specs = [
        ('Burst_IceDebris', TMP_EM_MESH),
        ('Burst_Streaks', TMP_EM_OMNI),
        ('Burst_Snowflakes', TMP_EM_OMNI),
        ('Burst_GoldStars', TMP_EM_OMNI),
    ]
    burst_pkg, burst_ref, burst_obj, burst_set = _ensure_standalone_system(report, BURST_SYS_NAME, burst_specs)

    debris_candidates = [
        f'{C.CLUSTER_DIR}/SM_IceDebris_01.SM_IceDebris_01',
        f'{C.CLUSTER_DIR}/SM_IceDebris_02.SM_IceDebris_02',
        f'{C.CLUSTER_DIR}/SM_IceDebris_03.SM_IceDebris_03',
        f'{C.MESH_DIR}/SM_IceDebris_01.SM_IceDebris_01',
        f'{C.MESH_DIR}/SM_IceDebris_02.SM_IceDebris_02',
        f'{C.MESH_DIR}/SM_IceDebris_03.SM_IceDebris_03',
    ]
    found_debris = [p for p in debris_candidates if C.asset_exists(p.split('.')[0])]
    if found_debris:
        mesh_refs = found_debris
        base_mesh_scale = (1.0, 1.0, 1.0)
        base_mesh_rot = (0.0, 0.0, 0.0)
        s_min, s_max = 0.85, 1.55
    else:
        mesh_refs = ['/Engine/BasicShapes/Cube.Cube']
        base_mesh_scale = (0.56, 0.24, 0.18)
        base_mesh_rot = (18.0, 12.0, 42.0)
        s_min, s_max = 0.75, 1.55

    _ensure_skill_emitter(burst_ref, 'Burst_IceDebris', TMP_EM_MESH, burst_set)
    _set_once_burst(burst_ref, 'Burst_IceDebris', spawn_time=0.0, count=20, life_max=0.90)
    _set_input(burst_ref, 'Burst_IceDebris', 'EmitterUpdateScript', 'EmitterState', 'Loop Duration', _val_float(1.8))
    _set_input(burst_ref, 'Burst_IceDebris', 'ParticleSpawnScript', 'InitializeParticle', 'Lifetime Min', _val_float(0.52))
    _set_input(burst_ref, 'Burst_IceDebris', 'ParticleSpawnScript', 'InitializeParticle', 'Lifetime Max', _val_float(0.90))
    _set_input(burst_ref, 'Burst_IceDebris', 'ParticleSpawnScript', 'InitializeParticle', 'UsePositionOffset', _val_bool(True))
    _set_input(burst_ref, 'Burst_IceDebris', 'ParticleSpawnScript', 'InitializeParticle', 'Position Offset', _val_vec3(0.0, 0.0, 48.0))
    _set_color_range(burst_ref, 'Burst_IceDebris', (0.72, 0.92, 1.0, 1.0), (1.0, 1.0, 1.0, 1.0))
    _set_input(burst_ref, 'Burst_IceDebris', 'ParticleSpawnScript', 'InitializeParticle', 'Mesh Uniform Scale Min', _val_float(s_min))
    _set_input(burst_ref, 'Burst_IceDebris', 'ParticleSpawnScript', 'InitializeParticle', 'Mesh Uniform Scale Max', _val_float(s_max))
    if len(mesh_refs) > 1:
        _set_input(
            burst_ref, 'Burst_IceDebris', 'ParticleSpawnScript', 'InitializeParticle',
            'Mesh Renderer Array Visibility Mode',
            _val_enum('/Niagara/Enums/Ribbons/ENiagara_UnsetDirectSetRandom.ENiagara_UnsetDirectSetRandom', 'NewEnumerator3')
        )
    _set_input(burst_ref, 'Burst_IceDebris', 'ParticleSpawnScript', 'AddVelocity', 'Cone Axis', _val_vec3(0.0, 0.0, 1.0))
    _set_input(burst_ref, 'Burst_IceDebris', 'ParticleSpawnScript', 'AddVelocity', 'Cone Angle', _val_float(122.0))
    _set_input(burst_ref, 'Burst_IceDebris', 'ParticleSpawnScript', 'AddVelocity', 'Inner Cone Angle', _val_float(34.0))
    _set_input(burst_ref, 'Burst_IceDebris', 'ParticleSpawnScript', 'AddVelocity', ['Velocity Speed', 'Minimum'], _val_float(720.0))
    _set_input(burst_ref, 'Burst_IceDebris', 'ParticleSpawnScript', 'AddVelocity', ['Velocity Speed', 'Maximum'], _val_float(1280.0))
    _ensure_module_once(burst_ref, 'Burst_IceDebris', 'ParticleSpawnScript', MOD_SHAPELOC)
    _set_input(burst_ref, 'Burst_IceDebris', 'ParticleSpawnScript', 'ShapeLocation', 'UseOwnerScale', _val_bool(False))
    _set_input(burst_ref, 'Burst_IceDebris', 'ParticleSpawnScript', 'ShapeLocation', 'Sphere Radius', _val_float(105.0))
    _set_input(burst_ref, 'Burst_IceDebris', 'ParticleSpawnScript', 'ShapeLocation', 'Non Uniform Scale', _val_vec3(1.0, 1.0, 0.55))
    _ensure_module_once(
        burst_ref, 'Burst_IceDebris', 'ParticleUpdateScript', MOD_GRAVITY,
        insert_before_mod='SolveForcesAndVelocity',
    )
    _set_input(burst_ref, 'Burst_IceDebris', 'ParticleUpdateScript', 'GravityForce', 'Gravity', _val_vec3(0.0, 0.0, -1350.0))
    _set_input(
        burst_ref, 'Burst_IceDebris', 'ParticleUpdateScript', 'ScaleMeshSize',
        ['Scale Factor', 'Value', 'FloatCurve'],
        _val_curve([(0.0, 0.65), (0.12, 1.0), (0.78, 0.90), (1.0, 0.0)]),
    )
    _set_input(
        burst_ref, 'Burst_IceDebris', 'ParticleUpdateScript', 'ScaleColor',
        ['Scale Alpha', 'FloatCurve'],
        _val_curve([(0.0, 1.0), (0.80, 1.0), (1.0, 0.0)]),
    )
    _update_mesh_renderer(
        burst_ref, 'Burst_IceDebris', mesh_refs,
        mis['DebrisToon'], facing='Velocity', mesh_scale=base_mesh_scale, mesh_rot=base_mesh_rot, sort_hint=18,
    )
    _save_skill_checkpoint(burst_pkg)

    _ensure_skill_emitter(burst_ref, 'Burst_Streaks', TMP_EM_OMNI, burst_set)
    _configure_omni_timed(
        burst_ref, 'Burst_Streaks', spawn_time=0.0, count=16, life_min=0.22, life_max=0.38,
        pos_offset=(0.0, 0.0, 48.0), origin_delta=(0.0, 0.0, -70.0),
        sphere_radius=90.0, shape_scale=(1.0, 1.0, 0.55),
        vel_min=550.0, vel_max=1150.0, gravity=(0, 0, 0), drag=2.5,
        size_curve=[(0.0, 0.50), (0.25, 1.15), (1.0, 0.15)],
        alpha_curve=[(0.0, 1.0), (0.45, 0.85), (1.0, 0.0)],
    )
    _set_input(burst_ref, 'Burst_Streaks', 'EmitterUpdateScript', 'EmitterState', 'Loop Duration', _val_float(1.8))
    _set_color_range(burst_ref, 'Burst_Streaks', (0.65, 0.95, 1.0, 1.0), (1.0, 1.0, 1.0, 1.0))
    _set_sprite_nonuniform_range(burst_ref, 'Burst_Streaks', (8.0, 170.0), (16.0, 340.0))
    _update_sprite_renderer(burst_ref, 'Burst_Streaks', mis['LightRay'], 'VelocityAligned', 'FaceCamera', pivot=(0.5, 0.35), sort_hint=22)
    _save_skill_checkpoint(burst_pkg)

    # Shrunk small snowflakes (#140/#141: 18-35 cm, 30-90 deg/s spin, alpha 0->1(0.15)->0)
    _ensure_skill_emitter(burst_ref, 'Burst_Snowflakes', TMP_EM_OMNI, burst_set)
    _configure_omni_timed(
        burst_ref, 'Burst_Snowflakes', spawn_time=0.0, count=8, life_min=0.85, life_max=1.35,
        pos_offset=(0.0, 0.0, 115.0), origin_delta=(0.0, 0.0, -65.0),
        sphere_radius=160.0, shape_scale=(1.1, 1.1, 0.65),
        vel_min=75.0, vel_max=220.0, gravity=(0.0, 0.0, -45.0), drag=2.5,
        size_curve=[(0.0, 0.35), (0.16, 1.00), (0.80, 0.92), (1.0, 0.0)],
        alpha_curve=[(0.0, 0.0), (0.15, 1.0), (1.0, 0.0)],
    )
    _set_input(burst_ref, 'Burst_Snowflakes', 'EmitterUpdateScript', 'EmitterState', 'Loop Duration', _val_float(1.8))
    _set_color_direct(burst_ref, 'Burst_Snowflakes', (0.94, 0.99, 1.0, 1.0))
    _set_sprite_uniform_range(burst_ref, 'Burst_Snowflakes', 18.0, 32.0, 0.0, 360.0)
    _ensure_sprite_spin(burst_ref, 'Burst_Snowflakes', 35.0, 85.0)
    _update_sprite_renderer(burst_ref, 'Burst_Snowflakes', mis['Snowflake'], 'Unaligned', 'FaceCamera', sort_hint=15)
    _save_skill_checkpoint(burst_pkg)

    # Shrunk small gold stars (#140/#141: 10-22 cm, 0.25-0.5s flash, size 0->1.2->0)
    _ensure_skill_emitter(burst_ref, 'Burst_GoldStars', TMP_EM_OMNI, burst_set)
    _configure_omni_timed(
        burst_ref, 'Burst_GoldStars', spawn_time=0.0, count=4, life_min=0.28, life_max=0.48,
        pos_offset=(0.0, 0.0, 120.0), origin_delta=(0.0, 0.0, -60.0),
        sphere_radius=170.0, shape_scale=(1.1, 1.1, 0.65),
        vel_min=45.0, vel_max=150.0, gravity=(0.0, 0.0, -15.0), drag=2.8,
        size_curve=[(0.0, 0.0), (0.35, 1.20), (1.0, 0.0)],
        alpha_curve=[(0.0, 0.0), (0.20, 1.0), (1.0, 0.0)],
    )
    _set_input(burst_ref, 'Burst_GoldStars', 'EmitterUpdateScript', 'EmitterState', 'Loop Duration', _val_float(1.8))
    _set_color_direct(burst_ref, 'Burst_GoldStars', (1.0, 0.90, 0.42, 1.0))
    _set_sprite_uniform_range(burst_ref, 'Burst_GoldStars', 10.0, 20.0, -6.0, 6.0)
    _update_sprite_renderer(burst_ref, 'Burst_GoldStars', mis['GoldStar'], 'Unaligned', 'FaceCamera', sort_hint=17)
    EAL.set_metadata_tag(burst_obj, MODULAR_TAG, MODULAR_VERSION)
    _save_skill_checkpoint(burst_pkg)
    report.modified(burst_pkg, 'configured standalone NS_IceSlash_Burst (4 emitters)')
    modular['Burst'] = burst_pkg

    return modular


def _make_slash_arc_keys(radius_cm, z_cm, sweep_deg=210.0, duration_s=0.10, num_keys=9, start_deg=-10.0):
    """Canonical NS_IceSlash_Slash local arc:
    circle around +Z starting at start_deg (-10 deg = SM_SlashArc_01 tail at +X) sweeping CCW
    through +90 deg (+Y belly) to +200 deg (-X head) over duration_s."""
    pts = []
    for i in range(num_keys):
        frac = i / float(num_keys - 1)
        t = frac * duration_s
        th = math.radians(start_deg + sweep_deg * frac)
        pts.append((t, radius_cm * math.cos(th), radius_cm * math.sin(th), float(z_cm)))
    return pts


def _configure_swept_arc_emitter(
    sys_ref, em_name, rate_hz, sweep_dur, loop_dur,
    life_min, life_max, arc_keys,
    sphere_radius=28.0, shape_scale=(1.0, 1.0, 1.0),
    origin=(0.0, 0.0, 0.0), vel_min=35.0, vel_max=75.0,
    gravity=(0.0, 0.0, 25.0), drag=1.8,
    size_curve=None, alpha_curve=None,
):
    _set_input(
        sys_ref, em_name, 'EmitterUpdateScript', 'EmitterState', 'Loop Behavior',
        _val_enum('/Niagara/Enums/ENiagara_EmitterStateOptions.ENiagara_EmitterStateOptions', 'NewEnumerator1')
    )
    _set_input(sys_ref, em_name, 'EmitterUpdateScript', 'EmitterState', 'Loop Duration', _val_float(loop_dur))
    # Disable instantaneous burst and drive sequential spawn via SpawnRate over [0, sweep_dur]
    _set_input(sys_ref, em_name, 'EmitterUpdateScript', 'SpawnBurst_Instantaneous', 'Spawn Count', _val_int(0))
    _ensure_module_once(sys_ref, em_name, 'EmitterUpdateScript', MOD_SPAWNRATE)
    _set_age_float_curve(
        sys_ref, em_name, 'EmitterUpdateScript', 'SpawnRate', 'SpawnRate',
        [(0.0, float(rate_hz)), (float(sweep_dur), float(rate_hz)), (float(sweep_dur) + 0.001, 0.0)],
        interp='RCIM_Linear',
    )
    _set_emitter_local_deterministic(sys_ref, em_name, bounds=900.0)

    _set_input(sys_ref, em_name, 'ParticleSpawnScript', 'InitializeParticle', 'Lifetime Min', _val_float(life_min))
    _set_input(sys_ref, em_name, 'ParticleSpawnScript', 'InitializeParticle', 'Lifetime Max', _val_float(life_max))
    _set_input(sys_ref, em_name, 'ParticleSpawnScript', 'InitializeParticle', 'UsePositionOffset', _val_bool(True))
    _set_age_vec3_curve(
        sys_ref, em_name, 'ParticleSpawnScript', 'InitializeParticle', 'Position Offset',
        arc_keys, interp='RCIM_Cubic',
    )

    _set_input(sys_ref, em_name, 'ParticleSpawnScript', 'ShapeLocation', 'UseOwnerScale', _val_bool(False))
    _set_input(sys_ref, em_name, 'ParticleSpawnScript', 'ShapeLocation', 'Sphere Radius', _val_float(sphere_radius))
    _set_input(sys_ref, em_name, 'ParticleSpawnScript', 'ShapeLocation', 'Non Uniform Scale', _val_vec3(*shape_scale))

    _set_input(sys_ref, em_name, 'ParticleSpawnScript', 'AddVelocity', 'Origin Offset', _val_vec3(*origin))
    _set_input(sys_ref, em_name, 'ParticleSpawnScript', 'AddVelocity', ['Velocity Speed', 'Minimum'], _val_float(vel_min))
    _set_input(sys_ref, em_name, 'ParticleSpawnScript', 'AddVelocity', ['Velocity Speed', 'Maximum'], _val_float(vel_max))
    _set_input(sys_ref, em_name, 'ParticleUpdateScript', 'GravityForce', 'Gravity', _val_vec3(*gravity))
    _set_input(sys_ref, em_name, 'ParticleUpdateScript', 'Drag', 'Drag', _val_float(drag))
    if size_curve:
        _set_input(
            sys_ref, em_name, 'ParticleUpdateScript', 'ScaleSpriteSize',
            ['Scale Factor', 'Value', 'FloatCurve'], _val_curve(size_curve)
        )
    if alpha_curve:
        _set_input(
            sys_ref, em_name, 'ParticleUpdateScript', 'ScaleColor',
            ['Scale Alpha', 'FloatCurve'], _val_curve(alpha_curve)
        )


def build_slash_overlay(report, mis, allow_inject=None):
    """Add Fog_* + Deco_* emitters to NobleShore's reusable single-slash system NS_IceSlash_Slash (#141).
    Local coords: horizontal circle around +Z, R=270cm, +X (t=0) -> +230 deg CCW (t=0.10s), Loop Duration 1.6s Once.
    Strictly preserves Blade* / Smoke* / Mist* emitters owned by NobleShore!"""
    if allow_inject is None:
        allow_inject = ALLOW_SLASH_OVERLAY
    sys_pkg = f'{C.NS_DIR}/{SLASH_SYS_NAME}'
    sys_ref = f'{sys_pkg}.{SLASH_SYS_NAME}'
    if not allow_inject:
        report.info(f'{sys_pkg}: ALLOW_SLASH_OVERLAY=False (waiting for NobleShore ready signal)')
        return None
    if not C.asset_exists(sys_pkg):
        report.info(f'{sys_pkg} not yet created by NobleShore; skipping Fog_/Deco_ injection')
        return None

    obj = C.load(sys_pkg)
    summary = _ntool('GetSystemSummary', {'system': {'refPath': sys_ref}})
    existing_names = [e['emitterName'] for e in summary.get('emitters', [])]
    existing_set = set(existing_names)
    preserved = [n for n in existing_names if not n.startswith(OUR_SLASH_PREFIXES)]
    ours_existing = [n for n in existing_names if n.startswith(OUR_SLASH_PREFIXES) and not n.startswith(PROTECTED_SLASH_PREFIXES)]

    wanted_specs = [
        ('Fog_Arc', TMP_EM_OMNI),
        ('Deco_Snowflakes', TMP_EM_OMNI),
        ('Deco_GoldStars', TMP_EM_OMNI),
        ('Deco_FrostDust', TMP_EM_OMNI),
    ]
    wanted_set = {w[0] for w in wanted_specs}
    for old_em in ours_existing:
        if REBUILD_MODULAR or old_em not in wanted_set:
            if old_em.startswith(PROTECTED_SLASH_PREFIXES) or not old_em.startswith(OUR_SLASH_PREFIXES):
                raise RuntimeError(f'SAFETY ABORT on {SLASH_SYS_NAME}: {old_em}')
            _ntool('RemoveEmitter', {'emitterRef': {'system': {'refPath': sys_ref}, 'emitterName': old_em}})
            existing_set.discard(old_em)
            _EM_INPUT_CACHE.pop((sys_ref, old_em), None)
            _EM_MOD_CACHE.pop((sys_ref, old_em), None)

    # 1. Fog_Arc: 14 FaceCamera puffs (140 Hz * 0.10s) along R=232cm (band 185-285cm), 160-285cm, 0.7->1.0->1.5, greyish-white
    _ensure_skill_emitter(sys_ref, 'Fog_Arc', TMP_EM_OMNI, existing_set)
    _configure_swept_arc_emitter(
        sys_ref, 'Fog_Arc', rate_hz=140.0, sweep_dur=0.10, loop_dur=1.6,
        life_min=0.92, life_max=1.36,
        arc_keys=_make_slash_arc_keys(radius_cm=232.0, z_cm=4.0, sweep_deg=230.0, duration_s=0.10),
        sphere_radius=34.0, shape_scale=(1.0, 1.0, 0.35),
        origin=(0.0, 0.0, 0.0), vel_min=35.0, vel_max=75.0,
        gravity=(0.0, 0.0, 26.0), drag=1.6,
        size_curve=[(0.0, 0.70), (0.45, 1.00), (1.0, 1.50)],
        alpha_curve=[(0.0, 0.0), (0.20, 0.45), (1.0, 0.0)],
    )
    _set_color_direct(sys_ref, 'Fog_Arc', (0.78, 0.82, 0.90, 1.0))
    _set_sprite_uniform_range(sys_ref, 'Fog_Arc', 160.0, 285.0, 0.0, 360.0)
    _ensure_sprite_spin(sys_ref, 'Fog_Arc', -20.0, 20.0)
    _update_sprite_renderer(sys_ref, 'Fog_Arc', mis['FogPuff'], 'Unaligned', 'FaceCamera', sort_hint=7)
    _save_skill_checkpoint(sys_pkg)

    # 2. Deco_Snowflakes: 5 small hex snowflakes (50 Hz * 0.10s), 18-32 cm, 0.82-1.28s, spin 35-85 deg/s, above/outside arc
    _ensure_skill_emitter(sys_ref, 'Deco_Snowflakes', TMP_EM_OMNI, existing_set)
    _configure_swept_arc_emitter(
        sys_ref, 'Deco_Snowflakes', rate_hz=50.0, sweep_dur=0.10, loop_dur=1.6,
        life_min=0.82, life_max=1.28,
        arc_keys=_make_slash_arc_keys(radius_cm=250.0, z_cm=88.0, sweep_deg=230.0, duration_s=0.10),
        sphere_radius=72.0, shape_scale=(1.0, 1.0, 0.85),
        origin=(0.0, 0.0, 30.0), vel_min=24.0, vel_max=56.0,
        gravity=(0.0, 0.0, 12.0), drag=2.0,
        size_curve=[(0.0, 0.45), (0.15, 1.00), (0.80, 0.92), (1.0, 0.0)],
        alpha_curve=[(0.0, 0.0), (0.15, 1.0), (1.0, 0.0)],
    )
    _set_color_direct(sys_ref, 'Deco_Snowflakes', (0.94, 0.99, 1.0, 0.95))
    _set_sprite_uniform_range(sys_ref, 'Deco_Snowflakes', 18.0, 32.0, 0.0, 360.0)
    _ensure_sprite_spin(sys_ref, 'Deco_Snowflakes', 35.0, 85.0)
    _update_sprite_renderer(sys_ref, 'Deco_Snowflakes', mis['Snowflake'], 'Unaligned', 'FaceCamera', sort_hint=16)
    _save_skill_checkpoint(sys_pkg)

    # 3. Deco_GoldStars: 3 small 4-pt gold stars (30 Hz * 0.10s), 10-20 cm, 0.26-0.48s fast flash, size 0->1.2->0
    _ensure_skill_emitter(sys_ref, 'Deco_GoldStars', TMP_EM_OMNI, existing_set)
    _configure_swept_arc_emitter(
        sys_ref, 'Deco_GoldStars', rate_hz=30.0, sweep_dur=0.10, loop_dur=1.6,
        life_min=0.26, life_max=0.48,
        arc_keys=_make_slash_arc_keys(radius_cm=255.0, z_cm=78.0, sweep_deg=230.0, duration_s=0.10),
        sphere_radius=65.0, shape_scale=(1.0, 1.0, 0.80),
        origin=(0.0, 0.0, 30.0), vel_min=20.0, vel_max=48.0,
        gravity=(0.0, 0.0, 8.0), drag=2.2,
        size_curve=[(0.0, 0.0), (0.35, 1.20), (1.0, 0.0)],
        alpha_curve=[(0.0, 0.0), (0.20, 1.0), (1.0, 0.0)],
    )
    _set_color_direct(sys_ref, 'Deco_GoldStars', (1.0, 0.90, 0.42, 0.98))
    _set_sprite_uniform_range(sys_ref, 'Deco_GoldStars', 10.0, 20.0, -6.0, 6.0)
    _update_sprite_renderer(sys_ref, 'Deco_GoldStars', mis['GoldStar'], 'Unaligned', 'FaceCamera', sort_hint=18)
    _save_skill_checkpoint(sys_pkg)

    # 4. Deco_FrostDust: 44 dim round specks (440 Hz * 0.10s), 3.2-6.8 cm, flung outward along the arc
    _ensure_skill_emitter(sys_ref, 'Deco_FrostDust', TMP_EM_OMNI, existing_set)
    _configure_swept_arc_emitter(
        sys_ref, 'Deco_FrostDust', rate_hz=440.0, sweep_dur=0.10, loop_dur=1.6,
        life_min=0.48, life_max=0.85,
        arc_keys=_make_slash_arc_keys(radius_cm=262.0, z_cm=10.0, sweep_deg=230.0, duration_s=0.10),
        sphere_radius=24.0, shape_scale=(1.0, 1.0, 0.45),
        origin=(0.0, 0.0, 0.0), vel_min=95.0, vel_max=220.0,
        gravity=(0.0, 0.0, -22.0), drag=2.4,
        size_curve=[(0.0, 0.65), (0.15, 1.02), (0.75, 0.82), (1.0, 0.0)],
        alpha_curve=[(0.0, 0.0), (0.12, 0.78), (0.72, 0.60), (1.0, 0.0)],
    )
    _set_color_range(sys_ref, 'Deco_FrostDust', (0.72, 0.92, 1.0, 0.58), (0.94, 0.99, 1.0, 0.82))
    _set_sprite_uniform_range(sys_ref, 'Deco_FrostDust', 3.2, 6.8, 0.0, 360.0)
    _update_sprite_renderer(sys_ref, 'Deco_FrostDust', mis['FrostSpeck'], 'Unaligned', 'FaceCamera', sort_hint=15)
    EAL.set_metadata_tag(obj, MODULAR_TAG, MODULAR_VERSION)
    _save_skill_checkpoint(sys_pkg)
    report.modified(sys_pkg, f'populated Fog_Arc + Deco_* on {SLASH_SYS_NAME} (preserved={preserved})')
    return sys_pkg


_STATIC_BLADE_DISABLED_MODS = [
    ('ParticleSpawnScript', 'AddVelocity'),
    ('ParticleSpawnScript', 'InitialMeshOrientation'),
    ('ParticleUpdateScript', 'GravityForce'),
    ('ParticleUpdateScript', 'UpdateMeshOrientation'),
    ('ParticleUpdateScript', 'Drag'),
    ('ParticleUpdateScript', 'ScaleMeshSize'),
]


def _configure_static_blade_emitter(
    sys_ref, em_name, mesh_name, mat_name, spawn_time, lifetime, loop_dur,
    pos_offset, mesh_scale, mesh_rot, alpha_curve, sort_hint,
):
    for script_n, mod_n in _STATIC_BLADE_DISABLED_MODS:
        try:
            _ntool('SetModuleEnabled', {
                'moduleRef': {'system': {'refPath': sys_ref}, 'emitterName': em_name, 'scriptName': script_n, 'moduleName': mod_n},
                'bEnabled': False,
            })
        except Exception:
            pass
    _set_input(
        sys_ref, em_name, 'EmitterUpdateScript', 'EmitterState', 'Loop Behavior',
        _val_enum('/Niagara/Enums/ENiagara_EmitterStateOptions.ENiagara_EmitterStateOptions', 'NewEnumerator1')
    )
    _set_input(sys_ref, em_name, 'EmitterUpdateScript', 'EmitterState', 'Loop Duration', _val_float(loop_dur))
    _set_input(sys_ref, em_name, 'EmitterUpdateScript', 'SpawnBurst_Instantaneous', 'Spawn Time', _val_float(spawn_time))
    _set_input(sys_ref, em_name, 'EmitterUpdateScript', 'SpawnBurst_Instantaneous', 'Spawn Count', _val_int(1))
    _set_emitter_local_deterministic(sys_ref, em_name, bounds=900.0)

    _set_input(
        sys_ref, em_name, 'ParticleSpawnScript', 'InitializeParticle', 'Lifetime Mode',
        _val_enum('/Niagara/Enums/ENiagara_LifetimeMode.ENiagara_LifetimeMode', 'NewEnumerator0')
    )
    _set_input(sys_ref, em_name, 'ParticleSpawnScript', 'InitializeParticle', 'Lifetime', _val_float(lifetime))
    _set_color_direct(sys_ref, em_name, (1.0, 1.0, 1.0, 1.0))
    _set_input(sys_ref, em_name, 'ParticleSpawnScript', 'InitializeParticle', 'UsePositionOffset', _val_bool(True))
    _set_input(sys_ref, em_name, 'ParticleSpawnScript', 'InitializeParticle', 'Position Offset', _val_vec3(*pos_offset))
    _set_input(
        sys_ref, em_name, 'ParticleSpawnScript', 'InitializeParticle', 'Mesh Scale Mode',
        _val_enum('/Niagara/Enums/ENiagara_SizeScaleMode.ENiagara_SizeScaleMode', 'NewEnumerator3')
    )
    _set_input(sys_ref, em_name, 'ParticleSpawnScript', 'InitializeParticle', 'Mesh Uniform Scale', _val_float(1.0))
    _ntool('SetModuleEnabled', {
        'moduleRef': {'system': {'refPath': sys_ref}, 'emitterName': em_name, 'scriptName': 'ParticleUpdateScript', 'moduleName': 'ScaleColor'},
        'bEnabled': True,
    })
    _set_input(
        sys_ref, em_name, 'ParticleUpdateScript', 'ScaleColor',
        ['Scale Alpha', 'FloatCurve'], _val_curve(alpha_curve)
    )
    mesh_ref = f'{C.MESH_DIR}/{mesh_name}.{mesh_name}'
    mat_path = f'{C.MAT_DIR}/{mat_name}'
    _update_mesh_renderer(
        sys_ref, em_name, [mesh_ref], mat_path,
        facing='Default', mesh_scale=mesh_scale, mesh_rot=mesh_rot, sort_hint=sort_hint,
    )


def build_canonical_slash_and_hit_systems(report, mis):
    """Build ONE canonical reusable slash system NS_IceSlash_Slash (matching user screenshot:
    crisp painted crescent SM_SlashArc_01 + MI_SlashArcNS_01 flattened to Z=0 plane, R=270cm,
    sweeping +X tail -> +Y belly -> -X head, with subtle Mist/Smoke/Fog_Arc/Deco_* strictly subordinate)
    PLUS standalone NS_IceSlash_Hit for target impacts."""
    out = {}

    # --- 1. Canonical NS_IceSlash_Slash ---
    slash_specs = [
        ('Mist', TMP_EM_MESH),
        ('Smoke', TMP_EM_MESH),
        ('Fog_Arc', TMP_EM_OMNI),
        ('Blade', TMP_EM_MESH),
        ('Blade_OuterGlow', TMP_EM_MESH),
        ('Deco_Snowflakes', TMP_EM_OMNI),
        ('Deco_GoldStars', TMP_EM_OMNI),
        ('Deco_FrostDust', TMP_EM_OMNI),
    ]
    slash_pkg, slash_ref, slash_obj, slash_set = _ensure_standalone_system(report, SLASH_SYS_NAME, slash_specs)
    canon_scale = (270.0 / 244.536, 270.0 / 244.536, 270.0 / 244.536)  # 1.104132 -> exact R=270cm
    canon_rot = (0.0, 90.0, 0.0)                                       # flat Z=0 plane, belly +Y
    canon_pos = (-1.97, -5.04, -78.82)                                 # centered at (0,0,0) on Z=0

    # (a) Mist: soft inner frost fan behind the blade
    _ensure_skill_emitter(slash_ref, 'Mist', TMP_EM_MESH, slash_set)
    _configure_static_blade_emitter(
        slash_ref, 'Mist', 'SM_SlashMist_01', 'MI_SlashMist_01',
        spawn_time=0.02, lifetime=0.72, loop_dur=1.4,
        pos_offset=canon_pos, mesh_scale=canon_scale, mesh_rot=canon_rot,
        alpha_curve=[(0.0, 0.82), (0.45, 0.72), (1.0, 0.0)], sort_hint=1,
    )
    _save_skill_checkpoint(slash_pkg)

    # (b) Smoke: subtle painted under-blade smoke sheet 22 cm below blade
    _ensure_skill_emitter(slash_ref, 'Smoke', TMP_EM_MESH, slash_set)
    _configure_static_blade_emitter(
        slash_ref, 'Smoke', 'SM_SlashArc_01', 'MI_SlashSmoke_01',
        spawn_time=0.005, lifetime=0.78, loop_dur=1.4,
        pos_offset=(canon_pos[0], canon_pos[1], canon_pos[2] - 22.0),
        mesh_scale=canon_scale, mesh_rot=canon_rot,
        alpha_curve=[(0.0, 0.62), (0.50, 0.48), (1.0, 0.0)], sort_hint=3,
    )
    _save_skill_checkpoint(slash_pkg)

    # (c) Fog_Arc: light translucent fog puffs under the blade (SortOrderHint=2 so cyan filigree curls stay 100% crisp)
    _ensure_skill_emitter(slash_ref, 'Fog_Arc', TMP_EM_OMNI, slash_set)
    _configure_swept_arc_emitter(
        slash_ref, 'Fog_Arc', rate_hz=90.0, sweep_dur=0.10, loop_dur=1.4,
        life_min=0.75, life_max=1.10,
        arc_keys=_make_slash_arc_keys(radius_cm=232.0, z_cm=-8.0, sweep_deg=210.0, duration_s=0.10, start_deg=-10.0),
        sphere_radius=24.0, shape_scale=(1.0, 1.0, 0.30),
        origin=(0.0, 0.0, 0.0), vel_min=22.0, vel_max=52.0,
        gravity=(0.0, 0.0, 16.0), drag=1.8,
        size_curve=[(0.0, 0.68), (0.45, 1.00), (1.0, 1.38)],
        alpha_curve=[(0.0, 0.0), (0.20, 0.24), (1.0, 0.0)],
    )
    _set_color_direct(slash_ref, 'Fog_Arc', (0.78, 0.84, 0.94, 1.0))
    _set_sprite_uniform_range(slash_ref, 'Fog_Arc', 135.0, 205.0, 0.0, 360.0)
    _ensure_sprite_spin(slash_ref, 'Fog_Arc', -18.0, 18.0)
    _update_sprite_renderer(slash_ref, 'Fog_Arc', mis['FogPuff'], 'Unaligned', 'FaceCamera', sort_hint=2)
    _save_skill_checkpoint(slash_pkg)

    # (d) Blade: HERO painted crescent slash (gold rim + white/cyan core + glowing cyan swirl curls + royal blue tail)
    _ensure_skill_emitter(slash_ref, 'Blade', TMP_EM_MESH, slash_set)
    _configure_static_blade_emitter(
        slash_ref, 'Blade', 'SM_SlashArc_01', 'MI_SlashArcNS_01',
        spawn_time=0.005, lifetime=0.44, loop_dur=1.4,
        pos_offset=canon_pos, mesh_scale=canon_scale, mesh_rot=canon_rot,
        alpha_curve=[(0.0, 1.0), (0.74, 1.0), (1.0, 0.0)], sort_hint=12,
    )
    _save_skill_checkpoint(slash_pkg)

    # (d2) Blade_OuterGlow: Narrow outer-rim additive emissive strip hugging the golden rim
    _ensure_skill_emitter(slash_ref, 'Blade_OuterGlow', TMP_EM_MESH, slash_set)
    _configure_static_blade_emitter(
        slash_ref, 'Blade_OuterGlow', 'SM_SlashOuterGlow_01', 'MI_SlashOuterGlowNS_01',
        spawn_time=0.005, lifetime=0.44, loop_dur=1.4,
        pos_offset=canon_pos, mesh_scale=canon_scale, mesh_rot=canon_rot,
        alpha_curve=[(0.0, 1.0), (0.74, 1.0), (1.0, 0.0)], sort_hint=13,
    )
    _save_skill_checkpoint(slash_pkg)

    # (e) Deco_Snowflakes: 4 small crisp hex snowflakes along outer rim
    _ensure_skill_emitter(slash_ref, 'Deco_Snowflakes', TMP_EM_OMNI, slash_set)
    _configure_swept_arc_emitter(
        slash_ref, 'Deco_Snowflakes', rate_hz=40.0, sweep_dur=0.10, loop_dur=1.4,
        life_min=0.72, life_max=1.10,
        arc_keys=_make_slash_arc_keys(radius_cm=268.0, z_cm=18.0, sweep_deg=210.0, duration_s=0.10, start_deg=-10.0),
        sphere_radius=36.0, shape_scale=(1.0, 1.0, 0.65),
        origin=(0.0, 0.0, 12.0), vel_min=20.0, vel_max=48.0,
        gravity=(0.0, 0.0, 8.0), drag=2.2,
        size_curve=[(0.0, 0.45), (0.15, 1.00), (0.80, 0.90), (1.0, 0.0)],
        alpha_curve=[(0.0, 0.0), (0.15, 0.92), (1.0, 0.0)],
    )
    _set_color_direct(slash_ref, 'Deco_Snowflakes', (0.94, 0.99, 1.0, 0.92))
    _set_sprite_uniform_range(slash_ref, 'Deco_Snowflakes', 15.0, 25.0, 0.0, 360.0)
    _ensure_sprite_spin(slash_ref, 'Deco_Snowflakes', 35.0, 80.0)
    _update_sprite_renderer(slash_ref, 'Deco_Snowflakes', mis['Snowflake'], 'Unaligned', 'FaceCamera', sort_hint=16)
    _save_skill_checkpoint(slash_pkg)

    # (f) Deco_GoldStars: 3 small 4-pt gold twinkle stars
    _ensure_skill_emitter(slash_ref, 'Deco_GoldStars', TMP_EM_OMNI, slash_set)
    _configure_swept_arc_emitter(
        slash_ref, 'Deco_GoldStars', rate_hz=30.0, sweep_dur=0.10, loop_dur=1.4,
        life_min=0.25, life_max=0.44,
        arc_keys=_make_slash_arc_keys(radius_cm=272.0, z_cm=14.0, sweep_deg=210.0, duration_s=0.10, start_deg=-10.0),
        sphere_radius=32.0, shape_scale=(1.0, 1.0, 0.60),
        origin=(0.0, 0.0, 10.0), vel_min=16.0, vel_max=40.0,
        gravity=(0.0, 0.0, 6.0), drag=2.4,
        size_curve=[(0.0, 0.0), (0.35, 1.15), (1.0, 0.0)],
        alpha_curve=[(0.0, 0.0), (0.20, 0.95), (1.0, 0.0)],
    )
    _set_color_direct(slash_ref, 'Deco_GoldStars', (1.0, 0.90, 0.42, 0.95))
    _set_sprite_uniform_range(slash_ref, 'Deco_GoldStars', 9.0, 17.0, -6.0, 6.0)
    _update_sprite_renderer(slash_ref, 'Deco_GoldStars', mis['GoldStar'], 'Unaligned', 'FaceCamera', sort_hint=18)
    _save_skill_checkpoint(slash_pkg)

    # (g) Deco_FrostDust: 28 fine ice dust specks flung lightly off the gold rim
    _ensure_skill_emitter(slash_ref, 'Deco_FrostDust', TMP_EM_OMNI, slash_set)
    _configure_swept_arc_emitter(
        slash_ref, 'Deco_FrostDust', rate_hz=280.0, sweep_dur=0.10, loop_dur=1.4,
        life_min=0.42, life_max=0.75,
        arc_keys=_make_slash_arc_keys(radius_cm=268.0, z_cm=4.0, sweep_deg=210.0, duration_s=0.10, start_deg=-10.0),
        sphere_radius=18.0, shape_scale=(1.0, 1.0, 0.40),
        origin=(0.0, 0.0, 0.0), vel_min=75.0, vel_max=180.0,
        gravity=(0.0, 0.0, -18.0), drag=2.5,
        size_curve=[(0.0, 0.65), (0.15, 1.00), (0.75, 0.80), (1.0, 0.0)],
        alpha_curve=[(0.0, 0.0), (0.12, 0.72), (0.72, 0.52), (1.0, 0.0)],
    )
    _set_color_range(slash_ref, 'Deco_FrostDust', (0.72, 0.92, 1.0, 0.55), (0.94, 0.99, 1.0, 0.78))
    _set_sprite_uniform_range(slash_ref, 'Deco_FrostDust', 3.0, 6.0, 0.0, 360.0)
    _update_sprite_renderer(slash_ref, 'Deco_FrostDust', mis['FrostSpeck'], 'Unaligned', 'FaceCamera', sort_hint=15)
    EAL.set_metadata_tag(slash_obj, MODULAR_TAG, MODULAR_VERSION)
    _save_skill_checkpoint(slash_pkg)
    report.modified(slash_pkg, 'configured canonical NS_IceSlash_Slash (7 emitters)')
    out['Slash'] = slash_pkg

    # --- 2. Standalone NS_IceSlash_Hit ---
    hit_specs = [
        ('Hit_BlueSplash', TMP_EM_OMNI),
        ('Hit_Rays', TMP_EM_OMNI),
        ('Hit_Starburst', TMP_EM_OMNI),
        ('Hit_Sparks', TMP_EM_OMNI),
    ]
    hit_pkg, hit_ref, hit_obj, hit_set = _ensure_standalone_system(report, HIT_SYS_NAME, hit_specs)

    _ensure_skill_emitter(hit_ref, 'Hit_BlueSplash', TMP_EM_OMNI, hit_set)
    _configure_omni_timed(
        hit_ref, 'Hit_BlueSplash', spawn_time=0.0, count=4, life_min=0.18, life_max=0.28,
        pos_offset=(0.0, 0.0, 0.0), sphere_radius=10.0,
        vel_min=180.0, vel_max=400.0, gravity=(0, 0, 0), drag=3.0,
        size_curve=[(0.0, 0.45), (0.30, 1.05), (1.0, 0.30)],
        alpha_curve=[(0.0, 0.90), (0.50, 0.70), (1.0, 0.0)],
    )
    _set_input(hit_ref, 'Hit_BlueSplash', 'EmitterUpdateScript', 'EmitterState', 'Loop Duration', _val_float(0.8))
    _set_color_range(hit_ref, 'Hit_BlueSplash', (0.05, 0.28, 0.82, 0.90), (0.18, 0.68, 1.0, 0.95))
    _set_sprite_nonuniform_range(hit_ref, 'Hit_BlueSplash', (50.0, 150.0), (80.0, 240.0))
    _update_sprite_renderer(hit_ref, 'Hit_BlueSplash', mis['GroundStreak'], 'VelocityAligned', 'FaceCamera', pivot=(0.5, 0.42), sort_hint=8)
    _save_skill_checkpoint(hit_pkg)

    _ensure_skill_emitter(hit_ref, 'Hit_Rays', TMP_EM_OMNI, hit_set)
    _configure_omni_timed(
        hit_ref, 'Hit_Rays', spawn_time=0.0, count=9, life_min=0.15, life_max=0.26,
        pos_offset=(0.0, 0.0, 0.0), sphere_radius=10.0,
        vel_min=380.0, vel_max=820.0, gravity=(0, 0, 0), drag=2.6,
        size_curve=[(0.0, 0.55), (0.26, 1.12), (1.0, 0.16)],
        alpha_curve=[(0.0, 1.0), (0.38, 0.88), (1.0, 0.0)],
    )
    _set_input(hit_ref, 'Hit_Rays', 'EmitterUpdateScript', 'EmitterState', 'Loop Duration', _val_float(0.8))
    _set_color_range(hit_ref, 'Hit_Rays', (0.45, 0.92, 1.0, 1.0), (1.0, 0.84, 0.38, 1.0))
    _set_sprite_nonuniform_range(hit_ref, 'Hit_Rays', (7.0, 180.0), (14.0, 380.0))
    _update_sprite_renderer(hit_ref, 'Hit_Rays', mis['LightRay'], 'VelocityAligned', 'FaceCamera', pivot=(0.5, 0.32), sort_hint=20)
    _save_skill_checkpoint(hit_pkg)

    _ensure_skill_emitter(hit_ref, 'Hit_Starburst', TMP_EM_OMNI, hit_set)
    _configure_omni_timed(
        hit_ref, 'Hit_Starburst', spawn_time=0.0, count=2, life_min=0.18, life_max=0.25,
        pos_offset=(0.0, 0.0, 0.0), sphere_radius=3.0,
        vel_min=0.0, vel_max=4.0, gravity=(0, 0, 0), drag=1.0,
        size_curve=[(0.0, 0.30), (0.40, 1.05), (1.0, 0.10)],
        alpha_curve=[(0.0, 1.0), (0.52, 0.92), (1.0, 0.0)],
    )
    _set_input(hit_ref, 'Hit_Starburst', 'EmitterUpdateScript', 'EmitterState', 'Loop Duration', _val_float(0.8))
    _set_color_range(hit_ref, 'Hit_Starburst', (1.0, 0.95, 0.68, 1.0), (1.0, 1.0, 1.0, 1.0))
    _set_sprite_uniform_range(hit_ref, 'Hit_Starburst', 145.0, 210.0, 0.0, 360.0)
    _update_sprite_renderer(hit_ref, 'Hit_Starburst', mis['ImpactStarburst'], 'Unaligned', 'FaceCamera', sort_hint=26)
    _save_skill_checkpoint(hit_pkg)

    _ensure_skill_emitter(hit_ref, 'Hit_Sparks', TMP_EM_OMNI, hit_set)
    _configure_omni_timed(
        hit_ref, 'Hit_Sparks', spawn_time=0.0, count=8, life_min=0.20, life_max=0.34,
        pos_offset=(0.0, 0.0, 0.0), sphere_radius=14.0,
        vel_min=360.0, vel_max=780.0, gravity=(0, 0, -380.0), drag=2.8,
        size_curve=[(0.0, 0.7), (0.3, 1.1), (1.0, 0.0)],
        alpha_curve=[(0.0, 1.0), (0.6, 0.85), (1.0, 0.0)],
    )
    _set_input(hit_ref, 'Hit_Sparks', 'EmitterUpdateScript', 'EmitterState', 'Loop Duration', _val_float(0.8))
    _set_color_range(hit_ref, 'Hit_Sparks', (0.75, 0.95, 1.0, 1.0), (1.0, 0.88, 0.38, 1.0))
    _set_sprite_uniform_range(hit_ref, 'Hit_Sparks', 12.0, 24.0, -15.0, 15.0)
    _update_sprite_renderer(hit_ref, 'Hit_Sparks', mis['GoldStar'], 'Unaligned', 'FaceCamera', sort_hint=22)
    EAL.set_metadata_tag(hit_obj, MODULAR_TAG, MODULAR_VERSION)
    _save_skill_checkpoint(hit_pkg)
    report.modified(hit_pkg, 'configured standalone NS_IceSlash_Hit (4 emitters)')
    out['Hit'] = hit_pkg

    return out


def _unwrap_async_json(res):
    if hasattr(res, 'is_complete'):
        if res.is_complete and getattr(res, 'value', None):
            val = json.loads(res.value)
            return val.get('returnValue', val) if isinstance(val, dict) else val
        return None
    return res


def verify_systems(report, built, extra_pkgs=None):
    evidence = {}
    items = list(built.items())
    for k, pkg in (extra_pkgs or {}).items():
        if pkg:
            items.append((k, pkg))
    for key, pkg in items:
        name = pkg.split('/')[-1]
        ref = f'{pkg}.{name}'
        if key not in ('Skill', 'Slash', 'Hit', 'Land', 'Burst'):
            _stamp_system(pkg)
        cstate_raw = _unwrap_async_json(vibeue.exec_tool(NTS, 'GetSystemCompileState', {'system': {'refPath': ref}}))
        issues_raw = _unwrap_async_json(vibeue.exec_tool(NTS, 'GetStackIssues', {'system': {'refPath': ref}}))
        summary = vibeue.exec_tool(NTS, 'GetSystemSummary', {'system': {'refPath': ref}})
        issues_list = issues_raw if isinstance(issues_raw, list) else []
        errs = [i for i in issues_list if isinstance(i, dict) and str(i.get('severity', '')).lower() == 'error']
        evidence[name] = {
            'compileState': cstate_raw if cstate_raw is not None else 'async_compiling_or_ready',
            'emitters': [e['emitterName'] for e in summary.get('emitters', [])],
            'numIssues': len(issues_list),
            'numErrors': len(errs),
        }
        if errs:
            for e in errs:
                report.error(f'{name} stack error: {e}')
        else:
            report.info(f'VERIFIED {name}: emitters={len(evidence[name]["emitters"])} errors=0')
    return evidence


def main():
    report = C.Report(SCRIPT_NAME)
    evidence = {}
    with report.step('Build Niagara particle materials & MIs'):
        mis = build_vfx_materials(report)
    built = build_systems(report, mis)
    with report.step('Build standalone NS_IceSlash_Land & NS_IceSlash_Burst (#141)'):
        modular = build_land_and_burst_systems(report, mis)
    with report.step('Build canonical NS_IceSlash_Slash & NS_IceSlash_Hit'):
        modular.update(build_canonical_slash_and_hit_systems(report, mis))
    with report.step('Verify Niagara compile state & stack issues'):
        evidence = verify_systems(report, built, extra_pkgs=modular)

    systems_out = dict(built)
    systems_out.update(modular)
    C.update_manifest('niagara', {
        'status': 'ready_v3_modular',
        'version': MAT_VERSION,
        'modular_version': MODULAR_VERSION,
        'materials': mis,
        'systems': systems_out,
        'verification': evidence,
    })
    C.save_all(report)
    return report.finish()


if __name__ == '__main__':
    main()
