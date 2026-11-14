"""Ice-slash skill: ONE Niagara system, blades as mesh emitters (NobleShore).

The reference effect is a single Niagara system whose emitters are ordered on the Niagara
timeline. This script owns the backbone of /Game/VFX/IceSlash/Niagara/NS_IceSlash_Skill:

  Mist_01 .. Mist_05     one mesh particle each: SM_SlashMist_0N + MI_SlashMist_0N, the frost haze
                         left behind by its blade (ice_slash_08_mist.py), same timing rules.
  Smoke_01 .. Smoke_05   the same blade sheets with M_SlashSmoke (ice_slash_11_smoke.py), 35 cm lower,
                         drawn under the blades: the grey-white smoke layer of the reference.
  Blade_01 .. Blade_05   one mesh particle each: SM_SlashArc_0N + MI_SlashArcNS_0N.
                         The material sweeps the blade out and erases it from the particle's
                         normalised age (UseParticleTime = 1), so the only timing data are the
                         burst's Spawn Time and the particle Lifetime, both visible / draggable
                         on the Niagara timeline.

Rules shared with ChartreuseReef (who adds the particle layers to the same system):
  * emitters whose names start with Blade_, Mist_ or Smoke_ belong to this script;
  * this script never removes or edits any other emitter, and never recreates the system.

The system origin is the character's feet (blade meshes have their pivot there), so the level
needs exactly one NiagaraActor at the character root: IceSlash_NS_Skill (created here).

Idempotent: emitters are added only when missing; inputs / renderer / emitter data are written
every run (cheap, and the values are the contract).
"""
import json
import os
import sys
import importlib

import unreal
import vibeue

TOOLS_DIR = '/Users/mengmeile/Downloads/lianxi/m/Tools/IceSlash'
if TOOLS_DIR not in sys.path:
    sys.path.insert(0, TOOLS_DIR)
import ice_slash_common as C  # noqa: E402
importlib.reload(C)

SCRIPT_NAME = 'ice_slash_09_skill_blades'
NTS = 'NiagaraToolsets.NiagaraToolset_System'
SYS_NAME = 'NS_IceSlash_Skill'
SYS_PKG = C.NS_DIR + '/' + SYS_NAME
SYS_REF = SYS_PKG + '.' + SYS_NAME
TMP_SYSTEM = '/Niagara/DefaultAssets/Templates/Systems/MinimalLightweight.MinimalLightweight'
TMP_MESH_EMITTER = '/Niagara/DefaultAssets/Templates/Emitters/UpwardMeshBurst.UpwardMeshBurst'
ACTOR_LABEL = 'IceSlash_NS_Skill'

# System time in seconds = reference video time - 1.50 (first slash).
SKILL_DURATION = 3.0
#        emitter      mesh               material             spawn  life  sort
BLADES = [
    ('Blade_01', 'SM_SlashArc_01', 'MI_SlashArcNS_01', 0.00, 0.45, 10),
    ('Blade_02', 'SM_SlashArc_02', 'MI_SlashArcNS_02', 0.50, 0.45, 11),
    ('Blade_03', 'SM_SlashArc_03', 'MI_SlashArcNS_03', 0.75, 0.50, 12),
    ('Blade_04', 'SM_SlashArc_04', 'MI_SlashArcNS_04', 1.25, 0.45, 13),
    ('Blade_05', 'SM_SlashArc_05', 'MI_SlashArcNS_05', 1.50, 0.45, 14),
]
# Frost mist fans (ice_slash_08_mist.py): start with their blade, linger about twice as long, draw behind it.
MISTS = [
    ('Mist_01', 'SM_SlashMist_01', 'MI_SlashMist_01', 0.02, 0.90, 0),
    ('Mist_02', 'SM_SlashMist_02', 'MI_SlashMist_02', 0.52, 0.90, 1),
    ('Mist_03', 'SM_SlashMist_03', 'MI_SlashMist_03', 0.77, 1.00, 2),
    ('Mist_04', 'SM_SlashMist_04', 'MI_SlashMist_04', 1.27, 0.90, 3),
    ('Mist_05', 'SM_SlashMist_05', 'MI_SlashMist_05', 1.52, 0.90, 4),
]
MIST_ALPHA_CURVE = [(0.0, 1.0), (0.45, 1.0), (1.0, 0.0)]
# Under-blade smoke (ice_slash_11_smoke.py): the same sheet with the smoke material, shifted down
# and drawn under its blade; it trails the blade's sweep and lingers about twice as long.
SMOKE_OFFSET = (0.0, 0.0, -35.0)
SMOKES = [
    ('Smoke_01', 'SM_SlashArc_01', 'MI_SlashSmoke_01', 0.00, 0.95, 5),
    ('Smoke_02', 'SM_SlashArc_02', 'MI_SlashSmoke_02', 0.50, 0.95, 6),
    ('Smoke_03', 'SM_SlashArc_03', 'MI_SlashSmoke_03', 0.75, 1.05, 7),
    ('Smoke_04', 'SM_SlashArc_04', 'MI_SlashSmoke_04', 1.25, 0.95, 8),
    ('Smoke_05', 'SM_SlashArc_05', 'MI_SlashSmoke_05', 1.50, 0.95, 9),
]
SMOKE_ALPHA_CURVE = [(0.0, 1.0), (0.55, 0.85), (1.0, 0.0)]
# Template modules that would move / spin / shrink / recolour the blade.
DISABLED_MODULES = [
    ('ParticleSpawnScript', 'AddVelocity'),
    ('ParticleSpawnScript', 'InitialMeshOrientation'),
    ('ParticleUpdateScript', 'GravityForce'),
    ('ParticleUpdateScript', 'UpdateMeshOrientation'),
    ('ParticleUpdateScript', 'Drag'),
    ('ParticleUpdateScript', 'ScaleMeshSize'),
]
# Whole-blade fade over the particle's normalised age (Particle Color alpha -> material opacity).
ALPHA_CURVE = [(0.0, 1.0), (0.72, 1.0), (1.0, 0.0)]
ROOT_LABEL = 'IceSlash_SlashRoot'   # blades were authored in this actor's space (yaw -90, Y mirrored)
# ICE_SLASH_ONLY=Smoke_,Mist_ limits a run to emitters with those prefixes (each Niagara stack write
# rebuilds the whole system view model, so touching only what changed keeps the editor responsive).
ONLY = tuple(x for x in os.environ.get('ICE_SLASH_ONLY', '').split(',') if x)
FIXED_BOUNDS = 900.0   # cm half extent; the largest blade spans about 600 cm


def tool(name, args):
    return vibeue.exec_tool(NTS, name, args)


def v_float(v):
    return {'struct': {'refPath': '/Script/Niagara.NiagaraFloat'}, 'value': {'value': float(v)}}


def v_int(v):
    return {'struct': {'refPath': '/Script/Niagara.NiagaraInt32'}, 'value': {'value': int(v)}}


def v_color(r, g, b, a):
    return {'struct': {'refPath': '/Script/CoreUObject.LinearColor'},
            'value': {'r': float(r), 'g': float(g), 'b': float(b), 'a': float(a)}}


def v_enum(enum_path, index):
    short = enum_path.split('.')[-1]
    return {'struct': {'refPath': '/Script/NiagaraEditor.NiagaraExt_StackInputData_Enum'},
            'value': {'enum': {'refPath': enum_path}, 'enumName': '%s::NewEnumerator%d' % (short, index)}}


def v_curve(points):
    keys = [{'interpMode': 'RCIM_Cubic', 'tangentMode': 'RCTM_Auto', 'tangentWeightMode': 'RCTWM_WeightedNone',
             'time': float(t), 'value': float(v), 'arriveTangent': 0.0, 'arriveTangentWeight': 0.0,
             'leaveTangent': 0.0, 'leaveTangentWeight': 0.0} for t, v in points]
    payload = {'Curve': {'keys': keys, 'preInfinityExtrap': 'RCCE_Constant', 'postInfinityExtrap': 'RCCE_Constant'}}
    return {'struct': {'refPath': '/Script/NiagaraEditor.NiagaraExt_StackInputData_DataInterface'},
            'value': {'propertyValues': json.dumps(payload)}}


def emitter_ref(em):
    return {'system': {'refPath': SYS_REF}, 'emitterName': em}


def set_input(em, script, module, name, data):
    stack = [name] if isinstance(name, str) else list(name)
    return tool('SetStackInputData', {
        'stackInputRef': {'system': {'refPath': SYS_REF}, 'emitterName': em, 'scriptName': script,
                          'moduleName': module, 'inputNameStack': stack},
        'inputData': data})


def emitter_names():
    summary = tool('GetSystemSummary', {'system': {'refPath': SYS_REF}})
    return [e['emitterName'] for e in summary.get('emitters', [])]


def ensure_system(report):
    C.ensure_dir(C.NS_DIR)
    if C.asset_exists(SYS_PKG):
        report.skipped(SYS_PKG, 'system exists')
        return
    tool('CreateNiagaraSystem', {'assetName': SYS_NAME, 'assetPath': C.NS_DIR,
                                 'templateSystem': {'refPath': TMP_SYSTEM}})
    report.created(SYS_PKG)
    for em in emitter_names():           # only the template's own emitter, on a brand-new system
        tool('RemoveEmitter', {'emitterRef': emitter_ref(em)})
        report.info('removed template emitter %s' % em)


def configure_blade(report, em, mesh, mat, spawn_time, lifetime, sort_hint, alpha_curve=None, offset=None):
    if ONLY and not em.startswith(ONLY):
        return
    mesh_ref = '%s/%s.%s' % (C.MESH_DIR, mesh, mesh)
    mat_ref = '%s/%s.%s' % (C.MAT_DIR, mat, mat)
    for path in (C.MESH_DIR + '/' + mesh, C.MAT_DIR + '/' + mat):
        if not C.asset_exists(path):
            report.error('%s: %s missing (run ice_slash_01 / 03 first)' % (em, path))
            return
    if em not in emitter_names():
        tool('AddEmitter', {'system': {'refPath': SYS_REF}, 'templateEmitter': {'refPath': TMP_MESH_EMITTER},
                            'emitterName': em})
        report.created('%s:%s' % (SYS_PKG, em))
    for script, module in DISABLED_MODULES:
        tool('SetModuleEnabled', {'moduleRef': {'system': {'refPath': SYS_REF}, 'emitterName': em,
                                                'scriptName': script, 'moduleName': module},
                                  'bEnabled': False})

    # timing: one particle at spawn_time, living `lifetime` seconds; the emitter plays once
    set_input(em, 'EmitterUpdateScript', 'EmitterState', 'Loop Behavior',
              v_enum('/Niagara/Enums/ENiagara_EmitterStateOptions.ENiagara_EmitterStateOptions', 1))   # Once
    set_input(em, 'EmitterUpdateScript', 'EmitterState', 'Loop Duration', v_float(SKILL_DURATION))
    set_input(em, 'EmitterUpdateScript', 'SpawnBurst_Instantaneous', 'Spawn Count', v_int(1))
    set_input(em, 'EmitterUpdateScript', 'SpawnBurst_Instantaneous', 'Spawn Time', v_float(spawn_time))
    set_input(em, 'ParticleSpawnScript', 'InitializeParticle', 'Lifetime Mode',
              v_enum('/Niagara/Enums/ENiagara_LifetimeMode.ENiagara_LifetimeMode', 0))                 # Direct Set
    set_input(em, 'ParticleSpawnScript', 'InitializeParticle', 'Lifetime', v_float(lifetime))
    set_input(em, 'ParticleSpawnScript', 'InitializeParticle', 'Color Mode',
              v_enum('/Niagara/Enums/ENiagara_ColorInitializationMode.ENiagara_ColorInitializationMode', 1))  # Direct Set
    set_input(em, 'ParticleSpawnScript', 'InitializeParticle', 'Color', v_color(1, 1, 1, 1))
    if offset is not None:
        set_input(em, 'ParticleSpawnScript', 'InitializeParticle', 'UsePositionOffset',
                  {'struct': {'refPath': '/Script/Niagara.NiagaraBool'}, 'value': {'value': -1}})
        set_input(em, 'ParticleSpawnScript', 'InitializeParticle', 'Position Offset',
                  {'struct': {'refPath': '/Script/CoreUObject.Vector3f'},
                   'value': {'x': float(offset[0]), 'y': float(offset[1]), 'z': float(offset[2])}})
    set_input(em, 'ParticleSpawnScript', 'InitializeParticle', 'Mesh Scale Mode',
              v_enum('/Niagara/Enums/ENiagara_SizeScaleMode.ENiagara_SizeScaleMode', 0))               # Unset = 1,1,1

    tool('SetModuleEnabled', {'moduleRef': {'system': {'refPath': SYS_REF}, 'emitterName': em,
                                            'scriptName': 'ParticleUpdateScript', 'moduleName': 'ScaleColor'},
                              'bEnabled': True})
    set_input(em, 'ParticleUpdateScript', 'ScaleColor', ['Scale Alpha', 'FloatCurve'], v_curve(alpha_curve or ALPHA_CURVE))

    # renderer: the blade mesh as authored (pivot at the character root), Niagara material instance
    rref = {'system': {'refPath': SYS_REF}, 'emitterName': em, 'rendererIndex': 0}
    props = json.loads(tool('GetRendererData', {'rendererRef': rref})['propertyValues'])
    entry = props['Meshes'][0]
    entry['mesh'] = {'refPath': mesh_ref}
    entry['scale'] = {'x': 1.0, 'y': 1.0, 'z': 1.0}
    entry['rotation'] = {'pitch': 0.0, 'yaw': 0.0, 'roll': 0.0}
    entry['pivotOffset'] = {'x': 0.0, 'y': 0.0, 'z': 0.0}
    props['Meshes'] = [entry]
    props['FacingMode'] = 'Default'
    props['bOverrideMaterials'] = True
    override = props['OverrideMaterials'][0] if props.get('OverrideMaterials') else {}
    override['explicitMat'] = {'refPath': mat_ref}
    props['OverrideMaterials'] = [override]
    props['bCastShadows'] = False
    props['SortOrderHint'] = int(sort_hint)
    tool('SetRendererData', {'rendererRef': rref, 'rendererData': {'propertyValues': json.dumps(props)}})

    # emitter: local space (follows the actor), fixed bounds so the big sheet is never culled
    edata = json.loads(tool('GetEmitterData', {'emitterRef': emitter_ref(em)})['propertyValues'])
    edata['bLocalSpace'] = True
    edata['bDeterminism'] = True
    edata['CalculateBoundsMode'] = 'Fixed'
    edata['FixedBounds'] = {'min': {'x': -FIXED_BOUNDS, 'y': -FIXED_BOUNDS, 'z': -FIXED_BOUNDS},
                            'max': {'x': FIXED_BOUNDS, 'y': FIXED_BOUNDS, 'z': FIXED_BOUNDS}, 'isValid': True}
    tool('SetEmitterData', {'emitterRef': emitter_ref(em), 'emitterData': {'propertyValues': json.dumps(edata)}})

    # read back the contract
    got = json.loads(tool('GetRendererData', {'rendererRef': rref})['propertyValues'])
    got_mesh = got['Meshes'][0]['mesh'].get('refPath')
    got_mat = (got.get('OverrideMaterials') or [{}])[0].get('explicitMat', {}).get('refPath')
    if got_mesh != mesh_ref or got_mat != mat_ref:
        report.error('%s renderer reads back mesh=%s material=%s' % (em, got_mesh, got_mat))
    else:
        report.modified('%s:%s' % (SYS_PKG, em), 'mesh %s, material %s, spawn %.2fs, life %.2fs' % (
            mesh, mat, spawn_time, lifetime))


def verify(report):
    state = tool('GetSystemCompileState', {'system': {'refPath': SYS_REF}})
    report.info('COMPILE %s: %s' % (SYS_NAME, json.dumps(state, default=str)[:400]))
    issues = tool('GetStackIssues', {'system': {'refPath': SYS_REF}})
    rows = issues.get('issues', []) if isinstance(issues, dict) else []
    mine = [i for i in rows if any(k in json.dumps(i, default=str) for k in ('Blade_', 'Mist_', 'Smoke_'))]
    for i in mine:
        text = json.dumps(i, default=str)
        sev = str(i.get('severity', ''))
        (report.error if 'Error' in sev else report.info)('issue: %s' % text[:300])
    report.info('EMITTERS %s: %s' % (SYS_NAME, emitter_names()))


def ensure_actor(report):
    """One NiagaraActor at the character root plays the whole skill."""
    sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    actor = None
    for a in sub.get_all_level_actors():
        if a.get_actor_label() == ACTOR_LABEL:
            actor = a
            break
    system = C.load(SYS_PKG)
    if actor is None:
        actor = sub.spawn_actor_from_object(system, unreal.Vector(0, 0, 0), unreal.Rotator(0, 0, 0))
        if actor is None:
            report.error('could not spawn %s' % ACTOR_LABEL)
            return
        actor.set_actor_label(ACTOR_LABEL)
        report.created('actor ' + ACTOR_LABEL)
    root = next((a for a in sub.get_all_level_actors() if a.get_actor_label() == ROOT_LABEL), None)
    if root is None:
        report.error('%s missing: the skill actor is not aligned with the blades' % ROOT_LABEL)
    elif actor.get_attach_parent_actor() != root:
        rule = unreal.AttachmentRule.KEEP_RELATIVE
        actor.attach_to_actor(root, '', rule, rule, rule, False)
        actor.root_component.set_relative_transform(unreal.Transform(), False, False)
        report.modified('actor ' + ACTOR_LABEL, 'attached to %s (relative identity)' % ROOT_LABEL)
    comp = actor.niagara_component
    if comp.get_asset() != system:
        comp.set_asset(system)
        report.modified('actor ' + ACTOR_LABEL, 'asset = ' + SYS_PKG)
    else:
        report.skipped('actor ' + ACTOR_LABEL, 'already uses ' + SYS_NAME)


def main():
    report = C.Report(SCRIPT_NAME)
    try:
        ensure_system(report)
        for row in BLADES:
            try:
                configure_blade(report, *row)
            except Exception as exc:
                report.error('blade emitter %s' % row[0], exc)
        for row in MISTS:
            try:
                configure_blade(report, *row, alpha_curve=MIST_ALPHA_CURVE)
            except Exception as exc:
                report.error('mist emitter %s' % row[0], exc)
        for row in SMOKES:
            try:
                configure_blade(report, *row, alpha_curve=SMOKE_ALPHA_CURVE, offset=SMOKE_OFFSET)
            except Exception as exc:
                report.error('smoke emitter %s' % row[0], exc)
        verify(report)
        ensure_actor(report)
    except Exception as exc:
        report.error('skill system', exc)
    try:
        unreal.EditorAssetLibrary.save_asset(SYS_PKG, False)
        C.save_all(report)
    except Exception as exc:
        report.error('save', exc)
    report.finish()


if __name__ == '__main__':
    main()
