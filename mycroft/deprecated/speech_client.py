# Copyright 2019 Mycroft AI Inc.
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

"""
NOTE: this is dead code! do not use!
This file is only present to ensure backwards compatibility
in case someone is importing from here
This is only meant for 3rd party code expecting ovos-core
to be a drop in replacement for mycroft-core
"""

from ovos_utils.log import LOG
from speech_recognition import AudioData


class RollingMean:
    """Simple rolling mean calculation optimized for speed.

    The optimization is made for cases where value retrieval is made at a
    comparative rate to the sample additions.

    Args:
        mean_samples: Number of samples to use for mean value
    """

    def __init__(self, mean_samples):
        self.num_samples = mean_samples
        self.samples = []
        self.value = None  # Leave unintialized
        self.replace_pos = 0  # Position to replace

    def append_sample(self, sample):
        """Add a sample to the buffer.

        The sample will be appended if there is room in the buffer,
        otherwise it will replace the oldest sample in the buffer.
        """
        sample = float(sample)
        current_len = len(self.samples)
        if current_len < self.num_samples:
            # build the mean
            self.samples.append(sample)
            if self.value is not None:
                avgsum = self.value * current_len + sample
                self.value = avgsum / (current_len + 1)
            else:  # If no samples are in the buffer set the sample as mean
                self.value = sample
        else:
            # Remove the contribution of the old sample
            replace_val = self.samples[self.replace_pos]
            self.value -= replace_val / self.num_samples

            # Replace it with the new sample and update the mean with it's
            # contribution
            self.value += sample / self.num_samples
            self.samples[self.replace_pos] = sample

            # Update replace position
            self.replace_pos = (self.replace_pos + 1) % self.num_samples


class WordExtractor:
    SILENCE_SECS = 0.1
    PRECISION_RATE = 0.01

    def __init__(self, audio, recognizer, metrics):
        self.audio = audio
        self.recognizer = recognizer
        self.audio_size = len(self.audio.frame_data)
        self.delta = int(self.audio_size / 2)
        self.begin = 0
        self.end = self.audio_size
        self.precision = int(self.audio_size * self.PRECISION_RATE)
        self.silence_data = self.create_silence(self.SILENCE_SECS,
                                                self.audio.sample_rate,
                                                self.audio.sample_width)
        self.metrics = metrics

    def __add(self, is_begin, value):
        if is_begin:
            self.begin += value
        else:
            self.end += value

    def __calculate_marker(self, is_begin):
        dt = self.delta
        sign = 1 if is_begin else -1

        while dt > self.precision:
            self.__add(is_begin, dt * sign)
            segment = self.audio.frame_data[self.begin:self.end]
            found = self.recognizer.is_recognized(segment, self.metrics)
            if not found:
                self.__add(is_begin, dt * -sign)
            dt = int(dt / 2)

    def calculate_range(self):
        self.__calculate_marker(False)
        self.__calculate_marker(True)

    @staticmethod
    def create_silence(seconds, sample_rate, sample_width):
        return '\0' * int(seconds * sample_rate * sample_width)

    def get_audio_data_before(self):
        byte_data = self.audio.frame_data[0:self.begin] + self.silence_data
        return AudioData(byte_data, self.audio.sample_rate,
                         self.audio.sample_width)

    def get_audio_data_after(self):
        byte_data = self.silence_data + self.audio.frame_data[self.end:
                                                              self.audio_size]
        return AudioData(byte_data, self.audio.sample_rate,
                         self.audio.sample_width)


class NoiseTracker:
    """DEPRECATED! use SilenceDetector instead, only provided for backwards compatibility imports

    Noise tracker, used to deterimine if an audio utterance is complete.

    The current implementation expects a number of loud chunks (not necessary
    in one continous sequence) followed by a short period of continous quiet
    audio data to be considered complete.

    Args:
        minimum (int): lower noise level will be threshold for "quiet" level
        maximum (int): ceiling of noise level
        sec_per_buffer (float): the length of each buffer used when updating
                                the tracker
        loud_time_limit (float): time in seconds of low noise to be considered
                                 a complete sentence
        silence_time_limit (float): time limit for silence to abort sentence
        silence_after_loud (float): time of silence to finalize the sentence.
                                    default 0.25 seconds.
    """

    def __init__(self, minimum, maximum, sec_per_buffer, loud_time_limit,
                 silence_time_limit, silence_after_loud_time=0.25):
        self.min_level = minimum
        self.max_level = maximum
        self.sec_per_buffer = sec_per_buffer

        self.num_loud_chunks = 0
        self.level = 0

        # Smallest number of loud chunks required to return loud enough
        self.min_loud_chunks = int(loud_time_limit / sec_per_buffer)

        self.max_silence_duration = silence_time_limit
        self.silence_duration = 0

        # time of quite period after long enough loud data to consider the
        # sentence complete
        self.silence_after_loud = silence_after_loud_time

        # Constants
        self.increase_multiplier = 200
        self.decrease_multiplier = 100

    def _increase_noise(self):
        """Bumps the current level.

        Modifies the noise level with a factor depending in the buffer length.
        """
        if self.level < self.max_level:
            self.level += self.increase_multiplier * self.sec_per_buffer

    def _decrease_noise(self):
        """Decrease the current level.

        Modifies the noise level with a factor depending in the buffer length.
        """
        if self.level > self.min_level:
            self.level -= self.decrease_multiplier * self.sec_per_buffer

    def update(self, is_loud):
        """Update the tracking. with either a loud chunk or a quiet chunk.

        Args:
            is_loud: True if a loud chunk should be registered
                     False if a quiet chunk should be registered
        """
        if is_loud:
            self._increase_noise()
            self.num_loud_chunks += 1
        else:
            self._decrease_noise()
        # Update duration of energy under the threshold level
        if self._quiet_enough():
            self.silence_duration += self.sec_per_buffer
        else:  # Reset silence duration
            self.silence_duration = 0

    def _loud_enough(self):
        """Check if the noise loudness criteria is fulfilled.

        The noise is considered loud enough if it's been over the threshold
        for a certain number of chunks (accumulated, not in a row).
        """
        return self.num_loud_chunks > self.min_loud_chunks

    def _quiet_enough(self):
        """Check if the noise quietness criteria is fulfilled.

        The quiet level is instant and will return True if the level is lower
        or equal to the minimum noise level.
        """
        return self.level <= self.min_level

    def recording_complete(self):
        """Has the end creteria for the recording been met.

        If the noise level has decresed from a loud level to a low level
        the user has stopped speaking.

        Alternatively if a lot of silence was recorded without detecting
        a loud enough phrase.
        """
        too_much_silence = (self.silence_duration > self.max_silence_duration)
        if too_much_silence:
            LOG.debug('Too much silence recorded without start of sentence '
                      'detected')
        return ((self._quiet_enough() and
                 self.silence_duration > self.silence_after_loud) and
                (self._loud_enough() or too_much_silence))
