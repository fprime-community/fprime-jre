"""Wheel tagging for fprime-jre

The package is pure Python but bundles a native Java runtime, so the wheel is tagged
`py3-none-<platform>`. The platform tag is taken from FPRIME_JRE_PLATFORM_TAG (set by CI to an
honest manylinux/macosx/win tag) and otherwise derived from the build host.
"""

import os
import sys
from pathlib import Path

from setuptools import setup

try:
    from setuptools.command.bdist_wheel import bdist_wheel, get_platform
except ImportError:  # setuptools < 70.1
    from wheel.bdist_wheel import bdist_wheel, get_platform

RUNTIME_DIR = Path(__file__).resolve().parent / "src" / "fprime_jre" / "runtime"


class PlatformWheel(bdist_wheel):
    """bdist_wheel producing a py3-none-<platform> tag"""

    def finalize_options(self):
        if not RUNTIME_DIR.is_dir():
            print(f"[ERROR] {RUNTIME_DIR} is missing; run build_runtime.py first", file=sys.stderr)
            sys.exit(1)
        super().finalize_options()
        self.plat_name = get_platform(None)
        self.plat_name_supplied = True

    def get_tag(self):
        python, abi, platform = super().get_tag()
        # Taken verbatim so compound tags (manylinux_2_17_x86_64.manylinux2014_x86_64) survive
        return python, abi, os.environ.get("FPRIME_JRE_PLATFORM_TAG") or platform


setup(cmdclass={"bdist_wheel": PlatformWheel})
