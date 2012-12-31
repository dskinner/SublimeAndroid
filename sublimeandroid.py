"""
Copyright (c) 2012, Daniel Skinner <daniel@dasa.cc>
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice, this
   list of conditions and the following disclaimer.
2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR
ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
(INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
"""
import imp
import logging
import os.path
import re
import shutil
import subprocess
import telnetlib
import threading
import traceback
from xml.etree import ElementTree as ET

import sublime
import sublime_plugin

packagemeta = imp.load_source("android_packagemeta", os.path.join("_packagemeta", "packagemeta.py"))
ant_build_proc = None


def logger(level):
    sh = logging.StreamHandler()
    sh.setLevel(logging.DEBUG)
    sh.setFormatter(logging.Formatter('%(levelname)s:%(name)s:%(message)s'))
    log = logging.getLogger(__name__)
    log.setLevel(level)
    log.addHandler(sh)
    return log


log = logger(logging.DEBUG)


class AndroidInstallRequiresCommand(packagemeta.PackageMetaInstallRequiresCommand):
    def is_visible(self):
        return self.visible()


_settings = None
_android_project_path = None
_notified_missing_plugins = False


def get_setting(key, default=None):
    global _settings
    try:
        s = sublime.active_window().active_view().settings()
        if s.has(key):
            return s.get(key)
    except:
        pass
    if _settings is None:
        _settings = sublime.load_settings("SublimeAndroid.sublime-settings")
    return _settings.get(key, default)


def android(fn):
    """Decorator to execute fn only if android project detected.

    Returns:
        Wrapped function
    """
    def _fn(*args, **kwargs):
        if is_android_project():
            return fn(*args, **kwargs)
    return _fn


def check_settings(*settings):
    """Decorator that checks given settings to affirm they're True.

    Returns:
        Wrapped function
    """
    def _decor(fn):
        def _fn(*args, **kwargs):
            for setting in settings:
                if not get_setting(setting):
                    return
            return fn(*args, **kwargs)
        return _fn
    return _decor


def is_android_project():
    """Determines if current sublime project contains an android project.

    TODO flukey check

    Returns:
        bool
    """
    p = get_android_project_path()
    if p is None:
        log.debug("Could not locate android project.")
        return False
    return True


def get_android_project_path():
    """Gets android project path from one of the top level folders in sublime project.

    TODO there are instances where a project may contain subprojects and
    even where sublime may be used in a fashion to include multiple top-level
    folders to show multiple projects. It would be nice to support these cases.

    Returns:
        String pointing to absolute path of android project root.
    """
    view = sublime.active_window().active_view()
    if view is None:
        return

    settings_path = view.settings().get("sublimeandroid_project_path", "")
    if settings_path:
        return settings_path

    log.info("Searching for project path.")

    # Use active file to traverse upwards and locate project
    if view is not None:
        file_name = view.file_name()
        if file_name:
            dir_name = os.path.dirname(file_name)
            log.debug("Starting check for AndroidManifest.xml in %s", dir_name)
            while dir_name != "/":
                android_manifest = os.path.join(dir_name, "AndroidManifest.xml")
                project_properties = os.path.join(dir_name, "project.properties")
                if os.path.isfile(android_manifest) and os.path.isfile(project_properties):
                    log.info("Found project from active file. %s", dir_name)
                    view.settings().set("sublimeandroid_project_path", dir_name)
                    return dir_name
                dir_name = os.path.abspath(os.path.join(dir_name, ".."))

    #
    global _android_project_path
    if _android_project_path is not None:
        return _android_project_path

    p = get_setting("sublimeandroid_project_path", "")

    # inspect project folders to locate root
    # BUG this could be buggy if tests are including in project root but sublime allows you
    # to add a subfolder of a project folder as another project folder. (phew!)
    if not p:
        folders = sublime.active_window().folders()
        for folder in folders:
            a = os.path.join(folder, "local.properties")
            b = os.path.join(folder, "project.properties")
            if os.path.isfile(a) and os.path.isfile(b):
                _android_project_path = folder
                return folder
        if not p:
            # TODO throw notification that no folders appear to be proper android projects
            return


def get_xml_attrib(el, key):
    """Gets an Element attribute value without regard to namespace.

    Returns:
        Value of given key or None.
    """
    for k in el.attrib.keys():
        if key == re.sub("^{.*}", "", k):
            return el.attrib[k]


def get_android_activity_main():
    manifest = os.path.join(get_android_project_path(), "AndroidManifest.xml")
    root = ET.parse(manifest).getroot()
    package = root.attrib.get("package", "")
    for activity in root.getiterator("activity"):
        action = activity.find("./intent-filter/action")
        if action is None:
            continue
        if get_xml_attrib(action, "name") == "android.intent.action.MAIN":
            return "{0}/{1}".format(package, get_xml_attrib(activity, "name"))


def get_classpaths():
    """Get java class paths.

    Use detected android project to determine absolute paths to
    to java class paths.

    Returns:
        list of strings that are absolute paths to standard paths of android
        projects.
    """
    classpaths = []
    p = get_android_project_path()
    log.debug("Project path %s", p)
    sdk_dir = get_sdk_dir()
    log.debug("SDK Dir %s", sdk_dir)
    target_platform = get_target_platform()
    log.debug("Target Platform %s", target_platform)

    classpaths = [
        os.path.join(sdk_dir, "platforms", target_platform, "android.jar"),
        os.path.join(p, "bin", "classes"),
        os.path.join(p, "gen"),
        os.path.join(p, "libs", "*")
    ]

    for path in classpaths:
        if not os.path.exists(path):
            log.warn("Classpath does not exist: %s", path)

    for lib in get_android_libs():
        classpaths.append(os.path.join(p, lib, "bin", "classes"))
        classpaths.append(os.path.join(p, lib, "gen"))
        classpaths.append(os.path.join(p, lib, "libs", "*"))

    return classpaths


def get_srcpaths():
    """Get java source paths.

    Use detected android project to determine absolute paths to
    java source files.

    Returns:
        list of strings that are absolute paths.
    """
    p = get_android_project_path()
    srcpaths = [os.path.join(p, "src")]
    for lib in get_android_libs():
        srcpaths.append(os.path.join(p, lib, "src"))
    return srcpaths


def get_sdk_dir():
    """Determine path of sdk dir.

    Check if setting exists to point to sdk dir, otherwise use
    local.properties of detected android project.
    """
    sdk_dir = get_setting("sublimeandroid_sdk_dir", "")
    if sdk_dir:
        return sdk_dir
    get_android_libs()
    p = get_android_project_path()
    f = open(os.path.join(p, "local.properties"))
    s = f.read()
    f.close()
    return re.search("^sdk\.dir=(.*)\n", s, re.MULTILINE).groups()[0]


def get_target_platform():
    """Get target platform.

    Use detected android project path to read target platform from
    project.properties

    Returns:
        String of target platform
    """
    p = get_android_project_path()
    f = open(os.path.join(p, "project.properties"))
    s = f.read()
    f.close()
    target = re.search("^target=(.*)\n", s, re.MULTILINE).groups()[0]
    if target.startswith("Google"):
        target = "android-%s" % target.rsplit(":")[-1]
    return target


def get_android_libs():
    """Gets a list of android libraries used for the project.

    Returns:
        List of strings that may be absolute or relative paths.
    """
    p = get_android_project_path()
    f = open(os.path.join(p, "project.properties"))
    s = f.read()
    f.close()
    return re.findall("^android\.library\.reference.*=(.*)", s, re.MULTILINE)


def get_adb_devices():
    """Gets a list of devices currently attached.

    Querys `adb` from `get_sdk_dir()` for all emulator/device instances.

    Returns:
        A tuple of lists. The first value is a list of device ids suitable for
        use in selecting a device when calling adb. The second value is a list
        of strings suitable for displaying text more descriptive to the use to
        choose an appropriate device.
    """
    adb = os.path.join(get_sdk_dir(), "platform-tools", "adb")
    cmd = [adb, "devices"]
    try:
        proc = subprocess.Popen(cmd, shell=False, stdout=subprocess.PIPE)
        out, err = proc.communicate()
    except:
        sublime.error_message("Error trying to launch ADB:\n\n{0}\n\n{1}".format(cmd, traceback.format_exc()))
        return
    # get list of device ids
    devices = []
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
        build_prop = proc.stdout.read().strip()
        # get name
        product = "Unknown"  # should never actually see this
        if device.startswith("emulator"):
            port = device.rsplit("-")[-1]
            t = telnetlib.Telnet("localhost", port)
            t.read_until("OK", 1000)
            t.write("avd name\n")
            product = t.read_until("OK", 1000)
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


@android
@packagemeta.requires("ADBView")
def load_settings_adbview(settings):
    settings.set("adb_command", os.path.join(get_sdk_dir(), "platform-tools", "adb"))


@android
@packagemeta.requires("SublimeJava")
def load_settings_sublimejava(settings):
    settings.set("sublimejava_classpath", get_classpaths())
    settings.set("sublimejava_srcpath", get_srcpaths())


@android
@packagemeta.requires("SublimeLinter")
def load_settings_sublimelinter(settings):
    java = {
        "working_directory": get_android_project_path(),
        "lint_args": [
            "-d", "bin/classes",
            "-sourcepath", "src",
            "-classpath", ":".join(get_classpaths()),
            "-Xlint",
            "{filename}"
        ]
    }
    linter = settings.get("SublimeLinter", {})
    linter["Java"] = java
    settings.set("SublimeLinter", linter)
    disable_sublimelinter_defaults(settings)


@android
@check_settings("sublimeandroid_auto_build")
def disable_sublimelinter_defaults(settings):
    """Disable sublimelinter if auto_build is enabled.

    When auto_build is enabled, SublimeLinter should run after the build so
    that class and gen folders are up to date. This disables the default
    behaviour and sublimelinter is invoked manually after a build completes
    later on.
    """
    settings.set("sublimelinter", False)


@android
@check_settings("sublimeandroid_auto_load_settings")
def load_settings(view):
    """Automatically load settings for external packages.

    Currently configures the following packages:
        * SublimeJava
        * SublimeLinter
        * ADBView

    TODO provide a one time warning on window load of missing external packages
    and a package setting to disable warning.
    """

    log.debug("reloading settings")
    settings = view.settings()
    load_settings_adbview(settings)
    load_settings_sublimejava(settings)
    load_settings_sublimelinter(settings)


def get_ant_project_name():
    p = get_android_project_path()
    root = ET.parse(os.path.join(p, "build.xml")).getroot()
    name = root.attrib.get("name", None)
    if name is None:
        log.error("Failed to get project name from build.xml")
    return name


@android
def ant_build(view=None, args=None, device=None, target=None, install=False, run=False, verbose=False, callback=None):
    if view is None:
        view = sublime.active_window().active_view()
    args = get_setting("sublimeandroid_ant_args")
    target = get_setting("sublimeandroid_default_ant_target", "debug")
    log.debug("ant_build received device %s", device)
    _ant_build(view, args, device, target, install, run, verbose, callback)


def _ant_build(view, args, device, target, install, run, verbose, callback):
    # vars for installation of target
    adb = os.path.join(get_sdk_dir(), "platform-tools", "adb")
    name = "%s-debug.apk" % get_ant_project_name()
    apk = os.path.join(get_android_project_path(), "bin", name)

    activity = get_setting("sublimeandroid_default_activity", "")
    if not activity:
        activity = get_android_activity_main()

    #
    cmd = "cd {working_dir} && ant {args} {target}".format(working_dir=get_android_project_path(), args=args, target=target)

    if install:
        if device is None:
            raise Exception("install is True but device is None")

        cmd += \
            " && echo && echo Installing Package" + \
            " && {adb} -s {device} install -r {apk}".format(adb=adb, device=device, apk=apk)

    if run:
        cmd += " && {adb} -s {device} shell am start -n {activity}".format(adb=adb, device=device, activity=activity)

    def start():
        global ant_build_proc

        if ant_build_proc is not None:
            ant_build_proc.kill()
            ant_build_proc.wait()

        ant_build_proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        view.set_status("SublimeAndroid", "Android: Building Project")

        window = sublime.active_window()
        if verbose:
            window.run_command("show_panel", {"panel": "console"})

        def wait(view, callback):
            global ant_build_proc

            lines = []

            while ant_build_proc is not None and ant_build_proc.poll() is None:
                line = ant_build_proc.stdout.readline().rstrip("\n")
                lines.append(line)

            log.info("\n".join(lines))

            if ant_build_proc is not None:
                stderr = ant_build_proc.stderr.read()
                log.info(stderr)

            view.erase_status("SublimeAndroid")
            log.debug("finished build")
            ant_build_proc = None

            if callback is not None:
                callback()

        threading.Thread(target=wait, args=(view, callback)).start()

    threading.Thread(target=start).start()


def exec_sdk_tool(cmd=[], panel=False):
    cmd[0] = os.path.join(get_sdk_dir(), "tools", cmd[0])
    if panel:
        sublime.active_window().run_command("exec", {"cmd": cmd})
    else:
        log.debug("executing sdk tool: %s", " ".join(cmd))
        subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


class SublimeAndroidAuto(sublime_plugin.EventListener):
    """EventListener to handle enabled automatic events.

    Settings are configured on multiple hooks to keep up with class path changes.
    """
    @android
    def on_load(self, view):
        load_settings(view)

    @android
    def on_new(self, view):
        load_settings(view)

    @android
    def on_post_save(self, view):
        load_settings(view)
        self.auto_build(view)

    @android
    @packagemeta.requires("SublimeLinter")
    @check_settings("sublimeandroid_auto_build")
    def lint(self, view):
        import SublimeLinter
        SublimeLinter.reload_view_module(view)
        linter = SublimeLinter.select_linter(view)
        SublimeLinter.queue_linter(linter, view, preemptive=True, event='on_post_save')

    @check_settings("sublimeandroid_auto_build")
    def auto_build(self, view):
        def callback():
            log.debug("calling SublimeLinter")
            self.lint(view)
        ant_build(view, callback=callback)


class SublimeAndroidToggleAutoCommand(sublime_plugin.WindowCommand):
    def run(self):
        auto = not get_setting("sublimeandroid_auto_build", True)
        log.debug("Setting auto build value to %s", auto)
        self.window.active_view().settings().set("sublimeandroid_auto_build", auto)

    def is_visible(self):
        return is_android_project()


class SublimeAndroidLoadSettingsCommand(sublime_plugin.WindowCommand):
    def run(self):
        load_settings(sublime_plugin.active_window().active_view())

    def is_visible(self):
        return is_android_project()


class AndroidAvdManagerCommand(sublime_plugin.WindowCommand):
    def run(self):
        exec_sdk_tool(cmd=["android", "avd"])


class AndroidSdkManagerCommand(sublime_plugin.WindowCommand):
    def run(self):
        exec_sdk_tool(cmd=["android", "sdk"])


class AndroidMonitorCommand(sublime_plugin.WindowCommand):
    def run(self):
        exec_sdk_tool(cmd=["monitor"])


class AndroidDrawNinePatchCommand(sublime_plugin.WindowCommand):
    def run(self):
        exec_sdk_tool(cmd=["draw9patch"])


create_project_buffer = """
--target <target-id>

--name MyApp

--path ./

--activity MainActivity

--package com.example.app
"""


class AndroidCreateProjectCommand(sublime_plugin.WindowCommand):
    def run(self):
        view = self.window.new_file()
        view.set_name("Create Android Project")
        view.set_scratch(True)
        edit = view.begin_edit()
        buf = create_project_buffer
        android = os.path.join(get_sdk_dir(), "tools", "android")
        p = subprocess.Popen([android, "list", "targets"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout = p.stdout.readlines()
        targets = "".join([line.replace(" or", "") for line in stdout if line.startswith("id:")])
        buf = targets + buf
        view.insert(edit, 0, buf)
        view.end_edit(edit)


class AndroidCreateProjectListener(sublime_plugin.EventListener):
    def on_close(self, view):
        if view.name() == "Create Android Project":
            data = view.substr(sublime.Region(0, view.size()))
            args = ["create", "project"]
            for line in data.split("\n"):
                if not line.startswith("--"):
                    continue

                if line.startswith("--path"):
                    path = line.split(" ", 1)[1]
                    path = os.path.join(sublime.active_window().folders()[0], path)
                    line = "--path " + path
                args.append(line.rstrip())
            android = os.path.join(get_sdk_dir(), "tools", "android")
            cmd = " ".join([android] + args)
            log.info("running: %s", cmd)
            p = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            stdout = p.stdout.read()
            log.info(stdout)
            stderr = p.stderr.read()
            log.info(stderr)


class AndroidUpdateProjectCommand(sublime_plugin.WindowCommand):
    def run(self):
        exec_sdk_tool(cmd=["android", "update", "project", "-p", get_android_project_path()], panel=True)

    def is_visible(self):
        return is_android_project()


class AndroidInstallSupportLibrary(sublime_plugin.WindowCommand):
    def run(self):
        support = os.path.join(get_sdk_dir(), "extras", "android", "support")
        if not os.path.exists(support):
            sublime.error_message("Support libraries are not installed.")
            return

        self.support_libs = []
        self.options = []

        for d in [d for d in os.listdir(support) if re.match(r"v[0-9]*", d) is not None]:
            path = os.path.join(support, d)
            print "checking:", path
            for root, dirs, files in os.walk(path):
                if self.match_files(root, files):
                    break

        self.window.show_quick_panel(self.options, self.on_done)

    def match_files(self, root, files):
        for f in files:
            if re.match(r"android.*\.jar$", f) is not None:
                self.support_libs.append(os.path.join(root, f))
                self.options.append(f)
                return True
        return False

    def on_done(self, picked):
        if picked == -1:
            return

        f = self.support_libs[picked]
        libs = os.path.join(get_android_project_path(), "libs")
        if not os.path.exists(libs):
            os.mkdir(libs)
        shutil.copy2(f, libs)

    def is_visible(self):
        return is_android_project()

    def is_enabled(self):
        return is_android_project()


class AndroidAntRunCommand(sublime_plugin.WindowCommand):
    """Command to build, install, and run a debug build on selected device.

    This is similar to ctrl+F11 in eclipse/ADT.
    """
    def run(self, device=None):
        devices, options = get_adb_devices()
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
        log.debug("selected device is %s", device)
        ant_build(view=self.window.active_view(), device=device, install=True, run=True, verbose=True)

    def is_visible(self):
        return is_android_project()


class AndroidAntBuildCommand(sublime_plugin.WindowCommand):
    """Command for selecting an ANT target and executing.

    Parses the project's build.xml including any imports specified to locate all
    build targets and then provides a quick panel for selecting the desired target.
    """
    def run(self):
        build_xml = os.path.join(get_android_project_path(), "build.xml")
        self.targets = self.get_targets(build_xml)

        options = []
        for k in sorted(self.targets):
            options.append("{0} - {1}".format(k.title(), self.targets[k]))

        self.window.show_quick_panel(options, self.on_done)

    def on_done(self, picked):
        if picked == -1:
            return

        target = sorted(self.targets)[picked]
        cmd = {
            "cmd": ["ant", target],
            "working_dir": get_android_project_path()
        }
        self.window.run_command("exec", cmd)

    def get_targets(self, path, targets={}):
        """Gets list of ANT targets

        Recursively search given file and contained imports for ant targets.

        Returns:
            A dict containing keys of all ANT targets and values being the target's
            description.
        """
        log.debug("checking path:", path)
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
            log.debug("found import with file attr:", f)
            if f.startswith("${sdk.dir"):
                f = f.replace("${sdk.dir}", get_sdk_dir())

            if not os.path.isabs(f):
                f = os.path.join(get_android_project_path(), f)

            self.get_targets(f, targets)

        return targets

    def is_visible(self):
        return is_android_project()


class SublimeAndroidXmlComplete(sublime_plugin.EventListener):
    def __init__(self):
        self.dirty = False

    def on_query_completions(self, view, prefix, locations):
        if not self.is_responsible(view):
            return

        if not hasattr(self, "lookup"):
            self.load_lookup()

        line = view.substr(sublime.Region(view.full_line(locations[0]).begin(), locations[0])).strip()
        if line == "<":
            keys = [(k, k) for k in self.lookup.keys() if k.lower().startswith(prefix.lower())]
            return (keys, sublime.INHIBIT_WORD_COMPLETIONS | sublime.INHIBIT_EXPLICIT_COMPLETIONS)

        part = line.rsplit(" ")[-1].strip()  # BUG this would flunk on string values with spaces
        data = view.substr(sublime.Region(0, locations[0] - len(prefix)))
        idx = data.rfind("<")
        el = re.search("<([[a-zA-Z0-9\.]*)[ \n\r]", data[idx:]).groups()[0].strip()

        if part.lower() == "android:":
            keys = []
            # TODO cache all this searching during initial load
            # match el and el_*
            for e in self.match_keys(el):
                keys += [(k, "%s=\"$0\"" % k) for k in self.lookup[e].keys()]

            for parent in self.widgets[el]:
                for e in self.match_keys(parent):
                    keys += [(k, "%s=\"$0\"" % k) for k in self.lookup[e].keys()]
            #

            self.dirty = True  # trigger to provide further completions to value
            keys.sort()
            return (set(keys), sublime.INHIBIT_WORD_COMPLETIONS | sublime.INHIBIT_EXPLICIT_COMPLETIONS)

        # set `dirty = False` here after providing initial autocomplete for dirty
        self.dirty = False
        srch = re.search(":(.*)=", part)
        if not srch:
            return
        groups = srch.groups()
        if not groups:
            return
        attr = groups[0]
        # need to iter through all possible keys to find attr def
        # TODO cache all this searching during initial load
        for e in self.match_keys(el):
            if attr in self.lookup[e] and self.lookup[e][attr]:
                keys = [(k, k) for k in self.lookup[e][attr]]
                return (keys, sublime.INHIBIT_WORD_COMPLETIONS | sublime.INHIBIT_EXPLICIT_COMPLETIONS)
        for parent in self.widgets[el]:
            for e in self.match_keys(parent):
                if attr in self.lookup[e] and self.lookup[e][attr]:
                    keys = [(k, k) for k in self.lookup[e][attr]]
                    return (keys, sublime.INHIBIT_WORD_COMPLETIONS | sublime.INHIBIT_EXPLICIT_COMPLETIONS)
        # TODO provide completions based on custom attrs defined within project

    def match_keys(self, key):
        """Matches a given key to other versions of the same type.

        The SDK data files segment items based on certain types of groups. For
        example, `ViewGroup` also has an entry for `ViewGroup_MarginLayout`.
        We don't want to provide tag completion for `ViewGroup_MarginLayout` as
        that's not a valid tag, but we do want to be able to lookup all keys
        that are associated with `ViewGroup`.

        Returns:
            List of strings where each value maps to self.lookup keys.
        """
        keys = []
        for e in self.lookup.keys():
            if e == key or e.startswith(key + "_"):
                keys.append(e)
        return keys

    def on_modified(self, view):
        if not self.is_responsible(view):
            return

        if self.dirty:
            # dont reset dirty here as it prevents final autocompletion in a somewhat
            # bizarre manner.
            view.run_command("auto_complete")
            return

        sel = view.sel()[0]
        if view.substr(sel.a - 1) in ["<", ":"]:
            view.run_command("auto_complete")

    def is_responsible(self, view):
        # TODO better check for if this is an android project
        if view.file_name() and view.file_name().endswith(".xml"):
            return True

        return False

    def load_widgets(self, sdk_dir, platform):
        self.widgets = {}
        lines = open(os.path.join(sdk_dir, "platforms", platform, "data/widgets.txt"), "rt").readlines()
        for line in lines:
            records = [s.rsplit(".")[-1] for s in line.split(" ")]
            self.widgets[records[0]] = records[1:]

    def load_lookup(self):
        self.lookup = {}  # prevents recursive calls (i guess) due to how things currently are
        sdk_dir = get_sdk_dir()
        platform = get_target_platform()

        self.load_widgets(sdk_dir, platform)

        els = ET.parse(os.path.join(sdk_dir, "platforms", platform, "data/res/values/attrs.xml")).getroot()
        self.lookup = {}

        for el in els:
            name = el.attrib.get("name", None)
            if name is None:
                continue
            attrs = {}

            for attr in el.getchildren():
                attr_name = attr.attrib.pop("name", None)
                if attr_name is None:
                    continue
                options = []
                for enum in attr.getchildren():
                    options.append(enum.attrib["name"])
                attrs[attr_name] = options

            self.lookup[name] = attrs
