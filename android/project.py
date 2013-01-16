import os
import re
from xml.etree import ElementTree as ET

import sublime

from util import log, get_setting, get_xml_attrib

# map views to android project paths
_project_map = {}


def get_path():
    """Gets android project path from one of the top level folders in sublime project.

    TODO there are instances where a project may contain subprojects and
    even where sublime may be used in a fashion to include multiple top-level
    folders to show multiple projects. It would be nice to support these cases.

    Returns:
        String pointing to absolute path of android project root.
    """
    p = get_setting("sublimeandroid_project_path", "")
    if p:
        log.debug("Returning project path from settings")
        return p

    view = sublime.active_window().active_view()

    # check if view has already been mapped to an android project
    if view is not None and _project_map.get(view.id(), None) is not None:
        log.debug("Returning cached response for view %s: %s", view.id(), _project_map[view.id()])
        return _project_map[view.id()]

    # Use active file to traverse upwards and locate project
    if view is not None and view.file_name():
        folder = os.path.dirname(view.file_name())
        while folder != "/":  # TODO fix for windows root path
            android_manifest = os.path.join(folder, "AndroidManifest.xml")
            project_properties = os.path.join(folder, "project.properties")
            if os.path.isfile(android_manifest) and os.path.isfile(project_properties):
                log.info("Found project from active file %s. %s", view.file_name(), folder)
                _project_map[view.id()] = folder
                return folder
            folder = os.path.abspath(os.path.join(folder, ".."))

    # inspect project folders to locate root android project
    #
    # Using sublime project folders has less precedent than the current viewsince this will
    # simply return the first android project found in the list of folders. This is not
    # contrained by a `view is None` check as it is meant to run in case the current view
    # is outside of the sublime project.
    #
    # BUG this could be buggy if tests are including in project root but sublime allows you
    # to add a subfolder of a project folder as another project folder. (phew!)
    for folder in sublime.active_window().folders():
        a = os.path.join(folder, "local.properties")
        b = os.path.join(folder, "project.properties")
        if os.path.isfile(a) and os.path.isfile(b):
            log.info("Found project from sublime folder %s.", folder)
            if view is not None:
                _project_map[view.id()] = folder
            return folder

    log.info("Android project path not found.")


def exists(fn=None):
    """Determines if current sublime project contains an android project.

    Can also be used as a decorator.

    TODO flukey check

    Returns:
        bool
    """
    def _exists():
        p = get_path()
        if p is None:
            log.debug("Not an android project.")
            return False
        log.debug("Is android project based on path %s", p)
        return True

    def _fn(*args, **kwargs):
        if _exists():
            return fn(*args, **kwargs)

    if fn is None:
        return _exists()

    if hasattr(fn, "__call__"):
        return _fn

    raise Exception("Misuse of decorator `exists`, param of type `{0}` not callable.".format(type(fn)))


def get_activity_main():
    manifest = os.path.join(get_path(), "AndroidManifest.xml")
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
    p = get_path()
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
    p = get_path()
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
    p = get_path()
    f = open(os.path.join(p, "local.properties"))
    s = f.read()
    f.close()
    return re.search("^sdk\.dir=(.*)\n", s, re.MULTILINE).groups()[0]


def get_target_platform():
    """Get target platform, such as API 8.

    Use detected android project path to read target platform from
    project.properties

    Returns:
        String of target platform
    """
    p = get_path()
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
    p = get_path()
    f = open(os.path.join(p, "project.properties"))
    s = f.read()
    f.close()
    return re.findall("^android\.library\.reference.*=(.*)", s, re.MULTILINE)
