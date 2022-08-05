# Copyright 2017 Mycroft AI Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
from os.path import abspath, basename
from datetime import timedelta
from ovos_utils.log import LOG
from mycroft.messagebus.message import Message, dig_for_message
from ovos_plugin_common_play.ocp.utils import extract_metadata
from ovos_plugin_common_play.ocp.status import PlaybackType, TrackState
from ovos_plugin_common_play.ocp.mycroft_cps import MycroftAudioService
from ovos_plugin_common_play.ocp.base import _uri2meta


def ensure_uri(s):
    """Interprete paths as file:// uri's.

    Args:
        s: string to be checked

    Returns:
        if s is uri, s is returned otherwise file:// is prepended
    """
    if isinstance(s, str):
        if '://' not in s:
            return 'file://' + abspath(s)
        else:
            return s
    elif isinstance(s, (tuple, list)):
        if '://' not in s[0]:
            return 'file://' + abspath(s[0]), s[1]
        else:
            return s
    else:
        raise ValueError('Invalid track')


class AudioService:
    """AudioService class for interacting with OCP subsystem

    Args:
        bus: Mycroft messagebus connection
    """

    def __init__(self, bus):
        self.bus = bus

    def _format_msg(self, msg_type, msg_data=None):
        # this method ensures all skills are .forward from the utterance
        # that triggered the skill, this ensures proper routing and metadata
        msg_data = msg_data or {}
        msg = dig_for_message()
        if msg:
            msg = msg.forward(msg_type, msg_data)
        else:
            msg = Message(msg_type, msg_data)
        # at this stage source == skills, lets indicate audio service took over
        sauce = msg.context.get("source")
        if sauce == "skills":
            msg.context["source"] = "audio_service"
        return msg

    # OCP bus api
    def queue(self, tracks=None):
        """Queue up a track to playing playlist.

        TODO allow rich metadata for OCP:
         - support dicts in tracks
         NOTE: skills using this won't be compatible with mycroft-core ...

        Args:
            tracks: track uri or list of track uri's
                    Each track can be added as a tuple with (uri, mime)
                    to give a hint of the mime type to the system
        """
        tracks = tracks or []
        if isinstance(tracks, (str, tuple)):
            tracks = [tracks]
        elif not isinstance(tracks, list):
            raise ValueError
        tracks = [_uri2meta(t) for t in tracks]
        msg = self._format_msg('ovos.common_play.playlist.queue',
                               {'tracks': tracks})
        self.bus.emit(msg)

    def play(self, tracks=None, utterance=None, repeat=None):
        """Start playback.

        TODO handle utterance, idea:
         - allow services to register .voc files
         - match utterance against vocs in OCP
         - select audio service based on parsing
         eg. "play X in spotify"

        TODO allow rich metadata for OCP:
         - support dicts in tracks
        NOTE: skills using this won't be compatible with mycroft-core ...

        Args:
            tracks: track uri or list of track uri's
                    Each track can be added as a tuple with (uri, mime)
                    to give a hint of the mime type to the system
            utterance: forward utterance for further processing by the
                        audio service.
            repeat: if the playback should be looped
        """
        repeat = repeat or False
        tracks = tracks or []
        utterance = utterance or ''
        if isinstance(tracks, (str, tuple)):
            tracks = [tracks]
        elif not isinstance(tracks, list):
            raise ValueError
        tracks = [_uri2meta(t) for t in tracks]

        msg = self._format_msg('ovos.common_play.play',
                               {"media": tracks[0],
                                "playlist": tracks,
                                "utterance": utterance,
                                'repeat': repeat})
        self.bus.emit(msg)

    def stop(self):
        """Stop the track."""
        msg = self._format_msg("ovos.common_play.stop")
        self.bus.emit(msg)

    def next(self):
        """Change to next track."""
        msg = self._format_msg("ovos.common_play.next")
        self.bus.emit(msg)

    def prev(self):
        """Change to previous track."""
        msg = self._format_msg("ovos.common_play.previous")
        self.bus.emit(msg)

    def pause(self):
        """Pause playback."""
        msg = self._format_msg("ovos.common_play.pause")
        self.bus.emit(msg)

    def resume(self):
        """Resume paused playback."""
        msg = self._format_msg("ovos.common_play.resume")
        self.bus.emit(msg)

    def seek(self, seconds=1):
        """Seek X seconds.

        Args:
            seconds (int): number of seconds to seek, if negative rewind
        """
        if isinstance(seconds, timedelta):
            seconds = seconds.total_seconds()
        if seconds < 0:
            self.seek_backward(abs(seconds))
        else:
            self.seek_forward(seconds)

    def seek_forward(self, seconds=1):
        """Skip ahead X seconds.

        Args:
            seconds (int): number of seconds to skip
        """
        if isinstance(seconds, timedelta):
            seconds = seconds.total_seconds()
        msg = self._format_msg('ovos.common_play.seek',
                               {"seconds": seconds})
        self.bus.emit(msg)

    def seek_backward(self, seconds=1):
        """Rewind X seconds

         Args:
            seconds (int): number of seconds to rewind
        """
        if isinstance(seconds, timedelta):
            seconds = seconds.total_seconds()
        msg = self._format_msg('ovos.common_play.seek',
                               {"seconds": seconds * -1})
        self.bus.emit(msg)

    def get_track_length(self):
        """
        getting the duration of the audio in miliseconds
        """
        length = 0
        msg = self._format_msg('ovos.common_play.get_track_length')
        info = self.bus.wait_for_response(msg, timeout=1)
        if info:
            length = info.data.get("length", 0)
        return length

    def get_track_position(self):
        """
        get current position in miliseconds
        """
        pos = 0
        msg = self._format_msg('ovos.common_play.get_track_position')
        info = self.bus.wait_for_response(msg, timeout=1)
        if info:
            pos = info.data.get("position", 0)
        return pos

    def set_track_position(self, miliseconds):
        """Go to X position.

        Arguments:
           miliseconds (int): position to go to in miliseconds
        """
        msg = self._format_msg('ovos.common_play.set_track_position',
                               {"position": miliseconds})
        self.bus.emit(msg)

    def track_info(self):
        """Request information of current playing track.

        Returns:
            Dict with track info.
        """
        msg = self._format_msg('ovos.common_play.track_info')
        response = self.bus.wait_for_response(msg)
        return response.data if response else {}

    def available_backends(self):
        """Return available audio backends.

        Returns:
            dict with backend names as keys
        """
        msg = self._format_msg('ovos.common_play.list_backends')
        response = self.bus.wait_for_response(msg)
        return response.data if response else {}

    @property
    def is_playing(self):
        """True if OCP is playing, else False."""
        return self.track_info() != {}
