# Copyright 2020 Mycroft AI Inc.
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
"""Contains simple tools for performing audio related tasks such as playback
of audio, recording and listing devices.
"""
import re
from mycroft.util.log import LOG
from ovos_utils.sound import play_acknowledge_sound, play_listening_sound, \
    play_end_listening_sound, play_error_sound, record, play_audio, \
    play_ogg as _po, play_wav as _pw, play_mp3 as _pm
try:
    import pyaudio
except ImportError:
    pyaudio = None


def play_audio_file(uri: str, environment=None):
    """Play an audio file.

    This wraps the other play_* functions, choosing the correct one based on
    the file extension. The function will return directly and play the file
    in the background.

    Args:
        uri:    uri to play
        environment (dict): optional environment for the subprocess call

    Returns: subprocess.Popen object. None if the format is not supported or
             an error occurs playing the file.
    """
    return play_audio(uri, environment=environment)


def play_wav(uri, environment=None):
    """Play a wav-file.

    This will use the application specified in the mycroft config
    and play the uri passed as argument. The function will return directly
    and play the file in the background.

    Args:
        uri:    uri to play
        environment (dict): optional environment for the subprocess call

    Returns: subprocess.Popen object or None if operation failed
    """
    return _pw(uri, environment=environment)


def play_mp3(uri, environment=None):
    """Play a mp3-file.

    This will use the application specified in the mycroft config
    and play the uri passed as argument. The function will return directly
    and play the file in the background.

    Args:
        uri:    uri to play
        environment (dict): optional environment for the subprocess call

    Returns: subprocess.Popen object or None if operation failed
    """
    return _pm(uri, environment=environment)


def play_ogg(uri, environment=None):
    """Play an ogg-file.

    This will use the application specified in the mycroft config
    and play the uri passed as argument. The function will return directly
    and play the file in the background.

    Args:
        uri:    uri to play
        environment (dict): optional environment for the subprocess call

    Returns: subprocess.Popen object, or None if operation failed
    """
    return _po(uri, environment=environment)


def find_input_device(device_name):
    """Find audio input device by name.

    Args:
        device_name: device name or regex pattern to match

    Returns: device_index (int) or None if device wasn't found
    """
    if pyaudio is None:
        raise ImportError("pyaudio not installed")
    LOG.info('Searching for input device: {}'.format(device_name))
    LOG.debug('Devices: ')
    pa = pyaudio.PyAudio()
    pattern = re.compile(device_name)
    for device_index in range(pa.get_device_count()):
        dev = pa.get_device_info_by_index(device_index)
        LOG.debug('   {}'.format(dev['name']))
        if dev['maxInputChannels'] > 0 and pattern.match(dev['name']):
            LOG.debug('    ^-- matched')
            return device_index
    return None
