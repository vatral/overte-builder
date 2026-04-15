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
import dbus
import re
from enum import IntEnum


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

class Urgency(IntEnum):
    Low = 0
    Normal = 1
    High = 2

class Notifier:
    def __init__(self, title = ""):
        self.title = title
        self.previous_id = 0
        self.previous_id_first_use = time.time()
        self.previous_time = time.time()
        self.min_update_time = 3
        self.max_duration = 60

        self.application_name = "Overte Builder"


        bus = dbus.SessionBus()
        notify_obj = bus.get_object('org.freedesktop.Notifications', '/org/freedesktop/Notifications')
        self.notify_iface = dbus.Interface(notify_obj, 'org.freedesktop.Notifications')


    def notify(self, message, urgency : Urgency = Urgency.Normal, replaces_id = 0, replace_previous = False) -> int:
        """Send a desktop notification via KDE's DBus interface."""


        if replace_previous:
            replaces_id = self.previous_id

        if replaces_id != 0:
            current_time = time.time()
            elapsed_since_first_use = current_time - self.previous_id_first_use

            if elapsed_since_first_use > self.max_duration:
                # Our notification has lasted too long, we want a new one.
                replaces_id = 0
            else:
                elapsed = current_time - self.previous_time

                if elapsed < self.min_update_time:
                    # In "replaces" mode we're rapidly updating a notification, limit it
                    # a bit
                    return replaces_id

                self.previous_time = current_time

        try:

            hints = {}

            #urgency_level = {'low': 0, 'normal': 1, 'high': 2}.get(urgency, 1)
            hints['urgency'] = dbus.Byte(urgency)

            id = self.notify_iface.Notify(
                self.application_name,
                replaces_id,
                "",
                self.title,
                message,
                [],
                hints,
                5000
            )
        except Exception as e:
            # Ignore excess notifications, we're drawing a progress bar, so it's a possibility it won't like it.
            if not "org.freedesktop.Notifications.Error.ExcessNotificationGeneration" in e:
                print(f"Notification failed: {e}", file=sys.stderr)
                return 0

        #print(f"Message returning id {id}")
        if self.previous_id != id:
            self.previous_id_first_use = time.time()

        self.previous_id = id
        return id


def run_command(cmd, cwd=None, log_file=None, callback=None):
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

                        decoded = data.decode(errors="replace")
                        print(decoded, end="")

                        if callback:
                            try:
                                callback(decoded)
                            except Exception as ex:
                                print(f"Error in callback: {ex}")

                        f.write(data)
                    if proc.poll() is not None:
                        break

                returncode = proc.wait()

    else:
        result = subprocess.run(cmd, cwd=cwd)
        returncode = result.returncode

    return returncode == 0

def unicode_progress_bar(percent: float, width: int = 12) -> str:
    """
    Return a Unicode progress bar like:
    ████████▌░░ 71%

    percent: 0..100
    width: number of bar cells
    """
    # Clamp to valid range
    percent = max(0.0, min(100.0, percent))

    # Partial block characters from empty to full
    partials = ["", "▏", "▎", "▍", "▌", "▋", "▊", "▉", "█"]

    total_units = width * 8
    filled_units = round((percent / 100.0) * total_units)

    full_blocks = filled_units // 8
    remainder = filled_units % 8

    bar = "█" * full_blocks

    if full_blocks < width and remainder > 0:
        bar += partials[remainder]

    bar += "░" * (width - len(bar))

    return f"{bar} {percent:>3.0f}%"


def ninja_build_progress(output : str, notifier : Notifier, message_id = 0):
    # CMake uses \r to print stuff on the same line, strip that
    output = output.replace("\r", "")

    ret = re.match(r"^\[(\d+)\/(\d+)\] (.*?)$", output, flags=re.MULTILINE)

    if ret:
        progress = int(ret.group(1))
        total = int(ret.group(2))
        file = ret.group(3)

        percent = (100/total) * progress
        unicode_bar = unicode_progress_bar(percent, width = 20)

        notifier.notify(unicode_bar, replaces_id=message_id)


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
    parser.add_argument("--skip-cmake", action='store_true', help="Skip CMake invocation")

    parser.add_argument("--build", action='store_true', help="Run a compilation. Without this option it only runs conan and cmake.")
    parser.add_argument("--incremental-build", action='store_true', help="Run a compilation incrementally. Skips conan and cmake, and builds without cleaning the tree.")
    parser.add_argument("--vulkan", action='store_true', help="Build with the Vulkan renderer")


    notifier = Notifier()
    args = parser.parse_args()

    if args.incremental_build:
        args.build = True
        args.skip_conan = True
        args.skip_cmake = True


    status_message = "Building"
    build_name = "Release"
    output_dir = "out/Release"
    cmake_preset = "conan-release"
    conan_build_type = "Release"

    if args.debug:
        output_dir = "out/Debug"
        cmake_preset = "conan-debug"
        build_name = "Debug"
        conan_build_type = "Debug"
    else:
        build_name = "Release"
        conan_build_type = "Release"

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
        print(f"{Fore.RED}Warning: Building with sanitizer but not in debug mode. Non-debug build will be built.{Fore.RESET}", flush=True)
        time.sleep(3)


    if not args.skip_conan and not args.skip_cmake:
        if Path(output_dir).exists():
            shutil.rmtree(output_dir)

    # Run Conan install
    if not args.skip_conan:
        notifier.notify(message = "Running Conan")

        conan_cmd = [
            "conan",
            "install",
            ".",
            "-s", "build_type=" + conan_build_type,
            "--build=missing",
            "-pr:b=default",
            "-of", output_dir,
        ]

        with CommandTimer() as tmr:
            if not run_command(conan_cmd, log_file="conan.log"):
                print("Conan install failed after {tmr.hhmmss}")
                notifier.notify(message="Conan install failed after {tmr.hhmmss}", urgency=Urgency.High)
                return 1

        print(f"{Fore.GREEN}Conan install succeeded after {tmr.hhmmss}{Fore.RESET}")

    # Run CMake
    if not args.skip_cmake:
        extra_cxxflags=""
        #if args.debug:


        cmake_cmd = [
            "cmake",
            "--preset", cmake_preset,
            "-G", "Ninja",
            "-DCMAKE_EXE_LINKER_FLAGS=-fuse-ld=mold",
            "-DCMAKE_SHARED_LINKER_FLAGS=-fuse-ld=mold",
            "-DCMAKE_CXX_FLAGS=-fdiagnostics-color=always -fdiagnostics-generate-patch -fdiagnostics-text-art-charset=emoji --param=max-vartrack-size=0"
        ]

        if args.asan:
            cmake_cmd += [ "-DOVERTE_MEMORY_DEBUGGING=ON" ]

        if args.tsan:
            cmake_cmd += [ "-DOVERTE_THREAD_DEBUGGING=ON" ]

        if args.vulkan:
            cmake_cmd += [ "-DOVERTE_RENDERING_BACKEND=Vulkan" ]

        notifier.notify(message = "Running CMake")

        with CommandTimer() as tmr:
            if not run_command(cmake_cmd, log_file="cmake.log"):
                print(f"CMake configuration failed after {tmr.hhmmss}")
                notifier.notify(message=f"CMake configuration failed after {tmr.hhmmss}", urgency=Urgency.High)

                return 1

            print(f"{Fore.GREEN}Generated CMake files in {Fore.WHITE}{output_dir}{Fore.GREEN} in in {tmr.hhmmss}{Fore.RESET}")

    # Build
    if args.build:
        build_cmd = ["cmake", "--build", output_dir]
        building_id = notifier.notify(message = "Compiling")


        start_time = time.time()

        with CommandTimer() as tmr:
            if not run_command(build_cmd, log_file="build.log", callback=lambda msg: ninja_build_progress(msg, notifier=notifier, message_id=building_id)):
                notifier.notify(message=f"Compilation failed after {tmr.hhmmss}", urgency = Urgency.High)
                print(f"Build failed after {tmr.hhmmss}")
                return 1

        notifier.notify(message=f"Build successfully completed in {tmr.hhmmss}", urgency = Urgency.Low)
        print(f"{Fore.GREEN}Successfully built {Fore.BLUE}{build_name}{Fore.GREEN} in {Fore.WHITE}{output_dir}{Fore.GREEN} in {tmr.hhmmss}{Fore.RESET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())