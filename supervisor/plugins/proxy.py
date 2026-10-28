"""Home Assistant proxy plugin.

Code: https://github.com/home-assistant/plugin-proxy
"""

import logging
from pathlib import Path

from awesomeversion import AwesomeVersion

from ..const import SOCKET_NAME_PROXY
from ..coresys import CoreSys
from ..docker.const import ContainerState
from ..docker.proxy import DockerProxy
from ..docker.stats import DockerStats
from ..exceptions import (
    DockerContainerNotFoundError,
    DockerContainerNotRunningError,
    DockerError,
    DockerStatsTimeoutError,
    HomeAssistantError,
    PluginDisabledError,
    PluginError,
    ProxyDisabledError,
    ProxyError,
    ProxyJobError,
    ProxyNotRunningError,
    ProxyStatsTimeoutError,
    ProxyUnknownError,
    ProxyUpdateError,
)
from ..jobs.const import JobThrottle
from ..jobs.decorator import Job
from ..utils.sentry import async_capture_exception
from ..utils.sockets import remove_socket_files
from .base import PluginBase
from .const import (
    FILE_HASSIO_PROXY,
    PLUGIN_UPDATE_CONDITIONS,
    WATCHDOG_THROTTLE_MAX_CALLS,
    WATCHDOG_THROTTLE_PERIOD,
)
from .validate import SCHEMA_PROXY_CONFIG

_LOGGER: logging.Logger = logging.getLogger(__name__)

# Caddy resumes the last config Core pushed from this file
AUTOSAVE_FILE = Path("caddy", "autosave.json")


class PluginProxy(PluginBase):
    """Reverse proxy fronting Home Assistant Core.

    Supervisor manages the container; Core configures the proxy directly over
    its admin socket.
    """

    def __init__(self, coresys: CoreSys):
        """Initialize proxy plugin."""
        super().__init__(FILE_HASSIO_PROXY, SCHEMA_PROXY_CONFIG)
        self.slug = "proxy"
        self.coresys: CoreSys = coresys
        self.instance: DockerProxy = DockerProxy(coresys)

    @property
    def default_image(self) -> str:
        """Return default image for proxy plugin."""
        if self.sys_updater.image_proxy:
            return self.sys_updater.image_proxy
        return super().default_image

    @property
    def latest_version(self) -> AwesomeVersion | None:
        """Return latest version of the proxy plugin."""
        return self.sys_updater.version_proxy

    @property
    def autosave_file(self) -> Path:
        """Return the resumed config file of the proxy."""
        return self.sys_config.path_proxy / AUTOSAVE_FILE

    def ensure_run_dirs(self) -> None:
        """Create the folders the proxy's socket mounts need.

        Must be run in executor.
        """
        self.sys_config.path_proxy.mkdir(parents=True, exist_ok=True)
        self.sys_config.path_run_proxy.mkdir(parents=True, exist_ok=True)
        self.sys_config.path_run_core_proxy.mkdir(parents=True, exist_ok=True)

    def _prepare_start(self) -> None:
        """Prepare folders and remove a stale admin socket before a start.

        Must be run in executor.
        """
        self.ensure_run_dirs()
        remove_socket_files(self.sys_config.path_run_proxy, [SOCKET_NAME_PROXY])

    @Job(
        name="plugin_proxy_enable",
        conditions=PLUGIN_UPDATE_CONDITIONS,
        on_condition=ProxyJobError,
    )
    async def enable(self) -> None:
        """Enable, install and start the proxy plugin.

        Core picks the proxy up from its container environment, so a running
        Core is rebuilt to switch over.
        """
        try:
            await super().enable()
        except (DockerError, PluginError) as err:
            raise ProxyError("Can't enable Proxy plugin", _LOGGER.error) from err
        await self._rebuild_core()

    async def disable(self) -> None:
        """Disable the proxy plugin and remove its container and image.

        The resumed config is dropped so a later enable does not claim the
        ports before Core pushes a current config.
        """
        try:
            await super().disable()
        except (DockerError, PluginError) as err:
            raise ProxyError("Can't disable Proxy plugin", _LOGGER.error) from err
        await self.sys_run_in_executor(self.autosave_file.unlink, True)
        await self._rebuild_core()

    async def _rebuild_core(self) -> None:
        """Recreate the Core container so it sees the proxy state."""
        if not await self.sys_homeassistant.core.is_running():
            return
        _LOGGER.info("Rebuilding Home Assistant Core for the proxy plugin change")
        try:
            await self.sys_homeassistant.core.rebuild()
        except HomeAssistantError as err:
            _LOGGER.error("Can't rebuild Home Assistant Core: %s", err)

    @Job(
        name="plugin_proxy_update",
        conditions=PLUGIN_UPDATE_CONDITIONS,
        on_condition=ProxyJobError,
    )
    async def update(self, version: AwesomeVersion | None = None) -> None:
        """Update proxy plugin."""
        try:
            await super().update(version)
        except PluginDisabledError as err:
            raise ProxyDisabledError(_LOGGER.error) from err
        except (DockerError, PluginError) as err:
            raise ProxyUpdateError("Proxy update failed", _LOGGER.error) from err

    async def restart(self) -> None:
        """Restart proxy plugin."""
        async with self._lifecycle_lock:
            if not self.enabled:
                raise ProxyDisabledError(_LOGGER.error)
            _LOGGER.info("Restarting Proxy plugin")
            await self.sys_run_in_executor(self._prepare_start)
            try:
                await self.instance.restart()
            except DockerError as err:
                raise ProxyError("Can't start Proxy plugin", _LOGGER.error) from err

    async def start(self) -> None:
        """Run proxy plugin."""
        if not self.enabled:
            raise ProxyDisabledError(_LOGGER.error)
        _LOGGER.info("Starting Proxy plugin")
        await self.sys_run_in_executor(self._prepare_start)
        try:
            await self.instance.run()
        except DockerError as err:
            raise ProxyError("Can't start Proxy plugin", _LOGGER.error) from err

    async def stop(self) -> None:
        """Stop proxy plugin."""
        _LOGGER.info("Stopping Proxy plugin")
        try:
            await self.instance.stop()
        except DockerError as err:
            raise ProxyError("Can't stop Proxy plugin", _LOGGER.error) from err

    async def stats(self, *, one_shot: bool = False) -> DockerStats:
        """Return stats of the proxy plugin."""
        try:
            return await self.instance.stats(one_shot=one_shot)
        except (DockerContainerNotFoundError, DockerContainerNotRunningError) as err:
            raise ProxyNotRunningError(_LOGGER.warning) from err
        except DockerStatsTimeoutError as err:
            raise ProxyStatsTimeoutError(_LOGGER.error) from err
        except DockerError as err:
            _LOGGER.error("Could not get stats of container for Proxy: %s", err)
            raise ProxyUnknownError from err

    async def repair(self) -> None:
        """Repair proxy plugin."""
        async with self._lifecycle_lock:
            if not self.enabled or await self.instance.exists():
                return

            _LOGGER.info("Repairing Proxy %s", self.version)
            try:
                await self.instance.install(self.version)
            except DockerError as err:
                _LOGGER.error("Repair of Proxy failed")
                await async_capture_exception(err)

    @Job(
        name="plugin_proxy_restart_after_problem",
        throttle_period=WATCHDOG_THROTTLE_PERIOD,
        throttle_max_calls=WATCHDOG_THROTTLE_MAX_CALLS,
        on_condition=ProxyJobError,
        throttle=JobThrottle.RATE_LIMIT,
    )
    async def _restart_after_problem(
        self, state: ContainerState, exit_code: int | None = None
    ):
        """Restart unhealthy or failed plugin."""
        return await super()._restart_after_problem(state, exit_code)
