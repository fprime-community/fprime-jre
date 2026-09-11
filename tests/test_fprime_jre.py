"""Tests for the installed fprime-jre wheel: run against an environment where it is pip-installed

Optional integration inputs:
  FPRIME_JRE_TEST_FPP_JAR   path to an fpp.jar published by the fpp build; runs fpp-check on it
  FPRIME_JRE_TEST_YAMCS_DIR path to an unpacked YAMCS bundle (bin/yamcsd); starts it and checks logs
"""

import os
import shutil
import subprocess
import sysconfig
import tempfile
import time
from pathlib import Path

import pytest

import fprime_jre

EXE = ".exe" if os.name == "nt" else ""


def run(*args, **kwargs):
    return subprocess.run(list(args), capture_output=True, text=True, timeout=120, check=False, **kwargs)


def test_paths_exist():
    assert fprime_jre.JAVA_HOME.is_dir()
    assert fprime_jre.JAVA.is_file()
    assert (fprime_jre.JAVA_HOME / "release").is_file()
    assert (fprime_jre.JAVA_HOME / "legal" / "java.base" / "LICENSE").is_file()


def test_java_version_matches_package_version():
    from importlib.metadata import version

    package = tuple(int(part) for part in version("fprime-jre").split("."))
    assert fprime_jre.JAVA_VERSION == package[:-1]
    assert fprime_jre.JAVA_VERSION[0] == 25


def test_bundled_java_reports_temurin_25():
    result = run(str(fprime_jre.JAVA), "-version")
    assert result.returncode == 0
    assert 'openjdk version "25.' in result.stderr
    assert "Temurin" in result.stderr


def test_java_shim_is_on_path_and_runs_bundled_runtime():
    scripts = sysconfig.get_path("scripts")
    java = shutil.which("java", path=scripts)
    assert java, f"no java console script in {scripts}"
    result = run(java, "-XshowSettings:properties", "-version")
    assert result.returncode == 0
    assert f"java.home = {fprime_jre.JAVA_HOME}" in result.stderr
    assert "Temurin-25." in result.stderr


def test_shim_ignores_java_home():
    java = shutil.which("java", path=sysconfig.get_path("scripts"))
    env = dict(os.environ, JAVA_HOME="/nonexistent/jdk")
    result = run(java, "-XshowSettings:properties", "-version", env=env)
    assert result.returncode == 0
    assert "Temurin-25." in result.stderr


def test_shim_forwards_arguments_stdio_and_exit_code():
    java = shutil.which("java", path=sysconfig.get_path("scripts"))
    result = run(java, "-Dfprime.jre.test=hello world", "-XshowSettings:properties", "-XX:+PrintFlagsFinal", "-version")
    assert result.returncode == 0
    assert "fprime.jre.test = hello world" in result.stderr
    assert "MaxHeapSize" in result.stdout
    result = run(java, "-cp", "nonexistent", "no.such.Main")
    assert result.returncode == 1
    assert "no.such.Main" in result.stderr


def test_runtime_is_runtime_only():
    for tool in ("javac", "jar", "javadoc", "jshell", "jlink", "jdeps"):
        assert not (fprime_jre.JAVA_HOME / "bin" / f"{tool}{EXE}").exists(), tool
    assert not (fprime_jre.JAVA_HOME / "jmods").exists()


def test_info_script():
    info = shutil.which("fprime-jre", path=sysconfig.get_path("scripts"))
    assert info
    assert Path(run(info).stdout.strip()) == fprime_jre.JAVA_HOME
    assert run(info, "--version").stdout.strip() == ".".join(map(str, fprime_jre.JAVA_VERSION))


@pytest.mark.skipif(not os.environ.get("FPRIME_JRE_TEST_FPP_JAR"), reason="FPRIME_JRE_TEST_FPP_JAR not set")
def test_fpp_jar_runs(tmp_path):
    jar = os.environ["FPRIME_JRE_TEST_FPP_JAR"]
    model = tmp_path / "M.fpp"
    model.write_text("module M { struct S { x: U32 } }\n")
    java = shutil.which("java", path=sysconfig.get_path("scripts"))
    flags = ["--sun-misc-unsafe-memory-access=allow", "--enable-native-access=ALL-UNNAMED"]
    result = run(java, *flags, "-jar", jar, "check", str(model))
    assert result.returncode == 0, result.stderr
    result = run(java, *flags, "-jar", jar, "to-json", "-d", str(tmp_path), str(model))
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "fpp-ast.json").is_file()


@pytest.mark.skipif(not os.environ.get("FPRIME_JRE_TEST_YAMCS_DIR"), reason="FPRIME_JRE_TEST_YAMCS_DIR not set")
@pytest.mark.skipif(os.name == "nt", reason="yamcsd is a shell script")
def test_yamcs_starts():
    yamcs = Path(os.environ["FPRIME_JRE_TEST_YAMCS_DIR"])
    env = {k: v for k, v in os.environ.items() if k != "JAVA_HOME"}
    env["PATH"] = sysconfig.get_path("scripts") + os.pathsep + env.get("PATH", "")
    with tempfile.TemporaryFile("w+") as log:
        process = subprocess.Popen(
            [str(yamcs / "bin" / "yamcsd")], cwd=yamcs, env=env, stdout=log, stderr=subprocess.STDOUT
        )
        try:
            deadline = time.time() + 90
            while time.time() < deadline and process.poll() is None:
                log.seek(0)
                if "Yamcs started" in log.read():
                    break
                time.sleep(1)
        finally:
            process.terminate()
            process.wait(timeout=30)
        log.seek(0)
        output = log.read()
    assert "Yamcs started" in output, output[-4000:]
