DOMAIN = "robonomics_report_service"
ADDRESS = "address"

SERVICE_PAID = False

STORAGE_PINATA_CREDS = "pinata_creds"

CONF_EMAIL = "email"
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
LOGS_MAX_LEN = 3*1024*1024

LIBP2P_WS_SERVER = "ws://127.0.0.1:8888"
LIBP2P_LISTEN_PROTOCOL = "/pinataCreds"
LIBP2P_SEND_INITIALISATION_PROTOCOL = "/initialization"
LIBP2P_SEND_REPORT_PROTOCOL = "/report"
INTEGRATOR_PEER_ID = "12D3KooWBE2XrMkf1Z6P3AtKqYmvdD59aoD5xwKySrCgkmBqJNFh"
PROBLEM_SERVICE_ROBONOMICS_ADDRESS = "4HifM6Cny7bHAdLb5jw3hHV2KabuzRZV8gmHG1eh4PxJakwi"

FRONTEND_URL_PUBLIC = "report-service"
FRONTEND_URL = "/rrs/frontend"

CHECK_ENTITIES_TIMEOUT = 24 # Hours

OWNER_ADDRESS = PROBLEM_SERVICE_ROBONOMICS_ADDRESS
ERROR_SOURCES_MANAGER = "error_sources_manages"