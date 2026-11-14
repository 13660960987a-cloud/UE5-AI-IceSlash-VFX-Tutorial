"""IceSlash step 13: Deterministic capture of upgraded flat Z=0 + Blade_OuterGlow showcase stills & 61-frame combo video sequence."""
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

HIT_FRAMES = [16, 27, 34, 41]
LAND_FRAME = 42


async def render_showcase(seq_dir, shots_dir):
    unreal.ViewportService.set_editor_window_state("restore")
    unreal.PerformanceService.set_background_throttling(False)
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

    anim = EAL.load_asset("/Game/VFX/IceSlash/Anims/AS_Guard_IceSlash_Combo")
    ns_slash = EAL.load_asset("/Game/VFX/IceSlash/Niagara/NS_IceSlash_Slash")
    ns_hit = EAL.load_asset("/Game/VFX/IceSlash/Niagara/NS_IceSlash_Hit")
    ns_land = EAL.load_asset("/Game/VFX/IceSlash/Niagara/NS_IceSlash_Land")

    g = actors["IceSlash_Guard"]
    gh = actors["IceSlash_Guard_Head"]
    dummy = actors["IceSlash_TargetDummy"]
    sc = g.skeletal_mesh_component
    sh = gh.skeletal_mesh_component
    for comp in (sc, sh):
        comp.visibility_based_anim_tick_option = unreal.VisibilityBasedAnimTickOption.ALWAYS_TICK_POSE_AND_REFRESH_BONES

    dummy_loc = dummy.get_actor_location()
    hit_loc = unreal.Vector(dummy_loc.x - 25.0, dummy_loc.y, dummy_loc.z + 108.0)
    land_loc = unreal.Vector(dummy_loc.x - 55.0, dummy_loc.y, 2.0)

    # 1. Capture clean standalone single-slash hero shot first
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

    # 2. Render 61-frame combo sequence with live per-frame bone refresh (SkeletalMeshComponent.cpp:4436-4452)
    cam_loc = unreal.Vector(240.0, -765.0, 545.0)
    cam_rot = unreal.Rotator(roll=0.0, pitch=-27.5, yaw=92.0)

    total_frames = 61  # 0..60 at 30fps (~2.00s)
    hero_map = {
        19: "result_combo_slash1.png",
        30: "result_combo_slash2.png",
        44: "result_combo_slash4_slam.png",
    }

    # Ensure Guard_Head follows Guard via leader pose component
    sh.set_leader_pose_component(sc, True)

    for f_idx in range(total_frames):
        t_sec = min(f_idx / 30.0, float(anim.get_play_length()) - 0.001)
        # override_animation_data switches to single-node mode and immediately ticks + refreshes bones in Editor
        sc.override_animation_data(anim, False, False, t_sec, 0.0)
        sh.set_leader_pose_component(sc, True)
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

        # Compact hit feedback bursts on target dummy (scale 0.52 so hit sparks accent without occluding the slash!)
        if ns_hit is not None:
            for hf in HIT_FRAMES:
                df_h = f_idx - hf
                if 0 <= df_h <= 8:
                    na_h = sub.spawn_actor_from_class(unreal.NiagaraActor, hit_loc, unreal.Rotator())
                    na_h.set_actor_scale3d(unreal.Vector(0.52, 0.52, 0.52))
                    nc_h = na_h.niagara_component
                    nc_h.set_asset(ns_hit)
                    nc_h.set_auto_destroy(False)
                    nc_h.reset_system()
                    nc_h.reinitialize_system()
                    nc_h.advance_simulation(max(2, int(round((df_h / 30.0 + 0.015) / 0.01))), 0.01)
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

    # Restore showcase default pose (Slash_01 peak)
    sc.override_animation_data(anim, False, False, 0.5667, 0.0)
    sh.set_leader_pose_component(sc, True)
    if "IceSlash_NS_Slash" in actors:
        actors["IceSlash_NS_Slash"].set_actor_hidden_in_game(False)
    unreal.ViewportService.set_game_view(False)
    unreal.ViewportService.set_realtime(True)
    unreal.PerformanceService.set_background_throttling(True)
    return {"frames": total_frames, "single": single_png, "heroes": list(hero_map.values())}
