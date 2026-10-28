"""Init file for Supervisor proxy plugin RESTful API."""

import asyncio
from collections.abc import Awaitable
import logging
from typing import Any

from aiohttp import web
import voluptuous as vol

from ..const import (
    ATTR_ENABLED,
    ATTR_ONE_SHOT,
    ATTR_UPDATE_AVAILABLE,
    ATTR_VERSION,
    ATTR_VERSION_LATEST,
)
from ..coresys import CoreSysAttributes
from ..exceptions import APIError, ProxyDisabledError
from ..validate import version_tag
from .utils import api_process, api_return_stats, api_validate, require_running_system

_LOGGER: logging.Logger = logging.getLogger(__name__)

# pylint: disable=no-value-for-parameter
SCHEMA_VERSION = vol.Schema({vol.Optional(ATTR_VERSION): version_tag})
SCHEMA_OPTIONS = vol.Schema({vol.Optional(ATTR_ENABLED): vol.Boolean()})


class APIProxyPlugin(CoreSysAttributes):
    """Handle RESTful API for the proxy plugin."""

    @api_process
    async def info(self, request: web.Request) -> dict[str, Any]:
        """Return proxy plugin information."""
        return {
            ATTR_VERSION: self.sys_plugins.proxy.version,
            ATTR_VERSION_LATEST: self.sys_plugins.proxy.latest_version,
            ATTR_UPDATE_AVAILABLE: self.sys_plugins.proxy.need_update,
            ATTR_ENABLED: self.sys_plugins.proxy.enabled,
        }

    @api_process
    async def options(self, request: web.Request) -> None:
        """Set proxy plugin options."""
        body = await api_validate(SCHEMA_OPTIONS, request)

        if ATTR_ENABLED in body:
            if body[ATTR_ENABLED]:
                await asyncio.shield(self.sys_plugins.proxy.enable())
            else:
                await asyncio.shield(self.sys_plugins.proxy.disable())

    @api_process
    async def stats(self, request: web.Request) -> dict[str, Any]:
        """Return resource information for v2 contract (always one-shot)."""
        stats = await self.sys_plugins.proxy.stats(one_shot=True)
        return api_return_stats(stats, legacy=False)

    @api_process
    async def stats_v1(self, request: web.Request) -> dict[str, Any]:
        """Return resource information."""
        one_shot = ATTR_ONE_SHOT in request.query
        stats = await self.sys_plugins.proxy.stats(one_shot=one_shot)

        return api_return_stats(stats, legacy=True)

    @api_process
    @require_running_system
    async def update(self, request: web.Request) -> None:
        """Update proxy plugin."""
        if not self.sys_plugins.proxy.enabled:
            raise ProxyDisabledError

        body = await api_validate(SCHEMA_VERSION, request)
        version = body.get(ATTR_VERSION, self.sys_plugins.proxy.latest_version)

        if not self.sys_plugins.proxy.version:
            raise APIError("Proxy plugin is not installed")
        if version == self.sys_plugins.proxy.version:
            raise APIError(f"Version {version} is already in use")
        await asyncio.shield(self.sys_plugins.proxy.update(version))

    @api_process
    @require_running_system
    def restart(self, request: web.Request) -> Awaitable[None]:
        """Restart proxy plugin."""
        return asyncio.shield(self.sys_plugins.proxy.restart())
