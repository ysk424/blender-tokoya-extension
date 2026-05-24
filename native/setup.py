# Phase 2B/4A/4B/4C/5A placeholder build script. setuptools + pybind11.
# Will be replaced when a later phase decides the long-term build system.
import os

from setuptools import setup
from pybind11.setup_helpers import Pybind11Extension, build_ext

# PhysX 5 SDK is expected at ../../PhysX (sibling to this repo) — see
# CLAUDE.md "External dependencies" section. The build preset that
# produces these libs is vc17win64-cpu-md (CPU only, dynamic CRT to
# match pybind11). Override via PHYSX_INSTALL_DIR if you put PhysX
# somewhere else.
_HERE = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_PHYSX_INSTALL = os.path.abspath(os.path.join(
    _HERE, "..", "..", "PhysX", "physx", "install",
    "vc17win64-cpu-md", "PhysX"))
PHYSX_INSTALL = os.environ.get("PHYSX_INSTALL_DIR", _DEFAULT_PHYSX_INSTALL)

PHYSX_INCLUDE = os.path.join(PHYSX_INSTALL, "include")
PHYSX_LIBDIR  = os.path.join(PHYSX_INSTALL, "bin", "win.x86_64.vc143.md", "release")

ext = Pybind11Extension(
    "phase2b_probe",
    ["probe.cpp"],
    cxx_std=17,
    include_dirs=[PHYSX_INCLUDE],
    library_dirs=[PHYSX_LIBDIR],
    libraries=[
        "PhysXFoundation_64",
        "PhysX_64",
        "PhysXCommon_64",
        "PhysXCooking_64",          # Phase 5D: triangle mesh cooking
        "PhysXExtensions_static_64",
        "PhysXPvdSDK_static_64",
    ],
)

setup(
    name="phase2b_probe",
    ext_modules=[ext],
    cmdclass={"build_ext": build_ext},
)
