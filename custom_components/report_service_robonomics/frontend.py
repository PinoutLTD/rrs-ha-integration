""""Starting setup task: Frontend"."""
from __future__ import annotations

from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN


@callback
def async_register_frontend(hass: HomeAssistant) -> None:
    """Register the frontend."""
    if DOMAIN not in hass.data.get("frontend_panels", {}):
        hass.components.frontend.async_register_built_in_panel(
            component_name="custom",
            sidebar_title="Report an Issue",
            sidebar_icon="mdi:server",
            frontend_url_path="report-service",
            config={
                "_panel_custom": {
                    "name": "robonomics-panel",
                    "module_url": "/local/robonomics-panel.js",
                }
            },
        )

def async_remove_frontend(hass: HomeAssistant) -> None:
    hass.components.frontend.async_remove_panel("report-service")