import sys
from pathlib import Path

import pytest

# The `chain` package is plain Python: its tests must run without the whole
# Home Assistant runtime, so the component directory goes on the path.
COMPONENT_DIR = Path(__file__).parents[1] / "custom_components" / "robonomics_report_service"
sys.path.insert(0, str(COMPONENT_DIR))

try:  # The older tests exercise code that imports Home Assistant itself.
    import homeassistant  # noqa: F401
except ModuleNotFoundError:
    collect_ignore = ["test_utils_encrypt_tools.py", "test_utils_file_handler.py"]

SENDER_SEED = "frozen woman pet meat entire question balcony wing echo excess adjust sleep"
RECIPIENT_SEED = "lens exchange drum inside current bullet include stamp purity decline absurd play"
TEMP_DIR_NAME_PREFIX = "dir_for_test"


@pytest.fixture(scope="module", name="sender_account")
def fixture_sender_account():
    """The site's keypair, on the integration's own crypto"""
    from chain import Keypair

    return Keypair.create_from_secret(SENDER_SEED)


@pytest.fixture(scope="module", name="recipient_account")
def fixture_recipient_account():
    """The integrator's keypair, on the integration's own crypto"""
    from chain import Keypair

    return Keypair.create_from_secret(RECIPIENT_SEED)


@pytest.fixture(scope="module", name="temp_dir_name_prefix")
def fixture_temp_dir_name_prefix():
    """Returns prefix for temp directory name"""
    return TEMP_DIR_NAME_PREFIX
