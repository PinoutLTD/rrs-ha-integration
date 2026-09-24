DOMAIN = "robonomics_report_service"
PROBLEM_REPORT_SERVICE = "send_problem_report"
ERROR_WATCHERS_MANAGER = "error_watchers_manager"

CREDS_STORAGE_KEY = "creds_storage"
# Reports waiting to be published, kept across restarts.
DATALOG_QUEUE_STORAGE_KEY = "datalog_queue"

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

NETWORK_POLKADOT = "polkadot"
NETWORK_KUSAMA = "kusama"
DEFAULT_NETWORK = NETWORK_POLKADOT

# Every node the client connects to must be a node of the chosen network.
NETWORK_GENESIS = {
    NETWORK_POLKADOT: "0x29f4371dcc41045f5041489dfcd51389bf8ccd2161332e0de1ca803bcc3ee872",
    NETWORK_KUSAMA: "0x631ccc82a078481584041656af292834e1ae6daab61d2875b4dd0c14bb9b17bc",
}

NETWORK_WSS = {
    NETWORK_POLKADOT: [
        "wss://polkadot.rpc.robonomics.network/",
    ],
    NETWORK_KUSAMA: [
        "wss://kusama.rpc.robonomics.network/",
    ],
}

RRS_REPORT_TEMP_DIR = "rrs_report_temp_dir"
TRACES_FILE_NAME = ".storage/trace.saved_traces"

REPORT_FILE_MAX_BYTES = 3 * 1024 * 1024
LOGS_PATH = f"{DOMAIN}/home-assistant.log"
LOGS_BACKUP_PATH = f"{DOMAIN}/home-assistant.log.1"

CHECK_LOGS_TIMEOUT = 24 * 60  # Mins
CHECK_ENTITIES_TIMEOUT = 24 * 60  # Mins
