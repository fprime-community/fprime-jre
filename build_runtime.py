"""Build the trimmed Java runtime image bundled in the fprime-jre wheel

The package version comes from the git tag (setuptools_scm) and is the Eclipse Temurin JAVA_VERSION
followed by a repackaging number: v25.0.4.1.0 bundles Temurin 25.0.4.1. This script downloads the
GA Temurin JDK for that JAVA_VERSION and the build host from the Adoptium API, verifies its SHA-256,
and assembles a runtime-only image with that JDK's jlink into src/fprime_jre/runtime. Runs at
wheel-build time in CI (one job per platform), never on user machines.

    python build_runtime.py            # download Temurin and build the image
    python build_runtime.py --jdk DIR  # build from an already-unpacked Temurin JDK

Set SETUPTOOLS_SCM_PRETEND_VERSION=<version> to build for a version that is not yet tagged.
"""

import argparse
import hashlib
import json
import platform
import re
import shutil
import subprocess
import tarfile
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

import setuptools_scm

ROOT = Path(__file__).resolve().parent
RUNTIME_DIR = ROOT / "src" / "fprime_jre" / "runtime"
BUILD_DIR = ROOT / "build" / "temurin"

# Version-range lookup: [JAVA_VERSION, next) also matches later point releases (17.0.4 -> 17.0.4.1),
# so results are filtered on the exact openjdk_version
ADOPTIUM_API = "https://api.adoptium.net/v3/assets/version/{range}"
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


def package_version() -> str:
    """Package version from the git tag (or SETUPTOOLS_SCM_PRETEND_VERSION), as the wheel will carry it"""
    try:
        return setuptools_scm.get_version(root=ROOT)
    except LookupError as error:
        raise SystemExit(f"Cannot determine the version from git: {error}") from None


def expected_java_version(version: str) -> str:
    """JAVA_VERSION implied by a package version: the release segment minus the repackaging number"""
    release = re.match(r"\d+(?:\.\d+)*", version)
    parts = release.group(0).split(".") if release else []
    if len(parts) < 2:
        raise SystemExit(f"Version {version!r} must be <JAVA_VERSION>.<repackaging number>, e.g. 25.0.4.1.0")
    return ".".join(parts[:-1])


def host_target() -> tuple:
    """Adoptium (os, architecture) names for the build host"""
    try:
        return ADOPTIUM_OS[platform.system()], ADOPTIUM_ARCH[platform.machine().lower()]
    except KeyError:
        raise SystemExit(f"Unsupported build host: {platform.system()} {platform.machine()}") from None


def fetch_asset(os_name: str, arch: str, java_version: str) -> dict:
    """Look up the JDK package (link, checksum, name) of the latest GA Temurin build of a JAVA_VERSION"""
    parts = java_version.split(".")
    upper = ".".join(parts[:-1] + [str(int(parts[-1]) + 1)])
    query = urllib.parse.urlencode(
        {
            "os": os_name,
            "architecture": arch,
            "image_type": "jdk",
            "heap_size": "normal",
            "project": "jdk",
            "release_type": "ga",
            "vendor": "eclipse",
        }
    )
    url = ADOPTIUM_API.format(range=urllib.parse.quote(f"[{java_version},{upper})")) + "?" + query
    print(f"[INFO] Querying {url}")
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": USER_AGENT})) as response:
        releases = json.load(response)
    releases = [r for r in releases if r["version_data"]["openjdk_version"].split("+")[0] == java_version]
    if not releases:
        raise SystemExit(f"No GA Temurin {java_version} JDK for {os_name}/{arch} on Adoptium")
    release = max(releases, key=lambda r: r["version_data"]["build"])
    print(f"[INFO] Using Temurin {release['release_name']}")
    binaries = [b for b in release["binaries"] if b["os"] == os_name and b["architecture"] == arch]
    if len(binaries) != 1:
        raise SystemExit(f"Expected one {os_name}/{arch} binary for {release['release_name']}, found {len(binaries)}")
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

    version = package_version()
    expected = expected_java_version(version)
    print(f"[INFO] Package version {version}: bundling Temurin JAVA_VERSION {expected}")
    if args.jdk:
        jdk_home = find_jdk_home(args.jdk)
    else:
        jdk_home = extract(download(fetch_asset(*host_target(), expected)))
    actual = java_version(jdk_home)
    if actual != expected:
        raise SystemExit(f"JDK at {jdk_home} is JAVA_VERSION {actual}; package version {version} expects {expected}")

    jlink(jdk_home, args.output)
    print(f"[INFO] Runtime image written to {args.output}")


if __name__ == "__main__":
    main()
