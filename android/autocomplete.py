import os
import re
from xml.etree import ElementTree as ET

import sublime
import sublime_plugin

from . import project


class AndroidXmlComplete(sublime_plugin.EventListener):
    def __init__(self):
        self.dirty = False

    def on_query_completions(self, view, prefix, locations):
        if not self.is_responsible(view):
            return

        if not hasattr(self, "lookup"):
            self.load_lookup()

        line = view.substr(sublime.Region(view.full_line(locations[0]).begin(), locations[0])).strip()
        if line == "<":
            keys = [(k, k) for k in list(self.lookup.keys()) if k.lower().startswith(prefix.lower())]
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
                keys += [(k, "%s=\"$0\"" % k) for k in list(self.lookup[e].keys())]

            for parent in self.widgets[el]:
                for e in self.match_keys(parent):
                    keys += [(k, "%s=\"$0\"" % k) for k in list(self.lookup[e].keys())]
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
        for e in list(self.lookup.keys()):
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
        sdk_dir = project.get_sdk_dir()
        platform = project.get_target_platform()

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
