class RobonomicsReportServiceError(Exception):
    """Base exception for RRS integration."""


# for encrypt_tools.py
class EnvelopeRecipientEncryptError(RobonomicsReportServiceError):
    """Failed to encrypt envelop for a specific recipient address."""

    def __init__(self, address: str, reason: str | None = None) -> None:
        self.address = address
        msg = f"Failed to wrap secret key for recipient address: {address}"
        if reason:
            msg += f" ({reason})"
        super().__init__(msg)


# for file_handler.py
class EncryptedFilesStagingError(RobonomicsReportServiceError):
    """Failed to prepare encrypted files in temp directory."""

    def __init__(self, msg: str, file_path: str | None = None) -> None:
        self.file_path = file_path
        full_msg = msg
        if file_path is not None:
            full_msg = f"{msg}: {file_path}"
        super().__init__(full_msg)


class TempArchiveCreateError(RobonomicsReportServiceError):
    """Failed to create ZIP archive."""


class IssueFileCreateError(RobonomicsReportServiceError):
    """Failed to create issue description file."""


# for ha_storage.py
class StorageError(RobonomicsReportServiceError):
    """Failed to load/save/remove integration storage."""


# for ipfs.py
class IPFSError(RobonomicsReportServiceError):
    """IPFS/Pinata operation failed."""


class PinataKeysRevokedError(IPFSError):
    """Pinata API key has been revoked."""


# for robonomics.py
class RobonomicsError(RobonomicsReportServiceError):
    """Robonomics operation failed."""


# for report_service.py
class ReportInputError(RobonomicsReportServiceError):
    """Report cannot be created due to missing/invalid inputs."""
