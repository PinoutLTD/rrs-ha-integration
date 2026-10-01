DOMAIN = "robonomics_report_service"
PROBLEM_REPORT_SERVICE = "send_problem_report"
ERROR_WATCHERS_MANAGER = "error_watchers_manager"

CREDS_STORAGE_KEY = "creds_storage"
# Reports waiting to be published, kept across restarts.
DATALOG_QUEUE_STORAGE_KEY = "datalog_queue"
# Daily memory means of the host, for the host health watcher.
HOST_HEALTH_STORAGE_KEY = "host_health"

HEARTBEAT = "heartbeat"
HEARTBEAT_INTERVAL = 24 * 60  # Mins
HEARTBEAT_STARTUP_DELAY = 5  # Mins

CONF_PINATA_SECRET = "pinata_secret"
CONF_PINATA_PUBLIC = "pinata_public"
CONF_SENDER_SEED = "sender_seed"
CONF_SENDER_EMAIL = "sender_email"
CONF_NETWORK = "network"

PROBLEM_SERVICE_ROBONOMICS_ADDRESS = "problem_service_robonomics_address"
OWNER_ADDRESS = "subscription_owner_robonomics_address"

# Robonomics on Polkadot only: Kusama is legacy and shutting down, and the
# chain library refuses its nodes. The network is still stored with the
# credentials so that going back to a beta that reads it keeps working.
NETWORK_POLKADOT = "polkadot"

ROBONOMICS_ENDPOINTS = [
    "wss://polkadot.rpc.robonomics.network/",
]

RRS_REPORT_TEMP_DIR = "rrs_report_temp_dir"
TRACES_FILE_NAME = ".storage/trace.saved_traces"

REPORT_FILE_MAX_BYTES = 3 * 1024 * 1024
LOGS_PATH = f"{DOMAIN}/home-assistant.log"
LOGS_BACKUP_PATH = f"{DOMAIN}/home-assistant.log.1"

CHECK_LOGS_TIMEOUT = 24 * 60  # Mins
CHECK_ENTITIES_TIMEOUT = 24 * 60  # Mins
