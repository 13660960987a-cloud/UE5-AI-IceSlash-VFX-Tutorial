---
name: stylized-slash-vfx
description: Author stylized anime/game sword-slash VFX in Unreal Engine 5.9 and bind them to character attack animations via skeleton sockets and AnimNotify_PlayNiagaraEffect. Use when the user asks to create a sword/blade slash trail or elemental crescent slash VFX, align slash effects to an attack combo AnimSequence, attach Niagara slashes to skeleton sockets without wrist-spin artifacts, or debug invisible/occluded slash meshes.
---

# Stylized Sword-Slash VFX + Socket AnimNotify Pipeline (UE 5.9)

Build reusable, crisp stylized slash effects (Genshin / Honkai / Wuthering Waves style) by **decoupling VFX authoring from combo choreography**:
1. Author **one canonical single-slash Niagara system** lying flat on local `Z = 0` centered at `(0, 0, 0)`.
2. Add an **anti-spin skeleton socket** (`FX_SlashSocket` parented to `root`, offset to chest height) so `Attached = True` follows character locomotion without twisting mid-fadeout when `hand_r` or `spine` rotates.
3. Sample bone velocities across the `AnimSequence` to find exact swing release frames, then bind `AnimNotify_PlayNiagaraEffect` onto `FX_SlashSocket` with per-swing `Location Offset`, `Rotation Offset`, and `Scale`.
4. Visually inspect every swing in `Game View` (`r.CustomDepth 0`, empty actor selection) to fix camera-grazing angles or particle over-occlusion.

---

## Step 0 — Reference Breakdown, Scale Budget & Asset Separation

Before writing any UE code:
1. **Quantify Reference Frames**: Extract frames (`0.10–0.25s` step) and measure elements against a `180 cm` character height benchmark (radii, widths, RGB colors, lifetimes).
2. **Enforce Big / Medium / Small Hierarchy**:
   - **Big (Hero Slash + Under-Mist)**: painted wide-sheet crescent (`Color × HollowBodyMask + EmissiveGlow`, `AlphaComposite` / premultiplied, swept via `ParticleRelativeTime`) + soft `FaceCamera` fog quads (`Alpha <= 0.25`). Avoid trying to fake hand-painted swirls with pure procedural shader math.
   - **Medium (Hit Feedback — SEPARATE System `NS_*_Hit`)**: horizontal hit-streak, starburst flash, directional splash/sparks. **Never bake hit VFX inside the slash system** — hit VFX spawns on the target only when a hit lands.
   - **Small (Sparse Rim Accents)**: snowflakes/sparks `15–25 cm` (`4–6` per slash), 4-pt stars `9–18 cm` (`2–4` per slash), fine dust `3–6 cm`. Never place oversized particles in the middle of the blade.
3. **Sprite Border & Material Pin Contracts**:
   - Every generated translucent sprite PNG **must** enforce `Alpha == 0` across its outer `16 px` border (decouple RGB `0.9–1.0` from monotone center-to-edge Alpha falloff) so quads never show hard rectangular edges.
   - After wiring translucent materials (`DepthFade -> Opacity`), always read back connections with `MaterialEditingLibrary.get_inputs_for_material_expression` — silent dropped opacity pins render sprites as opaque black boxes.

---

## Step 1 — Canonical Single-Slash Niagara (`NS_*_Slash`)

Never bake a multi-hit combo into one world-space Niagara System. Build **one canonical slash** (`R ≈ 250–270 cm`) in the local `Z = 0` horizontal plane sweeping from `-10°` (`+X` tail) through `+90°` (`+Y` character forward belly) to `+200°` (`-X` head).

### 1.1 Author Strictly Flat Planar Arc Meshes (`Z = 0`, Zero Out-of-Plane Bend)
A real sword blade sweeps on a **strictly flat 2D cutting plane** (`Z = 0.000 cm`, zero out-of-plane arch/warp). Never bend or dome slash crescent vertices along `Z` — 3D diagonal, uppercut, and overhead angles come **solely** from rotating that flat plane via `AnimNotify` `Rotation Offset`:
- Build crescent ribbon meshes (`SM_SlashArc_*`) on `Z = 0` with clean polar UVs (`U = 0 → 1` tail-to-head along the sweep, `V = 0 → 1` outer edge to inner edge) so straight horizontal strip textures bend seamlessly along the arc.
- Read [references/socket-and-canonical-arc-math.md](references/socket-and-canonical-arc-math.md) for the exact plane-fitting + center-offset math.
- Enable `ParticleRelativeTime` (`UseParticleTime = 1.0`) on the arc material instance so each spawned slash sweeps deterministically from `NormalizedAge = 0 → 1` over `0.40–0.48s`.
- Disable `InitialMeshOrientation`, `MeshRotationRate`, `GravityForce`, and `Drag` on mesh-arc emitters so particle simulation never tilts the flat cutting plane.

### 1.2 Enforce Strict Emitter Hierarchy (`SortOrderHint`) & `Blade_OuterGlow` Rim Strip
Keep secondary mist and particles subordinate so painted swirl details on the hero blade stay 100% legible:
- **Hero `Blade` (Mesh) + Stacked `Blade_OuterGlow` (Narrow Rim Mesh)**:
  - `Blade` (`SortOrderHint = 12`, `Lifetime = 0.44s`, `Translucent`/`AlphaComposite`): sharp outer rim + inner painted curls.
  - `Blade_OuterGlow` (`SortOrderHint = 13`, `Unlit` + `BLEND_Additive`, `EmissiveBoost ≈ 4.0–5.0`): **always stack a narrow flat `Z = 0` outer-rim strip mesh (`SM_SlashOuterGlow_01`) straddling the outer edge of `Blade`** with a dedicated non-premultiplied saturated emissive strip texture (`T_SlashOuterGlow`: saturated amber-to-white RGB, radial falloff in Alpha only, `16 px` `Alpha = 0` border). Do **not** premultiply RGB by Alpha when the shader also multiplies by `Tex.A`, or outer-halo pixels fall below UE5's `1.0` HDR Bloom threshold.
  - **Template Scale Trap**: When cloning a mesh emitter from `UpwardMeshBurst`, **always** set `InitializeParticle -> Mesh Scale Mode = Uniform` (`NewEnumerator3`) and `Mesh Uniform Scale = 1.0` — leaving `Mesh Scale Mode = Unset` (`NewEnumerator0`) leaves `Particles.Scale` bound to the template's `0.4–0.6` random scale and shrinks the outer-glow arc to ~55% radius!
- **Under-blade `Mist` / `Fog_Arc` / `Smoke`**: `SortOrderHint = 1..3` (strictly `< Blade`), soft puff alpha capped at `0.20–0.30`, offset slightly below (`Z - 20 cm`). Never render opaque white spheres or high-alpha smoke sprites on top of `Blade`.
- **Rim Accents (`Snowflakes`, `GoldStars`, `FrostDust`)**: `SortOrderHint = 14..16`, small sprites (`3–25 cm`) spawned along the outer arc (`R ≈ 0.97 * R_blade`) over `0.10s` (`-10° → +200°`) with gentle tangential velocity.

---

## Step 2 — Anti-Spin Skeleton Socket (`FX_SlashSocket` on `root`)

A slash mesh lasts `0.44–0.75s` (`14–22` frames at `30 fps`). Attaching `AnimNotify_PlayNiagaraEffect` (`Attached = True`) to `hand_r` or `spine_03` causes the lingering slash crescent to whip around wildly during wrist recovery or spin follow-through.

1. Check `root` rotation across the `AnimSequence` (`unreal.AnimSequenceService.get_pose_at_time`). On standard in-place or root-translated combat clips where `root` translates with steps/lunges while keeping `(0, 0, 0)` rotation:
   - Parent `FX_SlashSocket` to **`root`** at component-space chest/waist swing center `(0, +40, +105)` cm (assuming `+Y` character forward; detect forward axis from `foot -> ball` bones first!).
2. Add the socket to **both** the `USkeleton` and `USkeletalMesh` via `unreal.new_object(unreal.SkeletalMeshSocket, outer=mesh)` -> `set_socket_parent` -> `set_socket_local_transform` -> `mesh.add_socket(sock, True)` -> `SkeletalMeshEditorSubsystem.rename_socket` (see [scripts/bind_slash_notifies.py](scripts/bind_slash_notifies.py)).

---

## Step 3 — Pose Trajectory Sampling & `AnimNotify_PlayNiagaraEffect` Alignment

Never guess frame numbers. Sample `hand_r` (or weapon socket) component-space positions across every frame `0..N-1`:
1. Distinguish **windup** frames (hand pulling backward `-Y`) from **release** frames (peak forward/diagonal angular velocity). Trigger each slash `1–2` frames into the high-speed release so the crescent leads the weapon arc.
2. Bind `unreal.AnimNotify_PlayNiagaraEffect` on a dedicated notify track (e.g. `VFX_Niagara`):
   - `template`: `/Game/.../NS_*_Slash`
   - `socket_name`: `'FX_SlashSocket'`
   - `attached`: `True`
   - `should_fire_in_editor`: `True`
   - `rotation_offset`:
     - **Right-to-left horizontal / diagonal cut**: `Pitch ∈ [-30°, +30°]`, small `Roll` tilt.
     - **Left-to-right reverse/backhand cut**: flip `Pitch ≈ 155°–180°`! This mirrors the sweep direction cleanly using the **exact same** `NS_*_Slash` asset.
     - **Rising uppercut**: `Pitch ≈ -70° to -85°`.
     - **Overhead vertical slam**: `Pitch ≈ +70° to +85°`.
3. Use the ready-made template script [scripts/bind_slash_notifies.py](scripts/bind_slash_notifies.py) inside `execute_python` to create the socket and write `AnimNotify_PlayNiagaraEffect` idempotently.

---

## Step 4 — Mandatory `Game View` Visual QA

Compile status (`errors = 0`) is necessary but **never sufficient** for VFX. Always verify visually:
1. Clear selection (`EditorActorSubsystem.set_selected_level_actors([])`), enable `ViewportService.set_game_view(True)`, set `r.CustomDepth 0` if selection outlines persist, and snapshot `get_viewport_info()` so you can `restore_viewport_info()` afterward.
2. For deterministic Niagara frame inspection in `execute_python`:
   ```python
   nc.set_paused(False)
   nc.deactivate()
   nc.reset_system()
   nc.set_age_update_mode(unreal.NiagaraAgeUpdateMode.DESIRED_AGE)
   nc.set_can_render_while_seeking(True)
   nc.set_lock_desired_age_delta_time_to_seek_delta(True)
   nc.set_desired_age(0.0)
   nc.activate(True)
   await asyncio.sleep(0.035)   # allow system instance init tick
   nc.seek_to_desired_age(age)
   nc.set_desired_age(age)
   await asyncio.sleep(0.035)   # allow render proxy update
   nc.set_paused(True)
   ```
3. Inspect each swing frame (`age ≈ 0.08–0.16s`):
   - **Thin line / invisible blade?** The slash plane is nearly edge-on (coplanar) with the camera ray — adjust `Roll` / `Pitch` by `15°–30°` within the swing's natural arc so both the character swing and gameplay camera read the full crescent face.
   - **Muddy / washed-out blade?** Lower secondary fog/smoke `OpacityBoost` or move its `SortOrderHint` below `Blade`.
   - Always call `restore_viewport_info()` and save modified assets (`EditorAssetLibrary.save_asset`) when finished.
