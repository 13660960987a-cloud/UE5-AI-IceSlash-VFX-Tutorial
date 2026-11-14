"""Ice Slash step 04: toon ice-crystal material, its instances and mesh assignment.

Purpose
    Builds the cartoon three-tone crystal material C.MAT_DIR + '/M_IceCrystal_v2':
    Unlit, Masked (clip 0.333), one-sided. It has a fixed-light-direction three-tone ramp,
    a stepped Fresnel rim, a glow tint, a bottom-to-top growth cut with a white growth edge,
    a world-position-offset "grow out of the pivot" scale, a dithered CrystalOpacity fade
    and a cheap per-facet twinkle driven by NoiseSpeed.
    It then creates MI_IceCrystal_Prism / MI_IceCrystal_Boulder / MI_IceCrystal_SnowBase and
    assigns them to the ice-cluster part meshes in C.CLUSTER_DIR according to
    data/ice_slash_data.json cluster_parts[*].material_role (prism, boulder, snowbase).

Run order
    01 import -> 02 anim+sockets -> 03 slash material -> **04 crystal material (this file)**
    -> 05 niagara -> 06 showcase level -> 07 sequence.
    Needs the cluster part meshes from step 01. No level is loaded, and no other asset is
    touched.

How to run (inside the editor, by the owning agent):
    import runpy; runpy.run_path('/Users/mengmeile/Downloads/lianxi/m/Tools/IceSlash/ice_slash_04_material_crystal.py', run_name='__main__')

Creates or modifies
    /Game/VFX/IceSlash/Materials/M_IceCrystal_v2
    /Game/VFX/IceSlash/Materials/MI_IceCrystal_Prism, MI_IceCrystal_Boulder, MI_IceCrystal_SnowBase
    material slots of /Game/VFX/IceSlash/Meshes/IceCluster/SM_IceCluster_* (all slots per mesh)
    manifest section 'materials' -> key 'crystal' (merged; slash entries are preserved)

Idempotency
    - Assets are created only when missing. AssetTools.create_asset on an existing path opens a
      modal overwrite dialog (Engine/Source/Developer/AssetTools/Private/AssetTools.cpp:4920-4936).
    - The graph is built only for a new or empty material, or when REBUILD = True. A rebuild
      happens in place: every expression is deleted but the asset is kept, so references and MI
      overrides keyed by parameter name survive. Otherwise the existing graph is verified:
      missing parameters or unwired outputs log ERROR, and a version-tag mismatch logs a TODO
      asking for REBUILD. Parameter defaults that differ are changed in place
      (set_expression_property). This is the same convention as ice_slash_03_material_slash.py.
    - Metadata IceSlashGraphVersion = GRAPH_VERSION is written after a clean build+compile.
    - Material properties, MI parameters and mesh slots are compared before writing. Unchanged
      values log SKIPPED:.

Exit
    report.finish() prints 'ICE_SLASH_SUMMARY {...}' and raises RuntimeError if any ERROR: was
    recorded.
"""

import sys
import importlib
import math
import re

import unreal

TOOLS_DIR = '/Users/mengmeile/Downloads/lianxi/m/Tools/IceSlash'
if TOOLS_DIR not in sys.path:
    sys.path.insert(0, TOOLS_DIR)
import ice_slash_common as C  # noqa: E402
importlib.reload(C)

# --------------------------------------------------------------------------------------
# CONFIG
# --------------------------------------------------------------------------------------
SCRIPT_NAME = 'ice_slash_04_material_crystal'

# Same convention as ice_slash_03_material_slash.py:
# True: delete every expression of M_IceCrystal_v2 and rebuild the graph in place (the asset is kept).
REBUILD = False
# True: re-write parameter defaults, MI values and mesh slots even when they already match.
FORCE = False

# Stored as asset metadata after a clean build+compile; bump when build_graph() changes structurally.
# A mismatch only logs a TODO asking for REBUILD = True (as in step 03). It does not rebuild by itself.
GRAPH_VERSION = 'crystal_v2.3'
GRAPH_TAG = 'IceSlashGraphVersion'   # same tag name as the slash script

# 'ign': screen-space interleaved-gradient-noise dither built from ScreenPosition.PixelPosition.
#        Every node and its semantics are verified in source, and the 0/1 output works with any clip value.
# 'dither_temporal_aa': engine function DitherTemporalAA(CrystalOpacity). Its exact output range
#        relative to our clip value (0.333) could not be verified (binary .uasset). See the TODO.
DITHER_MODE = 'ign'
DITHER_TEMPORAL_AA_FN = '/Engine/Functions/Engine_MaterialFunctions02/Utility/DitherTemporalAA'

# Cheap per-facet twinkle on lit faces driven by NoiseSpeed (no texture needed).
ENABLE_SPARKLE = True
SPARKLE_THRESHOLD = 0.96   # sin() above this value flashes (about 9% of each period)
SPARKLE_GAIN = 1.5
GROWTH_EDGE_GAIN = 3.0     # "emissive white times 3"
GROWTH_EDGE_OFF_ABOVE = 0.999  # the growth-edge band switches off once fully grown (no permanent white tips)

MAT_NAME = 'M_IceCrystal_v2'
MAT_PATH = C.MAT_DIR + '/' + MAT_NAME

MATERIAL_PROPERTIES = [
    # (VibeUE MaterialService property name, full enum/value spelling). Full names only, because
    # the enum resolver falls back to substring matching (UMaterialService.cpp:208-257).
    ('MaterialDomain', 'MD_Surface'),
    ('ShadingModel', 'MSM_Unlit'),
    ('BlendMode', 'BLEND_Masked'),
    ('OpacityMaskClipValue', '0.333'),
    ('TwoSided', 'false'),
]


def _norm3(v):
    n = math.sqrt(sum(c * c for c in v)) or 1.0
    return tuple(c / n for c in v)


LIGHT_DIR = _norm3((-0.4, -0.6, 0.7))

# name -> (type, group, default, slider_min, slider_max)
# Vector defaults are (r, g, b, a).
PARAMS = {
    'LightDir':          ('Vector', 'Tone',   LIGHT_DIR + (0.0,), None, None),
    'LitColor':          ('Vector', 'Tone',   (0.75, 0.90, 1.00, 1.0), None, None),
    'MidColor':          ('Vector', 'Tone',   (0.25, 0.55, 0.95, 1.0), None, None),
    'ShadowColor':       ('Vector', 'Tone',   (0.05, 0.18, 0.55, 1.0), None, None),
    'ToneThreshold1':    ('Scalar', 'Tone',   0.35, -1.0, 1.0),
    'ToneThreshold2':    ('Scalar', 'Tone',   0.75, -1.0, 1.0),
    'RimColor':          ('Vector', 'Rim',    (1.0, 1.0, 1.0, 1.0), None, None),
    'RimThreshold':      ('Scalar', 'Rim',    0.55, 0.0, 1.0),
    'EdgeBrightness':    ('Scalar', 'Rim',    1.5, 0.0, 10.0),
    'CrystalGlow':       ('Scalar', 'Glow',   0.3, 0.0, 10.0),
    'CrystalColor':      ('Vector', 'Glow',   (0.4, 0.8, 1.0, 1.0), None, None),
    'NoiseSpeed':        ('Scalar', 'Glow',   0.2, 0.0, 5.0),
    'CrystalGrowth':     ('Scalar', 'Growth', 1.0, 0.0, 1.0),
    'GrowthEdgeWidth':   ('Scalar', 'Growth', 0.03, 0.0, 0.2),
    'GrowthScaleAmount': ('Scalar', 'Growth', 0.85, 0.0, 1.0),
    'CrystalOpacity':    ('Scalar', 'Growth', 1.0, 0.0, 1.0),
}

# MI name -> (material_role, {param: value}); an empty dict means it inherits every parent default.
INSTANCES = {
    'MI_IceCrystal_Prism': ('prism', {}),
    'MI_IceCrystal_Boulder': ('boulder', {
        'LitColor': (0.97, 0.98, 1.0, 1.0),
        'MidColor': (0.80, 0.88, 1.0, 1.0),
        'ShadowColor': (0.45, 0.60, 0.85, 1.0),
    }),
    'MI_IceCrystal_SnowBase': ('snowbase', {
        'LitColor': (1.0, 1.0, 1.0, 1.0),
        'MidColor': (0.86, 0.93, 1.0, 1.0),
        'ShadowColor': (0.55, 0.75, 0.95, 1.0),
        'EdgeBrightness': 0.6,
    }),
}

REQUIRED_OUTPUTS = ('EmissiveColor', 'OpacityMask', 'WorldPositionOffset')

MNS = unreal.MaterialNodeService
MS = unreal.MaterialService
MEL = unreal.MaterialEditingLibrary
EAL = unreal.EditorAssetLibrary


# --------------------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------------------
def _color_str(c):
    r, g, b = c[0], c[1], c[2]
    a = c[3] if len(c) > 3 else 1.0
    # '(R=..,G=..,B=..,A=..)' is the only colour form batch_set_properties accepts
    # (FLinearColor::InitFromString, UMaterialNodeService.cpp:1697-1708).
    return '(R=%.6f,G=%.6f,B=%.6f,A=%.6f)' % (r, g, b, a)


def _parse_color(s):
    vals = dict((k, float(v)) for k, v in re.findall(r'([RGBA])=([-+0-9.eE]+)', s or ''))
    if not all(k in vals for k in 'RGBA'):
        return None
    return (vals['R'], vals['G'], vals['B'], vals['A'])


def _close(a, b, eps=1e-4):
    if a is None or b is None:
        return False
    if isinstance(a, (tuple, list)) or isinstance(b, (tuple, list)):
        return len(a) == len(b) and all(abs(float(x) - float(y)) <= eps for x, y in zip(a, b))
    return abs(float(a) - float(b)) <= eps


def _text_matches(got, want):
    """Compare an ExportText value: numerically when both sides parse as floats, else case-insensitively."""
    g, w = (got or '').strip(), (want or '').strip()
    try:
        return _close(float(g), float(w))
    except ValueError:
        return g.lower() == w.lower()


def _lc_tuple(lc):
    return (float(lc.r), float(lc.g), float(lc.b), float(lc.a))


def _own_expressions(mat):
    """Expressions owned by mat itself. list_expressions also returns nodes inside referenced
    functions (GetAllExpressionsInMaterialAndFunctionsOfType, UMaterialNodeService.cpp:864-865)."""
    prefix = mat.get_path_name() + ':'
    return [e for e in MNS.list_expressions(MAT_PATH) if e.object_path.startswith(prefix)]


# --------------------------------------------------------------------------------------
# Step 1: material asset
# --------------------------------------------------------------------------------------
def ensure_material(report):
    C.ensure_dir(C.MAT_DIR)
    if C.asset_exists(MAT_PATH):
        mat = C.load(MAT_PATH)
        if not isinstance(mat, unreal.Material):
            raise RuntimeError('%s exists but is %s, not a Material' % (MAT_PATH, type(mat).__name__))
        report.skipped(MAT_PATH, 'material exists')
        return mat, False
    # VibeUE MaterialService has no create_material (UMaterialService.h:222-223); use the native
    # factory path proven in Saved/PredictiveIK/setup_showcase.py:18.
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    mat = tools.create_asset(MAT_NAME, C.MAT_DIR, unreal.Material, unreal.MaterialFactoryNew())
    if mat is None:
        raise RuntimeError('create_asset returned None for ' + MAT_PATH)
    report.created(MAT_PATH)
    return mat, True


# --------------------------------------------------------------------------------------
# Step 2: material-level properties
# --------------------------------------------------------------------------------------
def _prop_matches(current, wanted):
    if current is None:
        return False
    cur = current.strip()
    try:
        return _close(float(cur), float(wanted))
    except ValueError:
        pass
    cl, wl = cur.lower(), wanted.lower()
    # Enum names come back unqualified ("MSM_Unlit"); tolerate a namespaced form ("EX::MSM_Unlit").
    return cl == wl or cl.endswith('::' + wl)


def set_material_properties(report, results):
    for name, value in MATERIAL_PROPERTIES:
        try:
            # Bool UFUNCTION with an out param returns None on failure, else the struct
            # (PythonScriptPlugin PyGenUtil.cpp:1615-1626).
            info = MS.get_property_info(MAT_PATH, name)
            current = info.current_value if info is not None else None
            if _prop_matches(current, value):
                report.skipped('%s.%s' % (MAT_PATH, name), 'already %s' % current)
                results[name] = current
                continue
            # set_property: Modify -> write -> PostEditChange -> dirty; returns False instead of
            # raising (UMaterialService.cpp:646-681).
            if not MS.set_property(MAT_PATH, name, value):
                report.error('set_property %s=%s failed on %s (was %s)' % (name, value, MAT_PATH, current))
                continue
            info = MS.get_property_info(MAT_PATH, name)
            now = info.current_value if info is not None else None
            if not _prop_matches(now, value):
                report.error('%s.%s read back %r, wanted %s' % (MAT_PATH, name, now, value))
                continue
            results[name] = now
            report.modified(MAT_PATH, '%s: %s -> %s' % (name, current, now))
        except Exception as exc:  # noqa: BLE001
            report.error('material property %s' % name, exc)


# --------------------------------------------------------------------------------------
# Step 3: graph
# --------------------------------------------------------------------------------------
def graph_state(mat):
    """Return (tag, param_name->info, connected output names)."""
    tag = EAL.get_metadata_tag(mat, GRAPH_TAG)
    params = {}
    for e in _own_expressions(mat):
        if e.is_parameter and e.parameter_name:
            params[str(e.parameter_name)] = e
    outs = set(o.property_name for o in MNS.get_output_connections(MAT_PATH) if o.is_connected)
    return tag, params, outs


def _node_specs():
    """Graph spec: list of (key, class short name, x, y, {prop: value-string})."""
    specs = []
    y = 0
    for name, (ptype, group, default, smin, smax) in PARAMS.items():
        props = {'ParameterName': name, 'Group': group}
        if ptype == 'Scalar':
            props['DefaultValue'] = '%.6f' % default
            if smin is not None:
                props['SliderMin'] = '%.6f' % smin
                props['SliderMax'] = '%.6f' % smax
            specs.append(('P_' + name, 'ScalarParameter', -2200, y, props))
        else:
            props['DefaultValue'] = _color_str(default)
            specs.append(('P_' + name, 'VectorParameter', -2200, y, props))
        y += 140

    def n(key, cls, x, yy, **props):
        specs.append((key, cls, x, yy, dict((k, str(v)) for k, v in props.items())))

    # Tone: NdotL = dot(VertexNormalWS, normalize(LightDir)), stepped twice.
    n('VN', 'VertexNormalWS', -1800, 0)
    n('LightNorm', 'Normalize', -1800, 150)
    n('NdotL', 'DotProduct', -1600, 80)
    # Step(Y, X) = X >= Y ? 1 : 0 (MaterialExpressions.cpp:4862-4870; HLSLMaterialTranslator.cpp:10132-10162).
    n('ToneS1', 'Step', -1400, 0)
    n('ToneS2', 'Step', -1400, 150)
    n('LerpShadowMid', 'LinearInterpolate', -1200, 0)
    n('Tone', 'LinearInterpolate', -1000, 80)
    # Rim: Fresnel(exp 4, base 0) on the vertex normal, stepped at RimThreshold.
    n('Fresnel', 'Fresnel', -1600, 400, Exponent='4.0', BaseReflectFraction='0.0')
    n('RimStep', 'Step', -1400, 400)
    n('RimCol', 'Multiply', -1400, 550)
    n('Rim', 'Multiply', -1200, 450)
    # Glow.
    n('Glow', 'Multiply', -1200, 700)
    # Growth front on UV0.V (parts are UV'd bottom to top).
    n('TC', 'TextureCoordinate', -1800, 900)
    n('V', 'ComponentMask', -1600, 900, R='False', G='True', B='False', A='False')
    n('FrontStep', 'Step', -1400, 900)            # V >= growth -> 1
    n('GrowthMask', 'OneMinus', -1200, 900)       # visible below the front
    n('EdgeLow', 'Subtract', -1400, 1050)         # growth - width
    n('EdgeStep', 'Step', -1200, 1050)            # V >= growth - width
    n('EdgeBand', 'Multiply', -1000, 1000)
    n('EdgeActive', 'Step', -1200, 1200, ConstX='%.6f' % GROWTH_EDGE_OFF_ABOVE)  # 0.999 >= growth
    n('EdgeBandLive', 'Multiply', -800, 1050)
    n('Edge', 'Multiply', -600, 1050, ConstB='%.6f' % GROWTH_EDGE_GAIN)
    # Emissive sum.
    n('Add1', 'Add', -800, 200)
    n('Add2', 'Add', -600, 300)
    n('Add3', 'Add', -400, 400)
    if ENABLE_SPARKLE:
        # Per-facet twinkle: the hard-edged vertex normal is constant per facet, so frac(dot(N, k))
        # is a per-facet phase; sin(2*pi*(Time*NoiseSpeed + phase)) > threshold flashes on lit faces.
        n('Time', 'Time', -1800, 1400)
        n('TimeScaled', 'Multiply', -1600, 1400)
        n('HashK', 'Constant3Vector', -1800, 1550, Constant=_color_str((12.9898, 78.233, 37.719, 0.0)))
        n('HashDot', 'DotProduct', -1600, 1550)
        n('HashFrac', 'Frac', -1400, 1550)
        n('Phase', 'Add', -1200, 1450)
        n('Wave', 'Sine', -1000, 1450, Period='1.0')
        n('SparkStep', 'Step', -800, 1450, ConstY='%.6f' % SPARKLE_THRESHOLD)
        n('SparkLit', 'Multiply', -600, 1450)
        n('Spark', 'Multiply', -400, 1450, ConstB='%.6f' % SPARKLE_GAIN)
        n('Emissive', 'Add', -200, 500)
    # Dithered opacity.
    if DITHER_MODE == 'ign':
        # Interleaved gradient noise: frac(52.9829189 * frac(dot(pixel, (0.06711056, 0.00583715)))).
        # ScreenPosition outputs 'ViewportUV' and 'PixelPosition' (MaterialExpressions.cpp:10586-10588).
        n('ScreenPos', 'ScreenPosition', -1800, 1800)
        n('IgnK', 'Constant2Vector', -1800, 1950, R='0.06711056', G='0.00583715')
        n('IgnDot', 'DotProduct', -1600, 1850)
        n('IgnFrac1', 'Frac', -1400, 1850)
        n('IgnMul', 'Multiply', -1200, 1850, ConstB='52.9829189')
        n('Ign', 'Frac', -1000, 1850)
        n('DitherStep', 'Step', -800, 1800)       # CrystalOpacity >= noise -> 1
    n('OpMask', 'Multiply', -400, 1000)
    # WPO: (pivotWS - WorldPosition) * (1 - smoothstep(0, 1, growth)) * GrowthScaleAmount.
    # ObjectPositionWS is NOT the pivot in 5.9: it is the world-bounds origin
    # (PrimitiveUniformShaderParametersBuilder.h:196 AbsoluteObjectWorldPosition = InWorldBounds.Origin).
    # The component pivot is TransformPosition(Local -> world) of (0,0,0). Both sides use camera-relative
    # (translated) world space, which keeps them float3 instead of LWC (HLSLMaterialTranslator.cpp:6291-6297).
    n('PivotZero', 'Constant3Vector', -1800, 2200, Constant=_color_str((0.0, 0.0, 0.0, 0.0)))
    n('Pivot', 'TransformPosition', -1600, 2200,
      TransformSourceType='TRANSFORMPOSSOURCE_Local', TransformType='TRANSFORMPOSSOURCE_TranslatedWorld')
    n('WP', 'WorldPosition', -1600, 2350, WorldPositionShaderOffset='WPT_CameraRelative')
    n('RelPos', 'Subtract', -1400, 2250)
    n('GrowthSmooth', 'SmoothStep', -1400, 2450, ConstMin='0.0', ConstMax='1.0')
    n('InvGrowth', 'OneMinus', -1200, 2450)
    n('ShrinkAmt', 'Multiply', -1000, 2450)
    n('WPO', 'Multiply', -800, 2300)
    return specs


def _connections():
    """(src_key, src_output, dst_key, dst_input). Output '' = output 0; VectorParameter outputs are
    RGB/R/G/B/A/RGBA (MaterialExpressions.cpp:8148-8154). Inputs use the property names from each
    header (e.g. Normalize 'VectorInput', SmoothStep 'Value', LinearInterpolate 'Alpha')."""
    c = [
        ('P_LightDir', 'RGB', 'LightNorm', 'VectorInput'),
        ('VN', '', 'NdotL', 'A'),
        ('LightNorm', '', 'NdotL', 'B'),
        ('P_ToneThreshold1', '', 'ToneS1', 'Y'),
        ('NdotL', '', 'ToneS1', 'X'),
        ('P_ToneThreshold2', '', 'ToneS2', 'Y'),
        ('NdotL', '', 'ToneS2', 'X'),
        ('P_ShadowColor', 'RGB', 'LerpShadowMid', 'A'),
        ('P_MidColor', 'RGB', 'LerpShadowMid', 'B'),
        ('ToneS1', '', 'LerpShadowMid', 'Alpha'),
        ('LerpShadowMid', '', 'Tone', 'A'),
        ('P_LitColor', 'RGB', 'Tone', 'B'),
        ('ToneS2', '', 'Tone', 'Alpha'),
        ('VN', '', 'Fresnel', 'Normal'),
        ('P_RimThreshold', '', 'RimStep', 'Y'),
        ('Fresnel', '', 'RimStep', 'X'),
        ('P_RimColor', 'RGB', 'RimCol', 'A'),
        ('P_EdgeBrightness', '', 'RimCol', 'B'),
        ('RimCol', '', 'Rim', 'A'),
        ('RimStep', '', 'Rim', 'B'),
        ('P_CrystalColor', 'RGB', 'Glow', 'A'),
        ('P_CrystalGlow', '', 'Glow', 'B'),
        ('TC', '', 'V', 'Input'),
        ('P_CrystalGrowth', '', 'FrontStep', 'Y'),
        ('V', '', 'FrontStep', 'X'),
        ('FrontStep', '', 'GrowthMask', 'Input'),
        ('P_CrystalGrowth', '', 'EdgeLow', 'A'),
        ('P_GrowthEdgeWidth', '', 'EdgeLow', 'B'),
        ('EdgeLow', '', 'EdgeStep', 'Y'),
        ('V', '', 'EdgeStep', 'X'),
        ('GrowthMask', '', 'EdgeBand', 'A'),
        ('EdgeStep', '', 'EdgeBand', 'B'),
        ('P_CrystalGrowth', '', 'EdgeActive', 'Y'),
        ('EdgeBand', '', 'EdgeBandLive', 'A'),
        ('EdgeActive', '', 'EdgeBandLive', 'B'),
        ('EdgeBandLive', '', 'Edge', 'A'),
        ('Tone', '', 'Add1', 'A'),
        ('Rim', '', 'Add1', 'B'),
        ('Add1', '', 'Add2', 'A'),
        ('Glow', '', 'Add2', 'B'),
        ('Add2', '', 'Add3', 'A'),
        ('Edge', '', 'Add3', 'B'),
        ('GrowthMask', '', 'OpMask', 'A'),
        ('PivotZero', '', 'Pivot', 'Input'),
        ('Pivot', '', 'RelPos', 'A'),
        ('WP', '', 'RelPos', 'B'),
        ('P_CrystalGrowth', '', 'GrowthSmooth', 'Value'),
        ('GrowthSmooth', '', 'InvGrowth', 'Input'),
        ('InvGrowth', '', 'ShrinkAmt', 'A'),
        ('P_GrowthScaleAmount', '', 'ShrinkAmt', 'B'),
        ('RelPos', '', 'WPO', 'A'),
        ('ShrinkAmt', '', 'WPO', 'B'),
    ]
    if ENABLE_SPARKLE:
        c += [
            ('Time', '', 'TimeScaled', 'A'),
            ('P_NoiseSpeed', '', 'TimeScaled', 'B'),
            ('VN', '', 'HashDot', 'A'),
            ('HashK', '', 'HashDot', 'B'),
            ('HashDot', '', 'HashFrac', 'Input'),
            ('TimeScaled', '', 'Phase', 'A'),
            ('HashFrac', '', 'Phase', 'B'),
            ('Phase', '', 'Wave', 'Input'),
            ('Wave', '', 'SparkStep', 'X'),
            ('SparkStep', '', 'SparkLit', 'A'),
            ('ToneS2', '', 'SparkLit', 'B'),
            ('SparkLit', '', 'Spark', 'A'),
            ('Add3', '', 'Emissive', 'A'),
            ('Spark', '', 'Emissive', 'B'),
        ]
    if DITHER_MODE == 'ign':
        c += [
            ('ScreenPos', 'PixelPosition', 'IgnDot', 'A'),
            ('IgnK', '', 'IgnDot', 'B'),
            ('IgnDot', '', 'IgnFrac1', 'Input'),
            ('IgnFrac1', '', 'IgnMul', 'A'),
            ('IgnMul', '', 'Ign', 'Input'),
            ('Ign', '', 'DitherStep', 'Y'),
            ('P_CrystalOpacity', '', 'DitherStep', 'X'),
            ('DitherStep', '', 'OpMask', 'B'),
        ]
    return c


# Properties to read back after the build: (node key, property, expected value). Compared with
# _text_matches (numeric when possible) against get_expression_property's ExportText
# (UMaterialNodeService.cpp:1002-1029).
CRITICAL_READBACK = [
    ('Pivot', 'TransformType', 'TRANSFORMPOSSOURCE_TranslatedWorld'),
    ('WP', 'WorldPositionShaderOffset', 'WPT_CameraRelative'),
    ('V', 'G', 'True'),
    ('V', 'R', 'False'),
    ('Fresnel', 'Exponent', '4.0'),
    ('Fresnel', 'BaseReflectFraction', '0.0'),
    ('EdgeActive', 'ConstX', str(GROWTH_EDGE_OFF_ABOVE)),
    ('P_CrystalGrowth', 'ParameterName', 'CrystalGrowth'),
]


def build_graph(report, mat, todos):
    """Create every node, set properties, connect, wire outputs. Returns key->info map."""
    existing = _own_expressions(mat)
    if existing:
        # Structural rebuild in place: the asset, its references and MI overrides (keyed by parameter
        # name) stay intact. MaterialEditingLibrary.h:224 DeleteAllMaterialExpressions.
        MEL.delete_all_material_expressions(mat)
        report.modified(MAT_PATH, 'cleared %d expressions for graph rebuild (%s)' % (len(existing), GRAPH_VERSION))

    specs = _node_specs()
    # batch_create_expressions(path, classes, xs, ys): exactly 4 args; class names resolve to
    # MaterialExpression<Name> exactly (UMaterialNodeService.cpp:365-385, 1547-1600).
    infos = MNS.batch_create_expressions(MAT_PATH, [s[1] for s in specs], [s[2] for s in specs], [s[3] for s in specs])
    if len(infos) != len(specs):
        raise RuntimeError('batch_create_expressions returned %d of %d nodes' % (len(infos), len(specs)))
    nodes = {}
    for spec, info in zip(specs, infos):
        if not info.id:
            raise RuntimeError('failed to create node %s (%s)' % (spec[0], spec[1]))
        nodes[spec[0]] = info
    report.info('created %d expressions in %s' % (len(nodes), MAT_PATH))

    # Optional engine dither function.
    if DITHER_MODE == 'dither_temporal_aa':
        fn = MNS.create_function_call(MAT_PATH, DITHER_TEMPORAL_AA_FN, -1000, 1800)
        if not fn.id:
            raise RuntimeError('create_function_call failed for ' + DITHER_TEMPORAL_AA_FN)
        nodes['Dither'] = fn
        report.info('DitherTemporalAA pins in=%s out=%s' % (list(fn.input_names), list(fn.output_names)))
        todos.append('DitherTemporalAA output range vs OpacityMaskClipValue 0.333 is unverified; check that '
                     'CrystalOpacity=0 hides every pixel, or switch DITHER_MODE to "ign".')

    # Properties (one transaction, one refresh). ImportText path for non-colour values,
    # InitFromString for LinearColor (UMaterialNodeService.cpp:1658-1729).
    ids, names, values = [], [], []
    for key, _cls, _x, _y, props in specs:
        for p, v in props.items():
            ids.append(nodes[key].id)
            names.append(p)
            values.append(v)
    n_set = MNS.batch_set_properties(MAT_PATH, ids, names, values)
    if n_set != len(ids):
        report.error('batch_set_properties set %d of %d properties on %s' % (n_set, len(ids), MAT_PATH))
    else:
        report.info('set %d expression properties' % n_set)

    # Connections. batch_connect_expressions -> MaterialEditingLibrary::ConnectMaterialExpressions
    # (UMaterialNodeService.cpp:1639-1640): output names must be exact; '' = output 0.
    conns = list(_connections())
    if DITHER_MODE == 'dither_temporal_aa':
        fn = nodes['Dither']
        in_names = list(fn.input_names)
        alpha_in = next((s for s in in_names if 'alpha' in s.lower()), in_names[0] if in_names else '')
        out_name = list(fn.output_names)[0] if list(fn.output_names) else ''
        if out_name.startswith('Output_'):
            out_name = ''  # VibeUE placeholder for an unnamed output; MEL needs '' (MEL.cpp:104-161)
        conns += [('P_CrystalOpacity', '', 'Dither', alpha_in), ('Dither', out_name, 'OpMask', 'B')]
    made = MNS.batch_connect_expressions(
        MAT_PATH,
        [nodes[c[0]].id for c in conns], [c[1] for c in conns],
        [nodes[c[2]].id for c in conns], [c[3] for c in conns])
    if made != len(conns):
        report.error('batch_connect_expressions made %d of %d connections (see LogTemp warnings for the failing index)'
                     % (made, len(conns)))
    else:
        report.info('made %d connections' % made)

    # Material outputs: True only after a read-back confirms the wire (UMaterialNodeService.cpp:2759-2844).
    emissive_key = 'Emissive' if ENABLE_SPARKLE else 'Add3'
    for key, prop in ((emissive_key, 'EmissiveColor'), ('OpMask', 'OpacityMask'), ('WPO', 'WorldPositionOffset')):
        if MNS.connect_expression_to_output(MAT_PATH, nodes[key].id, '', prop):
            report.info('wired %s -> %s' % (key, prop))
        else:
            report.error('connect_expression_to_output %s -> %s failed' % (key, prop))

    # Read back the properties that drive correctness.
    for key, prop, want in CRITICAL_READBACK:
        got = MNS.get_expression_property(MAT_PATH, nodes[key].id, prop)
        if not _text_matches(got, want):
            report.error('%s.%s read back %r, wanted %r' % (key, prop, got, want))

    # MaterialNodeService has no layout_expressions UFUNCTION; use MEL (MaterialEditingLibrary.h:380-381).
    MEL.layout_material_expressions(mat)
    report.modified(MAT_PATH, 'graph built (%s, dither=%s, sparkle=%s)' % (GRAPH_VERSION, DITHER_MODE, ENABLE_SPARKLE))
    return nodes


def sync_param_defaults(report, params):
    """Graph is current; update parameter defaults in place when they differ from PARAMS."""
    changed = 0
    for name, (ptype, _group, default, _smin, _smax) in PARAMS.items():
        info = params.get(name)
        if info is None:
            report.error('parameter %s missing from %s' % (name, MAT_PATH))
            continue
        cur = MNS.get_expression_property(MAT_PATH, info.id, 'DefaultValue')
        if ptype == 'Scalar':
            try:
                same = _close(float(cur), default)
            except ValueError:
                same = False
            want = '%.6f' % default
        else:
            same = _close(_parse_color(cur), tuple(default))
            want = _color_str(default)
        if same and not FORCE:
            continue
        if MNS.set_expression_property(MAT_PATH, info.id, 'DefaultValue', want):
            changed += 1
            report.modified(MAT_PATH, '%s default %s -> %s' % (name, cur, want))
        else:
            report.error('set_expression_property %s.DefaultValue=%s failed' % (name, want))
    if not changed:
        report.skipped(MAT_PATH, 'graph %s current; all %d parameter defaults match' % (GRAPH_VERSION, len(PARAMS)))
    return changed


def compile_material(report, mat, built, results):
    # MaterialEditingLibrary.recompile_material blocks until the shader map finishes and returns the
    # error strings (MaterialEditingLibrary.h:339-347). MaterialService.compile_material is async
    # and returns no errors (UMaterialService.cpp:383-410), so it is not used here.
    errs = list(MEL.recompile_material(mat))
    results['compile_errors'] = errs
    if errs:
        try:
            bad = MEL.get_material_error_expressions(mat)  # index-aligned with errs (MEL.h:349-356)
        except Exception:  # noqa: BLE001
            bad = []
        for i, e in enumerate(errs):
            owner = bad[i].get_name() if i < len(bad) and bad[i] is not None else '<material>'
            report.error('COMPILE %s [%s]: %s' % (MAT_PATH, owner, e))
        return False
    report.info('COMPILE_OK %s' % MAT_PATH)
    # Tag only a graph this run actually built, so an old graph is never stamped with the new version.
    if built and EAL.get_metadata_tag(mat, GRAPH_TAG) != GRAPH_VERSION:
        EAL.set_metadata_tag(mat, GRAPH_TAG, GRAPH_VERSION)  # EditorAssetLibrary.h:388
        report.modified(MAT_PATH, 'metadata %s=%s' % (GRAPH_TAG, GRAPH_VERSION))
    return True


def print_graph_evidence(report):
    try:
        outs = MNS.get_output_connections(MAT_PATH)
        wired = sorted(o.property_name for o in outs if o.is_connected)
        report.info('OUTPUTS %s wired=%s' % (MAT_PATH, wired))
        missing = [p for p in REQUIRED_OUTPUTS if p not in wired]
        if missing:
            report.error('outputs not wired on %s: %s' % (MAT_PATH, missing))
        summary = MNS.export_material_graph_summary(MAT_PATH)
        report.info('GRAPH_SUMMARY ' + (summary[:1500] if summary else '<empty>'))
    except Exception as exc:  # noqa: BLE001
        report.error('graph evidence', exc)


# --------------------------------------------------------------------------------------
# Step 4: material instances
# --------------------------------------------------------------------------------------
def ensure_instance(report, mat, name, overrides):
    path = C.MAT_DIR + '/' + name
    if C.asset_exists(path):
        mi = C.load(path)
        if not isinstance(mi, unreal.MaterialInstanceConstant):
            raise RuntimeError('%s exists but is %s' % (path, type(mi).__name__))
        report.skipped(path, 'instance exists')
    else:
        tools = unreal.AssetToolsHelpers.get_asset_tools()
        # MaterialInstanceConstantFactoryNew.InitialParent is a flagless UPROPERTY()
        # (MaterialInstanceConstantFactoryNew.h:19-20), so set the parent through MEL below instead.
        mi = tools.create_asset(name, C.MAT_DIR, unreal.MaterialInstanceConstant,
                                unreal.MaterialInstanceConstantFactoryNew())
        if mi is None:
            raise RuntimeError('create_asset returned None for ' + path)
        report.created(path)

    parent = mi.get_editor_property('parent')
    if parent is None or parent.get_path_name() != mat.get_path_name():
        MEL.set_material_instance_parent(mi, mat)  # MaterialEditingLibrary.h:528-529
        parent = mi.get_editor_property('parent')
        if parent is None or parent.get_path_name() != mat.get_path_name():
            raise RuntimeError('parent of %s did not take' % path)
        report.modified(path, 'parent -> ' + MAT_PATH)

    changed = []
    for pname, value in overrides.items():
        ptype = PARAMS[pname][0]
        # MEL setters return True for any non-null instance and do not validate the name
        # (MaterialEditingLibrary.h:595-600), so compare before and read back after.
        if ptype == 'Scalar':
            cur = MEL.get_material_instance_scalar_parameter_value(mi, pname)
            overridden = MEL.is_material_instance_parameter_overridden(mi, pname)
            if overridden and _close(cur, value) and not FORCE:
                continue
            MEL.set_material_instance_scalar_parameter_value(mi, pname, float(value))
            now = MEL.get_material_instance_scalar_parameter_value(mi, pname)
            if not _close(now, value):
                report.error('%s.%s read back %s, wanted %s' % (path, pname, now, value))
                continue
        else:
            cur = _lc_tuple(MEL.get_material_instance_vector_parameter_value(mi, pname))
            overridden = MEL.is_material_instance_parameter_overridden(mi, pname)
            if overridden and _close(cur, tuple(value)) and not FORCE:
                continue
            MEL.set_material_instance_vector_parameter_value(mi, pname, unreal.LinearColor(*value))
            now = _lc_tuple(MEL.get_material_instance_vector_parameter_value(mi, pname))
            if not _close(now, tuple(value)):
                report.error('%s.%s read back %s, wanted %s' % (path, pname, now, value))
                continue
        changed.append(pname)
    if changed:
        MEL.update_material_instance(mi)  # MaterialEditingLibrary.h:636
        report.modified(path, 'parameters ' + ', '.join(changed))
    elif overrides:
        report.skipped(path, 'all %d overrides already match' % len(overrides))
    else:
        report.skipped(path, 'no overrides (inherits %s defaults)' % MAT_NAME)
    return mi


# --------------------------------------------------------------------------------------
# Step 5: mesh assignment
# --------------------------------------------------------------------------------------
def assign_to_meshes(report, mis_by_role, data):
    assigned = {}
    parts = data.get('cluster_parts') or []
    if not parts:
        report.error('data JSON has no cluster_parts (%s)' % C.DATA_PATH)
        return assigned
    for part in parts:
        name = part.get('name')
        try:
            if int(part.get('faces', 0)) <= 0:
                report.skipped(str(name), 'part has 0 faces (not imported)')
                continue
            role = part.get('material_role')
            mi = mis_by_role.get(role)
            if mi is None:
                report.error('part %s: no instance for material_role %r' % (name, role))
                continue
            mesh_path = C.CLUSTER_DIR + '/' + name
            if not C.asset_exists(mesh_path):
                report.error('mesh %s missing; run ice_slash_01 import first' % mesh_path)
                continue
            mesh = C.load(mesh_path)
            if not isinstance(mesh, unreal.StaticMesh):
                report.error('%s is %s, not a StaticMesh' % (mesh_path, type(mesh).__name__))
                continue
            # static_materials comes back as a copy (StaticMesh.h:1114-1115 BlueprintGetter); read its
            # length only, and write through StaticMesh.SetMaterial (StaticMesh.h:2408-2409), which
            # runs PreEditChange/PostEditChange and dirties the package.
            n_slots = len(mesh.get_editor_property('static_materials'))
            if n_slots == 0:
                report.error('%s has no material slots' % mesh_path)
                continue
            changed = []
            for i in range(n_slots):
                cur = mesh.get_material(i)  # StaticMesh.h:2257-2258
                if cur is not None and cur.get_path_name() == mi.get_path_name() and not FORCE:
                    continue
                mesh.set_material(i, mi)
                now = mesh.get_material(i)
                if now is None or now.get_path_name() != mi.get_path_name():
                    report.error('%s slot %d did not take %s' % (mesh_path, i, mi.get_name()))
                    continue
                changed.append(i)
            if changed:
                report.modified(mesh_path, 'slots %s -> %s' % (changed, mi.get_name()))
            else:
                report.skipped(mesh_path, 'all %d slot(s) already %s' % (n_slots, mi.get_name()))
            assigned[mesh_path] = {'role': role, 'instance': C.MAT_DIR + '/' + mi.get_name(), 'slots': n_slots}
        except Exception as exc:  # noqa: BLE001
            report.error('assign material to part %s' % name, exc)
    return assigned


# --------------------------------------------------------------------------------------
# Step 6: manifest
# --------------------------------------------------------------------------------------
def write_manifest(report, entry):
    # Merge under our own key, so slash-material entries written by step 03 survive whether
    # update_manifest merges at the section level or replaces the section.
    current = C.read_manifest().get('materials') or {}
    merged = dict(current) if isinstance(current, dict) else {}
    merged['crystal'] = entry
    C.update_manifest('materials', merged)
    report.info('manifest materials.crystal updated (%s)' % C.MANIFEST_PATH)


# --------------------------------------------------------------------------------------
def main():
    report = C.Report(SCRIPT_NAME)
    todos = []
    prop_results = {}
    compiled_ok = False
    built = False
    mat = None
    mis_by_role = {}
    assigned = {}

    if DITHER_MODE not in ('ign', 'dither_temporal_aa'):
        report.error('unknown DITHER_MODE %r' % DITHER_MODE)
    if not ENABLE_SPARKLE:
        todos.append('NoiseSpeed sparkle disabled (ENABLE_SPARKLE=False); NoiseSpeed exists but is unused.')

    # 1. material asset
    try:
        mat, created = ensure_material(report)
    except Exception as exc:  # noqa: BLE001
        report.error('ensure material ' + MAT_PATH, exc)
        created = False

    if mat is not None:
        # 2. material-level properties
        set_material_properties(report, prop_results)

        # 3. graph: build when REBUILD or when the material has no expressions of its own (new
        #    asset); otherwise verify it and sync parameter defaults in place (never delete+recreate
        #    just to change a value).
        try:
            if REBUILD or created or not _own_expressions(mat):
                report.info('building graph (%s)' % ('REBUILD flag' if REBUILD else 'empty graph'))
                build_graph(report, mat, todos)
                built = True
            else:
                tag, params, outs = graph_state(mat)
                missing_params = [p for p in PARAMS if p not in params]
                missing_outs = [o for o in REQUIRED_OUTPUTS if o not in outs]
                for p in missing_params:
                    report.error('parameter %s missing in %s (set REBUILD = True to rebuild the graph)' % (p, MAT_PATH))
                for o in missing_outs:
                    report.error('output %s not connected in %s (set REBUILD = True)' % (o, MAT_PATH))
                if tag != GRAPH_VERSION:
                    todos.append('%s graph version is %r, script is %s: run with REBUILD = True to refresh the graph'
                                 % (MAT_PATH, tag, GRAPH_VERSION))
                sync_param_defaults(report, params)
        except Exception as exc:  # noqa: BLE001
            report.error('build/sync graph ' + MAT_PATH, exc)

        # compile + evidence
        try:
            compiled_ok = compile_material(report, mat, built, prop_results)
        except Exception as exc:  # noqa: BLE001
            report.error('recompile ' + MAT_PATH, exc)
        print_graph_evidence(report)

        # 4. instances
        for mi_name, (role, overrides) in INSTANCES.items():
            try:
                mis_by_role[role] = ensure_instance(report, mat, mi_name, overrides)
            except Exception as exc:  # noqa: BLE001
                report.error('instance ' + mi_name, exc)

    # 5. assignment
    try:
        data = C.load_data()
        assigned = assign_to_meshes(report, mis_by_role, data)
    except Exception as exc:  # noqa: BLE001
        report.error('mesh assignment', exc)

    for t in todos:
        report.todo(t)

    # 6. manifest
    try:
        write_manifest(report, {
            'material': MAT_PATH,
            'graph_version': GRAPH_VERSION,
            'graph_rebuilt_this_run': built,
            'compiled_ok': compiled_ok,
            'compile_errors': prop_results.get('compile_errors', []),
            'blend_mode': 'BLEND_Masked',
            'shading_model': 'MSM_Unlit',
            'opacity_mask_clip': 0.333,
            'two_sided': False,
            'dither_mode': DITHER_MODE,
            'sparkle': ENABLE_SPARKLE,
            'pivot_source': 'TransformPosition(Local->TranslatedWorld, 0) (ObjectPositionWS = bounds origin in 5.9)',
            'parameters': dict((k, {'type': v[0], 'group': v[1], 'default': list(v[2]) if isinstance(v[2], tuple) else v[2]})
                               for k, v in PARAMS.items()),
            'instances': dict((role, C.MAT_DIR + '/' + n) for n, (role, _o) in INSTANCES.items()),
            'instance_overrides': dict((n, dict((p, list(v) if isinstance(v, tuple) else v) for p, v in o.items()))
                                       for n, (_r, o) in INSTANCES.items()),
            'assignments': assigned,
            'todo': todos,
        })
    except Exception as exc:  # noqa: BLE001
        report.error('manifest update', exc)

    # 7. save: save_all(report) saves only this run's and the IceSlash root's dirty packages,
    #    never the other agent's work (ice_slash_common.py save_all docstring).
    try:
        C.save_all(report)
    except Exception as exc:  # noqa: BLE001
        report.error('save_all', exc)

    report.finish()


if __name__ == '__main__':
    main()
