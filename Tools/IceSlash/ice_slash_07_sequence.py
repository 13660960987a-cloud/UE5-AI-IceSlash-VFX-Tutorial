"""Ice Slash v2, step 07: build the showcase LevelSequence LS_IceSlash_v2.

Run order: 01 import, 02 anim+sockets, 03 slash material, 04 crystal material,
05 niagara, 06 showcase level, 07 sequence (this script).

Run inside the UE 5.9 editor (synchronous, no top-level await):
    import runpy; runpy.run_path('/Users/mengmeile/Downloads/lianxi/m/Tools/IceSlash/ice_slash_07_sequence.py', run_name='__main__')

What it does:
  * Makes sure C.MAP_PATH (from script 06) is the open level. If another level is open it
    loads it only through C.guard_resident_maps + vibeue.safe_load_level (AGENTS.md sections 1, 9).
  * Creates C.SEQ_DIR + '/LS_IceSlash_v2' when it is missing (7.0 s, 30 fps display rate,
    playback range 0-7 s). An existing asset is never deleted.
  * Binds the actors that script 06 created (possessables found by actor label) and adds:
      - IceSlash_Guard body SkeletalMeshComponent: skeletal animation track with three sections:
        hold frame 0 (play rate 0) | play AS_Guard_IceSlash_Combo from anim_start_offset_s |
        hold the last frame (play rate 0, start offset = clip length) until 7.0 s.
      - IceSlash_Arc_01..05: actor visibility track (hidden, visible from FX_Slash_0N for
        arc_reveal.gone_s) and a component material track on StaticMeshComponent slot 0
        (SlashProgress, SlashWidth, DissolveAmount keys).
      - IceSlash_NS_*: Niagara system life-cycle tracks (MovieSceneNiagaraSystemTrack) on the
        NiagaraComponent bindings.
      - IceSlash_Crystal_<Part>: component material track (CrystalGrowth staggered by role,
        CrystalGlow, CrystalOpacity).
      - IceSlash_Camera: camera cut track 0-7 s plus a 3D transform track with eased keys.
      - One Sequencer mark per timeline event (FX_Slash_01 ... FX_End) for reference.
      - Sequencer preview captures (CAPTURE_SHOTS): LS_IceSlash_v2 is opened in Sequencer, each time in
        CAPTURE_TIMES_S is set with set_playhead_frame_async, the camera-cut viewport lock is turned on
        and the real level viewport (sequencer camera) is drawn once with ViewportService.capture_with_view,
        giving Saved/VFX/shots/seq_<s>.png (seq_0p5.png ... seq_5p4.png). Each draw advances the Sequencer
        by one CAPTURE_RENDER_FPS-sized dT, which the next move compensates for; r.CustomDepth is 0 for
        the draws (it would composite third-party editor gizmos) and the viewport lock and CVar are
        restored afterwards. The step is async, so run this through execute_python and await main().
  * Saves the sequence, prints a binding/track/section/key summary, writes the 'sequence'
    manifest section and finishes with report.finish() (raises RuntimeError on any error).

Idempotency:
  * REBUILD = False: existing tracks/sections are verified (key counts, ranges) and left as
    they are; missing ones are created. FORCE = True additionally re-keys existing tracks in
    place (keys at the same frames are updated, MovieSceneCurveChannelImpl.cpp:1129-1138).
  * REBUILD = True: every track of every binding, every master track and this script's marks
    are removed from the existing asset and rebuilt; bindings that no longer resolve are removed.
"""

import asyncio
import contextlib
import sys
import importlib
import math
import os

import unreal

TOOLS_DIR = '/Users/mengmeile/Downloads/lianxi/m/Tools/IceSlash'
if TOOLS_DIR not in sys.path:
    sys.path.insert(0, TOOLS_DIR)
import ice_slash_common as C
importlib.reload(C)


# ---------------------------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------------------------
SCRIPT_NAME = 'ice_slash_07_sequence'
REBUILD = True    # True: clear all tracks of the existing sequence and rebuild them (asset kept)
FORCE = False     # True: re-key existing tracks in place (upsert at the same frames)
SAVE_DIRTY_LEVEL_BEFORE_LOAD = False  # True: save a dirty open level before switching to MAP_PATH
                                      # (LoadLevel fails on a dirty level, LevelEditorSubsystem.h:200-210)
USE_V3_REF_TIMELINE = True            # True: use unified v3 reference timeline (1.50s = system t=0.00s)

SEQ_NAME = 'LS_IceSlash_v2'
SEQ_PATH = C.SEQ_DIR + '/' + SEQ_NAME
DURATION_S = 5.5
DISPLAY_FPS = 30
ROOT_FOLDER = 'IceSlash'

ANIM_GUARD = C.ANIM_DIR + '/AS_Guard_IceSlash_Combo'
ANIM_MANNY = C.ANIM_DIR + '/AS_Manny_IceSlash_Combo'
HOLD_LAST_EPSILON_S = 0.001   # hold section samples clip_length - epsilon (stays inside the clip)

# Unified v3 skill timeline (reference video seconds; NS_IceSlash_Skill starts at FX_Slash_01 = 1.50 s).
CTX = {
    'timeline': {
        'FX_HandEnergy_Start': 0.0,
        'FX_Slash_01': 1.50,
        'FX_Slash_02': 2.00,
        'FX_Slash_03': 2.25,
        'FX_Slash_04': 2.75,
        'FX_Slash_05': 3.00,
        'FX_Slash_Impact': 3.25,
        'FX_IceBurst': 3.50,
        'FX_CrystalReveal': 3.25,
        'FX_CrystalHold': 3.45,
        'FX_End': 4.80,
    },
    'arc_reveal': {'start_offset_s': 0.05, 'full_s': 0.20, 'gone_s': 0.35},
    'anim_start_offset_s': 1.1667,
    'anim_duration_s': 2.0333,
}

GUARD_LABEL = 'IceSlash_Guard'
CAMERA_LABEL = 'IceSlash_Camera'
CRYSTAL_ROOT_LABEL = 'IceSlash_CrystalRoot'
CRYSTAL_PREFIX = 'IceSlash_Crystal_'
SKILL_NS_LABEL = 'IceSlash_NS_Skill'
ARC_LABELS = ['IceSlash_Arc_%02d' % i for i in range(1, 6)]

# Arc material keys (unused when NS_IceSlash_Skill owns Blade_01..05).
ARC_DISSOLVE_LEAD_S = 0.10
ARC_DISSOLVE_END = 0.6
ARC_SLASH_WIDTH = 1.0

# Niagara windows: trigger unified NS_IceSlash_Skill once at FX_Slash_01 (1.50 s -> system t=0.00 s).
SPARKLE_DELAY_S = 0.10
SPARKLE_WINDOW_S = 0.60
NIAGARA_WINDOWS = [
    (SKILL_NS_LABEL, 'FX_Slash_01', 0.0, 'FX_End', 'burst'),
]
NIAGARA_AGE_MODE = 'TICK_DELTA_TIME'

# Crystals (sequence seconds).
CRYSTAL_PRISM_STAGGER = [0.02, 0.04, 0.06, 0.08, 0.10]   # non-core prisms in data order
CRYSTAL_BOULDER_DELAY = 0.02
CRYSTAL_SNOWBASE_LEAD = 0.05
CRYSTAL_GLOW_KEYS = [(0.0, 0.3), (0.3, 1.2), (None, 0.5)]   # +FX_CrystalHold; None = FX_End
CRYSTAL_FADE = [(4.9, 1.0), (5.5, 0.0)]

# Camera: elevated 3/4 view matching reference framing.
CAM_SIDE = -1.0
CAM_BASE_DIST_CM = 920.0
LUNGE_FOCUS_FWD_CM = 40.0
LUNGE_FOCUS_UP_CM = 105.0
CRYSTAL_FOCUS_UP_CM = 140.0
CRYSTAL_FALLBACK_FWD_CM = 125.0
# (time, focus, distance factor, azimuth deg, elevation deg, roll deg, z jitter cm, interpolation)
CAM_KEYS = [
    (0.00, 'lunge', 1.000, 38.0, 26.0, 0.0, 0.0, 'SMART_AUTO'),     # elevated 3/4 front
    (1.50, 'lunge', 0.960, 38.0, 26.0, 0.0, 0.0, 'SMART_AUTO'),     # horizontal slashes 1-3
    (2.45, 'lunge', 0.960, 38.0, 25.0, 0.0, 0.0, 'SMART_AUTO'),     # transition to vertical
    (2.75, 'lunge', 1.040, 42.0, 15.0, 0.0, 0.0, 'SMART_AUTO'),     # vertical slashes 4-5
    (3.20, 'lunge', 1.020, 40.0, 20.0, 0.0, 0.0, 'SMART_AUTO'),     # before landing impact
    (3.30, 'crystal', 0.960, 40.0, 22.0, 1.1, 6.0, 'AUTO'),         # landing impact shake 1
    (3.38, 'crystal', 0.960, 40.0, 22.0, -0.8, -4.0, 'AUTO'),       # landing impact shake 2
    (3.50, 'crystal', 1.080, 40.0, 23.0, 0.0, 0.0, 'SMART_AUTO'),   # crystal burst reveal
    (4.80, 'crystal', 1.120, 45.0, 23.0, 0.0, 0.0, 'SMART_AUTO'),   # hold on crystals
    (5.50, 'crystal', 1.140, 52.0, 23.0, 0.0, 0.0, 'SMART_AUTO'),   # gentle orbit out
]

MARK_EVENTS = ['FX_HandEnergy_Start', 'FX_Slash_01', 'FX_Slash_02', 'FX_Slash_03', 'FX_Slash_04',
               'FX_Slash_05', 'FX_Slash_Impact', 'FX_IceBurst', 'FX_CrystalReveal',
               'FX_CrystalHold', 'FX_End']

# Sequencer preview captures: disabled by default in v3 (use skill_shots deterministic simulation).
CAPTURE_SHOTS = False
CAPTURE_TIMES_S = [0.5, 1.6, 2.2, 2.6, 4.6, 5.4]
CAPTURE_FILES = {0.5: 'seq_0-5.png', 1.6: 'seq_1-6.png', 2.2: 'seq_2-2.png', 2.6: 'seq_2-6.png',
                 4.6: 'seq_4-6.png', 5.4: 'seq_5-4.png'}   # '-' is written as 'p'
CAPTURE_DIR = C.SHOTS_DIR
CAPTURE_W, CAPTURE_H = 1280, 720
CAPTURE_SETTLE_S = 0.15      # awaited between a playhead move and its draw
SAVE_BEFORE_CAPTURE = True   # save the sequence before drawing (Sequencer may re-evaluate on save)
CAPTURE_ATTEMPTS = 8         # (unlock + draw + relock) rounds until the sequence camera is frozen
# r.CustomDepth renders the CustomDepth buffer in the level viewport (UnrealCanvasBridge enables it),
# which draws third-party editor overlays (green gizmo arrows) over the shot. 0 for the draws only.
CUSTOM_DEPTH_CVAR = 'r.CustomDepth'


# ---------------------------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------------------------
class Ctx(object):
    def __init__(self, report):
        self.report = report
        self.seq = None
        self.world = None
        self.ticks_per_s = 24000.0
        self.display_fps = float(DISPLAY_FPS)
        self.data = {}
        self.timeline = dict(CTX['timeline'])
        self.arc_reveal = dict(CTX['arc_reveal'])
        self.anim_offset = CTX['anim_start_offset_s']
        self.actors = {}
        self.todos = []
        self.created_tracks = []
        self.capture_evidence = {}
        self.verified_tracks = []
        self.bindings = {}
        self.anim_info = {}
        self.camera_info = {}
        self.seq_created = False
        self.dirty = False

    # time helpers --------------------------------------------------------------------------
    def tick(self, seconds):
        """Seconds -> unreal.FrameNumber in TICK resolution (material keys take tick frames,
        MovieSceneComponentMaterialParameterSection.h:108-114)."""
        return unreal.FrameNumber(int(round(float(seconds) * self.ticks_per_s)))

    def t(self, event):
        return float(self.timeline[event])

    # report helpers ------------------------------------------------------------------------
    def todo(self, msg):
        self.todos.append(msg)
        self.report.todo(msg)

    def actor(self, label):
        return self.actors.get(label)


def tpath(*parts):
    return SEQ_PATH + ':' + '/'.join(parts)


def interp(name):
    # unreal.MovieSceneKeyInterpolation members: AUTO, USER, BREAK, LINEAR, CONSTANT, SMART_AUTO
    # (KeyParams.h:11-28). There is no CUBIC.
    return getattr(unreal.MovieSceneKeyInterpolation, name)


def num_keys(channel):
    try:
        return int(channel.get_num_keys())   # MovieSceneScriptingDouble.h:347, Float.h:541, Bool.h:154
    except Exception:
        try:
            return len(channel.get_keys())
        except Exception:
            return -1


def channel_name(channel):
    try:
        return str(channel.get_editor_property('channel_name'))   # MovieSceneScriptingChannel.h:87-88
    except Exception:
        return '?'


def section_key_counts(section):
    out = {}
    try:
        for ch in section.get_all_channels():   # MovieSceneSectionExtensions.h:498-499
            out[channel_name(ch)] = num_keys(ch)
    except Exception as exc:
        out['error'] = str(exc)
    return out


def first_component(actor, cls):
    try:
        comps = list(actor.get_components_by_class(cls))   # Actor.h:3806-3807 (ScriptName)
    except Exception:
        comps = []
    return comps[0] if comps else None


# ---------------------------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------------------------
def step_load_data(ctx):
    """Read timeline/arc_reveal/anim offset from the offline data JSON, plan values as fallback."""
    try:
        data = C.load_data()
        ctx.data = data or {}
    except Exception as exc:
        ctx.report.error('load_data failed; using plan values from CTX', exc)
        ctx.data = {}
    if not USE_V3_REF_TIMELINE:
        for item in ctx.data.get('timeline', []) or []:
            try:
                ctx.timeline[str(item['event'])] = float(item['time_s'])
            except Exception:
                pass
        for k, v in (ctx.data.get('arc_reveal') or {}).items():
            try:
                ctx.arc_reveal[k] = float(v)
            except Exception:
                pass
        if 'anim_start_offset_s' in ctx.data:
            ctx.anim_offset = float(ctx.data['anim_start_offset_s'])
    ctx.report.info('timeline %s' % ', '.join('%s=%.4f' % (k, ctx.timeline[k]) for k in MARK_EVENTS
                                               if k in ctx.timeline))
    ctx.report.info('arc_reveal %s anim_start_offset_s=%.4f' % (ctx.arc_reveal, ctx.anim_offset))


def step_level(ctx):
    """Make C.MAP_PATH the open level, loading it only through the resident-map guards."""
    current = C.current_level_path()
    ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
    if current == C.MAP_PATH:
        ctx.report.skipped(C.MAP_PATH, 'already the open level')
        ctx.world = ues.get_editor_world()
        return True
    if not C.asset_exists(C.MAP_PATH):
        ctx.report.error('level %s does not exist; run ice_slash_06_showcase first' % C.MAP_PATH)
        return False
    # LoadLevel's default policy is Fail when the open level is dirty and raises a script error
    # naming the packages (LevelEditorSubsystem.h:200-210, ELevelEditorUnsavedChangesPolicy :38-47).
    # The open level may belong to the editor owner, so it is only saved when allowed explicitly.
    dirty = [str(p) for p in unreal.PythonTools.get_dirty_packages(True)]   # PythonTools.h:75
    if current and current in dirty:
        if not SAVE_DIRTY_LEVEL_BEFORE_LOAD or not C.is_owned(C.package_name(current)):
            # Never save a level outside the IceSlash root (AGENTS.md section 9; C.save_all policy).
            ctx.report.error('open level %s has unsaved changes; save it (or set SAVE_DIRTY_LEVEL_BEFORE_LOAD '
                             'for an IceSlash-owned level) before this script switches to %s'
                             % (current, C.MAP_PATH))
            return False
        les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
        if les.save_current_level():   # LevelEditorSubsystem.h:217
            ctx.report.info('saved dirty open level %s before the level change' % current)
        else:
            ctx.report.error('could not save dirty open level %s' % current)
            return False
    # C.load_level: guard_resident_maps + vibeue.safe_load_level (vibeue.py:530-606), and it
    # verifies the open level afterwards.
    if not C.load_level(C.MAP_PATH, ctx.report):
        return False
    ctx.world = ues.get_editor_world()
    ctx.report.info('LOADED_LEVEL: %s (was %s)' % (C.MAP_PATH, current))
    return True


def step_collect_actors(ctx):
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    for a in eas.get_all_level_actors():   # EditorActorSubsystem.h:168
        try:
            label = a.get_actor_label()
        except Exception:
            continue
        if label.startswith('IceSlash_'):
            ctx.actors[label] = a
    ctx.report.info('found %d IceSlash_ actors: %s' % (len(ctx.actors), sorted(ctx.actors.keys())))
    for need in [GUARD_LABEL, CAMERA_LABEL, SKILL_NS_LABEL]:
        if need not in ctx.actors:
            ctx.report.error('actor %s not found in %s (script 06 creates it)' % (need, C.MAP_PATH))


def step_sequence_asset(ctx):
    """Create or load LS_IceSlash_v2 and apply rates and ranges."""
    if C.asset_exists(SEQ_PATH):
        seq = C.load(SEQ_PATH)
        if seq is None:
            ctx.report.error('could not load %s' % SEQ_PATH)
            return False
        ctx.report.skipped(SEQ_PATH, 'exists; REBUILD=%s FORCE=%s' % (REBUILD, FORCE))
    else:
        C.ensure_dir(C.SEQ_DIR)
        tools = unreal.AssetToolsHelpers.get_asset_tools()
        # create_asset does not call the factory's ConfigureProperties, so no dialog opens.
        # LevelSequenceFactoryNew.cpp initialises the movie scene (G5 digest section 6).
        seq = tools.create_asset(SEQ_NAME, C.SEQ_DIR, unreal.LevelSequence, unreal.LevelSequenceFactoryNew())
        if seq is None:
            ctx.report.error('create_asset failed for %s' % SEQ_PATH)
            return False
        ctx.seq_created = True
        ctx.report.created(SEQ_PATH)
    ctx.seq = seq

    # Display rate, playback range (MovieSceneSequenceExtensions.h:136, 248, 270, 346, 350).
    want_rate = unreal.FrameRate(DISPLAY_FPS, 1)
    cur_rate = seq.get_display_rate()
    if (cur_rate.numerator, cur_rate.denominator) != (DISPLAY_FPS, 1):
        seq.set_display_rate(want_rate)
        ctx.report.modified(SEQ_PATH, 'display rate %d/%d -> %d/1' % (cur_rate.numerator, cur_rate.denominator, DISPLAY_FPS))
        ctx.dirty = True
    ps, pe = seq.get_playback_start_seconds(), seq.get_playback_end_seconds()
    if abs(ps - 0.0) > 1e-4 or abs(pe - DURATION_S) > 1e-4:
        seq.set_playback_start_seconds(0.0)
        seq.set_playback_end_seconds(DURATION_S)
        seq.set_view_range(-0.2, DURATION_S + 0.2)
        seq.set_work_range(-0.2, DURATION_S + 0.2)
        ctx.report.modified(SEQ_PATH, 'playback range %.3f-%.3f -> 0-%.1f s' % (ps, pe, DURATION_S))
        ctx.dirty = True
    tr = seq.get_tick_resolution()   # :145; the factory's default is kept (times are converted)
    ctx.ticks_per_s = float(tr.numerator) / float(tr.denominator or 1)
    try:
        fr = seq.get_display_rate()
        ctx.display_fps = float(fr.numerator) / float(fr.denominator or 1)
    except Exception:
        ctx.display_fps = float(DISPLAY_FPS)
    ctx.report.info('SEQ_RATES: display=%d/%d tick=%d/%d playback=%.3f-%.3f s' % (
        seq.get_display_rate().numerator, seq.get_display_rate().denominator, tr.numerator, tr.denominator,
        seq.get_playback_start_seconds(), seq.get_playback_end_seconds()))
    return True


def step_rebuild_clear(ctx):
    """REBUILD: remove all tracks of all bindings, the master tracks, stale bindings and our marks."""
    if not REBUILD or ctx.seq_created:
        return
    seq = ctx.seq
    removed = 0
    for b in list(seq.get_bindings()):   # MovieSceneSequenceExtensions.h:438
        try:
            name = b.get_name()
            objs = list(seq.locate_bound_objects(b, ctx.world))   # :510
            for t in list(b.get_tracks()):   # MovieSceneBindingExtensions.h:108
                b.remove_track(t)            # :137
                removed += 1
            if not objs and name.startswith('IceSlash_'):
                b.remove()                   # :145
                ctx.report.info('REMOVED stale binding %s (no bound object in %s)' % (name, C.MAP_PATH))
        except Exception as exc:
            ctx.report.error('REBUILD clear binding failed', exc)
    for t in list(seq.get_tracks()):   # master tracks (camera cut lives here), :76
        try:
            seq.remove_track(t)        # :118
            removed += 1
        except Exception as exc:
            ctx.report.error('REBUILD remove master track failed', exc)
    for label in MARK_EVENTS:
        try:
            idx = seq.find_marked_frame_by_label(label)   # :773
            if idx >= 0:
                seq.delete_marked_frame(idx)              # :753
        except Exception as exc:
            ctx.report.error('REBUILD remove mark %s failed' % label, exc)
    ctx.dirty = True
    ctx.report.modified(SEQ_PATH, 'REBUILD removed %d track(s)' % removed)


def bind(ctx, obj, key):
    """seq.add_possessable is find-or-add: ULevelSequence::CreatePossessable -> FindOrAddBinding
    returns the existing binding id (LevelSequence.cpp:880-933, 964-967). Binding a component
    first binds its owning actor (parent binding)."""
    b = ctx.seq.add_possessable(obj)
    if not b.is_valid():   # MovieSceneBindingExtensions.h:28 (ScriptMethod on the proxy)
        raise RuntimeError('add_possessable returned an invalid binding for %s' % key)
    ctx.bindings[key] = b.get_name()
    return b


def get_or_add_track(ctx, binding, cls, key):
    """Returns (track, created). Bindings' add_track always appends (G5 digest), so look first."""
    tracks = list(binding.find_tracks_by_exact_type(cls))   # MovieSceneBindingExtensions.h:128
    if tracks:
        if len(tracks) > 1:
            ctx.todo('%s has %d %s tracks; only the first is managed (set REBUILD=True to clean up)'
                     % (key, len(tracks), cls.__name__))
        return tracks[0], False
    t = binding.add_track(cls)   # :155
    if t is None:
        raise RuntimeError('add_track(%s) returned None for %s' % (cls.__name__, key))
    ctx.dirty = True
    ctx.created_tracks.append(key)
    ctx.report.created(tpath(key))
    return t, True


def get_or_add_section(ctx, track, key):
    secs = list(track.get_sections())   # MovieSceneTrackExtensions.h:95
    if secs:
        return secs[0], False
    s = track.add_section()             # :77
    if s is None:
        raise RuntimeError('add_section returned None for %s' % key)
    ctx.dirty = True
    return s, True


def verify_counts(ctx, key, section, expected):
    """expected: {channel name: key count}. Records SKIPPED or a TODO when they differ."""
    got = section_key_counts(section)
    bad = {k: (got.get(k), v) for k, v in expected.items() if got.get(k) != v}
    if bad:
        ctx.todo('%s key counts differ from the plan %s (got, want); set FORCE=True or REBUILD=True'
                 % (key, bad))
    else:
        ctx.report.skipped(tpath(key), 'verified keys %s' % expected)
    ctx.verified_tracks.append(key)


# --- Guard skeletal animation --------------------------------------------------------------------
def pick_body_component(ctx, actor):
    comps = []
    try:
        comps = list(actor.get_components_by_class(unreal.SkeletalMeshComponent))
    except Exception as exc:
        ctx.report.error('get_components_by_class on %s failed' % GUARD_LABEL, exc)
    named = []
    for c in comps:
        try:
            mesh = c.get_skeletal_mesh_asset()   # SkeletalMeshComponent.h:374 (BlueprintPure)
            named.append((c, mesh, mesh.get_name() if mesh else ''))
        except Exception:
            named.append((c, None, ''))
    ctx.report.info('%s skeletal components: %s' % (GUARD_LABEL, [(c.get_name(), n) for c, _, n in named]))
    for c, m, n in named:
        if n == 'SK_Guard':
            return c, m
    for c, m, n in named:
        if m is not None and 'head' not in n.lower():
            return c, m
    return (named[0][0], named[0][1]) if named else (None, None)


def apply_anim_section(ctx, sec, anim_path, start_s, end_s, anim_offset_s, rate):
    # set_skeletal_animation only sets Params.Animation (MovieSceneSectionExtensions.h:439,
    # .cpp:745-806); it is a PythonCallable static, not a method.
    unreal.MovieSceneSectionExtensions.set_skeletal_animation(sec, anim_path)
    params = sec.get_editor_property('params')   # struct copy (MovieSceneSkeletalAnimationSection.h:119-120)
    # StartFrameOffset is in the sequence's tick resolution: MakeTransform divides it by the
    # outer (tick) frame rate (MovieSceneSkeletalAnimationSection.cpp:55-87).
    params.set_editor_property('start_frame_offset', ctx.tick(anim_offset_s))
    # Play even when an AnimBlueprint drives the component (header: bForceCustomMode).
    params.set_editor_property('force_custom_mode', True)
    sec.set_editor_property('params', params)
    sec.set_range_seconds(start_s, end_s)   # MovieSceneSectionExtensions.h:337
    # PlayRate lives inside Params, so set it after writing Params back. 0 = hold the section on
    # its first frame (MovieSceneTimeWarpExtensions.h:92-96, .cpp:181-197).
    unreal.MovieSceneTimeWarpExtensions.set_section_play_rate(sec, float(rate))


def step_guard(ctx):
    key = GUARD_LABEL + '/SkeletalAnimation'
    actor = ctx.actor(GUARD_LABEL)
    if actor is None:
        return
    try:
        body, mesh = pick_body_component(ctx, actor)
        if body is None:
            ctx.report.error('%s has no SkeletalMeshComponent' % GUARD_LABEL)
            return
        mesh_name = mesh.get_name() if mesh else ''
        anim_path = ANIM_GUARD if 'guard' in mesh_name.lower() or not mesh_name else ANIM_MANNY
        anim = C.load(anim_path)
        if anim is None:
            ctx.report.error('animation %s not found (script 02 creates it)' % anim_path)
            return
        try:
            mesh_skel = mesh.get_editor_property('skeleton') if mesh else None
            anim_skel = anim.get_editor_property('skeleton')
            ctx.report.info('skeletons: mesh %s=%s anim=%s' % (
                mesh_name, mesh_skel.get_path_name() if mesh_skel else None,
                anim_skel.get_path_name() if anim_skel else None))
            if mesh_skel and anim_skel and mesh_skel.get_path_name() != anim_skel.get_path_name():
                ctx.report.error('%s skeleton does not match %s; Sequencer would not play it' % (anim_path, mesh_name))
        except Exception as exc:
            ctx.todo('could not compare skeletons of %s and %s: %s' % (mesh_name, anim_path, exc))
        length = float(anim.get_play_length())   # AnimationAsset.h:1060-1061 (BlueprintPure)
        if length <= 0.0:
            length = float(ctx.data.get('anim', {}).get('duration_s', CTX['anim_duration_s']))
            ctx.todo('get_play_length returned 0 for %s; using %.4f s' % (anim_path, length))
        off = ctx.anim_offset
        play_end = min(off + length, DURATION_S)
        plan = [
            ('hold_first', 0.0, off, 0.0, 0.0),
            ('play', off, play_end, 0.0, 1.0),
            ('hold_last', play_end, DURATION_S, max(0.0, length - HOLD_LAST_EPSILON_S), 0.0),
        ]
        ctx.anim_info = {'anim': anim_path, 'component': body.get_name(), 'mesh': mesh_name,
                         'length_s': length, 'start_s': off, 'end_s': play_end,
                         'sections': [list(p) for p in plan]}
        ctx.report.info('ANIM_PLAN: %s' % ctx.anim_info)

        # Bind the body component directly: the skeletal animation system accepts a
        # SkeletalMeshComponent binding (MovieSceneSkeletalAnimationSystem.cpp:1116-1139), which
        # avoids playing on SK_Guard_Head when it is the actor's first skeletal component.
        b = bind(ctx, body, GUARD_LABEL + '.' + body.get_name())
        track, created = get_or_add_track(ctx, b, unreal.MovieSceneSkeletalAnimationTrack, key)
        secs = list(track.get_sections())
        if created or not secs:
            for name, s0, s1, aoff, rate in plan:
                if s1 - s0 <= 1e-4:
                    continue
                sec = track.add_section()
                apply_anim_section(ctx, sec, anim_path, s0, s1, aoff, rate)
            ctx.dirty = True
            ctx.report.modified(tpath(key), '%d sections' % len(track.get_sections()))
        elif FORCE and len(secs) == len([p for p in plan if p[2] - p[1] > 1e-4]):
            secs.sort(key=lambda s: s.get_start_frame_seconds())
            for sec, (name, s0, s1, aoff, rate) in zip(secs, [p for p in plan if p[2] - p[1] > 1e-4]):
                apply_anim_section(ctx, sec, anim_path, s0, s1, aoff, rate)
            ctx.dirty = True
            ctx.report.modified(tpath(key), 'FORCE re-applied %d sections' % len(secs))
        else:
            info = []
            for s in sorted(secs, key=lambda s: s.get_start_frame_seconds()):
                p = s.get_editor_property('params')
                a = p.get_editor_property('animation')
                info.append((round(s.get_start_frame_seconds(), 4), round(s.get_end_frame_seconds(), 4),
                             a.get_path_name() if a else None,
                             unreal.MovieSceneTimeWarpExtensions.get_section_play_rate(s)))
            want = len([p for p in plan if p[2] - p[1] > 1e-4])
            if len(secs) != want or any(i[2] is None or not i[2].startswith(anim_path) for i in info):
                ctx.todo('%s sections differ from plan: %s (set REBUILD=True)' % (key, info))
            else:
                ctx.report.skipped(tpath(key), 'verified sections %s' % info)
            ctx.verified_tracks.append(key)
    except Exception as exc:
        ctx.report.error('guard skeletal animation track failed', exc)


# --- Slash arcs -----------------------------------------------------------------------------------
def scalar_key(ctx, section, name, t, value, mode='LINEAR'):
    info = unreal.MaterialParameterInfo()   # MaterialParameters.h:33-55 (default = global parameter)
    info.set_editor_property('name', name)
    # Member UFUNCTION; InTime is in TICK resolution frames
    # (MovieSceneComponentMaterialParameterSection.h:108-114, .cpp:200-232).
    section.add_scalar_parameter_key(info, ctx.tick(t), float(value), '', '', interp(mode))


def material_track(ctx, comp, key):
    """Component material track on slot 0. Must be on the COMPONENT binding: the system casts the
    bound object to UPrimitiveComponent (G5 digest, MovieSceneComponentMaterialSystem.cpp:54)."""
    b = bind(ctx, comp, key.split('/')[0] + '.' + comp.get_name())
    track, created = get_or_add_track(ctx, b, unreal.MovieSceneComponentMaterialTrack, key)
    if created:
        mi = unreal.ComponentMaterialInfo()   # MovieSceneMaterialTrack.h:36-48
        mi.set_editor_property('material_slot_index', 0)
        mi.set_editor_property('material_type', unreal.ComponentMaterialType.INDEXED_MATERIAL)
        track.set_material_info(mi)   # MovieSceneMaterialTrackExtensions.h:50-51
    sec, sec_created = get_or_add_section(ctx, track, key)
    if sec_created:
        sec.set_range_seconds(0.0, DURATION_S)
    return track, sec, (created or sec_created)


def step_arcs(ctx):
    """Static IceSlash_Arc_01..05 are superseded by NS_IceSlash_Skill (Blade_01..05);
    keep them hidden throughout the sequence and omit their legacy material tracks (#134)."""
    for label in ARC_LABELS:
        actor = ctx.actor(label)
        if actor is None:
            continue
        vkey = label + '/Visibility'
        try:
            b = bind(ctx, actor, label)
            track, created = get_or_add_track(ctx, b, unreal.MovieSceneVisibilityTrack, vkey)
            if created:
                track.set_property_name_and_path('bHidden', 'bHidden')
            sec, sec_created = get_or_add_section(ctx, track, vkey)
            if created or sec_created or FORCE:
                sec.set_range_seconds(0.0, DURATION_S)
                ch = sec.get_all_channels()[0]
                ch.set_default(False)
                ch.add_key(ctx.tick(0.0), False, 0.0, unreal.MovieSceneTimeUnit.TICK_RESOLUTION)
                ctx.dirty = True
                ctx.report.modified(tpath(vkey), 'hidden 0-%.1f s (superseded by NS_IceSlash_Skill)' % DURATION_S)
            else:
                verify_counts(ctx, vkey, sec, {channel_name(sec.get_all_channels()[0]): 1})
        except Exception as exc:
            ctx.report.error('%s visibility track failed' % label, exc)


# --- Niagara --------------------------------------------------------------------------------------
def apply_niagara_section(sec, start, end, kind):
    sec.set_range_seconds(start, end)
    # UFUNCTION setters on UMovieSceneNiagaraSystemSpawnSection
    # (Niagara/Public/MovieScene/MovieSceneNiagaraSystemSpawnSection.h:8-71).
    sec.set_section_start_behavior(unreal.NiagaraSystemSpawnSectionStartBehavior.ACTIVATE)
    if kind == 'loop':
        sec.set_section_evaluate_behavior(unreal.NiagaraSystemSpawnSectionEvaluateBehavior.ACTIVATE_IF_INACTIVE)
    else:
        # A one-shot burst must not be re-activated after it completes.
        sec.set_section_evaluate_behavior(unreal.NiagaraSystemSpawnSectionEvaluateBehavior.NONE)
    # SetSystemInactive stops spawning and lets live particles finish (header comment :31-36).
    sec.set_section_end_behavior(unreal.NiagaraSystemSpawnSectionEndBehavior.SET_SYSTEM_INACTIVE)
    sec.set_age_update_mode(getattr(unreal.NiagaraAgeUpdateMode, NIAGARA_AGE_MODE))


def step_niagara(ctx):
    for label, ev0, d0, ev1, kind in NIAGARA_WINDOWS:
        actor = ctx.actor(label)
        if actor is None:
            ctx.report.error('Niagara actor %s not found (script 06 creates it)' % label)
            continue
        key = label + '/NiagaraLifeCycle'
        try:
            start = (ctx.t(ev0) if isinstance(ev0, str) else float(ev0)) + d0
            if ev1 is None:
                end = start + SPARKLE_WINDOW_S
            else:
                end = ctx.t(ev1) if isinstance(ev1, str) else float(ev1)
            end = min(end, DURATION_S)
            nc = getattr(actor, 'niagara_component', None) or first_component(actor, unreal.NiagaraComponent)
            if nc is None:
                ctx.report.error('%s has no NiagaraComponent' % label)
                continue
            try:
                if nc.get_editor_property('auto_activate'):
                    ctx.report.info('%s auto_activate is True; the Activate start behaviour deactivates it '
                                    'before the section while the sequence evaluates' % label)
            except Exception:
                pass
            # The track template CastChecked<UNiagaraComponent>s the bound object
            # (MovieSceneNiagaraSystemTrackTemplate.cpp:45), so bind the component.
            b = bind(ctx, nc, label + '.' + nc.get_name())
            track, created = get_or_add_track(ctx, b, unreal.MovieSceneNiagaraSystemTrack, key)
            sec, sec_created = get_or_add_section(ctx, track, key)   # -> spawn section (MovieSceneNiagaraSystemTrack.cpp:19-22)
            if created or sec_created or FORCE:
                apply_niagara_section(sec, start, end, kind)
                ctx.dirty = True
                ctx.report.modified(tpath(key), '%s %.4f-%.4f s' % (kind, start, end))
            else:
                s0, s1 = sec.get_start_frame_seconds(), sec.get_end_frame_seconds()
                if abs(s0 - start) > 0.02 or abs(s1 - end) > 0.02:
                    ctx.todo('%s range %.3f-%.3f differs from plan %.3f-%.3f (FORCE=True to update)' % (key, s0, s1, start, end))
                else:
                    ctx.report.skipped(tpath(key), 'verified range %.3f-%.3f' % (s0, s1))
                ctx.verified_tracks.append(key)
        except Exception as exc:
            ctx.report.error('%s Niagara track failed' % label, exc)


# --- Crystals -------------------------------------------------------------------------------------
def short_part(name):
    return name[len('SM_IceCluster_'):] if name.startswith('SM_IceCluster_') else name


def crystal_schedule(ctx):
    """Returns {short part name: (role, growth start, growth end)} in data order."""
    parts = [p for p in (ctx.data.get('cluster_parts') or []) if int(p.get('faces', 1)) > 0]
    reveal, hold = ctx.t('FX_CrystalReveal'), ctx.t('FX_CrystalHold')
    grow = hold - reveal
    sched = {}
    prism_i = 0
    for p in parts:
        s = short_part(str(p.get('name', '')))
        role = str(p.get('material_role', 'prism'))
        if s == 'Core':
            off = 0.0
        elif role == 'prism':
            off = CRYSTAL_PRISM_STAGGER[min(prism_i, len(CRYSTAL_PRISM_STAGGER) - 1)]
            prism_i += 1
        elif role == 'boulder':
            off = CRYSTAL_BOULDER_DELAY
        elif role == 'snowbase':
            off = -CRYSTAL_SNOWBASE_LEAD
        else:
            off = 0.0
        sched[s] = (role, reveal + off, reveal + off + grow)
    return sched


def step_crystals(ctx):
    sched = crystal_schedule(ctx)
    labels = sorted(l for l in ctx.actors if l.startswith(CRYSTAL_PREFIX))
    if not labels:
        ctx.report.error('no %s* actors found (script 06 creates them)' % CRYSTAL_PREFIX)
        return
    hold, end_t = ctx.t('FX_CrystalHold'), ctx.t('FX_End')
    for label in labels:
        key = label + '/Material'
        try:
            part = short_part(label[len(CRYSTAL_PREFIX):])
            if part in sched:
                role, g0, g1 = sched[part]
            else:
                role = 'snowbase' if 'base' in part.lower() else ('boulder' if 'boulder' in part.lower() else 'prism')
                g0, g1 = ctx.t('FX_CrystalReveal'), hold
                ctx.todo('%s not in data cluster_parts; using role %s and the unstaggered growth window' % (label, role))
            actor = ctx.actors[label]
            comp = getattr(actor, 'static_mesh_component', None) or first_component(actor, unreal.StaticMeshComponent)
            if comp is None:
                ctx.report.error('%s has no StaticMeshComponent' % label)
                continue
            track, sec, fresh = material_track(ctx, comp, key)
            if fresh or FORCE:
                scalar_key(ctx, sec, 'CrystalGrowth', g0, 0.0, 'SMART_AUTO')
                scalar_key(ctx, sec, 'CrystalGrowth', g1, 1.0, 'SMART_AUTO')
                for dt, v in CRYSTAL_GLOW_KEYS:
                    scalar_key(ctx, sec, 'CrystalGlow', end_t if dt is None else hold + dt, v, 'SMART_AUTO')
                for t, v in CRYSTAL_FADE:
                    scalar_key(ctx, sec, 'CrystalOpacity', t, v, 'SMART_AUTO')
                ctx.dirty = True
                ctx.report.modified(tpath(key), 'role=%s growth %.2f-%.2f s, glow, fade' % (role, g0, g1))
            else:
                verify_counts(ctx, key, sec, {'CrystalGrowth': 2, 'CrystalGlow': len(CRYSTAL_GLOW_KEYS),
                                              'CrystalOpacity': len(CRYSTAL_FADE)})
        except Exception as exc:
            ctx.report.error('%s crystal material track failed' % label, exc)


# --- Camera ---------------------------------------------------------------------------------------
def _add(a, b, s=1.0):
    return (a[0] + b[0] * s, a[1] + b[1] * s, a[2] + b[2] * s)


def camera_frame(ctx):
    """Forward (mesh +Y), side (mesh +X) and focus points in world space."""
    guard = ctx.actor(GUARD_LABEL)
    origin, yaw = (0.0, 0.0, 0.0), 0.0
    if guard is not None:
        body, _ = pick_body_component(ctx, guard)
        src = body if body is not None else guard.root_component
        loc = src.get_world_location()   # SceneComponent.h:661-662 (ScriptName GetWorldLocation)
        rot = src.get_world_rotation()   # :665-666
        origin, yaw = (loc.x, loc.y, loc.z), rot.yaw
    r = math.radians(yaw)
    fwd = (-math.sin(r), math.cos(r), 0.0)   # component +Y rotated by yaw
    side = (math.cos(r), math.sin(r), 0.0)   # component +X rotated by yaw
    lunge = _add(_add(origin, fwd, LUNGE_FOCUS_FWD_CM), (0, 0, 1), LUNGE_FOCUS_UP_CM)
    root = ctx.actor(CRYSTAL_ROOT_LABEL)
    if root is not None:
        c = root.get_actor_location()
        crystal_base = (c.x, c.y, c.z)
    else:
        crystal_base = _add(origin, fwd, CRYSTAL_FALLBACK_FWD_CM)
        ctx.todo('%s not found; camera crystal focus uses guard + %.0f cm forward' % (CRYSTAL_ROOT_LABEL, CRYSTAL_FALLBACK_FWD_CM))
    crystal = _add(crystal_base, (0, 0, 1), CRYSTAL_FOCUS_UP_CM)
    return {'origin': origin, 'yaw': yaw, 'fwd': fwd, 'side': side,
            'focus': {'lunge': lunge, 'crystal': crystal}}


def camera_keys(ctx, frame, focal):
    scale = (focal / 35.0) if focal and focal > 0 else 1.0
    out, prev_yaw = [], None
    for t, focus, dfac, az, el, roll, zj, mode in CAM_KEYS:
        tgt = frame['focus'][focus]
        a, e = math.radians(az), math.radians(el)
        horiz = _add(tuple(x * math.cos(a) for x in frame['fwd']), frame['side'], CAM_SIDE * math.sin(a))
        dirv = (horiz[0] * math.cos(e), horiz[1] * math.cos(e), math.sin(e))
        dist = CAM_BASE_DIST_CM * dfac * scale
        pos = _add(tgt, dirv, dist)
        pos = (pos[0], pos[1], pos[2] + zj)
        d = (tgt[0] - pos[0], tgt[1] - pos[1], tgt[2] - pos[2])
        yaw = math.degrees(math.atan2(d[1], d[0]))
        if prev_yaw is not None:   # unwrap so the eased yaw curve never spins 360 degrees
            while yaw - prev_yaw > 180.0:
                yaw -= 360.0
            while yaw - prev_yaw < -180.0:
                yaw += 360.0
        prev_yaw = yaw
        pitch = math.degrees(math.atan2(d[2], math.hypot(d[0], d[1])))
        out.append((t, pos, (roll, pitch, yaw), mode))
    return out


def step_camera(ctx):
    cam = ctx.actor(CAMERA_LABEL)
    if cam is None:
        return
    try:
        b_cam = bind(ctx, cam, CAMERA_LABEL)
    except Exception as exc:
        ctx.report.error('camera binding failed', exc)
        return

    # Camera cut (master track). seq.add_track routes camera cut tracks to AddCameraCutTrack,
    # which reuses the existing one (MovieSceneSequenceExtensions.cpp:282-312).
    key = 'CameraCut'
    try:
        cuts = list(ctx.seq.find_tracks_by_exact_type(unreal.MovieSceneCameraCutTrack))   # :96
        created = not cuts
        cut = cuts[0] if cuts else ctx.seq.add_track(unreal.MovieSceneCameraCutTrack)
        if created:
            ctx.created_tracks.append(key)
            ctx.report.created(tpath(key))
        sec, sec_created = get_or_add_section(ctx, cut, key)
        if created or sec_created or FORCE:
            sec.set_range_seconds(0.0, DURATION_S)
            # PythonCallable static (MovieSceneSectionExtensions.h:150-151, .cpp:80-105)
            unreal.MovieSceneSectionExtensions.set_camera_cut_binding(sec, b_cam)
            ctx.dirty = True
            ctx.report.modified(tpath(key), 'bound to %s 0-%.1f s' % (CAMERA_LABEL, DURATION_S))
        else:
            ctx.report.skipped(tpath(key), 'exists, %d section(s), range %.3f-%.3f, camera binding %s' % (
                len(cut.get_sections()), sec.get_start_frame_seconds(), sec.get_end_frame_seconds(),
                sec.get_camera_binding_id()))   # MovieSceneCameraCutSection.h:41-46
            ctx.verified_tracks.append(key)
    except Exception as exc:
        ctx.report.error('camera cut track failed', exc)

    key = CAMERA_LABEL + '/Transform'
    try:
        focal = 35.0
        try:
            cc = cam.get_cine_camera_component()   # CineCameraActor.h:89-90
            focal = float(cc.get_editor_property('current_focal_length'))   # CineCameraComponent.h:66
        except Exception as exc:
            ctx.todo('could not read the camera focal length (%s); framing assumes 35 mm' % exc)
        try:
            parent = cam.get_attach_parent_actor()   # Actor.h:3548
            if parent is not None:
                ctx.todo('%s is attached to %s; transform keys are relative to it but were computed in world space'
                         % (CAMERA_LABEL, parent.get_actor_label()))
        except Exception:
            pass
        frame = camera_frame(ctx)
        keys = camera_keys(ctx, frame, focal)
        ctx.camera_info = {'focal_mm': focal, 'guard_origin': frame['origin'], 'guard_yaw': frame['yaw'],
                           'focus': frame['focus'],
                           'keys': [{'t': t, 'loc': [round(v, 1) for v in p], 'rot_rpy': [round(v, 2) for v in r], 'interp': m}
                                    for t, p, r, m in keys]}
        track, created = get_or_add_track(ctx, b_cam, unreal.MovieScene3DTransformTrack, key)
        sec, sec_created = get_or_add_section(ctx, track, key)
        if created or sec_created or FORCE:
            sec.set_range_seconds(0.0, DURATION_S)
            # Channel names: MovieScene3DTransformSection.cpp:83-177 (Location.X/Y/Z,
            # Rotation.X=roll, Rotation.Y=pitch, Rotation.Z=yaw, Scale.X/Y/Z).
            chans = {n: sec.get_channel(n) for n in ('Location.X', 'Location.Y', 'Location.Z',
                                                    'Rotation.X', 'Rotation.Y', 'Rotation.Z')}
            try:
                s = cam.get_actor_scale3d()
                for n, v in (('Scale.X', s.x), ('Scale.Y', s.y), ('Scale.Z', s.z)):
                    sec.get_channel(n).set_default(float(v))   # MovieSceneScriptingDouble.h:475
            except Exception as exc:
                ctx.todo('could not set camera scale channel defaults: %s' % exc)
            tu = unreal.MovieSceneTimeUnit.TICK_RESOLUTION
            for t, p, r, mode in keys:
                fn = ctx.tick(t)
                im = interp(mode)
                # add_key(time, value, sub_frame, time_unit, interpolation) MovieSceneScriptingDouble.h:291
                for n, v in (('Location.X', p[0]), ('Location.Y', p[1]), ('Location.Z', p[2]),
                             ('Rotation.X', r[0]), ('Rotation.Y', r[1]), ('Rotation.Z', r[2])):
                    chans[n].add_key(fn, float(v), 0.0, tu, im)
            ctx.dirty = True
            ctx.report.modified(tpath(key), '%d keys per channel (focal %.1f mm)' % (len(keys), focal))
        else:
            verify_counts(ctx, key, sec, {n: len(CAM_KEYS) for n in ('Location.X', 'Location.Y', 'Location.Z',
                                                                     'Rotation.X', 'Rotation.Y', 'Rotation.Z')})
        for k in ctx.camera_info['keys']:
            ctx.report.info('CAM_KEY t=%.2f loc=%s rot(r,p,y)=%s %s' % (k['t'], k['loc'], k['rot_rpy'], k['interp']))
    except Exception as exc:
        ctx.report.error('camera transform track failed', exc)


# --- Sequencer preview captures -------------------------------------------------------------------
async def _await_if_needed(value):
    """SequencerEditorSubsystem async calls: an AsyncFunctionResultVoid or a coroutine. Poll its
    is_complete flag (the toolset's own ticker settles it); asyncio.sleep here is the runner's
    non-blocking sleep."""
    if asyncio.iscoroutine(value) or asyncio.isfuture(value):
        return await value
    if hasattr(value, 'is_complete'):
        done = value.is_complete
        limit = 600
        while not (done() if callable(done) else bool(done)) and limit > 0:
            await asyncio.sleep(0.05)
            limit -= 1
        err = getattr(value, 'error', '') if hasattr(value, 'error') else ''
        if err:
            raise RuntimeError(str(err))
    return value


def _channel_pair(section):
    """[(tick_frame, value_bool)] of the first bool channel of a section."""
    out = []
    try:
        for ch in section.get_all_channels():
            for k in ch.get_keys():
                out.append((int(k.get_time().frame_number.value), bool(k.get_value())))
            if out:
                return out
    except Exception:
        pass
    return out


def _bound_hidden(ctx, label):
    """The 'hidden' flag of the actor the sequence binds as `label` (as the evaluator set it)."""
    try:
        for b in ctx.seq.get_bindings():
            if b.get_name() != label:
                continue
            for obj in ctx.seq.locate_bound_objects(b, ctx.world):
                return bool(obj.get_editor_property('hidden'))
    except Exception:
        pass
    return None


def _rounded(pose):
    return tuple([round(v, 1) for v in pose[0]] + [round(pose[1], 1), round(pose[2], 1)])


def _camera_pose(ctx):
    cam = ctx.actor(CAMERA_LABEL)
    if cam is None:
        return ((0.0, 0.0, 0.0), 0.0, 0.0)
    loc, rot = cam.get_actor_location(), cam.get_actor_rotation()
    return ((loc.x, loc.y, loc.z), rot.yaw, rot.pitch)


def _evaluation_evidence(ctx, seconds, tilt_frames=1):
    """What the pose should look like at `seconds`: each arc's expected visibility from its track
    keys vs the bound actors' actual 'hidden' flags. Logged with each shot as evidence."""
    evidence = {}
    for label in ARC_LABELS:
        track = None
        for b in ctx.seq.get_bindings():
            if b.get_name() == label:
                for t in b.get_tracks():
                    if isinstance(t, unreal.MovieSceneVisibilityTrack):
                        track = t
        secs = list(track.get_sections()) if track is not None else []
        if not secs:
            continue
        want = 'visible'
        for frame, visible in _channel_pair(secs[0]):
            if frame <= seconds * ctx.display_fps + tilt_frames:
                want = 'visible' if visible else 'hidden'
        evidence[label] = (want, _bound_hidden(ctx, label))
    return evidence


def _draw_viewport(ctx, seconds, path):
    """One draw of the level viewport (UI-free) on the sequence camera, plus its evidence."""
    info = unreal.ViewportService.get_viewport_info()
    res = unreal.ViewportService.capture_with_view(info.location, info.rotation, CAPTURE_W, CAPTURE_H, path)
    if not res.success:
        raise RuntimeError('capture_with_view failed: %s' % res.error_message)
    evidence = _evaluation_evidence(ctx, seconds)
    ctx.report.info('CAPTURE: %.2f s -> %s (%d bytes); sequence camera %s; visibility want/actual %s' % (
        seconds, res.output_path, res.file_size_bytes, _rounded(_camera_pose(ctx)), evidence))
    ctx.capture_evidence['%.1f' % seconds] = {'camera': _rounded(_camera_pose(ctx)), 'visibility': evidence}
    return res.output_path


async def _capture_shot(ctx, seconds, path):
    """Seek, then (unlock + draw + relock) until the sequence camera stops moving between draws."""
    playback = ctx.seq.get_playback_start_seconds()
    frame = int(round((seconds - playback) * ctx.display_fps))
    lse, lib = ctx.lse_subsystem, unreal.LevelSequenceEditorBlueprintLibrary
    # set_playhead_frame_async takes ROOT-SEQUENCE display-rate frames and waits for the pose
    # (LevelSequenceEditorSubsystem.h SetPlayheadFrameAsync).
    await _await_if_needed(lse.set_playhead_frame_async(frame))
    await asyncio.sleep(CAPTURE_SETTLE_S)
    prev = None
    stable = False
    for attempt in range(CAPTURE_ATTEMPTS):
        pose = _rounded(_camera_pose(ctx))
        if prev is not None and pose == prev:
            stable = True
            break
        prev = pose
        # The SYNCHRONOUS lock setter: the ..._async twin forfeits the camera cut (Sequencer restores
        # its own saved view). With the lock off capture_with_view accepts the call; the pose it is
        # given is the viewport's current one, and on the lock-ON frames that is the camera cut's.
        lib.set_lock_camera_cut_to_viewport(False)
        await asyncio.sleep(CAPTURE_SETTLE_S)
        try:
            _draw_viewport(ctx, seconds, path)
        finally:
            lib.set_lock_camera_cut_to_viewport(True)
        await asyncio.sleep(CAPTURE_SETTLE_S)
    if not stable:
        ctx.todo('capture %.2f s: sequence camera did not settle in %d draws (last %s)' % (
            seconds, CAPTURE_ATTEMPTS, prev))
    return path


async def step_capture(ctx):
    """Draw the sequencer-camera preview at each CAPTURE_TIMES_S into Saved/VFX/shots.

    Runs INSIDE the calling event loop: time.sleep on the game thread freezes the editor
    (AGENTS.md section 7), so only the editor's async helpers and asyncio.sleep are used.
    """
    if not CAPTURE_SHOTS:
        ctx.report.skipped('captures', 'CAPTURE_SHOTS=False')
        return
    lsel = unreal.LevelSequenceEditorBlueprintLibrary
    ctx.lse_subsystem = unreal.get_editor_subsystem(unreal.LevelSequenceEditorSubsystem)
    current = lsel.get_current_level_sequence()
    if current is None:
        ctx.report.error('no sequence is open in Sequencer; captures need it opened first '
                         '(unreal.LevelSequenceEditorSubsystem.open_level_sequence_async)')
        return
    if current.get_path_name() != ctx.seq.get_path_name():
        ctx.report.error('Sequencer shows %s, not %s' % (current.get_path_name(), ctx.seq.get_path_name()))
        return
    os.makedirs(CAPTURE_DIR, exist_ok=True)
    cvar = unreal.SystemLibrary
    was_locked = lsel.is_camera_cut_locked_to_viewport()
    try:
        custom_depth = int(cvar.get_console_variable_int_value(CUSTOM_DEPTH_CVAR))
    except Exception:
        custom_depth = None
    ctx.report.info('capture setup: lock=%s %s=%s fps=%d' % (was_locked, CUSTOM_DEPTH_CVAR, custom_depth,
                                                             ctx.display_fps))
    if SAVE_BEFORE_CAPTURE:
        try:
            C.save_all(ctx.report, extra_packages=[SEQ_PATH])
        except Exception as exc:
            ctx.report.error('save before captures failed', exc)
    try:
        if custom_depth:
            cvar.execute_console_command(None, '%s 0' % CUSTOM_DEPTH_CVAR)   # restored below
        shots = {}
        for seconds in CAPTURE_TIMES_S:
            path = os.path.join(CAPTURE_DIR, CAPTURE_FILES[seconds].replace('-', 'p', 1))
            try:
                shots['%.1f' % seconds] = await _capture_shot(ctx, seconds, path)
                ctx.report.created(path)
            except Exception as exc:
                ctx.report.error('capture %.2f s' % seconds, exc)
        ctx.camera_info['captures'] = shots
    finally:
        if custom_depth:
            cvar.execute_console_command(None, '%s %d' % (CUSTOM_DEPTH_CVAR, custom_depth))
        try:
            await _await_if_needed(ctx.lse_subsystem.set_lock_camera_cut_to_viewport_async(was_locked))
        except Exception as exc:
            ctx.report.error('could not restore camera-cut viewport lock', exc)
        ctx.report.info('captures done; viewport lock and %s restored' % CUSTOM_DEPTH_CVAR)


# --- Marks ----------------------------------------------------------------------------------------
def step_marks(ctx):
    for label in MARK_EVENTS:
        try:
            if label not in ctx.timeline:
                continue
            if ctx.seq.find_marked_frame_by_label(label) >= 0:   # MovieSceneSequenceExtensions.h:773
                continue
            fn = ctx.tick(ctx.timeline[label])
            # StartFrame == EndFrame -> single-frame mark (MovieSceneSequenceExtensions.h:693-712)
            ctx.seq.add_marked_frame_range_to_sequence(fn, fn, unreal.MovieSceneTimeUnit.TICK_RESOLUTION, label)
            ctx.dirty = True
            ctx.report.created(tpath('Mark', label) + ' @ %.4f s' % ctx.timeline[label])
        except Exception as exc:
            ctx.report.error('mark %s failed' % label, exc)


# --- Save, summary, manifest ----------------------------------------------------------------------
def step_save(ctx):
    try:
        ok = unreal.EditorAssetLibrary.save_loaded_asset(ctx.seq, False)   # EditorAssetLibrary.h:265
        if ok:
            ctx.report.info('SAVED: %s' % SEQ_PATH)
        else:
            ctx.report.error('save_loaded_asset(%s) returned False' % SEQ_PATH)
    except Exception as exc:
        ctx.report.error('saving %s failed' % SEQ_PATH, exc)
    try:
        # Saves only packages this run dirtied / under C.ROOT (ice_slash_common.py save_all docstring).
        C.save_all(ctx.report, extra_packages=[SEQ_PATH])
    except Exception as exc:
        ctx.report.error('C.save_all failed', exc)
    try:
        print('DIRTY_AFTER: %s' % list(unreal.PythonTools.get_dirty_packages(True)))
    except Exception:
        pass


def describe_track(t):
    secs = []
    for s in t.get_sections():
        try:
            rng = '%.3f-%.3f' % (s.get_start_frame_seconds(), s.get_end_frame_seconds())
        except Exception:
            rng = 'unbounded'
        secs.append({'class': s.get_class().get_name(), 'range_s': rng, 'keys': section_key_counts(s)})
    return {'class': t.get_class().get_name(), 'sections': secs}


def step_summary(ctx):
    summary = {'bindings': [], 'master_tracks': []}
    try:
        for b in ctx.seq.get_bindings():
            try:
                objs = list(ctx.seq.locate_bound_objects(b, ctx.world))
            except Exception:
                objs = []
            entry = {'name': b.get_name(), 'resolved': [o.get_name() for o in objs],
                     'tracks': [describe_track(t) for t in b.get_tracks()]}
            summary['bindings'].append(entry)
            print('SEQ_BINDING: %s resolved=%s tracks=%d' % (entry['name'], entry['resolved'], len(entry['tracks'])))
            for tr in entry['tracks']:
                for s in tr['sections']:
                    print('SEQ_TRACK:   %s / %s %s keys=%s' % (tr['class'], s['class'], s['range_s'], s['keys']))
            if not objs:
                ctx.todo('binding %s does not resolve in %s (REBUILD=True removes stale IceSlash_ bindings)'
                         % (entry['name'], C.MAP_PATH))
        for t in ctx.seq.get_tracks():
            d = describe_track(t)
            summary['master_tracks'].append(d)
            for s in d['sections']:
                print('SEQ_MASTER:  %s / %s %s keys=%s' % (d['class'], s['class'], s['range_s'], s['keys']))
        marks = []
        for label in MARK_EVENTS:
            if ctx.seq.find_marked_frame_by_label(label) >= 0:
                marks.append(label)
        summary['marks'] = marks
        print('SEQ_MARKS: %s' % marks)
    except Exception as exc:
        ctx.report.error('summary failed', exc)
    return summary


def step_manifest(ctx, summary):
    try:
        C.update_manifest('sequence', {
            'path': SEQ_PATH,
            'map': C.MAP_PATH,
            'duration_s': DURATION_S,
            'display_fps': DISPLAY_FPS,
            'ticks_per_s': ctx.ticks_per_s,
            'rebuild': REBUILD,
            'force': FORCE,
            'created': ctx.seq_created,
            'timeline': ctx.timeline,
            'arc_reveal': ctx.arc_reveal,
            'anim': ctx.anim_info,
            'camera': ctx.camera_info,
            'captures': ctx.camera_info.get('captures', {}),
            'capture_evidence': ctx.capture_evidence,
            'created_tracks': ctx.created_tracks,
            'verified_tracks': ctx.verified_tracks,
            'bindings': summary.get('bindings', []),
            'master_tracks': summary.get('master_tracks', []),
            'marks': summary.get('marks', []),
            'todos': ctx.todos,
        })
        ctx.report.info('manifest section "sequence" written to %s' % C.MANIFEST_PATH)
    except Exception as exc:
        ctx.report.error('update_manifest(sequence) failed', exc)


async def main_async(steps=(step_guard, step_arcs, step_niagara, step_crystals, step_camera, step_capture,
                          step_marks)):
    """The whole run for callers inside an event loop (execute_python + runpy.run_path): the
    capture step has to await the editor's async Sequencer helpers, so it cannot run in main()."""
    report = C.Report(SCRIPT_NAME)
    ctx = Ctx(report)
    try:
        step_load_data(ctx)
        if step_level(ctx):
            step_collect_actors(ctx)
            if step_sequence_asset(ctx):
                step_rebuild_clear(ctx)
                for step in steps:
                    try:
                        if asyncio.iscoroutinefunction(step):
                            await step(ctx)
                        else:
                            step(ctx)
                    except Exception as exc:
                        report.error('%s failed' % step.__name__, exc)
                step_save(ctx)
                summary = step_summary(ctx)
                step_manifest(ctx, summary)
    except Exception as exc:
        report.error('unexpected failure', exc)
    return report.finish()


def main():
    """Run every step. With an event loop already running (execute_python) this returns the
    main_async() coroutine for the caller to await; otherwise (plain runpy) it runs main_async to
    completion here, exactly like the older synchronous main() did."""
    steps = (step_guard, step_arcs, step_niagara, step_crystals, step_camera, step_capture, step_marks)
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        coro = main_async(steps)
        try:
            coro.send(None)
        except StopIteration as stop:
            return stop.value
        coro.close()
        raise RuntimeError('%s: a step awaited without a running event loop; run it through '
                           'execute_python' % SCRIPT_NAME)
    return main_async(steps)


if __name__ == '__main__':
    # This module is built by runpy.run_path from inside execute_python (the engine runner and the
    # VibeUE overlay alike), which ends every script with an 'await' expression whose value
    # runpy.run_path returns. So building it hands back MAIN_COROUTINE, the coroutine main() created
    # via main_async(), and ending the script with that expression awaits it on the caller's loop.
    MAIN_COROUTINE = main()
