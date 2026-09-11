"""fprime-jre: a pip-installable Eclipse Temurin Java runtime

Exposes the location of the bundled runtime for Python callers:

>>> from fprime_jre import JAVA, JAVA_HOME, JAVA_VERSION
"""

import os
import re
from pathlib import Path

JAVA_HOME = Path(__file__).resolve().parent / "runtime"
JAVA = JAVA_HOME / "bin" / ("java.exe" if os.name == "nt" else "java")


def _read_java_version(java_home: Path) -> tuple:
    """Read JAVA_VERSION from the runtime image's release file as a tuple of ints"""
    release = java_home / "release"
    if not release.is_file():
        return ()
    match = re.search(r'^JAVA_VERSION="([0-9.]+)"', release.read_text(), re.MULTILINE)
    return tuple(int(part) for part in match.group(1).split(".")) if match else ()


JAVA_VERSION = _read_java_version(JAVA_HOME)
