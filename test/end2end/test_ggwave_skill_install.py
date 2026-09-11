# Copyright 2024 OpenVoiceOS
# Licensed under the Apache License, Version 2.0
"""End-to-end test: install a skill from *ggwave audio* through ovos-core.

Wires the real ggwave audio transformer plugin and ovos-core's ``SkillsStore``
onto a single bus, then feeds a genuine ggwave waveform carrying a ``GHS:``
(GitHub-skill) payload. The decoded payload must drive ``SkillsStore`` all the
way to a pip install request — proving the data-over-sound skill-install path
works end-to-end. ``pip_install`` and the GitHub validation call are mocked, so
nothing is fetched or installed.

Run:
    uv run pytest test/end2end/test_ggwave_skill_install.py -v
"""
import unittest
from unittest.mock import MagicMock

import ggwave
import numpy as np
from ovoscope.listener import get_mini_listener

from ovos_core.skill_installer import SkillsStore

PLUGIN_NAME = "ovos-audio-transformer-plugin-ggwave"
GGWAVE_RATE = 48000


def _ggwave_audio(payload: str, sample_rate: int = 16000) -> bytes:
    """Return *payload* as real ggwave audio in int16 PCM at *sample_rate*."""
    waveform = ggwave.encode(payload, protocolId=1, volume=20)
    f32_48k = np.frombuffer(waveform, dtype=np.float32)
    n_out = int(round(len(f32_48k) * sample_rate / GGWAVE_RATE))
    f32 = np.interp(np.linspace(0, len(f32_48k) - 1, n_out),
                    np.arange(len(f32_48k)), f32_48k).astype(np.float32)
    return (np.clip(f32, -1.0, 1.0) * 32767).astype("<i2").tobytes()


class TestGGWaveSkillInstall(unittest.TestCase):
    """A GHS: ggwave payload installs a skill via ovos-core's SkillsStore."""

    def setUp(self):
        from ovos_audio_transformer_plugin_ggwave import GGWavePlugin

        plugin = GGWavePlugin(
            config={"start_enabled": True, "sample_rate": 16000}
        )
        self.listener = get_mini_listener(
            plugin_instances={PLUGIN_NAME: plugin}
        )
        # SkillsStore listens on the SAME bus the plugin emits on
        self.store = SkillsStore(self.listener.bus, config={"allow_pip": True})
        # never touch the network or pip
        self.store.pip_install = MagicMock(return_value=True)
        self.store.validate_skill = MagicMock(return_value=True)

    def tearDown(self):
        self.store.shutdown()
        self.listener.shutdown()

    def test_ghs_audio_triggers_skill_install(self):
        audio = _ggwave_audio("GHS:OpenVoiceOS/skill-hello-world")
        msgs = self.listener.feed_audio_stream(audio, chunk_size=2048)
        types = [m.msg_type for m in msgs]

        # the plugin decoded the payload and asked the installer to install it
        installs = [m.data for m in msgs if m.msg_type == "ovos.skills.install"]
        self.assertTrue(installs, f"no install request emitted; got {types}")
        self.assertEqual(
            installs[0]["url"],
            "https://github.com/OpenVoiceOS/skill-hello-world",
        )

        # the installer ran pip exactly once for the git URL...
        self.store.pip_install.assert_called_once_with(
            ["git+https://github.com/OpenVoiceOS/skill-hello-world"]
        )
        # ...and reported success back on the bus
        self.assertIn("ovos.skills.install.complete", types)

    def test_install_blocked_when_pip_disabled(self):
        """With allow_pip off, the same audio is refused and pip never runs."""
        self.store.config = {"allow_pip": False}
        audio = _ggwave_audio("GHS:OpenVoiceOS/skill-hello-world")
        msgs = self.listener.feed_audio_stream(audio, chunk_size=2048)
        types = [m.msg_type for m in msgs]

        self.store.pip_install.assert_not_called()
        self.assertIn("ovos.skills.install.failed", types)


if __name__ == "__main__":
    unittest.main()
