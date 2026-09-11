"""Entry points for the `java` and `fprime-jre` console scripts

`java` always runs the bundled runtime: it never consults JAVA_HOME or the PATH. Callers that
want to prefer a user-selected JVM must do so themselves before falling back to `java`.
"""

import os
import subprocess
import sys

from fprime_jre import JAVA, JAVA_HOME, JAVA_VERSION


def main():
    """Run the bundled `java` with this process's arguments, stdio and exit status"""
    if not JAVA.is_file():
        print(f"[ERROR] fprime-jre runtime is missing: {JAVA}", file=sys.stderr)
        sys.exit(1)
    argv = [str(JAVA)] + sys.argv[1:]
    if os.name != "nt":
        os.execv(str(JAVA), argv)
    # Windows has no exec: run as a child and forward Ctrl-C to it by waiting it out
    process = subprocess.Popen(argv)
    while True:
        try:
            sys.exit(process.wait())
        except KeyboardInterrupt:
            continue


def info():
    """Print the bundled runtime's JAVA_HOME (for `export JAVA_HOME=$(fprime-jre)`) or its version"""
    if "--version" in sys.argv[1:]:
        print(".".join(str(part) for part in JAVA_VERSION))
    else:
        print(JAVA_HOME)


if __name__ == "__main__":
    main()
