"""Ice Slash step 02: FX sockets, retargeted attack animation and FX notifies.

Purpose
    1) Adds the FX sockets to two Skeleton assets, so every mesh on those skeletons gets them:
         * SKEL_Guard (/Game/Guard/Characters/Guard/SKEL_Guard), added through its visible mesh SK_Guard.
         * the skeleton of the gameplay driver mesh, which is the hidden Manny on the
           BP_ThirdPersonCharacter component CharacterMesh0. The mesh is read at runtime, because
           Saved/PredictiveIK/Guard/setup_guard.py never sets it.
       Sockets: FX_Hand_R (hand_r), FX_Hand_L (hand_l), FX_SlashOrigin (spine_03, tech plan 4.1),
       FX_IceBurst (root, 120 cm forward on the ground) and FX_CrystalCenter (root, 0,0,0).
    2) Retargets /Game/RamsterZ_FreeAnims_Volume1/AnimationSequence/1HM/1HM_AerialSwing01_2HitCombo:
         UE4 (RamsterZ) -> Manny driver skeleton with RTG_TraversalUE4ToManny,
           giving C.ANIM_DIR + '/AS_Manny_IceSlash_Combo'
         Manny -> SKEL_Guard with RTG_Guard (its rigs and meshes are checked at runtime first),
           giving C.ANIM_DIR + '/AS_Guard_IceSlash_Combo'
       It uses the IKRig batch retarget API (IKRetargetBatchOperation.run_batch_retarget_with_results).
    3) Adds named FX notifies to both outputs at ANIMATION time:
       sequence time from data/ice_slash_data.json minus anim_start_offset_s, snapped to the frame grid.
       FX_Slash_01/02/03 and FX_Slash_Impact always go on. FX_IceBurst, FX_CrystalReveal and FX_End
       go on only if they fall inside the clip; otherwise the manifest records them as
       sequence-driven events.
    4) Writes manifest sections 'sockets' and 'anim', saves what it touched (C.save_all) and ends with
       report.finish().

Run order
    01 import -> **02 anim+sockets (this file)** -> 03 slash material -> 04 crystal material
    -> 05 niagara -> 06 showcase level -> 07 sequence.
    Needs no output from step 01. It loads no level and touches no map.

How to run (inside the editor, by the owning agent):
    import runpy; runpy.run_path('/Users/mengmeile/Downloads/lianxi/m/Tools/IceSlash/ice_slash_02_anim_sockets.py', run_name='__main__')

Creates or modifies
    sockets on /Game/Guard/Characters/Guard/SKEL_Guard (plus the mesh-level copy on SK_Guard, see below)
    sockets on <driver skeleton> (plus the mesh-level copy on <driver mesh>)
    /Game/VFX/IceSlash/Anims/AS_Manny_IceSlash_Combo   (new, retargeted)
    /Game/VFX/IceSlash/Anims/AS_Guard_IceSlash_Combo   (new, retargeted)
    notifies (and, when the clip has none, one notify track 'FX') on both anims
    manifest sections 'sockets' and 'anim'

Engine behaviour this script depends on
    * VibeUE SkeletonService has no socket API. The skill says to use the engine SkeletalMeshTools,
      or unreal.* directly for skeleton sockets (Plugins/VibeUE/Skills/skeleton/SKILL.md:79-81). The
      toolset AddSocket only adds to the MESH (SkeletalMeshToolset.cpp:296-301). For a skeleton socket
      this script therefore uses the native route:
        unreal.new_object(SkeletalMeshSocket, outer=mesh) -> set_socket_parent -> set_socket_local_transform
        -> mesh.add_socket(sock, True) -> SkeletalMeshEditorSubsystem.rename_socket.
      USkeletalMesh::AddSocket(.., bAddToSkeleton=true) keeps the socket on the mesh AND duplicates it
      into the Skeleton (SkeletalMesh.cpp:5158-5238). The mesh copy shadows the skeleton copy on that
      one mesh, so this script keeps both copies identical. SkeletalMeshEditorSubsystem.RemoveSocket
      deletes both copies (SkeletalMeshEditorSubsystem.cpp:716-756), so the mesh copy is never removed.
    * SkeletalMeshSocket.socket_name and bone_name are VisibleAnywhere/BlueprintReadOnly
      (SkeletalMeshSocket.h:24-28), so the name is applied with rename_socket and the bone with
      set_socket_parent. Both call Modify() and so dirty the owning package
      (SkeletalMesh.cpp:7379-7428, :7469-7478, SkeletalMeshEditorSubsystem.cpp:607-694).
    * The offsets in bone space come from the reference pose:
      unreal.SkeletonService.get_bone_transform(mesh, bone, True) (USkeletonService.cpp:309-335)
      and Transform.inverse_transform_location / inverse_transform_rotation
      (KismetMathLibrary.h:4003, :4017).
    * The batch retarget raises a script error, which becomes a Python exception, when nothing is
      created or no op can run (IKRetargetBatchOperation.h:229-252, .cpp:1245-1347). Output name =
      Prefix + Name.Replace(Search, Replace) + Suffix (EditorAnimUtils.cpp:569-577), so Search/Replace
      gives the contract name directly. include_referenced_assets defaults to True, so it is set False.
    * AnimSequenceService.add_notify with '/Script/Engine.AnimNotify' makes a name-only skeleton notify
      (UAnimSequenceService.cpp:1720-1780). Indices change after every add (RefreshCacheData sorts the
      notifies), so the script re-lists by name before every edit. Never use AnimMontageService.add_notify
      with the abstract AnimNotify class: it crashes the editor (G4 digest; UAnimMontageService.cpp:1223-1237).

Idempotency
    Sockets that are missing are added. Sockets that differ (bone or transform) are changed in place
    and logged MODIFIED. Sockets that match are logged SKIPPED. Existing retarget outputs are skipped
    unless FORCE = True. Notifies are matched by name: a wrong time is moved in place with
    set_notify_trigger_time, never removed and re-added.

Exit
    report.finish() prints 'ICE_SLASH_SUMMARY {...}' and raises RuntimeError if any ERROR: was recorded.
"""

import sys
import importlib
import math

import unreal

TOOLS_DIR = '/Users/mengmeile/Downloads/lianxi/m/Tools/IceSlash'
if TOOLS_DIR not in sys.path:
    sys.path.insert(0, TOOLS_DIR)
import ice_slash_common as C  # noqa: E402
importlib.reload(C)

# --------------------------------------------------------------------------------------
# CONFIG
# --------------------------------------------------------------------------------------
SCRIPT_NAME = 'ice_slash_02_anim_sockets'

# True: re-run the batch retarget even when an output already exists. The batch then runs with
# overwrite_existing_files=True. That FORCE-REPLACES references and force-deletes the old asset
# (IKRetargetBatchOperation.cpp:915-960), so the notifies are added again by step 3. Default False.
FORCE = False
# True: re-write socket transforms and notify times even when they already match (logged MODIFIED).
REBUILD = False

DO_SOCKETS = True
DO_RETARGET = False
DO_NOTIFIES = True
DO_NIAGARA_NOTIFIES = True

# Characters
GUARD_SKELETON = '/Game/Guard/Characters/Guard/SKEL_Guard'
GUARD_MESH = '/Game/Guard/Characters/Guard/SK_Guard'
PAWN_BP = '/Game/ThirdPerson/Blueprints/BP_ThirdPersonCharacter'      # setup_guard.py:2
DRIVER_COMPONENT = 'CharacterMesh0'                                   # setup_guard.py:30
# Used only when CharacterMesh0 has no mesh asset or cannot be read. Codex previewed the driver
# with it (Saved/PredictiveIK/mantle_preview.py:17).
DRIVER_MESH_FALLBACK = '/Game/Characters/Mannequins/Meshes/SKM_Manny_Simple'

# Animation and retargeters
SRC_ANIM = '/Game/RamsterZ_FreeAnims_Volume1/AnimationSequence/1HM/1HM_AerialSwing01_2HitCombo'
# The UE4 RamsterZ mesh. This is a SkeletalMesh, unlike /Game/Characters/.../SK_Mannequin, which is a
# Skeleton. It is only a candidate: the source mesh must use the animation's skeleton, checked at runtime.
SRC_MESH_CANDIDATE = '/Game/RamsterZ_FreeAnims_Volume1/Demo/Mannequin/Character/Mesh/SK_Mannequin'
RTG_UE4_TO_MANNY = '/Game/PredictiveIK/Retarget/RTG_TraversalUE4ToManny'
RTG_MANNY_TO_GUARD = '/Game/Guard/Characters/Guard/RTG_Guard'
MANNY_ANIM_NAME = 'AS_Manny_IceSlash_Combo'
GUARD_ANIM_NAME = 'AS_Guard_IceSlash_Combo'
MANNY_ANIM = C.ANIM_DIR + '/' + MANNY_ANIM_NAME
GUARD_ANIM = C.ANIM_DIR + '/' + GUARD_ANIM_NAME

# Sockets.
#   space 'bone':      loc and rot are in parent-bone space. With 'toward', loc is placed instead at
#                      'fraction' of the way from the bone to the 'toward' bone (reference pose), which
#                      gives the palm centre on either hand without guessing per-side bone axes.
#   space 'component': loc is a component-space offset from the bone's reference-pose origin, in the
#                      character frame (X = right, Y = forward, Z = up; UE mesh forward is +Y, tech plan
#                      4.1). If the mesh's detected forward is not +Y, the offset is turned about Z.
#                      'ground': True puts the socket on Z = 0 of the component. rot is a
#                      component-space rotator and is converted to bone space.
SOCKETS = [
    {'name': 'FX_Hand_R', 'bone': 'hand_r', 'space': 'bone', 'toward': 'middle_01_r', 'fraction': 0.5,
     'loc': (0.0, 0.0, 0.0), 'rot': (0.0, 0.0, 0.0)},
    {'name': 'FX_Hand_L', 'bone': 'hand_l', 'space': 'bone', 'toward': 'middle_01_l', 'fraction': 0.5,
     'loc': (0.0, 0.0, 0.0), 'rot': (0.0, 0.0, 0.0)},
    # Tech plan 4.1: spine_03, (0, 32, 8) cm with forward = +Y, rotation (0, 0, 0).
    {'name': 'FX_SlashOrigin', 'bone': 'spine_03', 'space': 'component',
     'loc': (0.0, 32.0, 8.0), 'rot': (0.0, 0.0, 0.0)},
    # Task spec: root, 120 cm forward, at ground. This replaces tech plan 4.1's 165 cm.
    {'name': 'FX_IceBurst', 'bone': 'root', 'space': 'component', 'ground': True,
     'loc': (0.0, 120.0, 0.0), 'rot': (0.0, 0.0, 0.0)},
    {'name': 'FX_CrystalCenter', 'bone': 'root', 'space': 'bone',
     'loc': (0.0, 0.0, 0.0), 'rot': (0.0, 0.0, 0.0)},
    # Canonical single-slash & landing sockets on root (root translates with character steps while root_rot stays 0,0,0):
    {'name': 'FX_SlashSocket', 'bone': 'root', 'space': 'component', 'ground': True,
     'loc': (0.0, 40.0, 105.0), 'rot': (0.0, 0.0, 0.0)},
    {'name': 'FX_LandSocket', 'bone': 'root', 'space': 'component', 'ground': True,
     'loc': (0.0, 50.0, 0.0), 'rot': (0.0, 0.0, 0.0)},
]
# rot tuples are (pitch, yaw, roll) in degrees.

LOC_TOL = 0.05      # cm
ROT_TOL = 1e-4      # rotation-matrix element tolerance
SCALE_TOL = 1e-4

# Notifies
ANIM_NOTIFIES = ['FX_Slash_01', 'FX_Slash_02', 'FX_Slash_03', 'FX_Slash_Impact']
LATE_NOTIFIES = ['FX_IceBurst', 'FX_CrystalReveal', 'FX_End']   # added only when inside the clip
# The data timeline also has FX_Slash_04/05 (arcs 04 and 05). They are not contract notify names, so
# by default the manifest only records them as events for the sequence script (07).
ADD_EXTRA_ARC_NOTIFIES = False
EXTRA_ARC_NOTIFIES = ['FX_Slash_04', 'FX_Slash_05']
NOTIFY_CLASS = '/Script/Engine.AnimNotify'      # name-only skeleton notify (UAnimSequenceService.cpp:1720-1780)
NOTIFY_TRACK_NAME = 'FX'
NOTIFY_TIME_TOL = 1e-3                           # seconds
LENGTH_EPS = 1e-4

EAL = unreal.EditorAssetLibrary
SMES = unreal.SkeletalMeshEditorSubsystem       # static ScriptMethods (SkeletalMeshEditorSubsystem.h:217-237)


# --------------------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------------------
def _pkg(obj_or_path):
    """'/Game/A/B.B' or an object -> '/Game/A/B'."""
    if obj_or_path is None:
        return ''
    s = obj_or_path if isinstance(obj_or_path, str) else obj_or_path.get_path_name()
    return C.package_name(s) or s


def _skeleton_of(asset):
    """Skeleton of a SkeletalMesh or AnimationAsset. Mesh: SkeletalMesh.h:769-770 (BlueprintGetter).
    Anim: AnimationAsset.h:993-994 (VisibleAnywhere)."""
    if asset is None:
        return None
    try:
        return asset.get_editor_property('skeleton')
    except Exception:
        return None


def _vec(v):
    return [round(float(v.x), 4), round(float(v.y), 4), round(float(v.z), 4)]


def _rot(r):
    return {'pitch': round(float(r.pitch), 4), 'yaw': round(float(r.yaw), 4), 'roll': round(float(r.roll), 4)}


def _rot_matrix(pitch, yaw, roll):
    """UE FRotationMatrix rows (RotationMatrix.h). Used only to compare rotators robustly."""
    p, y, r = math.radians(pitch), math.radians(yaw), math.radians(roll)
    sp, cp, sy, cy, sr, cr = math.sin(p), math.cos(p), math.sin(y), math.cos(y), math.sin(r), math.cos(r)
    return [
        (cp * cy, cp * sy, sp),
        (sr * sp * cy - cr * sy, sr * sp * sy + cr * cy, -sr * cp),
        (-(cr * sp * cy + sr * sy), cy * sr - cr * sp * sy, cr * cp),
    ]


def _rot_equal(a, b):
    ma = _rot_matrix(a.pitch, a.yaw, a.roll)
    mb = _rot_matrix(b.pitch, b.yaw, b.roll)
    return all(abs(ma[i][j] - mb[i][j]) <= ROT_TOL for i in range(3) for j in range(3))


def _vec_equal(a, b, tol):
    return abs(a.x - b.x) <= tol and abs(a.y - b.y) <= tol and abs(a.z - b.z) <= tol


def _bone_exists(mesh, bone):
    """SkeletalMeshEditorSubsystem.get_bone_parent returns None both for the root and for a missing bone,
    and get_bone_children returns [] for a missing bone (SkeletalMeshEditorSubsystem.cpp GetBoneParent /
    GetBoneChildren). A bone exists if it has a parent or children; a lone root bone would be missed."""
    try:
        if str(SMES.get_bone_parent(mesh, bone)) != 'None':
            return True
        return len(SMES.get_bone_children(mesh, bone)) > 0
    except Exception:
        return False


def _bone_cs(mesh_path, bone):
    """Reference-pose component-space transform (USkeletonService.cpp:309-335). Identity if the bone is missing."""
    return unreal.SkeletonService.get_bone_transform(mesh_path, bone, True)


# --------------------------------------------------------------------------------------
# Driver mesh discovery
# --------------------------------------------------------------------------------------
def find_driver_mesh(report):
    """Return (mesh, how). The mesh is CharacterMesh0's mesh on BP_ThirdPersonCharacter, read the same
    way setup_guard.py:4-12 read the components; then the CDO 'mesh' component (Character.h:351-352);
    then DRIVER_MESH_FALLBACK."""
    bp = C.load(PAWN_BP)
    if bp is None:
        report.error('pawn blueprint %s not found' % PAWN_BP)
    else:
        try:
            sub = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
            lib = unreal.SubobjectDataBlueprintFunctionLibrary
            for h in sub.k2_gather_subobject_data_for_blueprint(bp):
                o = lib.get_object_for_blueprint(lib.get_data(h), bp)
                if o is not None and o.get_name() == DRIVER_COMPONENT:
                    mesh = o.get_skeletal_mesh_asset()          # SkeletalMeshComponent.h:374-375
                    if mesh is not None:
                        return mesh, 'BP subobject %s' % DRIVER_COMPONENT
                    report.info('%s on %s has no mesh asset' % (DRIVER_COMPONENT, PAWN_BP))
        except Exception as exc:
            report.info('subobject read of %s failed: %s: %s' % (PAWN_BP, type(exc).__name__, exc))
        try:
            cls = EAL.load_blueprint_class(PAWN_BP)              # EditorAssetLibrary.h:48
            cdo = unreal.get_default_object(cls)                 # PyCore.cpp:2596
            comp = cdo.get_editor_property('mesh')
            mesh = comp.get_skeletal_mesh_asset() if comp is not None else None
            if mesh is not None:
                return mesh, 'CDO mesh component'
        except Exception as exc:
            report.info('CDO read of %s failed: %s: %s' % (PAWN_BP, type(exc).__name__, exc))
    mesh = C.load(DRIVER_MESH_FALLBACK)
    if mesh is not None:
        report.todo('driver mesh not readable from %s; using fallback %s. Verify that it is what '
                    'CharacterMesh0 plays at runtime.' % (PAWN_BP, DRIVER_MESH_FALLBACK))
        return mesh, 'fallback constant'
    return None, 'not found'


# --------------------------------------------------------------------------------------
# Step 1: sockets
# --------------------------------------------------------------------------------------
def detect_forward(mesh_path):
    """Forward axis of the mesh from foot->ball in the reference pose. Returns ('+Y', yaw_deg, dx, dy)
    where yaw_deg turns the +Y character frame onto the detected axis."""
    dx = dy = 0.0
    n = 0
    for side in ('l', 'r'):
        f = _bone_cs(mesh_path, 'foot_' + side).translation
        b = _bone_cs(mesh_path, 'ball_' + side).translation
        if abs(b.x - f.x) + abs(b.y - f.y) > 1.0:
            dx += b.x - f.x
            dy += b.y - f.y
            n += 1
    if n == 0:
        return None, 0.0, dx, dy
    if abs(dy) >= abs(dx):
        return ('+Y', 0.0, dx, dy) if dy > 0 else ('-Y', 180.0, dx, dy)
    return ('+X', -90.0, dx, dy) if dx > 0 else ('-X', 90.0, dx, dy)


def _turn_xy(v, yaw_deg):
    a = math.radians(yaw_deg)
    return (v[0] * math.cos(a) - v[1] * math.sin(a), v[0] * math.sin(a) + v[1] * math.cos(a), v[2])


def desired_local(mesh, mesh_path, spec, fwd_yaw):
    """Socket transform in parent-bone space: (Vector, Rotator, Vector scale)."""
    bone = spec['bone']
    bone_cs = _bone_cs(mesh_path, bone)
    pitch, yaw, roll = spec['rot']
    if spec['space'] == 'bone':
        toward = spec.get('toward')
        if toward and _bone_exists(mesh, toward):
            t_cs = _bone_cs(mesh_path, toward)
            a, b, k = bone_cs.translation, t_cs.translation, float(spec.get('fraction', 0.5))
            p_cs = unreal.Vector(a.x + (b.x - a.x) * k, a.y + (b.y - a.y) * k, a.z + (b.z - a.z) * k)
            loc = bone_cs.inverse_transform_location(p_cs)      # KismetMathLibrary.h:4003
        else:
            loc = unreal.Vector(*spec['loc'])
        rot = unreal.Rotator(roll=roll, pitch=pitch, yaw=yaw)
    else:
        off = _turn_xy(spec['loc'], fwd_yaw)
        o = bone_cs.translation
        z = (0.0 + off[2]) if spec.get('ground') else (o.z + off[2])
        p_cs = unreal.Vector(o.x + off[0], o.y + off[1], z)
        loc = bone_cs.inverse_transform_location(p_cs)
        rot_cs = unreal.Rotator(roll=roll, pitch=pitch, yaw=yaw + fwd_yaw)
        rot = bone_cs.inverse_transform_rotation(rot_cs)        # KismetMathLibrary.h:4017
    return loc, rot, unreal.Vector(1.0, 1.0, 1.0)


def socket_copies(mesh, name):
    """{'mesh': [...], 'skeleton': [...]} sockets called `name`. NumSockets/GetSocketByIndex list the mesh's
    own sockets first, then its skeleton's (SkeletalMesh.h:2731-2736). The owner is told apart by the outer."""
    out = {'mesh': [], 'skeleton': []}
    skel = _skeleton_of(mesh)
    skel_path = skel.get_path_name() if skel is not None else ''
    mesh_path = mesh.get_path_name()
    for i in range(mesh.num_sockets()):
        s = mesh.get_socket_by_index(i)
        if s is None or str(s.get_editor_property('socket_name')) != name:
            continue
        outer = s.get_outer().get_path_name()
        if outer == skel_path:
            out['skeleton'].append(s)
        elif outer == mesh_path:
            out['mesh'].append(s)
    return out


def _sync_socket(report, mesh, sock, owner_path, spec, loc, rot, scale):
    """Bring one existing socket copy to the wanted bone and transform. Returns True if it was changed."""
    changes = []
    if str(sock.get_editor_property('bone_name')) != spec['bone']:
        sock.set_socket_parent(mesh, spec['bone'])                 # SkeletalMeshSocket.h:46-47, Modify()s
        if str(sock.get_editor_property('bone_name')) != spec['bone']:
            raise RuntimeError('set_socket_parent(%s) did not take on %s' % (spec['bone'], owner_path))
        changes.append('bone->' + spec['bone'])
    cur = sock.get_socket_local_transform()                       # SkeletalMeshSocket.h:61-62
    same = (_vec_equal(sock.get_editor_property('relative_location'), loc, LOC_TOL)
            and _rot_equal(sock.get_editor_property('relative_rotation'), rot)
            and _vec_equal(sock.get_editor_property('relative_scale'), scale, SCALE_TOL))
    if REBUILD or not same:
        # SetSocketLocalTransform calls Modify() so the owning package is dirtied (SkeletalMesh.cpp:7469-7478).
        sock.set_socket_local_transform(unreal.Transform(location=loc, rotation=rot, scale=scale))
        changes.append('transform %s/%s -> %s/%s' % (
            _vec(cur.translation), _rot(sock.get_editor_property('relative_rotation')) if False else '',
            _vec(loc), _rot(rot)))
    if changes:
        report.modified(owner_path, 'socket %s: %s' % (spec['name'], '; '.join(changes)))
        return True
    return False


def ensure_socket(report, mesh, spec, loc, rot, scale):
    """Make sure SKELETON socket spec['name'] exists with the wanted bone and transform. Returns a record."""
    mesh_path = _pkg(mesh)
    skel_path = _pkg(_skeleton_of(mesh))
    name = spec['name']
    copies = socket_copies(mesh, name)
    rec = {'bone': spec['bone'], 'location': _vec(loc), 'rotation': _rot(rot), 'scale': _vec(scale),
           'on_skeleton': False, 'mesh_copy': False, 'action': 'skipped'}

    if copies['skeleton']:
        changed = False
        for s in copies['skeleton']:
            changed |= _sync_socket(report, mesh, s, skel_path, spec, loc, rot, scale)
        for s in copies['mesh']:
            changed |= _sync_socket(report, mesh, s, mesh_path, spec, loc, rot, scale)
        if len(copies['skeleton']) > 1 or len(copies['mesh']) > 1:
            report.todo('socket %s has duplicates (skeleton %d, mesh %d) on %s; delete the extras by hand' % (
                name, len(copies['skeleton']), len(copies['mesh']), mesh_path))
        if not changed:
            report.skipped('%s:%s' % (skel_path, name), 'socket matches')
        rec.update(on_skeleton=True, mesh_copy=bool(copies['mesh']), action='modified' if changed else 'skipped')
        return rec

    if copies['mesh']:
        # Mesh-only socket (e.g. made with the toolset AddSocket per tech plan 4.1). It cannot be
        # promoted without RemoveSocket+add, and RemoveSocket deletes it (remove-and-recreate is not
        # allowed). It still works at runtime on this mesh, so keep it in sync and leave a TODO.
        changed = False
        for s in copies['mesh']:
            changed |= _sync_socket(report, mesh, s, mesh_path, spec, loc, rot, scale)
        if not changed:
            report.skipped('%s:%s' % (mesh_path, name), 'mesh-only socket matches')
        report.todo('socket %s exists only on mesh %s, not on skeleton %s. Promote it in the Skeleton '
                    'editor if other meshes need it.' % (name, mesh_path, skel_path))
        rec.update(mesh_copy=True, action='mesh_only_' + ('modified' if changed else 'skipped'))
        return rec

    # Create: new socket owned by the mesh (AddSocket requires Outer == mesh, SkeletalMesh.cpp:5165-5170),
    # parent + transform first so the skeleton duplicate copies them (SkeletalMesh.cpp:5224-5238).
    sock = unreal.new_object(unreal.SkeletalMeshSocket, outer=mesh)
    sock.set_socket_parent(mesh, spec['bone'])
    sock.set_socket_local_transform(unreal.Transform(location=loc, rotation=rot, scale=scale))
    mesh.add_socket(sock, True)                                   # SkeletalMesh.h:2704-2705
    auto_name = str(sock.get_editor_property('socket_name'))      # AddSocket names it 'Socket'/'Socket_N'
    if auto_name in ('', 'None') or not any(
            s.get_path_name() == sock.get_path_name()
            for s in [mesh.get_socket_by_index(i) for i in range(mesh.num_sockets())] if s is not None):
        raise RuntimeError('add_socket refused %s on %s (bone %s missing from skeleton?) - see Output Log '
                           'LogSkeletalMesh' % (name, mesh_path, spec['bone']))
    if auto_name != name:
        if not SMES.rename_socket(mesh, auto_name, name):        # renames mesh + skeleton copies (:607-694)
            raise RuntimeError('rename_socket %s -> %s failed on %s' % (auto_name, name, mesh_path))
    after = socket_copies(mesh, name)
    if not after['skeleton']:
        raise RuntimeError('socket %s added but no skeleton copy found on %s' % (name, skel_path))
    report.modified(skel_path, 'socket %s added on %s' % (name, spec['bone']))
    report.modified(mesh_path, 'socket %s mesh copy (USkeletalMesh::AddSocket keeps one)' % name)
    print('CREATED: socket %s on %s (bone %s, loc %s, rot %s)' % (name, skel_path, spec['bone'], _vec(loc), _rot(rot)))
    rec.update(on_skeleton=True, mesh_copy=bool(after['mesh']), action='created')
    return rec


def sockets_for_mesh(report, mesh, label):
    """Apply SOCKETS to the skeleton of `mesh`. Returns a manifest record."""
    mesh_path = _pkg(mesh)
    skel = _skeleton_of(mesh)
    rec = {'mesh_used': mesh_path, 'skeleton': _pkg(skel), 'sockets': {}}
    if skel is None:
        report.error('%s: mesh %s has no skeleton' % (label, mesh_path))
        return rec
    axis, fwd_yaw, dx, dy = detect_forward(mesh_path)
    if axis is None:
        report.info('%s: forward axis not detectable (no foot/ball bones); assuming +Y' % label)
        axis, fwd_yaw = '+Y', 0.0
    else:
        report.info('%s: forward axis %s (foot->ball dx=%.1f dy=%.1f cm)' % (label, axis, dx, dy))
    if axis != '+Y':
        report.todo('%s: mesh forward is %s, not +Y. Component-space socket offsets were turned %.0f deg; '
                    'check the slash arcs attach frame in step 06.' % (label, axis, fwd_yaw))
    rec['forward_axis'] = axis
    for spec in SOCKETS:
        try:
            if not _bone_exists(mesh, spec['bone']):
                report.error('%s: bone %s missing on %s; socket %s not made' % (
                    label, spec['bone'], mesh_path, spec['name']))
                continue
            loc, rot, scale = desired_local(mesh, mesh_path, spec, fwd_yaw)
            rec['sockets'][spec['name']] = ensure_socket(report, mesh, spec, loc, rot, scale)
        except Exception as exc:  # noqa: BLE001
            report.error('%s: socket %s' % (label, spec['name']), exc)
    # Evidence: every socket the mesh now resolves (its own plus its skeleton's).
    try:
        names = []
        for i in range(mesh.num_sockets()):
            s = mesh.get_socket_by_index(i)
            if s is not None:
                names.append('%s@%s' % (s.get_editor_property('socket_name'), _pkg(s.get_outer()).rsplit('/', 1)[-1]))
        print('SOCKETS: %s %s' % (mesh_path, names))
    except Exception as exc:  # noqa: BLE001
        report.info('socket listing failed on %s: %s' % (mesh_path, exc))
    return rec


def step_sockets(report, driver_mesh):
    out = {}
    guard_mesh = C.load(GUARD_MESH)
    if guard_mesh is None:
        report.error('Guard mesh %s not found' % GUARD_MESH)
    else:
        gskel = _pkg(_skeleton_of(guard_mesh))
        if gskel != GUARD_SKELETON:
            report.error('%s uses skeleton %s, expected %s' % (GUARD_MESH, gskel, GUARD_SKELETON))
        else:
            out[GUARD_SKELETON] = sockets_for_mesh(report, guard_mesh, 'SKEL_Guard')
    if driver_mesh is None:
        report.error('driver mesh unknown; driver skeleton sockets not made')
    else:
        dskel = _pkg(_skeleton_of(driver_mesh))
        if dskel in out:
            report.skipped(dskel, 'driver skeleton is SKEL_Guard; sockets already handled')
        elif dskel:
            out[dskel] = sockets_for_mesh(report, driver_mesh, 'driver skeleton')
        else:
            report.error('driver mesh %s has no skeleton' % _pkg(driver_mesh))
    return out


# --------------------------------------------------------------------------------------
# Step 2: retarget
# --------------------------------------------------------------------------------------
def _rtg_info(rtg):
    """Source/target IK rigs and preview meshes (IKRetargeterController.h:130-160, IKRigController.h:136-146)."""
    ctrl = unreal.IKRetargeterController.get_controller(rtg)
    info = {'controller': ctrl}
    for key, side in (('source', unreal.RetargetSourceOrTarget.SOURCE), ('target', unreal.RetargetSourceOrTarget.TARGET)):
        rig = ctrl.get_ik_rig(side)
        rig_mesh = None
        if rig is not None:
            try:
                rig_mesh = unreal.IKRigController.get_controller(rig).get_skeletal_mesh()
            except Exception:
                rig_mesh = None
        info[key + '_rig'] = rig
        info[key + '_rig_mesh'] = rig_mesh
        info[key + '_preview'] = ctrl.get_preview_mesh(side)
    return info


def _describe_rtg(path, info):
    def p(o):
        return _pkg(o) if o is not None else None

    def sk(o):
        return _pkg(_skeleton_of(o)) if o is not None else None
    return {
        'path': path,
        'source_rig': p(info['source_rig']), 'target_rig': p(info['target_rig']),
        'source_rig_mesh': p(info['source_rig_mesh']), 'source_rig_mesh_skeleton': sk(info['source_rig_mesh']),
        'target_rig_mesh': p(info['target_rig_mesh']), 'target_rig_mesh_skeleton': sk(info['target_rig_mesh']),
        'source_preview': p(info['source_preview']), 'target_preview': p(info['target_preview']),
    }


def _pick_mesh_for_skeleton(candidates, skel_path):
    for m in candidates:
        if m is not None and isinstance(m, unreal.SkeletalMesh) and _pkg(_skeleton_of(m)) == skel_path:
            return m
    return None


def retarget_hop(report, label, src_anim_path, out_name, rtg_path, src_mesh_candidates, tgt_mesh, hop_rec):
    """One batch retarget into C.ANIM_DIR/out_name. Returns the output path or None."""
    out_path = C.ANIM_DIR + '/' + out_name
    hop_rec.update({'output': out_path, 'retargeter': rtg_path, 'source_anim': src_anim_path})
    if C.asset_exists(out_path) and not FORCE:
        report.skipped(out_path, 'retarget output exists (FORCE = False)')
        hop_rec['action'] = 'skipped'
        return out_path

    anim = C.load(src_anim_path)
    if anim is None:
        report.error('%s: source animation %s not found' % (label, src_anim_path))
        return None
    anim_skel = _pkg(_skeleton_of(anim))
    rtg = C.load(rtg_path)
    if rtg is None:
        report.error('%s: retargeter %s not found. Create an IK Retargeter from the IK Rig of %s to the IK Rig '
                     'of %s and set rtg path in CONFIG; nothing was fabricated.' % (
                         label, rtg_path, anim_skel, _pkg(_skeleton_of(tgt_mesh))))
        return None
    info = _rtg_info(rtg)
    hop_rec['rtg'] = _describe_rtg(rtg_path, info)
    print('RTG: %s %s' % (label, hop_rec['rtg']))

    src_mesh = _pick_mesh_for_skeleton(
        list(src_mesh_candidates) + [info['source_preview'], info['source_rig_mesh']], anim_skel)
    if src_mesh is None:
        report.error('%s: no SkeletalMesh found that uses the animation skeleton %s (tried %s, the RTG source '
                     'preview mesh and source IK rig mesh). Set a source mesh for that skeleton.' % (
                         label, anim_skel, [_pkg(m) for m in src_mesh_candidates if m is not None]))
        return None
    if tgt_mesh is None:
        report.error('%s: target mesh unknown' % label)
        return None
    hop_rec.update({'source_mesh': _pkg(src_mesh), 'target_mesh': _pkg(tgt_mesh),
                    'source_skeleton': anim_skel, 'target_skeleton': _pkg(_skeleton_of(tgt_mesh))})

    # Rig/mesh compatibility evidence (IKRigController.h:148-150), then the full readiness check.
    for key, mesh in (('source_rig', src_mesh), ('target_rig', tgt_mesh)):
        rig = info[key]
        if rig is None:
            report.error('%s: %s has no %s' % (label, rtg_path, key.replace('_', ' ')))
            return None
        try:
            ok = unreal.IKRigController.get_controller(rig).is_skeletal_mesh_compatible(mesh)
            hop_rec[key + '_compatible'] = bool(ok)
            if not ok:
                report.info('%s: %s %s reports %s as incompatible' % (label, key, _pkg(rig), _pkg(mesh)))
        except Exception as exc:  # noqa: BLE001
            report.info('%s: is_skeletal_mesh_compatible failed: %s' % (label, exc))
    rep = info['controller'].validate_retargeter(src_mesh, tgt_mesh)   # IKRetargeterController.h:158-170
    hop_rec['validation'] = {'is_ready': bool(rep.is_ready), 'errors': [str(e) for e in rep.errors],
                             'warnings': [str(w) for w in rep.warnings],
                             'ops_that_cannot_run': [str(o) for o in rep.ops_that_cannot_run]}
    print('VALIDATE: %s %s' % (label, hop_rec['validation']))
    if not rep.is_ready:
        report.error('%s: %s cannot retarget %s -> %s: %s %s. Fix the IK Rigs of this retargeter (or make a '
                     'new one between these skeletons); nothing was fabricated.' % (
                         label, rtg_path, _pkg(src_mesh), _pkg(tgt_mesh), list(rep.errors), list(rep.ops_that_cannot_run)))
        return None

    C.ensure_dir(C.ANIM_DIR)
    src_name = src_anim_path.rsplit('/', 1)[-1]
    inputs = unreal.IKRetargetBatchOperationInputs()             # IKRetargetBatchOperation.h:116-177
    settings = {
        'assets_to_retarget': [EAL.find_asset_data(src_anim_path)],
        'source_mesh': src_mesh,
        'target_mesh': tgt_mesh,
        'ik_retarget_asset': rtg,
        'search': src_name,
        'replace': out_name,
        'prefix': '',
        'suffix': '',
        'target_path': C.ANIM_DIR,                               # no trailing slash (EditorAnimUtils.cpp:480-482)
        'use_source_path': False,
        'include_referenced_assets': False,
        'overwrite_existing_files': bool(FORCE),
        'retain_additive_flags': True,
    }
    for k, v in settings.items():
        inputs.set_editor_property(k, v)
    if FORCE and C.asset_exists(out_path):
        print('WARN: FORCE: %s will be replaced by the batch (ForceReplaceReferences + ForceDelete, '
              'IKRetargetBatchOperation.cpp:915-960)' % out_path)
    results = unreal.IKRetargetBatchOperation.run_batch_retarget_with_results(inputs)  # raises on total failure
    produced = []
    for r in results:
        status = r.status
        line = '%s %s -> %s %s' % (status, r.source_asset.package_name, r.retargeted_asset.package_name, r.reason)
        if status == unreal.IKRetargetBatchAssetStatus.RETARGETED:
            produced.append(str(r.retargeted_asset.package_name))
            print('RETARGET: ' + line)
        else:
            report.error('%s: batch result %s' % (label, line))
    hop_rec['batch_outputs'] = produced

    # Contract name: Search/Replace already produces it. Only a name clash would give '..._1'.
    if C.asset_exists(out_path) and (out_path in produced or FORCE):
        report.created(out_path)
    elif not C.asset_exists(out_path):
        got = [p for p in produced if C.asset_exists(p)]
        if len(got) == 1:
            if EAL.rename_asset(got[0], out_path):              # EditorAssetLibrary.h:209 (fixes references)
                report.created(out_path)
                report.info('renamed %s -> %s' % (got[0], out_path))
            else:
                report.error('%s: rename %s -> %s failed' % (label, got[0], out_path))
                return None
        else:
            report.error('%s: expected %s after the batch, got %s' % (label, out_path, produced))
            return None
    else:
        report.error('%s: %s already existed and the batch wrote %s instead (FORCE off?)' % (label, out_path, produced))
        return None
    hop_rec['action'] = 'created'
    return out_path


def describe_anim(path):
    S = unreal.AnimSequenceService                               # UAnimSequenceService.h:693-730, 1382-1401
    rec = {'path': path}
    for key, fn in (('length_s', S.get_animation_length), ('fps', S.get_animation_frame_rate),
                    ('frames', S.get_animation_frame_count), ('skeleton', S.get_animation_skeleton),
                    ('enable_root_motion', S.get_enable_root_motion), ('root_lock', S.get_root_motion_root_lock)):
        try:
            v = fn(path)
            rec[key] = v if isinstance(v, (int, float, bool)) else str(v)
        except Exception as exc:  # noqa: BLE001
            rec[key] = 'n/a (%s)' % exc
    return rec


def step_retarget(report, driver_mesh, anim_rec):
    guard_mesh = C.load(GUARD_MESH)
    src_cand = C.load(SRC_MESH_CANDIDATE)
    if src_cand is not None and not isinstance(src_cand, unreal.SkeletalMesh):
        report.info('%s is a %s, not a SkeletalMesh; ignored as source mesh' % (SRC_MESH_CANDIDATE, type(src_cand).__name__))
        src_cand = None
    anim_rec['source'] = describe_anim(SRC_ANIM)
    print('ANIM: source %s' % anim_rec['source'])

    hop1 = {}
    anim_rec['hops'] = {'ue4_to_manny': hop1}
    manny = None
    try:
        manny = retarget_hop(report, 'UE4->Manny', SRC_ANIM, MANNY_ANIM_NAME, RTG_UE4_TO_MANNY,
                             [src_cand], driver_mesh, hop1)
    except Exception as exc:  # noqa: BLE001
        report.error('UE4->Manny batch retarget', exc)
    if manny and driver_mesh is not None:
        got = _pkg(_skeleton_of(C.load(manny)))
        want = _pkg(_skeleton_of(driver_mesh))
        if got != want:
            report.error('%s has skeleton %s but the driver mesh uses %s' % (manny, got, want))

    hop2 = {}
    anim_rec['hops']['manny_to_guard'] = hop2
    guard = None
    if manny is None:
        report.error('Manny->Guard skipped: no %s' % MANNY_ANIM)
    else:
        try:
            guard = retarget_hop(report, 'Manny->Guard', manny, GUARD_ANIM_NAME, RTG_MANNY_TO_GUARD,
                                 [driver_mesh], guard_mesh, hop2)
        except Exception as exc:  # noqa: BLE001
            report.error('Manny->Guard batch retarget', exc)
        if guard:
            got = _pkg(_skeleton_of(C.load(guard)))
            if got != GUARD_SKELETON:
                report.error('%s has skeleton %s, expected %s' % (guard, got, GUARD_SKELETON))

    outs = {}
    for key, path in (('manny', manny), ('guard', guard)):
        if path:
            outs[key] = describe_anim(path)
            print('ANIM: %s %s' % (key, outs[key]))
            if outs[key].get('enable_root_motion') is False:
                report.info('%s: root motion disabled; the root track keeps its translation, which is what '
                            'the arcs were fitted to (data notes)' % path)
    anim_rec['outputs'] = outs
    return manny, guard


# --------------------------------------------------------------------------------------
# Step 3: notifies
# --------------------------------------------------------------------------------------
def notify_plan(data, fps):
    """[(event, sequence_time_s, anim_time_s)] for every timeline event."""
    offset = float(data['anim_start_offset_s'])
    plan = []
    for ev in data.get('timeline', []):
        t_seq = float(ev['time_s'])
        t = t_seq - offset
        if fps > 0:
            f = t * fps
            if abs(f - round(f)) < 0.05:                         # data times are rounded to 1e-4 s
                t = round(f) / fps
        plan.append((str(ev['event']), t_seq, t))
    return plan


def ensure_track(report, path):
    anim = C.load(path)
    names = unreal.AnimationLibrary.get_animation_notify_track_names(anim)   # AnimationBlueprintLibrary.h:295
    if names:
        return
    # A notify on track 0 with no tracks trips an ensure in RefreshCacheData (AnimSequenceBase.cpp:676-692).
    unreal.AnimationLibrary.add_animation_notify_track(anim, NOTIFY_TRACK_NAME, unreal.LinearColor(0.3, 0.8, 1.0, 1.0))
    anim.modify()                                                # AddAnimationNotifyTrack does not dirty
    report.modified(path, 'notify track %s added' % NOTIFY_TRACK_NAME)


def ensure_notify(report, path, name, t):
    S = unreal.AnimSequenceService
    hits = [n for n in S.list_notifies(path) if str(n.notify_name) == name]
    if len(hits) > 1:
        report.todo('%s has %d notifies named %s; only the first is managed' % (path, len(hits), name))
    if hits:
        cur = float(hits[0].trigger_time)
        if abs(cur - t) <= NOTIFY_TIME_TOL and not REBUILD:
            report.skipped('%s:%s' % (path, name), 'notify at %.4f s' % cur)
            return 'skipped'
        if not S.set_notify_trigger_time(path, hits[0].notify_index, t):   # in place, no remove+add
            raise RuntimeError('set_notify_trigger_time %s failed' % name)
        report.modified(path, 'notify %s %.4f -> %.4f s' % (name, cur, t))
        return 'modified'
    idx = S.add_notify(path, NOTIFY_CLASS, t, name)
    if idx < 0:
        raise RuntimeError('add_notify %s at %.4f returned %d' % (name, t, idx))
    check = [n for n in S.list_notifies(path) if str(n.notify_name) == name]   # indices shift after sorting
    if not check:
        raise RuntimeError('notify %s not found after add_notify' % name)
    report.modified(path, 'notify %s added at %.4f s' % (name, float(check[0].trigger_time)))
    print('CREATED: notify %s on %s at %.4f s' % (name, path, float(check[0].trigger_time)))
    return 'created'


def step_notifies(report, data, anim_paths, anim_rec):
    wanted = list(ANIM_NOTIFIES) + list(LATE_NOTIFIES) + (list(EXTRA_ARC_NOTIFIES) if ADD_EXTRA_ARC_NOTIFIES else [])
    per_anim = {}
    sequence_events = {}
    for path in anim_paths:
        S = unreal.AnimSequenceService
        length = float(S.get_animation_length(path))
        fps = float(S.get_animation_frame_rate(path))
        plan = notify_plan(data, fps)
        rec = {'length_s': length, 'fps': fps, 'notifies': {}}
        per_anim[path] = rec
        try:
            ensure_track(report, path)
        except Exception as exc:  # noqa: BLE001
            report.error('notify track on %s' % path, exc)
        planned = {e for e, _, _ in plan}
        for name in ANIM_NOTIFIES:
            if name not in planned:
                report.error('timeline in %s has no event %s' % (C.DATA_PATH, name))
        for event, t_seq, t in plan:
            inside = (-LENGTH_EPS <= t <= length + LENGTH_EPS)
            if event in wanted and inside:
                try:
                    action = ensure_notify(report, path, event, min(max(t, 0.0), length))
                    rec['notifies'][event] = {'anim_time_s': round(t, 5), 'sequence_time_s': t_seq, 'action': action}
                except Exception as exc:  # noqa: BLE001
                    report.error('notify %s on %s' % (event, path), exc)
                continue
            if event in ANIM_NOTIFIES:
                report.error('%s at anim time %.4f is outside %s (length %.4f)' % (event, t, path, length))
            why = ('anim time %.4f outside clip length %.4f' % (t, length)) if not inside else 'not an anim notify by contract'
            sequence_events[event] = {'sequence_time_s': t_seq, 'anim_time_s': round(t, 5), 'reason': why}
    for event, ev in sorted(sequence_events.items(), key=lambda kv: kv[1]['sequence_time_s']):
        print('SEQUENCE_EVENT: %s at %.4f s (%s)' % (event, ev['sequence_time_s'], ev['reason']))
    anim_rec['notifies'] = per_anim
    anim_rec['sequence_events'] = sequence_events
    anim_rec['anim_start_offset_s'] = float(data['anim_start_offset_s'])
    anim_rec['arc_reveal'] = data.get('arc_reveal')


NIAGARA_NOTIFY_TRACK = 'VFX_Niagara'
NIAGARA_NOTIFY_SPECS = [
    # (label, frame_30fps, system_name, socket_name, attached, loc_xyz, rot_rpy, scale_xyz)
    ('Slash_01_Diagonal', 14, 'NS_IceSlash_Slash', 'FX_SlashSocket', True,
     (0.0, -25.0, 42.0), (-12.0, -22.0, 0.0), (0.96, 0.96, 0.96)),
    ('Slash_02_SpinCut', 25, 'NS_IceSlash_Slash', 'FX_SlashSocket', True,
     (-12.0, -15.0, 8.0), (0.0, 158.0, -6.0), (1.00, 1.00, 1.00)),
    ('Slash_03_Uppercut', 32, 'NS_IceSlash_Slash', 'FX_SlashSocket', True,
     (22.0, -30.0, 52.0), (-14.0, -76.0, 12.0), (0.90, 0.90, 0.90)),
    ('Slash_04_OverheadSlam', 39, 'NS_IceSlash_Slash', 'FX_SlashSocket', True,
     (16.0, -10.0, 52.0), (-16.0, 74.0, -16.0), (0.98, 0.98, 0.98)),
]


def step_niagara_notifies(report, anim_paths, anim_rec):
    """Bind AnimNotify_PlayNiagaraEffect directly onto FX_SlashSocket / FX_LandSocket inside the AnimSequences."""
    AL = unreal.AnimationLibrary
    out_summary = {}
    for path in anim_paths:
        anim = C.load(path)
        if anim is None:
            report.error('cannot load %s for Niagara notifies' % path)
            continue
        track_names = [str(n) for n in AL.get_animation_notify_track_names(anim)]
        if NIAGARA_NOTIFY_TRACK not in track_names:
            AL.add_animation_notify_track(anim, NIAGARA_NOTIFY_TRACK, unreal.LinearColor(0.2, 0.9, 1.0, 1.0))
            anim.modify()
            report.modified(path, 'added notify track %s' % NIAGARA_NOTIFY_TRACK)

        # Cleanly rebuild the VFX_Niagara track events idempotently if count/times differ or REBUILD is set
        AL.remove_animation_notify_events_by_track(anim, NIAGARA_NOTIFY_TRACK)
        added_rows = []
        for label, frame_idx, sys_name, sock_name, attached, loc_xyz, rot_rpy, scale_xyz in NIAGARA_NOTIFY_SPECS:
            sys_path = '%s/%s' % (C.NS_DIR, sys_name)
            ns_obj = C.load(sys_path)
            if ns_obj is None:
                report.error('%s: missing NiagaraSystem %s' % (path, sys_path))
                continue
            t_sec = round(float(frame_idx) / 30.0, 6)
            notify_obj = AL.add_animation_notify_event(
                anim, NIAGARA_NOTIFY_TRACK, t_sec, unreal.AnimNotify_PlayNiagaraEffect
            )
            if notify_obj is None:
                report.error('%s: add_animation_notify_event returned None for %s' % (path, label))
                continue
            notify_obj.modify()
            notify_obj.set_editor_property('template', ns_obj)
            notify_obj.set_editor_property('socket_name', sock_name)
            notify_obj.set_editor_property('attached', bool(attached))
            notify_obj.set_editor_property('location_offset', unreal.Vector(*loc_xyz))
            notify_obj.set_editor_property(
                'rotation_offset',
                unreal.Rotator(roll=float(rot_rpy[0]), pitch=float(rot_rpy[1]), yaw=float(rot_rpy[2]))
            )
            notify_obj.set_editor_property('scale', unreal.Vector(*scale_xyz))
            notify_obj.set_editor_property('absolute_scale', False)
            notify_obj.set_editor_property('should_fire_in_editor', True)
            added_rows.append({
                'label': label,
                'frame': frame_idx,
                'time_s': round(t_sec, 4),
                'system': sys_path,
                'socket': sock_name,
                'attached': bool(attached),
                'location_offset': list(loc_xyz),
                'rotation_offset_rpy': list(rot_rpy),
                'scale': list(scale_xyz),
            })
        anim.modify()
        EAL.save_asset(path, False)
        report.modified(path, 'configured %d AnimNotify_PlayNiagaraEffect events on %s' % (len(added_rows), NIAGARA_NOTIFY_TRACK))
        out_summary[path] = added_rows
    anim_rec['niagara_notifies'] = out_summary



# --------------------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------------------
def main():
    report = C.Report(SCRIPT_NAME)
    anim_rec = {'source_anim': SRC_ANIM, 'manny_anim': MANNY_ANIM, 'guard_anim': GUARD_ANIM, 'force': FORCE}
    sockets_rec = {}
    data = None
    try:
        data = C.load_data()
    except Exception as exc:  # noqa: BLE001
        report.error('load data', exc)

    driver_mesh = None
    try:
        driver_mesh, how = find_driver_mesh(report)
        if driver_mesh is not None:
            report.info('driver mesh %s (skeleton %s) via %s' % (
                _pkg(driver_mesh), _pkg(_skeleton_of(driver_mesh)), how))
            anim_rec['driver_mesh'] = _pkg(driver_mesh)
            anim_rec['driver_skeleton'] = _pkg(_skeleton_of(driver_mesh))
            anim_rec['driver_mesh_source'] = how
        else:
            report.error('driver mesh not found (%s / %s)' % (PAWN_BP, DRIVER_MESH_FALLBACK))
    except Exception as exc:  # noqa: BLE001
        report.error('find driver mesh', exc)

    if DO_SOCKETS:
        try:
            sockets_rec = step_sockets(report, driver_mesh)
        except Exception as exc:  # noqa: BLE001
            report.error('sockets', exc)

    manny = guard = None
    if DO_RETARGET:
        try:
            manny, guard = step_retarget(report, driver_mesh, anim_rec)
        except Exception as exc:  # noqa: BLE001
            report.error('retarget', exc)
    else:
        manny = MANNY_ANIM if C.asset_exists(MANNY_ANIM) else None
        guard = GUARD_ANIM if C.asset_exists(GUARD_ANIM) else None

    if DO_NOTIFIES and data is not None:
        paths = [p for p in (manny, guard) if p and C.asset_exists(p)]
        if not paths:
            report.error('no retargeted animation to put notifies on')
        try:
            step_notifies(report, data, paths, anim_rec)
        except Exception as exc:  # noqa: BLE001
            report.error('notifies', exc)
        if DO_NIAGARA_NOTIFIES:
            try:
                step_niagara_notifies(report, paths, anim_rec)
            except Exception as exc:  # noqa: BLE001
                report.error('niagara_notifies', exc)

    try:
        C.update_manifest('sockets', {
            'definitions': [{k: v for k, v in s.items()} for s in SOCKETS],
            'skeletons': sockets_rec,
            'note': 'Skeleton sockets; USkeletalMesh::AddSocket(..., True) also leaves an identical mesh copy '
                    'on the mesh used to add them.',
        })
        C.update_manifest('anim', anim_rec)
    except Exception as exc:  # noqa: BLE001
        report.error('manifest', exc)

    try:
        C.save_all(report)
    except Exception as exc:  # noqa: BLE001
        report.error('save_all', exc)
    print('DIRTY_AFTER: %s' % [str(p) for p in unreal.PythonTools.get_dirty_packages(False)])   # PythonTools.h:75
    report.finish()


if __name__ == '__main__':
    main()
