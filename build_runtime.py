"""Build the trimmed Java runtime image bundled in the fprime-jre wheel

Downloads the pinned Eclipse Temurin JDK for the build host from the Adoptium API, verifies its
SHA-256, and assembles a runtime-only image with that JDK's jlink into src/fprime_jre/runtime.
Runs at wheel-build time in CI (one job per platform), never on user machines.

    python build_runtime.py            # download Temurin and build the image
    python build_runtime.py --jdk DIR  # build from an already-unpacked Temurin JDK
"""

import argparse
import hashlib
import json
import platform
import re
import shutil
import subprocess
import tarfile
import tomllib
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PYPROJECT = ROOT / "pyproject.toml"
RUNTIME_DIR = ROOT / "src" / "fprime_jre" / "runtime"
BUILD_DIR = ROOT / "build" / "temurin"

# The exact Temurin release. Its JAVA_VERSION must match the pyproject version minus the
# repackaging number; the build fails otherwise.
TEMURIN_RELEASE = "jdk-25.0.4.1+1"
ADOPTIUM_API = "https://api.adoptium.net/v3/assets/release_name/eclipse/{release}"
# The Adoptium API and GitHub CDN reject requests carrying urllib's default User-Agent
USER_AGENT = "fprime-jre-build (https://github.com/fprime-community/fprime-jre)"

# Runtime-only module set: the full Java SE API plus the JDK service modules that servers
# (YAMCS: netty, rocksdb, TLS, JMX) and Scala tools (fpp) load reflectively, and the
# diagnostics needed to inspect a running JVM. No compiler, jar, javadoc or jshell tooling.
MODULES = [
    "java.se",
    "jdk.attach",
    "jdk.charsets",
    "jdk.crypto.ec",
    "jdk.dynalink",
    "jdk.httpserver",
    "jdk.jcmd",
    "jdk.jfr",
    "jdk.localedata",
    "jdk.management",
    "jdk.management.agent",
    "jdk.management.jfr",
    "jdk.naming.dns",
    "jdk.net",
    "jdk.security.auth",
    "jdk.unsupported",
    "jdk.zipfs",
]
INCLUDED_LOCALES = ["en", "en-US"]

ADOPTIUM_OS = {"Linux": "linux", "Darwin": "mac", "Windows": "windows"}
ADOPTIUM_ARCH = {"x86_64": "x64", "amd64": "x64", "aarch64": "aarch64", "arm64": "aarch64"}


def expected_java_version() -> str:
    """JAVA_VERSION implied by the package version: everything but the repackaging number"""
    with PYPROJECT.open("rb") as f:
        version = tomllib.load(f)["project"]["version"]
    return version.rsplit(".", 1)[0]


def host_target() -> tuple:
    """Adoptium (os, architecture) names for the build host"""
    try:
        return ADOPTIUM_OS[platform.system()], ADOPTIUM_ARCH[platform.machine().lower()]
    except KeyError:
        raise SystemExit(f"Unsupported build host: {platform.system()} {platform.machine()}") from None


def fetch_asset(os_name: str, arch: str) -> dict:
    """Look up the JDK package (link, checksum, name) for the pinned release on Adoptium"""
    query = urllib.parse.urlencode(
        {"os": os_name, "architecture": arch, "image_type": "jdk", "heap_size": "normal", "project": "jdk"}
    )
    url = ADOPTIUM_API.format(release=urllib.parse.quote(TEMURIN_RELEASE)) + "?" + query
    print(f"[INFO] Querying {url}")
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": USER_AGENT})) as response:
        release = json.load(response)
    binaries = [b for b in release["binaries"] if b["os"] == os_name and b["architecture"] == arch]
    if len(binaries) != 1:
        raise SystemExit(f"Expected one {os_name}/{arch} binary for {TEMURIN_RELEASE}, found {len(binaries)}")
    return binaries[0]["package"]


def download(package: dict) -> Path:
    """Download the JDK archive (cached in build/) and verify its SHA-256 against Adoptium's"""
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    archive = BUILD_DIR / package["name"]
    if not archive.is_file():
        print(f"[INFO] Downloading {package['link']}")
        request = urllib.request.Request(package["link"], headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request) as response, archive.open("wb") as out:
            shutil.copyfileobj(response, out)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if digest != package["checksum"]:
        archive.unlink()
        raise SystemExit(f"SHA-256 mismatch for {archive.name}: {digest} != {package['checksum']}")
    print(f"[INFO] Verified sha256 {digest}")
    return archive


def extract(archive: Path) -> Path:
    """Unpack the JDK archive and return its home (the directory containing bin/ and release)"""
    destination = BUILD_DIR / "jdk"
    shutil.rmtree(destination, ignore_errors=True)
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(destination)
    else:
        with tarfile.open(archive) as tf:
            if hasattr(tarfile, "data_filter"):
                tf.extractall(destination, filter="data")
            else:
                tf.extractall(destination)
    return find_jdk_home(destination)


def find_jdk_home(directory: Path) -> Path:
    """Locate the JDK home under a directory (macOS nests it in Contents/Home)"""
    for release in sorted(directory.rglob("release")):
        if (release.parent / "bin").is_dir():
            return release.parent
    raise SystemExit(f"No JDK found under {directory}")


def java_version(jdk_home: Path) -> str:
    """JAVA_VERSION from a JDK or runtime image's release file"""
    match = re.search(r'^JAVA_VERSION="([0-9.]+)"', (jdk_home / "release").read_text(), re.MULTILINE)
    return match.group(1) if match else ""


def jlink(jdk_home: Path, output: Path) -> None:
    """Assemble the runtime image with the JDK's own jlink"""
    exe = ".exe" if platform.system() == "Windows" else ""
    shutil.rmtree(output, ignore_errors=True)
    command = [
        str(jdk_home / "bin" / f"jlink{exe}"),
        "--add-modules",
        ",".join(MODULES),
        f"--include-locales={','.join(INCLUDED_LOCALES)}",
        "--strip-debug",
        "--no-man-pages",
        "--no-header-files",
        "--compress",
        "zip-6",
        "--output",
        str(output),
    ]
    print(f"[INFO] {' '.join(command)}")
    subprocess.run(command, check=True)
    notice = jdk_home / "NOTICE"
    if notice.is_file():
        shutil.copy(notice, output / "NOTICE")
    subprocess.run([str(output / "bin" / f"java{exe}"), "-version"], check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--jdk", type=Path, help="use this unpacked Temurin JDK instead of downloading")
    parser.add_argument("--output", type=Path, default=RUNTIME_DIR, help=f"image directory (default: {RUNTIME_DIR})")
    args = parser.parse_args()

    expected = expected_java_version()
    if args.jdk:
        jdk_home = find_jdk_home(args.jdk)
    else:
        jdk_home = extract(download(fetch_asset(*host_target())))
    actual = java_version(jdk_home)
    if actual != expected:
        raise SystemExit(f"JDK at {jdk_home} is JAVA_VERSION {actual}; pyproject.toml expects {expected}")

    jlink(jdk_home, args.output)
    print(f"[INFO] Runtime image written to {args.output}")


if __name__ == "__main__":
    main()
