import typing as tp

class MessageFormatter:
    @staticmethod
    def format_devices_list(data: dict, first_line_string: str) -> str:
        message = first_line_string
        message += "\nDevices:\n"
        for device in data["devices"]:
            message += f"   * {data["devices"][device]['device_name']}\n"
            message += "   * Entities:\n"
            for entity_name in data["devices"][device]["entities"]:
                message += f"       * {entity_name}\n"
        if len(data["entities"]) > 0:
            message += "Entities without devices:\n"
            for entity_name in data["entities"]:
                message += f"   * {entity_name}\n"
        return message

    @staticmethod
    def concatinate_messages(message1: str, message2: str) -> str:
        return f"{message1}\n{message2}"

    @staticmethod
    def format_warnins_message(warnings: tp.List[str]) -> str:
        message = "Following warninds were detected:\n"
        for warning in warnings:
            message += f"*{warning}\n"
        return message
