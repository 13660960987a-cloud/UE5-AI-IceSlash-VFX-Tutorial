"""Ice-slash under-blade smoke: M_SlashSmoke + MI_SlashSmoke_01..05 (NobleShore).

The reference blade is two stacked layers: the coloured painted crescent on top and, just
below it, a grey-white smoke copy of the same crescent that lingers after the blade has
gone. As the user put it: the same slash sheet mesh with another material, shifted down a bit.

The smoke is rendered by mesh emitters Smoke_01..05 in NS_IceSlash_Skill (same SM_SlashArc_0N
sheets, ice_slash_09_skill_blades.py moves them down and draws them under the blades). This
material uses the same UVs as the blade material:
  UV0 = the painted crescent -> its alpha, sampled with a mip bias (soft, blurred outline),
        is the smoke's shape; two panned cloud-noise samples give the smoky texture
  UV1.x = sweep (0 tail .. 1 head) -> sweep-in / erase driven by the particle age
          (UseParticleTime = 1): head = sqrt(age) * (1 + SmokeWidth), slower and softer than
          the blade so the smoke trails it and thins out tail first.
Particle colour multiplies everything (Niagara ScaleColor fades the whole layer).

Reuses the graph builder in ice_slash_03_material_slash.py (loaded under another name, its
configuration replaced). Mesh slot assignment is skipped: the sheets keep their blade material.
"""
import importlib.util

TOOLS_DIR = '/Users/mengmeile/Downloads/lianxi/m/Tools/IceSlash'
REBUILD = False   # True: rebuild the M_SlashSmoke graph in place
FORCE = False

_spec = importlib.util.spec_from_file_location('ice_slash_smoke_builder',
                                               TOOLS_DIR + '/ice_slash_03_material_slash.py')
B = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(B)

B.SCRIPT_NAME = 'ice_slash_11_smoke'
B.REBUILD = REBUILD
B.FORCE = FORCE
B.GRAPH_VERSION = 'smoke_v1.0'
B.MAT_NAME = 'M_SlashSmoke'
B.MAT_PATH = B.C.MAT_DIR + '/' + B.MAT_NAME
B.MI_PREFIX = 'MI_SlashSmoke_'
B.NS_MI_PREFIX = 'MI_SlashSmoke_'
B.MANIFEST_KEY = 'smoke'
B.REVEAL_CONTRACT = {
    'param': 'particle normalised age (UseParticleTime = 1) or SmokeProgress (0)',
    'note': 'head = sqrt(age)*(1+SmokeWidth) along UV1.x; noisy soft tail erase',
}
B.step_mesh_slots = lambda report, state: None      # the sheets keep MI_SlashArc_0N
B.MATERIAL_PROPERTIES = [
    ('MaterialDomain', 'MD_Surface'),
    ('BlendMode', 'BLEND_Translucent'),
    ('ShadingModel', 'MSM_Unlit'),
    ('TwoSided', 'true'),
]
B.SCALAR_PARAMS = [
    ('SmokeProgress', 0.5, 0.0, 1.2, 'Smoke'),
    ('UseParticleTime', 0.0, 0.0, 1.0, 'Niagara'),
    ('SmokeWidth', 1.6, 0.1, 3.0, 'Smoke'),
    ('HeadSoft', 0.12, 0.001, 1.0, 'Smoke'),
    ('TailSoft', 0.5, 0.001, 2.0, 'Smoke'),
    ('TailNoise', 0.35, 0.0, 1.0, 'Smoke'),
    ('ShapeBoost', 1.6, 0.0, 5.0, 'Smoke'),
    ('SmokeOpacity', 0.55, 0.0, 1.0, 'Smoke'),
    ('Brightness', 1.0, 0.0, 5.0, 'Smoke'),
]
B.VECTOR_PARAMS = [
    ('SmokeColor', (0.55, 0.62, 0.74, 1.0), 'Color'),
    ('SmokeCore', (0.90, 0.93, 0.98, 1.0), 'Color'),
]
B.TEXTURE_PARAMS = [
    ('SheetTex', 'T_SlashBlade_Painted', ('SAMPLERTYPE_Color',)),
    ('CloudTex', 'T_SlashMist_Cloud', ('SAMPLERTYPE_LinearGrayscale', 'SAMPLERTYPE_Grayscale')),
    ('CloudTex2', 'T_SlashMist_Cloud', ('SAMPLERTYPE_LinearGrayscale', 'SAMPLERTYPE_Grayscale')),
]
B.ALL_PARAM_NAMES = ([p[0] for p in B.SCALAR_PARAMS] + [p[0] for p in B.VECTOR_PARAMS]
                     + [p[0] for p in B.TEXTURE_PARAMS])
B.MI_VALUES = {i: {'UseParticleTime': 1.0} for i in range(1, 6)}
B.NS_MI_VALUES = B.MI_VALUES

B.NODES = [
    ('P_SmokeProgress', 'ScalarParameter', -2600, -1000),
    ('P_UseParticleTime', 'ScalarParameter', -2600, -880),
    ('P_SmokeWidth', 'ScalarParameter', -2600, -760),
    ('P_HeadSoft', 'ScalarParameter', -2600, -640),
    ('P_TailSoft', 'ScalarParameter', -2600, -520),
    ('P_TailNoise', 'ScalarParameter', -2600, -400),
    ('P_ShapeBoost', 'ScalarParameter', -1600, 160),
    ('P_SmokeOpacity', 'ScalarParameter', -900, 700),
    ('P_Brightness', 'ScalarParameter', -900, -300),
    ('P_SmokeColor', 'VectorParameter', -1100, -560),
    ('P_SmokeCore', 'VectorParameter', -1100, -420),
    # shape: painted crescent alpha, blurred by a mip bias
    ('TexCoord', 'TextureCoordinate', -3200, 0),
    ('T_SheetTex', 'TextureSampleParameter2D', -2000, 0),
    ('ShapeMul', 'Multiply', -1400, 60),
    ('Shape', 'Saturate', -1200, 60),
    # cloud noise (UV0 tiled, two pans)
    ('TC1', 'TextureCoordinate', -3200, 400),
    ('Pan1', 'Panner', -3000, 400),
    ('T_CloudTex', 'TextureSampleParameter2D', -2700, 400),
    ('TC2', 'TextureCoordinate', -3200, 700),
    ('Pan2', 'Panner', -3000, 700),
    ('T_CloudTex2', 'TextureSampleParameter2D', -2700, 700),
    ('NMul', 'Multiply', -2300, 550),
    ('NoiseC', 'SmoothStep', -2100, 550),
    # sweep window (UV1.x) from the particle age
    ('TexCoord1', 'TextureCoordinate', -3200, -1200),
    ('Sweep', 'ComponentMask', -3000, -1200),
    ('PRT', 'ParticleRelativeTime', -3200, -1000),
    ('PRTpow', 'Power', -3000, -1000),
    ('ProgSel', 'LinearInterpolate', -2400, -1000),
    ('WPlus1', 'Add', -2400, -760),
    ('Head', 'Multiply', -2200, -900),
    ('Tail', 'Subtract', -2000, -800),
    ('HeadDist', 'Subtract', -1800, -1000),
    ('HeadClamp', 'Max', -2200, -640),
    ('HeadMask', 'SmoothStep', -1600, -1000),
    ('NoiseOff', 'Subtract', -2000, -400),
    ('NoiseOffS', 'Multiply', -1800, -400),
    ('TailDist0', 'Subtract', -1800, -800),
    ('TailDist', 'Add', -1600, -700),
    ('TailClamp', 'Max', -2200, -520),
    ('TailMask', 'SmoothStep', -1400, -700),
    ('Reveal', 'Multiply', -1200, -850),
    # opacity / colour
    ('O1', 'Multiply', -1000, 100),
    ('O2', 'Multiply', -800, 200),
    ('O3', 'Multiply', -600, 300),
    ('PCol', 'ParticleColor', -900, 900),
    ('O4', 'Multiply', -400, 500),
    ('OpacityOut', 'Saturate', -200, 500),
    ('ColLerp', 'LinearInterpolate', -700, -500),
    ('EmB', 'Multiply', -500, -400),
    ('EmPC', 'Multiply', -300, -300),
]
B.CONST_SETS = [
    ('TexCoord', 'CoordinateIndex', '0'),
    ('TexCoord1', 'CoordinateIndex', '1'),
    ('Sweep', 'R', 'True'), ('Sweep', 'G', 'False'), ('Sweep', 'B', 'False'), ('Sweep', 'A', 'False'),
    ('T_SheetTex', 'MipValueMode', 'TMVM_MipBias'), ('T_SheetTex', 'ConstMipValue', '3'),
    ('TC1', 'UTiling', '2.6'), ('TC1', 'VTiling', '2.6'),
    ('Pan1', 'SpeedX', '-0.06'), ('Pan1', 'SpeedY', '0.03'),
    ('TC2', 'UTiling', '5.2'), ('TC2', 'VTiling', '5.2'),
    ('Pan2', 'SpeedX', '0.05'), ('Pan2', 'SpeedY', '-0.045'),
    ('NoiseC', 'ConstMin', '0.04'), ('NoiseC', 'ConstMax', '0.55'),
    ('PRTpow', 'ConstExponent', '0.5'),
    ('WPlus1', 'ConstB', '1.0'),
    ('HeadClamp', 'ConstB', '0.001'),
    ('HeadMask', 'ConstMin', '0.0'),
    ('NoiseOff', 'ConstB', '0.5'),
    ('TailClamp', 'ConstB', '0.001'),
    ('TailMask', 'ConstMin', '0.0'),
]
B.CONNECTIONS = [
    ('TexCoord', '', 'T_SheetTex', 'UVs'),
    ('T_SheetTex', 'A', 'ShapeMul', 'A'),
    ('P_ShapeBoost', '', 'ShapeMul', 'B'),
    ('ShapeMul', '', 'Shape', ''),
    ('TC1', '', 'Pan1', 'Coordinate'),
    ('Pan1', '', 'T_CloudTex', 'UVs'),
    ('TC2', '', 'Pan2', 'Coordinate'),
    ('Pan2', '', 'T_CloudTex2', 'UVs'),
    ('T_CloudTex', 'R', 'NMul', 'A'),
    ('T_CloudTex2', 'R', 'NMul', 'B'),
    ('NMul', '', 'NoiseC', 'Value'),
    # sweep
    ('TexCoord1', '', 'Sweep', ''),
    ('PRT', '', 'PRTpow', 'Base'),
    ('P_SmokeProgress', '', 'ProgSel', 'A'),
    ('PRTpow', '', 'ProgSel', 'B'),
    ('P_UseParticleTime', '', 'ProgSel', 'Alpha'),
    ('P_SmokeWidth', '', 'WPlus1', 'A'),
    ('ProgSel', '', 'Head', 'A'),
    ('WPlus1', '', 'Head', 'B'),
    ('Head', '', 'Tail', 'A'),
    ('P_SmokeWidth', '', 'Tail', 'B'),
    ('Head', '', 'HeadDist', 'A'),
    ('Sweep', '', 'HeadDist', 'B'),
    ('P_HeadSoft', '', 'HeadClamp', 'A'),
    ('HeadClamp', '', 'HeadMask', 'Max'),
    ('HeadDist', '', 'HeadMask', 'Value'),
    ('T_CloudTex', 'R', 'NoiseOff', 'A'),
    ('NoiseOff', '', 'NoiseOffS', 'A'),
    ('P_TailNoise', '', 'NoiseOffS', 'B'),
    ('Sweep', '', 'TailDist0', 'A'),
    ('Tail', '', 'TailDist0', 'B'),
    ('TailDist0', '', 'TailDist', 'A'),
    ('NoiseOffS', '', 'TailDist', 'B'),
    ('P_TailSoft', '', 'TailClamp', 'A'),
    ('TailClamp', '', 'TailMask', 'Max'),
    ('TailDist', '', 'TailMask', 'Value'),
    ('HeadMask', '', 'Reveal', 'A'),
    ('TailMask', '', 'Reveal', 'B'),
    # opacity
    ('Shape', '', 'O1', 'A'),
    ('NoiseC', '', 'O1', 'B'),
    ('O1', '', 'O2', 'A'),
    ('Reveal', '', 'O2', 'B'),
    ('O2', '', 'O3', 'A'),
    ('P_SmokeOpacity', '', 'O3', 'B'),
    ('O3', '', 'O4', 'A'),
    ('PCol', 'A', 'O4', 'B'),
    ('O4', '', 'OpacityOut', ''),
    # colour
    ('P_SmokeColor', 'RGB', 'ColLerp', 'A'),
    ('P_SmokeCore', 'RGB', 'ColLerp', 'B'),
    ('NoiseC', '', 'ColLerp', 'Alpha'),
    ('ColLerp', '', 'EmB', 'A'),
    ('P_Brightness', '', 'EmB', 'B'),
    ('EmB', '', 'EmPC', 'A'),
    ('PCol', '', 'EmPC', 'B'),
]
B.OUTPUTS = [
    ('EmPC', '', 'EmissiveColor'),
    ('OpacityOut', '', 'Opacity'),
]

if __name__ == '__main__':
    B.main()
