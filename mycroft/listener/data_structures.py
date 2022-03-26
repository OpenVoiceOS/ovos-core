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
"""Data structures used by the speech client."""
from mycroft.deprecated.speech_client import RollingMean


class CyclicAudioBuffer:
    """A Cyclic audio buffer for storing binary data.

    TODO: The class is still unoptimized and performance can probably be
    enhanced.

    Args:
        size (int): size in bytes
        initial_data (bytes): initial buffer data
    """

    def __init__(self, size, initial_data):
        self.size = size
        # Get at most size bytes from the end of the initial data
        self._buffer = initial_data[-size:]

    def clear(self):
        self._buffer = b'\0' * self.size

    def append(self, data):
        """Add new data to the buffer, and slide out data if the buffer is full

        Args:
            data (bytes): binary data to append to the buffer. If buffer size
                          is exceeded the oldest data will be dropped.
        """
        buff = self._buffer + data
        if len(buff) > self.size:
            buff = buff[-self.size:]
        self._buffer = buff

    def get(self):
        """Get the binary data."""
        return self._buffer

    def get_last(self, size):
        """Get the last entries of the buffer."""
        return self._buffer[-size:]

    def __getitem__(self, key):
        return self._buffer[key]

    def __len__(self):
        return len(self._buffer)
