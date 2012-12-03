import sublime
import sublime_plugin
from xml.etree import ElementTree as ET
import re
import os.path

_settings = None
_android_project_path = None


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


def is_android_project():
	'''flukey check'''
	get_android_project_path()
	if _android_project_path is None:
		return False
	return True


def get_android_project_path():
	'''
	sublime projects may contain multiple folders, this returns the one
	containing the root of an android project
	'''
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


def get_classpaths():
	classpaths = []
	p = get_android_project_path()
	sdk_dir = get_sdk_dir()
	target_platform = get_target_platform()

	classpaths = [
		os.path.join(sdk_dir, "platforms", target_platform, "android.jar"),
		os.path.join(p, "bin", "classes"),
		os.path.join(p, "gen"),
		os.path.join(p, "libs", "*")
	]

	for lib in get_android_libs():
		classpaths.append(os.path.join(p, lib, "bin", "classes"))
		classpaths.append(os.path.join(p, lib, "gen"))
		classpaths.append(os.path.join(p, lib, "libs", "*"))

	return classpaths


def get_srcpaths():
	p = get_android_project_path()
	srcpaths = [os.path.join(p, "src")]
	for lib in get_android_libs():
		srcpaths.append(os.path.join(p, lib, "src"))
	return srcpaths


def get_sdk_dir():
	get_android_libs()
	p = get_android_project_path()
	f = open(os.path.join(p, "local.properties"))
	s = f.read()
	f.close()
	return re.search("^sdk\.dir=(.*)\n", s, re.MULTILINE).groups()[0]


def get_target_platform():
	p = get_android_project_path()
	f = open(os.path.join(p, "project.properties"))
	s = f.read()
	f.close()
	return re.search("^target=(.*)\n", s, re.MULTILINE).groups()[0]


def get_android_libs():
	'''returns list of referenced libs in project.properties'''
	p = get_android_project_path()
	f = open(os.path.join(p, "project.properties"))
	s = f.read()
	f.close()
	return re.findall("^android\.library\.reference.*=(.*)", s, re.MULTILINE)


class SublimeAndroid(sublime_plugin.EventListener):
	'''
	Automatically load settings for SublimeJava, SublimeLinter, ...
	'''
	def on_load(self, view):
		if not is_android_project():
			return

		settings = view.settings()
		# SublimeJava
		settings.set("sublimejava_classpath", get_classpaths())
		settings.set("sublimejava_srcpath", get_srcpaths())
		# SublimeLinter
		java = {
			"working_directory": get_android_project_path(),
			"lint_args": [
				"-sourcepath", "src",
				"-classpath", ":".join(get_classpaths()),
				"-Xlint",
				"{filename}"
			]
		}
		linter = settings.get("SublimeLinter")
		if linter is None:
			linter = {"Java": java}
		else:
			linter["Java"] = java
		settings.set("SublimeLinter", linter)


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
