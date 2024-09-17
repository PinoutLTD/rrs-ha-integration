from enum import Enum


class ProblemType(Enum):
    Devices = "unresponded_devices"
    Errors = "errors"
    Warnings = "warnings"
