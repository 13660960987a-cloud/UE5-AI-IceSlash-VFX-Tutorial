"""ice_slash_06_showcase.py - build the Ice Slash v2 preview level and capture review shots.

Purpose
    Builds (idempotently) the NEW preview level C.MAP_PATH (/Game/VFX/IceSlash/Maps/L_IceSlash_v2)
    and populates it with everything the earlier steps produced, so the slash arcs, the ice
    cluster and the Niagara anchors can be reviewed on the visible Guard in one place. It never
    touches any other map: if the open level has unsaved changes the script stops before the
    level switch and asks for them to be saved or discarded by the owner.

Run order (each script is run in the editor with
    import runpy; runpy.run_path('<script path>', run_name='__main__')):
    01 import, 02 anim + sockets, 03 slash material, 04 crystal material, 05 niagara,
    06 showcase level (THIS SCRIPT), 07 sequence.

What it creates / updates (actors are updated in place when the label already exists; nothing
is ever destroyed):
    Level   C.MAP_PATH (created with LevelEditorSubsystem.new_level when missing).
    Env     IceSlash_Floor (40 x 40 m plane), IceSlash_DirLight, IceSlash_SkyLight, IceSlash_Fog,
            IceSlash_PPV (unbound; bloom 0.8; fixed exposure min = max EV100 1.0; vignette 0.3).
    Guard   IceSlash_Guard (SkeletalMeshActor, SK_Guard, origin, facing +X, single-node anim
            C.ANIM_DIR/AS_Guard_IceSlash_Combo paused at slash-1 + 0.25 s) and IceSlash_Guard_Head
            (SK_Guard_Head attached to the body, following it through a leader pose).
    Slash   IceSlash_SlashRoot (empty actor attached to the Guard skeletal mesh component with the
            data JSON mirror_correction parent_scale (1,-1,1)) and IceSlash_Arc_01..05
            (SM_SlashArc_0N + MI_SlashArc_0N at the data JSON pivot_cm / rotation_deg / scale).
    Ice     IceSlash_CrystalRoot (ground anchor = cluster_center_cm, uniform scale cluster_scale)
            and IceSlash_Crystal_<PartName> (one per cluster part with faces > 0).
    Niagara IceSlash_NS_HandEnergy (FX_Hand_R), IceSlash_NS_SlashSparkles_01..05 (arc heads),
            IceSlash_NS_GroundTrail (FX_SlashOrigin projected to the floor), IceSlash_NS_Burst
            (FX_IceBurst), IceSlash_NS_CrystalSparkle (crystal root); auto-activate off.
    Camera  IceSlash_Camera (CineCameraActor, three-quarter front, ~650 cm, 180 cm high, looking
            at the chest); 'side', 'high' and 'crystals' views are stored in the manifest.
    Shots   C.SHOTS_DIR/ice_slash_preview_front.png, _side.png, _high.png (arcs visible, crystals
            hidden) and ice_slash_preview_crystals.png (arcs hidden, CrystalGrowth 1).
            The preview material values live on TRANSIENT dynamic material instances that are
            removed again after the captures, so the saved level references only the MI assets.
    Manifest section 'showcase' (labels, transforms, views, screenshots, todo).

Evidence lines: CREATED:/MODIFIED:/SKIPPED:/INFO:/TODO:/ERROR: from C.Report, plus
MIRROR_CHECK, POSE, CAPTURE and DIRTY_AFTER lines. report.finish() raises RuntimeError when any
step failed.
"""

import importlib
import math
import os
import sys

import unreal
import vibeue

TOOLS_DIR = '/Users/mengmeile/Downloads/lianxi/m/Tools/IceSlash'
if TOOLS_DIR not in sys.path:
    sys.path.insert(0, TOOLS_DIR)
import ice_slash_common as C  # noqa: E402
importlib.reload(C)

SCRIPT_NAME = 'ice_slash_06_showcase'

# ---------------------------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------------------------
# FORCE: re-apply every transform / material / setting even when it already matches.
FORCE = False
# REBUILD: when an actor with one of our labels exists but has the wrong class, rename it to
# '<label>_stale' and spawn a fresh one (never destroys anything). False = report an error.
REBUILD = False
# Stop instead of switching levels when the currently open level has unsaved changes.
# (new_level closes the current level WITHOUT saving, LevelEditorSubsystem.cpp:669-719, and
# load_level's default FAIL policy raises on unsaved level changes, LevelEditorSubsystem.cpp:816-820.)
ABORT_IF_OPEN_LEVEL_DIRTY = True
CAPTURE_SCREENSHOTS = False
# Un-minimize the editor window before capturing (capture_with_view refuses on a minimized
# window, UViewportService.cpp:1000-1004; AGENTS.md section 6).
RESTORE_MINIMIZED_WINDOW = True
# Keep the preview material values on the arcs after the captures (persistent MIDs owned by
# the components). False = transient MIDs that are removed again before the level is saved.
PERSIST_PREVIEW_MATERIALS = False
# Crystal actor labels: False -> 'IceSlash_Crystal_SM_IceCluster_Core' (the part name from
# SM_IceCluster_v2_parts.json), True -> 'IceSlash_Crystal_Core'. Either form is found on re-run.
CRYSTAL_LABEL_SHORT = False

GUARD_LOCATION = (0.0, 0.0, 0.0)
# SK_Guard (like UE5 Manny) faces +Y in component space (tech plan 4.1 note; data JSON notes:
# "character faces +Y"); yaw -90 turns component +Y onto world +X.
GUARD_YAW = -90.0
SK_GUARD_PATH = '/Game/Characters/Mannequins/Meshes/SKM_Manny_Simple'
SK_GUARD_HEAD_PATH = ''          # UE5 built-in Manny robot is a single unified SkeletalMesh
PREVIEW_OFFSET_S = 0.25          # pose = animation time of FX_Slash_01 + this

FLOOR_Z = 0.0
FLOOR_SIZE_M = 40.0
FLOOR_MESH = '/Engine/BasicShapes/Plane'       # 100 x 100 cm plane, pivot at its centre
FLOOR_MATERIALS = [
    '/Game/VFX/IceSlash/Materials/M_ArenaFloor_Tiled',
    '/Game/VFX_Showcase/M_ShowcaseDark',
    '/Game/PredictiveIK/M_Floor',
]

DIR_LIGHT_INTENSITY = 3.0                      # lux, low
DIR_LIGHT_COLOR = (0.70, 0.82, 1.00)           # cool tint
DIR_LIGHT_ROT = dict(roll=0.0, pitch=-45.0, yaw=150.0)
SKY_LIGHT_INTENSITY = 0.4
SKY_LIGHT_COLOR = (0.55, 0.70, 1.00)
FOG_DENSITY = 0.02
FOG_HEIGHT_FALLOFF = 0.2
FOG_COLOR = (0.015, 0.035, 0.11)               # dark navy background
PPV_BLOOM = 0.8
PPV_EV100 = 1.0
PPV_VIGNETTE = 0.3

# Arc preview values (per actor, transient). DissolveAmount 0 keeps the tail solid.
ARC_PREVIEW_PARAMS = {'SlashProgress': 0.5, 'SlashWidth': 1.0, 'DissolveAmount': 0.0}
CRYSTAL_PREVIEW_PARAMS = {'CrystalGrowth': 1.0}
CRYSTAL_MI_BY_ROLE = {'prism': 'MI_IceCrystal_Prism', 'boulder': 'MI_IceCrystal_Boulder',
                      'snowbase': 'MI_IceCrystal_SnowBase'}
CRYSTAL_YAW = 0.0

# Socket fallbacks when step 02 has not created the sockets (tech plan section 4.1, component cm).
FALLBACK_HAND_BONE = 'hand_r'
FALLBACK_SLASH_ORIGIN_BONE = 'spine_03'
FALLBACK_BURST_CM = (0.0, 165.0, 5.0)
FALLBACK_CRYSTAL_CENTER_CM = (0.0, 185.0, 0.0)
CHEST_BONE = 'spine_05'
GROUND_TRAIL_Z = 3.0

CAMERA_FOCAL_MM = 32.0
# Views: azimuth is measured from the Guard's forward direction (negative = Guard's left/3-quarter side),
# distance is the 3D distance to the target in cm, height is absolute Z.
VIEW_FRONT = dict(azimuth=-38.0, distance=860.0, height=430.0, target='chest')
VIEW_SIDE = dict(azimuth=-90.0, distance=800.0, height=170.0, target='arcs')
VIEW_HIGH = dict(azimuth=-35.0, distance=950.0, height=650.0, target='arcs')
VIEW_CRYSTALS = dict(azimuth=-38.0, distance=920.0, height=440.0, target='crystals')
CAPTURE_W = 1920
CAPTURE_H = 1080
CAPTURE_FIXED_EXPOSURE = False   # the PPV already fixes exposure at EV100 PPV_EV100
CAPTURE_EV100 = 1.0

FOLDER = 'IceSlash'
SKILL_NS_NAME = 'NS_IceSlash_Skill'
SKILL_ACTOR_LABEL = 'IceSlash_NS_Skill'
SKILL_ACTOR_ALT_LABELS = ('IceSlash_Skill', 'NS_IceSlash_Skill')
NS_ASSETS = {
    'Skill': SKILL_NS_NAME,
    'HandEnergy': 'NS_IceSlash_HandEnergy',
    'SlashSparkles': 'NS_IceSlash_SlashSparkles',
    'GroundTrail': 'NS_IceSlash_GroundTrail',
    'Burst': 'NS_IceSlash_Burst',
    'CrystalSparkle': 'NS_IceSlash_CrystalSparkle',
}

KEEP_REL = unreal.AttachmentRule.KEEP_RELATIVE


# ---------------------------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------------------------
def V(xyz):
    return unreal.Vector(x=float(xyz[0]), y=float(xyz[1]), z=float(xyz[2]))


def R(roll=0.0, pitch=0.0, yaw=0.0):
    # unreal.Rotator positional order is (roll, pitch, yaw): always use keywords.
    return unreal.Rotator(roll=float(roll), pitch=float(pitch), yaw=float(yaw))


def rot_from_data(d):
    d = d or {}
    return R(roll=d.get('roll', 0.0), pitch=d.get('pitch', 0.0), yaw=d.get('yaw', 0.0))


def XF(loc, rot=None, scale=(1.0, 1.0, 1.0)):
    return unreal.Transform(location=V(loc), rotation=rot or R(), scale=V(scale))


def vtuple(v):
    return [round(float(v.x), 3), round(float(v.y), 3), round(float(v.z), 3)]


def rtuple(r):
    return {'roll': round(float(r.roll), 3), 'pitch': round(float(r.pitch), 3),
            'yaw': round(float(r.yaw), 3)}


def near_v(a, b, tol=0.05):
    return abs(a.x - b.x) <= tol and abs(a.y - b.y) <= tol and abs(a.z - b.z) <= tol


def _adiff(a, b):
    d = (float(a) - float(b)) % 360.0
    return min(d, 360.0 - d)


def near_r(a, b, tol=0.05):
    return (_adiff(a.roll, b.roll) <= tol and _adiff(a.pitch, b.pitch) <= tol
            and _adiff(a.yaw, b.yaw) <= tol)


def sock_str(name):
    s = str(name) if name is not None else ''
    return '' if s in ('None', '') else s


def mark(obj):
    """Record an undoable change and dirty the owning package (Python Object.modify,
    PyWrapperObject.cpp:1297). Some setters used here do not call Modify themselves."""
    try:
        obj.modify()
    except Exception:
        pass


def values_equal(cur, want):
    if isinstance(want, float) or isinstance(cur, float):
        try:
            return abs(float(cur) - float(want)) <= 1e-4
        except Exception:
            return False
    if isinstance(want, unreal.LinearColor):
        return (abs(cur.r - want.r) + abs(cur.g - want.g) + abs(cur.b - want.b)
                + abs(cur.a - want.a)) <= 1e-4
    return cur == want


def apply_props(report, label, obj, props):
    """Set only the properties that differ (C.set_props); returns the changed names."""
    changed = {}
    for k, v in props.items():
        try:
            cur = obj.get_editor_property(k)
        except Exception:
            cur = None
        if FORCE or cur is None or not values_equal(cur, v):
            changed[k] = v
    if changed:
        failed = C.set_props(obj, **changed) or []
        for k in failed:
            report.error('%s: could not set %s' % (label, k))
        return [k for k in changed if k not in failed]
    return []


# ---------------------------------------------------------------------------------------------
# Context shared by the steps
# ---------------------------------------------------------------------------------------------
class Ctx(object):
    def __init__(self, report):
        self.report = report
        self.data = None
        self.todo = []
        self.level_ready = False
        self.eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        self.les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
        self.ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
        self.by_label = {}
        self.guard = None
        self.body = None
        self.slash_root = None
        self.crystal_root = None
        self.arcs = []          # [(label, actor, mi)]
        self.crystals = []      # [(label, actor, mi)]
        self.niagara = {}
        self.views = {}
        self.shots = {}
        self.pose = {}
        self.arc_mode = {}
        self.crystal_anchor = None

    def todo_add(self, msg):
        self.todo.append(msg)
        self.report.todo(msg)

    def refresh_labels(self):
        self.by_label = {}
        for a in self.eas.get_all_level_actors():   # EditorActorSubsystem.h:168
            lab = a.get_actor_label()
            if lab in self.by_label:
                self.report.info('duplicate actor label %s; using the first one' % lab)
                continue
            self.by_label[lab] = a

    def find(self, *labels):
        for lab in labels:
            a = self.by_label.get(lab)
            if a is not None:
                return lab, a
        return None, None

    def ensure_actor(self, cls, label, folder=FOLDER, loc=(0, 0, 0), rot=None, alt_labels=()):
        """Return (actor, created). Checks the label first (AGENTS.md section 9)."""
        found_label, a = self.find(label, *alt_labels)
        if a is not None and not isinstance(a, cls):
            if REBUILD:
                mark(a)
                a.set_actor_label(found_label + '_stale')
                self.report.modified('actor ' + found_label,
                                     'wrong class %s renamed to %s_stale' % (a.get_class().get_name(), found_label))
                self.by_label.pop(found_label, None)
                a = None
            else:
                raise RuntimeError('actor label %s exists with class %s, expected %s (set REBUILD=True to '
                                   'rename it aside)' % (found_label, a.get_class().get_name(), cls.__name__))
        if a is not None:
            if str(a.get_folder_path()) != folder:
                mark(a)
                a.set_folder_path(folder)
                self.report.modified('actor ' + found_label, 'folder ' + folder)
            self.report.skipped('actor ' + found_label, 'exists; updating in place')
            return a, False
        # spawn_actor_from_class(class, location, rotation) EditorActorSubsystem.h:230
        a = self.eas.spawn_actor_from_class(cls, V(loc), rot or R())
        if a is None:
            raise RuntimeError('spawn_actor_from_class(%s) returned None for %s' % (cls.__name__, label))
        a.set_actor_label(label)
        a.set_folder_path(folder)
        self.by_label[label] = a
        self.report.created('actor %s (%s)' % (label, cls.__name__))
        return a, True


def ensure_world_transform(ctx, label, a, loc, rot, scale=(1.0, 1.0, 1.0)):
    want_l, want_s = V(loc), V(scale)
    if (FORCE or not near_v(a.get_actor_location(), want_l) or not near_r(a.get_actor_rotation(), rot)
            or not near_v(a.get_actor_scale3d(), want_s, 1e-4)):
        mark(a)
        # K2_SetActorTransform, ScriptName SetActorTransform (Actor.h:1798-1799)
        a.set_actor_transform(unreal.Transform(location=want_l, rotation=rot, scale=want_s), False, False)
        ctx.report.modified('actor ' + label, 'world transform %s %s %s' % (vtuple(want_l), rtuple(rot), vtuple(want_s)))


def ensure_attached(ctx, label, child, parent_comp, socket, rel_loc, rel_rot=None, rel_scale=(1.0, 1.0, 1.0)):
    """Attach child's root to parent_comp[socket] and set its relative transform, only when it
    differs. Attach uses KEEP_RELATIVE and the relative transform is then set explicitly
    (Actor.h:2005-2006 AttachToComponent, Actor.h:1896-1897 SetActorRelativeTransform)."""
    rel_rot = rel_rot or R()
    root = child.root_component
    if root is None:
        raise RuntimeError('%s has no root component' % label)
    # A Static component cannot be attached to a Movable parent (SceneComponent.cpp:2381-2394).
    if root.get_editor_property('mobility') != unreal.ComponentMobility.MOVABLE:
        root.set_mobility(unreal.ComponentMobility.MOVABLE)
        ctx.report.modified('actor ' + label, 'mobility Movable')
    cur_parent = root.get_attach_parent()           # SceneComponent.h:700-701
    cur_sock = sock_str(root.get_attach_socket_name())  # SceneComponent.h:704-705
    if FORCE or cur_parent != parent_comp or cur_sock != (socket or ''):
        mark(child)
        ok = child.attach_to_component(parent_comp, socket or '', KEEP_REL, KEEP_REL, KEEP_REL, False)
        if not ok:
            raise RuntimeError('attach %s to %s[%s] failed' % (label, parent_comp.get_name(), socket))
        ctx.report.modified('actor ' + label, 'attached to %s.%s socket=%s' % (
            parent_comp.get_owner().get_actor_label(), parent_comp.get_name(), socket or '-'))
    want_l, want_s = V(rel_loc), V(rel_scale)
    cl = root.get_editor_property('relative_location')
    cr = root.get_editor_property('relative_rotation')
    cs = root.get_editor_property('relative_scale3d')
    if FORCE or not near_v(cl, want_l) or not near_r(cr, rel_rot) or not near_v(cs, want_s, 1e-4):
        mark(child)
        child.set_actor_relative_transform(unreal.Transform(location=want_l, rotation=rel_rot, scale=want_s),
                                           False, False)
        ctx.report.modified('actor ' + label, 'relative transform %s %s %s' % (
            vtuple(want_l), rtuple(rel_rot), vtuple(want_s)))


def ensure_materials(ctx, label, comp, mi):
    if mi is None:
        return
    for i in range(max(1, comp.get_num_materials())):   # PrimitiveComponent.h:2333-2334
        if FORCE or comp.get_material(i) != mi:
            mark(comp)
            comp.set_material(i, mi)
            ctx.report.modified('actor ' + label, 'material[%d] = %s' % (i, mi.get_path_name()))


def ensure_static_mesh(ctx, label, comp, mesh):
    if FORCE or comp.get_editor_property('static_mesh') != mesh:
        mark(comp)
        if not comp.set_static_mesh(mesh):
            raise RuntimeError('%s: set_static_mesh(%s) returned False' % (label, mesh.get_path_name()))
        ctx.report.modified('actor ' + label, 'static mesh ' + mesh.get_path_name())


def mesh_layout(mesh, pivot_cm, expect_size_cm):
    """Detect how step 01 imported a mesh. Returns (baked, unit_fix).
    bake_meshes=False keeps the object origin (pivot_cm in the data JSON); bake_meshes=True puts
    the origin at the FBX scene origin (data JSON notes). A 100x small mesh means the FBX unit
    scale ended up on the node (G3 gotcha); unit_fix is the scale that compensates."""
    bb = mesh.get_bounding_box()            # StaticMesh.h:2245-2246, local cm
    size = [bb.max.x - bb.min.x, bb.max.y - bb.min.y, bb.max.z - bb.min.z]
    unit_fix = 1.0
    if expect_size_cm and max(expect_size_cm) > 0 and max(size) > 0:
        ratio = max(size) / max(expect_size_cm)
        if 0.005 < ratio < 0.02:
            unit_fix = 100.0
        elif 0.35 < ratio < 3.0:
            unit_fix = 1.0
        else:
            unit_fix = None  # unexplained size: reported as todo by the caller

    def dist(p):
        d = 0.0
        for v, lo, hi in zip(p, (bb.min.x, bb.min.y, bb.min.z), (bb.max.x, bb.max.y, bb.max.z)):
            e = max(lo - v, 0.0, v - hi)
            d += e * e
        return math.sqrt(d)
    scale = 1.0 / (unit_fix or 1.0)
    d_origin = dist((0.0, 0.0, 0.0))
    d_pivot = dist([c * scale for c in pivot_cm])
    baked = d_pivot + 1.0 < d_origin
    return baked, unit_fix, size, d_origin, d_pivot


def load_or_todo(ctx, path, what):
    obj = C.load(path) if C.asset_exists(path) else None
    if obj is None:
        ctx.todo_add('%s missing: %s (run the step that creates it, then re-run 06)' % (what, path))
    return obj


# ---------------------------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------------------------
def step_level(ctx):
    """Create C.MAP_PATH if missing, then make it the open level (never edits another map)."""
    rep = ctx.report
    if ctx.ues.get_game_world() is not None:   # UnrealEditorSubsystem.h:51-52
        raise RuntimeError('PIE / Simulate is running; stop it before building the showcase level')
    world = ctx.ues.get_editor_world()
    cur_pkg = world.get_outermost().get_name() if world else ''
    rep.info('open level: %s' % cur_pkg)
    if cur_pkg == C.MAP_PATH:
        rep.skipped(C.MAP_PATH, 'already the open level')
        ctx.level_ready = True
        return
    dirty = [str(p) for p in unreal.PythonTools.get_dirty_packages(True)]   # PythonTools.h:75
    if ABORT_IF_OPEN_LEVEL_DIRTY and cur_pkg and cur_pkg in dirty:
        raise RuntimeError('the open level %s has unsaved changes; save or discard them first (this script '
                           'never saves or discards another map)' % cur_pkg)
    if not C.guard_resident_maps(rep):
        raise RuntimeError('resident maps present; a level change now would fatal the editor')
    if C.asset_exists(C.MAP_PATH):
        ok = vibeue.safe_load_level(C.MAP_PATH)   # vibeue.py:530 (raises LevelLoadRefused)
        if not ok:
            raise RuntimeError('safe_load_level(%s) returned False' % C.MAP_PATH)
        rep.info('loaded level %s' % C.MAP_PATH)
    else:
        C.ensure_dir(C.MAP_PATH.rsplit('/', 1)[0])
        # NewLevel: blank NewMap + SaveMap, unattended (LevelEditorSubsystem.cpp:669-719).
        ok = ctx.les.new_level(C.MAP_PATH, False)
        if not ok:
            raise RuntimeError('LevelEditorSubsystem.new_level(%s) returned False' % C.MAP_PATH)
        rep.created(C.MAP_PATH)
    world = ctx.ues.get_editor_world()
    now_pkg = world.get_outermost().get_name() if world else ''
    if now_pkg != C.MAP_PATH:
        raise RuntimeError('expected %s to be open after the level step, got %s' % (C.MAP_PATH, now_pkg))
    ctx.level_ready = True


def step_environment(ctx):
    rep = ctx.report
    # Floor --------------------------------------------------------------------------------
    try:
        a, _ = ctx.ensure_actor(unreal.StaticMeshActor, 'IceSlash_Floor', FOLDER + '/Env')
        comp = a.static_mesh_component
        mesh = C.load(FLOOR_MESH)
        if mesh is None:
            raise RuntimeError('missing engine mesh ' + FLOOR_MESH)
        ensure_static_mesh(ctx, 'IceSlash_Floor', comp, mesh)
        mat = None
        for p in FLOOR_MATERIALS:
            if C.asset_exists(p):
                mat = C.load(p)
                break
        if mat is None:
            ctx.todo_add('no dark floor material found (%s); floor keeps the mesh default' % FLOOR_MATERIALS)
        else:
            ensure_materials(ctx, 'IceSlash_Floor', comp, mat)
        ensure_world_transform(ctx, 'IceSlash_Floor', a, (0.0, 0.0, FLOOR_Z), R(),
                               (FLOOR_SIZE_M, FLOOR_SIZE_M, 1.0))
        comp.set_collision_profile_name('BlockAll')
    except Exception as exc:
        rep.error('floor', exc)

    # Directional light (Movable: no lighting build needed for the preview) ------------------
    try:
        a, _ = ctx.ensure_actor(unreal.DirectionalLight, 'IceSlash_DirLight', FOLDER + '/Env', (0, 0, 800))
        lc = a.light_component
        if lc.get_editor_property('mobility') != unreal.ComponentMobility.MOVABLE:
            lc.set_mobility(unreal.ComponentMobility.MOVABLE)
            rep.modified('actor IceSlash_DirLight', 'mobility Movable')
        ensure_world_transform(ctx, 'IceSlash_DirLight', a, (0, 0, 800), R(**DIR_LIGHT_ROT))
        ch = apply_props(rep, 'IceSlash_DirLight', lc, {
            'intensity': float(DIR_LIGHT_INTENSITY),
            'light_color': unreal.Color(r=int(DIR_LIGHT_COLOR[0] * 255), g=int(DIR_LIGHT_COLOR[1] * 255),
                                        b=int(DIR_LIGHT_COLOR[2] * 255), a=255)})
        if ch:
            rep.modified('actor IceSlash_DirLight', ', '.join(ch))
    except Exception as exc:
        rep.error('directional light', exc)

    # Sky light --------------------------------------------------------------------------------
    try:
        a, _ = ctx.ensure_actor(unreal.SkyLight, 'IceSlash_SkyLight', FOLDER + '/Env', (0, 0, 600))
        lc = a.light_component
        if lc.get_editor_property('mobility') != unreal.ComponentMobility.MOVABLE:
            lc.set_mobility(unreal.ComponentMobility.MOVABLE)
            rep.modified('actor IceSlash_SkyLight', 'mobility Movable')
        # 'intensity' and 'real_time_capture' proven in Saved/PredictiveIK/setup_showcase.py:51-53.
        ch = apply_props(rep, 'IceSlash_SkyLight', lc, {
            'intensity': float(SKY_LIGHT_INTENSITY), 'real_time_capture': False,  # no sky actor: real-time capture only prints an on-screen warning
            'light_color': unreal.Color(r=int(SKY_LIGHT_COLOR[0] * 255), g=int(SKY_LIGHT_COLOR[1] * 255),
                                        b=int(SKY_LIGHT_COLOR[2] * 255), a=255)})
        if ch:
            rep.modified('actor IceSlash_SkyLight', ', '.join(ch))
    except Exception as exc:
        rep.error('sky light', exc)

    # Exponential height fog (dark navy background) -------------------------------------------
    try:
        a, _ = ctx.ensure_actor(unreal.ExponentialHeightFog, 'IceSlash_Fog', FOLDER + '/Env', (0, 0, 0))
        fc = a.get_editor_property('component')    # ExponentialHeightFog.h:28
        want = unreal.LinearColor(r=FOG_COLOR[0], g=FOG_COLOR[1], b=FOG_COLOR[2], a=1.0)
        cur_d = fc.get_editor_property('fog_density')
        cur_f = fc.get_editor_property('fog_height_falloff')
        cur_c = fc.get_editor_property('fog_inscattering_luminance')
        if FORCE or not values_equal(cur_d, FOG_DENSITY) or not values_equal(cur_f, FOG_HEIGHT_FALLOFF) \
                or not values_equal(cur_c, want):
            mark(fc)
            # The fog properties are BlueprintReadOnly; use the UFUNCTION setters
            # (ExponentialHeightFogComponent.h:250-257, :286-287).
            fc.set_fog_density(float(FOG_DENSITY))
            fc.set_fog_height_falloff(float(FOG_HEIGHT_FALLOFF))
            fc.set_fog_inscattering_color(want)
            rep.modified('actor IceSlash_Fog', 'density %.3f falloff %.2f colour %s' % (
                FOG_DENSITY, FOG_HEIGHT_FALLOFF, FOG_COLOR))
    except Exception as exc:
        rep.error('height fog', exc)

    # Unbound post-process volume -------------------------------------------------------------
    try:
        a, _ = ctx.ensure_actor(unreal.PostProcessVolume, 'IceSlash_PPV', FOLDER + '/Env', (0, 0, 0))
        ch = apply_props(rep, 'IceSlash_PPV', a, {'unbound': True, 'priority': 10.0})
        s = a.get_editor_property('settings')     # struct COPY: modify then set back (Scene.h)
        want = {
            'override_bloom_intensity': True, 'bloom_intensity': float(PPV_BLOOM),               # Scene.h:824,1633
            'override_auto_exposure_min_brightness': True,                                     # Scene.h:926
            'auto_exposure_min_brightness': float(PPV_EV100),                                   # Scene.h:1998
            'override_auto_exposure_max_brightness': True,                                     # Scene.h:929
            'auto_exposure_max_brightness': float(PPV_EV100),                                   # Scene.h:2006
            'override_auto_exposure_bias': True, 'auto_exposure_bias': 0.0,                    # Scene.h:941
            'override_vignette_intensity': True, 'vignette_intensity': float(PPV_VIGNETTE),     # Scene.h:1019,2147
        }
        sch = apply_props(rep, 'IceSlash_PPV.settings', s, want)
        if sch:
            mark(a)
            a.set_editor_property('settings', s)
        if ch or sch:
            rep.modified('actor IceSlash_PPV', ', '.join(ch + sch))
    except Exception as exc:
        rep.error('post-process volume', exc)


def step_guard(ctx):
    rep = ctx.report
    data = ctx.data
    a, _ = ctx.ensure_actor(unreal.SkeletalMeshActor, 'IceSlash_Guard', FOLDER + '/Guard',
                            GUARD_LOCATION, R(yaw=GUARD_YAW))
    ctx.guard = a
    body = a.skeletal_mesh_component              # SkeletalMeshActor.h:38-39
    ctx.body = body
    ensure_world_transform(ctx, 'IceSlash_Guard', a, GUARD_LOCATION, R(yaw=GUARD_YAW))
    sk = C.load(SK_GUARD_PATH)
    if sk is None:
        raise RuntimeError('missing ' + SK_GUARD_PATH)
    if FORCE or body.get_editor_property('skeletal_mesh_asset') != sk:
        mark(body)
        body.set_skeletal_mesh_asset(sk)              # SkeletalMeshComponent.h:369
        rep.modified('actor IceSlash_Guard', 'skeletal mesh ' + SK_GUARD_PATH)
    body.set_collision_profile_name('NoCollision')

    # Pose: single-node animation paused at FX_Slash_01 + PREVIEW_OFFSET_S (animation time).
    t_slash1 = None
    for ev in data.get('timeline', []):
        if ev.get('event') == 'FX_Slash_01':
            t_slash1 = float(ev['time_s']) - float(data.get('anim_start_offset_s', 0.0))
    if t_slash1 is None:
        t_slash1 = float(data['arcs'][0]['time_range_s'][0])
    t_pose = t_slash1 + PREVIEW_OFFSET_S
    anim_path = C.ANIM_DIR + '/AS_Manny_IceSlash_Combo'
    anim = load_or_todo(ctx, anim_path, 'retargeted Manny animation')
    ctx.pose = {'anim': anim_path if anim else None, 'time_s': round(t_pose, 4)}
    if anim is not None:
        anim_skel = anim.get_editor_property('skeleton')        # AnimationAsset.h:993-994
        mesh_skel = sk.get_editor_property('skeleton')          # SkeletalMesh.h:769-770
        if anim_skel != mesh_skel:
            raise RuntimeError('%s skeleton %s does not match SK_Guard skeleton %s' % (
                anim_path, anim_skel.get_path_name() if anim_skel else None,
                mesh_skel.get_path_name() if mesh_skel else None))
        length = float(anim.get_play_length())
        t_pose = max(0.0, min(t_pose, length))
        ctx.pose['time_s'] = round(t_pose, 4)
        cur = body.get_editor_property('animation_data')        # SkeletalMeshComponent.h:449-450
        same = (cur.get_editor_property('anim_to_play') == anim
                and abs(float(cur.get_editor_property('saved_position')) - t_pose) < 1e-3
                and not cur.get_editor_property('saved_playing')
                and body.get_editor_property('animation_mode') == unreal.AnimationMode.ANIMATION_SINGLE_NODE)
        if FORCE or not same:
            mark(body)
            # OverrideAnimationData stores AnimationData (serialized), switches to single-node mode
            # and immediately ticks + refreshes the bones (SkeletalMeshComponent.cpp:4436-4452).
            body.override_animation_data(anim, False, False, t_pose, 0.0)
            rep.modified('actor IceSlash_Guard', 'pose %s @ %.4f s (paused)' % (anim_path, t_pose))
        print('POSE: %s at %.4f s (FX_Slash_01 anim time %.4f + %.2f)' % (anim_path, t_pose, t_slash1,
                                                                          PREVIEW_OFFSET_S))
    else:
        rep.info('IceSlash_Guard keeps the reference pose')

    # Head: optional separate SkeletalMeshActor (skipped when using UE5 unified SKM_Manny_Simple).
    if SK_GUARD_HEAD_PATH:
        try:
            head_sk = C.load(SK_GUARD_HEAD_PATH)
            if head_sk is None:
                raise RuntimeError('missing ' + SK_GUARD_HEAD_PATH)
            h, _ = ctx.ensure_actor(unreal.SkeletalMeshActor, 'IceSlash_Guard_Head', FOLDER + '/Guard',
                                    GUARD_LOCATION, R(yaw=GUARD_YAW))
            hc = h.skeletal_mesh_component
            if FORCE or hc.get_editor_property('skeletal_mesh_asset') != head_sk:
                mark(hc)
                hc.set_skeletal_mesh_asset(head_sk)
                rep.modified('actor IceSlash_Guard_Head', 'skeletal mesh ' + SK_GUARD_HEAD_PATH)
            hc.set_collision_profile_name('NoCollision')
            ensure_attached(ctx, 'IceSlash_Guard_Head', h, body, '', (0, 0, 0))
            leader = None
            try:
                leader = hc.get_editor_property('leader_pose_component')   # SkinnedMeshComponent.h:325-326
            except Exception:
                leader = None
            if FORCE or leader != body:
                mark(hc)
                hc.set_leader_pose_component(body, True)                    # SkinnedMeshComponent.h:1919-1920
                rep.modified('actor IceSlash_Guard_Head', 'leader pose -> IceSlash_Guard')
        except Exception as exc:
            rep.error('guard head', exc)


def step_slash(ctx):
    rep = ctx.report
    data = ctx.data
    body = ctx.body
    mirror = data.get('mirror_correction', {})
    pscale = mirror.get('parent_scale', [1, 1, 1]) if mirror.get('needed', True) else [1, 1, 1]
    root, _ = ctx.ensure_actor(unreal.Actor, 'IceSlash_SlashRoot', FOLDER + '/Slash')
    if root.root_component is None:
        # UActorFactoryEmptyActor adds a Movable DefaultSceneRoot (ActorFactory.cpp:1242-1264).
        raise RuntimeError('IceSlash_SlashRoot has no root component')
    # Mirror parent attached to the SKELETAL MESH component (not the actor root/capsule),
    # identity location/rotation, relative scale (1,-1,1) (data JSON mirror_correction).
    ensure_attached(ctx, 'IceSlash_SlashRoot', root, body, '', (0, 0, 0), R(), pscale)
    ctx.slash_root = root
    guard_xf = ctx.guard.get_actor_transform()
    centres = []
    for i, arc in enumerate(data['arcs']):
        n = i + 1
        label = 'IceSlash_Arc_%02d' % n
        try:
            mesh_path = '%s/SM_SlashArc_%02d' % (C.MESH_DIR, n)
            mi_path = '%s/MI_SlashArc_%02d' % (C.MAT_DIR, n)
            mesh = load_or_todo(ctx, mesh_path, 'slash arc mesh')
            mi = load_or_todo(ctx, mi_path, 'slash arc material instance')
            a, _ = ctx.ensure_actor(unreal.StaticMeshActor, label, FOLDER + '/Slash')
            comp = a.static_mesh_component
            comp.set_collision_profile_name('NoCollision')
            pivot = arc['pivot_cm']
            loc = list(pivot)
            scale = list(arc.get('scale', [1, 1, 1]))
            baked = False
            if mesh is not None:
                ensure_static_mesh(ctx, label, comp, mesh)
                baked, unit_fix, size, d0, dp = mesh_layout(mesh, pivot, arc.get('bounds_cm'))
                rep.info('%s bbox size %s (expected %s), origin-to-box %.1f, pivot-to-box %.1f -> %s' % (
                    mesh_path, [round(s, 1) for s in size], arc.get('bounds_cm'), d0, dp,
                    'baked (origin = FBX origin)' if baked else 'pivot at slash head'))
                if unit_fix is None:
                    ctx.todo_add('%s bounding box %s differs from legacy bounds_cm %s (widened v4 sheet)' % (
                        mesh_path, [round(s, 1) for s in size], arc.get('bounds_cm')))
                elif unit_fix != 1.0:
                    scale = [s * unit_fix for s in scale]
                    ctx.todo_add('%s is 100x too small (FBX unit scale on the node); compensated with actor '
                                 'scale x100 - fix the import (step 01)' % mesh_path)
                if baked:
                    loc = [0.0, 0.0, 0.0]
                ctx.arc_mode[label] = 'baked' if baked else 'pivot'
            ensure_materials(ctx, label, comp, mi)
            ensure_attached(ctx, label, a, root.root_component, '', loc, rot_from_data(arc.get('rotation_deg')), scale)
            # Static blade actors are superseded by NS_IceSlash_Skill (Blade_01..05); keep hidden in game/editor.
            if C.asset_exists('%s/%s' % (C.NS_DIR, SKILL_NS_NAME)):
                if not a.get_editor_property('bHidden'):
                    mark(a)
                    a.set_actor_hidden_in_game(True)
                    rep.modified('actor ' + label, 'hidden in game (superseded by NS_IceSlash_Skill)')
                a.set_is_temporarily_hidden_in_editor(True)
            # Evidence: where does the slash head land? Expected world = Guard * (px, -py, pz).
            exp = guard_xf.transform_location(V((pivot[0], -pivot[1], pivot[2])))   # KismetMathLibrary.h:3982
            origin, extent = a.get_actor_bounds(False)                               # Actor.h:1610-1611
            centres.append(origin)
            if not baked:
                got = a.get_actor_location()
                err = math.sqrt((got.x - exp.x) ** 2 + (got.y - exp.y) ** 2 + (got.z - exp.z) ** 2)
                print('MIRROR_CHECK: %s head world %s expected %s error %.2f cm; bounds centre %s extent %s' % (
                    label, vtuple(got), vtuple(exp), err, vtuple(origin), vtuple(extent)))
                if err > 1.0:
                    rep.error('%s head is %.1f cm away from the mirror-corrected position' % (label, err))
            else:
                print('MIRROR_CHECK: %s (baked) bounds centre %s extent %s' % (label, vtuple(origin), vtuple(extent)))
            ctx.arcs.append((label, a, mi))
        except Exception as exc:
            rep.error(label, exc)
    if centres:
        fwd = guard_xf.rotation.rotator().yaw + 90.0   # component +Y forward
        fx, fy = math.cos(math.radians(fwd)), math.sin(math.radians(fwd))
        gl = guard_xf.translation
        ahead = [((c.x - gl.x) * fx + (c.y - gl.y) * fy) for c in centres]
        print('MIRROR_CHECK: arc bounds centres along Guard forward (cm): %s' % [round(v, 1) for v in ahead])
        rep.info('arc bounds centres along Guard forward (cm): %s' % [round(v, 1) for v in ahead])


def socket_world(ctx, name, fallback_bone=None, fallback_cm=None):
    """World location of a Guard socket; falls back to a bone or a component-space offset."""
    body = ctx.body
    if body.does_socket_exist(name):                       # SceneComponent.h:832
        return body.get_socket_location(name), name        # SceneComponent.h:809
    if fallback_bone and body.does_socket_exist(fallback_bone):
        ctx.todo_add('socket %s missing on SK_Guard; using bone %s (run step 02)' % (name, fallback_bone))
        return body.get_socket_location(fallback_bone), fallback_bone
    ctx.todo_add('socket %s missing on SK_Guard; using component offset %s (run step 02)' % (name, fallback_cm))
    return ctx.guard.get_actor_transform().transform_location(V(fallback_cm or (0, 0, 0))), None


def step_crystals(ctx):
    rep = ctx.report
    data = ctx.data
    center = data['cluster_center_cm']
    cscale = float(data.get('cluster_scale', 4.0))
    base_mesh = C.load('%s/SM_IceCluster_Base' % C.CLUSTER_DIR) if C.asset_exists('%s/SM_IceCluster_Base' % C.CLUSTER_DIR) else None
    if base_mesh is not None:
        bb_base = base_mesh.get_bounding_box()
        base_xy = max(bb_base.max.x - bb_base.min.x, bb_base.max.y - bb_base.min.y)
        if base_xy < 180.0 and cscale < 2.5:
            cscale = 5.2
            rep.info('SM_IceCluster_Base local XY=%.1f cm (v2 union); using cluster_scale=%.2f (~520 cm)' % (base_xy, cscale))
    anchor, src = socket_world(ctx, 'FX_CrystalCenter', None, FALLBACK_CRYSTAL_CENTER_CM)
    anchor = unreal.Vector(x=anchor.x, y=anchor.y, z=FLOOR_Z)
    ctx.crystal_anchor = {'world_cm': vtuple(anchor), 'source': src or 'component offset'}
    root, _ = ctx.ensure_actor(unreal.Actor, 'IceSlash_CrystalRoot', FOLDER + '/Crystals', vtuple(anchor))
    if root.root_component is None:
        raise RuntimeError('IceSlash_CrystalRoot has no root component')
    ensure_world_transform(ctx, 'IceSlash_CrystalRoot', root, vtuple(anchor), R(yaw=CRYSTAL_YAW),
                           (cscale, cscale, cscale))
    ctx.crystal_root = root
    for part in data['cluster_parts']:
        name = part['name']
        short = name.replace('SM_IceCluster_', '')
        label = 'IceSlash_Crystal_' + (short if CRYSTAL_LABEL_SHORT else name)
        alt = 'IceSlash_Crystal_' + (name if CRYSTAL_LABEL_SHORT else short)
        if int(part.get('faces', 0)) <= 0:
            rep.skipped(label, '0 faces')
            continue
        try:
            mesh = load_or_todo(ctx, '%s/%s' % (C.CLUSTER_DIR, name), 'ice cluster part mesh')
            mi_name = CRYSTAL_MI_BY_ROLE.get(part.get('material_role', 'prism'), 'MI_IceCrystal_Prism')
            mi = load_or_todo(ctx, '%s/%s' % (C.MAT_DIR, mi_name), 'crystal material instance')
            a, _ = ctx.ensure_actor(unreal.StaticMeshActor, label, FOLDER + '/Crystals', alt_labels=(alt,))
            label = a.get_actor_label()
            comp = a.static_mesh_component
            comp.set_collision_profile_name('NoCollision')
            pivot = part['pivot_cm']
            origin_cm = list(pivot)
            scale = [1.0, 1.0, 1.0]
            if mesh is not None:
                ensure_static_mesh(ctx, label, comp, mesh)
                baked, unit_fix, size, d0, dp = mesh_layout(mesh, pivot, part.get('size_cm'))
                rep.info('%s bbox size %s (expected %s) -> %s' % (
                    name, [round(s, 1) for s in size], part.get('size_cm'), 'baked' if baked else 'pivot at base'))
                if unit_fix is None:
                    ctx.todo_add('%s bounding box %s differs from size_cm %s (v2 mesh vs v3 JSON)' % (
                        name, [round(s, 1) for s in size], part.get('size_cm')))
                elif unit_fix != 1.0:
                    scale = [unit_fix] * 3
                    ctx.todo_add('%s is 100x too small; compensated with relative scale x100 - fix step 01' % name)
                if baked:
                    origin_cm = [0.0, 0.0, 0.0]
            rel = [origin_cm[k] - center[k] for k in range(3)]
            ensure_materials(ctx, label, comp, mi)
            ensure_attached(ctx, label, a, root.root_component, '', rel, rot_from_data(part.get('rotation_deg')), scale)
            ctx.crystals.append((label, a, mi))
        except Exception as exc:
            rep.error(label, exc)


LEGACY_NIAGARA_LABELS = (
    'IceSlash_NS_HandEnergy',
    'IceSlash_NS_SlashSparkles_01',
    'IceSlash_NS_SlashSparkles_02',
    'IceSlash_NS_SlashSparkles_03',
    'IceSlash_NS_SlashSparkles_04',
    'IceSlash_NS_SlashSparkles_05',
    'IceSlash_NS_GroundTrail',
    'IceSlash_NS_Burst',
    'IceSlash_NS_CrystalSparkle',
)


def step_niagara(ctx):
    rep = ctx.report
    if ctx.slash_root is None:
        rep.error('IceSlash_NS_Skill: no IceSlash_SlashRoot')
        return

    try:
        a, _ = ctx.ensure_actor(unreal.NiagaraActor, SKILL_ACTOR_LABEL, FOLDER + '/Niagara',
                                alt_labels=SKILL_ACTOR_ALT_LABELS)
        label = a.get_actor_label()
        nc = a.niagara_component
        ns = load_or_todo(ctx, '%s/%s' % (C.NS_DIR, SKILL_NS_NAME), 'unified Niagara skill system')
        if ns is not None and (FORCE or nc.get_asset() != ns):
            mark(nc)
            nc.set_asset(ns)
            rep.modified('actor ' + label, 'asset ' + ns.get_path_name())
        if FORCE or nc.get_editor_property('auto_activate'):
            mark(nc)
            nc.set_auto_activate(False)
            rep.modified('actor ' + label, 'auto_activate False')
        ensure_attached(ctx, label, a, ctx.slash_root.root_component, '', (0.0, 0.0, 0.0), R(), (1.0, 1.0, 1.0))
        ctx.niagara[label] = a
    except Exception as exc:
        rep.error(SKILL_ACTOR_LABEL, exc)

    # Remove deprecated standalone Niagara actors per v3 single-system architecture (#134).
    for old_label in LEGACY_NIAGARA_LABELS:
        _, old_a = ctx.find(old_label)
        if old_a is not None:
            ctx.eas.destroy_actor(old_a)
            ctx.by_label.pop(old_label, None)
            rep.modified('actor ' + old_label, 'destroyed legacy NiagaraActor (unified into IceSlash_NS_Skill)')


def look_rot(cam, tgt):
    dx, dy, dz = tgt.x - cam.x, tgt.y - cam.y, tgt.z - cam.z
    return R(pitch=math.degrees(math.atan2(dz, math.hypot(dx, dy))), yaw=math.degrees(math.atan2(dy, dx)))


def make_view(ctx, spec, targets, fov):
    tgt = targets[spec['target']]
    fwd = GUARD_YAW + 90.0
    yaw = math.radians(fwd + spec['azimuth'])
    dz = spec['height'] - tgt.z
    horiz = math.sqrt(max(spec['distance'] ** 2 - dz ** 2, 1.0))
    cam = unreal.Vector(x=tgt.x + horiz * math.cos(yaw), y=tgt.y + horiz * math.sin(yaw), z=spec['height'])
    rot = look_rot(cam, tgt)
    return {'location': cam, 'rotation': rot, 'target': tgt, 'fov': fov, 'spec': dict(spec)}


def step_camera(ctx):
    rep = ctx.report
    body = ctx.body
    gl = ctx.guard.get_actor_location()
    chest = body.get_socket_location(CHEST_BONE) if body.does_socket_exist(CHEST_BONE) else \
        unreal.Vector(x=gl.x, y=gl.y, z=gl.z + 140.0)
    arcs_t = chest
    if ctx.arcs:
        mins, maxs = [1e9] * 3, [-1e9] * 3
        for _, a, _ in ctx.arcs:
            o, e = a.get_actor_bounds(False)
            for k, (c, h) in enumerate(((o.x, e.x), (o.y, e.y), (o.z, e.z))):
                mins[k] = min(mins[k], c - h)
                maxs[k] = max(maxs[k], c + h)
        arcs_t = unreal.Vector(x=(mins[0] + maxs[0]) / 2, y=(mins[1] + maxs[1]) / 2,
                               z=min(max((mins[2] + maxs[2]) / 2, 80.0), 200.0))
    cr = ctx.crystal_root.get_actor_location() if ctx.crystal_root else gl
    targets = {'chest': chest, 'arcs': arcs_t, 'crystals': unreal.Vector(x=cr.x, y=cr.y, z=cr.z + 160.0)}

    a, _ = ctx.ensure_actor(unreal.CineCameraActor, 'IceSlash_Camera', FOLDER + '/Camera')
    cc = a.get_cine_camera_component()           # CineCameraActor.h:89-90
    if FORCE or not values_equal(cc.get_editor_property('current_focal_length'), CAMERA_FOCAL_MM):
        mark(cc)
        # SetCurrentFocalLength is only a BlueprintSetter (CineCameraComponent.h:65), not a Python method;
 # set_editor_property routes through that setter.
        cc.set_editor_property('current_focal_length', float(CAMERA_FOCAL_MM))
        rep.modified('actor IceSlash_Camera', 'focal length %.1f mm' % CAMERA_FOCAL_MM)
    try:
        fs = cc.get_editor_property('focus_settings')        # CineCameraComponent.h:52 (struct copy)
        if fs.get_editor_property('focus_method') != unreal.CameraFocusMethod.DISABLE:
            fs.set_editor_property('focus_method', unreal.CameraFocusMethod.DISABLE)
            mark(cc)
            cc.set_editor_property('focus_settings', fs)
            rep.modified('actor IceSlash_Camera', 'focus disabled (no DOF blur)')
    except Exception as exc:
        rep.error('IceSlash_Camera focus settings', exc)
    sensor_w = float(cc.get_editor_property('filmback').get_editor_property('sensor_width'))
    fov = math.degrees(2.0 * math.atan(sensor_w / (2.0 * CAMERA_FOCAL_MM)))
    views = {
        'front': make_view(ctx, VIEW_FRONT, targets, fov),
        'side': make_view(ctx, VIEW_SIDE, targets, fov),
        'high': make_view(ctx, VIEW_HIGH, targets, fov),
        'crystals': make_view(ctx, VIEW_CRYSTALS, targets, fov),
    }
    front = views['front']
    ensure_world_transform(ctx, 'IceSlash_Camera', a, vtuple(front['location']), front['rotation'])
    ctx.views = views
    for k, v in views.items():
        rep.info('view %s: cam %s rot %s target %s hfov %.1f' % (
            k, vtuple(v['location']), rtuple(v['rotation']), vtuple(v['target']), v['fov']))


def _preview_mid(ctx, comp, mi, params, label):
    """Apply a dynamic material instance with preview values on every slot of comp."""
    for i in range(max(1, comp.get_num_materials())):
        parent = mi or comp.get_material(i)
        if parent is None:
            continue
        if PERSIST_PREVIEW_MATERIALS:
            mid = comp.create_dynamic_material_instance(i, parent, 'IceSlashPreview')  # PrimitiveComponent.h:1633
        else:
            # Transient MID in the transient package (KismetMaterialLibrary.cpp:123-142),
            # Python class name MaterialLibrary (ScriptName, KismetMaterialLibrary.h:21).
            mid = unreal.MaterialLibrary.create_dynamic_material_instance(
                comp, parent, 'IceSlashPreview_%d' % i, unreal.MIDCreationFlags.TRANSIENT)
            comp.set_material(i, mid)
        if mid is None:
            raise RuntimeError('%s: could not create a dynamic material instance' % label)
        got = {}
        for k, v in params.items():
            mid.set_scalar_parameter_value(k, float(v))                  # MaterialInstanceDynamic.h:24
            got[k] = round(float(mid.get_scalar_parameter_value(k)), 3)  # MaterialInstanceDynamic.h:56-57
        print('PREVIEW_MID: %s slot %d %s' % (label, i, got))


def _restore_materials(ctx, items):
    for label, a, mi in items:
        comp = a.static_mesh_component
        for i in range(max(1, comp.get_num_materials())):
            if mi is not None:
                comp.set_material(i, mi)
            else:
                comp.set_material(i, None)   # back to the mesh's own material


def _set_visible(items, visible):
    for _, a, _ in items:
        a.static_mesh_component.set_visibility(visible, False)   # SceneComponent.h:917


def _capture(ctx, key, filename):
    v = ctx.views[key]
    path = os.path.join(C.SHOTS_DIR, filename)
    # Renders the real level viewport from this pose once, writes the PNG and restores the
    # viewport (UViewportService.h:538-547, UViewportService.cpp:951-1091).
    res = unreal.ViewportService.capture_with_view(v['location'], v['rotation'], CAPTURE_W, CAPTURE_H, path,
                                                   float(v['fov']), CAPTURE_FIXED_EXPOSURE, CAPTURE_EV100)
    print('CAPTURE: %s success=%s path=%s bytes=%s view_applied=%s error=%s' % (
        key, res.success, res.output_path, res.file_size_bytes, res.view_applied, res.error_message))
    if not res.success:
        raise RuntimeError('capture %s failed: %s' % (key, res.error_message))
    ctx.shots[key] = res.output_path
    ctx.report.created(res.output_path)


def step_capture(ctx):
    rep = ctx.report
    if not CAPTURE_SCREENSHOTS:
        rep.skipped('screenshots', 'CAPTURE_SCREENSHOTS=False')
        return
    if not ctx.views:
        raise RuntimeError('no camera views (camera step failed)')
    C.ensure_dir  # noqa: B018 (content dirs only; the shots folder is on disk)
    os.makedirs(C.SHOTS_DIR, exist_ok=True)
    try:
        state = unreal.ViewportService.get_editor_window_state()
        if RESTORE_MINIMIZED_WINDOW and '"is_minimized": true' in str(state).replace('":true', '": true'):
            rep.info('editor window minimized; restoring: %s' % unreal.ViewportService.set_editor_window_state('restore'))
    except Exception as exc:
        rep.info('window state check skipped: %s' % exc)
    arc_vis = [(lab, a, a.static_mesh_component.is_visible()) for lab, a, _ in ctx.arcs]
    cry_vis = [(lab, a, a.static_mesh_component.is_visible()) for lab, a, _ in ctx.crystals]
    # vibeue.viewport_state snapshots camera/FOV/exposure/game view and restores them
    # (vibeue.py:1092-1148; RestoreViewportInfo restores game view, UViewportService.cpp:340-342).
    with vibeue.viewport_state():
        try:
            try:
                unreal.ViewportService.set_game_view(True)   # hide editor icons in the shots
            except Exception as exc:
                rep.info('set_game_view failed: %s' % exc)
            for label, a, mi in ctx.arcs:
                _preview_mid(ctx, a.static_mesh_component, mi, ARC_PREVIEW_PARAMS, label)
            _set_visible(ctx.crystals, False)
            for key, fn in (('front', 'ice_slash_preview_front.png'), ('side', 'ice_slash_preview_side.png'),
                            ('high', 'ice_slash_preview_high.png')):
                try:
                    _capture(ctx, key, fn)
                except Exception as exc:
                    rep.error('capture ' + key, exc)
            _set_visible(ctx.crystals, True)
            _set_visible(ctx.arcs, False)
            for label, a, mi in ctx.crystals:
                _preview_mid(ctx, a.static_mesh_component, mi, CRYSTAL_PREVIEW_PARAMS, label)
            try:
                _capture(ctx, 'crystals', 'ice_slash_preview_crystals.png')
            except Exception as exc:
                rep.error('capture crystals', exc)
        finally:
            for _, a, vis in arc_vis + cry_vis:
                a.static_mesh_component.set_visibility(bool(vis), False)
            if not PERSIST_PREVIEW_MATERIALS:
                _restore_materials(ctx, ctx.arcs)
            _restore_materials(ctx, ctx.crystals)   # crystals never keep the growth=1 preview
            rep.info('viewport, visibility and materials restored after captures')


def step_save(ctx):
    rep = ctx.report
    world = ctx.ues.get_editor_world()
    pkg = world.get_outermost().get_name() if world else ''
    if pkg != C.MAP_PATH:
        raise RuntimeError('refusing to save: the open level is %s, not %s' % (pkg, C.MAP_PATH))
    if not ctx.les.save_current_level():       # LevelEditorSubsystem.cpp:825+
        raise RuntimeError('save_current_level returned False for ' + C.MAP_PATH)
    rep.modified(C.MAP_PATH, 'saved')
    C.save_all()
    print('DIRTY_AFTER: %s' % list(unreal.PythonTools.get_dirty_packages(True)))


def actor_record(a):
    root = a.root_component
    rec = {'world_location': vtuple(a.get_actor_location()), 'world_rotation': rtuple(a.get_actor_rotation()),
           'world_scale': vtuple(a.get_actor_scale3d()), 'class': a.get_class().get_name()}
    if root is not None and root.get_attach_parent() is not None:
        p = root.get_attach_parent()
        rec['attach_parent'] = '%s.%s' % (p.get_owner().get_actor_label(), p.get_name())
        rec['attach_socket'] = sock_str(root.get_attach_socket_name())
        rec['relative_location'] = vtuple(root.get_editor_property('relative_location'))
        rec['relative_rotation'] = rtuple(root.get_editor_property('relative_rotation'))
        rec['relative_scale'] = vtuple(root.get_editor_property('relative_scale3d'))
    return rec


def step_manifest(ctx):
    ctx.refresh_labels()
    labels = sorted(l for l in ctx.by_label if l.startswith('IceSlash_'))
    transforms = {}
    for lab in labels:
        try:
            transforms[lab] = actor_record(ctx.by_label[lab])
        except Exception as exc:
            transforms[lab] = {'error': str(exc)}
    views = {}
    for k, v in ctx.views.items():
        views[k] = {'location': vtuple(v['location']), 'rotation': rtuple(v['rotation']),
                    'target': vtuple(v['target']), 'hfov_deg': round(v['fov'], 2), 'spec': v['spec']}
    C.update_manifest('showcase', {
        'script': SCRIPT_NAME,
        'map': C.MAP_PATH,
        'labels': labels,
        'arc_labels': [l for l, _, _ in ctx.arcs],
        'crystal_labels': [l for l, _, _ in ctx.crystals],
        'niagara_labels': sorted(ctx.niagara),
        'transforms': transforms,
        'guard': {'label': 'IceSlash_Guard', 'yaw': GUARD_YAW, 'pose': ctx.pose},
        'arc_mesh_mode': ctx.arc_mode,
        'crystal_anchor': ctx.crystal_anchor,
        'camera': 'IceSlash_Camera',
        'views': views,
        'screenshots': ctx.shots,
        'preview_params': {'arcs': ARC_PREVIEW_PARAMS, 'crystals': CRYSTAL_PREVIEW_PARAMS,
                           'persisted': PERSIST_PREVIEW_MATERIALS},
        'todo': ctx.todo,
    })
    ctx.report.modified(C.MANIFEST_PATH, "section 'showcase'")


# ---------------------------------------------------------------------------------------------
def main():
    report = C.Report(SCRIPT_NAME)
    ctx = Ctx(report)
    try:
        ctx.data = C.load_data()
    except Exception as exc:
        report.error('load data %s' % C.DATA_PATH, exc)
        report.finish()
        return
    try:
        step_level(ctx)
    except Exception as exc:
        report.error('level', exc)
    if not ctx.level_ready:
        report.info('level is not ready: nothing was populated, nothing was saved')
        report.finish()
        return

    ctx.refresh_labels()
    step_environment(ctx)
    try:
        step_guard(ctx)
    except Exception as exc:
        report.error('guard', exc)
    if ctx.guard is not None and ctx.body is not None:
        for fn in (step_slash, step_crystals, step_niagara, step_camera):
            try:
                fn(ctx)
            except Exception as exc:
                report.error(fn.__name__, exc)
        try:
            step_capture(ctx)
        except Exception as exc:
            report.error('captures', exc)
    else:
        report.error('no Guard actor: slash, crystals, niagara, camera and captures skipped')
    try:
        step_save(ctx)
    except Exception as exc:
        report.error('save', exc)
    try:
        step_manifest(ctx)
    except Exception as exc:
        report.error('manifest', exc)
    report.finish()


if __name__ == '__main__':
    main()
