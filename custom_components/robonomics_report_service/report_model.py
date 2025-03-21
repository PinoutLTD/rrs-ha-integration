from dataclasses import dataclass
from enum import Enum
from random import randint

class ReportStatus(Enum):
    WAIT_FOR_PINATA = 1
    WAIT_FOR_RESPONSE = 2
    DONE = 3

@dataclass
class ReportData:
    id: str
    encrypted_data: dict
    description: str
    status: ReportStatus

    @staticmethod
    def create(encrypted_data: dict, description: str) -> 'ReportData':
        return ReportData(str(randint(0, 100000)), encrypted_data, description, ReportStatus.WAIT_FOR_RESPONSE)
