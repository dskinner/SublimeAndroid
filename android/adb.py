import os
import re
import subprocess
import telnetlib
import traceback

import sublime
import sublime_plugin

from . import project
from .util import get_setting, logger

log = logger(__name__)


def get_devices():
    """Gets a list of devices currently attached.

    Querys `adb` from `get_sdk_dir()` for all emulator/device instances.

    Returns:
        A tuple of lists. The first value is a list of device ids suitable for
        use in selecting a device when calling adb. The second value is a list
        of strings suitable for displaying text more descriptive to the use to
        choose an appropriate device.
    """
    adb = os.path.join(project.get_sdk_dir(), "platform-tools", "adb")
    cmd = [adb, "devices"]
    try:
        proc = subprocess.Popen(cmd, shell=False, stdout=subprocess.PIPE)
        out, err = proc.communicate()
    except:
        sublime.error_message("Error trying to launch ADB:\n\n{0}\n\n{1}".format(cmd, traceback.format_exc()))
        return
    # get list of device ids
    devices = []
    out = str(out, "utf-8")
    for line in out.split("\n"):
        line = line.strip()
        if line not in ["", "List of devices attached"]:
            devices.append(re.sub(r"[ \t]*device$", "", line))
    # build quick menu options displaying name, version, and device id
    options = []
    for device in devices:
        # dump build.prop
        cmd = [adb, "-s", device, "shell", "cat /system/build.prop"]
        proc = subprocess.Popen(cmd, shell=False, stdout=subprocess.PIPE)
        build_prop = str(proc.stdout.read().strip(), "utf-8")
        # get name
        product = "Unknown"  # should never actually see this
        if device.startswith("emulator"):
            port = device.rsplit("-")[-1]
            t = telnetlib.Telnet("localhost", port)
            t.read_until(b"OK", 1000)
            t.write(b"avd name\n")
            product = str(t.read_until(b"OK", 1000), "utf-8")
            t.close()
            product = product.replace("OK", "").strip()
        else:
            product = re.findall(r"^ro\.product\.model=(.*)$", build_prop, re.MULTILINE)
            if product:
                product = product[0]
        # get version
        version = re.findall(r"ro\.build\.version\.release=(.*)$", build_prop, re.MULTILINE)
        if version:
            version = version[0]
        else:
            version = "x.x.x"
        product = str(product).strip()
        version = str(version).strip()
        device = str(device).strip()
        options.append("%s %s - %s" % (product, version, device))

    return devices, options


class AndroidSelectDeviceCommand(sublime_plugin.WindowCommand):
    def is_visible(self):
        return False

    def run(self, callbacks, opts={}):
        self.callbacks = callbacks
        self.opts = opts

        devices, options = get_devices()
        self.devices = devices

        if len(options) == 0:
            sublime.status_message("ADB: No device attached!")
        elif len(options) == 1 and get_setting("sublimeandroid_device_select_default", True):
            self.on_done(0)  # run default
        else:
            self.window.show_quick_panel(options, self.on_done)

    def on_done(self, picked):
        if picked == -1:
            return

        device = self.devices[picked]
        self.opts["device"] = device
        log.debug("selected device is %s", device)

        for callback in self.callbacks:
            self.window.run_command(callback, self.opts)
