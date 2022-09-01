# increasevol
Simple ffmpeg launcher to increase the audio volume of videos. It is made with python and GTK 3, that is with PyGObject.

## Description
It's a toy project to improve my Python skills. I was tired of having to launch the command
```
ffmpeg -i input.mkv -acodec mp3 -filter:a volume=3 -vcodec copy output.mkv
```
to increase the sound volume of the videos I watch on TV and I decided to make a small graphical application to avoid typing.

It may be useful to other novice programmers as an example of PyGObject usage:
- Uses Gtk.IconView and Gtk.TreeView with their respective data models.
- Allows drag and drop from Gtk.IconView widget to Gtk.TreeView. You can also drag files from a file manager to the Gtk.TreeView widget.
- Uses asynchronous reads of ffmpeg command outputs and displays the status in the GUI in real time without using threads.
- Uses the new tk.Application and Gtk.ApplicationWindow classes.

It only works on Linux.

## Installation

## Screenshots
