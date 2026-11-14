"""Ice-slash frost mist: M_SlashMist + MI_SlashMist_01..05 on SM_SlashMist_01..05 (NobleShore).

Layer 1 of the reference: a soft grey-blue haze that fills the area a blade has just swept and
lingers after the blade is gone. One fan mesh per blade (SourceAssets/SlashMist), UV0 = (U along
the swing 0 start .. 1 tip, V 0 blade side .. 1 deep inside the arc).

The mist lives in the single skill system NS_IceSlash_Skill as mesh emitters Mist_01..05
(ice_slash_09_skill_blades.py). Like the blades it is animated from the particle's normalised
age (UseParticleTime = 1):

  head  = saturate(age * HeadSpeed) * 1.15   the haze follows the blade along U
  erase = the tail end thins out first while the particle ages (gone at age 1)
  Particle Color alpha (Niagara ScaleColor curve) fades the whole fan.

With UseParticleTime = 0 the MistHead parameter places the front by hand (static preview).

This script reuses the graph builder of ice_slash_03_material_slash.py: that module is loaded
under another name and its configuration (names, parameters, node list) is replaced before its
main() runs. REBUILD / FORCE mean the same as there.
"""
import importlib.util

TOOLS_DIR = '/Users/mengmeile/Downloads/lianxi/m/Tools/IceSlash'
REBUILD = False   # True: rebuild the M_SlashMist graph in place
FORCE = False

_spec = importlib.util.spec_from_file_location('ice_slash_material_builder',
                                               TOOLS_DIR + '/ice_slash_03_material_slash.py')
B = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(B)          # defines the builder; its main() only runs as __main__

B.SCRIPT_NAME = 'ice_slash_08_mist'
B.REBUILD = REBUILD
B.FORCE = FORCE
B.GRAPH_VERSION = 'mist_v1.2'
B.MAT_NAME = 'M_SlashMist'
B.MAT_PATH = B.C.MAT_DIR + '/' + B.MAT_NAME
B.MI_PREFIX = 'MI_SlashMist_'
B.NS_MI_PREFIX = 'MI_SlashMist_'     # one instance set: the mist is only used by Niagara
B.MESH_PREFIX = 'SM_SlashMist_'
B.MANIFEST_KEY = 'mist'
B.REVEAL_CONTRACT = {
    'param': 'particle normalised age (UseParticleTime = 1) or MistHead (UseParticleTime = 0)',
    'note': 'front = saturate(age*HeadSpeed)*1.15 along UV.x; tail thins out from age 0.375, gone at 1',
}
B.MATERIAL_PROPERTIES = [
    ('MaterialDomain', 'MD_Surface'),
    ('BlendMode', 'BLEND_Translucent'),
    ('ShadingModel', 'MSM_Unlit'),
    ('TwoSided', 'true'),
]
B.SCALAR_PARAMS = [
    ('MistHead', 1.15, 0.0, 1.3, 'Mist'),
    ('UseParticleTime', 0.0, 0.0, 1.0, 'Niagara'),
    ('HeadSpeed', 6.0, 0.5, 20.0, 'Niagara'),
    ('MistSoft', 0.25, 0.001, 1.0, 'Mist'),
    ('MistOpacity', 0.5, 0.0, 1.0, 'Mist'),
    ('Brightness', 0.9, 0.0, 5.0, 'Mist'),
]
B.VECTOR_PARAMS = [
    ('MistColor', (0.36, 0.44, 0.60, 1.0), 'Color'),
    ('MistCore', (0.82, 0.87, 0.95, 1.0), 'Color'),
]
B.TEXTURE_PARAMS = [
    ('CloudTex', 'T_SlashMist_Cloud', ('SAMPLERTYPE_LinearGrayscale', 'SAMPLERTYPE_Grayscale')),
    ('CloudTex2', 'T_SlashMist_Cloud', ('SAMPLERTYPE_LinearGrayscale', 'SAMPLERTYPE_Grayscale')),
]
B.ALL_PARAM_NAMES = ([p[0] for p in B.SCALAR_PARAMS] + [p[0] for p in B.VECTOR_PARAMS]
                     + [p[0] for p in B.TEXTURE_PARAMS])
B.MI_VALUES = {i: {'UseParticleTime': 1.0} for i in range(1, 6)}
B.NS_MI_VALUES = B.MI_VALUES

B.NODES = [
    ('P_MistHead', 'ScalarParameter', -2400, -900),
    ('P_UseParticleTime', 'ScalarParameter', -2400, -780),
    ('P_HeadSpeed', 'ScalarParameter', -3000, -1000),
    ('P_MistSoft', 'ScalarParameter', -2400, -540),
    ('P_MistOpacity', 'ScalarParameter', -1000, 900),
    ('P_Brightness', 'ScalarParameter', -900, -600),
    ('P_MistColor', 'VectorParameter', -1100, -200),
    ('P_MistCore', 'VectorParameter', -1100, -400),
    # shape UV
    ('TexCoord', 'TextureCoordinate', -3200, 0),
    ('U', 'ComponentMask', -3000, -60),
    ('V', 'ComponentMask', -3000, 60),
    # two panned cloud samples -> wispy noise
    ('TC1', 'TextureCoordinate', -3200, 400),
    ('Pan1', 'Panner', -3000, 400),
    ('T_CloudTex', 'TextureSampleParameter2D', -2700, 400),
    ('TC2', 'TextureCoordinate', -3200, 700),
    ('Pan2', 'Panner', -3000, 700),
    ('T_CloudTex2', 'TextureSampleParameter2D', -2700, 700),
    ('NMul', 'Multiply', -2300, 550),
    ('NoiseC', 'SmoothStep', -2100, 550),
    # front along U: by hand or from the particle age
    ('PRT', 'ParticleRelativeTime', -3200, -1100),
    ('RTHead', 'Multiply', -2800, -1100),
    ('RTHeadSat', 'Saturate', -2600, -1100),
    ('RTHeadX', 'Multiply', -2400, -1100),
    ('HeadSel', 'LinearInterpolate', -2150, -900),
    ('HeadDist', 'Subtract', -1950, -900),
    ('SoftClamp', 'Max', -2200, -540),
    ('Reveal', 'SmoothStep', -1750, -900),
    # the tail end thins out first while the particle ages
    ('RTTail', 'Multiply', -2800, -1300),
    ('TailPos', 'Subtract', -2600, -1300),
    ('TailDist', 'Subtract', -2400, -1300),
    ('Erase', 'SmoothStep', -2200, -1300),
    # falloff across the fan and at both ends
    ('VIn', 'SmoothStep', -2700, 100),
    ('VOutS', 'SmoothStep', -2700, 220),
    ('VOut', 'OneMinus', -2500, 220),
    ('Vfade', 'Multiply', -2300, 160),
    ('UIn', 'SmoothStep', -2700, -220),
    ('UOutS', 'SmoothStep', -2700, -100),
    ('UOut', 'OneMinus', -2500, -100),
    ('Ucap', 'Multiply', -2300, -160),
    # opacity
    ('S1', 'Multiply', -1900, 0),
    ('S2', 'Multiply', -1600, 0),
    ('S3', 'Multiply', -1400, 0),
    ('S4', 'Multiply', -1200, 300),
    ('S5', 'Multiply', -800, 600),
    ('PCol', 'ParticleColor', -900, 1000),
    ('S6', 'Multiply', -600, 700),
    ('OpacityOut', 'Saturate', -400, 700),
    # colour
    ('ColLerp', 'LinearInterpolate', -700, -300),
    ('EmB', 'Multiply', -500, -400),
    ('EmPC', 'Multiply', -300, -300),
]
B.CONST_SETS = [
    ('TexCoord', 'CoordinateIndex', '0'),
    ('U', 'R', 'True'), ('U', 'G', 'False'), ('U', 'B', 'False'), ('U', 'A', 'False'),
    ('V', 'R', 'False'), ('V', 'G', 'True'), ('V', 'B', 'False'), ('V', 'A', 'False'),
    ('TC1', 'UTiling', '1.6'), ('TC1', 'VTiling', '0.7'),
    ('Pan1', 'SpeedX', '-0.07'), ('Pan1', 'SpeedY', '0.025'),
    ('TC2', 'UTiling', '3.3'), ('TC2', 'VTiling', '1.4'),
    ('Pan2', 'SpeedX', '0.05'), ('Pan2', 'SpeedY', '-0.04'),
    ('NoiseC', 'ConstMin', '0.02'), ('NoiseC', 'ConstMax', '0.62'),
    ('RTHeadX', 'ConstB', '1.15'),
    ('SoftClamp', 'ConstB', '0.001'),
    ('Reveal', 'ConstMin', '0.0'),
    ('RTTail', 'ConstB', '1.6'),
    ('TailPos', 'ConstB', '0.6'),
    ('Erase', 'ConstMin', '0.0'), ('Erase', 'ConstMax', '0.6'),
    ('VIn', 'ConstMin', '0.0'), ('VIn', 'ConstMax', '0.24'),
    ('VOutS', 'ConstMin', '0.26'), ('VOutS', 'ConstMax', '1.0'),
    ('UIn', 'ConstMin', '0.0'), ('UIn', 'ConstMax', '0.07'),
    ('UOutS', 'ConstMin', '0.90'), ('UOutS', 'ConstMax', '1.0'),
]
B.CONNECTIONS = [
    ('TexCoord', '', 'U', ''),
    ('TexCoord', '', 'V', ''),
    ('TC1', '', 'Pan1', 'Coordinate'),
    ('Pan1', '', 'T_CloudTex', 'UVs'),
    ('TC2', '', 'Pan2', 'Coordinate'),
    ('Pan2', '', 'T_CloudTex2', 'UVs'),
    ('T_CloudTex', 'R', 'NMul', 'A'),
    ('T_CloudTex2', 'R', 'NMul', 'B'),
    ('NMul', '', 'NoiseC', 'Value'),
    # front
    ('PRT', '', 'RTHead', 'A'),
    ('P_HeadSpeed', '', 'RTHead', 'B'),
    ('RTHead', '', 'RTHeadSat', ''),
    ('RTHeadSat', '', 'RTHeadX', 'A'),
    ('P_MistHead', '', 'HeadSel', 'A'),
    ('RTHeadX', '', 'HeadSel', 'B'),
    ('P_UseParticleTime', '', 'HeadSel', 'Alpha'),
    ('HeadSel', '', 'HeadDist', 'A'),
    ('U', '', 'HeadDist', 'B'),
    ('P_MistSoft', '', 'SoftClamp', 'A'),
    ('SoftClamp', '', 'Reveal', 'Max'),
    ('HeadDist', '', 'Reveal', 'Value'),
    # tail
    ('PRT', '', 'RTTail', 'A'),
    ('RTTail', '', 'TailPos', 'A'),
    ('U', '', 'TailDist', 'A'),
    ('TailPos', '', 'TailDist', 'B'),
    ('TailDist', '', 'Erase', 'Value'),
    # falloff
    ('V', '', 'VIn', 'Value'),
    ('V', '', 'VOutS', 'Value'),
    ('VOutS', '', 'VOut', ''),
    ('VIn', '', 'Vfade', 'A'),
    ('VOut', '', 'Vfade', 'B'),
    ('U', '', 'UIn', 'Value'),
    ('U', '', 'UOutS', 'Value'),
    ('UOutS', '', 'UOut', ''),
    ('UIn', '', 'Ucap', 'A'),
    ('UOut', '', 'Ucap', 'B'),
    # opacity
    ('Vfade', '', 'S1', 'A'),
    ('Ucap', '', 'S1', 'B'),
    ('S1', '', 'S2', 'A'),
    ('Reveal', '', 'S2', 'B'),
    ('S2', '', 'S3', 'A'),
    ('Erase', '', 'S3', 'B'),
    ('S3', '', 'S4', 'A'),
    ('NoiseC', '', 'S4', 'B'),
    ('S4', '', 'S5', 'A'),
    ('P_MistOpacity', '', 'S5', 'B'),
    ('S5', '', 'S6', 'A'),
    ('PCol', 'A', 'S6', 'B'),
    ('S6', '', 'OpacityOut', ''),
    # colour
    ('P_MistColor', 'RGB', 'ColLerp', 'A'),
    ('P_MistCore', 'RGB', 'ColLerp', 'B'),
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
