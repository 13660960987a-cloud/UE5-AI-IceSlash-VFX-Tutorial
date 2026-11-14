"""IceSlash step 03: cartoon slash-arc material, its instances and the arc mesh slots.

Run inside the UE 5.9 editor (synchronous, idempotent):
    import runpy; runpy.run_path('/Users/mengmeile/Downloads/lianxi/m/Tools/IceSlash/ice_slash_03_material_slash.py', run_name='__main__')

Run order: 01 import, 02 anim+sockets, -> 03 slash material <-, 04 crystal material,
05 niagara, 06 showcase level, 07 sequence. This script needs 01 to have imported the
SM_SlashArc_0N meshes and the T_SlashArc_* textures.

What it creates or enforces:
  * C.MAT_DIR/M_SlashArc_v2: Unlit, Translucent (not Additive, so the cobalt brush edge and
    the saturated teal survive), TwoSided, MD_Surface. The graph:
      UV2       = (U, lerp(V, 1 - V, FlipV))                      U: 0 = head, 1 = tail
      Head      = SlashProgress * (1 + SlashWidth); Tail = Head - SlashWidth
      reveal    = smoothstep(0, soft, Head - U) * smoothstep(0, soft, U - Tail)
                  soft = max(SlashSoftness, 0.001)
      noise     = MaskTex.B
      dissolve  = smoothstep(DissolveAmount - 0.02, DissolveAmount + 0.02, noise)
      edge      = dissolve * (1 - smoothstep(D + 0.02, D + 0.08, noise)) * saturate(D * 50)
      rim       = smoothstep(0.68, 0.88, BaseTex.R)
      glow      = (GlowTex.rgb * GlowTex.a + rim) * EdgeColor * GlowIntensity
      noiseMod  = lerp(0.85, 1.15, NoiseTex(Panner along U at NoiseSpeed).R)
      Emissive  = BaseTex.rgb * CoreColor * EmissiveBoost * noiseMod + glow + edge * EdgeColor * 4
      Opacity   = saturate(BaseTex.a * MaskTex.G * reveal * dissolve * Opacity)
  * C.MAT_DIR/MI_SlashArc_01..05 (parent M_SlashArc_v2) with per-arc GlowIntensity / CoreColor.
  * SM_SlashArc_0N material slot 0 = MI_SlashArc_0N.
  * Manifest section 'materials' -> key 'slash'.

Idempotency: an existing material is only verified (parameters, outputs, base properties)
unless REBUILD = True, which clears and rebuilds the graph IN PLACE (the asset, its package
and every reference to it are kept). Instances are created only when missing; their values
and the mesh slots are enforced on every run (written only when they differ, unless FORCE).
"""

import sys
import importlib

import unreal

TOOLS_DIR = '/Users/mengmeile/Downloads/lianxi/m/Tools/IceSlash'
if TOOLS_DIR not in sys.path:
    sys.path.insert(0, TOOLS_DIR)
import ice_slash_common as C  # noqa: E402
importlib.reload(C)

# ---------------------------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------------------------
SCRIPT_NAME = 'ice_slash_03_material_slash'
REBUILD = False   # True: delete every expression of M_SlashArc_v2 and rebuild the graph in place.
FORCE = False     # True: re-write base properties, MI values and mesh slots even when they match.

GRAPH_VERSION = 'slash_v4.4'                 # stored as asset metadata; bump when the graph changes
GRAPH_VERSION_TAG = 'IceSlashGraphVersion'

MAT_NAME = 'M_SlashArc_v2'
MAT_PATH = C.MAT_DIR + '/' + MAT_NAME
ARC_COUNT = 5
MI_PREFIX = 'MI_SlashArc_'       # static-mesh actors / previews (SlashProgress set by hand or Sequencer)
NS_MI_PREFIX = 'MI_SlashArcNS_'  # Niagara mesh particles: reveal driven by the particle's normalised age
MESH_PREFIX = 'SM_SlashArc_'
MANIFEST_KEY = 'slash'           # section of manifest['materials'] this module writes
REVEAL_CONTRACT = {
    'param': 'SlashProgress', 'hidden': 0.0, 'full_arc': 0.5, 'tail_gone': 1.0,
    'note': 'Head = SlashProgress*(1+SlashWidth); window [Head-SlashWidth, Head] along UV.x',
}

# Base material properties (MaterialService.set_property names/values; always the FULL enum
# names because the resolver falls back to suffix and substring matching,
# Plugins/VibeUE/Source/VibeUE/Private/PythonAPI/UMaterialService.cpp:208-257).
MATERIAL_PROPERTIES = [
    ('MaterialDomain', 'MD_Surface'),
    ('BlendMode', 'BLEND_AlphaComposite'),   # premultiplied: painted layer 'over' + additive glow
    ('ShadingModel', 'MSM_Unlit'),
    ('TwoSided', 'true'),
]

# name, default, slider min, slider max, group
SCALAR_PARAMS = [
    ('SlashProgress', 0.5, 0.0, 1.2, 'SlashControl'),
    ('SlashWidth', 1.0, 0.05, 1.0, 'SlashControl'),
    ('SlashSoftness', 0.04, 0.001, 0.25, 'SlashControl'),
    ('Opacity', 1.0, 0.0, 1.0, 'SlashControl'),
    ('DissolveAmount', 0.0, 0.0, 1.0, 'Dissolve'),
    ('GlowIntensity', 1.5, 0.0, 30.0, 'Glow'),
    ('EmissiveBoost', 1.15, 0.0, 10.0, 'Glow'),
    ('BodyMaskAmount', 1.0, 0.0, 1.0, 'Blade'),
    ('LineBoost', 1.0, 0.0, 10.0, 'Blade'),
    ('GlowBoost', 1.0, 0.0, 10.0, 'Glow'),
    ('GlowOcclude', 0.25, 0.0, 1.0, 'Glow'),
    ('UseParticleTime', 0.0, 0.0, 1.0, 'Niagara'),
    ('TailSoftness', 0.04, 0.001, 1.0, 'SlashControl'),
    ('TailNoise', 0.0, 0.0, 1.0, 'SlashControl'),
]
# name, default RGBA, group
VECTOR_PARAMS = [
    ('EdgeColor', (1.0, 0.62, 0.22, 1.0), 'Color'),
    ('CoreColor', (1.0, 1.0, 1.0, 1.0), 'Color'),
]
# parameter name, texture asset name, sampler types the lead expects (informational: the real
# sampler type is derived from the imported texture's settings, see _expected_sampler_type)
TEXTURE_PARAMS = [
    ('SheetTex', 'T_SlashBlade_Painted', ('SAMPLERTYPE_Color',)),
    ('MaskTex', 'T_SlashArc_Mask', ('SAMPLERTYPE_LinearColor', 'SAMPLERTYPE_Masks')),
    ('BodyMaskTex', 'T_SlashBlade_BodyMask', ('SAMPLERTYPE_Masks', 'SAMPLERTYPE_LinearColor')),
    ('GlowTex', 'T_SlashBlade_Emissive', ('SAMPLERTYPE_Color',)),
]
ALL_PARAM_NAMES = [p[0] for p in SCALAR_PARAMS] + [p[0] for p in VECTOR_PARAMS] + [p[0] for p in TEXTURE_PARAMS]

# Per-instance overrides; every other parameter stays at the parent default.
MI_VALUES = {
    1: {'GlowIntensity': 1.4, 'CoreColor': (1.0, 1.0, 1.0, 1.0)},
    2: {'GlowIntensity': 1.5, 'CoreColor': (0.95, 1.0, 1.05, 1.0)},
    3: {'GlowIntensity': 1.6, 'CoreColor': (1.05, 1.05, 1.1, 1.0)},
    4: {'GlowIntensity': 1.4, 'CoreColor': (0.95, 1.0, 1.0, 1.0)},
    5: {'GlowIntensity': 1.5, 'CoreColor': (1.0, 1.0, 1.0, 1.0)},
}

# Niagara instances: same look, progress = sqrt(particle normalised age) -> blade fully swept out
# at 25 % of the particle lifetime, then erased tail-first until the particle dies.
# The trailing edge is soft and broken up by noise (brushy erase instead of a straight cut);
# SlashWidth > 1 keeps the whole blade inside the window while it is fully swept out.
NS_MI_VALUES = {i: dict(v, UseParticleTime=1.0, SlashWidth=1.35, TailSoftness=0.35, TailNoise=0.3)
                for i, v in MI_VALUES.items()}

MS = unreal.MaterialService
MNS = unreal.MaterialNodeService
MEL = unreal.MaterialEditingLibrary
EAL = unreal.EditorAssetLibrary


# ---------------------------------------------------------------------------------------------
# Graph specification
# ---------------------------------------------------------------------------------------------
# Nodes: key -> (expression class short name, x, y). Class names must match
# MaterialExpression<Name> exactly (UMaterialNodeService.cpp:365-385; 'Lerp' does not exist).
# v3 look (reference video): UV2 = (U along the slash, V2 across: 0 = outer edge, 1 = inner edge).
# Outer gold rim with a white-hot core, navy-to-blue body, tiling cyan line-art swirls, and a
# jagged brush-eroded inner edge. Everything except the swirl/brush textures is procedural in V,
# so nothing stretches along the blade.
# v4 sheet mode (reference video: every slash is a flat sheet carrying a painted crescent with
# colour + alpha). UV0 samples the painting (laid along the arc by build_blade_sheets.py without
# distortion); UV1.x is the sweep parameter (0 = start/tail of the swing, 1 = end/head) used by
# the reveal window, so the painting itself never moves.
NODES = [
    ('P_SlashProgress', 'ScalarParameter', -2400, -900),
    ('P_SlashWidth', 'ScalarParameter', -2400, -780),
    ('P_SlashSoftness', 'ScalarParameter', -2400, -660),
    ('P_Opacity', 'ScalarParameter', -2400, 900),
    ('P_DissolveAmount', 'ScalarParameter', -2400, 500),
    ('P_GlowIntensity', 'ScalarParameter', -900, -320),
    ('P_EmissiveBoost', 'ScalarParameter', -900, -600),
    ('P_EdgeColor', 'VectorParameter', -1100, -200),
    ('P_CoreColor', 'VectorParameter', -1100, -760),
    ('TexCoord', 'TextureCoordinate', -2400, -300),
    ('TexCoord1', 'TextureCoordinate', -2400, -1100),
    ('Sweep', 'ComponentMask', -2200, -1100),
    ('T_SheetTex', 'TextureSampleParameter2D', -1700, -400),
    ('T_MaskTex', 'TextureSampleParameter2D', -1700, 300),
    # reveal window along the sweep
    ('WidthPlusOne', 'Add', -2200, -820),
    ('Head', 'Multiply', -2000, -880),
    ('Tail', 'Subtract', -1800, -800),
    ('HeadDist', 'Subtract', -1600, -940),
    ('TailDist', 'Subtract', -1600, -820),
    ('SoftClamp', 'Max', -2200, -660),
    ('HeadMask', 'SmoothStep', -1400, -940),
    ('TailMask', 'SmoothStep', -1400, -820),
    ('Reveal', 'Multiply', -1200, -880),
    # dissolve
    ('DisMin', 'Subtract', -2200, 440),
    ('DisMax', 'Add', -2200, 540),
    ('DisEdgeMax', 'Add', -2200, 640),
    ('DissolveMask', 'SmoothStep', -1300, 440),
    ('EdgeOuter', 'SmoothStep', -1300, 600),
    ('EdgeInv', 'OneMinus', -1100, 600),
    ('EdgeBand', 'Multiply', -900, 520),
    ('EdgeGateMul', 'Multiply', -2200, 760),
    ('EdgeGate', 'Saturate', -2000, 760),
    ('DissolveEdge', 'Multiply', -700, 560),
    ('EdgeTint', 'Multiply', -500, 480),
    ('EdgeTint4', 'Multiply', -300, 480),
    # warm bright rim -> extra emission for bloom
    ('RminusB', 'Subtract', -1300, -260),
    ('RBx3', 'Multiply', -1100, -260),
    ('RBsat', 'Saturate', -900, -260),
    ('RimSS', 'SmoothStep', -1100, -140),
    ('RimMask', 'Multiply', -700, -200),
    ('RimCol', 'Multiply', -500, -260),
    ('RimEm', 'Multiply', -300, -260),
    # painted colour
    ('E1', 'Multiply', -900, -700),
    ('E2', 'Multiply', -700, -680),
    ('Em1', 'Add', -100, -500),
    ('Emissive', 'Add', 100, -400),
    # opacity
    ('O1', 'Multiply', -900, 820),
    ('O2', 'Multiply', -700, 820),
    ('O3', 'Multiply', -500, 820),
    ('OpacityOut', 'Saturate', -300, 820),
    # v4.2 three stacked layers on the same UV0 (bake_blade_layers.py):
    #   colour sheet x body mask (hollow inner body) + line-art boost + emissive glow sheet.
    # Output is premultiplied (BLEND_AlphaComposite): the painted layer covers the background,
    # the glow layer adds light on top and barely occludes.
    ('T_BodyMaskTex', 'TextureSampleParameter2D', -1700, 1000),
    ('T_GlowTex', 'TextureSampleParameter2D', -1700, 1300),
    ('P_BodyMaskAmount', 'ScalarParameter', -1500, 1160),
    ('P_LineBoost', 'ScalarParameter', -900, -1000),
    ('P_GlowBoost', 'ScalarParameter', -500, 1400),
    ('P_GlowOcclude', 'ScalarParameter', -900, 1400),
    ('VisLerp', 'LinearInterpolate', -1300, 1040),
    ('A2', 'Multiply', -1100, 900),
    ('GA', 'Multiply', -1100, 1300),
    ('GOcc', 'Multiply', -700, 1300),
    ('OpSum', 'Add', -500, 900),
    ('LineEm', 'Multiply', -700, -1000),
    ('LineEmB', 'Multiply', -500, -1000),
    ('Em2', 'Add', 300, -500),
    ('PaintPre', 'Multiply', 500, -400),
    ('GlowCol', 'Multiply', -900, 1500),
    ('GlowEm', 'Multiply', -300, 1500),
    ('EmOut', 'Add', 700, -300),
    # v4.3 Niagara: particle age drives the sweep, particle colour tints / fades the whole blade
    ('P_UseParticleTime', 'ScalarParameter', -2900, -780),
    ('PRT', 'ParticleRelativeTime', -3100, -960),
    ('PRTpow', 'Power', -2900, -960),
    ('ProgSel', 'LinearInterpolate', -2650, -960),
    ('PCol', 'ParticleColor', 500, 100),
    ('EmPC1', 'Multiply', 900, -300),
    ('EmPC2', 'Multiply', 1100, -300),
    ('OpPC', 'Multiply', -400, 1000),
    # v4.4 soft, noisy trailing edge
    ('P_TailSoftness', 'ScalarParameter', -2400, -540),
    ('P_TailNoise', 'ScalarParameter', -2400, -420),
    ('TailSoftClamp', 'Max', -2200, -540),
    ('TailNoiseC', 'Subtract', -2000, -420),
    ('TailNoiseS', 'Multiply', -1800, -420),
    ('TailDistN', 'Add', -1600, -700),
]

CONST_SETS = [
    ('TexCoord', 'CoordinateIndex', '0'),
    ('TexCoord1', 'CoordinateIndex', '1'),
    ('Sweep', 'R', 'True'), ('Sweep', 'G', 'False'), ('Sweep', 'B', 'False'), ('Sweep', 'A', 'False'),
    ('WidthPlusOne', 'ConstB', '1.0'),
    ('SoftClamp', 'ConstB', '0.001'),
    ('HeadMask', 'ConstMin', '0.0'),
    ('TailMask', 'ConstMin', '0.0'),
    ('DisMin', 'ConstB', '0.02'),
    ('DisMax', 'ConstB', '0.02'),
    ('DisEdgeMax', 'ConstB', '0.08'),
    ('EdgeGateMul', 'ConstB', '50.0'),
    ('EdgeTint4', 'ConstB', '4.0'),
    ('RBx3', 'ConstB', '3.0'),
    ('RimSS', 'ConstMin', '0.80'), ('RimSS', 'ConstMax', '1.0'),
    ('VisLerp', 'ConstA', '1.0'),
    ('PRTpow', 'ConstExponent', '0.5'),
    ('TailSoftClamp', 'ConstB', '0.001'),
    ('TailNoiseC', 'ConstB', '0.5'),
]


def _color_text(rgba):
    """'(R=..,G=..,B=..,A=..)' is the only colour form batch_set_properties accepts
    (FLinearColor::InitFromString, UMaterialNodeService.cpp:1690-1704)."""
    return '(R=%.4f,G=%.4f,B=%.4f,A=%.4f)' % tuple(rgba)


def _property_sets():
    """(node key, C++ property name, value text) for batch_set_properties
    (FindPropertyByName + ImportText, UMaterialNodeService.cpp:1658-1729)."""
    sets = []
    for name, default, smin, smax, group in SCALAR_PARAMS:
        key = 'P_' + name
        sets += [(key, 'ParameterName', name), (key, 'Group', group),
                 (key, 'DefaultValue', '%.6f' % default),
                 (key, 'SliderMin', '%.6f' % smin), (key, 'SliderMax', '%.6f' % smax)]
    for name, rgba, group in VECTOR_PARAMS:
        key = 'P_' + name
        sets += [(key, 'ParameterName', name), (key, 'Group', group),
                 (key, 'DefaultValue', _color_text(rgba))]
    for name, _tex, _st in TEXTURE_PARAMS:
        sets += [('T_' + name, 'ParameterName', name), ('T_' + name, 'Group', 'Textures')]
    sets += CONST_SETS
    return sets


# (source key, source output, target key, target input). Output names: '' = output 0, texture
# samples and VectorParameter expose RGB/R/G/B/A (MaterialExpressions.cpp:2611-2617). Input names
# are the graph names (MaterialEditingLibrary.cpp:55-101): UVs, A, B, Alpha, Min, Max, Value,
# Coordinate, Time; '' = input 0 for single-input nodes.
CONNECTIONS = [
    ('TexCoord', '', 'T_SheetTex', 'UVs'),
    ('TexCoord', '', 'T_MaskTex', 'UVs'),
    ('TexCoord1', '', 'Sweep', ''),
    # reveal window
    ('P_SlashWidth', '', 'WidthPlusOne', 'A'),
    ('PRT', '', 'PRTpow', 'Base'),
    ('P_SlashProgress', '', 'ProgSel', 'A'),
    ('PRTpow', '', 'ProgSel', 'B'),
    ('P_UseParticleTime', '', 'ProgSel', 'Alpha'),
    ('ProgSel', '', 'Head', 'A'),
    ('WidthPlusOne', '', 'Head', 'B'),
    ('Head', '', 'Tail', 'A'),
    ('P_SlashWidth', '', 'Tail', 'B'),
    ('Head', '', 'HeadDist', 'A'),
    ('Sweep', '', 'HeadDist', 'B'),
    ('Sweep', '', 'TailDist', 'A'),
    ('Tail', '', 'TailDist', 'B'),
    ('P_SlashSoftness', '', 'SoftClamp', 'A'),
    ('SoftClamp', '', 'HeadMask', 'Max'),
    ('HeadDist', '', 'HeadMask', 'Value'),
    ('P_TailSoftness', '', 'TailSoftClamp', 'A'),
    ('TailSoftClamp', '', 'TailMask', 'Max'),
    ('T_MaskTex', 'B', 'TailNoiseC', 'A'),
    ('TailNoiseC', '', 'TailNoiseS', 'A'),
    ('P_TailNoise', '', 'TailNoiseS', 'B'),
    ('TailDist', '', 'TailDistN', 'A'),
    ('TailNoiseS', '', 'TailDistN', 'B'),
    ('TailDistN', '', 'TailMask', 'Value'),
    ('HeadMask', '', 'Reveal', 'A'),
    ('TailMask', '', 'Reveal', 'B'),
    # dissolve
    ('P_DissolveAmount', '', 'DisMin', 'A'),
    ('P_DissolveAmount', '', 'DisMax', 'A'),
    ('P_DissolveAmount', '', 'DisEdgeMax', 'A'),
    ('DisMin', '', 'DissolveMask', 'Min'),
    ('DisMax', '', 'DissolveMask', 'Max'),
    ('T_MaskTex', 'B', 'DissolveMask', 'Value'),
    ('DisMax', '', 'EdgeOuter', 'Min'),
    ('DisEdgeMax', '', 'EdgeOuter', 'Max'),
    ('T_MaskTex', 'B', 'EdgeOuter', 'Value'),
    ('EdgeOuter', '', 'EdgeInv', ''),
    ('DissolveMask', '', 'EdgeBand', 'A'),
    ('EdgeInv', '', 'EdgeBand', 'B'),
    ('P_DissolveAmount', '', 'EdgeGateMul', 'A'),
    ('EdgeGateMul', '', 'EdgeGate', ''),
    ('EdgeBand', '', 'DissolveEdge', 'A'),
    ('EdgeGate', '', 'DissolveEdge', 'B'),
    ('DissolveEdge', '', 'EdgeTint', 'A'),
    ('P_EdgeColor', 'RGB', 'EdgeTint', 'B'),
    ('EdgeTint', '', 'EdgeTint4', 'A'),
    # rim glow
    ('T_SheetTex', 'R', 'RminusB', 'A'),
    ('T_SheetTex', 'B', 'RminusB', 'B'),
    ('RminusB', '', 'RBx3', 'A'),
    ('RBx3', '', 'RBsat', ''),
    ('T_SheetTex', 'R', 'RimSS', 'Value'),
    ('RimSS', '', 'RimMask', 'A'),
    ('RBsat', '', 'RimMask', 'B'),
    ('RimMask', '', 'RimCol', 'A'),
    ('P_EdgeColor', 'RGB', 'RimCol', 'B'),
    ('RimCol', '', 'RimEm', 'A'),
    ('P_GlowIntensity', '', 'RimEm', 'B'),
    # painted colour
    ('T_SheetTex', 'RGB', 'E1', 'A'),
    ('P_CoreColor', 'RGB', 'E1', 'B'),
    ('E1', '', 'E2', 'A'),
    ('P_EmissiveBoost', '', 'E2', 'B'),
    ('E2', '', 'Em1', 'A'),
    ('RimEm', '', 'Em1', 'B'),
    ('Em1', '', 'Emissive', 'A'),
    ('EdgeTint4', '', 'Emissive', 'B'),
    ('TexCoord', '', 'T_BodyMaskTex', 'UVs'),
    ('TexCoord', '', 'T_GlowTex', 'UVs'),
    # reveal x dissolve x opacity (applies to the paint and the glow alike)
    ('Reveal', '', 'O1', 'A'),
    ('DissolveMask', '', 'O1', 'B'),
    ('O1', '', 'O2', 'A'),
    ('P_Opacity', '', 'O2', 'B'),
    # paint alpha x body mask
    ('T_BodyMaskTex', 'R', 'VisLerp', 'B'),
    ('P_BodyMaskAmount', '', 'VisLerp', 'Alpha'),
    ('T_SheetTex', 'A', 'A2', 'A'),
    ('VisLerp', '', 'A2', 'B'),
    ('A2', '', 'O3', 'A'),
    ('O2', '', 'O3', 'B'),
    # glow layer
    ('T_GlowTex', 'A', 'GA', 'A'),
    ('O2', '', 'GA', 'B'),
    ('GA', '', 'GOcc', 'A'),
    ('P_GlowOcclude', '', 'GOcc', 'B'),
    ('O3', '', 'OpSum', 'A'),
    ('GOcc', '', 'OpSum', 'B'),
    ('OpSum', '', 'OpPC', 'A'),
    ('PCol', 'A', 'OpPC', 'B'),
    ('OpPC', '', 'OpacityOut', ''),
    # line-art boost
    ('T_SheetTex', 'RGB', 'LineEm', 'A'),
    ('T_BodyMaskTex', 'G', 'LineEm', 'B'),
    ('LineEm', '', 'LineEmB', 'A'),
    ('P_LineBoost', '', 'LineEmB', 'B'),
    ('Emissive', '', 'Em2', 'A'),
    ('LineEmB', '', 'Em2', 'B'),
    # premultiplied output
    ('Em2', '', 'PaintPre', 'A'),
    ('O3', '', 'PaintPre', 'B'),
    ('T_GlowTex', 'RGB', 'GlowCol', 'A'),
    ('GA', '', 'GlowCol', 'B'),
    ('GlowCol', '', 'GlowEm', 'A'),
    ('P_GlowBoost', '', 'GlowEm', 'B'),
    ('PaintPre', '', 'EmOut', 'A'),
    ('GlowEm', '', 'EmOut', 'B'),
    ('EmOut', '', 'EmPC1', 'A'),
    ('PCol', '', 'EmPC1', 'B'),
    ('EmPC1', '', 'EmPC2', 'A'),
    ('PCol', 'A', 'EmPC2', 'B'),
]

# (node key, node output, material property) for connect_expression_to_output
# (property names: UMaterialNodeService.cpp:422-474).
OUTPUTS = [
    ('EmPC2', '', 'EmissiveColor'),
    ('OpacityOut', '', 'Opacity'),
]


# ---------------------------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------------------------
def _enum_name(value):
    """Upper-case enum member name of an unreal enum value (falls back to str())."""
    name = getattr(value, 'name', None)
    return (name if isinstance(name, str) else str(value)).upper()


def _expected_sampler_type(tex):
    """Python mirror of MaterialExpressionUtils::GetSamplerTypeForTexture
    (Engine/Source/Runtime/Engine/Public/Materials/MaterialExpressionUtils.cpp:14-49).
    Returns the C++ enum name, e.g. 'SAMPLERTYPE_LinearColor'."""
    srgb = bool(tex.get_editor_property('srgb'))
    comp = _enum_name(tex.get_editor_property('compression_settings'))
    lod = _enum_name(tex.get_editor_property('lod_group'))
    virtual = False
    try:
        virtual = bool(tex.get_editor_property('virtual_texture_streaming'))
    except Exception:
        virtual = False
    if '8BIT' in lod or '16BIT' in lod:
        return 'SAMPLERTYPE_Data'
    pre = 'SAMPLERTYPE_Virtual' if virtual else 'SAMPLERTYPE_'
    if 'NORMALMAP' in comp:
        return pre + 'Normal'
    if 'GRAYSCALE' in comp:
        return pre + ('Grayscale' if srgb else 'LinearGrayscale')
    if 'TC_ALPHA' in comp:
        return pre + 'Alpha'
    if 'MASKS' in comp:
        return pre + 'Masks'
    if 'DISTANCE' in comp:
        return 'SAMPLERTYPE_DistanceFieldFont'
    return pre + ('Color' if srgb else 'LinearColor')


def _colors_equal(a, b, tol=1e-4):
    return (abs(a.r - b[0]) < tol and abs(a.g - b[1]) < tol
            and abs(a.b - b[2]) < tol and abs(a.a - b[3]) < tol)


def _path_of(obj):
    return obj.get_path_name() if obj is not None else ''


# ---------------------------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------------------------
def step_ensure_material(report, state):
    """Create M_SlashArc_v2 if missing. Returns the UMaterial or None."""
    C.ensure_dir(C.MAT_DIR)
    if C.asset_exists(MAT_PATH):
        mat = C.load(MAT_PATH)
        if not isinstance(mat, unreal.Material):
            report.error('%s exists but is %s, not a Material' % (MAT_PATH, type(mat).__name__))
            return None
        report.skipped(MAT_PATH, 'material exists')
        state['material_created'] = False
        return mat
    # create_asset on an existing path opens a modal overwrite dialog (AssetTools.cpp:4920-4936),
    # hence the existence gate above. Same call as Saved/PredictiveIK/setup_showcase.py:18.
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    mat = tools.create_asset(MAT_NAME, C.MAT_DIR, unreal.Material, unreal.MaterialFactoryNew())
    if not isinstance(mat, unreal.Material):
        report.error('create_asset returned %r for %s' % (mat, MAT_PATH))
        return None
    report.created(MAT_PATH)
    state['material_created'] = True
    return mat


def step_material_properties(report, state):
    """Enforce domain / blend mode / shading model / two-sided through MaterialService.
    set_property returns False instead of raising (UMaterialService.cpp:646-681), so every write
    is read back through get_property_info (None on failure, PyGenUtil.cpp:1615-1626)."""
    for prop, want in MATERIAL_PROPERTIES:
        try:
            info = MS.get_property_info(MAT_PATH, prop)
            cur = info.current_value if info is not None else None
            if cur is not None and cur.lower() == want.lower() and not FORCE:
                report.skipped('%s.%s' % (MAT_PATH, prop), 'already %s' % cur)
                continue
            if not MS.set_property(MAT_PATH, prop, want):
                report.error('set_property %s=%s failed on %s' % (prop, want, MAT_PATH))
                continue
            info = MS.get_property_info(MAT_PATH, prop)
            now = info.current_value if info is not None else None
            if now is None or now.lower() != want.lower():
                report.error('%s.%s reads back %r, wanted %s' % (MAT_PATH, prop, now, want))
            else:
                report.modified(MAT_PATH, '%s: %s -> %s' % (prop, cur, now))
        except Exception as exc:
            report.error('material property %s' % prop, exc)


def _own_expressions(mat):
    """MaterialNodeService.list_expressions also returns nodes inside referenced material
    functions; keep only the ones this material owns."""
    prefix = mat.get_path_name() + ':'
    return [e for e in MNS.list_expressions(MAT_PATH) if e.object_path.startswith(prefix)]


def _connect_batch(report, nodes, conns):
    """batch_connect_expressions returns only a success count (UMaterialNodeService.cpp:1602-1656);
    on a short count, retry one by one to name the failing wires."""
    src = [nodes[c[0]].id for c in conns]
    out = [c[1] for c in conns]
    dst = [nodes[c[2]].id for c in conns]
    inp = [c[3] for c in conns]
    count = MNS.batch_connect_expressions(MAT_PATH, src, out, dst, inp)
    if count == len(conns):
        report.info('connected %d/%d wires in %s' % (count, len(conns), MAT_NAME))
        return True
    report.info('batch_connect_expressions connected %d/%d; locating failures' % (count, len(conns)))
    ok = True
    for c in conns:
        n = MNS.batch_connect_expressions(MAT_PATH, [nodes[c[0]].id], [c[1]], [nodes[c[2]].id], [c[3]])
        if n != 1:
            ok = False
            report.error('wire %s.%s -> %s.%s failed' % (c[0], c[1] or '<0>', c[2], c[3] or '<0>'))
    return ok


def _set_props_batch(report, nodes, sets):
    ids = [nodes[s[0]].id for s in sets]
    names = [s[1] for s in sets]
    values = [s[2] for s in sets]
    count = MNS.batch_set_properties(MAT_PATH, ids, names, values)
    if count == len(sets):
        report.info('set %d/%d expression properties in %s' % (count, len(sets), MAT_NAME))
        return True
    report.info('batch_set_properties set %d/%d; locating failures' % (count, len(sets)))
    ok = True
    for (key, prop, value), eid in zip(sets, ids):
        if not MNS.set_expression_property(MAT_PATH, eid, prop, value):
            ok = False
            report.error('property %s.%s=%s failed' % (key, prop, value))
    return ok


def _assign_textures(report, nodes, state, warnings):
    """Set each texture parameter's default natively: Python set_editor_property notifies only on
    a real change (PropertyAccessUtil.h:50-58) and UMaterialExpressionTextureSample::
    PostEditChangeProperty then runs AutoSetSampleType (MaterialExpressions.cpp:2663-2670).
    VibeUE's own texture setters skip that hook (UMaterialNodeService.cpp:1031-1096), so the
    sampler type is read back and corrected explicitly if needed."""
    ok = True
    samplers = {}
    for pname, tex_name, spec_types in TEXTURE_PARAMS:
        key = 'T_' + pname
        tex_path = C.TEX_DIR + '/' + tex_name
        try:
            tex = C.load(tex_path)
            if tex is None or not isinstance(tex, unreal.Texture):
                report.error('texture %s missing (run ice_slash_01 import first)' % tex_path)
                ok = False
                continue
            expr = unreal.find_object(None, nodes[key].object_path)
            if expr is None:
                report.error('cannot resolve expression %s (%s)' % (key, nodes[key].object_path))
                ok = False
                continue
            if _path_of(expr.get_editor_property('texture')) != tex.get_path_name():
                expr.set_editor_property('texture', tex)
            want = _expected_sampler_type(tex)
            cur = MNS.get_expression_property(MAT_PATH, nodes[key].id, 'SamplerType')
            if cur != want:
                if not MNS.set_expression_property(MAT_PATH, nodes[key].id, 'SamplerType', want):
                    report.error('%s: cannot set SamplerType %s (was %s)' % (pname, want, cur))
                    ok = False
                    continue
                warnings.append('%s sampler corrected %s -> %s' % (pname, cur, want))
                cur = MNS.get_expression_property(MAT_PATH, nodes[key].id, 'SamplerType')
            if cur not in spec_types:
                # The import settings (step 01) decide; a mismatch with the lead's expectation is
                # not a compile error, but worth a look.
                warnings.append('%s sampler %s differs from spec %s (texture srgb=%s compression=%s)' % (
                    pname, cur, '/'.join(spec_types), tex.get_editor_property('srgb'),
                    _enum_name(tex.get_editor_property('compression_settings'))))
            samplers[pname] = {'texture': tex.get_path_name(), 'sampler_type': cur}
            report.modified(MAT_PATH, '%s = %s (%s)' % (pname, tex_path, cur))
        except Exception as exc:
            ok = False
            report.error('texture parameter %s' % pname, exc)
    state['samplers'] = samplers
    return ok


def step_build_graph(report, mat, state, warnings):
    """Build (or, with REBUILD, rebuild in place) the full graph with the VibeUE batch calls."""
    existing = _own_expressions(mat)
    if existing and not REBUILD:
        return None  # caller verifies instead
    if existing:
        # Clears nodes and the root-pin links; the asset and its references are kept
        # (MaterialEditingLibrary.cpp:805-865).
        MEL.delete_all_material_expressions(mat)
        report.modified(MAT_PATH, 'REBUILD: deleted %d expressions' % len(existing))

    keys = [n[0] for n in NODES]
    infos = MNS.batch_create_expressions(MAT_PATH, [n[1] for n in NODES],
                                         [n[2] for n in NODES], [n[3] for n in NODES])
    if len(infos) != len(NODES):
        report.error('batch_create_expressions returned %d/%d entries' % (len(infos), len(NODES)))
        return False
    nodes = {}
    ok = True
    for key, spec, info in zip(keys, NODES, infos):
        if not info.id:
            ok = False
            report.error('could not create node %s (%s)' % (key, spec[1]))
        nodes[key] = info
    if not ok:
        return False
    report.modified(MAT_PATH, 'created %d expressions' % len(infos))

    ok = _set_props_batch(report, nodes, _property_sets()) and ok
    ok = _assign_textures(report, nodes, state, warnings) and ok
    ok = _connect_batch(report, nodes, CONNECTIONS) and ok
    for key, out, prop in OUTPUTS:
        # Returns True only after a read-back of the root pin (UMaterialNodeService.cpp:2759-2844).
        if MNS.connect_expression_to_output(MAT_PATH, nodes[key].id, out, prop):
            report.modified(MAT_PATH, 'output %s <- %s' % (prop, key))
        else:
            ok = False
            report.error('connect_expression_to_output %s -> %s failed' % (key, prop))
    if ok:
        EAL.set_metadata_tag(mat, GRAPH_VERSION_TAG, GRAPH_VERSION)
        report.modified(MAT_PATH, 'metadata %s=%s' % (GRAPH_VERSION_TAG, GRAPH_VERSION))
    state['graph_built'] = True
    return ok


def step_verify_graph(report, mat, state, warnings):
    """Verify parameters, outputs and texture defaults of an existing graph (no graph edits)."""
    for name in ALL_PARAM_NAMES:
        # parameter_exists covers scalar/vector/texture on a base UMaterial (UMaterialService.cpp:970-1022).
        if MS.parameter_exists(MAT_PATH, name):
            report.info('param ok: %s' % name)
        else:
            report.error('parameter %s missing in %s (set REBUILD = True to rebuild the graph)' % (name, MAT_PATH))
    try:
        conns = {c.property_name.lower(): c for c in MNS.get_output_connections(MAT_PATH)}
        for _key, _out, prop in OUTPUTS:
            c = conns.get(prop.lower())
            if c is None or not c.is_connected:
                report.error('output %s not connected in %s (set REBUILD = True)' % (prop, MAT_PATH))
            else:
                report.info('output ok: %s <- %s' % (prop, c.connected_expression_id))
    except Exception as exc:
        report.error('get_output_connections', exc)
    samplers = {}
    for pname, tex_name, _spec in TEXTURE_PARAMS:
        tex = MEL.get_material_default_texture_parameter_value(mat, pname)
        samplers[pname] = {'texture': _path_of(tex)}
        if tex is None:
            report.error('texture parameter %s has no default texture' % pname)
        elif tex.get_name() != tex_name:
            warnings.append('%s default is %s, expected %s' % (pname, tex.get_path_name(), tex_name))
    state['samplers'] = samplers
    tag = EAL.get_metadata_tag(mat, GRAPH_VERSION_TAG)
    state['graph_version_found'] = tag
    if tag != GRAPH_VERSION:
        msg = ('%s graph version is %r, script is %s: run with REBUILD = True to refresh the graph'
               % (MAT_PATH, tag, GRAPH_VERSION))
        warnings.append('graph version %r != %s' % (tag, GRAPH_VERSION))
        report.todo(msg)
        state['todo'].append(msg)


def step_compile(report, mat, state, warnings):
    """MaterialEditingLibrary.recompile_material blocks until the shader map is finished and
    returns the error strings (MaterialEditingLibrary.h:339-347, .cpp:1281-1324)."""
    errors = []
    try:
        errors = list(MEL.recompile_material(mat))
        culprits = []
        try:
            culprits = list(MEL.get_material_error_expressions(mat))  # index-aligned with errors
        except Exception as exc:
            warnings.append('get_material_error_expressions failed: %s' % exc)
        for i, err in enumerate(errors):
            node = culprits[i].get_name() if i < len(culprits) and culprits[i] is not None else '-'
            report.error('compile %s: %s [node %s]' % (MAT_NAME, err, node))
    except Exception as exc:
        report.error('recompile_material %s' % MAT_PATH, exc)
        errors = ['recompile_material raised: %s' % exc]
    for w in warnings:
        report.info('WARNING: %s' % w)
    report.info('COMPILE %s errors=%d warnings=%d' % (MAT_NAME, len(errors), len(warnings)))
    state['compile_errors'] = errors
    state['warnings'] = list(warnings)
    try:
        info = MS.get_material_info(MAT_PATH)
        if info is not None:
            report.info('EVIDENCE %s domain=%s blend=%s shading=%s two_sided=%s expressions=%d textures=%d' % (
                MAT_NAME, info.material_domain, info.blend_mode, info.shading_model,
                info.two_sided, info.expression_count, info.texture_sample_count))
            state['evidence'] = {'domain': info.material_domain, 'blend_mode': info.blend_mode,
                                 'shading_model': info.shading_model, 'two_sided': bool(info.two_sided),
                                 'expression_count': int(info.expression_count),
                                 'texture_sample_count': int(info.texture_sample_count)}
        names = (list(MEL.get_scalar_parameter_names(mat)) + list(MEL.get_vector_parameter_names(mat))
                 + list(MEL.get_texture_parameter_names(mat)))
        names = sorted(str(n) for n in names)
        report.info('PARAMS %s: %s' % (MAT_NAME, ', '.join(names)))
        missing = [n for n in ALL_PARAM_NAMES if n not in names]
        if missing:
            report.error('compiled %s lacks parameters %s' % (MAT_NAME, missing))
        state['parameters'] = names
    except Exception as exc:
        report.error('evidence read-back for %s' % MAT_PATH, exc)


def _ensure_instance(report, parent, idx, prefix):
    name = '%s%02d' % (prefix, idx)
    path = C.MAT_DIR + '/' + name
    if C.asset_exists(path):
        mi = C.load(path)
        if not isinstance(mi, unreal.MaterialInstanceConstant):
            report.error('%s exists but is %s' % (path, type(mi).__name__))
            return None, path
        report.skipped(path, 'instance exists')
    else:
        tools = unreal.AssetToolsHelpers.get_asset_tools()
        # MaterialInstanceConstantFactoryNew.InitialParent is a flagless UPROPERTY()
        # (MaterialInstanceConstantFactoryNew.h:19-20), so the parent is set through MEL below.
        mi = tools.create_asset(name, C.MAT_DIR, unreal.MaterialInstanceConstant,
                                unreal.MaterialInstanceConstantFactoryNew())
        if not isinstance(mi, unreal.MaterialInstanceConstant):
            report.error('create_asset returned %r for %s' % (mi, path))
            return None, path
        report.created(path)
    if _path_of(mi.get_editor_property('parent')) != parent.get_path_name() or FORCE:
        MEL.set_material_instance_parent(mi, parent)
        if _path_of(mi.get_editor_property('parent')) != parent.get_path_name():
            report.error('%s parent did not take (is %s)' % (path, _path_of(mi.get_editor_property('parent'))))
            return None, path
        report.modified(path, 'parent = %s' % MAT_PATH)
    return mi, path


def step_instances(report, mat, state, prefix=None, values_by_idx=None):
    """Create <prefix>01..05 and enforce their overrides (numbers = scalar parameters, tuples =
    vector parameters). MEL setters return True for any non-null instance
    (MaterialEditingLibrary.h:545/600), so values are read back."""
    prefix = prefix or MI_PREFIX
    values_by_idx = values_by_idx or MI_VALUES
    instances = state.setdefault('instances', {})
    for idx in range(1, ARC_COUNT + 1):
        try:
            mi, path = _ensure_instance(report, mat, idx, prefix)
            if mi is None:
                continue
            values = values_by_idx[idx]
            changed, record = [], {'parent': MAT_PATH}
            for pname, want in values.items():
                over = MEL.is_material_instance_parameter_overridden(mi, pname)
                if isinstance(want, (int, float)):
                    cur = MEL.get_material_instance_scalar_parameter_value(mi, pname)
                    if FORCE or not over or abs(cur - want) > 1e-4:
                        MEL.set_material_instance_scalar_parameter_value(mi, pname, want)
                        changed.append('%s %.3f -> %.3f' % (pname, cur, want))
                else:
                    cur = MEL.get_material_instance_vector_parameter_value(mi, pname)
                    if FORCE or not over or not _colors_equal(cur, want):
                        MEL.set_material_instance_vector_parameter_value(mi, pname, unreal.LinearColor(*want))
                        changed.append('%s -> (%.2f, %.2f, %.2f)' % ((pname,) + tuple(want[:3])))
            if changed:
                MEL.update_material_instance(mi)
                report.modified(path, '; '.join(changed))
            else:
                report.skipped(path, 'overrides already set: %s' % sorted(values))
            for pname, want in values.items():   # read back
                if isinstance(want, (int, float)):
                    got = MEL.get_material_instance_scalar_parameter_value(mi, pname)
                    record[pname] = got
                    if abs(got - want) > 1e-4:
                        report.error('%s read-back %s=%.3f, wanted %.3f' % (path, pname, got, want))
                else:
                    got = MEL.get_material_instance_vector_parameter_value(mi, pname)
                    record[pname] = [got.r, got.g, got.b, got.a]
                    if not _colors_equal(got, want):
                        report.error('%s read-back %s=(%.3f,%.3f,%.3f)' % (path, pname, got.r, got.g, got.b))
            # other overrides are left alone, but listed as evidence
            others = [str(q.parameter_name) for q in MS.list_parameters(path)
                      if q.is_overridden and str(q.parameter_name) not in values]
            if others:
                report.info('%s also overrides %s (left unchanged)' % (path, others))
            instances[path] = record
        except Exception as exc:
            report.error('instance %s%02d' % (prefix, idx), exc)
    return instances


def step_usage(report, mat):
    """The blades are also rendered as Niagara mesh particles (NS_IceSlash_Skill): the material
    needs the usage flag or the particles fall back to the default material."""
    try:
        usage = unreal.MaterialUsage.MATUSAGE_NIAGARA_MESH_PARTICLES
        if MEL.has_material_usage(mat, usage):
            report.skipped(MAT_PATH, 'usage NiagaraMeshParticles already set')
            return
        res = MEL.set_material_usage(mat, usage)
        report.modified(MAT_PATH, 'usage NiagaraMeshParticles set (%s)' % (res,))
        if not MEL.has_material_usage(mat, usage):
            report.error('%s: usage NiagaraMeshParticles did not take' % MAT_PATH)
    except Exception as exc:
        report.error('material usage', exc)


def step_mesh_slots(report, state):
    """SM_SlashArc_0N slot 0 = MI_SlashArc_0N. StaticMesh.set_material wraps the edit in
    Pre/PostEditChange and dirties the mesh (StaticMesh.cpp:10622-10647); writing back
    static_materials would only modify a copy."""
    slots = {}
    for idx in range(1, ARC_COUNT + 1):
        mesh_path = '%s/%s%02d' % (C.MESH_DIR, MESH_PREFIX, idx)
        mi_path = '%s/%s%02d' % (C.MAT_DIR, MI_PREFIX, idx)
        try:
            sm = C.load(mesh_path)
            if sm is None or not isinstance(sm, unreal.StaticMesh):
                report.error('mesh %s missing (run ice_slash_01 import first)' % mesh_path)
                continue
            mi = C.load(mi_path)
            if mi is None:
                report.error('instance %s missing, cannot assign slot' % mi_path)
                continue
            nslots = len(sm.get_editor_property('static_materials'))
            if nslots < 1:
                report.error('%s has no material slots' % mesh_path)
                continue
            if nslots > 1:
                report.info('%s has %d slots; only slot 0 is assigned' % (mesh_path, nslots))
            cur = sm.get_material(0)
            if _path_of(cur) == mi.get_path_name() and not FORCE:
                report.skipped(mesh_path, 'slot 0 already %s' % mi_path)
            else:
                sm.set_material(0, mi)
                if _path_of(sm.get_material(0)) != mi.get_path_name():
                    report.error('%s slot 0 reads back %s' % (mesh_path, _path_of(sm.get_material(0))))
                    continue
                report.modified(mesh_path, 'slot 0: %s -> %s' % (_path_of(cur) or 'None', mi_path))
            slots[mesh_path] = mi_path
        except Exception as exc:
            report.error('mesh slot %s' % mesh_path, exc)
    state['mesh_slots'] = slots


def step_manifest(report, state):
    try:
        # update_manifest merges dict sections one level deep (ice_slash_common.py:454-477), so
        # the crystal script's keys in 'materials' are kept.
        section = {}
        section[MANIFEST_KEY] = {
            'material': MAT_PATH,
            'graph_version': GRAPH_VERSION,
            'graph_built_this_run': bool(state.get('graph_built')),
            'blend_mode': dict(MATERIAL_PROPERTIES)['BlendMode'],
            'shading_model': 'MSM_Unlit',
            'two_sided': True,
            'parameters': ALL_PARAM_NAMES,
            'scalar_defaults': {p[0]: p[1] for p in SCALAR_PARAMS},
            'vector_defaults': {p[0]: list(p[1]) for p in VECTOR_PARAMS},
            'textures': state.get('samplers', {}),
            'instances': state.get('instances', {}),
            'mesh_slots': state.get('mesh_slots', {}),
            'compile_errors': state.get('compile_errors', []),
            'warnings': state.get('warnings', []),
            'evidence': state.get('evidence', {}),
            'reveal_contract': REVEAL_CONTRACT,
            'todo': state.get('todo', []),
        }
        C.update_manifest('materials', section)
        report.info('manifest materials.%s written to %s' % (MANIFEST_KEY, C.MANIFEST_PATH))
    except Exception as exc:
        report.error('manifest update', exc)


# ---------------------------------------------------------------------------------------------
def main():
    report = C.Report(SCRIPT_NAME)
    state = {'todo': []}
    warnings = []
    report.info('config REBUILD=%s FORCE=%s graph=%s' % (REBUILD, FORCE, GRAPH_VERSION))
    mat = None
    try:
        mat = step_ensure_material(report, state)
    except Exception as exc:
        report.error('ensure material %s' % MAT_PATH, exc)

    if mat is not None:
        step_material_properties(report, state)
        step_usage(report, mat)
        try:
            built = step_build_graph(report, mat, state, warnings)
            if built is None:
                report.skipped(MAT_PATH, 'graph exists and REBUILD is False: verifying only')
                step_verify_graph(report, mat, state, warnings)
            elif built is False:
                report.error('graph build for %s incomplete (re-run with REBUILD = True after fixing)' % MAT_PATH)
        except Exception as exc:
            report.error('graph build/verify %s' % MAT_PATH, exc)
        step_compile(report, mat, state, warnings)
        step_instances(report, mat, state)
        step_instances(report, mat, state, NS_MI_PREFIX, NS_MI_VALUES)
    else:
        report.error('no material: instances and mesh slots skipped')

    step_mesh_slots(report, state)
    step_manifest(report, state)
    try:
        # save_all(report) saves only this run's / the IceSlash root's dirty packages, never the
        # other agent's maps (ice_slash_common.py:335-424).
        C.save_all(report)
    except Exception as exc:
        report.error('save_all', exc)
    report.finish()


if __name__ == '__main__':
    main()
