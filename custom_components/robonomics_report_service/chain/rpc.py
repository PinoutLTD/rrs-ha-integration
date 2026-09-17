"""A small JSON-RPC client for a Substrate node, over one websocket.

Home Assistant already ships aiohttp, so nothing new is installed for this.
Calls are sequential by design: the integration publishes one report at a
time, and a multiplexing client would be more machinery than that deserves.
"""

import json
import logging
from typing import Any

import aiohttp

LOGGER = logging.getLogger(__name__)

# Statuses that end a submission, from author_submitAndWatchExtrinsic.
INCLUDED_STATUSES = ("inBlock", "finalized")
FAILED_STATUSES = ("dropped", "invalid", "usurped", "future", "retracted")


class RpcError(RuntimeError):
    """The node answered with an error."""

    def __init__(self, message: str, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


class RobonomicsRpc:
    """One websocket to one node; opened per operation, not kept warm."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        url: str,
        timeout_seconds: int = 30,
    ) -> None:
        self.session = session
        self.url = url
        self.timeout_seconds = timeout_seconds
        self._socket: aiohttp.ClientWebSocketResponse | None = None
        self._next_id = 0

    async def __aenter__(self) -> "RobonomicsRpc":
        self._socket = await self.session.ws_connect(
            self.url, timeout=aiohttp.ClientWSTimeout(ws_close=self.timeout_seconds)
        )
        return self

    async def __aexit__(self, *_) -> None:
        if self._socket is not None:
            await self._socket.close()
            self._socket = None

    @property
    def socket(self) -> aiohttp.ClientWebSocketResponse:
        if self._socket is None:
            raise RpcError("the websocket is not open")
        return self._socket

    async def _send(self, method: str, params: list[Any]) -> int:
        self._next_id += 1
        await self.socket.send_json(
            {"jsonrpc": "2.0", "id": self._next_id, "method": method, "params": params}
        )
        return self._next_id

    async def _read(self) -> dict:
        message = await self.socket.receive(timeout=self.timeout_seconds)
        if message.type is not aiohttp.WSMsgType.TEXT:
            raise RpcError(f"unexpected websocket message: {message.type.name}")
        return json.loads(message.data)

    async def request(self, method: str, params: list[Any] | None = None) -> Any:
        """Call a method and wait for the answer with the matching id."""

        request_id = await self._send(method, params or [])

        while True:
            message = await self._read()
            if message.get("id") != request_id:
                # A notification from an earlier subscription; not ours.
                continue
            if "error" in message:
                error = message["error"]
                text = error.get("message", "unknown error")
                # "Invalid Transaction" alone says nothing; the reason is in data.
                if error.get("data"):
                    text = f"{text}: {error['data']}"
                raise RpcError(text, error.get("code"))
            return message.get("result")

    async def submit_and_watch(self, extrinsic_hex: str) -> str:
        """Submit an extrinsic and return the hash of the block holding it."""

        subscription = await self.request("author_submitAndWatchExtrinsic", [extrinsic_hex])

        try:
            while True:
                message = await self._read()
                if message.get("method") != "author_extrinsicUpdate":
                    continue
                params = message.get("params", {})
                if params.get("subscription") != subscription:
                    continue

                status = params.get("result")
                if isinstance(status, str):
                    # "ready", "broadcast" and friends: still on its way.
                    continue
                if not isinstance(status, dict):
                    continue

                for name in INCLUDED_STATUSES:
                    if name in status:
                        return status[name]
                for name in FAILED_STATUSES:
                    if name in status:
                        raise RpcError(f"the node {name} the extrinsic")
        finally:
            try:
                await self.request("author_unwatchExtrinsic", [subscription])
            except (RpcError, aiohttp.ClientError, TimeoutError) as e:
                LOGGER.debug("Could not unwatch the extrinsic: %s", e)
