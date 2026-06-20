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
assert np.allclose(tuple(wm.tokoya_gravity), (0.0, 0.0, -9.81))
assert wm.tokoya_iterations == 10
assert wm.tokoya_interpolation_mag == 1
wm.tokoya_interpolation_mag = 2
wm.tokoya_simulation_steps = 1

from tokoya_test import _recording

spacing_roots = np.array(
    [[0.0, 0.0, 0.0], [0.001768, 0.0, 0.0]], dtype=np.float32
)
spacing = _recording._median_root_spacing(spacing_roots)
assert abs(spacing - 0.001768) < 1.0e-7, spacing
target_roots = spacing_roots + np.array(
    [0.005704, 0.0, 0.0], dtype=np.float32
)
assert _recording._auto_interpolation_count(
    spacing_roots, target_roots, spacing
) == 15

# Gravity is a full XYZ vector. A temporary +Y gravity moves free points
# backward while the two follicle points remain kinematic.
wm.tokoya_gravity = (0.0, 9.81, 0.0)
result = bpy.ops.tokoya.simulate()
assert result == {"FINISHED"}, result
after_sim = np.empty(27, dtype=np.float32)
curves_data.attributes["position"].data.foreach_get("vector", after_sim)
assert after_sim.reshape(-1, 3)[2:, 1].max() > 0.0
wm.tokoya_gravity = (0.0, 0.0, -9.81)

result = bpy.ops.tokoya.record()
assert result == {"FINISHED"}, result
assert wm.tokoya_record_mode == "RECORDING"
assert scene.sync_mode == "NONE"

scene.frame_set(2)

assert sorted(_recording.manager.frames) == [1, 2]
assert np.isfinite(_recording.manager.frames[2][0]).all()
assert wm.tokoya_auto_interpolation_current == 128

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
