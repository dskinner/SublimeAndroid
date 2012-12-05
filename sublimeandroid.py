import os.path
import re
import subprocess
import telnetlib
import threading
import traceback
from xml.etree import ElementTree as ET

import sublime
import sublime_plugin

DEBUG = True

_settings = None
_android_project_path = None
_notified_missing_plugins = False


def log(*args):
	if not DEBUG:
		return
	print " ".join(args)


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
	"""Determines if current sublime project contains an android project.

	TODO flukey check

	Returns:
		bool
	"""
	get_android_project_path()
	if _android_project_path is None:
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


def load_settings(view):
	"""Automatically load settings for external packages.

	Currently configures the following packages:
		* SublimeJava
		* SublimeLinter
		* ADBView

	TODO provide a one time warning on window load of missing external packages
	and a package setting to disable warning.
	"""
	if not is_android_project():
		return

	if not get_setting("sublimeandroid_auto_load_settings", True):
		return

	settings = view.settings()
	# ADBView
	settings.set("adb_command", os.path.join(get_sdk_dir(), "platform-tools", "adb"))
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


def auto_build(view):
	if not is_android_project():
		return

	if not get_setting("sublimeandroid_auto_build", True):
		return

	build_xml = os.path.join(get_android_project_path(), "build.xml")
	p = subprocess.Popen(["ant", "-f", build_xml, "debug"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.PIPE)
	view.set_status("SublimeAndroid", "Android: Building Project")

	def wait(p, view):
		p.wait()
		view.erase_status("SublimeAndroid")

	threading.Thread(target=wait, args=(p, view)).start()


class SublimeAndroidAuto(sublime_plugin.EventListener):
	"""EventListener to handle enabled automatic events.

	Settings are configured on multiple hooks to keep up with class path changes.
	"""
	def on_load(self, view):
		load_settings(view)

	def on_new(self, view):
		load_settings(view)

	def on_post_save(self, view):
		auto_build(view)
		load_settings(view)


class SublimeAndroidLoadSettingsCommand(sublime_plugin.WindowCommand):
	def run(self):
		load_settings(sublime_plugin.active_window().active_view())


class AndroidAntRunCommand(sublime_plugin.WindowCommand):
	"""Command to build, install, and run a debug build on selected device.

	This is similar to ctrl+F11 in eclipse/ADT.
	"""
	def run(self):
		devices, options = get_adb_devices()
		self.devices = devices

		if len(options) == 0:
			sublime.status_message("ADB: No device attached!")
		elif len(options) == 1:  # TODO and get_setting("device_auto_select"):
			self.done(0)  # run default
		else:
			self.window.show_quick_panel(options, self.on_done)

	def on_done(self, picked):
		if picked == -1:
			return

		device = self.devices[picked]
		adb = os.path.join(get_sdk_dir(), "platform-tools", "adb")

		apk = None
		bin = os.path.join(get_android_project_path(), "bin")
		for f in os.listdir(bin):
			if f.endswith("-debug.apk"):
				apk = os.path.join(bin, f)
				break

		if apk is None:
			log("failed to locate apk to install")
			return

		activity = get_android_activity_main()

		cmd = \
			"ant debug && " + \
			"echo && echo Installing Package && " + \
			"{adb} -s {device} install -r {apk} && " + \
			"{adb} -s {device} shell am start -n {activity}"

		self.window.run_command("exec", {
			"cmd": [cmd.format(adb=adb, device=device, apk=apk, activity=activity)],
			"working_dir": get_android_project_path(),
			"shell": True
		})


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
		log("checking path:", path)
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
			log("found import with file attr:", f)
			if f.startswith("${sdk.dir"):
				f = f.replace("${sdk.dir}", get_sdk_dir())

			if not os.path.isabs(f):
				f = os.path.join(get_android_project_path(), f)

			self.get_targets(f, targets)

		return targets


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
