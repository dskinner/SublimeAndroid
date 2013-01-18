import os

import sublime_plugin

import project
from util import check_settings, logger, packagemeta

log = logger(__name__)


@packagemeta.requires("ADBView")
def load_adbview(settings):
    settings.set("adb_command", os.path.join(project.get_sdk_dir(), "platform-tools", "adb"))


@packagemeta.requires("SublimeJava")
def load_sublimejava(settings):
    settings.set("sublimejava_classpath", project.get_classpaths())
    settings.set("sublimejava_srcpath", project.get_srcpaths())


@packagemeta.requires("SublimeLinter")
def load_sublimelinter(settings):
    java = {
        "working_directory": project.get_path(),
        "lint_args": [
            "-d", "bin/classes",
            "-sourcepath", "src",
            "-classpath", ":".join(project.get_classpaths()),
            "-source", "1.6",
            "-target", "1.6",
            "-Xlint",
            "{filename}"
        ]
    }
    linter = settings.get("SublimeLinter", {})
    linter["Java"] = java
    settings.set("SublimeLinter", linter)
    disable_sublimelinter_defaults(settings)


@project.exists
@check_settings("sublimeandroid_auto_build")
def disable_sublimelinter_defaults(settings):
    """Disable sublimelinter if auto_build is enabled.

    When auto_build is enabled, SublimeLinter should run after the build so
    that class and gen folders are up to date. This disables the default
    behaviour and sublimelinter is invoked manually after a build completes
    later on.
    """
    pass  # TODO
    # if should_auto_build:
    #     settings.set("sublimelinter", False)


@project.exists
@check_settings("sublimeandroid_auto_load_settings")
def load(view):
    """Automatically load settings for external packages.

    Currently configures the following packages:
        * SublimeJava
        * SublimeLinter
        * ADBView

    TODO provide a one time warning on window load of missing external packages
    and a package setting to disable warning.
    """

    log.debug("reloading settings based on view for %s.", view.file_name())
    settings = view.settings()
    load_adbview(settings)
    load_sublimejava(settings)
    load_sublimelinter(settings)


class AndroidLoadSettingsCommand(sublime_plugin.WindowCommand):
    def run(self):
        load(sublime_plugin.active_window().active_view())

    def is_visible(self):
        return project.exists()

    def is_enabled(self):
        return project.exists()
