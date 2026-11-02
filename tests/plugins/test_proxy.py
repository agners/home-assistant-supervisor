"""Test proxy plugin."""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from supervisor.coresys import CoreSys
from supervisor.docker.proxy import DockerProxy
from supervisor.exceptions import (
    DockerContainerNotFoundError,
    DockerContainerNotRunningError,
    DockerError,
    DockerNotFound,
    DockerStatsTimeoutError,
    PluginError,
    ProxyDisabledError,
    ProxyError,
    ProxyNotRunningError,
    ProxyStatsTimeoutError,
    ProxyUnknownError,
)
from supervisor.homeassistant.core import HomeAssistantCore
from supervisor.plugins.base import PluginBase


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        pytest.param(
            DockerContainerNotRunningError(name="hassio_proxy"),
            ProxyNotRunningError,
            id="not_running",
        ),
        pytest.param(
            DockerContainerNotFoundError(name="hassio_proxy"),
            ProxyNotRunningError,
            id="not_found",
        ),
        pytest.param(
            DockerStatsTimeoutError(name="hassio_proxy"),
            ProxyStatsTimeoutError,
            id="timeout",
        ),
        pytest.param(DockerError("boom"), ProxyUnknownError, id="unknown"),
    ],
)
async def test_stats_errors(
    coresys: CoreSys, error: DockerError, expected: type[ProxyError]
) -> None:
    """Test stats translates Docker errors into proxy errors."""
    with (
        patch.object(DockerProxy, "stats", AsyncMock(side_effect=error)),
        pytest.raises(expected),
    ):
        await coresys.plugins.proxy.stats()


@pytest.mark.usefixtures("tmp_supervisor_data")
async def test_start_prepares_run_dirs(coresys: CoreSys, tmp_run_dir: Path) -> None:
    """Test start creates the socket folders and drops a stale admin socket."""
    stale = tmp_run_dir / "plugins" / "proxy" / "proxy.sock"
    stale.parent.mkdir(parents=True)
    stale.touch()

    with patch.object(DockerProxy, "run") as run:
        await coresys.plugins.proxy.start()

    run.assert_called_once()
    assert (tmp_run_dir / "plugins" / "proxy").is_dir()
    assert (tmp_run_dir / "core" / "plugins" / "proxy").is_dir()
    assert not stale.exists()


@pytest.mark.usefixtures("tmp_supervisor_data", "tmp_run_dir")
async def test_restart_recreates_missing_container(coresys: CoreSys) -> None:
    """Test restart starts the plugin again when its container is gone."""
    with (
        patch.object(DockerProxy, "restart", side_effect=DockerNotFound("gone")),
        patch.object(DockerProxy, "run") as run,
    ):
        await coresys.plugins.proxy.restart()

    run.assert_called_once()


@pytest.mark.parametrize("action", ["start", "restart"])
async def test_actions_rejected_when_disabled(coresys: CoreSys, action: str) -> None:
    """Test start and restart refuse to run while disabled."""
    coresys.plugins.proxy._data["enabled"] = False  # pylint: disable=protected-access

    with pytest.raises(ProxyDisabledError):
        await getattr(coresys.plugins.proxy, action)()


@pytest.mark.usefixtures("supervisor_internet")
async def test_enable_failure(coresys: CoreSys) -> None:
    """Test enable translates plugin errors into ProxyError."""
    coresys.hardware.disk.get_disk_free_space = lambda x: 5000

    with (
        patch.object(PluginBase, "enable", side_effect=PluginError("boom")),
        pytest.raises(ProxyError),
    ):
        await coresys.plugins.proxy.enable()


@pytest.mark.usefixtures("supervisor_internet")
async def test_enable_rebuilds_running_core(coresys: CoreSys) -> None:
    """Test enabling recreates a running Core so it picks up the proxy."""
    coresys.hardware.disk.get_disk_free_space = lambda x: 5000

    with (
        patch.object(PluginBase, "enable"),
        patch.object(HomeAssistantCore, "is_running", AsyncMock(return_value=True)),
        patch.object(HomeAssistantCore, "rebuild") as rebuild,
    ):
        await coresys.plugins.proxy.enable()

    rebuild.assert_called_once()


@pytest.mark.usefixtures("tmp_supervisor_data")
async def test_disable_drops_resumed_config(coresys: CoreSys) -> None:
    """Test disabling removes the resumed config and leaves a stopped Core alone."""
    autosave = coresys.plugins.proxy.autosave_file
    autosave.parent.mkdir(parents=True)
    autosave.write_text("{}")

    with (
        patch.object(PluginBase, "disable"),
        patch.object(HomeAssistantCore, "is_running", AsyncMock(return_value=False)),
        patch.object(HomeAssistantCore, "rebuild") as rebuild,
    ):
        await coresys.plugins.proxy.disable()

    assert not autosave.exists()
    rebuild.assert_not_called()


@pytest.mark.usefixtures("tmp_supervisor_data")
async def test_disable_failure(coresys: CoreSys) -> None:
    """Test disable translates plugin errors into ProxyError."""
    with (
        patch.object(PluginBase, "disable", side_effect=PluginError("boom")),
        pytest.raises(ProxyError),
    ):
        await coresys.plugins.proxy.disable()


async def test_repair_skipped_when_disabled(coresys: CoreSys) -> None:
    """Test repair does nothing while disabled."""
    coresys.plugins.proxy._data["enabled"] = False  # pylint: disable=protected-access

    with (
        patch.object(DockerProxy, "exists", return_value=False),
        patch.object(DockerProxy, "install") as install,
    ):
        await coresys.plugins.proxy.repair()

    install.assert_not_called()
