from homeassistant.core import HomeAssistant, callback

from .watchers import EntitiesStatusChecker, ErrorWatcher, HostHealthWatcher, LoggerHandler


class ErrorWatchersManager:
    """Class to manage different watchers for errors"""

    def __init__(self, hass: HomeAssistant):
        self._started = False
        self.error_watchers: list[ErrorWatcher] = [
            EntitiesStatusChecker(hass),
            LoggerHandler(hass),
            HostHealthWatcher(hass),
        ]

    @callback
    def setup_watchers(self) -> None:
        """Start all watchers"""
        if self._started:
            return

        self._started = True

        for watcher in self.error_watchers:
            watcher.setup()

    @callback
    def remove_watchers(self) -> None:
        """Stop all watchers"""
        if not self._started:
            return

        self._started = False

        for watcher in self.error_watchers:
            try:
                watcher.remove()
            except Exception:
                pass
