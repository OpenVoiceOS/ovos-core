import json
import unittest

import pytest

import ovos_config.config
import mycroft.audio.audioservice
from os.path import dirname, join
from unittest.mock import patch

import ovos_plugin_common_play
from ovos_plugin_common_play import OCPAudioBackend, OCP, PlayerState, MediaState, TrackState, PlaybackType
from mycroft.audio.interface import AudioService as MycroftAudioService
# from ovos_plugin_common_play.ocp.mycroft_cps import MycroftAudioService

from mycroft.audio.audioservice import AudioService
# from mycroft.configuration import Configuration
from mycroft.skills.intent_service import IntentService
from mycroft.skills.skill_loader import SkillLoader
from ovos_utils.messagebus import FakeBus

# Patch Configuration in the audioservice module to ensure its patched
from ovos_config.config import Configuration
mycroft.audio.audioservice.Configuration = Configuration

BASE_CONF = {"Audio":
    {
        "native_sources": ["debug_cli", "audio"],
        "default-backend": "OCP",  # only used by mycroft-core
        "preferred_audio_services": ["ovos_test", "mycroft_test"],
        "backends": {
            "OCP": {
                "type": "ovos_common_play",
                "active": True,
                "mode": "local",
                "disable_mpris": True
            },
            "mycroft_test": {
                "type": "mycroft_test",
                "active": True
            },
            "ovos_test": {
                "type": "ovos_test",
                "active": True
            }
        }
    }
}


class TestOCPLoad(unittest.TestCase):

    @classmethod
    @patch.object(ovos_config.config.Configuration, 'load_all_configs')
    def setUpClass(self, mock) -> None:
        mock.return_value = BASE_CONF
        self.bus = FakeBus()
        self.bus.emitted_msgs = []

        def get_msg(msg):
            msg = json.loads(msg)
            msg.pop("context")
            self.bus.emitted_msgs.append(msg)

        self.bus.on("message", get_msg)

        self.audio = AudioService(self.bus)

    @pytest.mark.skip
    def test_native_ocp(self):
        # assert that OCP is the selected default backend
        self.assertTrue(isinstance(self.audio.default, OCPAudioBackend))

        # assert that OCP is in "local" mode
        self.assertEqual(self.audio.default.config["mode"], "local")

        # assert that OCP is loaded
        self.assertTrue(self.audio.default.ocp is not None)
        self.assertTrue(isinstance(self.audio.default.ocp, OCP))

        # assert that test backends also loaded
        # NOTE: "service" is a list, should be named "services"
        # not renamed for backwards compat but its a typo!
        loaded_services = [s.name for s in self.audio.service]
        self.assertIn("mycroft_test", loaded_services)
        self.assertIn("ovos_test", loaded_services)

    def tearDown(self) -> None:
        self.audio.shutdown()


class TestCPS(unittest.TestCase):
    bus = FakeBus()

    @classmethod
    @patch.object(Configuration, 'load_all_configs')
    def setUpClass(cls, mock) -> None:
        mock.return_value = BASE_CONF
        cls.bus.emitted_msgs = []

        def get_msg(msg):
            msg = json.loads(msg)
            msg.pop("context")
            cls.bus.emitted_msgs.append(msg)

        cls.bus.on("message", get_msg)

    def test_auto_unload(self):
        intents = IntentService(self.bus)
        skill = SkillLoader(self.bus, f"{dirname(__file__)}/ovos_tskill_mycroft_cps")
        skill.skill_id = "skill-playback-control.mycroftai"
        skill.load()

        # assert that mycroft common play intents registered
        cps_msgs = [
            {'type': 'register_intent',
             'data': {'name': 'skill-playback-control.mycroftai:play',
                      'requires': [['skill_playback_control_mycroftaiPlay',
                                    'skill_playback_control_mycroftaiPlay'],
                                   ['skill_playback_control_mycroftaiPhrase',
                                    'skill_playback_control_mycroftaiPhrase']],
                      'at_least_one': [], 'optional': []}},
            {'type': 'register_intent',
             'data': {'name': 'skill-playback-control.mycroftai:handle_prev',
                      'requires': [['skill_playback_control_mycroftaiPrev',
                                    'skill_playback_control_mycroftaiPrev'],
                                   ['skill_playback_control_mycroftaiTrack',
                                    'skill_playback_control_mycroftaiTrack']],
                      'at_least_one': [], 'optional': []}},
            {'type': 'register_intent',
             'data': {'name': 'skill-playback-control.mycroftai:handle_pause',
                      'requires': [['skill_playback_control_mycroftaiPause',
                                    'skill_playback_control_mycroftaiPause']],
                      'at_least_one': [], 'optional': []}},
            {'type': 'register_intent',
             'data': {'name': 'skill-playback-control.mycroftai:handle_next',
                      'requires': [['skill_playback_control_mycroftaiNext',
                                    'skill_playback_control_mycroftaiNext'],
                                   ['skill_playback_control_mycroftaiTrack',
                                    'skill_playback_control_mycroftaiTrack']],
                      'at_least_one': [], 'optional': []}},
            {'type': 'register_intent',
             'data': {'name': 'skill-playback-control.mycroftai:handle_play', 'requires': [],
                      'at_least_one': [['skill_playback_control_mycroftaiPlayResume',
                                        'skill_playback_control_mycroftaiResume']], 'optional': []}}
        ]
        for intent in cps_msgs:
            self.assertIn(intent, self.bus.emitted_msgs)

        # assert that mycroft common play intents loaded
        cps_intents = [
            {'name': 'skill-playback-control.mycroftai:handle_prev',
             'requires': [('skill_playback_control_mycroftaiPrev', 'skill_playback_control_mycroftaiPrev'),
                          ('skill_playback_control_mycroftaiTrack', 'skill_playback_control_mycroftaiTrack')],
             'at_least_one': [], 'optional': []},
            {'name': 'skill-playback-control.mycroftai:handle_play', 'requires': [],
             'at_least_one': [('skill_playback_control_mycroftaiPlayResume', 'skill_playback_control_mycroftaiResume')],
             'optional': []},
            {'name': 'skill-playback-control.mycroftai:handle_pause',
             'requires': [('skill_playback_control_mycroftaiPause', 'skill_playback_control_mycroftaiPause')],
             'at_least_one': [], 'optional': []},
            {'name': 'skill-playback-control.mycroftai:play',
             'requires': [('skill_playback_control_mycroftaiPlay', 'skill_playback_control_mycroftaiPlay'),
                          ('skill_playback_control_mycroftaiPhrase', 'skill_playback_control_mycroftaiPhrase')],
             'at_least_one': [], 'optional': []},
            {'name': 'skill-playback-control.mycroftai:handle_next',
             'requires': [('skill_playback_control_mycroftaiNext', 'skill_playback_control_mycroftaiNext'),
                          ('skill_playback_control_mycroftaiTrack', 'skill_playback_control_mycroftaiTrack')],
             'at_least_one': [], 'optional': []}
        ]
        for intent in cps_intents:
            self.assertIn(intent, intents.registered_intents)

        # load ocp
        self.bus.emitted_msgs = []
        cfg = {}
        ocp = OCPAudioBackend(cfg, self.bus)

        # assert that mycroft common play was deregistered
        disable_msgs = [
            {'type': 'skillmanager.deactivate',
             'data': {'skill': 'skill-playback-control.mycroftai'}},
            {'type': 'skillmanager.deactivate',
             'data': {'skill': 'mycroft-playback-control.mycroftai'}},
            {'type': 'skillmanager.deactivate',
             'data': {'skill': 'mycroft-playback-control'}},
            {'type': 'skillmanager.deactivate',
             'data': {'skill': 'skill-playback-control'}}
        ]  # possible skill-ids for mycroft skill
        for msg in disable_msgs:
            self.assertIn(msg, self.bus.emitted_msgs)
            # skill manager would call this if connected to bus
            if msg["data"]["skill"] == skill.skill_id:
                skill.deactivate()

        # assert that OCP intents registered
        locale_folder = join(dirname(ovos_plugin_common_play.__file__),
                             "ocp", "res", "locale", "en-us")
        ocp_msgs = [
            {'type': 'padatious:register_intent',
             'data': {
                 'file_name': f'{locale_folder}/play.intent',
                 'name': 'ovos.common_play:play.intent', 'lang': 'en-us'}},
            {'type': 'padatious:register_intent',
             'data': {
                 'file_name': f'{locale_folder}/read.intent',
                 'name': 'ovos.common_play:read.intent', 'lang': 'en-us'}},
            {'type': 'padatious:register_intent',
             'data': {
                 'file_name': f'{locale_folder}/open.intent',
                 'name': 'ovos.common_play:open.intent', 'lang': 'en-us'}},
            {'type': 'padatious:register_intent',
             'data': {
                 'file_name': f'{locale_folder}/next.intent',
                 'name': 'ovos.common_play:next.intent', 'lang': 'en-us'}},
            {'type': 'padatious:register_intent',
             'data': {
                 'file_name': f'{locale_folder}/prev.intent',
                 'name': 'ovos.common_play:prev.intent', 'lang': 'en-us'}},
            {'type': 'padatious:register_intent',
             'data': {
                 'file_name': f'{locale_folder}/pause.intent',
                 'name': 'ovos.common_play:pause.intent', 'lang': 'en-us'}},
            {'type': 'padatious:register_intent',
             'data': {
                 'file_name': f'{locale_folder}/resume.intent',
                 'name': 'ovos.common_play:resume.intent', 'lang': 'en-us'}},
            {'type': 'ovos.common_play.skills.get',
             'data': {}}
        ]
        for intent in ocp_msgs:
            self.assertIn(intent, self.bus.emitted_msgs)

        # assert that mycroft common play intents unloaded
        detach_msg = {'type': 'detach_skill',
                      'data': {'skill_id': 'skill-playback-control.mycroftai:'}}
        self.assertIn(detach_msg, self.bus.emitted_msgs)
        for intent in cps_intents:
            self.assertNotIn(intent, intents.registered_intents)

        ocp.shutdown()


class TestAudioServiceApi(unittest.TestCase):
    bus = FakeBus()

    @classmethod
    @patch.object(Configuration, 'load_all_configs')
    def setUpClass(cls, mock) -> None:
        mock.return_value = BASE_CONF
        cls.bus.emitted_msgs = []

        def get_msg(msg):
            msg = json.loads(msg)
            msg.pop("context")
            cls.bus.emitted_msgs.append(msg)

        cls.bus.on("message", get_msg)

        cls.api = MycroftAudioService(cls.bus)
        cls.audio = AudioService(cls.bus)

    def test_ocp_plugin_compat_layer(self):
        self.bus.emitted_msgs = []

        # test play track from single uri
        test_uri = "file://path/to/music.mp3"
        self.api.play([test_uri])
        expected = [
            {'type': 'mycroft.audio.service.play',
             'data': {'tracks': [test_uri],
                      'utterance': '', 'repeat': False}},
            {'type': 'ovos.common_play.playlist.clear', 'data': {}},
            {'type': 'ovos.common_play.media.state', 'data': {'state': 3}},
            {'type': 'ovos.common_play.track.state', 'data': {'state': 31}},
            {'type': 'ovos.common_play.playlist.queue',
             'data': {
                 'tracks': [{'uri': test_uri,
                             'title': 'music.mp3', 'playback': 2, 'status': 1,
                             'skill_id': 'mycroft.audio_interface'}]}},
            {'type': 'ovos.common_play.play',
             'data': {
                 'repeat': False,
                 'media': {
                     'uri': test_uri,
                     'title': 'music.mp3', 'playback': 2, 'status': 1, 'skill_id': 'mycroft.audio_interface',
                     'skill': 'mycroft.audio_interface', 'position': 0, 'length': None, 'skill_icon': None,
                     'artist': None, 'is_cps': False, 'cps_data': {}},
                 'playlist': [
                     {'uri': test_uri,
                      'title': 'music.mp3', 'playback': 2, 'status': 1, 'skill_id': 'mycroft.audio_interface',
                      'skill': 'mycroft.audio_interface', 'position': 0, 'length': None, 'skill_icon': None,
                      'artist': None, 'is_cps': False, 'cps_data': {}}]}}
        ]
        for m in expected:
            self.assertIn(m, self.bus.emitted_msgs)

        # test pause
        self.bus.emitted_msgs = []
        self.api.pause()
        expected = [
            {'type': 'mycroft.audio.service.pause', 'data': {}},
            {'type': 'ovos.common_play.pause', 'data': {}}
        ]
        for m in expected:
            self.assertIn(m, self.bus.emitted_msgs)

        # test resume
        self.bus.emitted_msgs = []
        self.api.resume()
        expected = [
            {'type': 'mycroft.audio.service.resume', 'data': {}},
            {'type': 'ovos.common_play.resume', 'data': {}}
        ]
        for m in expected:
            self.assertIn(m, self.bus.emitted_msgs)

        # test next
        self.bus.emitted_msgs = []
        self.api.next()
        expected = [
            {'type': 'mycroft.audio.service.next', 'data': {}},
            {'type': 'ovos.common_play.next', 'data': {}}
        ]
        for m in expected:
            self.assertIn(m, self.bus.emitted_msgs)

        # test prev
        self.bus.emitted_msgs = []
        self.api.prev()
        expected = [
            {'type': 'mycroft.audio.service.prev', 'data': {}},
            {'type': 'ovos.common_play.previous', 'data': {}}
        ]
        for m in expected:
            self.assertIn(m, self.bus.emitted_msgs)

        # test queue
        self.bus.emitted_msgs = []
        playlist = ["file://path/to/music2.mp3", "file://path/to/music3.mp3"]
        self.api.queue(playlist)
        expected = [
            {'type': 'mycroft.audio.service.queue',
             'data': {'tracks': ['file://path/to/music2.mp3', 'file://path/to/music3.mp3']}},
            {'type': 'ovos.common_play.playlist.queue',
             'data': {'tracks': [
                 {'uri': 'file://path/to/music2.mp3', 'title': 'music2.mp3', 'playback': 2, 'status': 1,
                  'skill_id': 'mycroft.audio_interface'},
                 {'uri': 'file://path/to/music3.mp3', 'title': 'music3.mp3', 'playback': 2, 'status': 1,
                  'skill_id': 'mycroft.audio_interface'}]
             }}
        ]
        for m in expected:
            self.assertIn(m, self.bus.emitted_msgs)

        # test play playlist
        self.bus.emitted_msgs = []
        self.api.play([test_uri] + playlist)
        expected = [
            {'type': 'mycroft.audio.service.play',
             'data': {'tracks': ['file://path/to/music.mp3', 'file://path/to/music2.mp3', 'file://path/to/music3.mp3'],
                      'utterance': '',
                      'repeat': False}},
            {'type': 'ovos.common_play.playlist.queue',
             'data': {'tracks': [
                 {'uri': 'file://path/to/music.mp3', 'title': 'music.mp3', 'playback': 2, 'status': 1,
                  'skill_id': 'mycroft.audio_interface'},
                 {'uri': 'file://path/to/music2.mp3', 'title': 'music2.mp3', 'playback': 2, 'status': 1,
                  'skill_id': 'mycroft.audio_interface'},
                 {'uri': 'file://path/to/music3.mp3', 'title': 'music3.mp3', 'playback': 2, 'status': 1,
                  'skill_id': 'mycroft.audio_interface'}]}},
            {'type': 'ovos.common_play.play',
             'data': {'repeat': False,
                      'media': {'uri': 'file://path/to/music.mp3',
                                'title': 'music.mp3', 'playback': 2,
                                'status': 1,
                                'skill_id': 'mycroft.audio_interface',
                                'skill': 'mycroft.audio_interface',
                                'position': 0, 'length': None,
                                'skill_icon': None, 'artist': None,
                                'is_cps': False, 'cps_data': {}},
                      'playlist': [
                          {'uri': 'file://path/to/music.mp3', 'title': 'music.mp3',
                           'playback': 2, 'status': 1,
                           'skill_id': 'mycroft.audio_interface',
                           'skill': 'mycroft.audio_interface', 'position': 0,
                           'length': None, 'skill_icon': None, 'artist': None,
                           'is_cps': False, 'cps_data': {}},
                          {'uri': 'file://path/to/music2.mp3', 'title': 'music2.mp3',
                           'playback': 2, 'status': 1,
                           'skill_id': 'mycroft.audio_interface',
                           'skill': 'mycroft.audio_interface', 'position': 0,
                           'length': None, 'skill_icon': None, 'artist': None,
                           'is_cps': False, 'cps_data': {}},
                          {'uri': 'file://path/to/music3.mp3', 'title': 'music3.mp3',
                           'playback': 2, 'status': 1,
                           'skill_id': 'mycroft.audio_interface',
                           'skill': 'mycroft.audio_interface', 'position': 0,
                           'length': None, 'skill_icon': None, 'artist': None,
                           'is_cps': False, 'cps_data': {}}]}}
        ]
        for m in expected:
            self.assertIn(m, self.bus.emitted_msgs)

    def test_play_mycroft_backend(self):
        self.bus.emitted_msgs = []
        selected = "mycroft_test"
        tracks = ["file://path/to/music.mp3", "file://path/to/music2.mp3"]

        # assert OCP not in use
        self.assertNotEqual(self.audio.default.ocp.player.state, PlayerState.PLAYING)

        self.api.play(tracks, repeat=True, utterance=selected)

        # correct service selected
        self.assertEqual(self.audio.current.name, selected)
        self.assertTrue(self.audio.current.playing)

        # OCP is not aware of internal player state - state events not emitted by mycroft plugins
        self.assertNotEqual(self.audio.default.ocp.player.state, PlayerState.PLAYING)

        # but track state is partially accounted for
        self.assertEqual(self.audio.default.ocp.player.now_playing.uri, tracks[0])
        self.assertEqual(self.audio.default.ocp.player.now_playing.playback, PlaybackType.AUDIO_SERVICE)
        self.assertEqual(self.audio.default.ocp.player.now_playing.status, TrackState.QUEUED_AUDIOSERVICE)
        self.assertEqual(self.audio.default.ocp.player.now_playing.skill_id, "mycroft.audio_interface")

        self.audio.current._track_start_callback("track_name")
        self.assertEqual(self.audio.default.ocp.player.now_playing.status, TrackState.PLAYING_AUDIOSERVICE)

    def test_play_ocp_backend(self):
        self.bus.emitted_msgs = []

        selected = "ovos_test"
        tracks = ["file://path/to/music.mp3", "file://path/to/music2.mp3"]

        # assert OCP not in use
        self.assertNotEqual(self.audio.default.ocp.player.state, PlayerState.PLAYING)

        # NOTE: this usage is equivalent to what OCP itself
        # does internally to select audio_service, where "utterance" is also used
        self.api.play(tracks, repeat=True, utterance=selected)

        # correct service selected
        self.assertEqual(self.audio.current.name, selected)

        # ocp state events emitted
        exptected = [
            {'type': 'mycroft.audio.service.play',
             'data': {'tracks': ['file://path/to/music.mp3', 'file://path/to/music2.mp3'], 'utterance': 'ovos_test',
                      'repeat': True}},
            {'type': 'ovos.common_play.playlist.clear', 'data': {}},  # TODO - maybe this is unwanted (?)
            {'type': 'ovos.common_play.media.state', 'data': {'state': 3}},
            {'type': 'ovos.common_play.track.state', 'data': {'state': 31}},
            {'type': 'ovos.common_play.playlist.queue', 'data': {'tracks': [
                {'uri': 'file://path/to/music.mp3', 'title': 'music.mp3', 'playback': 2, 'status': 1,
                 'skill_id': 'mycroft.audio_interface'},
                {'uri': 'file://path/to/music2.mp3', 'title': 'music2.mp3', 'playback': 2, 'status': 1,
                 'skill_id': 'mycroft.audio_interface'}]}},
            {'type': 'ovos.common_play.repeat.set', 'data': {}},
            {'type': 'ovos.common_play.player.state', 'data': {'state': 1}},
            {'type': 'ovos.common_play.media.state', 'data': {'state': 3}},
            {'type': 'ovos.common_play.track.state', 'data': {'state': 21}}
        ]
        for m in exptected:
            self.assertIn(m, self.bus.emitted_msgs)

        # assert OCP is tracking state
        self.assertEqual(self.audio.default.ocp.player.state, PlayerState.PLAYING)
        self.assertEqual(self.audio.default.ocp.player.media_state, MediaState.LOADED_MEDIA)
        self.assertEqual(self.audio.default.ocp.player.now_playing.uri, tracks[0])
        self.assertEqual(self.audio.default.ocp.player.now_playing.playback, PlaybackType.AUDIO_SERVICE)
        self.assertEqual(self.audio.default.ocp.player.now_playing.status, TrackState.PLAYING_AUDIOSERVICE)

    def tearDown(self) -> None:
        self.audio.shutdown()


if __name__ == '__main__':
    unittest.main()
