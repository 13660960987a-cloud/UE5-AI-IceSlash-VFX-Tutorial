# Ice slash data (`ice_slash_data.json`)

This file holds the measured placement and timing data that the IceSlash editor scripts read. The data come from the source FBX files and the animation guide. Nothing here needs the editor. Every number can be regenerated with the three scripts in this folder.

| File | Role |
| --- | --- |
| `extract_fbx_blender.py` | Headless Blender script. It parses each FBX raw (GlobalSettings plus `Lcl Translation/Rotation/Scaling` per Model) and also imports it normally, recording world location, rotation, scale, local bounds, polygon/triangle counts and per-vertex UV and position. Writes `fbx_extract_raw.json`. |
| `fbx_extract_raw.json` | Intermediate extract, in Blender metres. |
| `verify_arc_reproduction.py` | Runs under Blender's Python because it needs numpy. It re-executes only the fitting functions and constants of `Saved/VFX/generate_slash_arcs_v4.py` on the guide JSON and compares them with the FBX centre-lines. |
| `build_ice_slash_data.py` | Plain `python3 -I`. It combines the extract, the generator `SEGMENTS` (parsed with `ast`, not executed), the guide JSON and the parts JSON into `ice_slash_data.json`. |

To regenerate, run these from the project root:

```
/Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup -P Tools/IceSlash/data/extract_fbx_blender.py -- \
    Tools/IceSlash/data/fbx_extract_raw.json Saved/VFX/SlashArcs_v4.fbx SourceAssets/IceCrystal/SM_IceCluster_v2.fbx
/Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup -P Tools/IceSlash/data/verify_arc_reproduction.py -- "$PWD"
python3 -I Tools/IceSlash/data/build_ice_slash_data.py --report
```

## Coordinate chain (why the arcs are mirrored)

1. **Guide.** `SlashGuide_1HM_AerialSwing01_2HitCombo.json` holds UE component-space cm, which is left-handed. The character faces **+Y**: the right hand starts at x = -32, and the root motion carries the pelvis from y = 0 to y = 247 cm.
2. **Generator.** `generate_slash_arcs_v4.py` (`joint_position`) divides by 100 and uses x, y, z unchanged in right-handed Blender. `verify_arc_reproduction.py` confirms that Blender world equals guide / 100 exactly (worst error 8.8e-7 m).
3. **Blender export.** The settings were `axis_forward='-Y'`, `axis_up='Z'`, `bake_space_transform=False`, `apply_unit_scale=True`, `apply_scale_options='FBX_SCALE_ALL'`, `global_scale=1`. Blender 5.2 (`io_scene_fbx/fbx_utils.py:1814`) premultiplies every root object by `axis_conversion(-Y, Z)`, which is a 180-degree rotation about Z. The file then declares Up = +Z, Front = +Y, Coord = -X and UnitScaleFactor = 100. The raw parse shows every Model with `Lcl Translation = (-x, -y, z)` and `Lcl Rotation = (0, 0, 180)`. Vertices are left untransformed in object-local space.
4. **UE import.** This is Interchange FBX with the FBX SDK parser, which is the default (`bUseUfbxParser = false`, `InterchangeFbxTranslator.h:64`). `FFbxConvert::ConvertScene` (`FbxConvert.cpp:84-110`) converts to Z-up, front = -ParityOdd (-Y), right-handed. That is another 180-degree rotation about Z, so it cancels Blender's. `FbxSystemUnit::cm.ConvertScene` scales by 100, and `FFbxConvert::ConvertPos` (`FbxConvert.h:134`) maps (x, y, z) to (x, -y, z) for the right-to-left-handed conversion. The uFBX path (`UfbxParser.cpp:109-121`, `UFBX_MIRROR_AXIS_Y`) is built to give the same result.
5. **Net result.** In UE, each object is at `(100x, -100y, 100z)` with zero rotation, and its vertices are `(100vx, -100vy, 100vz)`. That is the guide space mirrored across XZ. In JSON terms, each imported arc vertex equals the guide position with Y negated.

**Correction.** Put one parent component, attached to the skeletal mesh component (not the capsule) with identity location and rotation, at relative scale `(1, -1, 1)`. Keep every arc at its imported relative transform: `pivot_cm` with zero rotation, or `(0, 0, 0)` if the meshes were baked. Every vertex then returns to guide space.

Confidence is high: both conversion paths were read in source, and the raw FBX values were checked.

If the correction is skipped, the arcs land 3.4 to 7.4 m away from where the generator put them.

### Hand path vs arc centre-line (cm; guide space; 40 samples per window)

| Arc | Bone | Frames | Mean / max distance, corrected | Mean / max distance, mirrored (as imported) | Circle centre, corrected | Plane normal, corrected |
| --- | --- | --- | --- | --- | --- | --- |
| 01 | hand_r | 10-18 | 61.9 / 109.8 | 116.2 / 197.1 | (47.9, 123.3, 144.1) | (-0.780, -0.125, 0.613) |
| 02 | hand_r | 14-22 | 141.0 / 171.7 | 213.0 / 248.3 | (64.2, 114.4, 128.2) | (0.493, -0.865, -0.095) |
| 03 | hand_r | 31-42 | 189.9 / 238.0 | 347.1 / 493.4 | (-15.1, 200.5, 137.2) | (-0.164, -0.767, -0.620) |
| 04 | hand_r | 36-46 | 30.8 / 45.5 | 447.8 / 502.1 | (-36.2, 212.2, 88.7) | (-0.901, 0.367, 0.230) |
| 05 | hand_l | 37-47 | 99.9 / 121.9 | 453.4 / 469.8 | (-14.0, 266.0, 88.4) | (-0.570, 0.689, -0.447) |

The arcs are idealised, so even the corrected distances are not zero. The generator fixes the radius at 130, 170 or 220 cm, pulls the circle centre 68% toward the pelvis, and shifts the arcs 0, 30 or 60 cm along -Y. The arcs always sit around the hand path, though, and never in a mirrored copy behind the character.

**Facing caveat.** The v4 author treated -Y as "front": `forward_offset` runs along -Y, the plane normals are forced to -Y, and the preview camera sits at -Y. In guide space the character actually faces +Y. After the correction, the forward offsets therefore push arcs 02 and 03 slightly behind the travel direction. The material is TwoSided, so this changes framing only.

## What the showcase should look like if it is right

- Seen from the side, all five arcs lie along the lunge, from the start position to about 3.75 m ahead along mesh +Y. The corrected AABBs span y = +4 to +375 cm.
- Arc 03 wraps the body during its swing. Its centre is about (-15, 201, 137) and the mean pelvis position is about (-25, 223, 113).
- Arc 03's tail ends near the ground just before the impact point, where hand_r is at (-13.7, 341.4, 14.0) at anim frame 42.
- At FX_Slash_01 + 0.20 s, the right hand is at (41.9, 189.7, 158.5). That is inside arc 01's circle, on the character's left side (mesh +X).
- **Failure sign:** arcs that extend 0 to 3.75 m behind the start position (mesh -Y) while the character lunges forward. That means the `(1, -1, 1)` parent is missing or sits at the wrong level.

## Import-mode assumptions (check after import)

- **Interchange default `common_meshes_properties.bake_meshes = True`** (`InterchangeGenericAssetsPipelineSharedSettings.h:99`). Node transforms are baked into the vertices, so each StaticMesh's pivot becomes the FBX scene origin. Place the arcs at `(0, 0, 0)` under the mirror parent. This is also the most robust choice for units.
- **`bake_meshes = False`.** The pivot stays at the slash head (arcs) or the bottom centre (cluster parts), and the actor goes at `pivot_cm`. With an FBX in metres, the FBX SDK unit conversion may put the x100 on the node rather than the vertices. After import, compare the StaticMesh bounding-box size with `bounds_cm` or `size_cm`. A size 100x too small needs compensating.
- **Cluster parts should keep their pivots (`bake_meshes = False`).** M_IceCrystal_v2 measures growth height from `ObjectPositionWS`. With baked meshes, the object origin would sit 37.4 cm above the snow-disc bottom, or 149.6 cm at scale 4.
- **Legacy importer equivalent:** `FbxStaticMeshImportData.transform_vertex_to_absolute`, which defaults to True and corresponds to bake.

## Arcs (imported UE cm, before correction)

| Arc | pivot_cm (head, UV.x = 0) | Frames | Anim s | Sequence s | Radius | Sweep | Width | Local AABB size (cm) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 01 | (89.64, -3.58, 172.82) | 10-18 | 0.333-0.600 | 1.400 | 130 | 205 | 40 | 162.2 x 250.6 x 182.0 |
| 02 | (182.91, -170.08, 236.29) | 14-22 | 0.467-0.733 | 1.533 | 170 | 185 | 28 | 272.0 x 151.6 x 289.4 |
| 03 | (188.20, -222.84, 56.04) | 31-42 | 1.033-1.400 | 2.100 | 220 | 245 | 45 | 438.0 x 274.8 x 290.2 |
| 04 | (-41.05, -113.57, 227.04) | 36-46 | 1.200-1.533 | 2.267 | 170 | 200 | 30 | 107.8 x 261.9 x 328.7 |
| 05 | (-54.08, -308.13, 204.63) | 37-47 | 1.233-1.567 | 2.300 | 130 | 265 | 26 | 209.2 x 199.3 x 238.5 |

- Rotation is 0 and scale is 1 for every arc.
- Radius, sweep and width are the generator values after its clamps. Measuring the FBX mesh agrees to within 0.01 cm and 0.1 deg.
- Arcs 04 and 05 dip below the floor, to z = -72 cm and z = -33 cm.

## Ice cluster (imported UE cm, scale 1; multiply by `cluster_scale` = 4)

| Part | pivot_cm (bottom centre) | size_cm | Faces (all triangles) | Role |
| --- | --- | --- | --- | --- |
| Core | (6.74, -2.44, -35.45) | 39.8 x 52.3 x 79.1 | 86 | prism |
| Left | (-6.93, 6.45, -38.57) | 21.5 x 24.4 x 45.3 | 87 | prism |
| Right | (20.12, 11.13, -40.53) | 47.5 x 52.9 x 40.4 | 188 | prism |
| Back | (-2.25, -15.53, -43.65) | 61.7 x 28.1 x 61.1 | 152 | prism |
| Boulders | (-0.39, 1.76, -41.31) | 87.7 x 91.2 x 47.1 | 914 | boulder |
| Base | (0.00, 0.00, -37.40) | 99.8 x 99.8 x 7.0 | 13300 | snowbase |

- **`cluster_center_cm` = (0, 0, -37.4).** XY is the centre of the union, and Z is the bottom of the snow disc, which serves as the ground.
- **Placement.** Put the parent at `FX_CrystalCenter` with scale 4. Put each part at relative `(pivot_cm - cluster_center_cm)`.
- **Size.** The union is 99.8 x 99.8 x 87.3 cm at scale 1, or 399 x 399 x 349 cm at scale 4.
- **Buried roots.** Prism roots reach 6.25 cm below the disc bottom, which is 25 cm below the floor at scale 4.
- **Naming flip.** The split script's "Back" (+Y in Blender) ends up on -Y in UE. No mirror correction is needed for the cluster.

## Timeline (sequence seconds)

`anim_start_offset_s` = 1.4 - 10/30 = **1.0667**. The attack animation (2.0333 s at 30 fps, 61 frame intervals, 62 keys) holds frame 0 until 1.0667 and ends at 3.1.

| Event | Time | Source | Basis |
| --- | --- | --- | --- |
| FX_HandEnergy_Start | 0.0 | plan | Hand energy and mist, 0.0-1.4 |
| FX_Slash_01 | 1.4000 | anim | Arc 01 window start, f10. Full brightness at f16, the swing's peak hand speed |
| FX_Slash_02 | 1.5333 | anim | f14 (plan said 1.8) |
| FX_Slash_03 | 2.1000 | anim | f31 (plan said 2.2) |
| FX_Slash_04 | 2.2667 | anim | f36, layer of the big sweep |
| FX_Slash_05 | 2.3000 | anim | f37, left-hand layer |
| FX_Slash_Impact | 2.4667 | anim | f42: hand_r lands (z = 14 cm, speed 1978 to 250 cm/s). Plan said 2.6 |
| FX_IceBurst | 3.2 | plan | Burst runs 3.2-4.3 |
| FX_CrystalReveal | 4.3 | plan | Growth runs 4.3-5.0 |
| FX_CrystalHold | 5.0 | plan | Hold and glow, 5.0-5.8 |
| FX_End | 5.8 | plan | Start of settle and fade, 5.8-7.0. The sequence ends at 7.0 |

- **Reveal timing.** Each arc is hidden at notify +0.00, starts revealing at +0.05, reaches full brightness at +0.20, and its tail is gone at +0.35.
- **Events after the animation.** Everything after 3.1 s happens after the animation has ended, so those events must be Sequencer events.
- **AnimNotifies on the sequence asset.** Use the animation time, which is `time_s - 1.0667`.
- **Impact point vs the plan's socket.** The impact point is about 73 cm in front of the pelvis at that moment, at component y = 341. The plan's `FX_IceBurst` socket at root + 165 cm assumes a stationary root.

## Assumptions and risks

- The guide is component space for the RamsterZ (UE4 mannequin) skeleton. Retargeting to Guard changes the proportions, so expect a few cm to about 20 cm of deviation.
- The arcs match only if the animation plays with the root moving in component space, meaning no root lock or root-motion extraction. Check `enable_root_motion` on the AnimSequence.
- Arc time ranges in the JSON are animation times. Timeline times are sequence times.
- `FX_End` is placed at 5.8 (start of the fade) rather than 7.0 (end of the sequence), so that it can trigger the fade.
