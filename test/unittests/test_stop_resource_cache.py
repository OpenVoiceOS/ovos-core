"""Tests for the process-local stop vocabulary cache."""

from unittest.mock import patch

from ovos_core.intent_services.stop_service import _CachedStopResources


@patch("ovos_core.intent_services.stop_service.LocaleResources.load_vocabulary")
def test_vocabulary_expansion_is_cached_per_language(load_vocabulary):
    load_vocabulary.return_value = ["stop", "cancel"]
    resources = _CachedStopResources(skill_locale="/unused")

    first = resources.load_vocabulary("stop", "en-US")
    second = resources.load_vocabulary("stop", "en-US")
    french = resources.load_vocabulary("stop", "fr-FR")

    assert first is second
    assert french == ["stop", "cancel"]
    assert load_vocabulary.call_count == 2


@patch("ovos_core.intent_services.stop_service.LocaleResources.load_vocabulary")
def test_distinct_vocabulary_names_do_not_share_entries(load_vocabulary):
    load_vocabulary.side_effect = [["stop"], ["cancel everything"]]
    resources = _CachedStopResources(skill_locale="/unused")

    assert resources.load_vocabulary("stop", "en-US") == ["stop"]
    assert resources.load_vocabulary("global_stop", "en-US") == [
        "cancel everything"
    ]
    assert load_vocabulary.call_count == 2


@patch("ovos_core.intent_services.stop_service.LocaleResources.load_vocabulary")
def test_cache_is_instance_scoped_and_clearable(load_vocabulary):
    load_vocabulary.return_value = ["stop"]
    first = _CachedStopResources(skill_locale="/unused")
    second = _CachedStopResources(skill_locale="/unused")

    first.load_vocabulary("stop", "en-US")
    first.load_vocabulary("stop", "en-US")
    second.load_vocabulary("stop", "en-US")
    assert load_vocabulary.call_count == 2

    first.clear_cache()
    first.load_vocabulary("stop", "en-US")
    assert load_vocabulary.call_count == 3
