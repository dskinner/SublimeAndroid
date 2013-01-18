import os
import re
import shutil
import subprocess

import sublime
import sublime_plugin

import project
from util import logger

log = logger(__name__)


def exec_tool(cmd=[], panel=False):
    # TODO is panel necessary? need docs
    # TODO windows compat
    cmd[0] = os.path.join(project.get_sdk_dir(), "tools", cmd[0])
    if panel:
        sublime.active_window().run_command("exec", {"cmd": cmd})
    else:
        log.debug("executing sdk tool: %s", " ".join(cmd))
        subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


class AndroidAvdManagerCommand(sublime_plugin.WindowCommand):
    def run(self):
        exec_tool(cmd=["android", "avd"])


class AndroidSdkManagerCommand(sublime_plugin.WindowCommand):
    def run(self):
        exec_tool(cmd=["android", "sdk"])


class AndroidMonitorCommand(sublime_plugin.WindowCommand):
    def run(self):
        exec_tool(cmd=["monitor"])


class AndroidDrawNinePatchCommand(sublime_plugin.WindowCommand):
    def run(self):
        exec_tool(cmd=["draw9patch"])


class AndroidCreateProjectCommand(sublime_plugin.WindowCommand):
    def run(self):
        view = self.window.new_file()
        view.set_name("Create Android Project")
        view.set_scratch(True)
        edit = view.begin_edit()
        buf = """
--target <target-id>

--name MyApp

--path ./

--activity MainActivity

--package com.example.app
"""
        android = os.path.join(project.get_sdk_dir(), "tools", "android")
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
            android = os.path.join(project.get_sdk_dir(), "tools", "android")
            cmd = " ".join([android] + args)
            log.info("running: %s", cmd)
            p = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            stdout = p.stdout.read()
            log.info(stdout)
            stderr = p.stderr.read()
            log.info(stderr)


class AndroidUpdateProjectCommand(sublime_plugin.WindowCommand):
    def run(self):
        exec_tool(cmd=["android", "update", "project", "-p", project.get_path()], panel=True)

    def is_visible(self):
        return project.exists()


class AndroidInstallSupportLibrary(sublime_plugin.WindowCommand):
    def run(self):
        support = os.path.join(project.get_sdk_dir(), "extras", "android", "support")
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
        libs = os.path.join(project.get_path(), "libs")
        if not os.path.exists(libs):
            os.mkdir(libs)
        shutil.copy2(f, libs)

    def is_visible(self):
        return project.exists()

    def is_enabled(self):
        return project.exists()
