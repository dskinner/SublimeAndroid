# SublimeAndroid

This is a work in progress!

Expects a properly configured android project via sdk command line tools. From
project directory:

```
android update project -p ./
```

## Installation

This package depends on a submodule.

For a fresh install:

```
git clone --recursive git://github.com/dskinner/SublimeAndroid.git
```

If updating from a previous install without the submodule

```
git pull
git submodule init
git submodule update
```

## Features

* Automatically configures external packages.
	* SublimeJava
	* SublimeLinter
	* ADBView
* Identifies project directory and target platform for autocompletion.
* XML autocompletion (incomplete) in layouts for tags, attributes and values.
* Identifies multiple android projects in a sublime project.