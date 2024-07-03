import typing as tp

class MessageFormatter:
    @staticmethod
    def format_devices_list(data: dict, type: str) -> str:
        message = ""
        for device in data["devices"]:
            message += f"*{data["devices"][device]['device_name']}:"
            for entity_name in data["devices"][device]["entities"]:
                message += f"{entity_name},"
            message += f" - {type}\n"
        if len(data["entities"]) > 0:
            message += "*Entities:"
            for entity_name in data["entities"]:
                message += f"{entity_name},"
        return message

    @staticmethod
    def concatinate_messages(message1: str, message2: str) -> str:
        return f"{message1}\n{message2}"

    @staticmethod
    def format_warnins_message(warnings: tp.List[str]) -> str:
        message = ""
        for warning in warnings:
            message += f"*{warning}\n"
        return message
