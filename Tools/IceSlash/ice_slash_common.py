"""ice_slash_common.py - shared helpers for the IceSlash v2 editor scripts.

Purpose
    One module that every Tools/IceSlash/NN_*.py script imports, so paths, evidence logging,
    manifest I/O, tool dispatch, level-load guarding and saving behave identically everywhere.
    It creates NO assets by itself.

How scripts import it (inside the editor, through execute_python + runpy.run_path):
    import sys, importlib
    TOOLS_DIR = '/Users/mengmeile/Downloads/lianxi/m/Tools/IceSlash'
    if TOOLS_DIR not in sys.path: sys.path.insert(0, TOOLS_DIR)
    import ice_slash_common as C
    importlib.reload(C)

Run order of the scripts that use it
    01 import, 02 anim+sockets, 03 slash material, 04 crystal material, 05 niagara,
    06 showcase level, 07 sequence.

Running this file directly (runpy.run_path(<this file>, run_name='__main__')) only runs
selftest(): it prints the contract paths and checks that unreal/vibeue/PythonTools are usable.
It writes nothing to content (read-only), and raises RuntimeError if a check fails.

What it writes
    Only the JSON manifest at MANIFEST_PATH (sections 'runs' and 'todos' from Report.finish(),
    plus whatever sections the scripts pass to update_manifest()).

Saving policy (save_all)
    asset-management SKILL.md (Plugins/VibeUE/Skills/asset-management/SKILL.md:537) says never call
    save_dirty_packages(True, True): a dirty package you did not touch belongs to someone else (here
    the editor belongs to the agent EmeraldCedar). So save_all() saves only
      * packages that became dirty after this run's Report() was constructed (baseline snapshot),
      * packages under the IceSlash content root (ours by contract), and
      * packages the script explicitly reported as created/modified or passed as extra_packages.
    World (map) packages outside the IceSlash root are never saved. Everything not saved is
    listed with a SKIPPED: line.
"""

import datetime
import json
import os
import sys
import traceback

import unreal

# ----------------------------------------------------------------------------------------------
# CONFIG
# ----------------------------------------------------------------------------------------------
# Defaults the scripts may read (each script may also define its own FORCE / REBUILD).
FORCE = False            # scripts: re-apply settings even when they already match
REBUILD = False          # scripts: rebuild graphs/assets in place (never delete+recreate)
PRINT_TRACEBACKS = True  # Report.error(msg, exc) also prints the full traceback as TRACE: lines
SAVE_PREEXISTING_IN_ROOT = True  # save_all(): also save packages under ROOT that were already dirty

# ----------------------------------------------------------------------------------------------
# Contract paths
# ----------------------------------------------------------------------------------------------
PROJECT_DIR = '/Users/mengmeile/Downloads/lianxi/m'
TOOLS_DIR = PROJECT_DIR + '/Tools/IceSlash'
DATA_PATH = TOOLS_DIR + '/data/ice_slash_data.json'

ROOT = '/Game/VFX/IceSlash'
MESH_DIR = ROOT + '/Meshes'
CLUSTER_DIR = ROOT + '/Meshes/IceCluster'
TEX_DIR = ROOT + '/Textures'
MAT_DIR = ROOT + '/Materials'
NS_DIR = ROOT + '/Niagara'
ANIM_DIR = ROOT + '/Anims'
SEQ_DIR = ROOT + '/Sequences'
MAP_PATH = ROOT + '/Maps/L_IceSlash_v2'

MANIFEST_PATH = PROJECT_DIR + '/Saved/VFX/ice_slash_manifest.json'
SHOTS_DIR = PROJECT_DIR + '/Saved/VFX/shots'

# Package-name prefixes that belong to this pipeline. One-file-per-actor maps keep their actors
# in /Game/__ExternalActors__/<map path minus /Game>/... and /Game/__ExternalObjects__/...
_OWNED_PREFIXES = (
    ROOT + '/',
    '/Game/__ExternalActors__' + ROOT[len('/Game'):] + '/',
    '/Game/__ExternalObjects__' + ROOT[len('/Game'):] + '/',
)
# Packages that are never saved by path (transient / engine / PIE).
_UNSAVEABLE_PREFIXES = ('/Temp/', '/Memory/', '/Engine/', '/Script/')

EAL = unreal.EditorAssetLibrary

# Baseline of dirty packages captured by the most recent Report() (see save_all).
_DIRTY_BASELINE = None


# ----------------------------------------------------------------------------------------------
# Small utilities
# ----------------------------------------------------------------------------------------------
def _now():
    return datetime.datetime.now().isoformat(timespec='seconds')


def _p(tag, msg):
    print('%s %s' % (tag, msg))


def package_name(path):
    """'/Game/A/B.B' or '/Game/A/B.B:Sub' or '/Game/A/B' -> '/Game/A/B'. Non-paths -> None."""
    if not isinstance(path, str):
        return None
    s = path.strip().split(' ', 1)[0].split(':', 1)[0]
    if not s.startswith('/'):
        return None
    head, _, leaf = s.rpartition('/')
    if '.' in leaf:
        leaf = leaf.split('.', 1)[0]
    return head + '/' + leaf if head else '/' + leaf


def is_owned(pkg):
    """True when a package name lies under the IceSlash content root (or its external actors)."""
    return bool(pkg) and (pkg == ROOT or any(pkg.startswith(p) for p in _OWNED_PREFIXES))


def _vibeue():
    """Import vibeue lazily (Plugins/VibeUE/Content/Python/vibeue.py, on the editor's sys.path)."""
    import vibeue  # noqa: WPS433 - deliberate lazy import so selftest can report a failure
    return vibeue


def _dirty(include_maps=True):
    """Sorted dirty package names. PythonTools.h:75 GetDirtyPackages(bool bIncludeMaps=true).

    With bIncludeMaps the engine may mark a dirty map's never-saved MapBuildData package dirty while
    enumerating (PythonTools.h:63-66, FileHelpers.cpp EnumerateDirtyWorldPackages), so callers that
    take a baseline enumerate twice.
    """
    return [str(n) for n in unreal.PythonTools.get_dirty_packages(include_maps)]


def _snapshot_dirty():
    a = set(_dirty(True))
    a |= set(_dirty(True))  # second pass catches MapBuildData dirtied by the first enumeration
    return a


# ----------------------------------------------------------------------------------------------
# Report
# ----------------------------------------------------------------------------------------------
class _Guard(object):
    """Context manager returned by Report.step(): records any exception as an error and continues."""

    def __init__(self, report, label):
        self.report = report
        self.label = label
        self.ok = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc is None:
            return False
        self.ok = False
        self.report.error('%s failed' % self.label, exc)
        return True  # swallow: the script continues with the next item


class Report(object):
    """Evidence logger. Each call prints exactly one prefixed line (TRACE: lines are extra detail).

        R = C.Report('01_import')
        R.created('/Game/VFX/IceSlash/Meshes/SM_SlashArc_01')
        with R.step('texture T_SlashArc_Base'):
            ...
        C.save_all(R)
        R.finish()      # prints ICE_SLASH_SUMMARY {...}; raises RuntimeError if any error
    """

    def __init__(self, script_name):
        global _DIRTY_BASELINE
        self.script = str(script_name)
        self.started = _now()
        self.created_paths = []
        self.modified_paths = []
        self.skipped_paths = []
        self.infos = []
        self.todos = []
        self.errors = []
        self.saved = []
        try:
            self.dirty_baseline = _snapshot_dirty()
        except Exception as exc:  # PythonTools missing would also break the whole pipeline
            self.dirty_baseline = None
            self.error('could not snapshot dirty packages (unreal.PythonTools.get_dirty_packages)', exc)
        _DIRTY_BASELINE = self.dirty_baseline
        _p('INFO:', '%s start %s (pre-existing dirty packages: %s)' % (
            self.script, self.started,
            'unknown' if self.dirty_baseline is None else len(self.dirty_baseline)))

    # -- line emitters --------------------------------------------------------------------------
    def created(self, path):
        self.created_paths.append(str(path))
        _p('CREATED:', path)

    def modified(self, path, what=''):
        self.modified_paths.append(str(path))
        _p('MODIFIED:', '%s%s' % (path, (' (%s)' % what) if what else ''))

    def skipped(self, path, why=''):
        self.skipped_paths.append(str(path))
        _p('SKIPPED:', '%s%s' % (path, (' (%s)' % why) if why else ''))

    def info(self, msg):
        self.infos.append(str(msg))
        _p('INFO:', msg)

    def todo(self, msg):
        self.todos.append(str(msg))
        _p('TODO:', msg)

    def error(self, msg, exc=None):
        text = str(msg)
        if exc is not None:
            where = ''
            try:
                frames = traceback.extract_tb(exc.__traceback__)
                if frames:
                    f = frames[-1]
                    where = ' @ %s:%s' % (os.path.basename(f.filename), f.lineno)
            except Exception:
                pass
            text = '%s: %s: %s%s' % (text, type(exc).__name__, exc, where)
        self.errors.append(text)
        _p('ERROR:', text)
        if exc is not None and PRINT_TRACEBACKS:
            try:
                for line in traceback.format_exception(type(exc), exc, exc.__traceback__):
                    for sub in line.rstrip().splitlines():
                        print('TRACE: ' + sub)
            except Exception:
                pass

    def step(self, label):
        """with report.step('label'): ... -> exceptions become report.error and execution continues."""
        return _Guard(self, label)

    @property
    def ok(self):
        return not self.errors

    # -- summary --------------------------------------------------------------------------------
    def summary(self):
        return {
            'script': self.script,
            'started': self.started,
            'finished': _now(),
            'ok': not self.errors,
            'counts': {
                'created': len(self.created_paths), 'modified': len(self.modified_paths),
                'skipped': len(self.skipped_paths), 'todos': len(self.todos),
                'errors': len(self.errors), 'saved': len(self.saved),
            },
            'created': self.created_paths,
            'modified': self.modified_paths,
            'saved': self.saved,
            'todos': self.todos,
            'errors': self.errors,
        }

    def finish(self):
        """Print 'ICE_SLASH_SUMMARY ' + one-line JSON, record it in the manifest, raise on errors."""
        summ = self.summary()
        try:
            update_manifest('runs', {self.script: {k: summ[k] for k in ('started', 'finished', 'ok', 'counts')}})
            update_manifest('todos', {self.script: list(self.todos)})
        except Exception as exc:  # manifest trouble must not hide the real result
            _p('WARN:', 'manifest summary write failed: %s: %s' % (type(exc).__name__, exc))
        print('ICE_SLASH_SUMMARY ' + json.dumps(summ, ensure_ascii=False, sort_keys=True, default=str))
        if self.errors:
            raise RuntimeError('%s: %d errors' % (self.script, len(self.errors)))
        return summ


# ----------------------------------------------------------------------------------------------
# Assets
# ----------------------------------------------------------------------------------------------
def asset_exists(path):
    """EditorAssetLibrary.DoesAssetExist (EditorAssetLibrary.h:73). False on malformed paths."""
    try:
        return bool(EAL.does_asset_exist(path))
    except Exception as exc:
        _p('WARN:', 'asset_exists(%r): %s' % (path, exc))
        return False


def _asset_class_name(path):
    """Class short name from the asset registry, without loading (EditorAssetLibrary.h:65,
    AssetData.h:203 AssetClassPath; same read as vibeue.safe_load_level)."""
    try:
        ad = EAL.find_asset_data(path)
        return str(ad.asset_class_path.asset_name)
    except Exception:
        return ''


def load(path):
    """Load an asset, or None when it does not exist.

    Refuses map (World) assets: a map loaded as an asset stays resident and the next level load
    FATALS the editor (PythonTools.h:23-33, AGENTS.md section 9). Use load_level() for maps.
    """
    if not path or not asset_exists(path):
        return None
    if _asset_class_name(path) == 'World':
        _p('WARN:', 'load(%s) refused: it is a map; use vibeue.safe_load_level / C.load_level' % path)
        return None
    try:
        return EAL.load_asset(path)  # EditorAssetLibrary.h:40
    except Exception as exc:
        _p('WARN:', 'load(%s) failed: %s' % (path, exc))
        return None


def ensure_dir(content_dir):
    """Make a content folder if missing. Returns True when it was created, False when it existed.

    EditorAssetLibrary.DoesDirectoryExist / MakeDirectory (EditorAssetLibrary.h:304, :320).
    Raises RuntimeError when MakeDirectory fails.
    """
    d = content_dir.rstrip('/')
    if EAL.does_directory_exist(d):
        return False
    if not EAL.make_directory(d):
        raise RuntimeError('ensure_dir: make_directory(%s) returned False' % d)
    _p('INFO:', 'made content dir %s' % d)
    return True


def save_all(report=None, extra_packages=None, include_maps=True):
    """Save the dirty packages this run is responsible for (see module docstring). Returns the list
    of package names saved.

    Uses UEditorLoadingAndSavingUtils::SavePackages(Packages, bOnlyDirty) (FileHelpers.h:86), which
    guards GIsRunningUnattendedScript so no modal dialog opens (FileHelpers.cpp:5950-5952), and
    unreal.find_package (PythonScriptPlugin PyCore.cpp:2594) to turn names into UPackage objects.
    Saving a map package also saves its dirty external (OFPA) packages (FileHelpers.cpp:853-872).
    NOT save_dirty_packages(True, True): asset-management SKILL.md:537.
    """
    baseline = getattr(report, 'dirty_baseline', None) if report is not None else _DIRTY_BASELINE
    try:
        dirty_all = set(_dirty(True) if include_maps else _dirty(False))
        dirty_content = set(_dirty(False))
    except Exception as exc:
        if report is not None:
            report.error('save_all: could not list dirty packages', exc)
            return []
        raise
    world_pkgs = dirty_all - dirty_content

    explicit = set()
    for src in (getattr(report, 'created_paths', []) if report is not None else []):
        explicit.add(package_name(src))
    for src in (getattr(report, 'modified_paths', []) if report is not None else []):
        explicit.add(package_name(src))
    for src in (extra_packages or []):
        explicit.add(package_name(src))
    explicit.discard(None)

    to_save, skipped = [], []
    for pkg in sorted(dirty_all):
        why = None
        if pkg.startswith(_UNSAVEABLE_PREFIXES):
            why = 'transient/engine package'
        elif is_owned(pkg):
            if baseline is not None and pkg in baseline and not SAVE_PREEXISTING_IN_ROOT and pkg not in explicit:
                why = 'already dirty before this run'
        elif pkg in world_pkgs:
            why = 'map/world package outside %s is never saved by these scripts' % ROOT
        elif pkg in explicit:
            pass
        elif baseline is None:
            why = 'no dirty baseline; not ours by path'
        elif pkg in baseline:
            why = 'already dirty before this run (not ours)'
        if why:
            skipped.append((pkg, why))
        else:
            to_save.append(pkg)

    for pkg, why in skipped:
        if report is not None:
            report.skipped(pkg, 'save: ' + why)
        else:
            _p('SKIPPED:', '%s (save: %s)' % (pkg, why))

    if not to_save:
        _p('INFO:', 'save_all: nothing of ours is dirty')
        return []

    packages, missing = [], []
    for pkg in to_save:
        obj = unreal.find_package(pkg)
        if obj is None:
            missing.append(pkg)
        else:
            packages.append(obj)
    for pkg in missing:
        msg = 'save_all: dirty package not found in memory: %s' % pkg
        if report is not None:
            report.error(msg)
        else:
            _p('ERROR:', msg)

    ok = bool(unreal.EditorLoadingAndSavingUtils.save_packages(packages, True)) if packages else True
    still = set(_dirty(True)) & set(to_save)
    saved = [p for p in to_save if p not in still and p not in missing]
    for pkg in saved:
        _p('SAVED:', pkg)
    if report is not None:
        report.saved.extend(saved)
    if not ok or still:
        msg = 'save_all: save_packages returned %s; still dirty: %s' % (ok, sorted(still))
        if report is not None:
            report.error(msg)
        else:
            raise RuntimeError(msg)
    _p('INFO:', 'save_all: saved %d package(s); dirty now: %d' % (len(saved), len(_dirty(True))))
    return saved


# ----------------------------------------------------------------------------------------------
# Data and manifest
# ----------------------------------------------------------------------------------------------
def load_data():
    """Static offline data (Tools/IceSlash/data/ice_slash_data.json) as a dict."""
    if not os.path.isfile(DATA_PATH):
        raise RuntimeError('load_data: missing %s (build it with data/build_ice_slash_data.py)' % DATA_PATH)
    with open(DATA_PATH, 'r', encoding='utf-8') as fh:
        return json.load(fh)


def read_manifest():
    """The manifest dict ({} when the file does not exist). Raises RuntimeError on corrupt JSON so a
    later update_manifest() never overwrites it."""
    if not os.path.isfile(MANIFEST_PATH):
        return {}
    try:
        with open(MANIFEST_PATH, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
    except ValueError as exc:
        raise RuntimeError('read_manifest: %s is not valid JSON (%s); fix or move it' % (MANIFEST_PATH, exc))
    if not isinstance(data, dict):
        raise RuntimeError('read_manifest: %s top level is %s, expected an object' % (
            MANIFEST_PATH, type(data).__name__))
    return data


def update_manifest(section, value, replace=False):
    """Merge one section into MANIFEST_PATH (atomic: temp file + os.replace).

    When the existing section and value are both dicts the keys are merged (new wins, one level);
    otherwise, or with replace=True, the section is replaced. '_meta' records the last update.
    Returns the new manifest dict.
    """
    data = read_manifest()
    old = data.get(section)
    if not replace and isinstance(old, dict) and isinstance(value, dict):
        merged = dict(old)
        merged.update(value)
        data[section] = merged
    else:
        data[section] = value
    data['_meta'] = {'updated': _now(), 'last_section': section}
    parent = os.path.dirname(MANIFEST_PATH)
    os.makedirs(parent, exist_ok=True)
    tmp = MANIFEST_PATH + '.tmp.%d' % os.getpid()
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False, sort_keys=True, default=str)
        fh.write('\n')
    os.replace(tmp, MANIFEST_PATH)
    return data


# ----------------------------------------------------------------------------------------------
# Engine toolsets and level safety
# ----------------------------------------------------------------------------------------------
def exec_tool(toolset, tool, args=None):
    """vibeue.exec_tool (vibeue.py:213) with every failure normalised to RuntimeError.

    vibeue raises KeyError for an unknown toolset (vibeue.py:122), ValueError listing all missing
    required params (vibeue.py:187) and RuntimeError carrying res.error (vibeue.py:229); when the
    tool has not completed it returns the raw async result object (vibeue.py:230-233,
    UToolsetRegistry.h:66 UAsyncFunctionResultString). These scripts are synchronous, so a pending
    result is also an error here.
    """
    vibeue = _vibeue()
    label = '%s::%s' % (toolset, tool)
    try:
        out = vibeue.exec_tool(toolset, tool, dict(args or {}))
    except RuntimeError:
        raise  # already '<toolset>::<tool> failed: <error text>'
    except KeyError as exc:
        raise RuntimeError('%s failed: unknown toolset: %s' % (label, exc.args[0] if exc.args else exc))
    except ValueError as exc:
        raise RuntimeError('%s failed: bad arguments: %s' % (label, exc))
    except Exception as exc:
        raise RuntimeError('%s failed: %s: %s' % (label, type(exc).__name__, exc))
    if hasattr(out, 'is_complete') and not isinstance(out, (dict, list, str)):
        err = getattr(out, 'error', '')
        if err:
            raise RuntimeError('%s failed: %s' % (label, err))
        if not out.is_complete:
            raise RuntimeError('%s did not complete synchronously (async tool); not usable from these '
                               'scripts' % label)
    return out


def guard_resident_maps(report=None):
    """True when no map besides the open level is resident (safe to load a level).

    unreal.PythonTools.get_resident_maps() (PythonTools.h:53); a non-empty list means the next level
    load FATALS the editor (PythonTools.h:40-41). Prints each resident map and returns False then.
    """
    resident = [str(m) for m in unreal.PythonTools.get_resident_maps()]
    if not resident:
        _p('INFO:', 'resident maps: none (level load allowed)')
        return True
    msg = 'resident maps present, level load NOT allowed (restart the editor first): %s' % resident
    if report is not None:
        report.info(msg)
    else:
        _p('INFO:', msg)
    return False


def current_level_path():
    """Package name of the open editor level ('' when unknown). UnrealEditorSubsystem.get_editor_world."""
    try:
        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
        return package_name(world.get_path_name()) or ''
    except Exception:
        return ''


def load_level(map_path, report):
    """Open map_path unless it is already the open level. Never loads while maps are resident.

    Returns True when map_path is the open level afterwards. Uses vibeue.safe_load_level
    (vibeue.py:530), which raises vibeue.LevelLoadRefused (a RuntimeError) instead of crashing.
    """
    target = package_name(map_path)
    if current_level_path() == target:
        report.skipped(target, 'already the open level')
        return True
    if not guard_resident_maps(report):
        report.error('load_level(%s) refused: resident maps present' % target)
        return False
    vibeue = _vibeue()
    try:
        ok = bool(vibeue.safe_load_level(target))
    except vibeue.LevelLoadRefused as exc:
        report.error('load_level(%s) refused by vibeue.safe_load_level' % target, exc)
        return False
    if not ok or current_level_path() != target:
        report.error('load_level(%s) returned %s; open level is %s' % (target, ok, current_level_path()))
        return False
    report.info('opened level %s' % target)
    return True


# ----------------------------------------------------------------------------------------------
# Properties
# ----------------------------------------------------------------------------------------------
def set_props(obj, **props):
    """Set each editor property separately; return the names that failed (each failure printed).

    A property that already holds the wanted value is left alone, so re-runs do not dirty assets
    (set_editor_property always notifies PreEdit/PostEditChange). Struct wrappers compare by value
    (PyWrapperStruct.cpp:1080 RichCmp), objects by identity. Names may be snake_case or the C++
    name (PyWrapperObject.cpp falls back to FindPropertyByName).
    """
    failed = []
    for name, value in props.items():
        try:
            try:
                if obj.get_editor_property(name) == value:
                    continue
            except Exception:
                pass  # unreadable or not comparable: just set it
            obj.set_editor_property(name, value)
        except Exception as exc:
            failed.append(name)
            try:
                who = obj.get_path_name()
            except Exception:
                who = repr(obj)
            _p('WARN:', 'set_props %s.%s = %r failed: %s: %s' % (who, name, value, type(exc).__name__, exc))
    return failed


# ----------------------------------------------------------------------------------------------
# Self test
# ----------------------------------------------------------------------------------------------
def selftest():
    """Read-only check: prints the contract paths, imports vibeue, probes PythonTools. Raises
    RuntimeError if any check fails. Saves nothing and writes no manifest entry."""
    problems = []
    for name in ('PROJECT_DIR', 'TOOLS_DIR', 'DATA_PATH', 'ROOT', 'MESH_DIR', 'CLUSTER_DIR', 'TEX_DIR',
                 'MAT_DIR', 'NS_DIR', 'ANIM_DIR', 'SEQ_DIR', 'MAP_PATH', 'MANIFEST_PATH', 'SHOTS_DIR'):
        print('PATH: %-13s = %s' % (name, globals()[name]))
    try:
        v = _vibeue()
        print('CHECK: vibeue imported from %s (exec_tool=%s, safe_load_level=%s)' % (
            getattr(v, '__file__', '?'), hasattr(v, 'exec_tool'), hasattr(v, 'safe_load_level')))
        if not (hasattr(v, 'exec_tool') and hasattr(v, 'safe_load_level')):
            problems.append('vibeue lacks exec_tool/safe_load_level')
    except Exception as exc:
        problems.append('import vibeue: %s: %s' % (type(exc).__name__, exc))
    try:
        print('CHECK: resident maps = %s' % list(unreal.PythonTools.get_resident_maps()))
        print('CHECK: dirty packages = %d' % len(_dirty(True)))
    except Exception as exc:
        problems.append('unreal.PythonTools: %s: %s' % (type(exc).__name__, exc))
    print('CHECK: data file %s' % ('present' if os.path.isfile(DATA_PATH) else 'MISSING'))
    if not os.path.isfile(DATA_PATH):
        problems.append('missing ' + DATA_PATH)
    try:
        print('CHECK: manifest sections = %s' % sorted(read_manifest().keys()))
    except Exception as exc:
        problems.append(str(exc))
    print('CHECK: content root exists = %s; open level = %s' % (
        EAL.does_directory_exist(ROOT), current_level_path() or '?'))
    for p in problems:
        print('ERROR: selftest: ' + p)
    print('ICE_SLASH_SELFTEST ' + json.dumps({'ok': not problems, 'problems': problems}))
    if problems:
        raise RuntimeError('ice_slash_common selftest: %d problem(s)' % len(problems))
    return True


def main():
    selftest()


if __name__ == '__main__':
    main()
