"""Acceptance captures for the ice-slash skill (NobleShore).

For every reference time T in SHOTS: open LS_IceSlash_v2 at T (character pose + cine camera),
then play NS_IceSlash_Skill deterministically to system time T - SKILL_START (reinitialise +
advance_simulation_by_time; SeekToDesiredAge drifts) and capture through IceSlash_Camera.
Writes Saved/VFX/shots/accept_<T>.png. The static blade actors are hidden (the blades live in
the Niagara system now). Run inside the editor (top-level await).
"""
import json
import unreal

SHOTS = [1.60, 2.10, 2.35, 2.85, 3.10, 3.30, 3.60]
SKILL_START = 1.50
SEQ = '/Game/VFX/IceSlash/Sequences/LS_IceSlash_v2'
OUT = '/Users/mengmeile/Downloads/lianxi/m/Saved/VFX/shots/'
LSE = unreal.LevelSequenceEditorBlueprintLibrary

sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
acts = {a.get_actor_label(): a for a in sub.get_all_level_actors() if a.get_actor_label().startswith('IceSlash_')}
for label, a in acts.items():
    if label.startswith('IceSlash_Arc_'):
        a.set_is_temporarily_hidden_in_editor(True)
cam = acts['IceSlash_Camera']
skill = acts['IceSlash_NS_Skill'].niagara_component
seq = unreal.EditorAssetLibrary.load_asset(SEQ)
LSE.open_level_sequence(seq)
LSE.set_lock_camera_cut_to_viewport(False)
unreal.ViewportService.set_game_view(True)
unreal.ViewportService.set_realtime(True)
skill.set_age_update_mode(unreal.NiagaraAgeUpdateMode.TICK_DELTA_TIME)
out = []
for t in SHOTS:
    LSE.set_current_time(int(round(t * 30)))   # display rate 30 fps
    LSE.refresh_current_level_sequence()
    await asyncio.sleep(0)
    skill.set_paused(False)
    skill.reinitialize_system()
    await asyncio.sleep(0)
    sys_t = t - SKILL_START
    if sys_t > 0:
        skill.advance_simulation_by_time(sys_t, 1.0 / 120.0)
    skill.set_paused(True)
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    comp = cam.get_cine_camera_component()
    fov = comp.get_editor_property('field_of_view')
    name = 'accept_%04d' % int(round(t * 1000))
    r = unreal.ViewportService.capture_with_view(cam.get_actor_location(), cam.get_actor_rotation(),
                                                 1280, 720, OUT + name + '.png', fov, True, 1.0)
    out.append([name, r.success, '' if r.success else r.error_message, round(fov, 1)])
skill.set_paused(False)
skill.reinitialize_system()
for label, a in acts.items():
    if label.startswith('IceSlash_Arc_'):
        a.set_is_temporarily_hidden_in_editor(False)
unreal.ViewportService.set_game_view(False)
LSE.close_level_sequence()
json.dumps(out)
