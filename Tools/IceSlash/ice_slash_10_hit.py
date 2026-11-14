"""Ice-slash hit feedback: the mid-scale layer of NS_IceSlash_Skill (NobleShore).

The reference effect reads in three scales: big = the crescent blades (+ frost mist), small =
sparse snowflakes / stars / frost dust (ChartreuseReef, S1_..S5_), and in between the hit
feedback where each blade meets the target:

  HitN_Flash   white-gold starburst that pops (0.05 s) and shrinks away
  HitN_Streak  long thin light streaks along the slash direction, white core / cyan glow,
               sliding forward and thinning out (velocity-aligned sprites)
  HitN_Splash  dark-blue ink splash under the streak (velocity-aligned)
  HitN_Sparks  short light rays bursting out of the hit point, cyan and gold

Hit points come from the blade meshes (SourceAssets/SlashTextures, Blender: rim point of each
blade closest to the target 1.7 m in front of the character), in the system's local space
(= blade mesh space, the skill actor sits under IceSlash_SlashRoot). The hit time is when the
blade's sweep head passes that point: spawn + life * (s / (1 + SlashWidth))^2.

Owns emitters named Hit<digit>_*; never touches any other emitter. Writes only inputs whose
value differs (every SetStackInputData rebuilds the system view model) and saves the system
after each emitter.
"""
import json
import sys
import importlib
import importlib.util

import unreal
import vibeue

TOOLS_DIR = '/Users/mengmeile/Downloads/lianxi/m/Tools/IceSlash'
if TOOLS_DIR not in sys.path:
    sys.path.insert(0, TOOLS_DIR)
import ice_slash_common as C  # noqa: E402
importlib.reload(C)
_spec = importlib.util.spec_from_file_location('skill_blades', TOOLS_DIR + '/ice_slash_09_skill_blades.py')
S = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(S)          # shared helpers / system names (its main() is not run)

SCRIPT_NAME = 'ice_slash_10_hit'
NTS = S.NTS
SYS_PKG, SYS_REF = S.SYS_PKG, S.SYS_REF
TMP_SPRITE = '/Niagara/DefaultAssets/Templates/Emitters/OmnidirectionalBurst.OmnidirectionalBurst'
MEL = unreal.MaterialEditingLibrary

# Blade timing (must match ice_slash_09 BLADES) and the hit point on each blade.
SWEEP_WIDTH = 1.35                       # MI_SlashArcNS SlashWidth: head = sqrt(age) * (1 + width)
HITS = [
    # n  blade spawn, life   s      position (cm, system local)   direction       size
    (1, 0.00, 0.45, 0.141, (75.4, -208.8, 22.1), (0.90, 0.30, 0.10), 1.00),
    (2, 0.50, 0.45, 0.563, (85.6, -220.5, 150.1), (-0.90, -0.30, 0.10), 1.00),
    (3, 0.75, 0.50, 0.563, (103.6, -253.7, 22.4), (0.90, 0.40, 0.10), 1.30),
    (4, 1.25, 0.45, 0.070, (-71.8, -41.3, 15.0), (0.80, 0.20, -0.60), 1.10),
    (5, 1.50, 0.45, 0.831, (192.3, -37.5, 15.0), (-0.80, 0.30, -0.50), 1.25),
]

# name, parent, texture, tint, EmissiveBoost, extra scalar overrides
MATERIALS = [
    ('MI_VFX_HitStreak', 'M_VFX_Sprite_Additive', 'T_VFX_HitStreak_A', (1.0, 0.96, 0.86, 1.0), 7.0, {}),
    ('MI_VFX_HitFlash', 'M_VFX_Sprite_Additive', 'T_VFX_HitFlash_A', (1.0, 0.93, 0.78, 1.0), 4.0, {}),
    ('MI_VFX_HitSplash', 'M_VFX_Sprite_Translucent', 'T_VFX_HitSplash_A', (0.06, 0.22, 0.78, 1.0), 1.8,
     {'OpacityBoost': 0.9, 'FadeDistance': 6.0}),
]

E_VEL = '/Niagara/Enums/Utility/ENiagara_VelocityMode.ENiagara_VelocityMode'                   # 0 Linear 1 From Point
E_SIZE = '/Niagara/Enums/ENiagara_SizeScaleMode.ENiagara_SizeScaleMode'                         # 1 Rnd Uniform 2 Rnd Non-Uniform
E_COLOR = '/Niagara/Enums/ENiagara_ColorInitializationMode.ENiagara_ColorInitializationMode'    # 1 Direct 2 Random Range
E_LIFE = '/Niagara/Enums/ENiagara_LifetimeMode.ENiagara_LifetimeMode'                           # 1 Random
E_ROT = '/Niagara/Enums/ENiagara_SpriteRotationMode.ENiagara_SpriteRotationMode'                # 2 Random 3 Unset
E_LOOP = '/Niagara/Enums/ENiagara_EmitterStateOptions.ENiagara_EmitterStateOptions'             # 1 Once


def v_vec2(x, y):
    return {'struct': {'refPath': '/Script/CoreUObject.Vector2f'}, 'value': {'x': float(x), 'y': float(y)}}


def v_vec3(x, y, z):
    return {'struct': {'refPath': '/Script/CoreUObject.Vector3f'},
            'value': {'x': float(x), 'y': float(y), 'z': float(z)}}


def v_bool(b):
    return {'struct': {'refPath': '/Script/Niagara.NiagaraBool'}, 'value': {'value': -1 if b else 0}}


def emitter_specs():
    """[(emitter, material, inputs, renderer, sort)] for every hit."""
    out = []
    for n, b_spawn, b_life, s, pos, d, k in HITS:
        t = b_spawn + max(b_life * (s / (1.0 + SWEEP_WIDTH)) ** 2, 0.03)
        px, py, pz = pos
        dx, dy, dz = d
        back = lambda dist: (px - dx * dist, py - dy * dist, pz - dz * dist)  # noqa: E731
        common = lambda when, count, lo, hi: [  # noqa: E731
            ('EmitterUpdateScript', 'EmitterState', 'Loop Behavior', S.v_enum(E_LOOP, 1)),
            ('EmitterUpdateScript', 'EmitterState', 'Loop Duration', S.v_float(S.SKILL_DURATION)),
            ('EmitterUpdateScript', 'SpawnBurst_Instantaneous', 'Spawn Count', S.v_int(count)),
            ('EmitterUpdateScript', 'SpawnBurst_Instantaneous', 'Spawn Time', S.v_float(when)),
            ('ParticleSpawnScript', 'InitializeParticle', 'Lifetime Mode', S.v_enum(E_LIFE, 1)),
            ('ParticleSpawnScript', 'InitializeParticle', 'Lifetime Min', S.v_float(lo)),
            ('ParticleSpawnScript', 'InitializeParticle', 'Lifetime Max', S.v_float(hi)),
            ('ParticleSpawnScript', 'InitializeParticle', 'UsePositionOffset', v_bool(True)),
            ('ParticleSpawnScript', 'ShapeLocation', 'UseOwnerScale', v_bool(False)),
        ]
        # flash: pops then shrinks, random spin
        flash = common(t, 1, 0.20, 0.24) + [
            ('ParticleSpawnScript', 'InitializeParticle', 'Position Offset', v_vec3(*pos)),
            ('ParticleSpawnScript', 'ShapeLocation', 'Sphere Radius', S.v_float(1.0)),
            ('ParticleSpawnScript', 'InitializeParticle', 'Color Mode', S.v_enum(E_COLOR, 1)),
            ('ParticleSpawnScript', 'InitializeParticle', 'Color', S.v_color(1, 1, 1, 1)),
            ('ParticleSpawnScript', 'InitializeParticle', 'Sprite Size Mode', S.v_enum(E_SIZE, 1)),
            ('ParticleSpawnScript', 'InitializeParticle', 'Uniform Sprite Size Min', S.v_float(120 * k)),
            ('ParticleSpawnScript', 'InitializeParticle', 'Uniform Sprite Size Max', S.v_float(160 * k)),
            ('ParticleSpawnScript', 'InitializeParticle', 'Sprite Rotation Mode', S.v_enum(E_ROT, 2)),
            ('ParticleSpawnScript', 'AddVelocity', 'Velocity Mode', S.v_enum(E_VEL, 0)),
            ('ParticleSpawnScript', 'AddVelocity', 'Velocity', v_vec3(0, 0, 0)),
            ('ParticleUpdateScript', 'ScaleSpriteSize', ['Scale Factor', 'Value', 'FloatCurve'],
             S.v_curve([(0.0, 0.35), (0.18, 1.1), (0.5, 0.75), (1.0, 0.05)])),
            ('ParticleUpdateScript', 'ScaleColor', ['Scale Alpha', 'FloatCurve'],
             S.v_curve([(0.0, 1.0), (0.55, 0.85), (1.0, 0.0)])),
        ]
        # streaks: start a little behind the hit point, slide forward along the slash, thin out
        streak = common(t - 0.01, 2, 0.20, 0.28) + [
            ('ParticleSpawnScript', 'InitializeParticle', 'Position Offset', v_vec3(*back(110))),
            ('ParticleSpawnScript', 'ShapeLocation', 'Sphere Radius', S.v_float(18.0)),
            ('ParticleSpawnScript', 'InitializeParticle', 'Color Mode', S.v_enum(E_COLOR, 1)),
            ('ParticleSpawnScript', 'InitializeParticle', 'Color', S.v_color(1, 1, 1, 1)),
            ('ParticleSpawnScript', 'InitializeParticle', 'Sprite Size Mode', S.v_enum(E_SIZE, 2)),
            ('ParticleSpawnScript', 'InitializeParticle', 'Sprite Size Min', v_vec2(12 * k, 520 * k)),
            ('ParticleSpawnScript', 'InitializeParticle', 'Sprite Size Max', v_vec2(22 * k, 780 * k)),
            ('ParticleSpawnScript', 'InitializeParticle', 'Sprite Rotation Mode', S.v_enum(E_ROT, 3)),
            ('ParticleSpawnScript', 'AddVelocity', 'Velocity Mode', S.v_enum(E_VEL, 0)),
            ('ParticleSpawnScript', 'AddVelocity', 'Velocity', v_vec3(dx * 420, dy * 420, dz * 420)),
            ('ParticleUpdateScript', 'Drag', 'Drag', S.v_float(2.5)),
            ('ParticleUpdateScript', 'ScaleSpriteSize', ['Scale Factor', 'Value', 'FloatCurve'],
             S.v_curve([(0.0, 0.45), (0.22, 1.15), (1.0, 0.55)])),
            ('ParticleUpdateScript', 'ScaleColor', ['Scale Alpha', 'FloatCurve'],
             S.v_curve([(0.0, 1.0), (0.6, 0.75), (1.0, 0.0)])),
        ]
        # splash: dark-blue ink just under the streak, lingers a bit longer
        sx, sy, sz = back(60)
        splash = common(t, 2, 0.30, 0.40) + [
            ('ParticleSpawnScript', 'InitializeParticle', 'Position Offset', v_vec3(sx, sy, max(sz - 12, 6))),
            ('ParticleSpawnScript', 'ShapeLocation', 'Sphere Radius', S.v_float(15.0)),
            ('ParticleSpawnScript', 'InitializeParticle', 'Color Mode', S.v_enum(E_COLOR, 1)),
            ('ParticleSpawnScript', 'InitializeParticle', 'Color', S.v_color(1, 1, 1, 1)),
            ('ParticleSpawnScript', 'InitializeParticle', 'Sprite Size Mode', S.v_enum(E_SIZE, 2)),
            ('ParticleSpawnScript', 'InitializeParticle', 'Sprite Size Min', v_vec2(80 * k, 230 * k)),
            ('ParticleSpawnScript', 'InitializeParticle', 'Sprite Size Max', v_vec2(115 * k, 320 * k)),
            ('ParticleSpawnScript', 'InitializeParticle', 'Sprite Rotation Mode', S.v_enum(E_ROT, 3)),
            ('ParticleSpawnScript', 'AddVelocity', 'Velocity Mode', S.v_enum(E_VEL, 0)),
            ('ParticleSpawnScript', 'AddVelocity', 'Velocity', v_vec3(dx * 200, dy * 200, dz * 200)),
            ('ParticleUpdateScript', 'Drag', 'Drag', S.v_float(4.0)),
            ('ParticleUpdateScript', 'ScaleSpriteSize', ['Scale Factor', 'Value', 'FloatCurve'],
             S.v_curve([(0.0, 0.6), (0.25, 1.0), (1.0, 1.1)])),
            ('ParticleUpdateScript', 'ScaleColor', ['Scale Alpha', 'FloatCurve'],
             S.v_curve([(0.0, 1.0), (0.5, 0.8), (1.0, 0.0)])),
        ]
        # sparks: short rays bursting out of the hit point
        sparks = common(t + 0.01, 8, 0.12, 0.24) + [
            ('ParticleSpawnScript', 'InitializeParticle', 'Position Offset', v_vec3(*pos)),
            ('ParticleSpawnScript', 'ShapeLocation', 'Sphere Radius', S.v_float(10.0)),
            ('ParticleSpawnScript', 'InitializeParticle', 'Color Mode', S.v_enum(E_COLOR, 2)),
            ('ParticleSpawnScript', 'InitializeParticle', 'Color Minimum', S.v_color(0.45, 0.85, 1.0, 1.0)),
            ('ParticleSpawnScript', 'InitializeParticle', 'Color Maximum', S.v_color(1.0, 0.85, 0.40, 1.0)),
            ('ParticleSpawnScript', 'InitializeParticle', 'Sprite Size Mode', S.v_enum(E_SIZE, 2)),
            ('ParticleSpawnScript', 'InitializeParticle', 'Sprite Size Min', v_vec2(5 * k, 90 * k)),
            ('ParticleSpawnScript', 'InitializeParticle', 'Sprite Size Max', v_vec2(10 * k, 220 * k)),
            ('ParticleSpawnScript', 'InitializeParticle', 'Sprite Rotation Mode', S.v_enum(E_ROT, 3)),
            ('ParticleSpawnScript', 'AddVelocity', 'Velocity Mode', S.v_enum(E_VEL, 1)),
            ('ParticleSpawnScript', 'AddVelocity', ['Velocity Speed', 'Minimum'], S.v_float(700)),
            ('ParticleSpawnScript', 'AddVelocity', ['Velocity Speed', 'Maximum'], S.v_float(1500)),
            ('ParticleUpdateScript', 'Drag', 'Drag', S.v_float(6.0)),
            ('ParticleUpdateScript', 'ScaleSpriteSize', ['Scale Factor', 'Value', 'FloatCurve'],
             S.v_curve([(0.0, 1.0), (1.0, 0.3)])),
            ('ParticleUpdateScript', 'ScaleColor', ['Scale Alpha', 'FloatCurve'],
             S.v_curve([(0.0, 1.0), (1.0, 0.0)])),
        ]
        out += [
            ('Hit%d_Splash' % n, 'MI_VFX_HitSplash', splash, ('VelocityAligned', 'FaceCamera'), 20),
            ('Hit%d_Streak' % n, 'MI_VFX_HitStreak', streak, ('VelocityAligned', 'FaceCamera'), 21),
            ('Hit%d_Sparks' % n, 'MI_VFX_LightRay', sparks, ('VelocityAligned', 'FaceCamera'), 22),
            ('Hit%d_Flash' % n, 'MI_VFX_HitFlash', flash, ('Unaligned', 'FaceCamera'), 23),
        ]
    return out


def ensure_materials(report):
    for name, parent, tex, tint, boost, extra in MATERIALS:
        path = C.MAT_DIR + '/' + name
        par = C.load(C.MAT_DIR + '/' + parent)
        texture = C.load(C.TEX_DIR + '/' + tex)
        if par is None or texture is None:
            report.error('%s: parent %s or texture %s missing' % (name, parent, tex))
            continue
        if C.asset_exists(path):
            mi = C.load(path)
        else:
            mi = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
                name, C.MAT_DIR, unreal.MaterialInstanceConstant, unreal.MaterialInstanceConstantFactoryNew())
            report.created(path)
        MEL.set_material_instance_parent(mi, par)
        MEL.set_material_instance_texture_parameter_value(mi, 'SpriteTex', texture)
        MEL.set_material_instance_vector_parameter_value(mi, 'TintColor', unreal.LinearColor(*tint))
        MEL.set_material_instance_scalar_parameter_value(mi, 'EmissiveBoost', boost)
        for k, v in extra.items():
            MEL.set_material_instance_scalar_parameter_value(mi, k, v)
        MEL.update_material_instance(mi)
        unreal.EditorAssetLibrary.save_asset(path, False)
        report.modified(path, 'parent %s, tex %s, tint %s, boost %.1f' % (parent, tex, tint[:3], boost))
    for parent in ('M_VFX_Sprite_Additive', 'M_VFX_Sprite_Translucent'):
        base = C.load(C.MAT_DIR + '/' + parent)
        usage = unreal.MaterialUsage.MATUSAGE_NIAGARA_SPRITES
        if not MEL.has_material_usage(base, usage):
            MEL.set_material_usage(base, usage)
            report.modified(C.MAT_DIR + '/' + parent, 'usage NiagaraSprites')


def _norm(v):
    """Comparable form of a stack value (json, rounded floats)."""
    def r(o):
        if isinstance(o, bool):
            return o
        if isinstance(o, (int, float)):
            return round(float(o), 4)
        if isinstance(o, dict):
            return {k: r(x) for k, x in o.items() if k not in ('displayName',)}
        if isinstance(o, list):
            return [r(x) for x in o]
        return o
    return json.dumps(r(v), sort_keys=True)


def current_values(em):
    vals = S.tool('GetEmitterInputValues', {'emitterRef': S.emitter_ref(em)})
    cur = {}
    for m in vals if isinstance(vals, list) else vals.get('modules', []):
        for iv in m.get('inputs', []):
            cur[(m['moduleName'], iv.get('name'))] = iv.get('value')
    return cur


def configure(report, em, mat, inputs, align, sort_hint):
    created = em not in S.emitter_names()
    if created:
        S.tool('AddEmitter', {'system': {'refPath': SYS_REF}, 'templateEmitter': {'refPath': TMP_SPRITE},
                              'emitterName': em})
        report.created('%s:%s' % (SYS_PKG, em))
        S.tool('SetModuleEnabled', {'moduleRef': {'system': {'refPath': SYS_REF}, 'emitterName': em,
                                                  'scriptName': 'ParticleUpdateScript', 'moduleName': 'GravityForce'},
                                    'bEnabled': False})
    cur = current_values(em)
    writes = 0
    for script, module, name, data in inputs:
        key = (module, name if isinstance(name, str) else None)
        if key[1] is not None and key in cur and _norm(cur[key]) == _norm(data):
            continue
        S.set_input(em, script, module, name, data)
        writes += 1

    rref = {'system': {'refPath': SYS_REF}, 'emitterName': em, 'rendererIndex': 0}
    props = json.loads(S.tool('GetRendererData', {'rendererRef': rref})['propertyValues'])
    mat_ref = '%s/%s.%s' % (C.MAT_DIR, mat, mat)
    want = {'Material': {'refPath': mat_ref}, 'Alignment': align[0], 'FacingMode': align[1],
            'SortOrderHint': int(sort_hint), 'bCastShadows': False}
    if any(props.get(k) != v for k, v in want.items()):
        props.update(want)
        S.tool('SetRendererData', {'rendererRef': rref, 'rendererData': {'propertyValues': json.dumps(props)}})
        writes += 1
    edata = json.loads(S.tool('GetEmitterData', {'emitterRef': S.emitter_ref(em)})['propertyValues'])
    fb = S.FIXED_BOUNDS
    ewant = {'bLocalSpace': True, 'bDeterminism': True, 'CalculateBoundsMode': 'Fixed',
             'FixedBounds': {'min': {'x': -fb, 'y': -fb, 'z': -fb}, 'max': {'x': fb, 'y': fb, 'z': fb}, 'isValid': True}}
    if any(edata.get(k) != v for k, v in ewant.items()):
        edata.update(ewant)
        S.tool('SetEmitterData', {'emitterRef': S.emitter_ref(em), 'emitterData': {'propertyValues': json.dumps(edata)}})
        writes += 1
    unreal.EditorAssetLibrary.save_asset(SYS_PKG, False)
    got = json.loads(S.tool('GetRendererData', {'rendererRef': rref})['propertyValues'])
    if got.get('Material', {}).get('refPath') != mat_ref:
        report.error('%s renderer material reads back %s' % (em, got.get('Material')))
    report.modified('%s:%s' % (SYS_PKG, em), '%d writes (%s)' % (writes, 'new' if created else 'update'))


def main():
    report = C.Report(SCRIPT_NAME)
    try:
        ensure_materials(report)
        for em, mat, inputs, align, sort_hint in emitter_specs():
            try:
                configure(report, em, mat, inputs, align, sort_hint)
            except Exception as exc:
                report.error('emitter %s' % em, exc)
        S.verify(report)
    except Exception as exc:
        report.error('hit feedback', exc)
    try:
        unreal.EditorAssetLibrary.save_asset(SYS_PKG, False)
        C.save_all(report)
    except Exception as exc:
        report.error('save', exc)
    report.finish()


if __name__ == '__main__':
    main()
