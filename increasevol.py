#!/usr/bin/env python3
# -*- coding: utf-8 -*-

#############################################################################
# Simple ffmpeg launcher to increase the audio volume of videos.
#
# Copyright (C) 2022 Eduardo Posadas Fernandez
#
# This program is free software: you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation, either version 3
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this# program. If not, see <https://www.gnu.org/licenses/>.
#############################################################################

import os
import sys
from enum import Enum, unique
import shlex
import shutil
import signal
import time
import tempfile
import traceback
import configparser
import urllib.parse
import urllib.request
import gi

gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
gi.require_version('Pango', '1.0')
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import GObject, GLib, Gio, GdkPixbuf, Pango, Gdk, Gtk


class Configuration:
    """Set default configuration values and load/save configuration values."""

    def __init__(self):
        self._video_extensions = ('mp4', 'avi', 'mkv')
        self._remove_subtitles = False
        self._volume_increase = 3
        self._keep_original = False
        self._output_prefix = ''  # Only used if _keep_original == True
        self._output_suffix = '_Vol-inc'  # Only used if _keep_original == True
        self._use_all_cpus = True
        self._max_jobs = os.cpu_count()  # Only used if _use_all_cpus == False
        self._file_expl_show_hidden_files = False
        self._file_expl_case_insensitive_sort = True
        self._file_expl_activate_on_single_click = True
        self._temp_file_prefix = 'ffmpeg_temp_'
        self._ignore_temp_files = True
        # Do not change configuration options below this
        self._file = os.path.join(os.path.expanduser("~"), '.config', 'increasevol')  # FIXME: This is not portable.
        self._required_cmd = ('ffprobe', 'ffmpeg')
        self._cwd = GLib.get_home_dir()
        self._win_maximized = False
        self._win_width = 783
        self._win_height = 309
        self._file_expl_undo_size = 100  # Stack size for "back" button
        self._paned_file_expl_position = 400
        self._ffprobe_get_duration_cmd = 'ffprobe -v error -show_entries format=duration ' \
                                         '-of default=noprint_wrappers=1:nokey=1 "{video_file_name}"'
        self._ffmpeg_increase_audio_cmd = 'ffmpeg -hide_banner -y -i "{video_file_name_input}" ' \
                                          '{remove_subtitles_param} ' \
                                          '-acodec mp3 -filter:a volume={volume_increase} -vcodec copy ' \
                                          '"{video_file_name_output}"'
        self._load()

    def _load(self):
        """Load configuration values from configuration file"""
        temp_conf = configparser.ConfigParser()
        temp_conf.read(self._file)

        tmp = temp_conf.get('DEFAULT', 'video_extensions', fallback=self._video_extensions)
        if isinstance(tmp, str):
            tmp_tuple = tuple(tmp.split(','))
            if len(tmp_tuple) > 0:
                self._video_extensions = tmp_tuple

        self._remove_subtitles = temp_conf.getboolean('DEFAULT', 'remove_subtitles', fallback=self._remove_subtitles)
        self._cwd = temp_conf.get('DEFAULT', 'directory', fallback=self._cwd)
        self._volume_increase = temp_conf.getfloat('DEFAULT', 'volume_increase', fallback=self._volume_increase)
        self._keep_original = temp_conf.getboolean('DEFAULT', 'keep_original', fallback=self._keep_original)
        self._output_prefix = temp_conf.get('DEFAULT', 'output_prefix', fallback=self._output_prefix)
        self._output_suffix = temp_conf.get('DEFAULT', 'output_suffix', fallback=self._output_suffix)
        self._use_all_cpus = temp_conf.getboolean('DEFAULT', 'use_all_cpus', fallback=self._use_all_cpus)
        self._max_jobs = temp_conf.getint('DEFAULT', 'max_jobs', fallback=self._max_jobs)
        self._file_expl_show_hidden_files = temp_conf.getboolean('DEFAULT', 'file_explorer_show_hidden_files',
                                                                 fallback=self._file_expl_show_hidden_files)
        self._file_expl_case_insensitive_sort = temp_conf.getboolean('DEFAULT',
                                                                     'file_explorer_case_insensitive_sort',
                                                                     fallback=self._file_expl_case_insensitive_sort)
        self._file_expl_activate_on_single_click = temp_conf.getboolean('DEFAULT',
                                                                        'file_explorer_activate_on_single_click',
                                                                        fallback=
                                                                        self._file_expl_activate_on_single_click)
        self._temp_file_prefix = temp_conf.get('DEFAULT', 'temp_file_prefix', fallback=self._temp_file_prefix)
        self._ignore_temp_files = temp_conf.getboolean('DEFAULT', 'ignore_temp_files', fallback=self._ignore_temp_files)
        self._paned_file_expl_position = temp_conf.getint('DEFAULT', 'paned_file_explorer_position',
                                                          fallback=self._paned_file_expl_position)
        self._win_maximized = temp_conf.getboolean('DEFAULT', 'win_maximized', fallback=self._win_maximized)
        self._win_width = temp_conf.getint('DEFAULT', 'win_width', fallback=self._win_width)
        self._win_height = temp_conf.getint('DEFAULT', 'win_height', fallback=self._win_height)

    def save(self):
        """Save configuration values from configuration file"""
        temp_conf = configparser.ConfigParser()
        temp_conf['DEFAULT'] = {
            'directory': self._cwd,
            'video_extensions': ','.join(self._video_extensions),
            'remove_subtitles': self._remove_subtitles,
            'volume_increase': self._volume_increase,
            'keep_original': self._keep_original,
            'output_prefix': self._output_prefix,
            'output_suffix': self._output_suffix,
            'use_all_cpus': self._use_all_cpus,
            'max_jobs': self._max_jobs,
            'file_explorer_show_hidden_files': self._file_expl_show_hidden_files,
            'file_explorer_case_insensitive_sort': self._file_expl_case_insensitive_sort,
            'file_explorer_activate_on_single_click': self._file_expl_activate_on_single_click,
            'temp_file_prefix': self._temp_file_prefix,
            'ignore_temp_files': self._ignore_temp_files,
            'paned_file_explorer_position': self._paned_file_expl_position,
            'win_maximized': self._win_maximized,
            'win_width': self._win_width,
            'win_height': self._win_height
        }

        try:
            with open(self._file, 'w') as configfile:
                temp_conf.write(configfile)
        except OSError:
            traceback.print_exc()
            dialog = Gtk.MessageDialog(
                message_type=Gtk.MessageType.ERROR,
                buttons=Gtk.ButtonsType.CLOSE,
                title='Error',
                text='Error saving configuration',
                secondary_text=traceback.format_exc()
            )
            dialog.run()

    @property
    def file(self):
        return self._file

    @property
    def required_cmd(self):
        return self._required_cmd

    @property
    def cwd(self):
        return self._cwd

    @cwd.setter
    def cwd(self, val: str):
        self._cwd = val

    @property
    def video_extensions(self):
        return self._video_extensions

    @video_extensions.setter
    def video_extensions(self, val: tuple):
        self._video_extensions = val

    @property
    def remove_subtitles(self):
        return self._remove_subtitles

    @remove_subtitles.setter
    def remove_subtitles(self, val: bool):
        self._remove_subtitles = val

    @property
    def volume_increase(self):
        return self._volume_increase

    @volume_increase.setter
    def volume_increase(self, val: float):
        self._volume_increase = val

    @property
    def keep_original(self):
        return self._keep_original

    @keep_original.setter
    def keep_original(self, val: bool):
        self._keep_original = val

    @property
    def output_prefix(self):
        return self._output_prefix

    @output_prefix.setter
    def output_prefix(self, val: str):
        self._output_prefix = val

    @property
    def output_suffix(self):
        return self._output_suffix

    @output_suffix.setter
    def output_suffix(self, val: str):
        self._output_suffix = val

    @property
    def use_all_cpus(self):
        return self._use_all_cpus

    @use_all_cpus.setter
    def use_all_cpus(self, val: bool):
        self._use_all_cpus = val

    @property
    def max_jobs(self):
        return self._max_jobs

    @max_jobs.setter
    def max_jobs(self, val: int):
        self._max_jobs = val

    @property
    def paned_file_expl_position(self):
        return self._paned_file_expl_position

    @paned_file_expl_position.setter
    def paned_file_expl_position(self, val: int):
        self._paned_file_expl_position = val

    @property
    def file_expl_show_hidden_files(self):
        return self._file_expl_show_hidden_files

    @file_expl_show_hidden_files.setter
    def file_expl_show_hidden_files(self, val: bool):
        self._file_expl_show_hidden_files = val

    @property
    def file_expl_case_insensitive_sort(self):
        return self._file_expl_case_insensitive_sort

    @file_expl_case_insensitive_sort.setter
    def file_expl_case_insensitive_sort(self, val: bool):
        self._file_expl_case_insensitive_sort = val

    @property
    def file_expl_undo_size(self):
        return self._file_expl_undo_size

    @property
    def file_expl_activate_on_single_click(self):
        return self._file_expl_activate_on_single_click

    @file_expl_activate_on_single_click.setter
    def file_expl_activate_on_single_click(self, val: bool):
        self._file_expl_activate_on_single_click = val

    @property
    def temp_file_prefix(self):
        return self._temp_file_prefix

    @temp_file_prefix.setter
    def temp_file_prefix(self, val: str):
        self._temp_file_prefix = val

    @property
    def ignore_temp_files(self):
        return self._ignore_temp_files

    @property
    def ffprobe_get_duration_cmd(self):
        return self._ffprobe_get_duration_cmd

    @property
    def ffmpeg_increase_audio_cmd(self):
        return self._ffmpeg_increase_audio_cmd

    @property
    def win_maximized(self):
        return self._win_maximized

    @win_maximized.setter
    def win_maximized(self, val: bool):
        self._win_maximized = val

    @property
    def win_width(self):
        return self._win_width

    @win_width.setter
    def win_width(self, val: int):
        self._win_width = val

    @property
    def win_height(self):
        return self._win_height

    @win_height.setter
    def win_height(self, val: int):
        self._win_height = val


class FileExplorer(Gtk.VBox):
    """
    The central panel of the main window is a file explorer.
    Copied from:
    https://github.com/GNOME/pygobject/blob/master/examples/demo/demos/IconView/iconviewbasics.py
    """

    (COL_PATH,
     COL_DISPLAY_NAME,
     COL_PIXBUF,
     COL_IS_DIRECTORY,
     NUM_COLS) = range(5)

    @GObject.Signal(arg_types=(str,))
    def video_selected(self, path):
        pass

    def __init__(self):
        super().__init__()

        if not os.path.isdir(config.cwd):
            config.cwd = GLib.get_home_dir()
            if not os.path.isdir(config.cwd):
                config.cwd = '/'  # FIXME: This is not portable.
        self._parent_dir = config.cwd

        self._locations = []
        self._locations_showed_element = 0
        self._locations_init(self._parent_dir)

        # create the store and fill it with content
        self._pixbuf_lookup = {}
        self._store = self._create_store()
        self.fill_store()

        self._tool_bar = Gtk.Toolbar()
        self.pack_start(self._tool_bar, False, False, 0)

        self._back_button = Gtk.ToolButton(stock_id=Gtk.STOCK_GO_BACK)
        self._back_button.set_is_important(True)
        self._back_button.set_sensitive(False)
        self._tool_bar.insert(self._back_button, -1)

        self._forward_button = Gtk.ToolButton(stock_id=Gtk.STOCK_GO_FORWARD)
        self._forward_button.set_is_important(True)
        self._forward_button.set_sensitive(False)
        self._tool_bar.insert(self._forward_button, -1)

        self._up_button = Gtk.ToolButton(stock_id=Gtk.STOCK_GO_UP)
        self._up_button.set_is_important(True)
        self._up_button.set_sensitive(self._parent_dir != '/')  # FIXME: This is not portable.
        self._tool_bar.insert(self._up_button, -1)

        self._home_button = Gtk.ToolButton(stock_id=Gtk.STOCK_HOME)
        self._home_button.set_is_important(True)
        self._tool_bar.insert(self._home_button, -1)

        self._back_button.connect('clicked', self._back_clicked, self._store)
        self._forward_button.connect('clicked', self._forward_clicked, self._store)
        self._up_button.connect('clicked', self._up_clicked, self._store)
        self._home_button.connect('clicked', self._home_clicked, self._store)

        self._separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        self.pack_start(self._separator, False, False, 0)

        self._location_label = Gtk.Label(label=self._parent_dir)
        self._location_label.set_xalign(0)
        self._location_label.set_ellipsize(Pango.EllipsizeMode.START)
        self._location_label.set_margin_top(5)
        self._location_label.set_margin_bottom(5)
        self.pack_start(self._location_label, False, False, 0)

        self._sw = Gtk.ScrolledWindow()
        self._sw.set_shadow_type(Gtk.ShadowType.ETCHED_IN)
        self._sw.set_policy(Gtk.PolicyType.AUTOMATIC,
                            Gtk.PolicyType.AUTOMATIC)

        self.pack_start(self._sw, True, True, 0)

        self._icon_view = Gtk.IconView(model=self._store)
        self._icon_view.set_selection_mode(Gtk.SelectionMode.MULTIPLE)
        self._icon_view.set_activate_on_single_click(config.file_expl_activate_on_single_click)
        self._icon_view.set_text_column(self.COL_DISPLAY_NAME)
        self._icon_view.set_pixbuf_column(self.COL_PIXBUF)
        self._icon_view.connect('item-activated', self._item_activated, self._store)

        self._icon_view.enable_model_drag_source(Gdk.ModifierType.BUTTON1_MASK, [], Gdk.DragAction.COPY)
        self._icon_view.drag_source_add_uri_targets()
        self._icon_view.connect("drag-data-get", self._on_drag_data_get)

        self._sw.add(self._icon_view)

    def _on_drag_data_get(self, _widget, _drag_context, data, _info, _time):
        uris = []
        for selected_path in self._icon_view.get_selected_items():
            selected_iter = self._store.get_iter(selected_path)
            uri = self._store.get_value(selected_iter, self.COL_PATH)
            uri = urllib.parse.urljoin('file:', urllib.request.pathname2url(uri))
            uris.append(uri)

        data.set_uris(uris)

    @property
    def cwd(self):
        return self._parent_dir

    def set_single_click(self, val: bool):
        self._icon_view.set_activate_on_single_click(val)

    def open_location_from_place_sidebar(self, _places_sidebar, location, _open_flags):
        if location.get_path() is None:
            return

        self._parent_dir = location.get_path()
        self._locations_push(self._parent_dir)
        self._refresh(self._parent_dir)

    def _back_clicked(self, _item, _store):
        self._parent_dir = self._locations_pop()
        self._refresh(self._parent_dir)

    def _forward_clicked(self, _item, _store):
        self._parent_dir = self._locations_forward()
        self._refresh(self._parent_dir)

    def _up_clicked(self, _item, _store):
        self._parent_dir = os.path.split(self._parent_dir)[0]
        self._locations_push(self._parent_dir)
        self._refresh(self._parent_dir)

    def _home_clicked(self, _item, _store):
        self._parent_dir = GLib.get_home_dir()
        self._locations_push(self._parent_dir)
        self._refresh(self._parent_dir)

    def _item_activated(self, _icon_view, tree_path, store):
        iter_ = store.get_iter(tree_path)
        (path, is_dir) = store.get(iter_, self.COL_PATH, self.COL_IS_DIRECTORY)
        if not is_dir:
            if path.lower().endswith(config.video_extensions):
                self.emit('video_selected', path)
            return
        else:
            self._parent_dir = path
            self._locations_push(self._parent_dir)
            self._refresh(self._parent_dir)

    def _refresh(self, path: str):
        self.fill_store()
        self._location_label.set_label(path)
        self._up_button.set_sensitive(path != '/')  # FIXME: This is not portable.

    # Methods for back and forward buttons
    def _locations_init(self, path: str):
        self._locations_showed_element = 1
        self._locations.append(path)

    def _locations_push(self, path: str):
        self._back_button.set_sensitive(True)

        if self._locations_showed_element < len(self._locations):
            self._locations = self._locations[:self._locations_showed_element]
            self._forward_button.set_sensitive(False)

        if self._locations_showed_element == config.file_expl_undo_size:
            self._locations.pop(0)
        else:
            self._locations_showed_element += 1

        self._locations.append(path)

    def _locations_pop(self) -> str:
        self._forward_button.set_sensitive(True)
        self._locations_showed_element -= 1

        if self._locations_showed_element == 1:
            self._back_button.set_sensitive(False)

        return self._locations[self._locations_showed_element - 1]

    def _locations_forward(self) -> str:
        if self._locations_showed_element == len(self._locations) - 1:
            self._forward_button.set_sensitive(False)

        if self._locations_showed_element == 1:
            self._back_button.set_sensitive(True)

        path = self._locations[self._locations_showed_element]
        self._locations_showed_element += 1
        return path

    def _sort_func(self, store, a_iter, b_iter, _user_data):
        (a_name, a_is_dir) = store.get(a_iter,
                                       self.COL_DISPLAY_NAME,
                                       self.COL_IS_DIRECTORY)

        (b_name, b_is_dir) = store.get(b_iter,
                                       self.COL_DISPLAY_NAME,
                                       self.COL_IS_DIRECTORY)

        if a_name is None:
            a_name = ''

        if b_name is None:
            b_name = ''

        if (not a_is_dir) and b_is_dir:
            return 1
        elif a_is_dir and (not b_is_dir):
            return -1
        else:
            if config.file_expl_case_insensitive_sort:
                a_name = a_name.lower()
                b_name = b_name.lower()
            if a_name > b_name:
                return 1
            elif a_name < b_name:
                return -1
            else:
                return 0

    def _create_store(self):
        store = Gtk.ListStore(str, str, GdkPixbuf.Pixbuf, bool)

        # set sort column and function
        store.set_default_sort_func(self._sort_func)
        store.set_sort_column_id(-1, Gtk.SortType.ASCENDING)

        return store

    def _file_to_icon_pixbuf(self, path):
        pixbuf = None

        # get the theme icon
        f = Gio.file_new_for_path(path)
        info = f.query_info(Gio.FILE_ATTRIBUTE_STANDARD_ICON,
                            Gio.FileQueryInfoFlags.NONE,
                            None)
        gicon = info.get_icon()

        # check to see if it is an image format we support
        for f in GdkPixbuf.Pixbuf.get_formats():
            for mime_type in f.get_mime_types():
                content_type = Gio.content_type_from_mime_type(mime_type)
                if content_type is not None:
                    break

            format_gicon = Gio.content_type_get_icon(content_type)
            if format_gicon.equal(gicon):
                # gicon = f.icon_new()
                # gicon = info.set_icon(format_gicon)
                info.set_icon(format_gicon)
                break

        if gicon in self._pixbuf_lookup:
            return self._pixbuf_lookup[gicon]

        if isinstance(gicon, Gio.ThemedIcon):
            names = gicon.get_names()
            icon_theme = Gtk.IconTheme.get_default()
            for name in names:
                try:
                    pixbuf = icon_theme.load_icon(name, 64, 0)
                    break
                except GLib.GError:
                    pass

            self._pixbuf_lookup[gicon] = pixbuf

        elif isinstance(gicon, Gio.FileIcon):
            icon_file = gicon.get_file()
            path = icon_file.get_path()
            pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size(path, 72, 72)
            self._pixbuf_lookup[gicon] = pixbuf

        return pixbuf

    def fill_store(self):
        """Refresh the panel content. It is used in AppWindow"""
        self._store.clear()
        for name in os.listdir(self._parent_dir):
            if config.file_expl_show_hidden_files or not name.startswith('.'):  # FIXME: This is not portable.
                path = os.path.join(self._parent_dir, name)
                is_dir = os.path.isdir(path)
                pixbuf = self._file_to_icon_pixbuf(path)
                self._store.append([path, name, pixbuf, is_dir])


@unique
class JobStatus(Enum):
    """Job statuses. It is used in Job and JobsQueue."""
    RUNNING = 1,
    QUEUED = 2,
    FAILED = 3,
    FINISHED = 4


# Icon displayed in JobsListWidget for each job status. Assumes Adwaita theme:
# https://gitlab.gnome.org/GNOME/adwaita-icon-theme/-/tree/master/Adwaita
job_status_pixbuf = {
    JobStatus.QUEUED: 'document-open-recent-symbolic',
    JobStatus.RUNNING: 'emblem-system-symbolic',
    JobStatus.FAILED: 'computer-fail-symbolic',
    JobStatus.FINISHED: 'emblem-ok-symbolic'
}

# Column names for the Gtk.TreeView model in JobsListWidget
# Used in classes: Job, JobsQueue and JobsListWidget
(JOB_LIST_COLUMN_FILENAME,
 JOB_LIST_COLUMN_STATUS,
 JOB_LIST_COLUMN_PROGRESS,
 JOB_LIST_COLUMN_ESTTIME,
 JOB_LIST_NUM_COLUMNS) = range(5)


class Job(GObject.GObject):
    """
    There is a Job instance for every job showed in JobsListWidget.
    It is responsible for executing the ffprobe and ffmpeg commands:
     - ffprobe returns the duration of the video in seconds.
     - ffmpeg increases the audio volume of the video. For every ffmpeg
       output line, this class update the job state showed in JobsListWidget.
    """

    @GObject.Signal(arg_types=(str,))
    def job_finished(self, path):
        pass

    @GObject.Signal(arg_types=(str, str,))
    def job_finished_with_error(self, path, error):
        pass

    def __init__(self,
                 file_name: str = '',
                 model: Gtk.ListStore = None):
        super().__init__()
        self._file_name = file_name
        self._model = model

        self._list_row = self._model.append()
        self._duration = 0
        self._start_time = 0
        self._tempOutput = None
        self._volume_increase = config.volume_increase
        self._remove_subtitles = config.remove_subtitles
        self._keep_original = config.keep_original
        self._output_prefix = config.output_prefix
        self._output_suffix = config.output_suffix
        self._temp_file_prefix = config.temp_file_prefix

        # Update the jobs list widget
        self._model[self._list_row][JOB_LIST_COLUMN_FILENAME] = self._file_name
        self._model[self._list_row][JOB_LIST_COLUMN_STATUS] = job_status_pixbuf[JobStatus.QUEUED]
        self._model[self._list_row][JOB_LIST_COLUMN_PROGRESS] = 0
        self._model[self._list_row][JOB_LIST_COLUMN_ESTTIME] = ''

    def get_duration(self):
        """Launch ffprobe to get video duration. This method is the first step of the chain."""
        self._model[self._list_row][JOB_LIST_COLUMN_STATUS] = job_status_pixbuf[JobStatus.RUNNING]
        ffprobe = FfprobeLauncher(self._file_name)
        ffprobe.connect('finished', self._increase_volume)
        ffprobe.connect('finished_with_error', self._manage_error)
        GLib.idle_add(ffprobe.run)

    def _increase_volume(self, _object, duration: float):
        """Launch ffmpeg to increase the volume."""
        self._duration = duration
        if self._duration == 0:
            self._manage_error(None, "Error executing ffprobe. Can't get video's duration.")
            return

        # Choose temporary output file
        suffix = os.path.splitext(self._file_name)[1]
        directory = os.path.dirname(self._file_name)
        try:
            handle, self._tempOutput = tempfile.mkstemp(dir=directory,
                                                        suffix=suffix,
                                                        prefix=self._temp_file_prefix)
        except Exception as e:
            self._manage_error(None, 'Error creating temporal file:\n' + str(e))
            return
        else:
            os.close(handle)

        self._start_time = time.time()

        ffmpeg = FfmpegLauncher(self._file_name, self._tempOutput, self._volume_increase, self._remove_subtitles,
                                self._duration)
        ffmpeg.connect('update_state', self._update_conversion_state)
        ffmpeg.connect('finished', self._conversion_finished)
        ffmpeg.connect('finished_with_error', self._manage_error)
        GLib.idle_add(ffmpeg.run)

    def _update_conversion_state(self, _object, progress_percent: float):
        if progress_percent == 0:
            est_remaining = 0
        else:
            spent_time = time.time() - self._start_time
            est_remaining = spent_time * (100 - progress_percent) / progress_percent
        m, s = divmod(int(est_remaining), 60)
        h, m = divmod(m, 60)
        est_remaining_str = f'{h:02d}:{m:02d}:{s:02d}'

        self._model[self._list_row][JOB_LIST_COLUMN_PROGRESS] = progress_percent
        self._model[self._list_row][JOB_LIST_COLUMN_ESTTIME] = est_remaining_str

    def _conversion_finished(self, _object):
        self._model[self._list_row][JOB_LIST_COLUMN_STATUS] = job_status_pixbuf[JobStatus.FINISHED]
        self._model[self._list_row][JOB_LIST_COLUMN_PROGRESS] = 100
        self._model[self._list_row][JOB_LIST_COLUMN_ESTTIME] = ''

        if self._keep_original:
            directory, name = os.path.split(self._file_name)
            name, ext = os.path.splitext(name)
            name = directory + os.sep + self._output_prefix + name + self._output_suffix + ext
            if os.path.exists(name):
                self._manage_error(None, f'File "{name}" exists.\nNot renaming "{self._tempOutput}" to\n"{name}"')
            else:
                try:
                    os.rename(self._tempOutput, name)
                except Exception as e:
                    self._manage_error(None, f'Error renaming "{self._tempOutput}" to\n"{name}":\n\n{str(e)}')
                finally:
                    self.emit('job_finished', self._file_name)
        else:
            # self._keep_original == False
            try:
                os.remove(self._file_name)
            except Exception as e:
                self._manage_error(None, f'Error removing "{self._file_name}"\n'
                                         f'Preserving temporal output file:\n'
                                         f'"{self._tempOutput}"\n\n'
                                         f'{str(e)}')
            else:
                try:
                    os.rename(self._tempOutput, self._file_name)
                except Exception as e:
                    self._manage_error(None, f'Error renaming "{self._tempOutput}" to\n'
                                             f'"{self._file_name}":\n\n'
                                             f'{str(e)}')
                finally:
                    self.emit('job_finished', self._file_name)

    def _manage_error(self, _object, error: str):
        self._model[self._list_row][JOB_LIST_COLUMN_STATUS] = job_status_pixbuf[JobStatus.FAILED]
        self._model[self._list_row][JOB_LIST_COLUMN_ESTTIME] = '--:--:--'

        if self._tempOutput is not None and os.path.exists(self._tempOutput):
            try:
                os.remove(self._tempOutput)
            except OSError:
                pass
        self.emit('job_finished_with_error', self._file_name, error)


class JobsQueue:
    """
    Class instantiated in main. Controls the number of jobs running at
    once based on config.max_jobs. If a job ends with error shows a
    window with the error text.
    """
    def __init__(self):
        self._model = None
        self._n_running_jobs = 0
        self._jobs_queue = []

    def set_model(self, model: Gtk.ListStore):
        self._model = model

    def add_job(self, path: str):
        if self._model is None:
            return

        if self._is_queued_or_running(path):
            self._error_message(text='Duplicated entry',
                                secondary_text=f'Processing:\n{path}\n\n'
                                               'There is already a queued or running entry with this path.')
        else:
            if self._n_running_jobs >= config.max_jobs:
                self._queue_job(path)
            else:
                self._launch_job(path)

    def check_queue(self):
        while len(self._jobs_queue) > 0 and self._n_running_jobs < config.max_jobs:
            self._unqueue_job()

    def _is_queued_or_running(self, path: str):
        for i in self._model:
            if (i[JOB_LIST_COLUMN_FILENAME] == path and
                    (i[JOB_LIST_COLUMN_STATUS] == job_status_pixbuf[JobStatus.QUEUED] or
                     i[JOB_LIST_COLUMN_STATUS] == job_status_pixbuf[JobStatus.RUNNING])):
                return True

        return False

    def _launch_job(self, path: str):
        j = Job(file_name=path, model=self._model)
        j.connect('job_finished', self._finished_job)
        j.connect('job_finished_with_error', self._finished_with_error_job)
        self._n_running_jobs += 1
        j.get_duration()

    def _queue_job(self, path: str):
        j = Job(file_name=path, model=self._model)
        j.connect('job_finished', self._finished_job)
        j.connect('job_finished_with_error', self._finished_with_error_job)
        self._jobs_queue.append(j)

    def _unqueue_job(self):
        self._n_running_jobs += 1
        j = self._jobs_queue.pop(0)
        j.get_duration()

    def _finished_job(self, _object, _path: str):
        self._n_running_jobs -= 1
        self.check_queue()

    def _finished_with_error_job(self, _job, path: str, error: str):
        self._finished_job(self, path)
        self._error_message(text='Error processing file',
                            secondary_text=f'Processing:\n{path}\n\nError:\n{error}')

    def _error_message(self, text: str, secondary_text: str):
        dialog = Gtk.MessageDialog(
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.CLOSE,
            title='Error',
            text=text,
            secondary_text=secondary_text
        )
        # Allow user copy the error
        dialog.get_message_area().foreach(lambda label: label.set_selectable(True))
        dialog.show_all()
        dialog.connect('response', lambda *d: dialog.destroy())


class JobsListWidget(Gtk.ScrolledWindow):
    """
    The right panel is a jobs list made with Gtk.TreeView.
    Modified from:
    https://github.com/GNOME/pygobject/blob/master/examples/demo/demos/TreeView/liststore.py
    """

    def __init__(self):
        super().__init__()

        self.set_shadow_type(Gtk.ShadowType.ETCHED_IN)
        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        self._model = Gtk.ListStore(str,
                                    str,
                                    GObject.TYPE_INT,
                                    str)
        self._treeview = Gtk.TreeView(model=self._model)
        self._treeview.set_search_column(JOB_LIST_COLUMN_FILENAME)
        self.add(self._treeview)

        self._treeview.enable_model_drag_dest([], Gdk.DragAction.COPY)
        self._treeview.drag_dest_add_uri_targets()
        self._treeview.connect("drag-data-received", self._on_drag_data_received)

        jq.set_model(self._model)

        self._add_columns(self._treeview)

    def _on_drag_data_received(self, _widget, _drag_context, _x, _y, data, _info, _time_str):
        for uri in data.get_uris():
            # continue if it isn't a local file
            if not uri.startswith('file:///'):  # FIXME: This is not portable.
                continue
            path = urllib.request.url2pathname(uri)
            path = path[7:]  # removes 'file://'

            if os.path.isfile(path):
                if config.ignore_temp_files and os.path.basename(path).startswith(config.temp_file_prefix):
                    continue
                if path.lower().endswith(config.video_extensions):
                    jq.add_job(path)
            elif os.path.isdir(path):
                for root, dirs, files in os.walk(path, topdown=False, followlinks=True):
                    for name in files:
                        if config.ignore_temp_files and name.startswith(config.temp_file_prefix):
                            continue
                        if name.lower().endswith(config.video_extensions):
                            jq.add_job(os.path.join(root, name))

    def add_job_from_path(self, _object, path: str):
        jq.add_job(path)

    def _add_columns(self, treeview):
        # column for file names
        renderer = Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.START)
        column = Gtk.TreeViewColumn("File", renderer,
                                    text=JOB_LIST_COLUMN_FILENAME)
        column.set_expand(True)
        column.set_sort_column_id(JOB_LIST_COLUMN_FILENAME)
        treeview.append_column(column)

        # column for job status
        renderer = Gtk.CellRendererPixbuf()
        column = Gtk.TreeViewColumn("Status", renderer,
                                    icon_name=JOB_LIST_COLUMN_STATUS)
        column.set_sort_column_id(JOB_LIST_COLUMN_STATUS)
        treeview.append_column(column)

        # column for progress bar
        renderer = Gtk.CellRendererProgress()
        column = Gtk.TreeViewColumn("Progress", renderer, value=JOB_LIST_COLUMN_PROGRESS)
        column.set_sort_column_id(JOB_LIST_COLUMN_PROGRESS)
        treeview.append_column(column)

        # column for estimated remaining time
        renderer = Gtk.CellRendererText()
        column = Gtk.TreeViewColumn("Remaining time", renderer,
                                    text=JOB_LIST_COLUMN_ESTTIME)
        column.set_sort_column_id(JOB_LIST_COLUMN_ESTTIME)
        treeview.append_column(column)


class ProcessLauncher(GObject.GObject):
    """
    Process launcher with async IO.
    Modified from:
    https://gist.github.com/fthiery/da43365ceeefff8a9e3d0dd83ec24af9
    This class is not used. Instead, the child classes FfprobeLauncher and
    FfmpegLauncher are used.
    To use the ProcessLauncher class it is necessary to create a derived class
    and override at least the methods __init__, for_each_line, at_finalization
    and at_finalization_with_error.

    The super().__init__(command) call in the derived class must include the
    command executed, like super().__init__('/bin/ls').
    The for_each_line method is called for each line of the command output. The
    end of the line character set is specified in the read_upto_async call of
    the _queue_read method. In the current implementation the end of line
    character list is '\r\n' which is the correct one for ffmpeg output on Linux
    For a common Linux command the '\n' character should be sufficient.

    The at_finalization and at_finalization_with_error methods are called when
    the command is over without error and with error respectively
    """
    def __init__(self, cmd: str = None):
        super().__init__()

        if cmd is None:
            raise NotImplementedError()
        else:
            self._cmd = cmd

        self._process = None
        self._data_stream = None
        self._cancellable = None

    def run(self):
        self._cancellable = Gio.Cancellable()
        try:
            flags = Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_MERGE
            args = shlex.split(self._cmd)
            self._process = p = Gio.Subprocess.new(args, flags)
            p.wait_check_async(
                cancellable=self._cancellable,
                callback=self._on_finished
            )
            # print('Started')
            stream = p.get_stdout_pipe()
            self._data_stream = Gio.DataInputStream.new(stream)
            self._queue_read()
        except GLib.GError as e:
            traceback.print_exc()
            self.at_finalization_with_error(f'{str(e)}\n\nCommand:\n{self._cmd}')
            return

    def _queue_read(self):
        self._data_stream.read_upto_async(
            stop_chars='\r\n',  # FIXME: This is not portable.
            stop_chars_len=2,
            io_priority=GLib.PRIORITY_DEFAULT,
            cancellable=self._cancellable,
            callback=self._on_data
        )

    def _cancel_read(self):
        # print('Cancelling read')
        self._cancellable.cancel()

    def _on_finished(self, proc, results):
        # print('Process finished')
        try:
            proc.wait_check_finish(results)
        except Exception as e:
            traceback.print_exc()
            self.at_finalization_with_error(f'{str(e)}\n\nCommand:\n{self._cmd}')
        else:
            self.at_finalization()
        self._cancel_read()

    def _on_data(self, source, result):
        # FIXME: sometimes this method is executed even when the task is cancelled
        if result.had_error():
            return

        try:
            line, length = source.read_upto_finish(result)
            if line:
                # consume the stop character
                source.read_byte(self._cancellable)
                self.for_each_line(line)
        except GLib.GError as e:
            traceback.print_exc()
            self.at_finalization_with_error(f'{str(e)}\n\nCommand:\n{self._cmd}')
            return

        # read_upto_finish() returns None on error without raise any exception
        if line is not None:
            self._queue_read()

    def stop(self):
        # print('Stop')
        self._process.send_signal(signal.SIGTERM)

    def kill(self):
        # print('Kill')
        self._cancel_read()
        self._process.send_signal(signal.SIGKILL)

    def for_each_line(self, line: str):
        raise NotImplementedError()

    def at_finalization(self):
        raise NotImplementedError()

    def at_finalization_with_error(self, error: str):
        raise NotImplementedError()


class FfprobeLauncher(ProcessLauncher):
    @GObject.Signal(arg_types=(float,))
    def finished(self, duration):
        pass

    @GObject.Signal(arg_types=(str,))
    def finished_with_error(self, error):
        pass

    def __init__(self, file_name: str):
        self._duration = 0
        self._n_lines = 0
        self._cmd = config.ffprobe_get_duration_cmd.format(video_file_name=file_name)
        super().__init__(self._cmd)

    def for_each_line(self, line: str):
        if self._n_lines > 0:
            self.at_finalization_with_error(f'Error executing ffprobe:\nExpected just one line, got more:\n{line}')
        try:
            self._duration = float(line)
        except Exception as e:
            self.at_finalization_with_error(f'Error executing ffprobe:\n'
                                            f'Trying to read a float got error:\n{str(e)}\n'
                                            f'in line:\n{line}')
        finally:
            self._n_lines += 1

    def at_finalization(self):
        self.emit('finished', self._duration)

    def at_finalization_with_error(self, error):
        self.emit('finished_with_error', error)


class FfmpegLauncher(ProcessLauncher):
    @GObject.Signal(arg_types=(float,))
    def update_state(self, progress):
        pass

    @GObject.Signal()
    def finished(self):
        pass

    @GObject.Signal(arg_types=(str,))
    def finished_with_error(self, error):
        pass

    def __init__(self, file_name: str, temp_output: str, volume_increase: int, remove_subtitles: bool, duration: float):
        self._duration = duration
        self._cmd = config.ffmpeg_increase_audio_cmd.format(video_file_name_input=file_name,
                                                            video_file_name_output=temp_output,
                                                            volume_increase=volume_increase,
                                                            remove_subtitles_param='-sn' if remove_subtitles else '')
        super().__init__(self._cmd)

    def for_each_line(self, line: str):
        if line.startswith('frame='):
            time_beg = line.find(' time=')
            time_beg += 6
            time_end = line.find(' ', time_beg)
            time_str = line[time_beg:time_end]
            time_list = time_str.split(':')
            progress = (int(time_list[0]) * 3600 +
                        int(time_list[1]) * 60 +
                        float(time_list[2]))
            progress_percent = progress * 100 / self._duration
            self.emit('update_state', progress_percent)

    def at_finalization(self):
        self.emit('finished')

    def at_finalization_with_error(self, error):
        self.emit('finished_with_error', error)


class Preferences(Gtk.Window):
    """Preferences window."""

    def __init__(self):
        super().__init__()
        self._vol_increase_decimals = 1
        self._separator_margin = 5
        self.set_title('Preferences')
        self.set_border_width(10)
        self._grid = Gtk.Grid()

        self._video_ext_label = Gtk.Label(label='Video extensions: ')
        self._video_ext_entry = Gtk.Entry(text=','.join(config.video_extensions))
        self._grid.add(self._video_ext_label)
        self._grid.attach_next_to(self._video_ext_entry, self._video_ext_label, Gtk.PositionType.RIGHT, 1, 1)

        self._vol_increase_label = Gtk.Label(label='Volume increase: ')
        self._vol_increase_spin = Gtk.SpinButton(adjustment=Gtk.Adjustment(value=float(config.volume_increase),
                                                                           lower=1.0,
                                                                           upper=10.0,
                                                                           step_increment=0.1,
                                                                           page_increment=0.5,
                                                                           page_size=0.0),
                                                 climb_rate=1.0, digits=self._vol_increase_decimals)
        self._grid.attach_next_to(self._vol_increase_label, self._video_ext_label, Gtk.PositionType.BOTTOM, 1, 1)
        self._grid.attach_next_to(self._vol_increase_spin, self._vol_increase_label, Gtk.PositionType.RIGHT, 1, 1)

        self._remove_subtitles_label = Gtk.Label(label='Remove subtitles: ')
        self._remove_subtitles_toggle = Gtk.CheckButton(active=config.remove_subtitles)
        self._grid.attach_next_to(self._remove_subtitles_label, self._vol_increase_label, Gtk.PositionType.BOTTOM, 1, 1)
        self._grid.attach_next_to(self._remove_subtitles_toggle, self._remove_subtitles_label, Gtk.PositionType.RIGHT,
                                  1, 1)

        self._sep1 = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        self._sep1.set_margin_top(self._separator_margin)
        self._sep1.set_margin_bottom(self._separator_margin)
        self._grid.attach_next_to(self._sep1, self._remove_subtitles_label, Gtk.PositionType.BOTTOM, 2, 1)

        self._max_jobs_label = Gtk.Label(label='Number of jobs: ')
        self._max_jobs_spin = Gtk.SpinButton(adjustment=Gtk.Adjustment(value=config.max_jobs,
                                                                       lower=1,
                                                                       upper=os.cpu_count(),
                                                                       step_increment=1,
                                                                       page_increment=1,
                                                                       page_size=0))
        self._grid.attach_next_to(self._max_jobs_label, self._sep1, Gtk.PositionType.BOTTOM, 1, 1)
        self._grid.attach_next_to(self._max_jobs_spin, self._max_jobs_label, Gtk.PositionType.RIGHT, 1, 1)

        self._use_all_cpus_label = Gtk.Label(label='Use all CPUs: ')
        self._use_all_cpus_toggle = Gtk.CheckButton(active=False)
        self._grid.attach_next_to(self._use_all_cpus_label, self._max_jobs_label, Gtk.PositionType.BOTTOM, 1, 1)
        self._grid.attach_next_to(self._use_all_cpus_toggle, self._use_all_cpus_label, Gtk.PositionType.RIGHT, 1, 1)

        self._sep2 = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        self._sep2.set_margin_top(self._separator_margin)
        self._sep2.set_margin_bottom(self._separator_margin)
        self._grid.attach_next_to(self._sep2, self._use_all_cpus_label, Gtk.PositionType.BOTTOM, 2, 1)

        self._keep_original_label = Gtk.Label(label='Keep Original: ')
        self._keep_original_toggle = Gtk.CheckButton(active=config.keep_original)
        self._grid.attach_next_to(self._keep_original_label, self._sep2, Gtk.PositionType.BOTTOM, 1, 1)
        self._grid.attach_next_to(self._keep_original_toggle, self._keep_original_label, Gtk.PositionType.RIGHT, 1, 1)

        self._output_prefix_label = Gtk.Label(label='Output prefix: ')
        self._output_prefix_entry = Gtk.Entry(text=config.output_prefix)
        self._grid.attach_next_to(self._output_prefix_label, self._keep_original_label, Gtk.PositionType.BOTTOM, 1, 1)
        self._grid.attach_next_to(self._output_prefix_entry, self._output_prefix_label, Gtk.PositionType.RIGHT, 1, 1)

        self._output_suffix_label = Gtk.Label(label='Output suffix: ')
        self._output_suffix_entry = Gtk.Entry(text=config.output_suffix)
        self._grid.attach_next_to(self._output_suffix_label, self._output_prefix_label, Gtk.PositionType.BOTTOM, 1, 1)
        self._grid.attach_next_to(self._output_suffix_entry, self._output_suffix_label, Gtk.PositionType.RIGHT, 1, 1)

        self._sep3 = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        self._sep3.set_margin_top(self._separator_margin)
        self._sep3.set_margin_bottom(self._separator_margin)
        self._grid.attach_next_to(self._sep3, self._output_suffix_label, Gtk.PositionType.BOTTOM, 2, 1)

        self._temp_file_prefix_label = Gtk.Label(label='Temporal file prefix: ')
        self._temp_file_prefix_entry = Gtk.Entry(text=config.temp_file_prefix)
        self._grid.attach_next_to(self._temp_file_prefix_label, self._sep3, Gtk.PositionType.BOTTOM, 1, 1)
        self._grid.attach_next_to(self._temp_file_prefix_entry, self._temp_file_prefix_label, Gtk.PositionType.RIGHT, 1,
                                  1)

        if config.use_all_cpus:
            self._use_all_cpus_toggle.set_active(True)
            self._max_jobs_spin.set_sensitive(False)

        if not config.keep_original:
            self._output_prefix_entry.set_sensitive(False)
            self._output_suffix_entry.set_sensitive(False)

        self._use_all_cpus_toggle.connect('toggled', self._on_max_jobs_toggled)
        self._keep_original_toggle.connect('toggled', self._on_keep_original_toggled)

        self.add(self._grid)
        self.show_all()
        self.connect('destroy', self._on_destroy)

    def _on_max_jobs_toggled(self, toggle: Gtk.ToggleButton):
        if toggle.get_active():
            self._max_jobs_spin.set_sensitive(False)
            self._max_jobs_spin.set_value(os.cpu_count())
        else:
            self._max_jobs_spin.set_sensitive(True)

    def _on_keep_original_toggled(self, toggle: Gtk.ToggleButton):
        if toggle.get_active():
            self._output_prefix_entry.set_sensitive(True)
            self._output_suffix_entry.set_sensitive(True)
        else:
            self._output_prefix_entry.set_sensitive(False)
            self._output_suffix_entry.set_sensitive(False)

    def _on_destroy(self, _w):
        if config.max_jobs != int(self._max_jobs_spin.get_value()):
            config.max_jobs = int(self._max_jobs_spin.get_value())
            jq.check_queue()

        config.video_extensions = tuple(self._video_ext_entry.get_text().split(','))
        config.remove_subtitles = self._remove_subtitles_toggle.get_active()
        config.volume_increase = round(self._vol_increase_spin.get_value(), self._vol_increase_decimals)
        config.use_all_cpus = self._use_all_cpus_toggle.get_active()
        config.keep_original = self._keep_original_toggle.get_active()
        config.output_prefix = self._output_prefix_entry.get_text()
        config.output_suffix = self._output_suffix_entry.get_text()
        config.temp_file_prefix = self._temp_file_prefix_entry.get_text()
        self.destroy()


# This XML is here to avoid another file. This is a "one file application" with no installation instructions.
MENU_XML = """
<?xml version="1.0" encoding="UTF-8"?>
<interface>
  <menu id="app-menu">
    <section>
      <item>
        <attribute name="action">app.preferences</attribute>
        <attribute name="label" translatable="yes">_Preferences</attribute>
        <attribute name="accel">&lt;Primary&gt;p</attribute>
    </item>
    </section>
    <section>
      <item>
        <attribute name="action">win.file_expl_show_hidden_files</attribute>
        <attribute name="label" translatable="yes">Show hidden files</attribute>
      </item>
      <item>
        <attribute name="action">win.file_expl_case_insensitive_sort</attribute>
        <attribute name="label" translatable="yes">Case insensitive sort</attribute>
      </item>
      <item>
        <attribute name="action">win.file_expl_single_click</attribute>
        <attribute name="label" translatable="yes">Single click</attribute>
      </item>
    </section>
    <section>
      <item>
        <attribute name="action">app.about</attribute>
        <attribute name="label" translatable="yes">_About</attribute>
      </item>
      <item>
        <attribute name="action">app.quit</attribute>
        <attribute name="label" translatable="yes">_Quit</attribute>
        <attribute name="accel">&lt;Primary&gt;q</attribute>
    </item>
    </section>
  </menu>
</interface>
"""


class AppWindow(Gtk.ApplicationWindow):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Window size
        if config.win_maximized:
            self.maximize()
        else:
            self.unmaximize()
            self.set_default_size(config.win_width, config.win_height)

        # https://wiki.gnome.org/HowDoI/SaveWindowState
        self.connect('size-allocate', self._on_size_allocate_change)
        self.connect('window-state-event', self._on_state_event)

        # Menu actions
        file_exp_hidden_files_action = Gio.SimpleAction.new_stateful(
            "file_expl_show_hidden_files", None, GLib.Variant.new_boolean(config.file_expl_show_hidden_files)
        )
        file_exp_hidden_files_action.connect("change-state", self._on_hidden_files_toggle)
        self.add_action(file_exp_hidden_files_action)

        file_exp_case_sort_action = Gio.SimpleAction.new_stateful(
            "file_expl_case_insensitive_sort", None, GLib.Variant.new_boolean(config.file_expl_case_insensitive_sort)
        )
        file_exp_case_sort_action.connect("change-state", self._on_case_sort_toggle)
        self.add_action(file_exp_case_sort_action)

        file_exp_single_click_action = Gio.SimpleAction.new_stateful(
            "file_expl_single_click", None, GLib.Variant.new_boolean(config.file_expl_activate_on_single_click)
        )
        file_exp_single_click_action.connect("change-state", self._on_single_click_toggle)
        self.add_action(file_exp_single_click_action)

        # Build main window
        menubutton = Gtk.MenuButton(direction=Gtk.ArrowType.NONE)
        builder = Gtk.Builder.new_from_string(MENU_XML, -1)
        menubutton.set_menu_model(builder.get_object("app-menu"))

        headerbar = Gtk.HeaderBar(title='Increase video audio volume with ffmpeg')
        headerbar.set_show_close_button(True)
        headerbar.pack_start(menubutton)
        self.set_titlebar(headerbar)

        self._places = Gtk.PlacesSidebar()
        self.file_exp = FileExplorer()
        self._jobsListWidget = JobsListWidget()

        self._places.connect('open-location', self.file_exp.open_location_from_place_sidebar)
        self.file_exp.connect('video_selected', self._jobsListWidget.add_job_from_path)

        self._paned_file_exp = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        self._paned_file_exp.add1(self.file_exp)
        self._paned_file_exp.add2(self._jobsListWidget)
        # FIXME: if the window is maximized this does not work
        self._paned_file_exp.set_position(config.paned_file_expl_position)
        self._paned_file_exp.connect('notify::position', self._on_paned_file_exp_position)

        self._paned_places = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        self._paned_places.add1(self._places)
        self._paned_places.add2(self._paned_file_exp)

        self.add(self._paned_places)

    def _on_hidden_files_toggle(self, action: Gio.SimpleAction, value: bool):
        action.set_state(value)
        config.file_expl_show_hidden_files = value
        self.file_exp.fill_store()

    def _on_case_sort_toggle(self, action: Gio.SimpleAction, value: bool):
        action.set_state(value)
        config.file_expl_case_insensitive_sort = value
        self.file_exp.fill_store()

    def _on_single_click_toggle(self, action: Gio.SimpleAction, value: bool):
        action.set_state(value)
        config.file_expl_activate_on_single_click = value
        self.file_exp.set_single_click(value)

    def _on_paned_file_exp_position(self, paned: Gtk.Paned, _pspec):
        config.paned_file_expl_position = paned.get_position()

    def _on_size_allocate_change(self, w: Gtk.Window, _allocation: Gdk.Rectangle):
        if not w.is_maximized():
            width, height = w.get_size()
            config.win_width = width
            config.win_height = height

    def _on_state_event(self, _w: Gtk.Window, event: Gdk.EventWindowState):
        is_maximized = (event.new_window_state & Gdk.WindowState.MAXIMIZED != 0)
        config.win_maximized = is_maximized


class Application(Gtk.Application):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, application_id="org.example.myapp", **kwargs)
        self.window = None

    def do_startup(self):
        Gtk.Application.do_startup(self)

        preferences_action = Gio.SimpleAction.new("preferences", None)
        preferences_action.connect("activate", self._on_preferences)
        self.add_action(preferences_action)

        about_action = Gio.SimpleAction.new("about", None)
        about_action.connect("activate", self._on_about)
        self.add_action(about_action)

        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", self._on_quit)
        self.add_action(quit_action)

    def do_activate(self):
        if not self.window:
            self.window = AppWindow(application=self)
        self.window.show_all()
        self.window.present()

    def do_shutdown(self):
        config.cwd = self.window.file_exp.cwd
        config.save()
        Gtk.Application.do_shutdown(self)

    def _on_about(self, _action, _param):
        about_dialog = Gtk.AboutDialog(transient_for=self.window, modal=True)
        about_dialog.set_title('About')
        about_dialog.set_program_name('increasevol')
        about_dialog.set_comments('Increase video audio volume with ffmpeg')
        about_dialog.set_website('https://github.com/eduardoposadas/increasevol')
        about_dialog.set_website_label('Source Code at GitHub')
        about_dialog.set_logo_icon_name(None)

        try:
            gpl = ""
            with open('/usr/share/common-licenses/GPL-3', encoding="utf-8") as h:
                s = h.readlines()
                for line in s:
                    gpl += line

            about_dialog.set_license(gpl)
        except Exception as e:
            print(e)

        about_dialog.connect('response', lambda w, res: w.destroy())
        about_dialog.present()

    def _on_quit(self, _action, _param):
        self.quit()

    def _on_preferences(self, _action, _param):
        Preferences()


def check_prerequisites():
    """Check commands in config.required_cmd tuple are in PATH."""
    error = False
    error_str = ''
    for cmd in config.required_cmd:
        if shutil.which(cmd) is None:
            error = True
            error_str += f'\n{cmd}'

    if error:
        error_str = f'Missing commands:{error_str}'
        dialog = Gtk.MessageDialog(
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.CLOSE,
            title='Error',
            text='Does not meet the prerequisites',
            secondary_text=error_str
        )
        dialog.run()
        raise SystemExit(error_str)


if __name__ == '__main__':
    config = Configuration()
    check_prerequisites()
    jq = JobsQueue()
    app = Application()
    app.run(sys.argv)
