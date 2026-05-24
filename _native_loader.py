"""Phase 2D experimental native module loader.

Working name only — not part of the final API.

Discovery priority (γ):
    1. HAIR_SIM_NATIVE_DIR (dev override)
    2. Extension-bundled <pkg>/native/
    3. unavailable -> None

No internal caching: each call re-runs discovery from scratch so
priority switching is honored even within a single Blender session.
Uses importlib.util.spec_from_file_location to bind a specific .pyd
path explicitly, bypassing sys.path search caches.
"""
from __future__ import annotations

import glob
import importlib.util
import os
import sys
from types import ModuleType


# Phase 2D placeholders. Centralized so a later phase can rename in one place.
_ENV_VAR        = "HAIR_SIM_NATIVE_DIR"
_MODULE_NAME    = "phase2b_probe"
_BUNDLED_SUBDIR = "native"


def _find_pyd(native_dir: str) -> str | None:
    if not native_dir or not os.path.isdir(native_dir):
        return None
    matches = sorted(glob.glob(os.path.join(native_dir, _MODULE_NAME + "*.pyd")))
    return matches[0] if matches else None


def _load_from_path(pyd_path: str) -> ModuleType | None:
    # Make co-located runtime DLLs (Phase 5A: PhysX) resolvable.
    pyd_dir = os.path.dirname(pyd_path)

    # 1) Tell Python's extension import machinery about the directory.
    #    This handles statically linked deps of the .pyd itself.
    if hasattr(os, "add_dll_directory") and os.path.isdir(pyd_dir):
        try:
            os.add_dll_directory(pyd_dir)
        except (OSError, FileNotFoundError):
            pass

    # 2) Preload PhysX runtime DLLs in dependency order. PhysX_64 uses
    #    delay-load for PhysXCommon_64, and the Microsoft delay-load
    #    helper does raw LoadLibrary calls that do NOT respect
    #    os.add_dll_directory (per Python docs). Loading the DLLs here
    #    by absolute path puts them in the process's DLL handle cache
    #    so delay-load resolves them by bare filename later.
    #    These DLLs may not be present (e.g., extension built without
    #    PhysX); each load is best-effort and does not abort import.
    if os.path.isdir(pyd_dir):
        import ctypes
        for dep_name in ("PhysXFoundation_64.dll",
                         "PhysXCommon_64.dll",
                         "PhysXCooking_64.dll",
                         "PhysX_64.dll"):
            dep_path = os.path.join(pyd_dir, dep_name)
            if os.path.isfile(dep_path):
                try:
                    ctypes.WinDLL(dep_path)
                except OSError:
                    pass

    sys.modules.pop(_MODULE_NAME, None)
    spec = importlib.util.spec_from_file_location(_MODULE_NAME, pyd_path)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[_MODULE_NAME] = mod
    try:
        spec.loader.exec_module(mod)
    except (ImportError, OSError):
        sys.modules.pop(_MODULE_NAME, None)
        return None
    # CPython's single-phase extension cache may retain the first-loaded
    # __file__ across re-loads under the same module name. Force the
    # attribute to reflect the path we actually chose so callers can rely
    # on __file__ to inspect which source was honored.
    actual = sys.modules.get(_MODULE_NAME)
    if actual is not None:
        try:
            actual.__file__ = pyd_path
        except AttributeError:
            pass
    return actual


def get_native() -> ModuleType | None:
    # 1. env var override (dev)
    pyd = _find_pyd(os.environ.get(_ENV_VAR, ""))
    if pyd:
        mod = _load_from_path(pyd)
        if mod is not None:
            return mod

    # 2. bundled fallback (next to this file)
    bundled_dir = os.path.join(os.path.dirname(__file__), _BUNDLED_SUBDIR)
    pyd = _find_pyd(bundled_dir)
    if pyd:
        mod = _load_from_path(pyd)
        if mod is not None:
            return mod

    # 3. unavailable
    return None
