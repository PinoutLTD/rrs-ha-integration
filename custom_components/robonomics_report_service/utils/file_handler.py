import json
import os
import shutil
import tempfile
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

import homeassistant.util.dt as dt_util
from robonomicsinterface import Keypair

from ..const import REPORT_FILE_MAX_BYTES
from ..exceptions import (
    EncryptedFilesStagingError,
    IssueFileCreateError,
    TempArchiveCreateError,
)
from .encrypt_tools import multi_envelope_encrypt_data


def create_temp_dir_with_encrypted_files(
    dir_name_prefix: str,
    file_paths: list[str],
    sender_keypair: Keypair,
    recipient_addresses: list[str],
) -> str:
    """
    Create directory in tepmoral directory and copy there files.

    :param dir_name_prefix:     Name of the directory to create
    :param file_paths:          List of file paths to copy
    :param sender_keypair:      Robonomics keypair of sender
    :param recipient_addresses: List of addresses to send encrypted files

    :return:                    Path to the created directory
    """
    if not file_paths:
        raise EncryptedFilesStagingError(
            "No files provided for encryption staging"
        )

    # Create unique temp directory (ensured by mkdtemp)
    temp_dir_path = tempfile.mkdtemp(prefix=dir_name_prefix + "_")

    # Encrypt each file and copy it to temp directory
    try:
        for file_path in file_paths:
            try:
                # Prepere metadata with file name
                file_name = os.path.basename(file_path)
                metadata = {"orig_file_name": file_name}

                # Only last 3 MiB of logs are needed
                data_bytes = _read_tail_bytes(file_path, REPORT_FILE_MAX_BYTES)
                data = data_bytes.decode("utf-8", errors="replace")

                encrypted_data = multi_envelope_encrypt_data(
                    data, sender_keypair, list(recipient_addresses), metadata
                )

                # Unique temp file with ecncypted data
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    suffix=".enc",
                    dir=temp_dir_path,
                    delete=False,
                    delete_on_close=False,
                ) as f:
                    f.write(encrypted_data)

            except Exception as e:
                raise EncryptedFilesStagingError(
                    "Failed to encrypt file", file_path=file_path
                ) from e

        return temp_dir_path
    except Exception:
        shutil.rmtree(temp_dir_path, ignore_errors=True)
        raise


def delete_temp_dir(temp_dir_path: str) -> None:
    """
    Delete temporary directory

    :param dirpath: Path to the directory
    """
    try:
        shutil.rmtree(temp_dir_path)
    except FileNotFoundError:
        # Temp directory has benn already removed
        return
    except Exception:
        # Best-effort cleanup, ignore any failure
        return


def get_temp_dirs(dir_name_prefix: str) -> list[str]:
    """
    Collect list with all created temp dirs

    :param dir_name_prefix: Prefix of temp dirs
    :return:                List with paths of temp dirs
    """
    main_temp_dir_path = tempfile.gettempdir()
    found_temp_dirs_paths: list[str] = []

    try:
        with os.scandir(main_temp_dir_path) as all_temp_files:
            for temp_file in all_temp_files:
                if temp_file.is_dir() and temp_file.name.startswith(
                    dir_name_prefix
                ):
                    found_temp_dirs_paths.append(temp_file.path)
    except OSError:
        return []

    return found_temp_dirs_paths


def create_temp_archive(
    dir_to_archive: str, address_prefix: str, temp_dir_prefix: str
) -> str:
    """
    Create ZIP archive with files located in the specified directory

    :param dir_to_archive:  Directory with files to zip
    :param address_prefix:  Robonomics address to name archive
    :param temp_dir_prefix: Prefix to name temp dir for archive

    :return:                Path to created archive with directory files
    """
    temp_archive_dir_path = tempfile.mkdtemp(
        prefix=(temp_dir_prefix + "_archive_")
    )

    # Prepearing path and name for archive
    dt = dt_util.utcnow()
    dt_prefix = (
        dt.strftime("%Y%m%dT%H%M%S") + "MS" + f"{dt.microsecond // 1000:03d}"
    )

    temp_archive_name = f"{address_prefix}-{dt_prefix}.zip"
    temp_archive_path = os.path.join(temp_archive_dir_path, temp_archive_name)

    try:
        with ZipFile(
            temp_archive_path, "w", compression=ZIP_DEFLATED
        ) as zip_file:
            for entry in os.scandir(dir_to_archive):
                if not entry.is_file():
                    continue
                zip_file.write(filename=entry.path, arcname=entry.name)

        return temp_archive_path
    except Exception as e:
        shutil.rmtree(temp_archive_dir_path, ignore_errors=True)
        raise TempArchiveCreateError(
            f"Failed to create archive from directory: {dir_to_archive}"
        ) from e


def create_temp_dir_with_issue(
    issue: dict[str, Any],
    temp_dir_prefix: str,
) -> str:
    """
    Create temp directory and place there issue description to file

    :param issue:   Dict with description of issue

    :return:        Path to issue file
    """
    temp_issue_dir_path = tempfile.mkdtemp(
        prefix=(temp_dir_prefix + "_issue_")
    )

    issue_path = os.path.join(temp_issue_dir_path, "issue_description.json")

    try:
        payload = json.dumps(issue, ensure_ascii=False, indent=4)

        with open(issue_path, "w", encoding="utf-8") as f:
            f.write(payload)

        return issue_path

    except (OSError, TypeError) as e:
        shutil.rmtree(temp_issue_dir_path, ignore_errors=True)
        raise IssueFileCreateError(
            "Failed to create issue description file"
        ) from e


def _read_tail_bytes(path: str, max_bytes: int) -> bytes:
    """Collect only last max_bytes of data from file"""
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        start = max(0, size - max_bytes)
        f.seek(start, os.SEEK_SET)
        return f.read()


def remove_logs_files(log_path: str, backup_path: str) -> None:
    """Remove integration log files if they exist."""
    for path in (log_path, backup_path):
        try:
            os.remove(path)
        except FileNotFoundError:
            continue


def remove_logs_dir_if_empty(log_path: str) -> None:
    """Remove logs directory if it became empty."""
    logs_dir = os.path.dirname(log_path)
    if not logs_dir:
        return
    try:
        os.rmdir(logs_dir)
    except OSError:
        # Not empty or cannot remove: ignore
        return
