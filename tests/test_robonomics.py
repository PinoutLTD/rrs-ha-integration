"""The chain client as the integration builds it, and the move off Kusama."""

from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("homeassistant", reason="robonomics.py is Home Assistant glue")

from homeassistant.util.ssl import client_context  # noqa: E402
from robonomicsinterface import ROBONOMICS_GENESIS_HASH  # noqa: E402

import custom_components.robonomics_report_service as integration  # noqa: E402
from custom_components.robonomics_report_service.const import (  # noqa: E402
    CONF_NETWORK,
    ROBONOMICS_ENDPOINTS,
)
from custom_components.robonomics_report_service.robonomics import Robonomics  # noqa: E402

from .conftest import SENDER_SEED  # noqa: E402


def test_the_client_talks_to_polkadot_with_home_assistants_tls_context():
    robonomics = Robonomics(MagicMock(), MagicMock(), SENDER_SEED)

    # Built when Home Assistant starts; a context made per connection would
    # read certificates from disk inside the event loop.
    assert robonomics.client._ssl is client_context()
    assert robonomics.client.genesis_hash == ROBONOMICS_GENESIS_HASH
    assert list(robonomics.client.endpoints) == ROBONOMICS_ENDPOINTS


@pytest.mark.asyncio
async def test_a_site_stored_on_kusama_moves_to_polkadot(monkeypatch, caplog):
    save = AsyncMock()
    monkeypatch.setattr(integration, "async_save_to_store", save)
    creds = {CONF_NETWORK: "kusama", "sender_seed": "kept"}

    await integration._move_off_kusama(MagicMock(), creds)

    assert creds == {CONF_NETWORK: "polkadot", "sender_seed": "kept"}
    save.assert_awaited_once()
    assert "no longer supported" in caplog.text


@pytest.mark.asyncio
async def test_a_polkadot_site_is_left_as_it_is(monkeypatch):
    save = AsyncMock()
    monkeypatch.setattr(integration, "async_save_to_store", save)

    await integration._move_off_kusama(MagicMock(), {CONF_NETWORK: "polkadot"})
    await integration._move_off_kusama(MagicMock(), {})

    save.assert_not_awaited()
