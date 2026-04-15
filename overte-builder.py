#!/usr/bin/env python3
"""Build script for Overte using Conan and CMake."""

import argparse
import subprocess
import sys
from pathlib import Path
import time
from colorama import Fore, init
import shutil
import pty
import select
import os


def run_command(cmd, cwd=None, log_file=None):
    """Execute a command and return the result."""
    print(f"Running: {' '.join(cmd)}")

    if log_file:
        master_fd, slave_fd = pty.openpty()

        with open(log_file, 'ab') as f:
            f.write(f"Running: {' '.join(cmd)}\n".encode())
            f.flush()

            #with subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True) as proc:
            with subprocess.Popen(cmd, cwd=cwd, stdin=slave_fd, stdout=slave_fd, stderr=slave_fd, text=True, close_fds=True) as proc:
                while True:
                    read_fds, _, _ = select.select([master_fd], [], [], 0.1)
                    if master_fd in read_fds:
                        try:
                            data = os.read(master_fd, 1024)
                        except OSError:
                            break
                        if not data:
                            break
                        print(data.decode(errors="replace"), end="")
                        f.write(data)
                    if proc.poll() is not None:
                        break

                returncode = proc.wait()

    else:
        result = subprocess.run(cmd, cwd=cwd)
        returncode = result.returncode

    return returncode == 0


def main():

    init()

    parser = argparse.ArgumentParser(
        description="Build script for Overte",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument("--debug", action='store_true', help="Debug mode")
    parser.add_argument("--asan",  action='store_true', help="Build with Address Sanitizer")
    parser.add_argument("--tsan", action='store_true', help="Build with Thread Sanitizer")
    parser.add_argument("--skip-conan", action='store_true', help="Skip Conan invocation")
    parser.add_argument("--build", action='store_true', help="Run a compilation")


    args = parser.parse_args()

    output_dir = "out/Release"
    cmake_preset = "conan-release"

    if args.debug:
        output_dir = "out/Debug"
        cmake_preset = "conan-debug"

    if args.asan:
        output_dir = output_dir + "ASAN"

    if args.tsan:
        output_dir = output_dir + "TSAN"


    if (args.asan or args.tsan) and not args.debug:
        print(f"{Fore.RED}Warning: Building with sanitizer but not in debug mode. Non-debug build will be built.{Fore.RESET}", flush=True)
        time.sleep(3)

    if Path(output_dir).exists():
        shutil.rmtree(output_dir)

    # Run Conan install
    if not args.skip_conan:
        conan_cmd = [
            "conan",
            "install",
            ".",
            "--build=missing",
            "-pr:b=default",
            "-of", output_dir,
        ]
        if not run_command(conan_cmd, log_file="conan.log"):
            print("Conan install failed")
            return 1

    # Run CMake
    cmake_cmd = [
        "cmake",
        "--preset", cmake_preset,
        "-G", "Ninja"
    ]

    if not run_command(cmake_cmd, log_file="cmake.log"):
        print("CMake configuration failed")
        return 1

    print(f"{Fore.GREEN}Generated files in {Fore.WHITE}{output_dir}{Fore.RESET}")

    # Build
    if args.build:
        build_cmd = ["cmake", "--build", output_dir]
        if not run_command(build_cmd, log_file="build.log"):
            print("Build failed")
            return 1

        print(f"Build completed successfully in {output_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())