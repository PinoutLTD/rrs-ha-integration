from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
import voluptuous as vol
import logging

from .const import FRONTEND_URL_PUBLIC, DOMAIN, SERVICE_STATUS
from .utils import ReportServiceStatus

_LOGGER = logging.getLogger(__name__)

@callback
def async_register_websocket_commands(hass: HomeAssistant) -> None:
    websocket_api.async_register_command(hass, check_subscription)


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{FRONTEND_URL_PUBLIC}/check_subscription",
    }
)
@websocket_api.async_response
async def check_subscription(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict,
) -> None:
    """Handle websocket subscriptions."""

    connection.send_result(msg["id"], hass.data[DOMAIN][SERVICE_STATUS])