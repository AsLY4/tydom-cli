"""Async Tydom client built on the pytydom transport.

A small standalone session client — the terminal counterpart of the Home
Assistant hub — that exercises the whole pytydom library end to end: the
cloud gateway-password lookup (account mode), the digest handshake and
websocket session, HTTP-over-websocket request/response correlation by
Transac-Id, and the unsolicited push stream.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import time
from collections.abc import Callable

import aiohttp
from pytydom import (
    Frame,
    TydomConnectionError,
    cloud,
    gateway,
    protocol,
)

_LOGGER = logging.getLogger(__name__)

# Same partial-message reassembly cap as the integration.
_FRAME_BUFFER_LIMIT = 1_048_576

# Redact credentials before they reach the (debug) log.
_SECRET_RE = re.compile(r'("(?:pwd|pin|password)"\s*:\s*)"[^"]*"', re.IGNORECASE)


def _redact(body: str) -> str:
    return _SECRET_RE.sub(r'\1"***"', body or "")


class TydomClient:
    """One websocket session to a Tydom gateway."""

    def __init__(
        self,
        host: str,
        mac: str,
        *,
        port: int,
        timeout: float,
        heartbeat: float,
        verify_tls: bool = False,
        remote: bool = False,
    ) -> None:
        self._host = host
        self._mac = mac
        self._port = port
        self._timeout = timeout
        self._heartbeat = heartbeat
        self._verify_tls = verify_tls
        self._remote = remote
        self._tx_prefix = b"\x02" if remote else b""
        self._session: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._reader: asyncio.Task | None = None
        self._pending: dict[str, asyncio.Future] = {}
        self._rx = b""
        self._last_ms = 0
        self._push_handlers: list[Callable[[Frame], None]] = []

    def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None:
            self._session = aiohttp.ClientSession()
        return self._session

    async def fetch_gateway_password(
        self,
        email: str,
        account_password: str,
        *,
        discovery_url: str,
        sites_url: str,
        client_id: str,
        scope: str,
    ) -> str:
        """Account mode: retrieve the gateway password from the cloud."""
        return await cloud.async_get_gateway_password(
            self._ensure_session(),
            email,
            account_password,
            self._mac,
            discovery_url=discovery_url,
            sites_url=sites_url,
            client_id=client_id,
            scope=scope,
            timeout=self._timeout,
        )

    async def connect(self, gateway_password: str) -> None:
        """Open the authenticated websocket session and start reading."""
        self._ws = await gateway.async_open_session(
            self._ensure_session(),
            self._host,
            self._mac,
            gateway_password,
            self._verify_tls,
            port=self._port,
            timeout=self._timeout,
            heartbeat=self._heartbeat,
        )
        _LOGGER.debug("Session opened to %s:%s", self._host, self._port)
        self._reader = asyncio.create_task(self._read_loop())

    def on_push(self, handler: Callable[[Frame], None]) -> None:
        """Register a callback for unsolicited (request-style) frames."""
        self._push_handlers.append(handler)

    def _next_transac_id(self) -> str:
        now_ms = int(time.time() * 1000)
        self._last_ms = max(now_ms, self._last_ms + 1)
        return str(self._last_ms)

    async def request(
        self, method: str, path: str, body: str = "", *, timeout: float | None = None
    ) -> Frame:
        """Send one request and await its Transac-Id-correlated response.

        Returns the full response Frame — unlike the integration's runtime
        router, the CLI surfaces the HTTP status so a rejected command is
        visible (a diagnostic tool must not hide it).
        """
        if self._ws is None or self._ws.closed:
            raise TydomConnectionError("Not connected to the gateway")
        transac_id = self._next_transac_id()
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[transac_id] = future
        _LOGGER.debug("-> %s %s #%s %s", method, path, transac_id, _redact(body))
        try:
            await self._ws.send_bytes(
                self._tx_prefix + protocol.build_request(method, path, transac_id, body)
            )
            return await asyncio.wait_for(future, timeout or self._timeout)
        except (TimeoutError, aiohttp.ClientError, OSError) as err:
            raise TydomConnectionError("Gateway did not answer the request") from err
        finally:
            self._pending.pop(transac_id, None)

    async def _read_loop(self) -> None:
        try:
            async for msg in self._ws:
                if msg.type in (aiohttp.WSMsgType.BINARY, aiohttp.WSMsgType.TEXT):
                    raw = (
                        bytes(msg.data)
                        if isinstance(msg.data, (bytes, bytearray))
                        else str(msg.data).encode()
                    )
                    self._feed(raw.lstrip(b"\x02"))
        except (aiohttp.ClientError, OSError, asyncio.CancelledError):
            pass
        finally:
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(TydomConnectionError("Gateway session closed"))

    def _feed(self, raw: bytes) -> None:
        buffer = self._rx + raw
        self._rx = b""
        while buffer:
            try:
                frame, remainder = protocol.next_frame(buffer)
            except ValueError:
                return
            if frame is None:
                if remainder and len(remainder) <= _FRAME_BUFFER_LIMIT:
                    self._rx = remainder  # incomplete: wait for more bytes
                return
            try:
                self._dispatch(frame)
            except Exception:  # noqa: BLE001 - reader must survive bad frames/handlers
                _LOGGER.debug(
                    "Failed to dispatch frame for %s", frame.path, exc_info=True
                )
            buffer = remainder

    def _dispatch(self, frame: Frame) -> None:
        if frame.kind == "response":
            _LOGGER.debug(
                "<- HTTP %s %s #%s %s",
                frame.status,
                frame.path,
                frame.transac_id,
                _redact(frame.body),
            )
            future = self._pending.get(frame.transac_id or "")
            if future is not None and not future.done():
                future.set_result(frame)
                return
        else:
            _LOGGER.debug(
                "<- push %s %s %s", frame.method or "", frame.path, _redact(frame.body)
            )
        # Unsolicited push (or an uncorrelated/late response).
        for handler in self._push_handlers:
            handler(frame)

    async def close(self) -> None:
        if self._reader is not None:
            self._reader.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reader
        if self._ws is not None:
            await self._ws.close()
        if self._session is not None:
            await self._session.close()
