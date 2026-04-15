from enum import IntEnum
import time
import dbus

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
        except dbus.exceptions.DBusException as de:
            print(f"Notification failed: {e}", file=sys.stderr)
            return 0

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
