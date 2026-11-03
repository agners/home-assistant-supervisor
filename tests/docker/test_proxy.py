"""Test proxy plugin container."""

from unittest.mock import patch

from aiodocker.containers import DockerContainer
from awesomeversion import AwesomeVersion
import pytest

from supervisor.coresys import CoreSys
from supervisor.docker.const import DockerMount, MountType
from supervisor.docker.manager import DockerAPI


@pytest.mark.usefixtures("path_extern", "tmp_supervisor_data", "tmp_run_dir")
async def test_start(coresys: CoreSys, container: DockerContainer) -> None:
    """Test starting the proxy plugin on the host network with its sockets."""
    coresys.plugins.proxy.version = AwesomeVersion("2026.10.0")

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
    ]
