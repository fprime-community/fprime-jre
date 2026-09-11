# fprime-jre

A Java runtime you can `pip install`. `fprime-jre` bundles a
[jlink](https://docs.oracle.com/en/java/javase/25/docs/specs/man/jlink.html)-trimmed
[Eclipse Temurin](https://adoptium.net/) Java 25 runtime and puts a `java` command in your
Python environment, so F Prime tools that need Java — [fpp](https://github.com/nasa/fpp)
and [fprime-yamcs](https://github.com/fprime-community/fprime-yamcs) — run on machines with
no Java installed, with no changes to those tools.

```bash
pip install fprime-jre
java -version
# openjdk version "25.0.4.1" 2026-08-18 LTS
# OpenJDK Runtime Environment Temurin-25.0.4.1+1 (build 25.0.4.1+1-LTS)
```

This is a runtime only: it runs JARs. It does not include `javac`, `jar`, `jshell`, sbt, or
anything else needed to *build* Java or Scala software.

## How it works

The wheel installs a `java` console script next to `pip` and `python` in your environment's
`bin/` (`Scripts\` on Windows). Inside a virtual environment that directory precedes the system
`PATH`, so tools that look up `java` on the `PATH` — `fpp-check` and friends, `yamcsd` — find
this one. The script `exec`s the bundled runtime with your arguments, stdio, exit code and
signals unchanged.

Java 25 is the version required by fpp's published JARs and supported by YAMCS.

### Which Java wins?

`java` from `fprime-jre` is unconditional: if it is invoked, the bundled runtime runs. It never
looks at `JAVA_HOME`. Choosing between a Java you already have and this one is the caller's job,
in the conventional `JAVA_HOME` then `PATH` order:

- `yamcsd` uses `$JAVA_HOME/bin/java` when `JAVA_HOME` is set, otherwise `java` on the `PATH`.
- fpp's wrapper currently uses the `PATH` only ([nasa/fpp#1107](https://github.com/nasa/fpp/issues/1107)
  requests `JAVA_HOME` be honoured first).

So: set `JAVA_HOME` and tools use your Java; leave it unset inside an environment with
`fprime-jre` and they use this one. To point other tooling at the bundled runtime:

```bash
export JAVA_HOME="$(fprime-jre)"
```

### From Python

```python
import subprocess
from fprime_jre import JAVA, JAVA_HOME, JAVA_VERSION  # Path, Path, (25, 0, 4, 1)

subprocess.run([str(JAVA), "-jar", "tool.jar"])
```

## Platforms

Wheels are published for Linux x86_64 and aarch64 (glibc 2.17+), macOS x86_64 and arm64
(11.0+), and Windows x64. Alpine/musl is not supported. Wheels are platform-specific but
Python-version independent (`py3-none-<platform>`), for Python 3.8+.

## Versioning

The package version is the Temurin `JAVA_VERSION` followed by a repackaging number:
`25.0.4.1.0` bundles Temurin `jdk-25.0.4.1+1`. Consumers wanting Java 25 can depend on
`fprime-jre>=25,<26`.

## Building

Wheels are built by [CI](.github/workflows/build.yml), one job per platform, since the runtime
must be linked on its target OS. To build locally (Python 3.11+ for the build script):

```bash
python build_runtime.py               # downloads Temurin from Adoptium, verifies SHA-256, runs jlink
python -m build --wheel               # dist/fprime_jre-<version>-py3-none-<platform>.whl
pip install dist/*.whl pytest && pytest tests
```

`FPRIME_JRE_PLATFORM_TAG` overrides the wheel's platform tag (CI sets the manylinux/macosx
tags). Optional integration tests run when `FPRIME_JRE_TEST_FPP_JAR` (path to an `fpp.jar`) or
`FPRIME_JRE_TEST_YAMCS_DIR` (an unpacked YAMCS bundle) are set.

Updating Java: change `TEMURIN_RELEASE` in `build_runtime.py` and the version in
`pyproject.toml` together; the build fails if they disagree. Publishing is by GitHub release
through [publish.yml](.github/workflows/publish.yml) using PyPI trusted publishing.

## License

The Python code in this repository and the bundled OpenJDK runtime are distributed under the
GNU General Public License, version 2, with the Classpath Exception
([LICENSE](LICENSE), [ASSEMBLY_EXCEPTION](ASSEMBLY_EXCEPTION),
[ADDITIONAL_LICENSE_INFO](ADDITIONAL_LICENSE_INFO)). Per-module third-party notices ship inside
the runtime under `legal/`; Temurin's notices are in [NOTICE](NOTICE).

Java and OpenJDK are trademarks or registered trademarks of Oracle and/or its affiliates.
Eclipse Temurin is a trademark of the Eclipse Foundation.
