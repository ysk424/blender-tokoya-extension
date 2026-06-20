import importlib.util
import pathlib
import sys
import types

import bpy


ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "tokoya_rollback_test",
    ROOT / "__init__.py",
    submodule_search_locations=[str(ROOT)],
)
addon = importlib.util.module_from_spec(spec)
sys.modules["tokoya_rollback_test"] = addon
spec.loader.exec_module(addon)

from tokoya_rollback_test import _recording

original_load_cache = _recording.manager.load_cache
original_bpy = _recording.bpy
_recording.bpy = types.SimpleNamespace(data=object())
assert _recording._cache_path() is None
_recording.bpy = original_bpy


def fail_load_cache():
    raise RuntimeError("intentional registration failure")


_recording.manager.load_cache = fail_load_cache
try:
    addon.register()
except RuntimeError as exc:
    assert "intentional registration failure" in str(exc)
else:
    raise AssertionError("register() should have failed")

assert not hasattr(bpy.types, "TOKOYA_PT_main")
assert not hasattr(bpy.types, "TOKOYA_OT_record")
assert not hasattr(bpy.types.WindowManager, "tokoya_record_mode")

_recording.manager.load_cache = original_load_cache
addon.register()
assert hasattr(bpy.types, "TOKOYA_PT_main")
assert hasattr(bpy.types, "TOKOYA_OT_record")
addon.unregister()

print("TOKOYA_REGISTRATION_ROLLBACK_OK")
