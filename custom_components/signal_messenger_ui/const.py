"""Constants for the Signal Messenger UI integration."""

from typing import Final

DOMAIN: Final = "signal_messenger_ui"

CONF_NUMBER: Final = "number"
CONF_RECIPIENT: Final = "recipient"
CONF_RECIPIENT_TYPE: Final = "recipient_type"
CONF_TEXT_MODE: Final = "text_mode"

SUBENTRY_TYPE_RECIPIENT: Final = "recipient"

RECIPIENT_TYPE_NUMBER: Final = "number"
RECIPIENT_TYPE_GROUP: Final = "group"

GROUP_ID_PREFIX: Final = "group."

TEXT_MODE_NORMAL: Final = "normal"
TEXT_MODE_STYLED: Final = "styled"
TEXT_MODES: Final = [TEXT_MODE_NORMAL, TEXT_MODE_STYLED]

ATTR_ATTACHMENTS: Final = "attachments"
ATTR_CONFIG_ENTRY_ID: Final = "config_entry_id"
ATTR_RECIPIENTS: Final = "recipients"
ATTR_TEXT_MODE: Final = "text_mode"
ATTR_URLS: Final = "urls"
ATTR_VERIFY_SSL: Final = "verify_ssl"

SERVICE_SEND_MESSAGE: Final = "send_message"

MAX_ATTACHMENT_BYTES: Final = 50 * 1024 * 1024
URL_DOWNLOAD_TIMEOUT: Final = 10
