# SublimeAndroid

This is a work in progress!

Expects a properly configured android project via sdk command line tools. From
project directory:

```
android update project -p ./
```

## Features

* Automatically configures external packages.
	* SublimeJava
	* SublimeLinter
	* ADBView
* Identifies project directory and target platform for autocompletion.
* XML autocompletion (incomplete) in layouts for tags, attributes and values.
* Identifies multiple android projects in a sublime project.