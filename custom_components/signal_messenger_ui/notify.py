"""Notify entities for Signal recipients."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.notify import NotifyEntity, NotifyEntityFeature
from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import SignalApiClient, SignalError
from .const import (
    CONF_RECIPIENT,
    CONF_RECIPIENT_TYPE,
    CONF_TEXT_MODE,
    DOMAIN,
    RECIPIENT_TYPE_GROUP,
    TEXT_MODE_NORMAL,
    TEXT_MODE_STYLED,
)

if TYPE_CHECKING:
    from . import SignalConfigEntry

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SignalConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create a notify entity for every recipient subentry."""
    for subentry in entry.subentries.values():
        entity = SignalNotifyEntity(entry.runtime_data.client, subentry)
        entry.runtime_data.entities[subentry.subentry_id] = entity
        async_add_entities([entity], config_subentry_id=subentry.subentry_id)


def format_message(message: str, title: str | None, text_mode: str) -> str:
    """Prepend the title, bold when styled text is enabled."""
    if not title:
        return message
    if text_mode == TEXT_MODE_STYLED:
        title = f"**{title}**"
    return f"{title}\n{message}"


async def async_send(
    client: SignalApiClient,
    message: str,
    recipients: list[str],
    *,
    text_mode: str,
    base64_attachments: list[str] | None = None,
) -> None:
    """Send a message and translate API errors."""
    try:
        await client.async_send(
            message,
            recipients,
            text_mode=text_mode,
            base64_attachments=base64_attachments,
        )
    except SignalError as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="send_failed",
            translation_placeholders={"error": str(err)},
        ) from err


class SignalNotifyEntity(NotifyEntity):
    """A Signal phone number or group to send messages to."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_supported_features = NotifyEntityFeature.TITLE

    def __init__(self, client: SignalApiClient, subentry: ConfigSubentry) -> None:
        """Initialize the entity."""
        self._client = client
        self.recipient: str = subentry.data[CONF_RECIPIENT]
        self.text_mode: str = subentry.data.get(CONF_TEXT_MODE, TEXT_MODE_NORMAL)
        is_group = subentry.data.get(CONF_RECIPIENT_TYPE) == RECIPIENT_TYPE_GROUP
        self._attr_unique_id = subentry.subentry_id
        self._attr_icon = "mdi:account-group" if is_group else "mdi:account"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, subentry.subentry_id)},
            name=subentry.title,
            manufacturer="Signal",
            model="Group" if is_group else "Contact",
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_send_message(self, message: str, title: str | None = None) -> None:
        """Send a message to this recipient."""
        await async_send(
            self._client,
            format_message(message, title, self.text_mode),
            [self.recipient],
            text_mode=self.text_mode,
        )

    def record_notification(self) -> None:
        """Mark that a notification was sent via the custom action."""
        self._async_record_notification()
