"""Phase 2C experimental native module loader.

Working name only — not part of the final API. Will likely be renamed
or absorbed into a different boundary in a later phase.

No caching: each call re-runs discovery so behavior tracks environment
changes immediately. (Python's own sys.modules cache is acceptable
residue and is not cleared here.)
"""
from __future__ import annotations

import os
import sys
from types import ModuleType


# Phase 2C placeholders. Centralized here so later phases can rename
# both in one edit.
_ENV_VAR     = "HAIR_SIM_NATIVE_DIR"
_MODULE_NAME = "phase2b_probe"


def get_native() -> ModuleType | None:
    """Return the experimental native module, or None on any failure
    (env var unset, directory missing, import error)."""
    native_dir = os.environ.get(_ENV_VAR)
    if not native_dir or not os.path.isdir(native_dir):
        return None

    inserted = False
    if native_dir not in sys.path:
        sys.path.insert(0, native_dir)
        inserted = True
    try:
        return __import__(_MODULE_NAME)
    except ImportError:
        return None
    finally:
        if inserted and native_dir in sys.path:
            sys.path.remove(native_dir)
