from __future__ import annotations

import pytest

from liblaf.cherries import profiles


def test_factory_accepts_profile_name_instance_and_class() -> None:
    instance = profiles.ProfileDebug()

    assert isinstance(profiles.factory("debug"), profiles.ProfileDebug)
    assert profiles.factory(instance) is instance
    assert isinstance(profiles.factory(profiles.ProfileDebug), profiles.ProfileDebug)


def test_factory_prefers_debug_environment_when_profile_is_omitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEBUG", "1")
    monkeypatch.setenv("PROFILE", "default")

    assert isinstance(profiles.factory(), profiles.ProfileDebug)


def test_factory_uses_profile_environment_when_debug_is_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEBUG", "0")
    monkeypatch.setenv("PROFILE", "debug")

    assert isinstance(profiles.factory(), profiles.ProfileDebug)
