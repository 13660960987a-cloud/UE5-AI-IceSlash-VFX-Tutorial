# Canonical Arc Flattening & Socket Alignment Reference

## 1. Flattening an Imported 3D Slash Mesh to `Z = 0`

When an imported static mesh (`SM_SlashArc_01`) has arbitrary local pivot or tilt:

1. Read mesh vertices in Python (`unreal.ProceduralMeshLibrary.get_section_from_static_mesh(mesh, 0, 0)`):
   - Compute centroid $\mathbf{c}$ and covariance matrix of $(\mathbf{v}_i - \mathbf{c})$.
   - The eigenvector with the **smallest** eigenvalue is the arc plane normal $\mathbf{n}$.
   - Fit circle center $\mathbf{p}_0$ and radius $r_0$ in the 2D plane orthogonal to $\mathbf{n}$.

2. Solve for `MeshRenderer` properties so all rim vertices lie on $Z = 0$ at target radius $R_{\text{target}}$ (e.g. $270\text{ cm}$), sweeping from $+X$ (`-10°`) through $+Y$ (`+90°`, character forward) to $-X$ (`+200°`):
   - **Uniform Scale**:
     $$s = \frac{R_{\text{target}}}{r_0}$$
   - **MeshRenderer Rotation**: Choose Euler `(Roll, Pitch, Yaw)` such that $R_{\text{rot}} \cdot \mathbf{n} = (0, 0, 1)^T$ and the arc midpoint maps onto $(0, +R_{\text{target}}, 0)$.
   - **MeshRenderer Position Offset** (`OS_Local` / `SimulationPosition`):
     $$\mathbf{t}_{\text{offset}} = -s \cdot (R_{\text{rot}} \cdot \mathbf{p}_0)$$

Verify numerically that $\max_i |(s \cdot R_{\text{rot}} \mathbf{v}_i + \mathbf{t}_{\text{offset}})_z| < 1\text{ cm}$ before building emitters.

---

## 2. Detecting Character Forward Axis & Placing `FX_SlashSocket`

Different character packs use `+Y` or `+X` as mesh forward in reference pose. Measure `foot_l -> ball_l` and `foot_r -> ball_r` in component space via `unreal.SkeletonService.get_bone_transform(mesh_path, bone, True)`:

- If $|\Delta y| \ge |\Delta x|$ and $\Delta y > 0$: Forward is **`+Y`** (`fwd_yaw = 0°`).
- If $|\Delta x| > |\Delta y|$ and $\Delta x > 0$: Forward is **`+X`** (`fwd_yaw = -90°`).

Place `FX_SlashSocket` on `root` at `(0, +40, +105)` cm in character-forward component space, converted to `root` bone space via:
```python
bone_cs = unreal.SkeletonService.get_bone_transform(mesh_path, 'root', True)
local_loc = bone_cs.inverse_transform_location(target_cs_point)
local_rot = bone_cs.inverse_transform_rotation(target_cs_rot)
```

---

## 3. Quick Orientation Cheat-Sheet for `AnimNotify_PlayNiagaraEffect`

Assuming canonical `NS_*_Slash` lies in `Z = 0` with belly toward `+Y` (forward) and sweeps `+X -> +Y -> -X` (right-to-left):

| Attack Cut Type | `Rotation Offset (Roll, Pitch, Yaw)` | Visual Result |
| :--- | :--- | :--- |
| Horizontal Right → Left | `(0, 0, 0)` | Pure waist-level horizontal slash |
| High-Right → Low-Left Diagonal | `(-12, -22, 0)` | Classic opening aerial/diagonal cut |
| Reverse Left → Right Spin Cut | `(0, 158, -6)` | Flips arc upside-down (`~180°` Pitch) to sweep Left → Right |
| Low-Right → High-Left Uppercut | `(-14, -76, 12)` | Steep rising diagonal slash |
| Overhead Top → Down Slam | `(-16, 74, -16)` | Near-vertical downward crescent smash |
