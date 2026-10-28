"""Proxy plugin docker object."""

import logging

from ..const import PROXY_DOCKER_NAME
from ..coresys import CoreSysAttributes
from ..exceptions import DockerJobError
from ..jobs.const import JobConcurrency
from ..jobs.decorator import Job
from .const import (
    ENV_TIME,
    PATH_PRIVATE_DATA,
    PATH_RUN_CORE,
    PATH_RUN_PROXY,
    DockerMount,
    MountType,
)
from .interface import DockerInterface

_LOGGER: logging.Logger = logging.getLogger(__name__)


class DockerProxy(DockerInterface, CoreSysAttributes):
    """Docker Supervisor wrapper for the proxy plugin."""

    @property
    def image(self) -> str:
        """Return name of the proxy plugin image."""
        return self.sys_plugins.proxy.image

    @property
    def name(self) -> str:
        """Return name of Docker container."""
        return PROXY_DOCKER_NAME

    @property
    def mounts(self) -> list[DockerMount]:
        """Return mounts for container."""
        return [
            # Resumed config, certificates and TLS state
            DockerMount(
                type=MountType.BIND,
                source=self.sys_config.path_extern_proxy.as_posix(),
                target=PATH_PRIVATE_DATA.as_posix(),
                read_only=False,
            ),
            # The proxy listens for Core on its admin socket in here
            DockerMount(
                type=MountType.BIND,
                source=self.sys_config.path_extern_run_proxy.as_posix(),
                target=PATH_RUN_PROXY.as_posix(),
                read_only=False,
            ),
            # Core listens for the proxy in here
            DockerMount(
                type=MountType.BIND,
                source=self.sys_config.path_extern_run_core_proxy.as_posix(),
                target=PATH_RUN_CORE.as_posix(),
                read_only=True,
            ),
        ]

    @Job(
        name="docker_proxy_run",
        on_condition=DockerJobError,
        concurrency=JobConcurrency.GROUP_REJECT,
    )
    async def run(self) -> None:
        """Run Docker image."""
        await self._run(
            tag=str(self.sys_plugins.proxy.version),
            init=False,
            name=self.name,
            hostname=self.name.replace("_", "-"),
            # Owns the HTTP(S) ports on the host, like Core did
            network_mode="host",
            detach=True,
            security_opt=self.security_opt,
            environment={ENV_TIME: self.sys_timezone},
            mounts=self.mounts,
            oom_score_adj=-300,
        )
        _LOGGER.info(
            "Starting Proxy %s with version %s - Host", self.image, self.version
        )
