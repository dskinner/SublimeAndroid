import imp
import logging
import os
import re

import sublime

from .. import packagemeta

import Default.exec as sublime_exec

def logger(name, level=logging.DEBUG):
    sh = logging.StreamHandler()
    sh.setLevel(logging.DEBUG)
    sh.setFormatter(logging.Formatter('%(levelname)s:%(name)s:%(message)s'))
    log = logging.getLogger(name)
    log.setLevel(level)
    log.addHandler(sh)
    return log


log = logger(__name__)

_settings = None


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


def get_xml_attrib(el, key):
    """Gets an Element attribute value without regard to namespace.

    Returns:
        Value of given key or None.
    """
    for k in el.attrib.keys():
        if key == re.sub("^{.*}", "", k):
            return el.attrib[k]


class AndroidInstallRequiresCommand(packagemeta.PackageMetaInstallRequiresCommand):
    def is_visible(self):
        return self.visible()


class AndroidExecCommand(sublime_exec.ExecCommand):
    """Execute lazy serial tasks in background.

    Builds on Default/exec.py to spend less time debugging segfaults with threading in sublime.
    """

    first_run = True
    queue = []
    running = False

    def run(self, *args, **kwargs):
        if kwargs.get("kill", False):
            self.running = False
            super(AndroidExecCommand, self).run(*args, **kwargs)
            self.handle_queue()
            return

        # TODO sync against mutex
        if self.running:
            self.queue.append((args, kwargs))
            return

        self.running = True

        # Don't erase previous build results for serial tasks
        #
        # BUG the following fn swap is racey for other plugins
        fn = self.window.get_output_panel
        if hasattr(self, "output_view"):
            self.window.get_output_panel = lambda s: self.output_view

        super(AndroidExecCommand, self).run(*args, **kwargs)
        self.window.get_output_panel = fn

        if self.first_run:
            self.first_run = False
            self.window.get_output_panel("exec")

    def on_finished(self, proc):
        try:
            super(AndroidExecCommand, self).on_finished(proc)
        except OSError as e:
            log.error(e)

        if proc.exit_code() not in [0, None]:
            self.queue = []

        self.running = False
        self.handle_queue()

    def handle_queue(self):
        if self.running:
            return

        if self.queue:
            args, kwargs = self.queue.pop(0)
            self.run(*args, **kwargs)
        else:
            self.first_run = True
