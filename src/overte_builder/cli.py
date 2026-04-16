"""Build script for Overte using Conan and CMake."""

from __future__ import annotations

import argparse
import os
import pty
import re
import select
import shutil
import subprocess
import time
import sys

from pathlib import Path
from typing import Callable

from colorama import Fore, init

from .notifier import Notifier, Urgency
from .progress import ProgressBarNotifier, create_progress_bar_notifier

class CommandTimer:
    """Timer that can be used as a context manager and queried at any time."""

    def __init__(self):
        self._start = time.monotonic()
        self._end = None

    def __enter__(self):
        if self._start is None:
            self._start = time.monotonic()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.stop()

    def stop(self) -> float:
        if self._end is None:
            self._end = time.monotonic()
        return self.elapsed_seconds

    @property
    def elapsed_seconds(self) -> float:
        if self._start is None:
            return 0.0
        end = self._end if self._end is not None else time.monotonic()
        return max(0.0, end - self._start)

    @property
    def hhmmss(self) -> str:
        total = int(self.elapsed_seconds)
        hours, remainder = divmod(total, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def run_command(
    cmd: list[str],
    cwd: str | os.PathLike[str] | None = None,
    log_file: str | None = None,
    callback: Callable[[str], None] | None = None,
) -> bool:
    """Execute a command and stream output to terminal and optional log."""
    print(f"Running: {' '.join(cmd)}")

    if log_file:
        master_fd, slave_fd = pty.openpty()

        with open(log_file, "ab") as f:
            f.write(f"Running: {' '.join(cmd)}\n".encode())
            f.flush()

            with subprocess.Popen(
                cmd,
                cwd=cwd,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                text=True,
                close_fds=True,
            ) as proc:
                while True:
                    read_fds, _, _ = select.select([master_fd], [], [], 0.1)
                    if master_fd in read_fds:
                        try:
                            data = os.read(master_fd, 1024)
                        except OSError:
                            break
                        if not data:
                            break

                        decoded = data.decode(errors="replace")
                        print(decoded, end="")

                        if callback:
                            try:
                                callback(decoded)
                            except Exception as exc:
                                print(f"Error in callback: {exc}")

                        f.write(data)
                    if proc.poll() is not None:
                        break

                returncode = proc.wait()
    else:
        result = subprocess.run(cmd, cwd=cwd)
        returncode = result.returncode

    return returncode == 0




def ninja_build_progress(output: str, progress_notifier: ProgressBarNotifier) -> None:
    """Parse Ninja output and publish progress notifications."""
    output = output.replace("\r", "")

    result = re.match(r"^\[(\d+)\/(\d+)\] (.*?)$", output, flags=re.MULTILINE)

    if result:
        completed = int(result.group(1))
        total = int(result.group(2))

        percent = (100 / total) * completed
        progress_notifier.update(percent)


def main() -> int:
    """CLI entry point."""
    init()

    parser = argparse.ArgumentParser(
        description="Build script for Overte",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument("--debug", action="store_true", help="Debug mode")
    parser.add_argument("--asan", action="store_true", help="Build with Address Sanitizer")
    parser.add_argument("--tsan", action="store_true", help="Build with Thread Sanitizer")
    parser.add_argument("--skip-conan", action="store_true", help="Skip Conan invocation")
    parser.add_argument("--skip-cmake", action="store_true", help="Skip CMake invocation")
    parser.add_argument(
        "--build",
        action="store_true",
        help="Run compilation. Without this option it only runs conan and cmake.",
    )
    parser.add_argument(
        "--incremental-build",
        action="store_true",
        help="Run incremental compilation: skip conan/cmake and do not clean output.",
    )
    parser.add_argument(
        "--vulkan",
        action="store_true",
        help="Build with the Vulkan renderer",
    )
    parser.add_argument("--test-progress", action="store_true", help="Test the progress bar")

    notifier = Notifier()
    args = parser.parse_args()


    if args.test_progress:
        progress = create_progress_bar_notifier()
        progress.start("Testing")
        for x in range(0,10):
            progress.update((100/10)*x)
            time.sleep(1)
        progress.finish()

        sys.exit(0)


    if args.incremental_build:
        args.build = True
        args.skip_conan = True
        args.skip_cmake = True

    build_name = "Release"
    output_dir = "out/Release"
    cmake_preset = "conan-release"
    conan_build_type = "Release"

    if args.debug:
        output_dir = "out/Debug"
        cmake_preset = "conan-debug"
        build_name = "Debug"
        conan_build_type = "Debug"

    if args.vulkan:
        output_dir = output_dir + "Vulkan"
        build_name = build_name + " Vulkan"
    else:
        output_dir = output_dir + "OpenGL"
        build_name = build_name + " OpenGL"

    if args.asan:
        output_dir = output_dir + "ASAN"
        build_name = build_name + " with ASAN"

    if args.tsan:
        output_dir = output_dir + "TSAN"
        build_name = build_name + " with TSAN"

    status_message = "Building " + build_name
    notifier.title = status_message

    if (args.asan or args.tsan) and not args.debug:
        print(
            (
                f"{Fore.RED}Warning: Building with sanitizer but not in debug mode. "
                "Non-debug build will be built."
                f"{Fore.RESET}"
            ),
            flush=True,
        )
        time.sleep(3)

    if not args.skip_conan and not args.skip_cmake and Path(output_dir).exists():
        shutil.rmtree(output_dir)

    if not args.skip_conan:
        notifier.notify(message="Running Conan")

        conan_cmd = [
            "conan",
            "install",
            ".",
            "-s",
            "build_type=" + conan_build_type,
            "--build=missing",
            "-pr:b=default",
            "-of",
            output_dir,
        ]

        with CommandTimer() as tmr:
            if not run_command(conan_cmd, log_file="conan.log"):
                print(f"Conan install failed after {tmr.hhmmss}")
                notifier.notify(
                    message=f"Conan install failed after {tmr.hhmmss}",
                    urgency=Urgency.High,
                )
                return 1

        print(f"{Fore.GREEN}Conan install succeeded after {tmr.hhmmss}{Fore.RESET}")

    if not args.skip_cmake:
        cmake_cmd = [
            "cmake",
            "--preset",
            cmake_preset,
            "-G",
            "Ninja",
            "-DCMAKE_EXE_LINKER_FLAGS=-fuse-ld=mold",
            "-DCMAKE_SHARED_LINKER_FLAGS=-fuse-ld=mold",
            (
                "-DCMAKE_CXX_FLAGS=-fdiagnostics-color=always "
                "-fdiagnostics-generate-patch "
                "-fdiagnostics-text-art-charset=emoji --param=max-vartrack-size=0"
            ),
        ]

        if args.asan:
            cmake_cmd += ["-DOVERTE_MEMORY_DEBUGGING=ON"]

        if args.tsan:
            cmake_cmd += ["-DOVERTE_THREAD_DEBUGGING=ON"]

        if args.vulkan:
            cmake_cmd += ["-DOVERTE_RENDERING_BACKEND=Vulkan"]

        notifier.notify(message="Running CMake")

        with CommandTimer() as tmr:
            if not run_command(cmake_cmd, log_file="cmake.log"):
                print(f"CMake configuration failed after {tmr.hhmmss}")
                notifier.notify(
                    message=f"CMake configuration failed after {tmr.hhmmss}",
                    urgency=Urgency.High,
                )
                return 1

            print(
                (
                    f"{Fore.GREEN}Generated CMake files in {Fore.WHITE}{output_dir}"
                    f"{Fore.GREEN} in {tmr.hhmmss}{Fore.RESET}"
                )
            )

    if args.build:
        build_cmd = ["cmake", "--build", output_dir]
        building_id = notifier.notify(message="Compiling")

        progress = create_progress_bar_notifier()
        progress.start(status_message)

        with CommandTimer() as tmr:
            if not run_command(
                build_cmd,
                log_file="build.log",
                callback=lambda msg: ninja_build_progress(
                    msg,
                    progress_notifier=progress,
                ),
            ):
                notifier.notify(
                    message=f"Compilation failed after {tmr.hhmmss}",
                    urgency=Urgency.High,
                )
                print(f"Build failed after {tmr.hhmmss}")
                return 1

        notifier.notify(
            message=f"Build successfully completed in {tmr.hhmmss}",
            urgency=Urgency.Low,
        )
        print(
            (
                f"{Fore.GREEN}Successfully built {Fore.BLUE}{build_name}{Fore.GREEN} "
                f"in {Fore.WHITE}{output_dir}{Fore.GREEN} in {tmr.hhmmss}{Fore.RESET}"
            )
        )

    return 0
