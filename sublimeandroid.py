import sublime
import sublime_plugin
from xml.etree import ElementTree as ET
import re
import os.path


class SublimeAndroidXmlComplete(sublime_plugin.EventListener):
	def __init__(self):
		self.dirty = 0
		self.settings = sublime.load_settings("SublimeAndroid.sublime-settings")

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
		el = re.search("<(.*)[ \n\r]", data[idx:]).groups()[0].strip()

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
		'''matches a given key to self.lookup[key] and self.lookup[key_*]'''
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

	def get_setting(self, key, default=None):
		try:
			s = sublime.active_window().active_view().settings()
			if s.has(key):
				return s.get(key)
		except:
			pass
		return self.settings.get(key, default)

	def load_widgets(self, sdk_dir, platform):
		self.widgets = {}
		lines = open(os.path.join(sdk_dir, "platforms", platform, "data/widgets.txt"), "rt").readlines()
		for line in lines:
			records = [s.rsplit(".")[-1] for s in line.split(" ")]
			self.widgets[records[0]] = records[1:]

	def load_lookup(self):
		self.lookup = {}  # prevents recursive calls (i guess) due to how things currently are
		sdk_dir = ""
		platform = ""

		p = self.get_setting("sublimeandroid_project_path", "")

		# inspect project folders to locate root
		# BUG this could be buggy if tests are including in project root but sublime allows you
		# to add a subfolder of a project folder as another project folder. (phew!)
		if not p:
			folders = sublime.active_window().folders()
			for folder in folders:
				a = os.path.join(folder, "local.properties")
				b = os.path.join(folder, "project.properties")
				if os.path.isfile(a) and os.path.isfile(b):
					p = folder
					break
			if not p:
				return

		f = open(os.path.join(p, "local.properties"))
		sdk_dir = self.parse_sdk_dir(f.read())
		f.close()
		f = open(os.path.join(p, "project.properties"))
		platform = self.parse_platform(f.read())
		f.close()

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

	def parse_sdk_dir(self, s):
		return re.search("^sdk\.dir=(.*)\n", s, re.MULTILINE).groups()[0]

	def parse_platform(self, s):
		return re.search("^target=(.*)\n", s, re.MULTILINE).groups()[0]
