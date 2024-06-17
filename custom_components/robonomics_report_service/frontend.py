""""Starting setup task: Frontend"."""
from __future__ import annotations

from homeassistant.core import HomeAssistant, callback
from homeassistant.components.frontend import async_remove_panel, async_register_built_in_panel

from .const import DOMAIN, FRONTEND_URL, FRONTEND_URL_PUBLIC
from .rrs_frontend import get_path

@callback
def async_register_frontend(hass: HomeAssistant) -> None:
    """Register the frontend."""
    hass.http.register_static_path(FRONTEND_URL, get_path(), cache_headers=False)
    if DOMAIN not in hass.data.get("frontend_panels", {}):
        async_register_built_in_panel(
            hass,
            component_name="custom",
            sidebar_title="Report an Issue",
            sidebar_icon="mdi:server",
            frontend_url_path=FRONTEND_URL_PUBLIC,
            config={
                "_panel_custom": {
                    "name": "robonomics-panel",
                    "module_url": f"{FRONTEND_URL}/robonomics-panel.js",
                }
            },
        )


def async_remove_frontend(hass: HomeAssistant) -> None:
    async_remove_panel(hass, FRONTEND_URL_PUBLIC)
