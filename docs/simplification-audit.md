# Simplification audit

October 2026, at 1.1.0-beta.9 (`5bdbc2c`). Read-only pass over
`custom_components/` hunting over-engineering only: what to delete, simplify,
or replace with the standard library or Home Assistant itself. Nothing here is
applied yet; pick items by number.

The rule modules (`host_health`, `publisher`, `log_buffer`, `entity_health`)
are lean and are left alone. The weight sits in the older code: IPFS, report
assembly, exceptions, the watchers manager.

## Findings, biggest cut first

1. **delete** `IPFS.pin_files_from_dir_to_pinata` and `_pin_files_from_dir_to_pinata`
   (~50 lines). No callers: left over from pinning files one by one, before the
   archive. Its revoked-key branch duplicates `_pin_file_to_pinata`.
   [ipfs.py:65,111]
2. **native** drop `pinatapy-vourhey`. It serves one multipart POST and one
   DELETE; the key check already goes through Home Assistant's `aiohttp`
   (`async_check_pinata_keys`). With `async_get_clientsession` the fork, the
   executor jobs and the `pinatapy.API_ENDPOINT` patch for the stand all go; the
   stand endpoint becomes a plain URL. Changes the dependencies installed on
   sites, so decide separately. [ipfs.py, manifest.json, pyproject.toml]
3. **shrink** unpinning. The only caller passes one CID string
   (`Pending.payload`), so `_normalize_unpin_payload`, `_normalize_hash_dict`,
   `IpfsHashes`, JSON-string parsing and `UnpinResult` (whose `failed_hashes`
   nobody reads) collapse into `remove_pin(cid) -> bool` (~55 lines). Caveat: an
   old dict payload in a saved queue; the queue lives at most 72 h, so none will
   be left by 2.0.0. [ipfs.py:80-240, robonomics.py `_on_dropped`]
4. **yagni** nine classes in `exceptions.py` plus `utils/encrypt_tools.py`
   (~70 lines). Almost all are caught only to become one of two Home Assistant
   exceptions; the `address` and `file_path` attributes are never read.
   `multi_envelope_encrypt_data` only re-wraps the library's
   `encrypt_for_recipients`, and `file_handler` wraps any error in
   `EncryptedFilesStagingError` anyway. Keep two classes: "cannot build the
   report" and "an external service failed"; call the library directly.
   [exceptions.py, utils/encrypt_tools.py, report_service.py:87-120]
5. **shrink** six pairs of one-line wrappers in `ReportService`
   (`_async_create_*` / `_create_*`): call
   `hass.async_add_executor_job(create_temp_archive, …)` directly. One report
   also makes three temp directories (issue, encrypted files, archive) with
   three cleanups; one `tempfile.TemporaryDirectory()` built in a single executor
   function does it (~45 lines). [report_service.py:120-218, utils/file_handler.py]
6. **shrink** `ErrorWatcher._send_report`: a task that creates a task, with
   `try/except` around `async_create_task`, which never raises. One line:
   `hass.async_create_task(report_service.send_report(issue))`, without the
   service bus (~20 lines). [error_watchers/watchers/error_watcher.py:40-61]
7. **native** `hass.data[DOMAIN][entry_id][…]` → `entry.runtime_data`. Takes with
   it the `"report_service"` key (written, never read), the
   `ERROR_WATCHERS_MANAGER` and `HEARTBEAT` constants, and the empty
   `async_setup`, not needed by a config-entry-only integration (~20 lines).
   [__init__.py, const.py]
8. **yagni** `ErrorWatchersManager` and its `_started` flag guard against a
   double setup/remove that never happens. Keep the three watchers as a list in
   `runtime_data`, loop in setup and unload; drop `abc` from the base class
   (~35 lines). [error_watchers/error_watchers_manager.py, watchers/__init__.py]
9. **shrink** the `seed` step of the config flow: `async_show_form` with the same
   `description_placeholders` three times → one `_seed_form(errors)`; the
   generated seed is checked with `Keypair` twice (~20 lines).
   [config_flow.py:116-175]
10. **shrink** `_count_devices_entities` and the `or {}` / `or []` guards on dicts
    the checker built itself: `entities == len(unavailable_ids)`,
    `devices == len(grouped["devices"])` (~15 lines).
    [error_watchers/watchers/entities_checker.py:240-298]
11. **stdlib** `delete_temp_dir` → `shutil.rmtree(path, ignore_errors=True)`;
    `get_temp_dirs` → `glob.glob(os.path.join(tempfile.gettempdir(), prefix + "*"))`
    (~20 lines). [utils/file_handler.py:80-115]
12. **reuse** the message signature in `LoggerHandler` (`name|level|message`)
    repeats `log_buffer.message_key`; the `ts` computation is copied in two
    methods (~10 lines). [error_watchers/watchers/logger_handler.py:121-170]
13. **delete** at 2.0.0: storing `CONF_NETWORK = polkadot` in the config flow,
    kept only for a downgrade to beta.6. The warning in `_move_off_kusama` stays:
    1.0.0 sites still upgrade through it. [config_flow.py:108, const.py]
14. **delete** the HACS section of the README, `hacs.json`, `media/hacs.png` —
    only if 2.0.0 does drop HACS for file-based updates.

net: about −450 lines, −1 dependency possible.

## Out of scope, for a correctness review

- The `user` step of the config flow validates neither the addresses nor the
  Pinata keys; only `reconfigure` does. A typo at first setup surfaces at the
  first report.
- A failed report from a watcher never reaches the `except` of item 6: it lands
  in the log as an unhandled task exception, without a readable message.

## Suggested grouping

Items 1, 3, 4, 5 and 6 fit one PR before 2.0.0. Item 2 on its own, as it
changes what sites install.
