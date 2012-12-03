# SublimeAndroid

This is a work in progress!

Expects a properly configured android project via command line tools. From project directory:

```
android update project -p ./
```

## Features

* identifies project directory and target platform for xml autocompletion
* xml layout autocompletion for tags, attributes, and values (somewhat done)
* automatically configures SublimeJava, SublimeLinter for project and referenced libraries

## Current Roadmap

* build configurations related to ant or push changes to upstream sublime ant projects to handle includes
* more testing for xml autocomplete
