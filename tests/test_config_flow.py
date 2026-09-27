"""The setup form: what it asks for and what it stores."""

from unittest.mock import AsyncMock

import pytest

pytest.importorskip("homeassistant", reason="the config flow is Home Assistant code")

from custom_components.robonomics_report_service import config_flow  # noqa: E402
from custom_components.robonomics_report_service.const import CONF_NETWORK  # noqa: E402


def test_the_form_no_longer_asks_for_a_network():
    # Robonomics on Kusama is legacy; there is nothing left to choose.
    asked = {str(key) for key in config_flow.STEP_USER_DATA_SCHEMA.schema}

    assert CONF_NETWORK not in asked
    assert "problem_service_robonomics_address" in asked


@pytest.mark.asyncio
async def test_the_stored_network_is_polkadot_for_older_betas(monkeypatch):
    flow = config_flow.ReportServiceConfigFlow()
    flow.async_set_unique_id = AsyncMock()
    flow._abort_if_unique_id_configured = lambda: None

    async def stop_at_seed_step():
        return "seed step"

    monkeypatch.setattr(flow, "async_step_seed", stop_at_seed_step)

    await flow.async_step_user({"problem_service_robonomics_address": "4GsB"})

    assert flow._storage_data[CONF_NETWORK] == "polkadot"
