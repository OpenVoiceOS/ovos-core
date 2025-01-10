from os.path import join, dirname

from ovos_utils.ocp import MediaType, PlaybackType
from ovos_workshop.decorators.ocp import ocp_search
from ovos_workshop.skills.common_play import OVOSCommonPlaybackSkill


class FakeFMSkill(OVOSCommonPlaybackSkill):

    def __init__(self, *args, **kwargs):
        super().__init__(supported_media = [MediaType.RADIO,
                                            MediaType.GENERIC],
                         skill_icon=join(dirname(__file__), "ui", "fakefm.png"),
                         *args, **kwargs)

    @ocp_search()
    def search_fakefm(self, phrase, media_type):
        score = 30
        if "fake" in phrase:
            score += 35
        if media_type == MediaType.RADIO:
            score += 20
        else:
            score -= 30

        for i in range(5):
            score = score + i
            yield {
                "match_confidence": score,
                "media_type": MediaType.RADIO,
                "uri": f"https://fake_{i}.mp3",
                "playback": PlaybackType.AUDIO,
                "image": f"https://fake_{i}.png",
                "bg_image": f"https://fake_{i}.png",
                "skill_icon": f"https://fakefm.png",
                "title": f"fake station {i}",
                "author": "FakeFM",
                "length": 0
            }