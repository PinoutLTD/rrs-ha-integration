import logging
import typing as tp
import asyncio
import json
from copy import deepcopy

from homeassistant.core import HomeAssistant
from .pyproxy import Libp2pProxyAPI
from homeassistant.exceptions import HomeAssistantError

from .const import (
    LIBP2P_WS_SERVER,
    INTEGRATOR_PEER_ID,
    PROBLEM_SERVICE_ROBONOMICS_ADDRESS,
    CONF_EMAIL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

LIBP2P_LISTEN_ERRORS_PROTOCOL = "/feedback"
LIBP2P_INITILIZATION_PROTOCOL = "/initialization"
LIBP2P_REPORT_PROTOCOL = "/report"

class LibP2PConnectionException(HomeAssistantError):
    """Can't connect to LibP2P"""

class LibP2P:
    def __init__(self, hass_address: str) -> None:
        self._hass_address = hass_address
        self._libp2p_proxy = Libp2pProxyAPI(LIBP2P_WS_SERVER)
        self._init_instanse = LibP2PInitialization(self._libp2p_proxy, self._hass_address)
        self._report_instanse = LibP2PReports(self._libp2p_proxy, self._hass_address)

    async def get_integrator_address(self) -> str | None:
        return await self._init_instanse.get_integrator_address()

    async def get_pinata_creds(self, encrypted_email: str) -> dict:
        return await self._init_instanse.get_pinata_creds(encrypted_email)

    async def send_report(self, report_data: dict, report_id: int) -> None:
        await self._report_instanse.send_report(report_data, report_id)

    def register_report_handler(self, handler: tp.Awaitable) -> None:
        self._report_instanse.register_report_handler(handler)

    async def disconnect(self) -> None:
        _LOGGER.debug("Start disconnect from libp2p")
        await self._libp2p_proxy.unsubscribe_from_all_protocols()
        _LOGGER.debug("Finish disconnect from libp2p")


class LibP2PReports:
    def __init__(self, libp2p_proxy: Libp2pProxyAPI, hass_address: str) -> None:
        """Initialize the LibP2PInitialization class.

        :param libp2p_proxy: Instance of Libp2pProxyAPI.
        :param hass_address: Home Assistant address.
        """
        self._hass_address: str = hass_address
        self._libp2p_proxy: Libp2pProxyAPI = libp2p_proxy
        self._handle_report_response: tp.Awaitable = None
        self._wait_for_response_count = 0
        self._subscribed_for_responses = False

    async def send_report(self, report_data: dict, report_id: int) -> None:
        _LOGGER.debug(f"Start send report in libp2p with id: {report_id}")
        await self._subscribe_to_report_response_protocol()
        await asyncio.sleep(0)
        message = self._format_report_message(report_data, report_id)
        _LOGGER.debug(f"Sending report using libp2p: {message}")
        await self._libp2p_proxy.send_msg_to_libp2p(
            message, LIBP2P_REPORT_PROTOCOL, server_peer_id=INTEGRATOR_PEER_ID
        )

    def register_report_handler(self, handler: tp.Awaitable) -> None:
        self._handle_report_response = handler

    async def _subscribe_to_report_response_protocol(self) -> None:
        _LOGGER.debug("Subscribe to report responce protocol")
        self._wait_for_response_count += 1
        _LOGGER.debug(f"Wait for responces reports in subscribe: {self._wait_for_response_count}, _subscribed_for_responses: {self._subscribed_for_responses}")
        if not self._subscribed_for_responses:
            await self._libp2p_proxy.subscribe_to_protocol_async(
                f"{LIBP2P_REPORT_PROTOCOL}/{self._hass_address}", self._handle_report_response_message, reconnect=False
            )
            while not self._libp2p_proxy.ws_client.is_listening:
                await asyncio.sleep(1)
            self._subscribed_for_responses = True
            _LOGGER.debug("Subscribed to report responce protocol")

    async def _handle_report_response_message(self, received_data: tp.Union[str, dict]):
        _LOGGER.debug(f"Libp2p report response: {received_data}")
        self._wait_for_response_count -= 1
        _LOGGER.debug(f"Wait for responces reports: {self._wait_for_response_count}")
        if self._wait_for_response_count == 0:
            self._subscribed_for_responses = False
            await self._libp2p_proxy.unsubscribe_from_protocol(f"{LIBP2P_REPORT_PROTOCOL}/{self._hass_address}")
        if "datalog" in received_data and "id" in received_data:
            await self._handle_report_response(received_data["id"], received_data)
        else:
            _LOGGER.error(f"Libp2p message in wrong format: {received_data}")

    def _format_report_message(self, report_data: dict, report_id: int) -> str:
        return json.dumps({"report": report_data, "address": self._hass_address, "id": report_id})


class LibP2PInitialization:
    """Handles the initialization process for LibP2P, including retrieving integrator addresses and Pinata credentials."""

    def __init__(self, libp2p_proxy: Libp2pProxyAPI, hass_address: str) -> None:
        self._hass_address = hass_address
        self._libp2p_proxy = libp2p_proxy
        self._common_resp_received = False
        self._common_resp = None
        self._err_feedback = False

    async def get_integrator_address(self) -> str | None:
        await self._subscribe_to_feedback_protocol()
        res = await self._send_request_and_wait_for_response(
            self._format_data_for_init_request_address(), LIBP2P_INITILIZATION_PROTOCOL
        )
        if "integrator_address" in res:
            return res["integrator_address"]
        else:
            _LOGGER.error("Integrator address not received, message is in wrong format: %s", res)
            return None

    async def get_pinata_creds(self, encrypted_email: str) -> dict:
        res = await self._send_request_and_wait_for_response(
            self._format_data_for_init_request_pinata(encrypted_email), LIBP2P_INITILIZATION_PROTOCOL
        )
        if not ("public" in res and "private" in res):
            _LOGGER.error("Pinata creds not received, message is in wrong format: %s", res)
            res = {}
        await self._libp2p_proxy.unsubscribe_from_protocol(f"{LIBP2P_INITILIZATION_PROTOCOL}/{self._hass_address}")
        return res

    async def _send_request_and_wait_for_response(self, data: str, protocol: str) -> dict:
        self._common_resp_received = False
        self._common_resp = None
        await self._libp2p_proxy.subscribe_to_protocol_async(
            f"{protocol}/{self._hass_address}", self._common_request_callback, reconnect=True
        )
        _LOGGER.debug("Sending request to LibP2P: %s", data)
        await self._libp2p_proxy.send_msg_to_libp2p(data, protocol, server_peer_id=INTEGRATOR_PEER_ID)
        while not self._common_resp_received:
            if self._err_feedback:
                self._err_feedback = False
                raise LibP2PConnectionException
            await asyncio.sleep(1)
        self._common_resp_received = False
        resp = deepcopy(self._common_resp)
        self._common_resp = None
        return resp

    async def _subscribe_to_feedback_protocol(self) -> None:
        await self._libp2p_proxy.subscribe_to_protocol_async(
            LIBP2P_LISTEN_ERRORS_PROTOCOL, self._handle_libp2p_feedback, reconnect=False
        )

    async def _handle_libp2p_feedback(self, received_data: tp.Union[str, dict]):
        _LOGGER.debug(
            f"Libp2p feedback on initialisation: {received_data}"
        )
        if received_data["feedback"] != "ok":
            self._err_feedback = True
        await self._libp2p_proxy.unsubscribe_from_protocol(LIBP2P_LISTEN_ERRORS_PROTOCOL)

    async def _common_request_callback(self, received_data: tp.Union[str, dict]):
        _LOGGER.debug("Received LibP2P response: %s", received_data)
        self._common_resp = received_data
        self._common_resp_received = True

    def _format_data_for_init_request_pinata(self, encrypted_email: str) -> str:
        data = {
            "email": encrypted_email,
            "address": self._hass_address,
        }
        return json.dumps(data)

    def _format_data_for_init_request_address(self) -> str:
        data = {
            "new_client": self._hass_address,
        }
        return json.dumps(data)
