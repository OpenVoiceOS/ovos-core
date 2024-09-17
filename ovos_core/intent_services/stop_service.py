import os
import re
from os.path import dirname
from threading import Event
from typing import Optional, List

from ovos_bus_client.message import Message
from ovos_bus_client.session import SessionManager
from ovos_config.config import Configuration
from ovos_utils import flatten_list
from ovos_utils.bracket_expansion import expand_options
from ovos_utils.log import LOG
from ovos_utils.parse import match_one

from ovos_plugin_manager.templates.pipeline import IntentMatch


class StopService:
    """Intent Service thats handles stopping skills."""

    def __init__(self, bus):
        self.bus = bus
        self._voc_cache = {}
        self.load_resource_files()

    def load_resource_files(self):
        base = f"{dirname(__file__)}/locale"
        for lang in os.listdir(base):
            lang2 = lang.split("-")[0].lower()
            self._voc_cache[lang2] = {}
            for f in os.listdir(f"{base}/{lang}"):
                with open(f"{base}/{lang}/{f}", encoding="utf-8") as fi:
                    lines = [expand_options(l) for l in fi.read().split("\n")
                             if l.strip() and not l.startswith("#")]
                    n = f.split(".", 1)[0]
                    self._voc_cache[lang2][n] = flatten_list(lines)

    @property
    def config(self):
        """
        Returns:
            stop_config (dict): config for stop handling options
        """
        return Configuration().get("skills", {}).get("stop") or {}

    def get_active_skills(self, message: Optional[Message]=None):
        """Active skill ids ordered by converse priority
        this represents the order in which stop will be called

        Returns:
            active_skills (list): ordered list of skill_ids
        """
        session = SessionManager.get(message)
        return [skill[0] for skill in session.active_skills]

    def _collect_stop_skills(self, message: Message):
        """use the messagebus api to determine which skills can stop
        This includes all skills and external applications"""

        want_stop = []
        skill_ids = []

        active_skills = self.get_active_skills(message)

        if not active_skills:
            return want_stop

        event = Event()

        def handle_ack(msg):
            nonlocal event
            skill_id = msg.data["skill_id"]

            # validate the stop pong
            if all((skill_id not in want_stop,
                    msg.data.get("can_handle", True),
                    skill_id in active_skills)):
                want_stop.append(skill_id)

            if skill_id not in skill_ids:  # track which answer we got
                skill_ids.append(skill_id)

            if all(s in skill_ids for s in active_skills):
                # all skills answered the ping!
                event.set()

        self.bus.on("skill.stop.pong", handle_ack)

        # ask skills if they can stop
        for skill_id in active_skills:
            self.bus.emit(message.forward(f"{skill_id}.stop.ping",
                                          {"skill_id": skill_id}))

        # wait for all skills to acknowledge they can stop
        event.wait(timeout=0.5)

        self.bus.remove("skill.stop.pong", handle_ack)
        return want_stop or active_skills

    def stop_skill(self, skill_id: str, message: Message):
        """Tell a skill to stop anything it's doing,
        taking into account the message Session

        Args:
            skill_id: skill to query.
            message (Message): message containing interaction info.

        Returns:
            handled (bool): True if handled otherwise False.
        """
        stop_msg = message.reply(f"{skill_id}.stop")
        result = self.bus.wait_for_response(stop_msg, f"{skill_id}.stop.response")
        if result and 'error' in result.data:
            error_msg = result.data['error']
            LOG.error(f"{skill_id}: {error_msg}")
            return False
        elif result is not None:
            return result.data.get('result', False)

    def match_stop_high(self, utterances: List[str], lang: str, message: Message) -> Optional[IntentMatch]:
        """If utterance is an exact match for "stop" , run before intent stage

        Args:
            utterances (list):  list of utterances
            lang (string):      4 letter ISO language code
            message (Message):  message to use to generate reply

        Returns:
            IntentMatch if handled otherwise None.
        """
        lang = lang.split("-")[0]
        if lang not in self._voc_cache:
            return None

        sess = SessionManager.get(message)

        # we call flatten in case someone is sending the old style list of tuples
        utterance = flatten_list(utterances)[0]

        is_stop = self.voc_match(utterance, 'stop', exact=True, lang=lang)
        is_global_stop = self.voc_match(utterance, 'global_stop', exact=True, lang=lang) or \
                         (is_stop and not len(self.get_active_skills(message)))

        conf = 1.0

        if is_global_stop:
            # emit a global stop, full stop anything OVOS is doing
            self.bus.emit(message.reply("mycroft.stop", {}))
            return IntentMatch(intent_service='Stop',
                                                         intent_type=True,
                                                         intent_data={"conf": conf},
                                                         skill_id=None,
                                                         utterance=utterance)

        if is_stop:
            # check if any skill can stop
            for skill_id in self._collect_stop_skills(message):
                if skill_id in sess.blacklisted_skills:
                    LOG.debug(f"ignoring match, skill_id '{skill_id}' blacklisted by Session '{sess.session_id}'")
                    continue

                if self.stop_skill(skill_id, message):
                    return IntentMatch(intent_service='Stop',
                                                                 intent_type=True,
                                                                 intent_data={"conf": conf},
                                                                 skill_id=skill_id,
                                                                 utterance=utterance)
        return None

    def match_stop_medium(self, utterances: List[str], lang: str, message: Message) -> Optional[IntentMatch]:
        """ if "stop" intent is in the utterance,
        but it contains additional words not in .intent files

        Args:
            utterances (list):  list of utterances
            lang (string):      4 letter ISO language code
            message (Message):  message to use to generate reply

        Returns:
            IntentMatch if handled otherwise None.
        """
        lang = lang.split("-")[0]
        if lang not in self._voc_cache:
            return None

        # we call flatten in case someone is sending the old style list of tuples
        utterance = flatten_list(utterances)[0]

        is_stop = self.voc_match(utterance, 'stop', exact=False, lang=lang)
        if not is_stop:
            is_global_stop = self.voc_match(utterance, 'global_stop', exact=False, lang=lang) or \
                             (is_stop and not len(self.get_active_skills(message)))
            if not is_global_stop:
                return None

        return self.match_stop_low(utterances, lang, message)

    def match_stop_low(self, utterances: List[str], lang: str, message: Message) -> Optional[IntentMatch]:
        """ before fallback_low , fuzzy match stop intent

        Args:
            utterances (list):  list of utterances
            lang (string):      4 letter ISO language code
            message (Message):  message to use to generate reply

        Returns:
            IntentMatch if handled otherwise None.
        """
        lang = lang.split("-")[0]
        if lang not in self._voc_cache:
            return None
        sess = SessionManager.get(message)
        # we call flatten in case someone is sending the old style list of tuples
        utterance = flatten_list(utterances)[0]

        conf = match_one(utterance, self._voc_cache[lang]['stop'])[1]
        if len(self.get_active_skills(message)) > 0:
            conf += 0.1
        conf = round(min(conf, 1.0), 3)

        if conf < self.config.get("min_conf", 0.5):
            return None

        # check if any skill can stop
        for skill_id in self._collect_stop_skills(message):
            if skill_id in sess.blacklisted_skills:
                LOG.debug(f"ignoring match, skill_id '{skill_id}' blacklisted by Session '{sess.session_id}'")
                continue

            if self.stop_skill(skill_id, message):
                return IntentMatch(intent_service='Stop',
                                                             intent_type=True,
                                                             # emit instead of intent message
                                                             intent_data={"conf": conf},
                                                             skill_id=skill_id, utterance=utterance)

        # emit a global stop, full stop anything OVOS is doing
        self.bus.emit(message.reply("mycroft.stop", {}))
        return IntentMatch(intent_service='Stop',
                                                     intent_type=True,
                                                     # emit instead of intent message {"conf": conf},
                                                     intent_data={},
                                                     skill_id=None,
                                                     utterance=utterance)

    def voc_match(self, utt: str, voc_filename: str, lang: str,
                  exact: bool = False):
        """
        Determine if the given utterance contains the vocabulary provided.

        By default the method checks if the utterance contains the given vocab
        thereby allowing the user to say things like "yes, please" and still
        match against "Yes.voc" containing only "yes". An exact match can be
        requested.

        The method first checks in the current Skill's .voc files and secondly
        in the "res/text" folder of mycroft-core. The result is cached to
        avoid hitting the disk each time the method is called.

        Args:
            utt (str): Utterance to be tested
            voc_filename (str): Name of vocabulary file (e.g. 'yes' for
                                'res/text/en-us/yes.voc')
            lang (str): Language code, defaults to self.lang
            exact (bool): Whether the vocab must exactly match the utterance

        Returns:
            bool: True if the utterance has the given vocabulary it
        """
        lang = lang.split("-")[0].lower()
        if lang not in self._voc_cache:
            return False

        _vocs = self._voc_cache[lang].get(voc_filename) or []

        if utt and _vocs:
            if exact:
                # Check for exact match
                return any(i.strip() == utt
                           for i in _vocs)
            else:
                # Check for matches against complete words
                return any([re.match(r'.*\b' + i + r'\b.*', utt)
                            for i in _vocs])
        return False
