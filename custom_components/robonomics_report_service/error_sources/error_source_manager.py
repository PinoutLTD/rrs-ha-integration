import typing as tp

from homeassistant.core import HomeAssistant, callback

from .sources.entities_checker import EntitiesStatusChecker
from .sources.error_source import ErrorSource
from .sources.logger_handler import LoggerHandler

class ErrorSourcesManager:
    def __init__(self, hass: HomeAssistant):
        self.error_sources: tp.List[ErrorSource] = [EntitiesStatusChecker(hass), LoggerHandler(hass)]

    @callback
    def setup_sources(self) -> None:
        for source in self.error_sources:
            source.setup()

    @callback
    def remove_sources(self) -> None:
        for source in self.error_sources:
            source.remove()