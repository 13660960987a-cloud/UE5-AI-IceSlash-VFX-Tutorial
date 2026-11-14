"""Ice Slash v2, step 01: import the slash arcs, the ice cluster parts and every texture.

Run order: 01 import (this script), 02 anim + sockets, 03 slash material, 04 crystal material,
05 niagara, 06 showcase level, 07 sequence.

Run inside the editor (synchronous, idempotent, safe to re-run):
    import runpy; runpy.run_path('/Users/mengmeile/Downloads/lianxi/m/Tools/IceSlash/ice_slash_01_import.py', run_name='__main__')

What it creates / enforces:
  * C.MESH_DIR/SM_SlashArc_01 .. 05     from Saved/VFX/SlashSheets_v7_ue.fbx
  * C.CLUSTER_DIR/<part name>           from SourceAssets/IceCrystal/SM_IceCluster_v3_tripo_up_cm.fbx
                                        (names read from SM_IceCluster_v2_parts.json, 0-face parts skipped)
    Static meshes: one asset per FBX object (no combine), object transform NOT baked into the vertices
    (each mesh keeps its own pivot), no materials / textures imported, no collision, no lightmap-UV
    generation, Nanite off, FBX normals kept (no recompute).
  * C.TEX_DIR/T_SlashArc_Base|Mask|Glow|Noise and the five T_VFX_* sprites, with the sRGB /
    compression / LOD group / address settings below enforced on every run (MODIFIED only when a
    value actually changes).
  * Verification: every mesh's bounding box (cm) is printed and compared with
    Tools/IceSlash/data/ice_slash_data.json (arcs[].bounds_cm, cluster_parts[].size_cm). A mismatch
    of more than BOUNDS_TOLERANCE is reported as TODO (unit / axis problem). With
    AUTO_FIX_UNIT_SCALE an exact 100x / 0.01x unit error is corrected through the LOD0 build
    setting BuildScale3D (no reimport, no delete).
  * Manifest section 'import' in C.MANIFEST_PATH.

Existing assets are SKIPPED unless FORCE_REIMPORT is True, in which case they are reimported in
place through unreal.AssetDiscoveryService.reimport_asset (the asset object is kept).

Import path: the G3 grounding digest established that FBX import in this project goes through
Interchange (Interchange.FeatureFlags.Import.FBX defaults to true, InterchangeFbxTranslator.cpp:34-39,
and InterchangeImportModule enables Interchange import). The script checks those cvars at runtime and
uses the legacy UFbxImportUI options only when Interchange FBX import is off (or as a second attempt
when the Interchange pipeline override produced no static mesh).
"""

import sys
import importlib
import json
import os
import struct

import unreal

TOOLS_DIR = '/Users/mengmeile/Downloads/lianxi/m/Tools/IceSlash'
if TOOLS_DIR not in sys.path:
    sys.path.insert(0, TOOLS_DIR)
import ice_slash_common as C
importlib.reload(C)

# ----------------------------------------------------------------------------------------------
# CONFIG
# ----------------------------------------------------------------------------------------------
SCRIPT_NAME = 'ice_slash_01_import'

FORCE_REIMPORT = False          # True: reimport existing meshes / textures in place from their source files
AUTO_FIX_UNIT_SCALE = True      # True: fix an exact 100x / 0.01x unit error through LOD0 BuildScale3D
CLEAN_STALE_STAGING = False     # True: also delete leftovers of an EARLIER run found in the staging folders
BOUNDS_TOLERANCE = 0.10         # 10 percent per axis

SLASH_FBX = C.PROJECT_DIR + '/Saved/VFX/SlashSheets_v7_ue.fbx'
CLUSTER_FBX = C.PROJECT_DIR + '/SourceAssets/IceCrystal/SM_IceCluster_v3_tripo_up_cm.fbx'
MIST_FBX = C.PROJECT_DIR + '/SourceAssets/SlashMist/SlashMist_v1_cm.fbx'      # frost-mist fans, one per blade
MIST_TEX_SRC = C.PROJECT_DIR + '/SourceAssets/SlashMist'
CLUSTER_PARTS_JSON = C.PROJECT_DIR + '/SourceAssets/IceCrystal/SM_IceCluster_v2_parts.json'
SLASH_TEX_SRC = C.PROJECT_DIR + '/SourceAssets/SlashTextures'
SPRITE_TEX_SRC = C.PROJECT_DIR + '/SourceAssets/VFXSprites'

ARC_NAMES = ['SM_SlashArc_%02d' % i for i in range(1, 6)]
MIST_NAMES = ['SM_SlashMist_%02d' % i for i in range(1, 6)]

# Dedicated, script-owned staging folders. Interchange names multi-mesh imports after the FBX
# geometry (SM_SlashArc_01Mesh, SM_IceCluster_Core_mesh: InterchangeGenericStaticMeshPipeline.cpp:401-415,
# FbxHelper.cpp:21-39), so the meshes land here first and are renamed to the contract names.
SLASH_STAGING = C.MESH_DIR + '/_Staging_SlashArcs'
MIST_STAGING = C.MESH_DIR + '/_Staging_SlashMist'
CLUSTER_STAGING = C.CLUSTER_DIR + '/_Staging_IceCluster'

EAL = unreal.EditorAssetLibrary


def _texture_specs():
    """(name, source file, wanted settings). Built at runtime so enum lookups happen in the editor."""
    TC = unreal.TextureCompressionSettings
    TA = unreal.TextureAddress
    effects = unreal.TextureGroup.TEXTUREGROUP_EFFECTS            # TextureDefines.h:43
    bc7 = getattr(TC, 'TC_BC7', None) or TC.TC_DEFAULT             # TextureDefines.h:404
    clamp, wrap = TA.TA_CLAMP, TA.TA_WRAP                          # TextureDefines.h:498-499

    def spec(name, folder, srgb, comp, ax=clamp, ay=clamp):
        return {'name': name, 'src': folder + '/' + name + '.png',
                'want': {'srgb': srgb, 'compression_settings': comp, 'lod_group': effects,
                         'address_x': ax, 'address_y': ay}}

    return [
        spec('T_SlashArc_Base', SLASH_TEX_SRC, True, bc7),
        spec('T_SlashArc_Mask', SLASH_TEX_SRC, False, TC.TC_MASKS),
        spec('T_SlashArc_Glow', SLASH_TEX_SRC, True, TC.TC_DEFAULT),
        # TC_GRAYSCALE with sRGB on is stored as uncompressed RGBA8 (TextureDefines.h:396): srgb False.
        spec('T_SlashArc_Noise', SLASH_TEX_SRC, False, TC.TC_GRAYSCALE, wrap, clamp),
        spec('T_VFX_HexSnowflake_A', SPRITE_TEX_SRC, True, TC.TC_DEFAULT),
        spec('T_VFX_GoldStar4Pt_A', SPRITE_TEX_SRC, True, TC.TC_DEFAULT),
        spec('T_VFX_GroundBrushTrail_A', SPRITE_TEX_SRC, True, TC.TC_DEFAULT),
        spec('T_VFX_RadialLightRays_A', SPRITE_TEX_SRC, False, TC.TC_DEFAULT),
        spec('T_VFX_ToonSnowMistDisc_A', SPRITE_TEX_SRC, True, TC.TC_DEFAULT),
        spec('T_VFX_ImpactStarburst_A', SPRITE_TEX_SRC, True, TC.TC_DEFAULT),
        spec('T_VFX_SmokePuff_A', SPRITE_TEX_SRC, True, TC.TC_DEFAULT),
        spec('T_VFX_HitStreak_A', SPRITE_TEX_SRC, True, TC.TC_DEFAULT),
        spec('T_VFX_HitFlash_A', SPRITE_TEX_SRC, True, TC.TC_DEFAULT),
        spec('T_VFX_HitSplash_A', SPRITE_TEX_SRC, True, TC.TC_DEFAULT),
        spec('T_Slash_SwirlLines', SLASH_TEX_SRC, False, TC.TC_GRAYSCALE, wrap, clamp),
        spec('T_Slash_SwirlBold', SLASH_TEX_SRC, False, TC.TC_GRAYSCALE, wrap, clamp),
        spec('T_SlashBlade_Painted', SLASH_TEX_SRC, True, bc7),
        spec('T_SlashBlade_BodyMask', SLASH_TEX_SRC, False, TC.TC_MASKS),
        spec('T_SlashBlade_Emissive', SLASH_TEX_SRC, True, bc7),
        spec('T_SlashMist_Cloud', MIST_TEX_SRC, False, TC.TC_GRAYSCALE, wrap, wrap),
    ]


# C++ property names used as fallbacks: set/get_editor_property resolve an unmapped name straight to
# FindPropertyByName (PyWrapperObject.cpp:618-625, :1448-1464; structs PyWrapperStruct.cpp:1684-1700).
TEXTURE_PROP_CPP = {'srgb': 'SRGB', 'compression_settings': 'CompressionSettings', 'lod_group': 'LODGroup',
                    'address_x': 'AddressX', 'address_y': 'AddressY'}


# ----------------------------------------------------------------------------------------------
# small helpers (no asset objects are kept alive across calls; see _delete_created)
# ----------------------------------------------------------------------------------------------
class Ctx(object):
    def __init__(self, report):
        self.report = report
        self.todos = []
        self.touched = []           # package paths to save at the end
        self.interchange_fbx = True
        self.interchange_enabled = True
        self.manifest = {'meshes': {'arcs': {}, 'cluster': {}, 'mist': {}}, 'textures': {}, 'todo': self.todos}

    def todo(self, msg):
        self.todos.append(msg)
        self.report.todo(msg)

    def touch(self, path):
        if path not in self.touched:
            self.touched.append(path)


def _pkg(path):
    """'/Game/A/B.B' or '/Game/A/B.B:Sub' -> '/Game/A/B'."""
    path = str(path)
    if ':' in path:
        path = path.split(':', 1)[0]
    if '.' in path.rsplit('/', 1)[-1]:
        path = path.rsplit('.', 1)[0]
    return path


def _get(obj, *names):
    last = None
    for n in names:
        try:
            return obj.get_editor_property(n)
        except Exception as exc:  # try the next spelling
            last = exc
    raise last if last else RuntimeError('no property name given')


def _set(obj, value, *names):
    last = None
    for n in names:
        try:
            obj.set_editor_property(n, value)
            return n
        except Exception as exc:
            last = exc
    raise last if last else RuntimeError('no property name given')


def _cvar_bool(name, default):
    try:
        # KismetSystemLibrary.h:640 GetConsoleVariableBoolValue (false when the cvar does not exist).
        return bool(unreal.SystemLibrary.get_console_variable_bool_value(name))
    except Exception:
        return default


def _asset_class(path):
    try:
        ad = EAL.find_asset_data(path)                                 # EditorAssetLibrary.h:65
        return str(ad.asset_class_path.asset_name)
    except Exception:
        return ''


def _list_pkgs(folder, recursive=True):
    if not EAL.does_directory_exist(folder):                           # EditorAssetLibrary.h:304
        return []
    return sorted(set(_pkg(p) for p in EAL.list_assets(folder, recursive, False)))   # :331


def _png_size(path):
    try:
        with open(path, 'rb') as f:
            head = f.read(24)
        if head[:8] == b'\x89PNG\r\n\x1a\n':
            return list(struct.unpack('>II', head[16:24]))
    except Exception:
        pass
    return None


def _vec(v):
    return [round(float(v.x), 2), round(float(v.y), 2), round(float(v.z), 2)]


# ----------------------------------------------------------------------------------------------
# step 0: folders and importer detection
# ----------------------------------------------------------------------------------------------
def step_dirs(ctx):
    for d in (C.MESH_DIR, C.CLUSTER_DIR, C.TEX_DIR):
        try:
            C.ensure_dir(d)
        except Exception as exc:
            ctx.report.error('ensure_dir %s' % d, exc)


def step_detect_importer(ctx):
    # Interchange.FeatureFlags.Import.Enable: InterchangeManager.cpp:60-64 (the module turns it on at
    # startup, InterchangeImportModule.cpp:179). Interchange.FeatureFlags.Import.FBX:
    # InterchangeFbxTranslator.cpp:34-39 (default true). AssetTools uses Interchange when it is enabled
    # and AssetImportTask.factory is None (AssetTools.cpp:3597-3600).
    ctx.interchange_enabled = _cvar_bool('Interchange.FeatureFlags.Import.Enable', True)
    ctx.interchange_fbx = ctx.interchange_enabled and _cvar_bool('Interchange.FeatureFlags.Import.FBX', True)
    ctx.manifest['importer'] = 'interchange' if ctx.interchange_fbx else 'legacy_fbx_factory'
    ctx.report.info('Interchange import enabled=%s, Interchange FBX=%s -> mesh importer: %s'
                    % (ctx.interchange_enabled, ctx.interchange_fbx, ctx.manifest['importer']))


# ----------------------------------------------------------------------------------------------
# import options
# ----------------------------------------------------------------------------------------------
def _configure_generic_assets_pipeline(ctx, gap):
    """Returns a list of setting failures; critical ones abort the import."""
    critical, other = [], []

    def put(obj, value, names, crit=True):
        try:
            _set(obj, value, *names)
        except Exception as exc:
            (critical if crit else other).append('%s=%r (%s)' % (names[0], value, exc))

    # InterchangeGenericAssetsPipeline.h:60-73
    put(gap, False, ('bUseSourceNameForAsset', 'use_source_name_for_asset'), False)
    put(gap, '', ('AssetName', 'asset_name'), False)
    put(gap, False, ('bSceneNameSubFolder', 'scene_name_sub_folder'))
    put(gap, False, ('bAssetTypeSubFolders', 'asset_type_sub_folders'))
    # Sources are the *_cm.fbx re-exports (geometry baked to centimetres by data/rescale_fbx_cm.py);
    # the original metre exports kept the x100 in node transforms, which Interchange dropped.

    cm = _get(gap, 'CommonMeshesProperties', 'common_meshes_properties')   # .h:88-89
    # InterchangeGenericAssetsPipelineSharedSettings.h:26-36, :71-131
    put(cm, unreal.InterchangeForceMeshType.IFMT_STATIC_MESH, ('ForceAllMeshAsType', 'force_all_mesh_as_type'))
    put(cm, False, ('bBakeMeshes', 'bake_meshes'))             # :99 False keeps each object's own pivot
    put(cm, False, ('bBakePivotMeshes', 'bake_pivot_meshes'))  # :103
    put(cm, False, ('bImportLods', 'import_lods'), False)      # :95
    put(cm, False, ('bImportSockets', 'import_sockets'), False)  # :127
    put(cm, False, ('bRecomputeNormals', 'recompute_normals'))   # :131 keep the FBX (faceted) normals

    mp = _get(gap, 'MeshPipeline', 'mesh_pipeline')            # InterchangeGenericMeshPipeline.h
    put(mp, True, ('bImportStaticMeshes', 'import_static_meshes'))                    # :73
    put(mp, unreal.InterchangeCombineStaticMeshesBehavior.DO_NOT_COMBINE,
        ('CombineStaticMeshesBehavior', 'combine_static_meshes_behavior'))            # :32-39, :80
    # :101 bCollision. Its pythonized name 'collision' would be ambiguous with the enum 'Collision'
    # (that one is ScriptName FallbackCollisionType, :120), so the C++ name is tried first.
    put(mp, False, ('bCollision', 'collision'))
    put(mp, False, ('bBuildNanite', 'build_nanite'))                                  # :134
    put(mp, False, ('bGenerateLightmapUVs', 'generate_lightmap_u_vs'))                # :149
    put(mp, False, ('bImportSkeletalMeshes', 'import_skeletal_meshes'), False)        # :204
    put(mp, False, ('bImportGeometryCaches', 'import_geometry_caches'), False)        # :274

    try:
        ap = _get(gap, 'AnimationPipeline', 'animation_pipeline')
        put(ap, False, ('bImportAnimations', 'import_animations'), False)             # Animation.h:69
    except Exception as exc:
        other.append('animation_pipeline (%s)' % exc)
    matp = _get(gap, 'MaterialPipeline', 'material_pipeline')
    put(matp, False, ('bImportMaterials', 'import_materials'))                        # MaterialPipeline.h:85
    try:
        tp = _get(matp, 'TexturePipeline', 'texture_pipeline')                        # :124-125
        put(tp, False, ('bImportTextures', 'import_textures'))                        # TexturePipeline.h:32
    except Exception as exc:
        critical.append('texture_pipeline (%s)' % exc)
    for o in other:
        ctx.report.info('non-critical pipeline setting not applied: ' + o)
    return critical


def _interchange_mesh_options(ctx, fbx):
    """Same construction as the engine's StaticMeshToolset (EditorToolsetHelpers.cpp:359-395):
    copies of the project stack, the generic assets pipeline adjusted, all wrapped in an
    InterchangePipelineStackOverride. A bare pipeline object as task.options would go through
    ConvertImportData, find no converter and silently fall back to the project default stack
    (AssetTools.cpp:3985-3997, InterchangeManager.cpp:1110-1116)."""
    pipelines = []
    try:
        src = unreal.InterchangeManager.create_source_data(fbx)                         # InterchangeManager.h:803-804
        pipelines = list(unreal.InterchangeProjectSettingsScript.get_pipeline_stack_from_source_data(False, src))  # InterchangeProjectSettings.h:266-267 (duplicates)
    except Exception as exc:
        ctx.report.info('project pipeline stack not available (%s); using a fresh InterchangeGenericAssetsPipeline' % exc)
    gap = None
    for p in pipelines:
        if isinstance(p, unreal.InterchangeGenericAssetsPipeline):
            gap = p
            break
    if gap is None:
        gap = unreal.InterchangeGenericAssetsPipeline()   # constructor creates the instanced sub-pipelines (InterchangeGenericAssetsPipeline.cpp:75-82)
        pipelines = [gap]
    critical = _configure_generic_assets_pipeline(ctx, gap)
    if critical:
        raise RuntimeError('Interchange pipeline settings failed: ' + '; '.join(critical))
    ov = unreal.InterchangePipelineStackOverride()        # InterchangeManager.h:387-404
    for p in pipelines:
        ov.add_pipeline(p)                                # stored as soft path, resolved by TryLoad + duplicated (InterchangeManager.cpp:800-866, :881-884)
    return ov, pipelines


def _legacy_fbx_options(ctx):
    """UFbxImportUI (FbxImportUI.h:97-218). Used by the legacy FbxFactory, and converted by Interchange
    (InterchangeFbxAssetImportDataConverter.cpp:255-321) when Interchange is active."""
    ui = unreal.FbxImportUI()
    fails = []

    def put(obj, value, *names):
        try:
            _set(obj, value, *names)
        except Exception as exc:
            fails.append('%s (%s)' % (names[0], exc))

    put(ui, True, 'bImportMesh', 'import_mesh')
    put(ui, False, 'bImportAsSkeletal', 'import_as_skeletal')
    put(ui, unreal.FBXImportType.FBXIT_STATIC_MESH, 'MeshTypeToImport', 'mesh_type_to_import')
    put(ui, False, 'bImportMaterials', 'import_materials')
    put(ui, False, 'bImportTextures', 'import_textures')
    put(ui, False, 'bImportAnimations', 'import_animations')
    put(ui, False, 'bAutomatedImportShouldDetectType', 'automated_import_should_detect_type')
    put(ui, False, 'bCreatePhysicsAsset', 'create_physics_asset')
    smd = _get(ui, 'StaticMeshImportData', 'static_mesh_import_data')                   # FbxImportUI.h:202
    put(smd, False, 'bCombineMeshes', 'combine_meshes')                                 # FbxStaticMeshImportData.h:57
    put(smd, False, 'bAutoGenerateCollision', 'auto_generate_collision')                # :53
    put(smd, False, 'bGenerateLightmapUVs', 'generate_lightmap_u_vs')                   # :45
    put(smd, False, 'bBuildNanite', 'build_nanite')                                     # :42
    put(smd, False, 'bTransformVertexToAbsolute', 'transform_vertex_to_absolute')       # FbxMeshImportData.h:67
    put(smd, False, 'bBakePivotInVertex', 'bake_pivot_in_vertex')                       # :71
    put(smd, False, 'bImportMeshLODs', 'import_mesh_lo_ds')                             # :75
    put(smd, unreal.FBXNormalImportMethod.FBXNIM_IMPORT_NORMALS, 'NormalImportMethod', 'normal_import_method')  # :11-16, :79
    if fails:
        ctx.report.info('legacy FBX option(s) not applied: ' + '; '.join(fails))
    return ui


def _run_import_task(filename, dest, dest_name, options, replace=False):
    """Synchronous AssetImportTask (AssetImportTask.h:35-93). Returns imported package paths (strings
    only: no UObject reference survives this call, so a later delete is not blocked by Python)."""
    t = unreal.AssetImportTask()
    _set(t, filename, 'Filename', 'filename')
    _set(t, dest, 'DestinationPath', 'destination_path')
    _set(t, dest_name, 'DestinationName', 'destination_name')
    # automated=True avoids the Yes/No/Cancel and pipeline dialogs (InterchangeManager.cpp:1766, :1806-1830).
    _set(t, True, 'bAutomated', 'automated')
    _set(t, replace, 'bReplaceExisting', 'replace_existing')
    # Saved explicitly after renaming / settings, so the staging package never reaches disk.
    _set(t, False, 'bSave', 'save')
    # bAsync pythonizes to 'async_' (reserved word, PyGenUtil.cpp:2573-2577); False -> ImportAssetWithResult.
    _set(t, False, 'bAsync', 'async_')
    if options is not None:
        _set(t, options, 'Options', 'options')
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([t])
    paths = []
    try:
        paths = [str(p) for p in _get(t, 'ImportedObjectPaths', 'imported_object_paths')]  # AssetTools.cpp:3019
    except Exception:
        pass
    del t
    return sorted(set(_pkg(p) for p in paths))


def _delete_created(ctx, pkg_path, why):
    """Delete an asset this run just created (VibeUE UAssetDiscoveryService.h:211-214, no dialog)."""
    try:
        res = unreal.AssetDiscoveryService.delete_asset_unattended(pkg_path, False)
        ok = bool(_get(res, 'bSuccess', 'success'))
        if ok:
            print('DELETED: %s (%s)' % (pkg_path, why))
            return True
        msg = ''
        for n in ('ErrorMessage', 'error_message'):
            try:
                msg = str(_get(res, n))
                break
            except Exception:
                pass
        ctx.todo('could not delete %s (%s): %s; delete it by hand or re-run with CLEAN_STALE_STAGING=True'
                 % (pkg_path, why, msg))
    except Exception as exc:
        ctx.todo('delete_asset_unattended(%s) raised %s' % (pkg_path, exc))
    return False


def _match_target(asset_name, targets):
    """Contract name for an importer-produced name: exact, '<target>Mesh', '<target>_mesh',
    or legacy '<file>_<target>'. The longest matching target wins."""
    best = None
    for t in targets:
        hit = False
        if asset_name == t:
            hit = True
        elif asset_name.startswith(t):
            rest = asset_name[len(t):]
            hit = not rest[:1].isdigit()
        elif asset_name.endswith('_' + t) or ('_' + t + '_') in asset_name or ('_' + t + 'Mesh') in asset_name:
            hit = True
        if hit and (best is None or len(t) > len(best)):
            best = t
    return best


def _wait_mesh_build(pkg_path):
    """Reading the bounds waits for the async static-mesh build (StaticMesh.h:1597-1603)."""
    try:
        m = C.load(pkg_path)
        if m is not None and isinstance(m, unreal.StaticMesh):
            m.get_bounding_box()
    except Exception:
        pass


# ----------------------------------------------------------------------------------------------
# step 1 / 2: FBX -> separate static meshes
# ----------------------------------------------------------------------------------------------
def import_mesh_set(ctx, label, fbx, final_dir, staging, targets):
    r = ctx.report
    if not os.path.isfile(fbx):
        r.error('%s: source FBX missing: %s' % (label, fbx))
        return
    existing = [n for n in targets if C.asset_exists(final_dir + '/' + n)]
    missing = [n for n in targets if n not in existing]

    for n in existing:
        dst = final_dir + '/' + n
        if not FORCE_REIMPORT:
            r.skipped(dst, 'exists (FORCE_REIMPORT=False)')
            continue
        try:
            # UAssetDiscoveryService.h:216-220: bool + out params -> None on failure, else (source, error).
            res = unreal.AssetDiscoveryService.reimport_asset(dst, fbx)
            if res is None:
                r.error('%s: reimport failed for %s (see Output Log)' % (label, dst))
            else:
                r.modified(dst, 'reimported from %s' % os.path.basename(fbx))
                ctx.touch(dst)
        except Exception as exc:
            r.error('%s: reimport %s' % (label, dst), exc)

    if not missing:
        return

    before = set(_list_pkgs(staging))
    created = set()
    if before:
        r.info('%s: staging %s already holds %d asset(s) from an earlier run: %s'
               % (label, staging, len(before), sorted(before)))
    leftover_meshes = [p for p in before if _asset_class(p) == 'StaticMesh'
                       and _match_target(p.rsplit('/', 1)[-1], missing)]
    if not leftover_meshes:
        # Never import on top of <staging>/<fbx basename>: with an existing asset there the import
        # becomes a reimport using that asset's stored pipeline (InterchangeManager.cpp:1796-1840).
        attempts = []
        if ctx.interchange_fbx:
            attempts.append('interchange_override')
        attempts.append('fbx_import_ui')
        for how in attempts:
            try:
                C.ensure_dir(staging)
                if how == 'interchange_override':
                    options, _pipes = _interchange_mesh_options(ctx, fbx)
                else:
                    options = _legacy_fbx_options(ctx)
                reported = _run_import_task(fbx, staging, '', options, replace=False)
                options = None
                _pipes = None
                after = set(_list_pkgs(staging))
                created |= (after - before) | set(p for p in reported if p.startswith(staging + '/'))
                outside = [p for p in reported if not p.startswith(staging + '/')]
                if outside:
                    ctx.todo('%s: importer reported assets outside staging (left untouched): %s' % (label, outside))
                meshes_now = [p for p in created if _asset_class(p) == 'StaticMesh']
                r.info('%s: import via %s -> %d new asset(s), %d static mesh(es): %s'
                       % (label, how, len(created), len(meshes_now), sorted(created)))
                if meshes_now:
                    ctx.manifest.setdefault('mesh_import_path', {})[label] = how
                    break
            except Exception as exc:
                r.error('%s: import attempt %s' % (label, how), exc)
    else:
        r.info('%s: resuming from leftover staging meshes %s' % (label, sorted(leftover_meshes)))

    # rename the staged meshes to the contract names
    pool = sorted(created | set(leftover_meshes))
    claimed = {}
    for p in pool:
        if _asset_class(p) != 'StaticMesh':
            continue
        t = _match_target(p.rsplit('/', 1)[-1], targets)
        if t is None:
            continue
        if t in claimed:
            ctx.todo('%s: two staged meshes map to %s: %s and %s' % (label, t, claimed[t], p))
            continue
        claimed[t] = p

    renamed = set()
    for t in missing:
        src = claimed.get(t)
        dst = final_dir + '/' + t
        if not src:
            r.error('%s: no imported mesh matched %s (staged: %s)' % (label, t, pool))
            continue
        try:
            _wait_mesh_build(src)
            if EAL.rename_asset(src, dst):                              # EditorAssetLibrary.h:209
                r.created(dst)
                ctx.touch(dst)
                renamed.add(src)
            else:
                r.error('%s: rename %s -> %s failed' % (label, src, dst))
        except Exception as exc:
            r.error('%s: rename %s -> %s' % (label, src, dst), exc)

    # Everything else this run created in its staging folder is unwanted: duplicates of meshes that
    # already existed, unmatched meshes, materials / textures the importer still produced.
    for p in sorted(created - renamed):
        if C.asset_exists(p):
            _delete_created(ctx, p, 'created by this import, not a contract asset (%s)' % (_asset_class(p) or '?'))
    stale = [p for p in sorted(before) if p not in renamed and C.asset_exists(p)]
    for p in stale:
        if CLEAN_STALE_STAGING:
            _delete_created(ctx, p, 'stale staging leftover')
        else:
            ctx.todo('%s: stale staging asset %s left in place (set CLEAN_STALE_STAGING=True to remove)' % (label, p))
    try:
        if EAL.does_directory_exist(staging) and not EAL.does_directory_have_assets(staging, True):  # :304, :312
            EAL.delete_directory(staging)                                                               # :159
            r.info('%s: removed empty staging folder %s' % (label, staging))
    except Exception as exc:
        r.info('%s: staging folder cleanup skipped (%s)' % (label, exc))


# ----------------------------------------------------------------------------------------------
# step 3: post-import enforcement and bounds verification
# ----------------------------------------------------------------------------------------------
def _sme():
    return unreal.get_editor_subsystem(unreal.StaticMeshEditorSubsystem)


def enforce_mesh_settings(ctx, path):
    """Nanite off, no simple collision, no lightmap-UV generation, no normal recompute.
    Each change only when the current value differs (idempotent)."""
    r = ctx.report
    sme = _sme()
    mesh = C.load(path)
    if mesh is None:
        r.error('load %s' % path)
        return {}
    out = {}
    # Nanite: StaticMeshEditorSubsystem.h:217/226, FMeshNaniteSettings.bEnabled EngineTypes.h:3292
    try:
        ns = sme.get_nanite_settings(mesh)
        on = bool(_get(ns, 'bEnabled', 'enabled'))
        if on:
            _set(ns, False, 'bEnabled', 'enabled')
            sme.set_nanite_settings(mesh, ns, True)
            r.modified(path, 'nanite disabled')
            ctx.touch(path)
        out['nanite'] = False
    except Exception as exc:
        r.error('nanite settings %s' % path, exc)
    # Collision: GetSimpleCollisionCount :259, RemoveCollisions :347
    try:
        n = int(sme.get_simple_collision_count(mesh))
        if n > 0:
            if sme.remove_collisions(mesh):
                r.modified(path, 'removed %d simple collision primitive(s)' % n)
                ctx.touch(path)
            else:
                r.error('remove_collisions %s' % path)
        out['simple_collision'] = 0
    except Exception as exc:
        r.error('collision check %s' % path, exc)
    # LOD0 build settings: GetLodBuildSettings :81 / SetLodBuildSettings :90 (PostEditChange rebuild,
    # StaticMeshEditorSubsystem.cpp:547-586)
    try:
        bs = sme.get_lod_build_settings(mesh, 0)
        change = []
        if bool(_get(bs, 'bGenerateLightmapUVs', 'generate_lightmap_u_vs')):
            _set(bs, False, 'bGenerateLightmapUVs', 'generate_lightmap_u_vs')
            change.append('generate_lightmap_uvs=False')
        if bool(_get(bs, 'bRecomputeNormals', 'recompute_normals')):
            _set(bs, False, 'bRecomputeNormals', 'recompute_normals')
            change.append('recompute_normals=False')
        if change:
            sme.set_lod_build_settings(mesh, 0, bs)
            r.modified(path, ', '.join(change))
            ctx.touch(path)
        out['generate_lightmap_uvs'] = False
        out['recompute_normals'] = False
    except Exception as exc:
        r.error('build settings %s' % path, exc)
    return out


def _measure(path):
    mesh = C.load(path)
    bb = mesh.get_bounding_box()                     # StaticMesh.h:2246, local space cm
    mn, mx = _vec(bb.min), _vec(bb.max)
    size = [round(mx[i] - mn[i], 2) for i in range(3)]
    tris = None
    try:
        tris = int(mesh.get_num_triangles(0))        # StaticMesh.h:2194
    except Exception:
        pass
    return mn, mx, size, tris


def verify_mesh(ctx, path, expected):
    r = ctx.report
    entry = {'path': path, 'expected_size_cm': expected}
    try:
        mn, mx, size, tris = _measure(path)
    except Exception as exc:
        r.error('measure %s' % path, exc)
        return entry
    entry.update({'bbox_min_cm': mn, 'bbox_max_cm': mx, 'size_cm': size, 'triangles': tris})
    print('BOUNDS: %s size_cm=%s min=%s max=%s tris=%s expected_cm=%s' % (path, size, mn, mx, tris, expected))
    if not expected:
        ctx.todo('%s: no expected size in the data JSON' % path)
        return entry

    def ratios(sz):
        return [(sz[i] / expected[i]) if expected[i] > 0.5 else 1.0 for i in range(3)]

    rs = ratios(size)
    ok = all(abs(x - 1.0) <= BOUNDS_TOLERANCE for x in rs)
    entry['ratio'] = [round(x, 4) for x in rs]
    if ok:
        r.info('bounds OK %s ratios=%s' % (path, entry['ratio']))
        entry['bounds_ok'] = True
        return entry

    factor = None
    for f in (100.0, 0.01):
        if all(abs(x * f - 1.0) <= BOUNDS_TOLERANCE for x in rs):
            factor = f
    if factor and AUTO_FIX_UNIT_SCALE:
        try:
            sme = _sme()
            mesh = C.load(path)
            bs = sme.get_lod_build_settings(mesh, 0)
            cur = _get(bs, 'BuildScale3D', 'build_scale3d')   # FMeshBuildSettings::BuildScale3D
            new = unreal.Vector(cur.x * factor, cur.y * factor, cur.z * factor)
            _set(bs, new, 'BuildScale3D', 'build_scale3d')
            sme.set_lod_build_settings(mesh, 0, bs)
            mesh = None
            r.modified(path, 'BuildScale3D %s -> %s (unit fix x%g)' % (_vec(cur), _vec(new), factor))
            ctx.touch(path)
            mn, mx, size, tris = _measure(path)
            rs = ratios(size)
            entry.update({'bbox_min_cm': mn, 'bbox_max_cm': mx, 'size_cm': size,
                          'ratio': [round(x, 4) for x in rs], 'build_scale_fix': factor})
            print('BOUNDS: %s after fix size_cm=%s min=%s max=%s' % (path, size, mn, mx))
            if all(abs(x - 1.0) <= BOUNDS_TOLERANCE for x in rs):
                entry['bounds_ok'] = True
                return entry
        except Exception as exc:
            r.error('BuildScale3D fix %s' % path, exc)
    entry['bounds_ok'] = False
    if sorted(round(s, 0) for s in size) and all(
            abs(a / b - 1.0) <= BOUNDS_TOLERANCE for a, b in zip(sorted(size), sorted(expected)) if b > 0.5):
        ctx.todo('%s: bounds %s match %s only after reordering axes: the importer rotated the mesh; '
                 'compensate in actor placement' % (path, size, expected))
    else:
        ctx.todo('%s: bounds %s differ from expected %s by more than %d%% (ratios %s): unit or scale issue'
                 % (path, size, expected, int(BOUNDS_TOLERANCE * 100), entry['ratio']))
    return entry


# ----------------------------------------------------------------------------------------------
# step 4: textures
# ----------------------------------------------------------------------------------------------
def _texture_size(tex):
    for fx, fy in (('blueprint_get_size_x', 'blueprint_get_size_y'), ('get_size_x', 'get_size_y')):
        try:
            return [int(getattr(tex, fx)()), int(getattr(tex, fy)())]   # Texture2D.h:358-367
        except Exception:
            continue
    return None


def _import_texture(ctx, spec, dst):
    r = ctx.report
    folder, name = C.TEX_DIR, spec['name']
    options = None
    if ctx.interchange_enabled:
        # Engine TextureToolset pattern (TextureToolset.cpp:48-58): a fresh generic texture pipeline,
        # normal-map detection off, non-power-of-two allowed, wrapped in a stack override.
        tp = unreal.InterchangeGenericTexturePipeline()
        _set(tp, False, 'bDetectNormalMapTexture', 'detect_normal_map_texture')    # TexturePipeline.h:44
        _set(tp, True, 'bAllowNonPowerOfTwo', 'allow_non_power_of_two')            # :74
        options = unreal.InterchangePipelineStackOverride()
        options.add_pipeline(tp)
    reported = []
    try:
        # DestinationName names the single texture (InterchangeGenericTexturePipeline.cpp:469-479).
        reported = _run_import_task(spec['src'], folder, name, options, replace=False)
    except Exception as exc:
        r.info('%s: AssetImportTask raised %s' % (name, exc))
    options = None
    if not C.asset_exists(dst):
        tex_pk = [p for p in reported if _asset_class(p) == 'Texture2D']
        if tex_pk and EAL.rename_asset(tex_pk[0], dst):
            r.info('%s: renamed importer output %s -> %s' % (name, tex_pk[0], dst))
    if not C.asset_exists(dst):
        # Fallback: VibeUE direct UTextureFactory path, exact name, saves (UAssetDiscoveryService.h:100-130).
        path, err = unreal.AssetDiscoveryService.import_asset(spec['src'], folder, name)
        if not path:
            raise RuntimeError('import_asset fallback failed: %s' % err)
        r.info('%s: imported through AssetDiscoveryService.import_asset -> %s' % (name, path))
    r.created(dst)
    ctx.touch(dst)


def _enforce_texture(ctx, dst, want):
    r = ctx.report
    tex = C.load(dst)
    if tex is None:
        raise RuntimeError('cannot load ' + dst)
    changed = []
    for k, v in want.items():
        names = (k, TEXTURE_PROP_CPP[k])
        cur = _get(tex, *names)
        if (bool(cur) != bool(v)) if k == 'srgb' else (cur != v):
            # set_editor_property runs Pre/PostEditChange, so the texture rebuilds and is marked dirty.
            _set(tex, v, *names)
            changed.append('%s %s->%s' % (k, cur, v))
    if changed:
        r.modified(dst, '; '.join(changed))
        ctx.touch(dst)
    else:
        r.skipped(dst, 'settings already correct')
    final = {k: str(_get(tex, k, TEXTURE_PROP_CPP[k])) for k in want}
    return tex, final, changed


def step_textures(ctx):
    r = ctx.report
    try:
        specs = _texture_specs()
    except Exception as exc:
        r.error('texture specs (enum lookup)', exc)
        return
    for spec in specs:
        name = spec['name']
        dst = C.TEX_DIR + '/' + name
        entry = {'path': dst, 'source': spec['src'], 'source_size': _png_size(spec['src'])}
        try:
            if not os.path.isfile(spec['src']):
                raise RuntimeError('source missing: ' + spec['src'])
            if C.asset_exists(dst):
                if FORCE_REIMPORT:
                    res = unreal.AssetDiscoveryService.reimport_asset(dst, spec['src'])
                    if res is None:
                        r.error('reimport failed for %s (see Output Log)' % dst)
                    else:
                        r.modified(dst, 'reimported from ' + os.path.basename(spec['src']))
                        ctx.touch(dst)
                else:
                    r.skipped(dst, 'exists (FORCE_REIMPORT=False)')
            else:
                _import_texture(ctx, spec, dst)
            tex, final, changed = _enforce_texture(ctx, dst, spec['want'])
            size = _texture_size(tex)
            tex = None
            entry.update({'size': size, 'settings': final, 'changed': changed})
            print('TEXTURE: %s size=%s source_size=%s settings=%s' % (dst, size, entry['source_size'], final))
            if size and entry['source_size'] and size != entry['source_size']:
                ctx.todo('%s: asset size %s differs from source %s' % (dst, size, entry['source_size']))
        except Exception as exc:
            r.error('texture %s' % name, exc)
            entry['error'] = str(exc)
        ctx.manifest['textures'][name] = entry


# ----------------------------------------------------------------------------------------------
# step 1-3 drivers
# ----------------------------------------------------------------------------------------------
def _cluster_targets(ctx):
    with open(CLUSTER_PARTS_JSON, 'r') as f:
        parts = json.load(f)
    names, skipped, size_m = [], [], {}
    for p in parts:
        n = str(p.get('name', '')).strip()
        if not n:
            continue
        if int(p.get('faces', 0) or 0) <= 0:
            skipped.append(n)
            continue
        names.append(n)
        if p.get('size_m'):
            size_m[n] = [round(float(v) * 100.0, 2) for v in p['size_m']]
    for n in skipped:
        ctx.report.skipped(C.CLUSTER_DIR + '/' + n, '0 faces in SM_IceCluster_v2_parts.json')
    return names, skipped, size_m


def step_meshes(ctx, data):
    r = ctx.report
    arc_expect = {}
    for a in data.get('arcs', []):
        arc_expect[a.get('name')] = a.get('bounds_cm')
    clu_expect = {}
    for p in data.get('cluster_parts', []):
        clu_expect[p.get('name')] = p.get('size_cm')

    # slash arcs
    try:
        import_mesh_set(ctx, 'arcs', SLASH_FBX, C.MESH_DIR, SLASH_STAGING, ARC_NAMES)
    except Exception as exc:
        r.error('arc import', exc)
    try:
        import_mesh_set(ctx, 'mist', MIST_FBX, C.MESH_DIR, MIST_STAGING, MIST_NAMES)
    except Exception as exc:
        r.error('mist import', exc)
    # ice cluster
    cluster_names = []
    try:
        cluster_names, skipped, size_m = _cluster_targets(ctx)
        ctx.manifest['cluster_parts_skipped'] = skipped
        for n, s in size_m.items():
            clu_expect.setdefault(n, s)
        r.info('cluster parts from JSON: %s' % cluster_names)
        import_mesh_set(ctx, 'cluster', CLUSTER_FBX, C.CLUSTER_DIR, CLUSTER_STAGING, cluster_names)
    except Exception as exc:
        r.error('cluster import', exc)

    for group, names, folder, expect in (('arcs', ARC_NAMES, C.MESH_DIR, arc_expect),
                                         ('mist', MIST_NAMES, C.MESH_DIR, {}),
                                         ('cluster', cluster_names, C.CLUSTER_DIR, clu_expect)):
        for n in names:
            path = folder + '/' + n
            if not C.asset_exists(path):
                ctx.manifest['meshes'][group][n] = {'path': path, 'missing': True}
                continue
            try:
                settings = enforce_mesh_settings(ctx, path)
                entry = verify_mesh(ctx, path, expect.get(n))
                entry['settings'] = settings
                ctx.manifest['meshes'][group][n] = entry
            except Exception as exc:
                r.error('verify %s' % path, exc)


# ----------------------------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------------------------
def step_save(ctx):
    r = ctx.report
    for p in ctx.touched:
        try:
            if C.asset_exists(p) and not EAL.save_asset(p, True):       # EditorAssetLibrary.h:284
                r.error('save %s' % p)
        except Exception as exc:
            r.error('save %s' % p, exc)
    try:
        C.save_all()
    except Exception as exc:
        r.error('C.save_all', exc)
    try:
        dirty = [d for d in unreal.PythonTools.get_dirty_packages(False) if d.startswith(C.ROOT)]  # PythonTools.h:75
        r.info('dirty IceSlash packages after save: %s' % dirty)
    except Exception as exc:
        r.info('get_dirty_packages unavailable (%s)' % exc)


def main():
    report = C.Report(SCRIPT_NAME)
    ctx = Ctx(report)
    ctx.manifest['config'] = {'force_reimport': FORCE_REIMPORT, 'auto_fix_unit_scale': AUTO_FIX_UNIT_SCALE,
                              'bounds_tolerance': BOUNDS_TOLERANCE}
    ctx.manifest['sources'] = {'slash_fbx': SLASH_FBX, 'cluster_fbx': CLUSTER_FBX,
                               'cluster_parts_json': CLUSTER_PARTS_JSON}
    ctx.manifest['mesh_options'] = {'combine': False, 'bake_meshes': False, 'materials': False,
                                    'textures': False, 'collision': False, 'lightmap_uvs': False,
                                    'nanite': False, 'recompute_normals': False}
    data = {}
    try:
        data = C.load_data()
    except Exception as exc:
        report.error('load data JSON %s' % C.DATA_PATH, exc)

    step_dirs(ctx)
    step_detect_importer(ctx)
    step_meshes(ctx, data)
    step_textures(ctx)
    try:
        C.update_manifest('import', ctx.manifest)
        report.info('manifest section import written to %s' % C.MANIFEST_PATH)
    except Exception as exc:
        report.error('update_manifest import', exc)
    step_save(ctx)
    report.finish()


if __name__ == '__main__':
    main()
