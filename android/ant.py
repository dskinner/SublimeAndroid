import os
import re
from xml.etree import ElementTree as ET

import sublime_plugin

from . import project
from .util import get_setting, logger

log = logger(__name__)


def get_project_name():
    """Get ant project name.

    Parsed from the android project's build.xml file.
    """
    p = project.get_path()
    root = ET.parse(os.path.join(p, "build.xml")).getroot()
    name = root.attrib.get("name", None)
    if name is None:
        log.error("Failed to get project name from build.xml")
    return name


class AndroidAntBuildCommand(sublime_plugin.WindowCommand):
    """Command for selecting an ANT target and executing.

    Parses the project's build.xml including any imports specified to locate all
    build targets and then provides a quick panel for selecting the desired target.
    """

    def run(self):
        build_xml = os.path.join(project.get_path(), "build.xml")
        self.targets = self.get_targets(build_xml)

        options = ["Build, Install, Run"]
        for k in sorted(self.targets):
            options.append("{0} - {1}".format(k.title(), self.targets[k]))

        self.window.show_quick_panel(options, self.on_done)

    def on_done(self, picked):
        if picked == -1:
            return

        install_and_run = False

        if picked == 0:
            target = "debug"
            install_and_run = True
        else:
            picked -= 1
            target = sorted(self.targets)[picked]

        log.debug("picked %s, target %s", picked, target)

        opts = {
            "cmd": ["ant", target],
            "working_dir": project.get_path()
        }
        self.window.run_command("android_exec", opts)

        if install_and_run:
            log.debug("target is %s and calling install and run.", target)
            self.window.run_command("android_select_device", {"callbacks": ["android_ant_install", "android_ant_run"]})

    def get_targets(self, path, targets={}):
        """Gets list of ANT targets

        Recursively search given file and contained imports for ant targets.

        Returns:
            A dict containing keys of all ANT targets and values being the target's
            description.
        """
        log.debug("checking path: %s", path)
        # return in cases where path is not valid. this may occur when the build.xml
        # stubs imports for custom rules that may not have been implemented.
        if not os.path.isfile(path):
            return

        root = ET.parse(path).getroot()

        for target in root.getiterator("target"):
            name = target.attrib["name"]
            desc = target.attrib.get("description", "")[:100]

            # TODO skip targets with ant vars for now
            if re.search("\${.*}", name) is not None:
                continue

            if not name.startswith("-") and name not in targets:
                targets[name] = desc

        for imp in root.getiterator("import"):
            f = imp.attrib["file"]
            # check for paths with a reference to ${sdk.dir}
            #
            # TODO should load property files for more complex build.xml files
            # to determine appropriate paths with referenced ant vars.
            log.debug("found import with file attr: %s", f)
            if f.startswith("${sdk.dir"):
                f = f.replace("${sdk.dir}", project.get_sdk_dir())

            if not os.path.isabs(f):
                f = os.path.join(project.get_path(), f)

            self.get_targets(f, targets)

        return targets

    def is_visible(self):
        return project.exists()

    def is_enabled(self):
        return project.exists()


class AndroidAntInstallCommand(sublime_plugin.WindowCommand):
    """Install target apk based on sdk's ant build.xml"""
    def run(self, device=None, target="debug"):
        # TODO if device is None, run android_select_device and come back here.
        if device is None:
            self.window.run_command("android_select_device", {"target": target})
            return

        adb = os.path.join(project.get_sdk_dir(), "platform-tools", "adb")
        name = "{0}-{1}.apk".format(get_project_name(), target)
        apk = os.path.join(project.get_path(), "bin", name)

        opts = {
            "cmd": [adb, "-s", device, "install", "-r", apk],
            "working_dir": project.get_path()
        }
        self.window.run_command("android_exec", opts)


class AndroidAntRunCommand(sublime_plugin.WindowCommand):
    def run(self, device):
        adb = os.path.join(project.get_sdk_dir(), "platform-tools", "adb")
        activity = get_setting("sublimeandroid_default_activity", "")
        if not activity:
            activity = project.get_activity_main()

        opts = {
            "cmd": [adb, "-s", device, "shell", "am", "start", "-n", activity],
            "working_dir": project.get_path()
        }
        self.window.run_command("android_exec", opts)
