# backwards compat imports, do not remove before 0.1.0 / 0.2.0
from enum import IntEnum
from ovos_workshop.skills.common_query_skill import CommonQuerySkill, CQSMatchLevel, \
    TOPIC_MATCH_RELEVANCE, RELEVANCE_MULTIPLIER, WORD_COUNT_DIVISOR, MAX_ANSWER_LEN_FOR_CONFIDENCE


# DEPRECATED - remove in 0.1.0 - mk2 hardcoded hacks
CQSVisualMatchLevel = IntEnum('CQSVisualMatchLevel',
                              [e.name for e in CQSMatchLevel])


def is_CQSVisualMatchLevel(
        match_level):
    return isinstance(match_level, type(CQSVisualMatchLevel.EXACT))


VISUAL_DEVICES = ['mycroft_mark_2']


def handles_visuals(platform):
    return platform in VISUAL_DEVICES

