import os
import random
import threading
from dataclasses import dataclass
from os.path import join, dirname
from threading import Lock, RLock
from typing import List, Tuple, Optional, Union

import time
from ovos_bus_client.apis.ocp import ClassicAudioServiceInterface
from ovos_bus_client.message import Message, dig_for_message
from ovos_bus_client.session import SessionManager
from ovos_bus_client.util import wait_for_reply
from ovos_utils import classproperty
from ovos_utils.gui import is_gui_connected, is_gui_running
from ovos_utils.log import LOG
from ovos_utils.messagebus import FakeBus
from ovos_workshop.app import OVOSAbstractApplication
from padacioso import IntentContainer

from ovos_plugin_manager.ocp import available_extractors
from ovos_plugin_manager.templates.pipeline import IntentMatch

try:
    from ovos_utils.ocp import MediaType, PlaybackType, PlaybackMode, PlayerState, OCP_ID, \
        MediaEntry, Playlist, MediaState, TrackState, dict2entry, PluginStream
    from ovos_bus_client.apis.ocp import OCPInterface, OCPQuery
except ImportError:
    from ovos_workshop.backwards_compat import MediaType, PlaybackType, PlaybackMode, PlayerState, OCP_ID, \
        MediaEntry, Playlist, MediaState, TrackState, dict2entry, PluginStream
    from ovos_bus_client.apis.ocp import OCPInterface as _OIF, OCPQuery as _OQ


    class OCPInterface(_OIF):

        # needs utils 0.1.0 in ovos-bus-client
        @classmethod
        def norm_tracks(cls, tracks: list):
            """ensures a list of tracks contains only MediaEntry or Playlist items"""
            assert isinstance(tracks, list)
            # support Playlist and MediaEntry objects in tracks
            for idx, track in enumerate(tracks):
                if isinstance(track, dict):
                    tracks[idx] = MediaEntry.from_dict(track)
                if isinstance(track, list) and not isinstance(track, Playlist):
                    tracks[idx] = cls.norm_tracks(track)
                elif not isinstance(track, MediaEntry):
                    # TODO - support string uris
                    # let it fail in next assert
                    # log all bad entries before failing
                    LOG.error(f"Bad track, invalid type: {track}")
            assert all(isinstance(t, (MediaEntry, Playlist)) for t in tracks)
            return tracks


    class OCPQuery(_OQ):
        cast2audio = [
            MediaType.MUSIC,
            MediaType.PODCAST,
            MediaType.AUDIOBOOK,
            MediaType.RADIO,
            MediaType.RADIO_THEATRE,
            MediaType.VISUAL_STORY,
            MediaType.NEWS
        ]

        # needs utils 0.1.0 in ovos-bus-client
        def __init__(self, query, bus, media_type=MediaType.GENERIC, config=None):
            LOG.debug(f"Created {media_type.name} query: {query}")
            self.query = query
            self.media_type = media_type
            self.bus = bus
            self.config = config or {}
            self.reset()

        def wait(self):
            # if there is no match type defined, lets increase timeout a bit
            # since all skills need to search
            if self.media_type == MediaType.GENERIC:
                timeout = self.config.get("max_timeout", 15) + 3  # timeout bonus
            else:
                timeout = self.config.get("max_timeout", 15)
            while self.searching and time.time() - self.search_start <= timeout:
                time.sleep(0.1)
            self.searching = False
            self.remove_events()

        def reset(self):
            self.active_skills = {}
            self.active_skills_lock = Lock()
            self.query_replies = []
            self.searching = False
            self.search_start = 0
            self.query_timeouts = self.config.get("min_timeout", 5)
            if self.config.get("playback_mode") in [PlaybackMode.AUDIO_ONLY]:
                self.has_gui = False
            else:
                self.has_gui = is_gui_running() or is_gui_connected(self.bus)


@dataclass
class OCPPlayerProxy:
    """proxy object tracking the state of connected player devices (Sessions)"""
    session_id: str
    available_extractors: List[str]
    ocp_available: bool
    player_state: PlayerState = PlayerState.STOPPED
    media_state: MediaState = MediaState.UNKNOWN
    media_type: MediaType = MediaType.GENERIC


class OCPPipelineMatcher(OVOSAbstractApplication):
    intents = ["play.intent", "open.intent", "media_stop.intent",
               "next.intent", "prev.intent", "pause.intent", "play_favorites.intent",
               "resume.intent", "like_song.intent"]

    def __init__(self, bus=None, config=None):
        super().__init__(skill_id=OCP_ID, bus=bus or FakeBus(),
                         resources_dir=f"{dirname(__file__)}")

        self.ocp_api = OCPInterface(self.bus)
        self.legacy_api = ClassicAudioServiceInterface(self.bus)
        self.mycroft_cps = LegacyCommonPlay(self.bus)

        self.config = config or {}
        self.search_lock = RLock()
        self.ocp_sessions = {}  # session_id: PlaybackCapabilities

        self.intent_matchers = {}
        self.skill_aliases = {
            # "skill_id": ["names"]
        }
        self.media2skill = {
            m: [] for m in MediaType
        }
        self.entity_csvs = self.config.get("entity_csvs", [])  # user defined keyword csv files
        self.load_classifiers()

        self.register_ocp_api_events()
        self.register_ocp_intents()
        # request available Stream extractor plugins from OCP
        self.bus.emit(Message("ovos.common_play.SEI.get"))

    def load_classifiers(self):
        # warm up the featurizer so intent matches faster (lazy loaded)
        try:
            OCPFeaturizer.init_keyword_matcher()
            if self.entity_csvs:
                OCPFeaturizer.load_csv(self.entity_csvs)
                OCPFeaturizer.extract_entities("UNLEASH THE AUTOMATONS")
        except ImportError:  # ovos-classifiers is optional
            pass

        if self.config.get("experimental_binary_classifier", False):  # ocp_medium
            from ovos_classifiers.skovos.classifier import SklearnOVOSClassifier
            LOG.info("Using experimental OCP binary classifier")
            # TODO - train a single multilingual model instead of this
            b = f"{dirname(__file__)}/models"
            c = SklearnOVOSClassifier.from_file(f"{b}/binary_ocp_kw_small.clf")
            self._binary_clf = (c, OCPFeaturizer())
            # lang specific classifiers (english only for now)
            c = SklearnOVOSClassifier.from_file(f"{b}/binary_ocp_cv2_kw_medium.clf")
            self._binary_en_clf = (c, OCPFeaturizer("binary_ocp_cv2_small"))

        if self.config.get("experimental_media_classifier", False):
            from ovos_classifiers.skovos.classifier import SklearnOVOSClassifier
            LOG.info("Using experimental OCP media type classifier")
            # TODO - train a single multilingual model instead of this
            b = f"{dirname(__file__)}/models"
            c = SklearnOVOSClassifier.from_file(f"{b}/media_ocp_kw_small.clf")
            self._media_clf = (c, OCPFeaturizer())
            # lang specific classifiers (english only for now)
            c = SklearnOVOSClassifier.from_file(f"{b}/media_ocp_cv2_kw_medium.clf")
            self._media_en_clf = (c, OCPFeaturizer("media_ocp_cv2_medium"))

    def load_resource_files(self):
        intents = {}
        for lang in self.native_langs:
            intents[lang] = {}
            locale_folder = join(dirname(__file__), "locale", lang)
            for f in os.listdir(locale_folder):
                path = join(locale_folder, f)
                if f in self.intents:
                    with open(path) as intent:
                        samples = intent.read().split("\n")
                        for idx, s in enumerate(samples):
                            samples[idx] = s.replace("{{", "{").replace("}}", "}")
                        intents[lang][f] = samples
        return intents

    def register_ocp_api_events(self):
        """
        Register messagebus handlers for OCP events
        """
        self.add_event("ovos.common_play.search", self.handle_search_query)
        self.add_event("ovos.common_play.play_search", self.handle_play_search)
        self.add_event('ovos.common_play.status.response', self.handle_player_state_update)
        self.add_event('ovos.common_play.track.state', self.handle_track_state_update)

        self.add_event('ovos.common_play.register_keyword', self.handle_skill_keyword_register)
        self.add_event('ovos.common_play.deregister_keyword', self.handle_skill_keyword_deregister)
        self.add_event('ovos.common_play.announce', self.handle_skill_register)

        self.add_event("mycroft.audio.playing_track", self._handle_legacy_audio_start)
        self.add_event("mycroft.audio.queue_end", self._handle_legacy_audio_end)
        self.add_event("mycroft.audio.service.pause", self._handle_legacy_audio_pause)
        self.add_event("mycroft.audio.service.resume", self._handle_legacy_audio_resume)
        self.add_event("mycroft.audio.service.stop", self._handle_legacy_audio_stop)
        self.bus.emit(Message("ovos.common_play.status"))  # sync player state on launch

    def register_ocp_intents(self):
        intent_files = self.load_resource_files()

        for lang, intent_data in intent_files.items():
            self.intent_matchers[lang] = IntentContainer()
            for intent_name in self.intents:
                samples = intent_data.get(intent_name)
                if samples:
                    LOG.debug(f"registering OCP intent: {intent_name}")
                    self.intent_matchers[lang].add_intent(
                        intent_name.replace(".intent", ""), samples)

        self.add_event("ocp:play", self.handle_play_intent, is_intent=True)
        self.add_event("ocp:play_favorites", self.handle_play_favorites_intent, is_intent=True)
        self.add_event("ocp:open", self.handle_open_intent, is_intent=True)
        self.add_event("ocp:next", self.handle_next_intent, is_intent=True)
        self.add_event("ocp:prev", self.handle_prev_intent, is_intent=True)
        self.add_event("ocp:pause", self.handle_pause_intent, is_intent=True)
        self.add_event("ocp:resume", self.handle_resume_intent, is_intent=True)
        self.add_event("ocp:media_stop", self.handle_stop_intent, is_intent=True)
        self.add_event("ocp:search_error", self.handle_search_error_intent, is_intent=True)
        self.add_event("ocp:like_song", self.handle_like_intent, is_intent=True)
        self.add_event("ocp:legacy_cps", self.handle_legacy_cps, is_intent=True)

    def update_player_proxy(self, player: OCPPlayerProxy):
        """remember OCP session state"""
        self.ocp_sessions[player.session_id] = player

    def handle_skill_register(self, message: Message):
        """ register skill names as keywords to match their MediaType"""
        skill_id = message.data["skill_id"]
        media = message.data.get("media_types") or \
                message.data.get("media_type") or []
        has_featured_media = message.data.get("featured_tracks", False)
        thumbnail = message.data.get("thumbnail", "")
        display_name = message.data["skill_name"].replace(" Skill", "")
        aliases = message.data.get("aliases", [display_name])
        LOG.info(f"Registering OCP Keyword for {skill_id} : {aliases}")
        self.skill_aliases[skill_id] = aliases

        for idx, m in enumerate(media):
            try:
                m = self._normalize_media_enum(m)
                self.media2skill[m].append(skill_id)
                media[idx] = m
            except:
                LOG.error(f"{skill_id} reported an invalid media_type: {m}")

        if OCPFeaturizer.ocp_keywords is None:
            return
        # TODO - review below and add missing
        # set bias in classifier
        # aliases -> {type}_streaming_service bias
        if MediaType.MUSIC in media:
            OCPFeaturizer.ocp_keywords.register_entity("music_streaming_service", aliases)
        if MediaType.MOVIE in media:
            OCPFeaturizer.ocp_keywords.register_entity("movie_streaming_service", aliases)
        # if MediaType.SILENT_MOVIE in media:
        #    OCPFeaturizer.ocp_keywords.register_entity("silent_movie_streaming_service", aliases)
        # if MediaType.BLACK_WHITE_MOVIE in media:
        #    OCPFeaturizer.ocp_keywords.register_entity("bw_movie_streaming_service", aliases)
        if MediaType.SHORT_FILM in media:
            OCPFeaturizer.ocp_keywords.register_entity("shorts_streaming_service", aliases)
        if MediaType.PODCAST in media:
            OCPFeaturizer.ocp_keywords.register_entity("podcast_streaming_service", aliases)
        if MediaType.AUDIOBOOK in media:
            OCPFeaturizer.ocp_keywords.register_entity("audiobook_streaming_service", aliases)
        if MediaType.NEWS in media:
            OCPFeaturizer.ocp_keywords.register_entity("news_provider", aliases)
        if MediaType.TV in media:
            OCPFeaturizer.ocp_keywords.register_entity("tv_streaming_service", aliases)
        if MediaType.RADIO in media:
            OCPFeaturizer.ocp_keywords.register_entity("radio_streaming_service", aliases)
        if MediaType.ADULT in media:
            OCPFeaturizer.ocp_keywords.register_entity("porn_streaming_service", aliases)

    def handle_skill_keyword_register(self, message: Message):
        """ register skill provided keywords """
        if OCPFeaturizer.ocp_keywords is None:
            return
        skill_id = message.data["skill_id"]
        kw_label = message.data["label"]
        media = message.data["media_type"]
        samples = message.data.get("samples", [])
        csv_path = message.data.get("csv")

        # NB: we need to validate labels,
        # they MUST be part of the classifier training data

        if kw_label in OCPFeaturizer.labels:
            # set bias in classifier
            if csv_path:
                OCPFeaturizer.ocp_keywords.load_entities(csv_path)
            if samples:
                OCPFeaturizer.ocp_keywords.register_entity(kw_label, samples)
            OCPFeaturizer.ocp_keywords.fit()  # update

            # warm up the featurizer so intent matches faster (lazy loaded)
            OCPFeaturizer.extract_entities("UNLEASH THE AUTOMATONS")

    def handle_skill_keyword_deregister(self, message: Message):
        skill_id = message.data["skill_id"]
        kw_label = message.data["label"]
        media = message.data["media_type"]

        # unset bias in classifier
        # TODO - support for removing samples, instead of full keyword
        # we need to keep the keyword available to the classifier
        # OCPFeaturizer.ocp_keywords.deregister_entity(kw_label)

    def handle_track_state_update(self, message: Message):
        """ovos.common_play.track.state"""
        state = message.data.get("state")
        if state is None:
            raise ValueError(f"Got state update message with no state: "
                             f"{message}")
        if isinstance(state, int):
            state = TrackState(state)
        player = self.get_player(message)
        if player.player_state != PlayerState.PLAYING and \
                state in [TrackState.PLAYING_AUDIO, TrackState.PLAYING_AUDIOSERVICE,
                          TrackState.PLAYING_VIDEO, TrackState.PLAYING_WEBVIEW,
                          TrackState.PLAYING_MPRIS]:
            player = self.get_player(message)
            player.player_state = PlayerState.PLAYING
            LOG.info(f"Session: {player.session_id} OCP PlayerState: PlayerState.PLAYING")
            self.update_player_proxy(player)

    def handle_player_state_update(self, message: Message):
        """
        Handles 'ovos.common_play.status' messages with player status updates
        @param message: Message providing new "state" data
        """
        player = self.get_player(message)
        pstate: int = message.data.get("player_state")
        mstate: int = message.data.get("media_state")
        mtype: int = message.data.get("media_type")
        if pstate is not None:
            player.player_state = PlayerState(pstate)
            LOG.debug(f"Session: {player.session_id} PlayerState: {player.player_state}")
        if mstate is not None:
            player.media_state = MediaState(mstate)
            LOG.debug(f"Session: {player.session_id} MediaState: {player.media_state}")
        if mtype is not None:
            player.media_type = MediaType(pstate)
            LOG.debug(f"Session: {player.session_id} MediaType: {player.media_type}")
        self.update_player_proxy(player)

    # pipeline
    def match_high(self, utterances: List[str], lang: str, message: Message = None) -> Optional[IntentMatch]:
        """ exact matches only, handles playback control
        recommended after high confidence intents pipeline stage """
        if lang not in self.intent_matchers:
            return None

        self.bus.emit(Message("ovos.common_play.status"))  # sync

        utterance = utterances[0].lower()
        match = self.intent_matchers[lang].calc_intent(utterance)

        if match["name"] is None:
            return None
        LOG.info(f"OCP exact match: {match}")

        player = self.get_player(message)

        if match["name"] == "play":
            utterance = match["entities"].pop("query")
            return self._process_play_query(utterance, lang, match)

        if match["name"] == "like_song" and player.media_type != MediaType.MUSIC:
            LOG.debug("Ignoring like_song intent, current media is not MediaType.MUSIC")
            return None

        if match["name"] not in ["open", "play_favorites"] and player.player_state == PlayerState.STOPPED:
            LOG.info(f'Ignoring OCP intent match {match["name"]}, OCP Virtual Player is not active')
            # next / previous / pause / resume not targeted
            # at OCP if playback is not happening / paused
            if match["name"] == "resume":
                # TODO - handle resume for last_played query, eg, previous day
                return None
            else:
                return None

        return IntentMatch(intent_service="OCP_intents",
                           intent_type=f'ocp:{match["name"]}',
                           intent_data=match,
                           skill_id=OCP_ID,
                           utterance=utterance)

    def match_medium(self, utterances: List[str], lang: str, message: Message = None) -> Optional[IntentMatch]:
        """ match a utterance via classifiers,
        recommended before common_qa pipeline stage"""
        utterance = utterances[0].lower()
        # is this a OCP query ?
        is_ocp, bconf = self.is_ocp_query(utterance, lang)

        if not is_ocp:
            return None

        # classify the query media type
        media_type, confidence = self.classify_media(utterance, lang)

        # extract entities
        if OCPFeaturizer.ocp_keywords is None:
            ents = {}
        else:
            ents = OCPFeaturizer.extract_entities(utterance)

        # extract the query string
        query = self.remove_voc(utterance, "Play", lang).strip()

        return IntentMatch(intent_service="OCP_media",
                           intent_type="ocp:play",
                           intent_data={"media_type": media_type,
                                        "entities": ents,
                                        "query": query,
                                        "is_ocp_conf": bconf,
                                        "conf": confidence},
                           skill_id=OCP_ID,
                           utterance=utterance)

    def match_fallback(self, utterances: List[str], lang: str, message: Message = None) -> Optional[IntentMatch]:
        """ match an utterance via presence of known OCP keywords,
        recommended before fallback_low pipeline stage"""
        utterance = utterances[0].lower()
        if OCPFeaturizer.ocp_keywords is None:
            ents = {}
        else:
            ents = OCPFeaturizer.extract_entities(utterance)

        if not ents:
            return None

        # classify the query media type
        media_type, confidence = self.classify_media(utterance, lang)

        if confidence < 0.3:
            return None

        # extract the query string
        query = self.remove_voc(utterance, "Play", lang).strip()

        return IntentMatch(intent_service="OCP_fallback",
                           intent_type="ocp:play",
                           intent_data={"media_type": media_type,
                                        "entities": ents,
                                        "query": query,
                                        "conf": float(confidence)},
                           skill_id=OCP_ID,
                           utterance=utterance)

    def _process_play_query(self, utterance: str, lang: str, match: dict = None,
                            message: Optional[Message] = None) -> Optional[IntentMatch]:

        match = match or {}
        player = self.get_player(message)
        # if media is currently paused, empty string means "resume playback"
        if player.player_state == PlayerState.PAUSED and \
                self._should_resume(utterance, lang, message=message):
            return IntentMatch(intent_service="OCP_intents",
                               intent_type="ocp:resume",
                               intent_data=match,
                               skill_id=OCP_ID,
                               utterance=utterance)

        if not utterance:
            # user just said "play", we are missing the search query
            phrase = self.get_response("play.what", num_retries=2)
            if not phrase:
                # let the error intent handler take action
                return IntentMatch(intent_service="OCP_intents",
                                  intent_type="ocp:search_error",
                                  intent_data=match,
                                  skill_id=OCP_ID,
                                  utterance=utterance)

        sess = SessionManager.get(message)
        # if a skill was explicitly requested, search it first
        valid_skills = [
            skill_id for skill_id, samples in self.skill_aliases.items()
            if skill_id not in sess.blacklisted_skills and
               any(s.lower() in utterance for s in samples)
        ]
        if valid_skills:
            LOG.info(f"OCP specific skill names matched: {valid_skills}")

        # classify the query media type
        media_type, conf = self.classify_media(utterance, lang)

        # extract the query string
        query = self.remove_voc(utterance, "Play", lang).strip()

        if OCPFeaturizer.ocp_keywords is None:
            ents = {}
        else:
            ents = OCPFeaturizer.extract_entities(utterance)

        return IntentMatch(intent_service="OCP_intents",
                           intent_type="ocp:play",
                           intent_data={"media_type": media_type,
                                        "query": query,
                                        "entities": ents,
                                        "skills": valid_skills,
                                        "conf": match["conf"],
                                        "media_conf": float(conf),
                                        # "results": results,
                                        "lang": lang},
                           skill_id=OCP_ID,
                           utterance=utterance)

    # bus api
    def handle_search_query(self, message: Message):
        utterance = message.data["utterance"].lower()
        phrase = message.data.get("query", "") or utterance
        lang = message.data.get("lang") or message.context.get("session", {}).get("lang", "en-us")
        LOG.debug(f"Handle {message.msg_type} request: {phrase}")
        num = message.data.get("number", "")
        if num:
            phrase += " " + num

        # classify the query media type
        media_type, prob = self.classify_media(utterance, lang)
        # search common play skills
        results = self._search(phrase, media_type, lang, message=message)
        best = self.select_best(results, message)
        results = [r.as_dict if isinstance(best, (MediaEntry, Playlist)) else r
                   for r in results]
        if isinstance(best, (MediaEntry, Playlist)):
            best = best.as_dict
        self.bus.emit(message.response(data={"results": results,
                                             "best": best,
                                             "media_type_conf": float(prob)}))

    def handle_play_search(self, message: Message):
        LOG.info("searching and playing best OCP result")
        utterance = message.data["utterance"].lower()
        match = self._process_play_query(utterance, self.lang, {"conf": 1.0})
        self.bus.emit(message.forward(match.intent_type, match.intent_data))

    def handle_play_favorites_intent(self, message: Message):
        LOG.info("playing favorite tracks")
        self.bus.emit(message.forward("ovos.common_play.liked_tracks.play"))

    # intent handlers
    @staticmethod
    def _normalize_media_enum(m: Union[int, MediaType]):
        if isinstance(m, MediaType):
            return m
        # convert int to enum
        for e in MediaType:
            if e == m:
                return e
        raise ValueError(f"{m} is not a valid media type")

    def handle_play_intent(self, message: Message):

        if not len(self.skill_aliases):  # skill_id registered when skills load
            self.speak_dialog("no.media.skills")
            return

        self.speak_dialog("just.one.moment")

        lang = message.data["lang"]
        query = message.data["query"]
        media_type = message.data["media_type"]
        skills = message.data.get("skills", [])

        # search common play skills
        results = self._search(query, media_type, lang,
                               skills=skills, message=message)

        # tell OCP to play
        self.bus.emit(message.forward('ovos.common_play.reset'))
        if not results:
            self.speak_dialog("cant.play",
                              data={"phrase": query,
                                    "media_type": media_type})
        else:
            LOG.debug(f"Playing {len(results)} results for: {query}")
            best = self.select_best(results, message)
            if best is None:
                self.speak_dialog("cant.play",
                                  data={"phrase": query,
                                        "media_type": media_type})
                return
            LOG.debug(f"OCP Best match: {best}")
            results = [r for r in results if r.as_dict != best.as_dict]
            results.insert(0, best)
            self.set_context("Playing", origin=OCP_ID)

            # ovos-PHAL-plugin-mk1 will display music icon in response to play message
            player = self.get_player(message)
            if not player.ocp_available:
                self.legacy_play(results, query, message=message)
            else:
                self.ocp_api.play(results, query, source_message=message)

    def handle_open_intent(self, message: Message):
        LOG.info("Requesting OCP homescreen")
        # let ovos-media handle it
        self.bus.emit(message.forward('ovos.common_play.home'))

    def handle_like_intent(self, message: Message):
        LOG.info("Requesting OCP to like current song")
        # let ovos-media handle it
        self.bus.emit(message.forward("ovos.common_play.like"))

    def handle_stop_intent(self, message: Message):
        player = self.get_player(message)
        if not player.ocp_available:
            LOG.info("Requesting Legacy AudioService to stop")
            self.legacy_api.stop(source_message=message)
        else:
            LOG.info("Requesting OCP to stop")
            self.ocp_api.stop(source_message=message)
        player = self.get_player(message)
        player.player_state = PlayerState.STOPPED
        self.update_player_proxy(player)

    def handle_next_intent(self, message: Message):
        player = self.get_player(message)
        if not player.ocp_available:
            LOG.info("Requesting Legacy AudioService to go to next track")
            self.legacy_api.next(source_message=message)
        else:
            LOG.info("Requesting OCP to go to next track")
            self.ocp_api.next(source_message=message)

    def handle_prev_intent(self, message: Message):
        player = self.get_player(message)
        if not player.ocp_available:
            LOG.info("Requesting Legacy AudioService to go to prev track")
            self.legacy_api.prev(source_message=message)
        else:
            LOG.info("Requesting OCP to go to prev track")
            self.ocp_api.prev(source_message=message)

    def handle_pause_intent(self, message: Message):
        player = self.get_player(message)
        if not player.ocp_available:
            LOG.info("Requesting Legacy AudioService to pause")
            self.legacy_api.pause(source_message=message)
        else:
            LOG.info("Requesting OCP to go to pause")
            self.ocp_api.pause(source_message=message)
        player = self.get_player(message)
        player.player_state = PlayerState.PAUSED
        self.update_player_proxy(player)

    def handle_resume_intent(self, message: Message):
        player = self.get_player(message)
        if not player.ocp_available:
            LOG.info("Requesting Legacy AudioService to resume")
            self.legacy_api.resume(source_message=message)
        else:
            LOG.info("Requesting OCP to go to resume")
            self.ocp_api.resume(source_message=message)
        player = self.get_player(message)
        player.player_state = PlayerState.PLAYING
        self.update_player_proxy(player)

    def handle_search_error_intent(self, message: Message):
        self.bus.emit(message.forward("mycroft.audio.play_sound",
                                      {"uri": "snd/error.mp3"}))
        player = self.get_player(message)
        if not player.ocp_available:
            LOG.info("Requesting Legacy AudioService to stop")
            self.legacy_api.stop(source_message=message)
        else:
            LOG.info("Requesting OCP to stop")
            self.ocp_api.stop(source_message=message)

    # NLP
    def voc_match_media(self, query: str, lang: str) -> Tuple[MediaType, float]:
        # simplistic approach via voc_match, works anywhere
        # and it's easy to localize, but isn't very accurate
        if self.voc_match(query, "MusicKeyword", lang=lang):
            # NOTE - before movie to handle "{movie_name} soundtrack"
            return MediaType.MUSIC, 0.6
        elif self.voc_match(query, "MovieKeyword", lang=lang):
            if self.voc_match(query, "ShortKeyword", lang=lang):
                return MediaType.SHORT_FILM, 0.7
            elif self.voc_match(query, "SilentKeyword", lang=lang):
                return MediaType.SILENT_MOVIE, 0.7
            elif self.voc_match(query, "BWKeyword", lang=lang):
                return MediaType.BLACK_WHITE_MOVIE, 0.7
            return MediaType.MOVIE, 0.6
        elif self.voc_match(query, "DocumentaryKeyword", lang=lang):
            return MediaType.DOCUMENTARY, 0.6
        elif self.voc_match(query, "AudioBookKeyword", lang=lang):
            return MediaType.AUDIOBOOK, 0.6
        elif self.voc_match(query, "NewsKeyword", lang=lang):
            return MediaType.NEWS, 0.6
        elif self.voc_match(query, "AnimeKeyword", lang=lang):
            return MediaType.ANIME, 0.6
        elif self.voc_match(query, "CartoonKeyword", lang=lang):
            return MediaType.CARTOON, 0.6
        elif self.voc_match(query, "PodcastKeyword", lang=lang):
            return MediaType.PODCAST, 0.6
        elif self.voc_match(query, "TVKeyword", lang=lang):
            return MediaType.TV, 0.6
        elif self.voc_match(query, "SeriesKeyword", lang=lang):
            return MediaType.VIDEO_EPISODES, 0.6
        elif self.voc_match(query, "AudioDramaKeyword", lang=lang):
            # NOTE - before "radio" to allow "radio theatre"
            return MediaType.RADIO_THEATRE, 0.6
        elif self.voc_match(query, "RadioKeyword", lang=lang):
            return MediaType.RADIO, 0.6
        elif self.voc_match(query, "ComicBookKeyword", lang=lang):
            return MediaType.VISUAL_STORY, 0.4
        elif self.voc_match(query, "GameKeyword", lang=lang):
            return MediaType.GAME, 0.4
        elif self.voc_match(query, "ADKeyword", lang=lang):
            return MediaType.AUDIO_DESCRIPTION, 0.4
        elif self.voc_match(query, "ASMRKeyword", lang=lang):
            return MediaType.ASMR, 0.4
        elif self.voc_match(query, "AdultKeyword", lang=lang):
            if self.voc_match(query, "CartoonKeyword", lang=lang) or \
                    self.voc_match(query, "AnimeKeyword", lang=lang) or \
                    self.voc_match(query, "HentaiKeyword", lang=lang):
                return MediaType.HENTAI, 0.4
            elif self.voc_match(query, "AudioKeyword", lang=lang) or \
                    self.voc_match(query, "ASMRKeyword", lang=lang):
                return MediaType.ADULT_AUDIO, 0.4
            return MediaType.ADULT, 0.4
        elif self.voc_match(query, "HentaiKeyword", lang=lang):
            return MediaType.HENTAI, 0.4
        elif self.voc_match(query, "VideoKeyword", lang=lang):
            return MediaType.VIDEO, 0.4
        elif self.voc_match(query, "AudioKeyword", lang=lang):
            return MediaType.AUDIO, 0.4
        return MediaType.GENERIC, 0.0

    def classify_media(self, query: str, lang: str) -> Tuple[MediaType, float]:
        """ determine what media type is being requested """
        # using a trained classifier (Experimental)
        if self.config.get("experimental_media_classifier", False):
            from ovos_classifiers.skovos.classifier import SklearnOVOSClassifier
            try:
                if lang.startswith("en"):
                    clf: SklearnOVOSClassifier = self._media_en_clf[0]
                    featurizer: OCPFeaturizer = self._media_en_clf[1]
                else:
                    clf: SklearnOVOSClassifier = self._media_clf[0]
                    featurizer: OCPFeaturizer = self._media_clf[1]
                X = featurizer.transform([query])
                preds = clf.predict_labels(X)[0]
                label = max(preds, key=preds.get)
                prob = float(round(preds[label], 3))
                LOG.info(f"OVOSCommonPlay MediaType prediction: {label} confidence: {prob}")
                LOG.debug(f"     utterance: {query}")
                if prob < self.config.get("classifier_threshold", 0.4):
                    LOG.info("ignoring MediaType classifier, low confidence prediction")
                    return MediaType.GENERIC, prob
                else:
                    return OCPFeaturizer.label2media(label), prob
            except:
                LOG.exception(f"OCP classifier exception: {query}")
        return self.voc_match_media(query, lang)

    def is_ocp_query(self, query: str, lang: str) -> Tuple[bool, float]:
        """ determine if a playback question is being asked"""
        if self.config.get("experimental_binary_classifier", False):
            from ovos_classifiers.skovos.classifier import SklearnOVOSClassifier
            try:
                # TODO - train a single multilingual classifier
                if lang.startswith("en"):
                    clf: SklearnOVOSClassifier = self._binary_en_clf[0]
                    featurizer: OCPFeaturizer = self._binary_en_clf[1]
                else:
                    clf: SklearnOVOSClassifier = self._binary_clf[0]
                    featurizer: OCPFeaturizer = self._binary_clf[1]

                X = featurizer.transform([query])
                preds = clf.predict_labels(X)[0]
                label = max(preds, key=preds.get)
                prob = round(preds[label], 3)
                LOG.info(f"OVOSCommonPlay prediction: {label} confidence: {prob}")
                LOG.debug(f"     utterance: {query}")
                return label == "OCP", float(prob)
            except:
                LOG.exception("OCP binary classifier failure")
        m, p = self.voc_match_media(query, lang)
        return m != MediaType.GENERIC, p

    def _should_resume(self, phrase: str, lang: str, message: Optional[Message] = None) -> bool:
        """
        Check if a "play" request should resume playback or be handled as a new
        session.
        @param phrase: Extracted playback phrase
        @return: True if player should resume, False if this is a new request
        """
        player = self.get_player(message)
        if player.player_state == PlayerState.PAUSED:
            if not phrase.strip() or \
                    self.voc_match(phrase, "Resume", lang=lang, exact=True) or \
                    self.voc_match(phrase, "Play", lang=lang, exact=True):
                return True
        return False

    # search
    def get_player(self, message: Optional[Message] = None, timeout=1) -> OCPPlayerProxy:
        """get a PlayerProxy object, containing info such as player state and the available stream extractors from OCP
        this is tracked per Session, if needed requests the info from the client"""
        sess = SessionManager.get(message)
        if sess.session_id not in self.ocp_sessions:
            player = OCPPlayerProxy(available_extractors=available_extractors(),
                                    ocp_available=False,
                                    session_id=sess.session_id)
            if not self.config.get("legacy"):  # force legacy audio in config
                ev = threading.Event()

                def handle_m(m):
                    s = SessionManager.get(m)
                    if s.session_id == player.session_id:
                        player.available_extractors = m.data["SEI"]
                        player.ocp_available = True
                        ev.set()
                        LOG.info(f"Session: {player.session_id} Available stream extractor plugins: {m.data['SEI']}")

                self.bus.on("ovos.common_play.SEI.get.response", handle_m)
                message = message or dig_for_message() or Message("")  # get message.context to forward
                self.bus.emit(message.forward("ovos.common_play.SEI.get"))
                ev.wait(timeout)
                self.bus.remove("ovos.common_play.SEI.get.response", handle_m)
            self.update_player_proxy(player)

        return self.ocp_sessions[sess.session_id]

    def normalize_results(self, results: list) -> List[Union[MediaEntry, Playlist, PluginStream]]:
        # support Playlist and MediaEntry objects in tracks
        for idx, track in enumerate(results):
            if isinstance(track, dict):
                try:
                    results[idx] = dict2entry(track)
                except Exception as e:
                    LOG.error(f"got an invalid track: {track}")
                    results[idx] = None
        return [r for r in results if r]

    def filter_results(self, results: list, phrase: str, lang: str,
                       media_type: MediaType = MediaType.GENERIC,
                       message: Optional[Message] = None) -> list:
        # ignore very low score matches
        l1 = len(results)
        results = [r for r in results
                   if r.match_confidence >= self.config.get("min_score", 50)]
        LOG.debug(f"filtered {l1 - len(results)} low confidence results")

        # filter based on MediaType
        if self.config.get("filter_media", True) and media_type != MediaType.GENERIC:
            l1 = len(results)
            # TODO - also check inside playlists
            results = [r for r in results
                       if isinstance(r, Playlist) or r.media_type == media_type]
            LOG.debug(f"filtered {l1 - len(results)} wrong MediaType results")

        # filter based on available stream extractors
        player = self.get_player(message)
        valid_starts = ["/", "http://", "https://", "file://"] + \
                       [f"{sei}//" for sei in player.available_extractors]
        if self.config.get("filter_SEI", True):
            # TODO - also check inside playlists
            bad_seis = [r for r in results if isinstance(r, MediaEntry) and
                        not any(r.uri.startswith(sei) for sei in valid_starts)]

            results = [r for r in results if r not in bad_seis]
            plugs = set([s.uri.split('//')[0] for s in bad_seis if '//' in s.uri])
            if bad_seis:
                LOG.debug(f"filtered {len(bad_seis)} results that require "
                          f"unavailable plugins: {plugs}")

        # filter by media type
        audio_only = self.voc_match(phrase, "audio_only", lang=lang)
        video_only = self.voc_match(phrase, "video_only", lang=lang)
        if self.config.get("playback_mode") == PlaybackMode.VIDEO_ONLY:
            # select only from VIDEO results if preference is set
            audio_only = True
        elif self.config.get("playback_mode") == PlaybackMode.AUDIO_ONLY:
            # select only from AUDIO results if preference is set
            video_only = True

        # check if user said "play XXX audio only"
        if audio_only or not player.ocp_available:
            l1 = len(results)
            # TODO - also check inside playlists
            results = [r for r in results
                       if (isinstance(r, Playlist) and player.ocp_available)
                       or r.playback == PlaybackType.AUDIO]
            LOG.debug(f"filtered {l1 - len(results)} non-audio results")

        # check if user said "play XXX video only"
        elif video_only:
            l1 = len(results)
            results = [r for r in results
                       if isinstance(r, Playlist) or r.playback == PlaybackType.VIDEO]
            LOG.debug(f"filtered {l1 - len(results)} non-video results")

        return results

    def _search(self, phrase: str, media_type: MediaType, lang: str,
                skills: Optional[List[str]] = None,
                message: Optional[Message] = None) -> list:
        self.bus.emit(message.reply("ovos.common_play.search.start"))
        self.enclosure.mouth_think()  # animate mk1 mouth during search

        # Now we place a query on the messsagebus for anyone who wants to
        # attempt to service a 'play.request' message.
        results = []
        for r in self._execute_query(phrase,
                                     media_type=media_type,
                                     skills=skills,
                                     message=message):
            results += r["results"]

        results = self.normalize_results(results)

        if not skills:
            LOG.debug(f"Got {len(results)} results")
            results = self.filter_results(results, phrase, lang, media_type,
                                          message=message)
            LOG.debug(f"Got {len(results)} usable results")
        else:  # no filtering if skill explicitly requested
            LOG.debug(f"Got {len(results)} usable results from {skills}")

        self.bus.emit(message.reply("ovos.common_play.search.end"))
        return results

    def _execute_query(self, phrase: str,
                       media_type: MediaType = Union[int, MediaType],
                       skills: Optional[List[str]] = None,
                       message: Optional[Message] = None) -> list:
        """ actually send the search to OCP skills"""
        media_type = self._normalize_media_enum(media_type)

        with self.search_lock:
            # stop any search still happening
            self.bus.emit(message.reply("ovos.common_play.search.stop"))

            query = OCPQuery(query=phrase, media_type=media_type,
                             config=self.config, bus=self.bus)
            # search individual skills first if user specifically asked for it
            results = []
            if skills:
                for skill_id in skills:
                    if skill_id not in self.media2skill[media_type]:
                        LOG.debug(f"{skill_id} can't handle {media_type} queries")
                        continue
                    LOG.debug(f"Searching OCP Skill: {skill_id}")
                    query.send(skill_id, source_message=message)
                    query.wait()
                    results += query.results

            if not len(self.media2skill[media_type]):
                LOG.info(f"No skills available to handle {media_type} queries, "
                         f"forcing MediaType.GENERIC")
                media_type = MediaType.GENERIC

            # search all skills
            if not results:
                if skills:
                    LOG.info(f"No specific skill results from {skills}, "
                             f"performing global OCP search")
                query.reset()
                query.send()
                query.wait()
                results = query.results

            # fallback to generic search type
            if not results and \
                    self.config.get("search_fallback", True) and \
                    media_type != MediaType.GENERIC:
                LOG.debug("OVOSCommonPlay falling back to MediaType.GENERIC")
                query.media_type = MediaType.GENERIC
                query.reset()
                query.send()
                query.wait()
                results = query.results

        LOG.debug(f'Returning {len(results)} search results')
        return results

    def select_best(self, results: list, message: Message) -> Union[MediaEntry, Playlist, PluginStream]:

        sess = SessionManager.get(message)

        # Look at any replies that arrived before the timeout
        # Find response(s) with the highest confidence
        best = None
        ties = []

        for res in results:
            if isinstance(res, dict):
                res = dict2entry(res)
            if res.skill_id in sess.blacklisted_skills:
                LOG.debug(f"ignoring match, skill_id '{res.skill_id}' blacklisted by Session '{sess.session_id}'")
                continue
            if not best or res.match_confidence > best.match_confidence:
                best = res
                ties = [best]
            elif res.match_confidence == best.match_confidence:
                ties.append(res)

        if ties:
            # select randomly
            selected = random.choice(ties)
            # TODO: Ask user to pick between ties or do it automagically
        else:
            selected = best
        if selected:
            LOG.info(f"OVOSCommonPlay selected: {selected.skill_id} - {selected.match_confidence}")
            LOG.debug(str(selected))
        else:
            LOG.error("No valid OCP matches")
        return selected

    ##################
    # Legacy Audio subsystem API
    def legacy_play(self, results: List[Union[MediaEntry, Playlist, PluginStream]], phrase="",
                    message: Optional[Message] = None):
        res = []
        for r in results:
            if not (r.playback == PlaybackType.AUDIO or r.media_type in OCPQuery.cast2audio):
                # we need to filter video results
                continue
            if isinstance(r, Playlist):
                # get internal entries from the playlist
                for e in r.entries:
                    res.append(e.uri)
            elif isinstance(r, MediaEntry):
                res.append(r.uri)
            elif isinstance(r, PluginStream):
                # for legacy audio service we need to do stream extraction here
                res.append(r.extract_uri(video=False))

        self.legacy_api.play(res, utterance=phrase, source_message=message)

        player = self.get_player(message)
        player.player_state = PlayerState.PLAYING
        player.media_state = MediaState.LOADING_MEDIA
        self.update_player_proxy(player)

    def _handle_legacy_audio_stop(self, message: Message):
        player = self.get_player(message)
        if not player.ocp_available:
            player.player_state = PlayerState.STOPPED
            player.media_state = MediaState.NO_MEDIA
            self.update_player_proxy(player)

    def _handle_legacy_audio_pause(self, message: Message):
        player = self.get_player(message)
        if not player.ocp_available and player.player_state == PlayerState.PLAYING:
            player.player_state = PlayerState.PAUSED
            player.media_state = MediaState.LOADED_MEDIA
            self.update_player_proxy(player)

    def _handle_legacy_audio_resume(self, message: Message):
        player = self.get_player(message)
        if not player.ocp_available and player.player_state == PlayerState.PAUSED:
            player.player_state = PlayerState.PLAYING
            player.media_state = MediaState.LOADED_MEDIA
            self.update_player_proxy(player)

    def _handle_legacy_audio_start(self, message: Message):
        player = self.get_player(message)
        if not player.ocp_available:
            player.player_state = PlayerState.PLAYING
            player.media_state = MediaState.LOADED_MEDIA
            self.update_player_proxy(player)

    def _handle_legacy_audio_end(self, message: Message):
        player = self.get_player(message)
        if not player.ocp_available:
            player.player_state = PlayerState.STOPPED
            player.media_state = MediaState.END_OF_MEDIA
            self.update_player_proxy(player)

    ############
    # Legacy Mycroft CommonPlay skills

    def match_legacy(self, utterances: List[str], lang: str, message: Message = None) -> Optional[IntentMatch]:
        """ match legacy mycroft common play skills  (must import from deprecated mycroft module)
        not recommended, legacy support only

        legacy base class at mycroft/skills/common_play_skill.py marked for removal in ovos-core 0.1.0
        """
        if not self.config.get("legacy_cps", True):
            # needs to be explicitly enabled in pipeline config
            return None

        utterance = utterances[0].lower()

        match = self.intent_matchers[lang].calc_intent(utterance)

        if match["name"] is None:
            return None
        if match["name"] == "play":
            LOG.info(f"Legacy Mycroft CommonPlay match: {match}")
            utterance = match["entities"].pop("query")
            return IntentMatch(intent_service="OCP_media",
                               intent_type="ocp:legacy_cps",
                               intent_data={"query": utterance,
                                            "conf": 0.7},
                               skill_id=OCP_ID,
                               utterance=utterance)

    def handle_legacy_cps(self, message: Message):
        """intent handler for legacy CPS matches"""
        utt = message.data["query"]
        res = self.mycroft_cps.search(utt)
        if res:
            best = self.select_best([r[0] for r in res], message)
            if best:
                callback = [r[1] for r in res if r[0].uri == best.uri][0]
                self.mycroft_cps.skill_play(skill_id=best.skill_id,
                                            callback_data=callback,
                                            phrase=utt,
                                            message=message)
                return
        self.bus.emit(message.forward("mycroft.audio.play_sound",
                                      {"uri": "snd/error.mp3"}))

    def shutdown(self):
        self.mycroft_cps.shutdown()
        self.default_shutdown()  # remove events registered via self.add_event


class LegacyCommonPlay:
    """ interface for mycroft common play
    1 - emit 'play:query'
    2 - gather 'play:query.response' from legacy skills
    3 - emit 'play:start' for selected skill

    legacy base class at mycroft/skills/common_play_skill.py
    marked for removal in ovos-core 0.1.0
    """

    def __init__(self, bus):
        self.bus = bus
        self.query_replies = {}
        self.query_extensions = {}
        self.waiting = False
        self.start_ts = 0
        self.bus.on("play:query.response", self.handle_cps_response)

    def skill_play(self, skill_id: str, callback_data: dict,
                   phrase: Optional[str] = "",
                   message: Optional[Message] = None):
        """tell legacy CommonPlaySkills they were selected and should handle playback"""
        message = message or Message("ocp:legacy_cps")
        self.bus.emit(message.forward(
            'play:start',
            {"skill_id": skill_id,
             "phrase": phrase,
             "callback_data": callback_data}
        ))

    def shutdown(self):
        self.bus.remove("play:query.response", self.handle_cps_response)

    @property
    def cps_status(self):
        return wait_for_reply('play:status.query',
                              reply_type="play:status.response",
                              bus=self.bus).data

    def handle_cps_response(self, message):
        """receive matches from legacy skills"""
        search_phrase = message.data["phrase"]

        if ("searching" in message.data and
                search_phrase in self.query_extensions):
            # Manage requests for time to complete searches
            skill_id = message.data["skill_id"]
            if message.data["searching"]:
                # extend the timeout by N seconds
                # IGNORED HERE, used in mycroft-playback-control skill
                if skill_id not in self.query_extensions[search_phrase]:
                    self.query_extensions[search_phrase].append(skill_id)
            else:
                # Search complete, don't wait on this skill any longer
                if skill_id in self.query_extensions[search_phrase]:
                    self.query_extensions[search_phrase].remove(skill_id)

        elif search_phrase in self.query_replies:
            # Collect all replies until the timeout
            self.query_replies[message.data["phrase"]].append(message.data)

    def send_query(self, phrase):
        self.query_replies[phrase] = []
        self.query_extensions[phrase] = []
        self.bus.emit(Message('play:query',
                              {"phrase": phrase}))

    def get_results(self, phrase):
        if self.query_replies.get(phrase):
            return [self.cps2media(r) for r in self.query_replies[phrase]]
        return []

    def search(self, phrase, timeout=5):
        self.send_query(phrase)
        self.waiting = True
        start_ts = time.time()
        while self.waiting and time.time() - start_ts <= timeout:
            time.sleep(0.2)
        self.waiting = False
        return self.get_results(phrase)

    @staticmethod
    def cps2media(res: dict, media_type=MediaType.GENERIC) -> Tuple[MediaEntry, dict]:
        """convert a cps result into a modern result"""
        entry = MediaEntry(title=res["phrase"],
                           artist=res["skill_id"],
                           uri=f"callback:{res['skill_id']}",
                           media_type=media_type,
                           playback=PlaybackType.SKILL,
                           match_confidence=res["conf"] * 100,
                           skill_id=res["skill_id"])
        return entry, res['callback_data']


class OCPFeaturizer:
    """used by the experimental media type classifier,
    API should be considered unstable"""
    ocp_keywords = None
    # defined at training time
    _clf_labels = ['ad_keyword', 'album_name', 'anime_genre', 'anime_name', 'anime_streaming_service',
                   'artist_name', 'asmr_keyword', 'asmr_trigger', 'audio_genre', 'audiobook_narrator',
                   'audiobook_streaming_service', 'book_author', 'book_genre', 'book_name',
                   'bw_movie_name', 'cartoon_genre', 'cartoon_name', 'cartoon_streaming_service',
                   'comic_name', 'comic_streaming_service', 'comics_genre', 'country_name',
                   'documentary_genre', 'documentary_name', 'documentary_streaming_service',
                   'film_genre', 'film_studio', 'game_genre', 'game_name', 'gaming_console_name',
                   'generic_streaming_service', 'hentai_name', 'hentai_streaming_service',
                   'media_type_adult', 'media_type_adult_audio', 'media_type_anime', 'media_type_audio',
                   'media_type_audiobook', 'media_type_bts', 'media_type_bw_movie', 'media_type_cartoon',
                   'media_type_documentary', 'media_type_game', 'media_type_hentai', 'media_type_movie',
                   'media_type_music', 'media_type_news', 'media_type_podcast', 'media_type_radio',
                   'media_type_radio_theatre', 'media_type_short_film', 'media_type_silent_movie',
                   'media_type_sound', 'media_type_trailer', 'media_type_tv', 'media_type_video',
                   'media_type_video_episodes', 'media_type_visual_story', 'movie_actor',
                   'movie_director', 'movie_name', 'movie_streaming_service', 'music_genre',
                   'music_streaming_service', 'news_provider', 'news_streaming_service',
                   'play_verb_audio', 'play_verb_video', 'playback_device', 'playlist_name',
                   'podcast_genre', 'podcast_name', 'podcast_streaming_service', 'podcaster',
                   'porn_film_name', 'porn_genre', 'porn_streaming_service', 'pornstar_name',
                   'radio_drama_actor', 'radio_drama_genre', 'radio_drama_name', 'radio_program',
                   'radio_program_name', 'radio_streaming_service', 'radio_theatre_company',
                   'radio_theatre_streaming_service', 'record_label', 'series_name',
                   'short_film_name', 'shorts_streaming_service', 'silent_movie_name',
                   'song_name', 'sound_name', 'soundtrack_keyword', 'tv_channel', 'tv_genre',
                   'tv_streaming_service', 'video_genre', 'video_streaming_service', 'youtube_channel']

    def __init__(self, base_clf=None):
        self.clf_feats = None
        from ovos_classifiers.skovos.classifier import SklearnOVOSClassifier
        from ovos_classifiers.skovos.features import ClassifierProbaVectorizer
        self.init_keyword_matcher()
        if base_clf:
            if isinstance(base_clf, str):
                clf_path = f"{dirname(__file__)}/models/{base_clf}.clf"
                assert os.path.isfile(clf_path)
                base_clf = SklearnOVOSClassifier.from_file(clf_path)
            self.clf_feats = ClassifierProbaVectorizer(base_clf)
        for l in self._clf_labels:  # no samples, just to ensure featurizer has right number of feats
            self.ocp_keywords.register_entity(l, [])

    @classmethod
    def init_keyword_matcher(cls):
        from ovos_classifiers.skovos.features import KeywordFeaturesVectorizer
        if OCPFeaturizer.ocp_keywords is None:
            # ignore_list accounts for "noise" keywords in the csv file
            OCPFeaturizer.ocp_keywords = KeywordFeaturesVectorizer(ignore_list=["play", "stop"])

    @classmethod
    def load_csv(cls, entity_csvs: list):
        for csv in entity_csvs or []:
            if not os.path.isfile(csv):
                # check for bundled files
                if os.path.isfile(f"{dirname(__file__)}/models/{csv}"):
                    csv = f"{dirname(__file__)}/models/{csv}"
                else:
                    LOG.error(f"Requested OCP entities file does not exist? {csv}")
                    continue
            OCPFeaturizer.ocp_keywords.load_entities(csv)
            LOG.info(f"Loaded OCP keywords: {csv}")

    @classproperty
    def labels(cls):
        """
        in V0 classifier using synth dataset - this is tied to the classifier model"""
        return cls._clf_labels

    @staticmethod
    def label2media(label: str) -> MediaType:
        if isinstance(label, MediaType):
            return label
        if label == "ad":
            mt = MediaType.AUDIO_DESCRIPTION
        elif label == "adult":
            mt = MediaType.ADULT
        elif label == "adult_asmr":
            mt = MediaType.ADULT_AUDIO
        elif label == "anime":
            mt = MediaType.ANIME
        elif label == "audio":
            mt = MediaType.AUDIO
        elif label == "asmr":
            mt = MediaType.ASMR
        elif label == "audiobook":
            mt = MediaType.AUDIOBOOK
        elif label == "bts":
            mt = MediaType.BEHIND_THE_SCENES
        elif label == "bw_movie":
            mt = MediaType.BLACK_WHITE_MOVIE
        elif label == "cartoon":
            mt = MediaType.CARTOON
        elif label == "comic":
            mt = MediaType.VISUAL_STORY
        elif label == "documentary":
            mt = MediaType.DOCUMENTARY
        elif label == "game":
            mt = MediaType.GAME
        elif label == "hentai":
            mt = MediaType.HENTAI
        elif label == "movie":
            mt = MediaType.MOVIE
        elif label == "music":
            mt = MediaType.MUSIC
        elif label == "news":
            mt = MediaType.NEWS
        elif label == "podcast":
            mt = MediaType.PODCAST
        elif label == "radio":
            mt = MediaType.RADIO
        elif label == "radio_drama":
            mt = MediaType.RADIO_THEATRE
        elif label == "series":
            mt = MediaType.VIDEO_EPISODES
        elif label == "short_film":
            mt = MediaType.SHORT_FILM
        elif label == "silent_movie":
            mt = MediaType.SILENT_MOVIE
        elif label == "trailer":
            mt = MediaType.TRAILER
        elif label == "tv_channel":
            mt = MediaType.TV
        elif label == "video":
            mt = MediaType.VIDEO
        else:
            LOG.error(f"bad label {label}")
            mt = MediaType.GENERIC
        return mt

    def transform(self, X):
        if self.clf_feats:
            from sklearn.pipeline import FeatureUnion
            vec = FeatureUnion([
                ("kw", self.ocp_keywords),
                ("clf", self.clf_feats)
            ])
            return vec.transform(X)
        return self.ocp_keywords.transform(X)

    @classmethod
    def extract_entities(cls, utterance) -> dict:
        return cls.ocp_keywords._transformer.wordlist.extract(utterance)
