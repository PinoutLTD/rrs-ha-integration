import asyncio
from functools import wraps
import websockets
from .logger import logger


def set_websocket(func):
    """Check if a websocket exists and create a new otherwise.

    :param func: Wrapped function.
    :return: Wrapped function after decoration.
    """

    @wraps(func)
    async def wrapper(ws_client_instance, *args, **kwargs):
        """
        :param ws_client_instance: WebsocketClient instance in a decorated function.
        :param args: Wrapped function args.
        :param kwargs: Wrapped function kwargs
        """
        if ws_client_instance.websocket is not None:
            await func(ws_client_instance, *args, **kwargs)
            return

        connected = await _connect(ws_client_instance, kwargs.get("reconnect", False))
        if connected:
            protocols = ws_client_instance.protocols_manager.get_protocols()
            await ws_client_instance.send_msg_to_subscribe(protocols)
            await func(ws_client_instance, *args, **kwargs)

    async def _connect(ws_client_instance, reconnect: bool) -> bool:
        if not ws_client_instance.is_connecting or reconnect:
            if ws_client_instance.websocket is None:
                ws_client_instance.is_connecting = True
                if reconnect:
                    await _reconnecting(ws_client_instance)
                else:
                    await _connect_once(ws_client_instance)
                ws_client_instance.is_connecting = False
        return ws_client_instance.websocket is not None

    async def _reconnecting(ws_client_instance) -> None:
        while ws_client_instance.websocket is None:
            try:
                ws_client_instance.websocket = await websockets.connect(
                    ws_client_instance.proxy_server_url, ping_timeout=None
                )
            except Exception as e:
                logger.warning(f"Websocket connection exception in decorator: {e}, reconnecting...")
                await asyncio.sleep(5)

    async def _connect_once(ws_client_instance) -> None:
        try:
            ws_client_instance.websocket = await websockets.connect(
                ws_client_instance.proxy_server_url, ping_timeout=None
            )
        except Exception as e:
            logger.error(f"Websocket connection exception in decorator: {e}, will not reconnect")
            raise e

    return wrapper
