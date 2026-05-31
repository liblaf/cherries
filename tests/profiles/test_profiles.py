import pytest

from liblaf.cherries import core, plugins, profiles


def test_profile_factory_honors_debug_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PROFILE", raising=False)
    monkeypatch.setenv("DEBUG", "1")

    assert isinstance(profiles.factory(), profiles.ProfileDebug)


def test_profile_factory_honors_profile_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DEBUG", raising=False)
    monkeypatch.setenv("PROFILE", "debug")

    assert isinstance(profiles.factory(), profiles.ProfileDebug)


def test_profile_factory_accepts_names_instances_and_classes() -> None:
    debug = profiles.ProfileDebug()

    assert isinstance(profiles.factory("debug"), profiles.ProfileDebug)
    assert profiles.factory(debug) is debug
    assert isinstance(profiles.factory(profiles.ProfileDebug), profiles.ProfileDebug)


def test_default_profile_registers_production_plugins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = core.Run()
    monkeypatch.setattr(core, "run", run)

    assert profiles.ProfileDefault().init() is run
    assert isinstance(run.registry["Comet"], plugins.Comet)
    assert run.registry["Comet"].disabled is False
    assert isinstance(run.registry["Git"], plugins.Git)
    assert run.registry["Git"].commit is True
    assert isinstance(run.registry["Local"], plugins.Local)
    assert isinstance(run.registry["Logging"], plugins.Logging)


def test_debug_profile_disables_remote_and_commit_side_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = core.Run()
    monkeypatch.setattr(core, "run", run)

    assert profiles.ProfileDebug().init() is run
    assert isinstance(run.registry["Comet"], plugins.Comet)
    assert run.registry["Comet"].disabled is True
    assert isinstance(run.registry["Git"], plugins.Git)
    assert run.registry["Git"].commit is False
