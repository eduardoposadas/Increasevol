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

from typing import Any
import os
import sys
import math
from enum import Enum, unique
import shlex
import shutil
import signal
import time
from collections import namedtuple
from collections.abc import Callable
import tempfile
import traceback
import configparser
import urllib.parse
import urllib.request
import gi
gi.require_version('Gtk', '3.0')  # noqa: E402
gi.require_version('Gdk', '3.0')  # noqa: E402
gi.require_version('Pango', '1.0')  # noqa: E402
gi.require_version('GdkPixbuf', '2.0')  # noqa: E402
from gi.repository import GObject, GLib, Gio, GdkPixbuf, Pango, Gdk, Gtk

# time.struct_time with nanoseconds
struct_time_ns = namedtuple('struct_time_ns',
                            ['tm_year', 'tm_mon', 'tm_mday', 'tm_hour', 'tm_min', 'tm_sec', 'tm_wday',
                             'tm_yday', 'tm_isdst', 'tm_ns'])


class Configuration:
    """Set default configuration values and load/save configuration values."""

    def __init__(self):
        self._video_extensions = ('mp4', 'avi', 'mkv')
        self._remove_subtitles = False
        self._volume_increase = 3
        self._audio_encoder = 'mp3'  # Key for _audio_encoder_quality
        self._audio_quality = 3  # Index for _audio_encoder_quality[_audio_encoder]
        self._keep_original = False
        self._output_prefix = ''  # Only used if _keep_original == True
        self._output_suffix = '_Vol-inc'  # Only used if _keep_original == True
        self._use_all_cpus = True
        self._max_jobs = os.cpu_count()  # Only used if _use_all_cpus == False
        self._file_expl_show_hidden_files = False
        self._file_expl_case_sensitive_sort = False
        self._file_expl_activate_on_single_click = True
        self._temp_file_prefix = 'ffmpeg_temp_'
        self._ignore_temp_files = True
        self._show_milliseconds = False
        # Do not change configuration options below this line
        self._file = os.path.join(os.path.expanduser("~"), '.config', 'increasevol')  # FIXME: This is not portable.
        self._required_cmd = ('ffprobe', 'ffmpeg')
        self._cwd = GLib.get_home_dir()
        self._win_maximized = False
        self._win_width = 783
        self._win_height = 309
        self._file_expl_undo_size = 100  # Stack size for "back" button
        self._paned_file_expl_position = 400
        """ audio_encoder_quality:
        Key: ffmpeg audio encoder (audio_encoder in _ffmpeg_increase_audio_cmd)
        Value: list with valid quality values for the audio encoder, from lowest to highest quality
               (audio_quality in _ffmpeg_increase_audio_cmd) """
        self._audio_encoder_quality = {
            'mp3':       [9.9,   8, 5,   3,  0],  # https://trac.ffmpeg.org/wiki/Encode/MP3
            'aac':       [0.1, 0.5, 1, 1.5,  2],  # https://trac.ffmpeg.org/wiki/Encode/AAC
            'libvorbis': [0,   2.5, 5, 7.5, 10],  # https://ffmpeg.org/ffmpeg-codecs.html#libvorbis
            'flac':      [0,     0, 0,   0,  0],  # https://ffmpeg.org/ffmpeg-codecs.html#flac-2 (flac doesn't have -q)
            # 'libopus': [],
        }
        self._n_qualities = len(self._audio_encoder_quality[self._audio_encoder])
        self._ffprobe_get_duration_cmd = 'ffprobe -v error -show_entries format=duration ' \
                                         '-of default=noprint_wrappers=1:nokey=1 "{video_file_name}"'
        self._ffmpeg_increase_audio_cmd = 'ffmpeg -hide_banner -y -i "{video_file_name_input}" -map 0 -c:v copy ' \
                                          '{remove_subtitles_param} -c:s copy ' \
                                          '-c:a {audio_encoder} -q:a {audio_quality} ' \
                                          '-filter:a volume={volume_increase} ' \
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
        self._audio_encoder = temp_conf.get('DEFAULT', 'audio_encoder', fallback=self._audio_encoder)
        self._audio_quality = temp_conf.getint('DEFAULT', 'audio_quality', fallback=self._audio_quality)
        self._keep_original = temp_conf.getboolean('DEFAULT', 'keep_original', fallback=self._keep_original)
        self._output_prefix = temp_conf.get('DEFAULT', 'output_prefix', fallback=self._output_prefix)
        self._output_suffix = temp_conf.get('DEFAULT', 'output_suffix', fallback=self._output_suffix)
        self._use_all_cpus = temp_conf.getboolean('DEFAULT', 'use_all_cpus', fallback=self._use_all_cpus)
        self._max_jobs = temp_conf.getint('DEFAULT', 'max_jobs', fallback=self._max_jobs)
        self._file_expl_show_hidden_files = temp_conf.getboolean('DEFAULT', 'file_explorer_show_hidden_files',
                                                                 fallback=self._file_expl_show_hidden_files)
        self._file_expl_case_sensitive_sort = temp_conf.getboolean('DEFAULT',
                                                                   'file_explorer_case_sensitive_sort',
                                                                   fallback=self._file_expl_case_sensitive_sort)
        self._file_expl_activate_on_single_click = temp_conf.getboolean('DEFAULT',
                                                                        'file_explorer_activate_on_single_click',
                                                                        fallback=
                                                                        self._file_expl_activate_on_single_click)
        self._temp_file_prefix = temp_conf.get('DEFAULT', 'temp_file_prefix', fallback=self._temp_file_prefix)
        self._ignore_temp_files = temp_conf.getboolean('DEFAULT', 'ignore_temp_files', fallback=self._ignore_temp_files)
        self._show_milliseconds = temp_conf.getboolean('DEFAULT', 'show_milliseconds', fallback=self._show_milliseconds)
        self._paned_file_expl_position = temp_conf.getint('DEFAULT', 'paned_file_explorer_position',
                                                          fallback=self._paned_file_expl_position)
        self._win_maximized = temp_conf.getboolean('DEFAULT', 'win_maximized', fallback=self._win_maximized)
        self._win_width = temp_conf.getint('DEFAULT', 'win_width', fallback=self._win_width)
        self._win_height = temp_conf.getint('DEFAULT', 'win_height', fallback=self._win_height)

    def save(self):
        """Save configuration values to configuration file"""
        temp_conf = configparser.ConfigParser()
        temp_conf['DEFAULT'] = {
            'directory': self._cwd,
            'video_extensions': ','.join(self._video_extensions),
            'remove_subtitles': self._remove_subtitles,
            'volume_increase': self._volume_increase,
            'audio_encoder': self._audio_encoder,
            'audio_quality': self._audio_quality,
            'keep_original': self._keep_original,
            'output_prefix': self._output_prefix,
            'output_suffix': self._output_suffix,
            'use_all_cpus': self._use_all_cpus,
            'max_jobs': self._max_jobs,
            'file_explorer_show_hidden_files': self._file_expl_show_hidden_files,
            'file_explorer_case_sensitive_sort': self._file_expl_case_sensitive_sort,
            'file_explorer_activate_on_single_click': self._file_expl_activate_on_single_click,
            'temp_file_prefix': self._temp_file_prefix,
            'ignore_temp_files': self._ignore_temp_files,
            'show_milliseconds': self._show_milliseconds,
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
            error_message(text='Error',
                          secondary_text='Error saving configuration',
                          modal=True)

    @property
    def file(self) -> str:
        return self._file

    @property
    def required_cmd(self) -> tuple:
        return self._required_cmd

    @property
    def cwd(self) -> str:
        return self._cwd

    @cwd.setter
    def cwd(self, val: str):
        self._cwd = val

    @property
    def video_extensions(self) -> tuple:
        return self._video_extensions

    @video_extensions.setter
    def video_extensions(self, val: tuple):
        self._video_extensions = val

    @property
    def remove_subtitles(self) -> bool:
        return self._remove_subtitles

    @remove_subtitles.setter
    def remove_subtitles(self, val: bool):
        self._remove_subtitles = val

    @property
    def volume_increase(self) -> float:
        return self._volume_increase

    @volume_increase.setter
    def volume_increase(self, val: float):
        self._volume_increase = val

    @property
    def audio_encoder(self) -> str:
        return self._audio_encoder

    @audio_encoder.setter
    def audio_encoder(self, val: str):
        self._audio_encoder = val

    @property
    def audio_encoders(self) -> list:
        return list(self._audio_encoder_quality)

    @property
    def audio_quality(self) -> int:
        return self._audio_quality

    @audio_quality.setter
    def audio_quality(self, val: int):
        self._audio_quality = val

    @property
    def audio_encoder_quality(self) -> int:
        return self._audio_encoder_quality[self._audio_encoder][self._audio_quality]

    @property
    def n_qualities(self) -> int:
        return self._n_qualities

    @property
    def keep_original(self) -> bool:
        return self._keep_original

    @keep_original.setter
    def keep_original(self, val: bool):
        self._keep_original = val

    @property
    def output_prefix(self) -> str:
        return self._output_prefix

    @output_prefix.setter
    def output_prefix(self, val: str):
        self._output_prefix = val

    @property
    def output_suffix(self) -> str:
        return self._output_suffix

    @output_suffix.setter
    def output_suffix(self, val: str):
        self._output_suffix = val

    @property
    def use_all_cpus(self) -> bool:
        return self._use_all_cpus

    @use_all_cpus.setter
    def use_all_cpus(self, val: bool):
        self._use_all_cpus = val

    @property
    def max_jobs(self) -> int:
        return self._max_jobs

    @max_jobs.setter
    def max_jobs(self, val: int):
        self._max_jobs = val

    @property
    def paned_file_expl_position(self) -> int:
        return self._paned_file_expl_position

    @paned_file_expl_position.setter
    def paned_file_expl_position(self, val: int):
        self._paned_file_expl_position = val

    @property
    def file_expl_show_hidden_files(self) -> bool:
        return self._file_expl_show_hidden_files

    @file_expl_show_hidden_files.setter
    def file_expl_show_hidden_files(self, val: bool):
        self._file_expl_show_hidden_files = val

    @property
    def file_expl_case_sensitive_sort(self) -> bool:
        return self._file_expl_case_sensitive_sort

    @file_expl_case_sensitive_sort.setter
    def file_expl_case_sensitive_sort(self, val: bool):
        self._file_expl_case_sensitive_sort = val

    @property
    def file_expl_undo_size(self) -> int:
        return self._file_expl_undo_size

    @property
    def file_expl_activate_on_single_click(self) -> bool:
        return self._file_expl_activate_on_single_click

    @file_expl_activate_on_single_click.setter
    def file_expl_activate_on_single_click(self, val: bool):
        self._file_expl_activate_on_single_click = val

    @property
    def temp_file_prefix(self) -> str:
        return self._temp_file_prefix

    @temp_file_prefix.setter
    def temp_file_prefix(self, val: str):
        self._temp_file_prefix = val

    @property
    def ignore_temp_files(self) -> bool:
        return self._ignore_temp_files

    @ignore_temp_files.setter
    def ignore_temp_files(self, val: bool):
        self._ignore_temp_files = val

    @property
    def show_milliseconds(self) -> bool:
        return self._show_milliseconds

    @show_milliseconds.setter
    def show_milliseconds(self, val: bool):
        self._show_milliseconds = val

    @property
    def ffprobe_get_duration_cmd(self) -> str:
        return self._ffprobe_get_duration_cmd

    @property
    def ffmpeg_increase_audio_cmd(self) -> str:
        return self._ffmpeg_increase_audio_cmd

    @property
    def win_maximized(self) -> bool:
        return self._win_maximized

    @win_maximized.setter
    def win_maximized(self, val: bool):
        self._win_maximized = val

    @property
    def win_width(self) -> int:
        return self._win_width

    @win_width.setter
    def win_width(self, val: int):
        self._win_width = val

    @property
    def win_height(self) -> int:
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

    @GObject.Signal(arg_types=[str, ])
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
        self._fill_store()

        self._tool_bar = Gtk.Toolbar()
        self.pack_start(self._tool_bar, False, False, 0)

        self._back_button = Gtk.ToolButton(icon_name='go-previous')
        self._back_button.set_sensitive(False)
        self._tool_bar.insert(self._back_button, -1)

        self._forward_button = Gtk.ToolButton(icon_name='go-next')
        self._forward_button.set_sensitive(False)
        self._tool_bar.insert(self._forward_button, -1)

        self._up_button = Gtk.ToolButton(icon_name='go-up')
        self._up_button.set_sensitive(self._parent_dir != '/')  # FIXME: This is not portable.
        self._tool_bar.insert(self._up_button, -1)

        self._refresh_button = Gtk.ToolButton(icon_name='view-refresh')
        self._tool_bar.insert(self._refresh_button, -1)

        self._home_button = Gtk.ToolButton(icon_name='go-home')
        self._tool_bar.insert(self._home_button, -1)

        self._back_button.connect('clicked', self._back_clicked)
        self._forward_button.connect('clicked', self._forward_clicked)
        self._up_button.connect('clicked', self._up_clicked)
        self._refresh_button.connect('clicked', self.refresh_clicked)
        self._home_button.connect('clicked', self._home_clicked)

        self._separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        self.pack_start(self._separator, False, False, 0)

        self._location_label = Gtk.Label(label=self._parent_dir)
        self._location_label.set_selectable(True)
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

    def refresh_clicked(self, _item):
        """It is used in AppWindow"""
        self._fill_store()

    def _back_clicked(self, _item):
        self._parent_dir = self._locations_pop()
        self._refresh(self._parent_dir)

    def _forward_clicked(self, _item):
        self._parent_dir = self._locations_forward()
        self._refresh(self._parent_dir)

    def _up_clicked(self, _item):
        self._parent_dir = os.path.dirname(self._parent_dir)
        self._locations_push(self._parent_dir)
        self._refresh(self._parent_dir)

    def _home_clicked(self, _item):
        self._parent_dir = GLib.get_home_dir()
        self._locations_push(self._parent_dir)
        self._refresh(self._parent_dir)

    def _item_activated(self, _icon_view, tree_path, store):
        iter_ = store.get_iter(tree_path)
        (path, is_dir) = store.get(iter_, self.COL_PATH, self.COL_IS_DIRECTORY)
        if not is_dir:
            self.emit('video_selected', path)
        else:
            self._parent_dir = path
            self._locations_push(self._parent_dir)
            self._refresh(self._parent_dir)

    def _refresh(self, path: str):
        self._fill_store()
        self._location_label.set_label(path)
        self._up_button.set_sensitive(path != '/')  # FIXME: This is not portable.

    # Methods for the locations stack for "back" and "forward" buttons
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
            if not config.file_expl_case_sensitive_sort:
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

    def _fill_store(self):
        self._store.clear()
        for name in os.listdir(self._parent_dir):
            if ((config.ignore_temp_files and name.startswith(config.temp_file_prefix)) or
                    (not config.file_expl_show_hidden_files and name.startswith('.'))):  # FIXME: This is not portable.
                continue
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
    FINISHED = 4,
    TERMINATED = 5


# Icon displayed in JobsListWidget for each job status. Assumes Adwaita theme:
# https://gitlab.gnome.org/GNOME/adwaita-icon-theme/-/tree/master/Adwaita
job_status_pixbuf = {
    JobStatus.QUEUED: 'document-open-recent-symbolic',
    JobStatus.RUNNING: 'emblem-system-symbolic',
    JobStatus.FAILED: 'computer-fail-symbolic',
    JobStatus.FINISHED: 'emblem-ok-symbolic',
    JobStatus.TERMINATED: 'window-close-symbolic'
}

# Column names for the Gtk.ListStore model in JobsListWidget
# Used in classes: Job, JobsQueue and JobsListWidget
# Only fields with COLUMN are displayed
(JOB_LIST_ID,
 JOB_LIST_COLUMN_FILENAME,
 JOB_LIST_COLUMN_STATUS,
 JOB_LIST_COLUMN_PROGRESS,
 JOB_LIST_COLUMN_ESTTIME,
 JOB_LIST_START_TIME,
 JOB_LIST_END_TIME,
 JOB_LIST_ERROR_STRING,
 JOB_LIST_VOLUME_INC,
 JOB_LIST_AUDIO_ENC,
 JOB_LIST_KEEP_ORIGINAL,
 JOB_LIST_OUTPUT_FILE,
 JOB_LIST_NUM_COLUMNS
 ) = range(13)


class Job(GObject.GObject):
    """
    There is a Job instance for every job showed in JobsListWidget.
    It is responsible for executing the ffprobe and ffmpeg commands:
     - ffprobe returns the duration of the video in seconds.
     - ffmpeg increases the audio volume of the video. For every ffmpeg
       output line, this class update the job state showed in JobsListWidget.
    """

    @GObject.Signal(arg_types=[str, ])
    def job_finished(self, path):
        pass

    @GObject.Signal(arg_types=[str, str, ])
    def job_finished_with_error(self, path, error):
        pass

    def __init__(self,
                 id_: int,
                 file_name: str = '',
                 model: Gtk.ListStore = None):
        super().__init__()
        self.id_ = id_
        self.file_name = file_name
        self._output_file_name = ''
        self._model = model
        self._ffprobe = None
        self._ffmpeg = None

        self._row = self._model.append()
        self._duration = 0
        self._tempOutput = None
        self._volume_increase = config.volume_increase
        self._audio_encoder = config.audio_encoder
        self._audio_quality = config.audio_encoder_quality
        self._remove_subtitles = config.remove_subtitles
        self._keep_original = config.keep_original
        self._output_prefix = config.output_prefix
        self._output_suffix = config.output_suffix
        self._temp_file_prefix = config.temp_file_prefix

        # Update the jobs list widget
        self._model[self._row][JOB_LIST_COLUMN_FILENAME] = self.file_name
        self._model[self._row][JOB_LIST_COLUMN_STATUS] = job_status_pixbuf[JobStatus.QUEUED]
        self._model[self._row][JOB_LIST_COLUMN_PROGRESS] = 0
        self._model[self._row][JOB_LIST_COLUMN_ESTTIME] = ''

        # Update hidden model fields
        self._model[self._row][JOB_LIST_ID] = self.id_
        self._model[self._row][JOB_LIST_START_TIME] = 0
        self._model[self._row][JOB_LIST_END_TIME] = 0
        self._model[self._row][JOB_LIST_AUDIO_ENC] = self._audio_encoder
        self._model[self._row][JOB_LIST_VOLUME_INC] = self._volume_increase
        self._model[self._row][JOB_LIST_KEEP_ORIGINAL] = self._keep_original
        self._model[self._row][JOB_LIST_OUTPUT_FILE] = self._output_file_name
        self._model[self._row][JOB_LIST_ERROR_STRING] = ''

    # def __del__(self):
    #     print(f'__del__ Job id: {self.id_} file: {self.file_name}')

    def get_duration(self):
        """Launch ffprobe to get video duration. This method is the first step of the chain."""
        self._model[self._row][JOB_LIST_COLUMN_STATUS] = job_status_pixbuf[JobStatus.RUNNING]
        self._model[self._row][JOB_LIST_START_TIME] = time.time_ns()

        self._ffprobe = FfprobeLauncher(self.file_name)
        self._ffprobe.connect('finished', self._increase_volume)
        self._ffprobe.connect('finished_with_error', self._manage_error)
        self._ffprobe.connect('terminated', self._manage_termination)
        GLib.idle_add(self._ffprobe.run)

    def _increase_volume(self, _object, duration: float):
        """Launch ffmpeg to increase the volume."""
        self._ffprobe = None
        self._duration = duration
        if self._duration == 0:
            return

        # Check output name doesn't exist if user wants to keep the original file
        if self._keep_original:
            directory, name = os.path.split(self.file_name)
            name, ext = os.path.splitext(name)
            self._output_file_name = directory + os.sep + self._output_prefix + name + self._output_suffix + ext
            self._model[self._row][JOB_LIST_OUTPUT_FILE] = self._output_file_name
            if os.path.exists(self._output_file_name):
                self._manage_error(None, f'Output file "{self._output_file_name}" exists.', False)
                return

        # Choose temporary output file
        suffix = os.path.splitext(self.file_name)[1]
        directory = os.path.dirname(self.file_name)
        try:
            handle, self._tempOutput = tempfile.mkstemp(dir=directory,
                                                        suffix=suffix,
                                                        prefix=self._temp_file_prefix)
        except Exception as e:
            self._manage_error(None, 'Error creating temporal file:\n' + str(e), True)
            return
        else:
            os.close(handle)

        self._ffmpeg = FfmpegLauncher(self.file_name, self._tempOutput, self._volume_increase, self._audio_encoder,
                                      self._audio_quality, self._remove_subtitles, self._duration)
        self._ffmpeg.connect('update_state', self._update_conversion_state)
        self._ffmpeg.connect('finished', self._conversion_finished)
        self._ffmpeg.connect('finished_with_error', self._manage_error)
        self._ffmpeg.connect('terminated', self._manage_termination)
        GLib.idle_add(self._ffmpeg.run)

    def _update_conversion_state(self, _object, progress_percent: float):
        if progress_percent == 0:
            est_remaining = 0
        else:
            spent_time = time.time_ns() - self._model[self._row][JOB_LIST_START_TIME]
            est_remaining = spent_time * (100 - progress_percent) / progress_percent

        self._model[self._row][JOB_LIST_COLUMN_PROGRESS] = progress_percent
        self._model[self._row][JOB_LIST_COLUMN_ESTTIME] = format_time_ns(est_remaining)

    def _conversion_finished(self, _object):
        self._ffmpeg = None
        self._model[self._row][JOB_LIST_COLUMN_STATUS] = job_status_pixbuf[JobStatus.FINISHED]
        self._model[self._row][JOB_LIST_COLUMN_PROGRESS] = 100
        self._model[self._row][JOB_LIST_END_TIME] = time.time_ns()

        spent_time = self._model[self._row][JOB_LIST_END_TIME] - self._model[self._row][JOB_LIST_START_TIME]
        self._model[self._row][JOB_LIST_COLUMN_ESTTIME] = f'Total: {format_time_ns(spent_time)}'

        if self._keep_original:
            if os.path.exists(self._output_file_name):
                self._manage_error(None, f'File "{self._output_file_name}" exists.\n'
                                         f'Not renaming "{self._tempOutput}" to\n"{self._output_file_name}"',
                                   False)
            else:
                try:
                    os.rename(self._tempOutput, self._output_file_name)
                except Exception as e:
                    self._manage_error(None, f'Error renaming "{self._tempOutput}" to\n'
                                             f'"{self._output_file_name}":\n\n{str(e)}', False)
                finally:
                    self.emit('job_finished', self.file_name)
        else:
            # self._keep_original == False
            try:
                os.remove(self.file_name)
            except Exception as e:
                self._manage_error(None, f'Error removing "{self.file_name}"\n'
                                         f'Preserving temporal output file:\n'
                                         f'"{self._tempOutput}"\n\n'
                                         f'{str(e)}',
                                   False)
            else:
                try:
                    os.rename(self._tempOutput, self.file_name)
                except Exception as e:
                    self._manage_error(None, f'Error renaming "{self._tempOutput}" to\n'
                                             f'"{self.file_name}":\n\n'
                                             f'{str(e)}',
                                       False)
                finally:
                    self.emit('job_finished', self.file_name)

    def _manage_error(self, _object, error: str, remove_temp_output: bool):
        self._ffprobe = None
        self._ffmpeg = None
        self._model[self._row][JOB_LIST_COLUMN_STATUS] = job_status_pixbuf[JobStatus.FAILED]
        self._model[self._row][JOB_LIST_COLUMN_ESTTIME] = '--:--:--'
        self._model[self._row][JOB_LIST_END_TIME] = time.time_ns()
        self._model[self._row][JOB_LIST_ERROR_STRING] = error

        if remove_temp_output and self._tempOutput is not None and os.path.exists(self._tempOutput):
            try:
                os.remove(self._tempOutput)
            except OSError:
                pass
        self.emit('job_finished_with_error', self.file_name, error)

    def _manage_termination(self, _object):
        self._ffprobe = None
        self._ffmpeg = None
        self._model[self._row][JOB_LIST_COLUMN_STATUS] = job_status_pixbuf[JobStatus.TERMINATED]
        self._model[self._row][JOB_LIST_END_TIME] = time.time_ns()
        spent_time = self._model[self._row][JOB_LIST_END_TIME] - self._model[self._row][JOB_LIST_START_TIME]
        self._model[self._row][JOB_LIST_COLUMN_ESTTIME] = f'Term. at: {format_time_ns(spent_time)}'
        self.emit('job_finished', self.file_name)

    def terminate(self):
        if self._ffprobe is not None:
            self._ffprobe.terminate()
        if self._ffmpeg is not None:
            self._ffmpeg.terminate()


class JobsQueue(GObject.GObject):
    """
    Class instantiated in main. Controls the number of jobs running at
    once based on config.max_jobs. If a job ends with error shows a
    window with the error text.
    """

    @GObject.Signal()
    def job_finished(self):
        pass

    def __init__(self):
        super().__init__()
        self._model = None
        self._job_id = 0
        self._job_queue = []
        self._running_jobs = []

    def set_model(self, model: Gtk.ListStore):
        self._model = model

    def add_job(self, path: str):
        if self._model is None:
            return

        if self._is_queued_or_running(path):
            error_message(text='Duplicated entry',
                          secondary_text=f'Processing:\n{path}\n\n'
                                         'There is already a queued or running entry with this path.')
        else:
            if len(self._running_jobs) >= config.max_jobs:
                self._queue_job(path)
            else:
                self._launch_job(path)

    def remove_jobs(self, _action: Gio.SimpleAction, _param: Any, job_id_list: list[int]):
        for row in self._model:
            id_ = row[JOB_LIST_ID]
            if id_ in job_id_list:
                job_id_list.remove(id_)
                status = row[JOB_LIST_COLUMN_STATUS]
                if (status == job_status_pixbuf[JobStatus.FAILED] or
                        status == job_status_pixbuf[JobStatus.FINISHED] or
                        status == job_status_pixbuf[JobStatus.TERMINATED]):
                    self._model.remove(row.iter)
                elif status == job_status_pixbuf[JobStatus.QUEUED]:
                    # remove job from queue
                    [self._job_queue.remove(j) for j in self._job_queue if j.id_ == id_]
                    self._model.remove(row.iter)
                elif status == job_status_pixbuf[JobStatus.RUNNING]:
                    pass
                    # self._kill_job(id_)
                    # self._model.remove(row.iter)
                else:
                    raise ValueError('Unexpected status')

    def force_launch_queued_jobs(self, _action: Gio.SimpleAction, _param: Any, job_id_list: list[int]):
        for job in [j for j in self._job_queue if j.id_ in job_id_list]:
            self._job_queue.remove(job)
            self._running_jobs.append(job)
            job.get_duration()

    def launch_again_failed_jobs(self, _action: Gio.SimpleAction, _param: Any, job_id_list: list[int]):
        [self.add_job(i[JOB_LIST_COLUMN_FILENAME]) for i in self._model if i[JOB_LIST_ID] in job_id_list]
        # for i in self._model:
        #     if i[JOB_LIST_ID] in job_id_list:
        #         self.add_job(i[JOB_LIST_COLUMN_FILENAME])
        #         job_id_list.remove(i[JOB_LIST_ID])
        #         if not job_id_list:
        #             return

    def terminate_jobs(self, _action: Gio.SimpleAction, _param: Any, job_id_list: list[int]):
        [job.terminate() for job in self._running_jobs if job.id_ in job_id_list]
        # for job in [j for j in self._running_jobs if j.id_ in job_id_list]:
        #     job.terminate()

    def check_queue(self):
        while len(self._job_queue) > 0 and len(self._running_jobs) < config.max_jobs:
            self._dequeue_job()

    def _is_queued_or_running(self, path: str) -> bool:
        path_list = [job.file_name for job in self._running_jobs] + \
                    [job.file_name for job in self._job_queue]
        if path in path_list:
            return True
        else:
            return False

    def _next_job_id(self) -> int:
        id_ = self._job_id
        self._job_id += 1
        return id_

    def _launch_job(self, path: str):
        j = Job(id_=self._next_job_id(), file_name=path, model=self._model)
        j.connect('job_finished', self._finished_job)
        j.connect('job_finished_with_error', self._finished_with_error_job)
        self._running_jobs.append(j)
        j.get_duration()

    def _queue_job(self, path: str):
        j = Job(id_=self._next_job_id(), file_name=path, model=self._model)
        j.connect('job_finished', self._finished_job)
        j.connect('job_finished_with_error', self._finished_with_error_job)
        self._job_queue.append(j)

    def _dequeue_job(self):
        j = self._job_queue.pop(0)
        self._running_jobs.append(j)
        j.get_duration()

    def _finished_job(self, job, _path: str):
        self._running_jobs.remove(job)
        self.check_queue()
        self.emit('job_finished')

    def _finished_with_error_job(self, job, path: str, error: str):
        self._finished_job(job, path)
        error_message(text='Error processing file',
                      secondary_text=f'Processing:\n{path}\n\nError:\n{error}')


class JobsListWidget(Gtk.ScrolledWindow):
    """
    The right panel is a jobs list made with Gtk.TreeView.
    Modified from:
    https://github.com/GNOME/pygobject/blob/master/examples/demo/demos/TreeView/liststore.py
    Tooltip general idea:
    https://athenajc.gitbooks.io/python-gtk-3-api/content/gtk-group/gtktooltip.html
    Context menu idea:
    https://docs.gtk.org/gtk3/treeview-tutorial.html#context-menus-on-right-click
    How to make dynamic menus using Gio.Menu (Gtk.Menu is deprecated):
    https://discourse.gnome.org/t/how-to-create-menus-for-apps-using-python/2413/22
    """

    def __init__(self):
        super().__init__()

        self.set_shadow_type(Gtk.ShadowType.ETCHED_IN)
        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        self._model = Gtk.ListStore(int,
                                    str,
                                    str,
                                    int,
                                    str,
                                    float,
                                    float,
                                    str,
                                    float,
                                    str,
                                    bool,
                                    str)
        self._treeview = Gtk.TreeView(model=self._model, rubber_banding=True, has_tooltip=True)
        self._treeview.set_search_column(JOB_LIST_COLUMN_FILENAME)
        self._add_columns(self._treeview)
        self.add(self._treeview)

        self._tv_selection = self._treeview.get_selection()
        self._tv_selection.set_mode(Gtk.SelectionMode.MULTIPLE)

        # Lists of jobs for popup menu when several jobs are selected
        self._queued_jobs = []
        self._running_jobs = []
        self._failed_jobs = []
        self._finished_jobs = []
        self._terminated_jobs = []

        actions = (
            ('remove_queued',     jq.remove_jobs,              self._queued_jobs),
            ('remove_failed',     jq.remove_jobs,              self._failed_jobs),
            ('remove_terminated', jq.remove_jobs,              self._terminated_jobs),
            ('remove_finished',   jq.remove_jobs,              self._finished_jobs),
            ('launch_queued',     jq.force_launch_queued_jobs, self._queued_jobs),
            ('launch_failed',     jq.launch_again_failed_jobs, self._failed_jobs),
            ('launch_terminated', jq.launch_again_failed_jobs, self._terminated_jobs),
            ('terminate',         jq.terminate_jobs,           self._running_jobs),
        )
        self._action_group = Gio.SimpleActionGroup()
        for (name, callback, list_) in actions:
            sa = Gio.SimpleAction(name=name, parameter_type=None, enabled=True)
            sa.connect("activate", callback, list_)
            self._action_group.add_action(sa)
        self._treeview.insert_action_group('app', self._action_group)

        self._treeview.connect('button-press-event', self._on_button_press)
        self._treeview.connect('query-tooltip', self._on_query_tooltip)

        self._treeview.enable_model_drag_dest([], Gdk.DragAction.COPY)
        self._treeview.drag_dest_add_uri_targets()
        self._treeview.connect("drag-data-received", self._on_drag_data_received)

        jq.set_model(self._model)

    def _on_button_press(self, widget, event):
        # single click with the right mouse button?
        if event.type == Gdk.EventType.BUTTON_PRESS and event.button == 3:
            self._view_popup_menu(widget, event)
            return Gdk.EVENT_STOP
        return Gdk.EVENT_PROPAGATE

    def _view_popup_menu(self, _widget, event):
        # path, column, cell_x, cell_y = self._treeview.get_path_at_pos(event.x, event.y)
        returned_tuple = self._treeview.get_path_at_pos(event.x, event.y)
        if returned_tuple is None:
            return
        path, *_ = returned_tuple
        n_selected = self._tv_selection.count_selected_rows()
        popover_menu = Gio.Menu()

        self._queued_jobs.clear()
        self._running_jobs.clear()
        self._failed_jobs.clear()
        self._finished_jobs.clear()
        self._terminated_jobs.clear()

        #  If one or no rows are selected or
        #  multiple rows are selected but the mouse is not over a selected row
        if (n_selected <= 1 or
                (n_selected > 1 and not self._tv_selection.path_is_selected(path))):
            id_, file_name, status = self._model.get(self._model.get_iter(path),
                                                     JOB_LIST_ID,
                                                     JOB_LIST_COLUMN_FILENAME,
                                                     JOB_LIST_COLUMN_STATUS)
            self._queued_jobs.append(id_)
            self._running_jobs.append(id_)
            self._failed_jobs.append(id_)
            self._finished_jobs.append(id_)
            self._terminated_jobs.append(id_)

            file_name = os.path.basename(file_name)
            file_name = file_name.replace('_', '__')  # Avoid use _ as menu accelerator mark

            if status == job_status_pixbuf[JobStatus.QUEUED]:
                popover_menu.append(f'Remove from queue {file_name}', 'app.remove_queued')
                popover_menu.append(f'Launch now {file_name}', 'app.launch_queued')
            elif (status == job_status_pixbuf[JobStatus.FAILED] or
                  status == job_status_pixbuf[JobStatus.TERMINATED]):
                popover_menu.append(f'Remove from list {file_name}', 'app.remove_queued')  # jq.remove_jobs works
                popover_menu.append(f'Launch again {file_name}', 'app.launch_failed')
            elif status == job_status_pixbuf[JobStatus.FINISHED]:
                popover_menu.append(f'Remove from list {file_name}', 'app.remove_queued')
            elif status == job_status_pixbuf[JobStatus.RUNNING]:
                popover_menu.append(f'Terminate processing {file_name}', 'app.terminate')
            else:
                raise ValueError('Unexpected status')

        else:  # Several rows are selected and the mouse is over a selected row.
            for row_path in self._tv_selection.get_selected_rows()[1]:
                id_, status = self._model.get(self._model.get_iter(row_path), JOB_LIST_ID, JOB_LIST_COLUMN_STATUS)
                if status == job_status_pixbuf[JobStatus.QUEUED]:
                    self._queued_jobs.append(id_)
                elif status == job_status_pixbuf[JobStatus.RUNNING]:
                    self._running_jobs.append(id_)
                elif status == job_status_pixbuf[JobStatus.FAILED]:
                    self._failed_jobs.append(id_)
                elif status == job_status_pixbuf[JobStatus.FINISHED]:
                    self._finished_jobs.append(id_)
                elif status == job_status_pixbuf[JobStatus.TERMINATED]:
                    self._terminated_jobs.append(id_)
                else:
                    raise ValueError('Unexpected status')

            if len(self._queued_jobs) > 0:
                section = Gio.Menu()
                section.append('Remove queued jobs from queue', 'app.remove_queued')
                section.append('Launch queued jobs now', 'app.launch_queued')
                popover_menu.append_section(label='Queued jobs', section=section)
            if len(self._failed_jobs) > 0:
                section = Gio.Menu()
                section.append('Remove failed jobs from list', 'app.remove_failed')
                section.append('Launch failed jobs again', 'app.launch_failed')
                popover_menu.append_section(label='Failed jobs', section=section)
            if len(self._terminated_jobs) > 0:
                section = Gio.Menu()
                section.append('Remove terminated jobs from list', 'app.remove_terminated')
                section.append('Launch terminated jobs again', 'app.launch_terminated')
                popover_menu.append_section(label='Terminated jobs', section=section)
            if len(self._finished_jobs) > 0:
                section = Gio.Menu()
                section.append('Remove finished jobs from list', 'app.remove_finished')
                popover_menu.append_section(label='Finished jobs', section=section)
            if len(self._running_jobs) > 0:
                section = Gio.Menu()
                section.append('Terminate processing running jobs', 'app.terminate')
                popover_menu.append_section(label='Running jobs', section=section)

        popover = Gtk.Popover.new_from_model(relative_to=self._treeview, model=popover_menu)
        popover.set_position(Gtk.PositionType.BOTTOM)
        rect = Gdk.Rectangle()
        rect.x = event.x
        rect.y = event.y + 20
        rect.width = rect.height = 1
        popover.set_pointing_to(rect)
        popover.popup()

    def _on_query_tooltip(self, widget, x, y, keyboard_mode, tooltip):
        # success, cellx, celly, model, path, iter_ = widget.get_tooltip_context(x, y, keyboard_mode)
        success, *_, iter_ = widget.get_tooltip_context(x, y, keyboard_mode)
        if not success:
            return False
        n_selected = self._tv_selection.count_selected_rows()

        #  If one or no rows are selected or
        #  multiple rows are selected but the mouse is not over a selected row
        if (n_selected <= 1 or
                (n_selected > 1 and not self._tv_selection.iter_is_selected(iter_))):
            (file_name, audio_enc, volume_inc,
             keep_original, output_file, status,
             start_time, end_time, est_time,
             error_string) = self._model.get(iter_,
                                             JOB_LIST_COLUMN_FILENAME, JOB_LIST_AUDIO_ENC, JOB_LIST_VOLUME_INC,
                                             JOB_LIST_KEEP_ORIGINAL, JOB_LIST_OUTPUT_FILE, JOB_LIST_COLUMN_STATUS,
                                             JOB_LIST_START_TIME, JOB_LIST_END_TIME, JOB_LIST_COLUMN_ESTTIME,
                                             JOB_LIST_ERROR_STRING)
            file_name = os.path.basename(file_name)

            if not keep_original:
                output_file_name_str = ''
            else:
                output_file_name = os.path.basename(output_file)
                output_file_name_str = f'Output file:\t\t\t{output_file_name}\n'

            if status == job_status_pixbuf[JobStatus.QUEUED]:
                status_str = "Queued"
            elif status == job_status_pixbuf[JobStatus.RUNNING]:
                status_str = "Running"
            elif status == job_status_pixbuf[JobStatus.FAILED]:
                status_str = "Failed"
            elif status == job_status_pixbuf[JobStatus.FINISHED]:
                status_str = "Finished"
            elif status == job_status_pixbuf[JobStatus.TERMINATED]:
                status_str = "Terminated"
            else:
                raise ValueError('Unexpected status')

            start_time_str = ''
            end_time_str = ''
            estimated_end_time_str = ''
            elapsed_time_str = ''
            if start_time != 0:
                status_str += '\n'
                temp = localtime_ns(start_time)
                start_time_str = f'Start time:\t\t\t{format_localtime_ns(temp)}\n'

                if end_time != 0:
                    temp = localtime_ns(end_time)
                    end_time_str = f'End time:\t\t\t{format_localtime_ns(temp)}\n'

                    elapsed_time = end_time - start_time
                    elapsed_time_str = f'Elapsed time:\t\t{format_time_ns(elapsed_time)}'
                elif est_time != '':  # and end_time == 0
                    h, m, s = est_time.split(':')
                    est_time_ns = time.time_ns() + int((int(h) * 3600 + int(m) * 60 + float(s)) * 10e8)
                    estimated_end_time_str = f'Estimated end time:\t{format_localtime_ns(localtime_ns(est_time_ns))}'

            if error_string != '':
                error_string = f'\nError:\n{error_string}'
                if elapsed_time_str != '':
                    elapsed_time_str += '\n'
                if estimated_end_time_str != '':
                    estimated_end_time_str += '\n'

            tooltip.set_text(f'File:\t\t\t\t{file_name}\n'
                             f'Keep Original:\t\t{keep_original}\n'
                             f'{output_file_name_str}'
                             f'Audio encoder:\t\t{audio_enc}\n'
                             f'Volume increase:\t{volume_inc}\n'
                             f'Status:\t\t\t\t{status_str}'
                             f'{start_time_str}{end_time_str}{estimated_end_time_str}{elapsed_time_str}{error_string}')
            return True

        else:  # Several rows are selected and the mouse is over a selected row.
            total_queued_jobs = 0
            total_finished_jobs = 0
            total_running_jobs = 0
            total_time = 0
            start_time = float('+Infinity')
            end_time = 0
            est_time = 0
            for row_path in self._tv_selection.get_selected_rows()[1]:
                status, est_time_str, start, end = self._model.get(self._model.get_iter(row_path),
                                                                   JOB_LIST_COLUMN_STATUS,
                                                                   JOB_LIST_COLUMN_ESTTIME,
                                                                   JOB_LIST_START_TIME,
                                                                   JOB_LIST_END_TIME)
                if status == job_status_pixbuf[JobStatus.FINISHED]:
                    total_finished_jobs += 1
                    total_time += end - start
                    if start < start_time:
                        start_time = start
                    if end > end_time:
                        end_time = end

                if status == job_status_pixbuf[JobStatus.RUNNING] and est_time_str != '':
                    total_running_jobs += 1
                    h, m, s = est_time_str.split(':')
                    t = int((int(h) * 3600 + int(m) * 60 + float(s)) * 10e8)
                    if t > est_time:
                        est_time = t

                if status == job_status_pixbuf[JobStatus.QUEUED]:
                    total_queued_jobs += 1

            if total_finished_jobs == 0:
                start_time_str = '00:00:00'
                end_time_str = '00:00:00'
                elapsed_time_str = '00:00:00'
                avg_elapsed_time_str = ''
                accumulated_time_str = '00:00:00'
                avg_time_str = '00:00:00'
                est_end_time_queued_str = ''
            else:
                elapsed_time = end_time - start_time
                start_time = localtime_ns(start_time)
                end_time = localtime_ns(end_time)
                avg_time = total_time // total_finished_jobs
                avg_elapsed_time = elapsed_time // total_finished_jobs

                elapsed_time_str = format_time_ns(elapsed_time)
                start_time_str = format_localtime_ns(start_time)
                end_time_str = format_localtime_ns(end_time)
                accumulated_time_str = format_time_ns(total_time)
                avg_time_str = format_time_ns(avg_time)
                avg_elapsed_time_str = f'Average elapsed time:\t\t{format_time_ns(avg_elapsed_time)}\n'

                if total_queued_jobs == 0 and total_running_jobs == 0:
                    est_end_time_queued_str = ''
                else:
                    est_end_time_queued = (time.time_ns() + est_time +
                                           (avg_time * math.ceil(total_queued_jobs / config.max_jobs)))
                    est_end_time_queued = localtime_ns(est_end_time_queued)
                    est_end_time_queued_str = f'\n\nEstimated end time:\t\t{format_localtime_ns(est_end_time_queued)}'

            tooltip.set_text(f'Statistics of {total_finished_jobs} completed jobs:\n'
                             f'Start time:\t\t\t\t\t{start_time_str}\n'
                             f'End time:\t\t\t\t\t{end_time_str}\n'
                             f'Elapsed time:\t\t\t\t{elapsed_time_str}\n'
                             f'{avg_elapsed_time_str}'
                             f'Total accumulated time:\t\t{accumulated_time_str}\n'
                             f'Average completion time:\t{avg_time_str}'
                             f'{est_end_time_queued_str}')
            return True

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
                else:
                    error_message(text='Not a video file', secondary_text=f'File:\n{path}')
            elif os.path.isdir(path):
                for root, dirs, files in os.walk(path, topdown=False, followlinks=True):
                    for name in files:
                        if config.ignore_temp_files and name.startswith(config.temp_file_prefix):
                            continue
                        if name.lower().endswith(config.video_extensions):
                            jq.add_job(os.path.join(root, name))

    def add_job_from_path(self, _object, path: str):
        if path.lower().endswith(config.video_extensions):
            jq.add_job(path)
        else:
            error_message(text='Not a video file', secondary_text=f'File:\n{path}')

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
    and:
        - In the __init__ method of the derived class set self._cmd before
          calling super.__init__(), for example:
            self._cmd = '/bin/ls'
            super.__init__()
        - override at least the methods for_each_line, at_finalization,
    at_finalization_with_error and at_termination.

    The for_each_line method is called for each line of the command output. The
    end of the line character set is specified in the read_upto_async call of
    the _queue_read method. In the current implementation the end of line
    character list is '\r\n' which is the correct one for ffmpeg output on
    Linux. For a common Linux command the '\n' character should be sufficient.

    The at_finalization and at_finalization_with_error methods are called when
    the command terminates without error and with error respectively.

    The at_termination method is called when the process is terminated with the
    terminate() method.
    """
    def __init__(self):
        super().__init__()

        if not self._cmd:
            raise NotImplementedError()

        self._process = None
        self._data_stream = None
        self._cancellable = None
        self._term_signaled = False

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
            self.at_finalization_with_error(f'{e.message}\n\nCommand:\n{self._cmd}')
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
        except GLib.GError as e:
            self._cancel_read()
            if (self._term_signaled and proc.get_if_exited() and not proc.get_successful() and
                    e.domain == 'g-spawn-exit-error-quark' and e.code == 255):  # FIXME: This is not portable.
                self.at_termination()
            else:
                traceback.print_exc()
                self.at_finalization_with_error(f'{e.message}\n\nCommand:\n{self._cmd}')
        else:
            self._cancel_read()
            self.at_finalization()
        finally:
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
            self.at_finalization_with_error(f'{e.message}\n\nCommand:\n{self._cmd}')
            return

        # read_upto_finish() returns None on error without raise any exception
        if line is not None:
            self._queue_read()

    def terminate(self):
        # print('Terminated')
        self._term_signaled = True
        self._process.send_signal(signal.SIGTERM)

    def kill(self):
        # print('Kill')
        self._process.send_signal(signal.SIGKILL)

    def for_each_line(self, line: str):
        raise NotImplementedError()

    def at_finalization(self):
        raise NotImplementedError()

    def at_finalization_with_error(self, error: str):
        raise NotImplementedError()

    def at_termination(self):
        raise NotImplementedError()


class FfprobeLauncher(ProcessLauncher):
    @GObject.Signal(arg_types=[float, ])
    def finished(self, duration):
        pass

    @GObject.Signal(arg_types=[str, bool, ])
    def finished_with_error(self, error, remove_temp_output):
        pass

    @GObject.Signal()
    def terminated(self):
        pass

    def __init__(self, file_name: str):
        self._error = False
        self._duration = 0
        self._n_lines = 0
        self._cmd = config.ffprobe_get_duration_cmd.format(video_file_name=file_name)
        super().__init__()

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
        if not self._error:
            self._error = True
            self.emit('finished_with_error', error, True)

    def at_termination(self):
        self.emit('terminated')


class FfmpegLauncher(ProcessLauncher):
    @GObject.Signal(arg_types=[float, ])
    def update_state(self, progress):
        pass

    @GObject.Signal()
    def finished(self):
        pass

    @GObject.Signal(arg_types=[str, bool, ])
    def finished_with_error(self, error, remove_temp_output):
        pass

    @GObject.Signal()
    def terminated(self):
        pass

    def __init__(self, file_name: str, temp_output: str, volume_increase: float, audio_encoder: str,
                 audio_quality: float, remove_subtitles: bool, duration: float):
        self._error = False
        self._duration = duration
        self._cmd = config.ffmpeg_increase_audio_cmd.format(video_file_name_input=file_name,
                                                            video_file_name_output=temp_output,
                                                            volume_increase=volume_increase,
                                                            audio_encoder=audio_encoder,
                                                            audio_quality=audio_quality,
                                                            remove_subtitles_param='-sn' if remove_subtitles else '')
        super().__init__()

    def for_each_line(self, line: str):
        if line.startswith('frame='):
            time_beg = line.find(' time=')
            time_beg += 6
            time_end = line.find(' ', time_beg)
            time_str = line[time_beg:time_end]
            h, m, s = time_str.split(':')
            progress = int(h) * 3600 + int(m) * 60 + float(s)
            progress_percent = progress * 100 / self._duration
            self.emit('update_state', progress_percent)

    def at_finalization(self):
        self.emit('finished')

    def at_finalization_with_error(self, error):
        if not self._error:
            self._error = True
            self.emit('finished_with_error', error, True)

    def at_termination(self):
        self.emit('terminated')


class Preferences(Gtk.Window):
    """Preferences window."""

    def __init__(self, _action: Gio.SimpleAction, _param: Any):
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

        self._sep1 = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        self._sep1.set_margin_top(self._separator_margin)
        self._sep1.set_margin_bottom(self._separator_margin)
        self._grid.attach_next_to(self._sep1, self._video_ext_label, Gtk.PositionType.BOTTOM, 2, 1)

        self._vol_increase_label = Gtk.Label(label='Volume increase: ')
        self._vol_increase_spin = Gtk.SpinButton(climb_rate=1.0,
                                                 digits=self._vol_increase_decimals,
                                                 adjustment=Gtk.Adjustment(value=float(config.volume_increase),
                                                                           lower=0.1,
                                                                           upper=10.0,
                                                                           step_increment=0.1,
                                                                           page_increment=0.5,
                                                                           page_size=0.0))
        self._grid.attach_next_to(self._vol_increase_label, self._sep1, Gtk.PositionType.BOTTOM, 1, 1)
        self._grid.attach_next_to(self._vol_increase_spin, self._vol_increase_label, Gtk.PositionType.RIGHT, 1, 1)

        self._audio_encoder_label = Gtk.Label(label='Audio encoder: ')
        self._audio_encoder_combo = Gtk.ComboBoxText()
        for i, enc in enumerate(config.audio_encoders):
            self._audio_encoder_combo.append_text(enc)
            if enc == config.audio_encoder:
                self._audio_encoder_combo.set_active(i)
        self._grid.attach_next_to(self._audio_encoder_label, self._vol_increase_label, Gtk.PositionType.BOTTOM, 1, 1)
        self._grid.attach_next_to(self._audio_encoder_combo, self._audio_encoder_label, Gtk.PositionType.RIGHT, 1, 1)

        self._audio_quality_label = Gtk.Label(label='Audio quality: ')
        self._audio_quality_label.set_margin_bottom(27)  # FIXME. How to center the label?
        self._audio_quality_scale = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL,
                                              adjustment=Gtk.Adjustment(value=config.audio_quality,
                                                                        lower=0,
                                                                        upper=config.n_qualities - 1,
                                                                        step_increment=1,
                                                                        page_increment=1,
                                                                        page_size=0))
        self._audio_quality_scale.set_draw_value(False)
        self._audio_quality_scale.add_mark(value=0, position=Gtk.PositionType.BOTTOM, markup='Min')
        for i in range(1, config.n_qualities - 1):
            self._audio_quality_scale.add_mark(value=i, position=Gtk.PositionType.BOTTOM)
        self._audio_quality_scale.add_mark(value=config.n_qualities - 1, position=Gtk.PositionType.BOTTOM, markup='Max')
        self._grid.attach_next_to(self._audio_quality_label, self._audio_encoder_label, Gtk.PositionType.BOTTOM, 1, 1)
        self._grid.attach_next_to(self._audio_quality_scale, self._audio_quality_label, Gtk.PositionType.RIGHT, 1, 1)

        self._sep2 = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        self._sep2.set_margin_top(self._separator_margin)
        self._sep2.set_margin_bottom(self._separator_margin)
        self._grid.attach_next_to(self._sep2, self._audio_quality_label, Gtk.PositionType.BOTTOM, 2, 1)

        self._remove_subtitles_label = Gtk.Label(label='Remove subtitles: ')
        self._remove_subtitles_toggle = Gtk.CheckButton(active=config.remove_subtitles)
        self._grid.attach_next_to(self._remove_subtitles_label, self._sep2, Gtk.PositionType.BOTTOM, 1, 1)
        self._grid.attach_next_to(self._remove_subtitles_toggle, self._remove_subtitles_label, Gtk.PositionType.RIGHT,
                                  1, 1)

        self._sep3 = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        self._sep3.set_margin_top(self._separator_margin)
        self._sep3.set_margin_bottom(self._separator_margin)
        self._grid.attach_next_to(self._sep3, self._remove_subtitles_label, Gtk.PositionType.BOTTOM, 2, 1)

        self._max_jobs_label = Gtk.Label(label='Number of jobs: ')
        self._max_jobs_spin = Gtk.SpinButton(adjustment=Gtk.Adjustment(value=config.max_jobs,
                                                                       lower=1,
                                                                       upper=os.cpu_count(),
                                                                       step_increment=1,
                                                                       page_increment=1,
                                                                       page_size=0))
        self._grid.attach_next_to(self._max_jobs_label, self._sep3, Gtk.PositionType.BOTTOM, 1, 1)
        self._grid.attach_next_to(self._max_jobs_spin, self._max_jobs_label, Gtk.PositionType.RIGHT, 1, 1)

        self._use_all_cpus_label = Gtk.Label(label='Use all CPUs: ')
        self._use_all_cpus_toggle = Gtk.CheckButton(active=False)
        self._grid.attach_next_to(self._use_all_cpus_label, self._max_jobs_label, Gtk.PositionType.BOTTOM, 1, 1)
        self._grid.attach_next_to(self._use_all_cpus_toggle, self._use_all_cpus_label, Gtk.PositionType.RIGHT, 1, 1)

        self._sep4 = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        self._sep4.set_margin_top(self._separator_margin)
        self._sep4.set_margin_bottom(self._separator_margin)
        self._grid.attach_next_to(self._sep4, self._use_all_cpus_label, Gtk.PositionType.BOTTOM, 2, 1)

        self._keep_original_label = Gtk.Label(label='Keep Original: ')
        self._keep_original_toggle = Gtk.CheckButton(active=config.keep_original)
        self._grid.attach_next_to(self._keep_original_label, self._sep4, Gtk.PositionType.BOTTOM, 1, 1)
        self._grid.attach_next_to(self._keep_original_toggle, self._keep_original_label, Gtk.PositionType.RIGHT, 1, 1)

        self._output_prefix_label = Gtk.Label(label='Output prefix: ')
        self._output_prefix_entry = Gtk.Entry(text=config.output_prefix)
        self._grid.attach_next_to(self._output_prefix_label, self._keep_original_label, Gtk.PositionType.BOTTOM, 1, 1)
        self._grid.attach_next_to(self._output_prefix_entry, self._output_prefix_label, Gtk.PositionType.RIGHT, 1, 1)

        self._output_suffix_label = Gtk.Label(label='Output suffix: ')
        self._output_suffix_entry = Gtk.Entry(text=config.output_suffix)
        self._grid.attach_next_to(self._output_suffix_label, self._output_prefix_label, Gtk.PositionType.BOTTOM, 1, 1)
        self._grid.attach_next_to(self._output_suffix_entry, self._output_suffix_label, Gtk.PositionType.RIGHT, 1, 1)

        self._sep5 = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        self._sep5.set_margin_top(self._separator_margin)
        self._sep5.set_margin_bottom(self._separator_margin)
        self._grid.attach_next_to(self._sep5, self._output_suffix_label, Gtk.PositionType.BOTTOM, 2, 1)

        self._ignore_temp_files_label = Gtk.Label(label='Ignore temporal files: ')
        self._ignore_temp_files_toggle = Gtk.CheckButton(active=config.ignore_temp_files)
        self._grid.attach_next_to(self._ignore_temp_files_label, self._sep5, Gtk.PositionType.BOTTOM, 1, 1)
        self._grid.attach_next_to(self._ignore_temp_files_toggle, self._ignore_temp_files_label, Gtk.PositionType.RIGHT, 1, 1)

        self._temp_file_prefix_label = Gtk.Label(label='Temporal file prefix: ')
        self._temp_file_prefix_entry = Gtk.Entry(text=config.temp_file_prefix)
        self._grid.attach_next_to(self._temp_file_prefix_label, self._ignore_temp_files_label, Gtk.PositionType.BOTTOM, 1, 1)
        self._grid.attach_next_to(self._temp_file_prefix_entry, self._temp_file_prefix_label, Gtk.PositionType.RIGHT, 1, 1)
        self._show_milliseconds_label = Gtk.Label(label='Show milliseconds: ')
        self._show_milliseconds_toggle = Gtk.CheckButton(active=config.show_milliseconds)
        self._grid.attach_next_to(self._show_milliseconds_label, self._temp_file_prefix_label, Gtk.PositionType.BOTTOM, 1, 1)
        self._grid.attach_next_to(self._show_milliseconds_toggle, self._show_milliseconds_label, Gtk.PositionType.RIGHT, 1, 1)
        # Avoid selection of _video_ext_entry text
        self._use_all_cpus_toggle.grab_focus()

        # Kubuntu GTK theme doesn't show scale ticks
        provider = Gtk.CssProvider()
        provider.load_from_data(b"scale marks mark indicator {min-height: 5px; min-width: 5px;}")
        self._audio_quality_scale.get_style_context().add_provider(provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        if config.use_all_cpus:
            self._use_all_cpus_toggle.set_active(True)
            self._max_jobs_spin.set_sensitive(False)

        if not config.keep_original:
            self._output_prefix_entry.set_sensitive(False)
            self._output_suffix_entry.set_sensitive(False)

        self._changed_value_id = self._audio_quality_scale.connect('change-value', self._on_audio_quality_change_value)
        self._use_all_cpus_toggle.connect('toggled', self._on_max_jobs_toggled)
        self._keep_original_toggle.connect('toggled', self._on_keep_original_toggled)

        self.add(self._grid)
        self.show_all()
        self.connect('destroy', self._on_destroy)

    def _on_audio_quality_change_value(self, _scale, scroll_type, value):
        """
        Allows only discrete values for the Gtk.Scale widget.
        https://stackoverflow.com/questions/39013193/is-there-an-official-way-to-create-discrete-valued-range-widget-in-gtk
        """
        # find the closest valid value
        # value = min(range(config.n_qualities), key=lambda v: abs(value-v))
        value = round(value)
        # emit a new signal with the new value
        self._audio_quality_scale.handler_block(self._changed_value_id)
        self._audio_quality_scale.emit('change-value', scroll_type, value)
        self._audio_quality_scale.handler_unblock(self._changed_value_id)
        return True  # prevent the signal from escalating

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
        config.audio_encoder = self._audio_encoder_combo.get_active_text()
        config.audio_quality = int(self._audio_quality_scale.get_value())
        config.use_all_cpus = self._use_all_cpus_toggle.get_active()
        config.keep_original = self._keep_original_toggle.get_active()
        config.output_prefix = self._output_prefix_entry.get_text()
        config.output_suffix = self._output_suffix_entry.get_text()
        config.ignore_temp_files = self._ignore_temp_files_toggle.get_active()
        config.temp_file_prefix = self._temp_file_prefix_entry.get_text()
        config.show_milliseconds = self._show_milliseconds_toggle.get_active()
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
    </item>
    </section>
    <section>
      <item>
        <attribute name="action">win.file_expl_show_hidden_files</attribute>
        <attribute name="label" translatable="yes">Show hidden files</attribute>
      </item>
      <item>
        <attribute name="action">win.file_expl_case_sensitive_sort</attribute>
        <attribute name="label" translatable="yes">Case sensitive sort</attribute>
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

        # Main menu stateful actions
        actions = (
            ("file_expl_show_hidden_files", self._on_hidden_files_toggle, config.file_expl_show_hidden_files),
            ("file_expl_case_sensitive_sort", self._on_case_sort_toggle, config.file_expl_case_sensitive_sort),
            ("file_expl_single_click", self._on_single_click_toggle, config.file_expl_activate_on_single_click)
        )
        for (name, callback, value) in actions:
            action = Gio.SimpleAction.new_stateful(name, None, GLib.Variant.new_boolean(value))
            action.connect("change-state", callback)
            self.add_action(action)

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
        jq.connect('job_finished',  self.file_exp.refresh_clicked)

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
        self.file_exp.refresh_clicked(None)

    def _on_case_sort_toggle(self, action: Gio.SimpleAction, value: bool):
        action.set_state(value)
        config.file_expl_case_sensitive_sort = value
        self.file_exp.refresh_clicked(None)

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
    def __init__(self):
        super().__init__(application_id="org.example.myapp")
        self.window = None

    def do_startup(self):
        Gtk.Application.do_startup(self)

        actions = (
            ("preferences", Preferences, ["<Control>p"]),
            ("about", self._on_about, ["<Control>a"]),
            ("quit", lambda _action, _param: self.quit(), ["<Control>q"])
        )
        for (name, callback, accels) in actions:
            action = Gio.SimpleAction(name=name, parameter_type=None, enabled=True)
            action.connect('activate', callback)
            self.add_action(action)
            self.set_accels_for_action("app." + name, accels)

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


def error_message(text: str, secondary_text: str, modal: bool = False):
    dialog = Gtk.MessageDialog(
        message_type=Gtk.MessageType.ERROR,
        buttons=Gtk.ButtonsType.CLOSE,
        title='Error',
        text=text,
        secondary_text=secondary_text
    )
    dialog.connect('response', lambda *d: dialog.destroy())
    dialog.get_message_area().foreach(lambda label: label.set_selectable(True))  # Allow user copy dialog's text
    if modal:
        dialog.run()
    else:
        dialog.show_all()


def localtime_ns(ns_: int) -> struct_time_ns:
    """time.localtime() with nanoseconds"""
    s, ns = divmod(int(ns_), int(10e8))
    st = time.localtime(s)
    return struct_time_ns(st.tm_year, st.tm_mon, st.tm_mday, st.tm_hour, st.tm_min, st.tm_sec,
                          st.tm_wday, st.tm_yday, st.tm_isdst, ns)


def format_localtime_ns(st: struct_time_ns) -> str:
    if config.show_milliseconds:
        return f'{st.tm_hour:02d}:{st.tm_min:02d}:{st.tm_sec:02d}.{str(st.tm_ns)[0:3]}'
    else:
        return f'{st.tm_hour:02d}:{st.tm_min:02d}:{st.tm_sec:02d}'


def format_time_ns(ns_: int) -> str:
    s, ns = divmod(int(ns_), int(10e8))
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    if config.show_milliseconds:
        return f'{h:02d}:{m:02d}:{s:02d}.{str(ns)[0:3]}'
    else:
        return f'{h:02d}:{m:02d}:{s:02d}'


def check_prerequisites():
    """Check commands in config.required_cmd tuple are in PATH."""
    error = False
    missing_commands = ''
    for cmd in config.required_cmd:
        if shutil.which(cmd) is None:
            error = True
            missing_commands += f'\n{cmd}'

    if error:
        error_message(text='Does not meet the prerequisites. Install:',
                      secondary_text=missing_commands,
                      modal=True)
        raise SystemExit(missing_commands)


if __name__ == '__main__':
    config = Configuration()
    check_prerequisites()
    jq = JobsQueue()
    app = Application()
    app.run(sys.argv)
