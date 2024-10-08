import logging
import typing as tp
import asyncio
import json

from homeassistant.core import HomeAssistant
from pyproxy import Libp2pProxyAPI

from .const import (
    LIBP2P_WS_SERVER,
    LIBP2P_LISTEN_PROTOCOL,
    LIBP2P_SEND_INITIALISATION_PROTOCOL,
    LIBP2P_SEND_REPORT_PROTOCOL,
    INTEGRATOR_PEER_ID,
    STORAGE_PINATA_CREDS,
    PROBLEM_SERVICE_ROBONOMICS_ADDRESS,
    CONF_PINATA_PUBLIC,
    CONF_PINATA_SECRET,
    CONF_EMAIL,
    DOMAIN,
)
from .utils import (
    async_save_to_store,
    decrypt_message,
    encrypt_message,
    get_address_for_seed,
)
from .ipfs import IPFS

_LOGGER = logging.getLogger(__name__)

LIBP2P_LISTEN_ERRORS_PROTOCOL = "/feedback"


class LibP2P:
    def __init__(self, hass: HomeAssistant, sender_seed: str):
        self.hass = hass
        self.libp2p_proxy = Libp2pProxyAPI(LIBP2P_WS_SERVER)
        self.sender_seed = sender_seed
        self.sender_address = get_address_for_seed(self.sender_seed)
        self.email = hass.data[DOMAIN][CONF_EMAIL]
        self._pinata_creds_saved = False
        self._listen_protocol = f"{LIBP2P_LISTEN_PROTOCOL}/{self.sender_address}"
        self._initialisation = False
        self._current_report = None

    async def send_report(self, report_hashes: tp.Dict, address: str) -> None:
        self._current_report = report_hashes
        try:
            await self._subscribe_to_feedback_protocol()
            message = self._format_report_message(report_hashes, address)
            _LOGGER.debug(f"Sending report using libp2p: {message}")
            await self.libp2p_proxy.send_msg_to_libp2p(
                message, LIBP2P_SEND_REPORT_PROTOCOL, server_peer_id=INTEGRATOR_PEER_ID
            )
        except Exception as e:
            _LOGGER.error(f"Error in sending report: {e}")
            await IPFS(self.hass).unpin_from_pinata(self._current_report)
            self._current_report = None

    async def get_and_save_pinata_creds(self) -> bool:
        _LOGGER.debug("Start getting Pinata creds")
        self._initialisation = True
        self._pinata_creds_saved = False
        await self._subscribe_to_feedback_protocol()
        await self.libp2p_proxy.subscribe_to_protocol_async(
            self._listen_protocol, self._save_pinata_creds, reconnect=True
        )
        await self._send_init_request()
        while not self._pinata_creds_saved:
            await asyncio.sleep(1)
        _LOGGER.debug("After got pinata creds")
        await self.libp2p_proxy.unsubscribe_from_all_protocols()
        self._initialisation = False
        return True

    async def _subscribe_to_feedback_protocol(self) -> None:
        await self.libp2p_proxy.subscribe_to_protocol_async(
            LIBP2P_LISTEN_ERRORS_PROTOCOL, self._handle_libp2p_feedback, reconnect=False
        )

    async def _save_pinata_creds(self, received_data: tp.Union[str, dict]):
        if "public" in received_data and "private" in received_data:
            storage_data = {}
            storage_data[CONF_PINATA_PUBLIC] = self._decrypt_message(
                received_data["public"]
            )
            storage_data[CONF_PINATA_SECRET] = self._decrypt_message(
                received_data["private"]
            )
            await async_save_to_store(
                self.hass,
                STORAGE_PINATA_CREDS,
                storage_data,
            )
            self._pinata_creds_saved = True
            _LOGGER.debug("Got and saved pinata creds")
        else:
            _LOGGER.error(f"Libp2p message in wrong format: {received_data}")

    async def _handle_libp2p_feedback(self, received_data: tp.Union[str, dict]):
        _LOGGER.debug(
            f"Libp2p feedback on {'initialisation' if self._initialisation else 'report'}: {received_data}"
        )
        if received_data["feedback"] != "ok":
            if self._initialisation:
                await asyncio.sleep(5)
                await self._send_init_request()
        if not self._initialisation:
            if received_data["feedback"] != "ok":
                if self._current_report is not None:
                    await IPFS(self.hass).unpin_from_pinata(self._current_report)
            self._current_report = None
            await self.libp2p_proxy.unsubscribe_from_all_protocols()

    def _decrypt_message(self, encrypted_data: str) -> str:
        return decrypt_message(
            encrypted_data,
            sender_address=PROBLEM_SERVICE_ROBONOMICS_ADDRESS,
            receiver_seed=self.sender_seed,
        )

    async def _send_init_request(self) -> None:
        data = self._format_data_for_init_request()
        _LOGGER.debug(f"Sendig initialisation request: {data}")
        await self.libp2p_proxy.send_msg_to_libp2p(
            data, LIBP2P_SEND_INITIALISATION_PROTOCOL, server_peer_id=INTEGRATOR_PEER_ID
        )

    def _format_data_for_init_request(self) -> str:
        encrypted_email = self._encrypt_message(self.email)
        data = {
            "email": encrypted_email,
            "sender_address": self.sender_address,
        }
        return json.dumps(data)

    def _format_report_message(self, report_hashes: tp.Dict, address: str) -> str:
        return json.dumps({"report": report_hashes, "address": address})

    def _encrypt_message(self, data: str) -> str:
        return encrypt_message(
            data,
            sender_seed=self.sender_seed,
            recipient_address=PROBLEM_SERVICE_ROBONOMICS_ADDRESS,
        )
