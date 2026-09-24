"""The chain client as the integration builds it."""

from unittest.mock import MagicMock

import pytest

pytest.importorskip("homeassistant", reason="robonomics.py is Home Assistant glue")

from homeassistant.util.ssl import client_context  # noqa: E402

from custom_components.robonomics_report_service.const import (  # noqa: E402
    NETWORK_GENESIS,
    NETWORK_KUSAMA,
    NETWORK_POLKADOT,
)
from custom_components.robonomics_report_service.robonomics import Robonomics  # noqa: E402

from .conftest import SENDER_SEED  # noqa: E402


@pytest.mark.parametrize("network", [NETWORK_POLKADOT, NETWORK_KUSAMA])
def test_the_client_uses_home_assistants_tls_context(network):
    robonomics = Robonomics(MagicMock(), network, MagicMock(), SENDER_SEED)

    # Built when Home Assistant starts; a context made per connection would
    # read certificates from disk inside the event loop.
    assert robonomics.client._ssl is client_context()
    assert robonomics.client.genesis_hash == NETWORK_GENESIS[network]
