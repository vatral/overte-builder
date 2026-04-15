"""Desktop notification helpers for build status updates."""

from __future__ import annotations

import sys
import time
from enum import IntEnum

try:
    import dbus
except ImportError:  # pragma: no cover - depends on local desktop environment
    dbus = None


class Urgency(IntEnum):
    """Freedesktop urgency levels."""

    Low = 0
    Normal = 1
    High = 2


class Notifier:
    """Send desktop notifications through the Freedesktop DBus API."""

    def __init__(self, title: str = ""):
        self.title = title
        self.previous_id = 0
        self.previous_id_first_use = time.time()
        self.previous_time = time.time()
        self.min_update_time = 3
        self.max_duration = 60
        self.application_name = "Overte Builder"

        self.notify_iface = None
        if dbus is None:
            return

        try:
            bus = dbus.SessionBus()
            notify_obj = bus.get_object(
                "org.freedesktop.Notifications", "/org/freedesktop/Notifications"
            )
            self.notify_iface = dbus.Interface(
                notify_obj,
                "org.freedesktop.Notifications",
            )
        except Exception as exc:  # pragma: no cover - env dependent
            print(f"Notification init failed: {exc}", file=sys.stderr)
            self.notify_iface = None

    def notify(
        self,
        message: str,
        urgency: Urgency = Urgency.Normal,
        replaces_id: int = 0,
        replace_previous: bool = False,
    ) -> int:
        """Send a desktop notification if DBus notifications are available."""
        if self.notify_iface is None or dbus is None:
            return 0

        if replace_previous:
            replaces_id = self.previous_id

        if replaces_id != 0:
            current_time = time.time()
            elapsed_since_first_use = current_time - self.previous_id_first_use

            if elapsed_since_first_use > self.max_duration:
                replaces_id = 0
            else:
                elapsed = current_time - self.previous_time
                if elapsed < self.min_update_time:
                    return replaces_id
                self.previous_time = current_time

        try:
            hints = {"urgency": dbus.Byte(urgency)}
            notification_id = self.notify_iface.Notify(
                self.application_name,
                replaces_id,
                "",
                self.title,
                message,
                [],
                hints,
                5000,
            )
        except Exception as exc:  # pragma: no cover - env dependent
            # Ignore rate-limit style failures from some notification daemons.
            if "ExcessNotificationGeneration" not in str(exc):
                print(f"Notification failed: {exc}", file=sys.stderr)
            return 0

        if self.previous_id != notification_id:
            self.previous_id_first_use = time.time()

        self.previous_id = int(notification_id)
        return int(notification_id)
