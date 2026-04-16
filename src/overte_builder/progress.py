
#!/usr/bin/env python3

from abc import ABC, abstractmethod
import os
from typing import Mapping

try:
    import dbus  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - depends on local desktop environment
    dbus = None

from .notifier import Notifier

class ProgressBarNotifier(ABC):
    """Generic base for progress bar notification backends."""

    def __init__(self, title: str = ""):
        self.title = title

    @abstractmethod
    def start(self, message: str) -> None:
        """Start a progress notification sequence."""

    @abstractmethod
    def update(self, progress: float, message: str = "") -> None:
        """Update the current progress state."""

    @abstractmethod
    def finish(self, message: str = "") -> None:
        """Complete and close the progress notification sequence."""


class KDEProgressBarNotifier(ProgressBarNotifier):
    """KDE progress notifications via JobViewServerV2."""

    def __init__(self, title: str = ""):
        super().__init__(title=title)
        self.desktop_entry = "overte-builder"
        self.application_name = "Overte Builder"
        self.application_icon_name = "applications-development"
        self.capabilities = 0

        self._bus = None
        self._service_name = None
        self._server_iface = None
        self._job_view_iface = None

        if dbus is None:
            return

        try:
            self._bus = dbus.SessionBus()
        except Exception:
            self._bus = None

    def _safe_call(self, method_name: str, *args) -> None:
        """Call a JobView method if available and ignore runtime DBus failures."""
        if self._job_view_iface is None:
            return
        method = getattr(self._job_view_iface, method_name, None)
        if not callable(method):
            return
        try:
            method(*args)
        except Exception:
            pass

    def _bind_server_iface(self) -> bool:
        """Bind to a running KDE JobView server if one is available."""
        if self._bus is None or dbus is None:
            return False

        for service_name in ("org.kde.JobViewServer", "org.kde.kuiserver"):
            try:
                server_obj = self._bus.get_object(service_name, "/JobViewServer")
                self._server_iface = dbus.Interface(server_obj, "org.kde.JobViewServerV2")
                self._service_name = service_name
                return True
            except Exception as ex:
                print(f"Exception in _bind_server_iface: {ex}")
                continue

        self._server_iface = None
        self._service_name = None
        return False

    def _ensure_job_view(self) -> bool:
        """Create a JobViewV2 object for this notifier if needed."""
        if self._job_view_iface is not None:
            return True

        if self._server_iface is None and not self._bind_server_iface():
            return False

        try:
            hints = dbus.Dictionary(
                {
                    "application-name": dbus.String(self.application_name),
                    "application-icon-name": dbus.String(self.application_icon_name),
                },
                signature="sv",
            )
            view_path = self._server_iface.requestView(
                self.desktop_entry,
                dbus.Int32(self.capabilities),
                hints,
            )
            view_obj = self._bus.get_object(self._service_name, view_path)
            self._job_view_iface = dbus.Interface(view_obj, "org.kde.JobViewV2")
            return True
        except Exception as ex:
            print(f"Exception in _ensure_job_view: {ex}")
            self._job_view_iface = None
            return False

    def start(self, message: str) -> None:
        if not self._ensure_job_view() or dbus is None:
            return

        self._safe_call("setPercent", dbus.UInt32(0))
        self._safe_call("setInfoMessage", message)
        if self.title:
            self._safe_call("setDescriptionField", dbus.UInt32(0), "Task", self.title)

    def update(self, progress: float, message: str = "") -> None:
        if not self._ensure_job_view() or dbus is None:
            return

        bounded = max(0.0, min(100.0, progress))
        self._safe_call("setPercent", dbus.UInt32(int(round(bounded))))
        if message:
            self._safe_call("setInfoMessage", message)

    def finish(self, message: str = "") -> None:
        if self._job_view_iface is None or dbus is None:
            return

        self._safe_call("setPercent", dbus.UInt32(100))
        if message:
            self._safe_call("setInfoMessage", message)
        self._safe_call("terminate", "")
        self._job_view_iface = None


class GenericProgressBarNotifier(ProgressBarNotifier):
    """Non-KDE progress bar notifier scaffold."""

    def __init__(self, title: str = ""):
        super().__init__(title=title)
        self._notifier = Notifier()
        self._notifier.title = title or "Overte Builder"


    def _unicode_progress_bar(self, percent: float, width: int = 12) -> str:
        """Return a compact progress bar plus integer percentage."""
        percent = max(0.0, min(100.0, percent))

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


    def start(self, message: str) -> None:
        self._notifier.notify("Building")

    def update(self, progress: float, message: str = "") -> None:
        self._notifier.notify(self._unicode_progress_bar(progress), replace_previous=True)

    def finish(self, message: str = "") -> None:
        self._notifier.notify(message)


def is_kde_session(environment: Mapping[str, str] | None = None) -> bool:
    """Detect whether the current desktop session appears to be KDE."""
    env = dict(environment or os.environ)

    kde_full_session = env.get("KDE_FULL_SESSION", "")
    xdg_current_desktop = env.get("XDG_CURRENT_DESKTOP", "")
    desktop_session = env.get("DESKTOP_SESSION", "")

    if kde_full_session.lower() in {"1", "true"}:
        return True

    desktop_markers = f"{xdg_current_desktop}:{desktop_session}".lower()
    return "kde" in desktop_markers or "plasma" in desktop_markers


def create_progress_bar_notifier(title: str = "") -> ProgressBarNotifier:
    """Select a progress bar notifier implementation based on desktop session."""
    if is_kde_session():
        return KDEProgressBarNotifier(title=title)
    return GenericProgressBarNotifier(title=title)