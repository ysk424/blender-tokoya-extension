import importlib.util
import os
import pathlib
import sys

import bpy
import numpy as np


ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "tokoya_test",
    ROOT / "__init__.py",
    submodule_search_locations=[str(ROOT)],
)
addon = importlib.util.module_from_spec(spec)
sys.modules["tokoya_test"] = addon
spec.loader.exec_module(addon)
addon.register()

curves_data = bpy.data.hair_curves.new("RecordingTestHair")
curves_data.add_curves([9])
curves_obj = bpy.data.objects.new("RecordingTestHair", curves_data)
bpy.context.scene.collection.objects.link(curves_obj)
points = np.array(
    [[0.0, 0.0, 2.0 + index * 0.05] for index in range(9)],
    dtype=np.float32,
)
curves_data.attributes["position"].data.foreach_set("vector", points.ravel())

bpy.ops.mesh.primitive_cube_add(location=(0.0, 0.0, -5.0))
body = bpy.context.object
body.name = "RecordingTestBody"

curves_obj.location.x = 0.0
curves_obj.keyframe_insert("location", frame=1)
curves_obj.location.x = 0.02
curves_obj.keyframe_insert("location", frame=2)

scene = bpy.context.scene
scene.frame_start = 1
scene.frame_end = 3
scene.render.fps = 24
scene.render.fps_base = 1.0
scene.sync_mode = "AUDIO_SYNC"
scene.frame_set(1)

wm = bpy.context.window_manager
wm.tokoya_body_obj = body.name
wm.tokoya_compute_backend = os.environ.get("TOKOYA_TEST_BACKEND", "CPU")
wm.tokoya_frame_interpolation = 2
wm.tokoya_substeps = 1
wm.tokoya_iterations = 1
wm.tokoya_simulation_steps = 1

# The existing single-frame styling path remains compatible.
result = bpy.ops.tokoya.simulate()
assert result == {"FINISHED"}, result

result = bpy.ops.tokoya.record()
assert result == {"FINISHED"}, result
assert wm.tokoya_record_mode == "RECORDING"
assert scene.sync_mode == "NONE"

scene.frame_set(2)
from tokoya_test import _recording

assert sorted(_recording.manager.frames) == [1, 2]
assert np.isfinite(_recording.manager.frames[2][0]).all()

# Reverse playback aborts recording and restores the cached frame.
scene.frame_set(1)
assert wm.tokoya_record_mode == "PLAYBACK"
assert scene.sync_mode == "AUDIO_SYNC"

# Starting again from an earlier cached frame truncates and overwrites forward.
result = bpy.ops.tokoya.record()
assert result == {"FINISHED"}, result
assert scene.sync_mode == "NONE"
assert sorted(_recording.manager.frames) == [1]
scene.frame_set(2)
assert sorted(_recording.manager.frames) == [1, 2]

result = bpy.ops.tokoya.record()
assert result == {"FINISHED"}, result
assert wm.tokoya_record_mode == "PLAYBACK"
assert scene.sync_mode == "AUDIO_SYNC"

blend_path = ROOT / "tests" / "recording_smoke.blend"
bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
cache_path = pathlib.Path(str(blend_path) + ".tokoya-cache.npz")
assert cache_path.exists(), cache_path

_recording.manager.frames.clear()
assert _recording.manager.load_cache()
assert sorted(_recording.manager.frames) == [1, 2]
scene.frame_set(1)
assert _recording.manager.restore(scene, 1)

print("TOKOYA_RECORDING_SMOKE_OK", cache_path.stat().st_size)
addon.unregister()
