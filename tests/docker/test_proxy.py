"""Test proxy plugin container."""

from dataclasses import replace
from unittest.mock import patch

from aiodocker.containers import DockerContainer
from awesomeversion import AwesomeVersion
import pytest

from supervisor.coresys import CoreSys
from supervisor.docker.const import DockerMount, MountImageOptions, MountType
from supervisor.docker.manager import DockerAPI

FRONTEND_MOUNT = DockerMount(
    type=MountType.IMAGE,
    source="ghcr.io/home-assistant/qemux86-64-homeassistant:2026.4.0",
    target="/usr/share/hass_frontend",
    read_only=True,
    image_options=MountImageOptions(subpath="usr/share/hass_frontend"),
)
WWW_MOUNT = DockerMount(
    type=MountType.BIND,
    source="/mnt/data/supervisor/homeassistant/www",
    target="/config/www",
    read_only=True,
)


@pytest.mark.usefixtures("path_extern", "tmp_supervisor_data", "tmp_run_dir")
@pytest.mark.parametrize(
    ("docker_version", "labels", "frontend"),
    [
        pytest.param(
            "28.0.0",
            {"io.hass.frontend": "/usr/share/hass_frontend"},
            [FRONTEND_MOUNT],
            id="image_mount",
        ),
        pytest.param(
            "27.5.0",
            {"io.hass.frontend": "/usr/share/hass_frontend"},
            [],
            id="old_engine",
        ),
        pytest.param("28.0.0", {}, [], id="no_label"),
    ],
)
async def test_start(
    coresys: CoreSys,
    container: DockerContainer,
    docker_version: str,
    labels: dict[str, str],
    frontend: list[DockerMount],
) -> None:
    """Test starting the proxy plugin on the host network with its mounts."""
    coresys.plugins.proxy.version = AwesomeVersion("2026.10.0")
    coresys.homeassistant.version = AwesomeVersion("2026.4.0")
    coresys.docker._info = replace(  # pylint: disable=protected-access
        coresys.docker.info, version=AwesomeVersion(docker_version)
    )
    coresys.homeassistant.core.instance._meta = {  # pylint: disable=protected-access
        "Config": {"Labels": labels}
    }

    with patch.object(
        DockerAPI, "run", return_value=container.show.return_value
    ) as run:
        await coresys.plugins.proxy.start()

    run.assert_called_once()
    assert run.call_args.kwargs["name"] == "hassio_proxy"
    assert run.call_args.kwargs["hostname"] == "hassio-proxy"
    assert run.call_args.kwargs["network_mode"] == "host"
    assert run.call_args.kwargs["oom_score_adj"] == -300
    assert run.call_args.kwargs["mounts"] == [
        DockerMount(
            type=MountType.BIND,
            source=coresys.config.path_extern_proxy.as_posix(),
            target="/data",
            read_only=False,
        ),
        DockerMount(
            type=MountType.BIND,
            source="/run/supervisor/plugins/proxy",
            target="/run/supervisor/proxy",
            read_only=False,
        ),
        DockerMount(
            type=MountType.BIND,
            source="/run/supervisor/core/plugins/proxy",
            target="/run/supervisor/core/plugins/proxy",
            read_only=True,
        ),
        *frontend,
        WWW_MOUNT,
    ]
    assert run.call_args.kwargs["mounts"][-1].to_dict() == {
        "Type": "bind",
        "Source": "/mnt/data/supervisor/homeassistant/www",
        "Target": "/config/www",
        "ReadOnly": True,
    }
    if frontend:
        assert FRONTEND_MOUNT.to_dict()["ImageOptions"] == {
            "Subpath": "usr/share/hass_frontend"
        }
