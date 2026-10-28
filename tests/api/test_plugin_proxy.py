"""Test proxy plugin api."""

from unittest.mock import PropertyMock, patch

from aiohttp.test_utils import TestClient
from awesomeversion import AwesomeVersion

from supervisor.const import CoreState
from supervisor.coresys import CoreSys
from supervisor.host.const import LogFormatter
from supervisor.plugins.proxy import PluginProxy


async def test_api_proxy_logs(advanced_logs_tester) -> None:
    """Test proxy plugin logs."""
    await advanced_logs_tester("/proxy", "hassio_proxy", LogFormatter.VERBOSE)


async def test_api_proxy_info(
    api_client_with_prefix: tuple[TestClient, str], coresys: CoreSys
) -> None:
    """Test proxy info reports the enabled state."""
    api_client, prefix = api_client_with_prefix

    resp = await api_client.get(f"{prefix}/proxy/info")
    assert resp.status == 200
    result = await resp.json()
    assert result["data"]["enabled"] is True

    coresys.plugins.proxy._data["enabled"] = False  # pylint: disable=protected-access
    resp = await api_client.get(f"{prefix}/proxy/info")
    result = await resp.json()
    assert result["data"]["enabled"] is False
    assert result["data"]["update_available"] is False


async def test_api_proxy_options(
    api_client_with_prefix: tuple[TestClient, str],
) -> None:
    """Test proxy options enable and disable the plugin."""
    api_client, prefix = api_client_with_prefix

    with (
        patch.object(PluginProxy, "disable") as disable,
        patch.object(PluginProxy, "enable") as enable,
    ):
        resp = await api_client.post(f"{prefix}/proxy/options", json={"enabled": False})
        assert resp.status == 200
        disable.assert_called_once()
        enable.assert_not_called()

        disable.reset_mock()
        resp = await api_client.post(f"{prefix}/proxy/options", json={"enabled": True})
        assert resp.status == 200
        enable.assert_called_once()
        disable.assert_not_called()


async def test_api_proxy_disabled_actions(
    api_client_with_prefix: tuple[TestClient, str], coresys: CoreSys
) -> None:
    """Test restart and update are rejected while the plugin is disabled."""
    api_client, prefix = api_client_with_prefix
    await coresys.core.set_state(CoreState.RUNNING)
    coresys.plugins.proxy._data["enabled"] = False  # pylint: disable=protected-access

    resp = await api_client.post(f"{prefix}/proxy/restart")
    assert resp.status == 400
    result = await resp.json()
    assert result["message"] == "Proxy plugin is disabled"

    with patch.object(
        PluginProxy,
        "latest_version",
        new=PropertyMock(return_value=AwesomeVersion("2026.10.0")),
    ):
        resp = await api_client.post(f"{prefix}/proxy/update")
    assert resp.status == 400
