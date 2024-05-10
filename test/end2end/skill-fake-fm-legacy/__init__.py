from typing import Tuple

from mycroft.skills.common_play_skill import CommonPlaySkill, CPSMatchLevel


class FakeFMLegacySkill(CommonPlaySkill):

    def CPS_match_query_phrase(self, phrase: str) -> Tuple[str, float, dict]:
        """Respond to Common Play Service query requests.

        Args:
            phrase: utterance request to parse

        Returns:
            Tuple(Name of station, confidence, Station information)
        """
        score = 50
        if "fake" in phrase:
            score += 35

        # Translate match confidence levels to CPSMatchLevels
        if score >= 90:
            match_level = CPSMatchLevel.EXACT
        elif score >= 70:
            match_level = CPSMatchLevel.ARTIST
        elif score >= 50:
            match_level = CPSMatchLevel.CATEGORY
        else:
            return None

        cb = {"uri": f"https://fake.mp3", "foo": "bar"}
        return phrase, match_level, cb

    def CPS_start(self, phrase, data):
        """Handle request from Common Play System to start playback."""
        self.speak("legacy common play test skill selected")
        self.speak(data["uri"])
