"""Template script: Add anti-spin FX_SlashSocket on `root` and bind AnimNotify_PlayNiagaraEffect events.

Run inside UE 5.9 via `execute_python` after customizing CONFIG below.
"""

import unreal

# --- CONFIG ---
MESH_PATH = '/Game/Guard/Characters/Guard/SK_Guard'
ANIM_PATH = '/Game/VFX/IceSlash/Anims/AS_Guard_IceSlash_Combo'
SLASH_SYSTEM_PATH = '/Game/VFX/IceSlash/Niagara/NS_IceSlash_Slash'
SOCKET_NAME = 'FX_SlashSocket'
NOTIFY_TRACK = 'VFX_Niagara'
FPS = 30.0

# (label, frame_at_fps, loc_offset_xyz, rot_offset_roll_pitch_yaw, scale_xyz)
SLASH_NOTIFY_SPECS = [
    ('Slash_01_Diagonal',     14, (0.0, -25.0, 42.0),  (-12.0, -22.0, 0.0),  (0.96, 0.96, 0.96)),
    ('Slash_02_ReverseCut',   25, (-12.0, -15.0, 8.0), (0.0, 158.0, -6.0),   (1.00, 1.00, 1.00)),
    ('Slash_03_Uppercut',     32, (22.0, -30.0, 52.0), (-14.0, -76.0, 12.0), (0.90, 0.90, 0.90)),
    ('Slash_04_OverheadSlam', 39, (16.0, -10.0, 52.0), (-16.0, 74.0, -16.0), (0.98, 0.98, 0.98)),
]


def ensure_root_slash_socket(mesh_path: str, socket_name: str, comp_offset=(0.0, 40.0, 105.0)):
    mesh = unreal.load_asset(mesh_path)
    if mesh is None:
        raise RuntimeError(f'Missing SkeletalMesh: {mesh_path}')
    bone_cs = unreal.SkeletonService.get_bone_transform(mesh_path, 'root', True)
    target_cs = unreal.Vector(bone_cs.translation.x + comp_offset[0],
                              bone_cs.translation.y + comp_offset[1],
                              comp_offset[2])
    local_loc = bone_cs.inverse_transform_location(target_cs)
    local_rot = bone_cs.inverse_transform_rotation(unreal.Rotator(0.0, 0.0, 0.0))
    xf = unreal.Transform(location=local_loc, rotation=local_rot, scale=unreal.Vector(1.0, 1.0, 1.0))

    found = False
    for i in range(mesh.num_sockets()):
        s = mesh.get_socket_by_index(i)
        if s is not None and str(s.get_editor_property('socket_name')) == socket_name:
            s.set_socket_parent(mesh, 'root')
            s.set_socket_local_transform(xf)
            found = True

    if not found:
        sock = unreal.new_object(unreal.SkeletalMeshSocket, outer=mesh)
        sock.set_socket_parent(mesh, 'root')
        sock.set_socket_local_transform(xf)
        mesh.add_socket(sock, True)
        auto_name = str(sock.get_editor_property('socket_name'))
        if auto_name != socket_name:
            unreal.SkeletalMeshEditorSubsystem.rename_socket(mesh, auto_name, socket_name)

    skel = mesh.get_editor_property('skeleton')
    unreal.EditorAssetLibrary.save_asset(mesh_path, False)
    if skel is not None:
        unreal.EditorAssetLibrary.save_asset(skel.get_path_name().split('.')[0], False)


def bind_niagara_slash_notifies(anim_path: str, ns_path: str, track_name: str, specs):
    anim = unreal.load_asset(anim_path)
    ns_obj = unreal.load_asset(ns_path)
    if anim is None or ns_obj is None:
        raise RuntimeError(f'Missing asset: anim={anim} ns={ns_obj}')

    al = unreal.AnimationLibrary
    tracks = [str(t) for t in al.get_animation_notify_track_names(anim)]
    if track_name not in tracks:
        al.add_animation_notify_track(anim, track_name, unreal.LinearColor(0.2, 0.9, 1.0, 1.0))
        anim.modify()

    al.remove_animation_notify_events_by_track(anim, track_name)
    for _label, frame_idx, loc_xyz, rot_rpy, scl_xyz in specs:
        t_sec = round(float(frame_idx) / FPS, 6)
        ev = al.add_animation_notify_event(anim, track_name, t_sec, unreal.AnimNotify_PlayNiagaraEffect)
        ev.modify()
        ev.set_editor_property('template', ns_obj)
        ev.set_editor_property('socket_name', SOCKET_NAME)
        ev.set_editor_property('attached', True)
        ev.set_editor_property('location_offset', unreal.Vector(*loc_xyz))
        ev.set_editor_property('rotation_offset', unreal.Rotator(roll=rot_rpy[0], pitch=rot_rpy[1], yaw=rot_rpy[2]))
        ev.set_editor_property('scale', unreal.Vector(*scl_xyz))
        ev.set_editor_property('absolute_scale', False)
        ev.set_editor_property('should_fire_in_editor', True)

    anim.modify()
    unreal.EditorAssetLibrary.save_asset(anim_path, False)


ensure_root_slash_socket(MESH_PATH, SOCKET_NAME)
bind_niagara_slash_notifies(ANIM_PATH, SLASH_SYSTEM_PATH, NOTIFY_TRACK, SLASH_NOTIFY_SPECS)
print('DONE: Socket + AnimNotify_PlayNiagaraEffect bound and saved.')
