DOMAIN = "robonomics_report_service"
ADDRESS = "address"

STORAGE_ACCOUNT_SEED = "account_seed"
STORAGE_PINATA_CREDS = "pinata_creds"

CONF_EMAIL = "email"
CONF_OWNER_SEED = "owner_seed"
CONF_CONTROLLER_SEED = "controller_seed"
CONF_OWNER_ADDRESS = "owner_address"
CONF_PINATA_SECRET = "pinata_secret"
CONF_PINATA_PUBLIC = "pinata_public"
CONF_SENDER_SEED = "sender_seed"
CONF_PHONE_NUMBER = "phone_number"

ROBONOMICS_WSS = [
    "wss://kusama.rpc.robonomics.network/",
    "wss://robonomics.leemo.me/",
    "wss://robonomics.0xsamsara.com/",
]

PROBLEM_REPORT_SERVICE = "report_an_issue"
LOG_FILE_NAME = "home-assistant.log"
TRACES_FILE_NAME = ".storage/trace.saved_traces"
IPFS_PROBLEM_REPORT_FOLDER = "ha_problem_report"
LOGS_MAX_LEN = 9*1024*1024

ROOT_LOGGER = "root_logger"
LOGGER_HANDLER = "logger_handler"

WEBSOCKET = "websocket"
LIBP2P_UNSUB = "libp2p"
LIBP2P_WS_SERVER = "ws://127.0.0.1:8888"
LIBP2P_LISTEN_PROTOCOL = "/pinataCreds"
LIBP2P_SEND_PROTOCOL = "/initialization"
INTEGRATOR_PEER_ID = "12D3KooWBE2XrMkf1Z6P3AtKqYmvdD59aoD5xwKySrCgkmBqJNFh"
PROBLEM_SERVICE_ROBONOMICS_ADDRESS = "4HifM6Cny7bHAdLb5jw3hHV2KabuzRZV8gmHG1eh4PxJakwi"

FRONTEND_URL_PUBLIC = "report-service"
FRONTEND_URL = "/rrs/frontend"
ROBONOMICS = "robonomics"
SERVICE_STATUS = "service_status"

RWS_CHECK_UNSUB = "rws_check_unsub"
CHECK_ENTITIES_TRACK_TIME_UNSUB = "check_entities_track_time_unsub"
HANDLE_CHECK_ENTITIES_TIME_CHANGE = "handle_check_entities_time_change"
CHECK_ENTITIES_TIMEOUT = 24 # Hours

OWNER_ADDRESS = ""