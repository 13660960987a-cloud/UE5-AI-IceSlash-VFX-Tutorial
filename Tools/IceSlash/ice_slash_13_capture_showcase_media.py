"""IceSlash step 13: Deterministic capture of upgraded flat Z=0 + Blade_OuterGlow + target-hit-only NS_IceSlash_Hit showcase media using UE5's built-in Manny robot."""
import asyncio
import os
import shutil
import unreal

EAL = unreal.EditorAssetLibrary

COMBO_SPECS = [
    # (label, start_frame_30fps, loc_xyz, rot_rpy, scale_xyz)
    ("Slash_01_Diagonal", 14, (0.0, -25.0, 42.0), (-12.0, -22.0, 0.0), (0.96, 0.96, 0.96)),
    ("Slash_02_SpinCut", 25, (-12.0, -15.0, 8.0), (0.0, 158.0, -6.0), (1.00, 1.00, 1.00)),
    ("Slash_03_Uppercut", 32, (22.0, -30.0, 52.0), (-14.0, -76.0, 12.0), (0.90, 0.90, 0.90)),
    ("Slash_04_OverheadSlam", 39, (16.0, -10.0, 52.0), (-16.0, 74.0, -16.0), (0.98, 0.98, 0.98)),
]

# (hit_frame_30fps, z_offset_cm, cut_rot_rpy) — aligned with each slash's cutting plane!
HIT_SPECS = [
    (16, 72.0, (0.0, 3.5, 92.0)),
    (27, 88.0, (0.0, -6.0, -88.0)),
    (34, 96.0, (0.0, 28.0, 92.0)),
    (41, 68.0, (0.0, -48.0, 92.0)),
]


def _target_is_hit(dummy, guard_actor, max_range_cm=520.0):
    """True only when a live visible target actor is within the slash blade's reach ('打到人才触发')."""
    if dummy is None or dummy.is_actor_being_destroyed():
        return False
    if dummy.is_hidden_ed() or bool(getattr(dummy, "hidden", False)):
        return False
    d_loc = dummy.get_actor_location()
    g_loc = guard_actor.get_actor_location()
    dx = d_loc.x - g_loc.x
    dy = d_loc.y - g_loc.y
    return (dx * dx + dy * dy) ** 0.5 <= max_range_cm


async def render_showcase(seq_dir, shots_dir):
    unreal.ViewportService.set_editor_window_state("restore")
    unreal.PerformanceService.set_background_throttling(False)
    unreal.SystemLibrary.execute_console_command(None, "r.AntiAliasingMethod 4")
    unreal.SystemLibrary.execute_console_command(None, "r.Streaming.FullyLoadUsedTextures 1")
    await asyncio.sleep(0.20)
    if os.path.exists(seq_dir):
        shutil.rmtree(seq_dir)
    os.makedirs(seq_dir, exist_ok=True)
    os.makedirs(shots_dir, exist_ok=True)

    sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    actors = {a.get_actor_label(): a for a in sub.get_all_level_actors()}
    sub.set_selected_level_actors([])

    if "IceSlash_NS_Slash" in actors:
        actors["IceSlash_NS_Slash"].set_actor_hidden_in_game(True)

    skm_manny = EAL.load_asset("/Game/Characters/Mannequins/Meshes/SKM_Manny_Simple")
    anim = EAL.load_asset("/Game/VFX/IceSlash/Anims/AS_Manny_IceSlash_Combo")
    ns_slash = EAL.load_asset("/Game/VFX/IceSlash/Niagara/NS_IceSlash_Slash")
    ns_hit = EAL.load_asset("/Game/VFX/IceSlash/Niagara/NS_IceSlash_Hit")

    g = actors["IceSlash_Guard"]
    gh = actors.get("IceSlash_Guard_Head")
    if gh is not None:
        gh.skeletal_mesh_component.set_leader_pose_component(None, False)
        gh.skeletal_mesh_component.set_skeletal_mesh_asset(None)
        gh.set_actor_hidden_in_game(True)
        gh.set_is_temporarily_hidden_in_editor(True)

    dummy = actors.get("IceSlash_TargetDummy")
    if dummy is not None:
        dummy.set_actor_hidden_in_game(False)
        dummy.set_is_temporarily_hidden_in_editor(False)

    sc = g.skeletal_mesh_component
    sc.set_leader_pose_component(None, False)
    sc.set_skeletal_mesh_asset(skm_manny)
    sc.set_editor_property("override_materials", [])
    sc.visibility_based_anim_tick_option = unreal.VisibilityBasedAnimTickOption.ALWAYS_TICK_POSE_AND_REFRESH_BONES

    # 1. Capture clean standalone single-slash hero shot first (empty air -> NO NS_IceSlash_Hit!)
    unreal.ViewportService.set_realtime(False)
    unreal.ViewportService.set_game_view(True)
    stage = unreal.Vector(450.0, 650.0, 95.0)
    single_cam_loc = unreal.Vector(450.0 - 385.0, 650.0 - 355.0, 345.0)
    single_cam_rot = unreal.Rotator(roll=0.0, pitch=-27.0, yaw=46.0)
    na_s = sub.spawn_actor_from_class(unreal.NiagaraActor, stage, unreal.Rotator())
    nc_s = na_s.niagara_component
    nc_s.set_asset(ns_slash)
    nc_s.set_auto_destroy(False)
    nc_s.reset_system()
    nc_s.reinitialize_system()
    nc_s.advance_simulation(18, 0.01)
    single_png = os.path.join(shots_dir, "result_single_slash.png")
    unreal.ViewportService.capture_with_view(single_cam_loc, single_cam_rot, 1600, 900, single_png, 62.0, True, 0.0)
    sub.destroy_actor(na_s)

    # 2. Render 61-frame combo sequence with live per-frame bone refresh on UE5 Manny robot
    cam_loc = unreal.Vector(240.0, -765.0, 545.0)
    cam_rot = unreal.Rotator(roll=0.0, pitch=-27.5, yaw=92.0)

    total_frames = 61  # 0..60 at 30fps (~2.00s)
    hero_map = {
        19: "result_combo_slash1.png",
        30: "result_combo_slash2.png",
        44: "result_combo_slash4_slam.png",
    }

    for f_idx in range(total_frames):
        t_sec = min(f_idx / 30.0, float(anim.get_play_length()) - 0.001)
        sc.override_animation_data(anim, False, False, t_sec, 0.0)
        await asyncio.sleep(0)

        unreal.ViewportService.set_realtime(False)
        unreal.ViewportService.set_game_view(True)

        sock_xf = sc.get_socket_transform("FX_SlashSocket", unreal.RelativeTransformSpace.RTS_WORLD)
        spawned = []

        # Active slashes within [0, 0.44s] (~14 frames)
        for _lbl, start_f, loc_xyz, rot_rpy, scale_xyz in COMBO_SPECS:
            df = f_idx - start_f
            if 0 <= df <= 14:
                w_loc = sock_xf.transform_location(unreal.Vector(*loc_xyz))
                w_rot = sock_xf.transform_rotation(
                    unreal.Rotator(roll=float(rot_rpy[0]), pitch=float(rot_rpy[1]), yaw=float(rot_rpy[2]))
                )
                na = sub.spawn_actor_from_class(unreal.NiagaraActor, w_loc, w_rot)
                na.set_actor_scale3d(unreal.Vector(*scale_xyz))
                nc = na.niagara_component
                nc.set_asset(ns_slash)
                nc.set_auto_destroy(False)
                nc.reset_system()
                nc.reinitialize_system()
                steps = max(2, int(round((df / 30.0 + 0.02) / 0.01)))
                nc.advance_simulation(steps, 0.01)
                spawned.append(na)

        # Target-Hit Feedback (NS_IceSlash_Hit): ONLY spawns when a live target is actually hit within reach!
        if ns_hit is not None and _target_is_hit(dummy, g):
            dummy_loc = dummy.get_actor_location()
            for hf, z_off, cut_rpy in HIT_SPECS:
                df_h = f_idx - hf
                if 0 <= df_h <= 7:
                    hit_loc = unreal.Vector(dummy_loc.x + 12.0, dummy_loc.y - 28.0, dummy_loc.z + z_off)
                    hit_rot = unreal.Rotator(roll=float(cut_rpy[0]), pitch=float(cut_rpy[1]), yaw=float(cut_rpy[2]))
                    na_h = sub.spawn_actor_from_class(unreal.NiagaraActor, hit_loc, hit_rot)
                    na_h.set_actor_scale3d(unreal.Vector(1.0, 1.0, 1.0))
                    nc_h = na_h.niagara_component
                    nc_h.set_asset(ns_hit)
                    nc_h.set_auto_destroy(False)
                    nc_h.reset_system()
                    nc_h.reinitialize_system()
                    nc_h.advance_simulation(max(2, int(round((df_h / 30.0 + 0.02) / 0.01))), 0.01)
                    spawned.append(na_h)

        frame_png = os.path.join(seq_dir, f"frame_{f_idx:04d}.png")
        for _try in range(3):
            unreal.ViewportService.capture_with_view(cam_loc, cam_rot, 1600, 900, frame_png, 64.0, True, 0.0)
            if os.path.exists(frame_png):
                break
            unreal.ViewportService.set_editor_window_state("restore")
            await asyncio.sleep(0.10)
        if f_idx in hero_map and os.path.exists(frame_png):
            shutil.copy2(frame_png, os.path.join(shots_dir, hero_map[f_idx]))

        for a_tmp in spawned:
            sub.destroy_actor(a_tmp)

    # Restore showcase default pose (Slash_01 peak) on Manny
    sc.override_animation_data(anim, False, False, 0.5667, 0.0)
    if "IceSlash_NS_Slash" in actors:
        actors["IceSlash_NS_Slash"].set_actor_hidden_in_game(False)
    unreal.ViewportService.set_game_view(False)
    unreal.ViewportService.set_realtime(True)
    unreal.PerformanceService.set_background_throttling(True)
    unreal.EditorLoadingAndSavingUtils.save_dirty_packages(True, True)
    return {"frames": total_frames, "single": single_png, "heroes": list(hero_map.values())}
