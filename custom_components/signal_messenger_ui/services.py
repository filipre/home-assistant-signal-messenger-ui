"""The signal_messenger_ui.send_message action."""

from __future__ import annotations

import base64
from collections import defaultdict
import mimetypes
import os
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import unquote, urlparse

import aiohttp
from homeassistant.components.notify import ATTR_MESSAGE, ATTR_TITLE
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.target import (
    TargetSelection,
    async_extract_referenced_entity_ids,
)
import voluptuous as vol

from .const import (
    ATTR_ATTACHMENTS,
    ATTR_CONFIG_ENTRY_ID,
    ATTR_RECIPIENTS,
    ATTR_TEXT_MODE,
    ATTR_URLS,
    ATTR_VERIFY_SSL,
    DOMAIN,
    MAX_ATTACHMENT_BYTES,
    SERVICE_SEND_MESSAGE,
    TEXT_MODE_NORMAL,
    TEXT_MODES,
    URL_DOWNLOAD_TIMEOUT,
)
from .notify import async_send, format_message

if TYPE_CHECKING:
    from . import SignalConfigEntry
    from .notify import SignalNotifyEntity

SEND_MESSAGE_SCHEMA = vol.Schema(
    {
        **cv.ENTITY_SERVICE_FIELDS,
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Optional(ATTR_RECIPIENTS): vol.All(cv.ensure_list, [cv.string]),
        vol.Required(ATTR_MESSAGE): cv.string,
        vol.Optional(ATTR_TITLE): cv.string,
        vol.Optional(ATTR_TEXT_MODE): vol.In(TEXT_MODES),
        vol.Optional(ATTR_ATTACHMENTS): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(ATTR_URLS): vol.All(cv.ensure_list, [cv.url]),
        vol.Optional(ATTR_VERIFY_SSL, default=True): cv.boolean,
    }
)


def _data_uri(content: bytes, filename: str, mime: str | None) -> str:
    """Encode an attachment the way signal-cli-rest-api expects it."""
    mime = mime or mimetypes.guess_type(filename)[0] or "application/octet-stream"
    encoded = base64.b64encode(content).decode()
    return f"data:{mime};filename={filename};base64,{encoded}"


def _read_file(path: str) -> bytes:
    file = Path(path)
    if file.stat().st_size > MAX_ATTACHMENT_BYTES:
        raise ValueError("too_large")
    return file.read_bytes()


async def _load_file(hass: HomeAssistant, path: str) -> str:
    if not hass.config.is_allowed_path(path):
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="path_not_allowed",
            translation_placeholders={"path": path},
        )
    try:
        content = await hass.async_add_executor_job(_read_file, path)
    except ValueError as err:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="attachment_too_large",
            translation_placeholders={
                "attachment": path,
                "max_size": str(MAX_ATTACHMENT_BYTES),
            },
        ) from err
    except OSError as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="attachment_failed",
            translation_placeholders={"attachment": path, "error": str(err)},
        ) from err
    return _data_uri(content, os.path.basename(path), None)


async def _download(hass: HomeAssistant, url: str, verify_ssl: bool) -> str:
    if not hass.config.is_allowed_external_url(url):
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="url_not_allowed",
            translation_placeholders={"url": url},
        )
    too_large = ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key="attachment_too_large",
        translation_placeholders={
            "attachment": url,
            "max_size": str(MAX_ATTACHMENT_BYTES),
        },
    )
    session = async_get_clientsession(hass, verify_ssl=verify_ssl)
    try:
        async with session.get(
            url, timeout=aiohttp.ClientTimeout(total=URL_DOWNLOAD_TIMEOUT)
        ) as resp:
            resp.raise_for_status()
            if int(resp.headers.get("Content-Length") or 0) > MAX_ATTACHMENT_BYTES:
                raise too_large
            content = bytearray()
            async for chunk in resp.content.iter_chunked(64 * 1024):
                content.extend(chunk)
                if len(content) > MAX_ATTACHMENT_BYTES:
                    raise too_large
            mime = (
                resp.content_type
                if resp.content_type != "application/octet-stream"
                else None
            )
    except (aiohttp.ClientError, TimeoutError) as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="attachment_failed",
            translation_placeholders={
                "attachment": url,
                "error": str(err) or type(err).__name__,
            },
        ) from err
    filename = os.path.basename(unquote(urlparse(url).path)) or "attachment"
    return _data_uri(bytes(content), filename, mime)


def _loaded_entry(hass: HomeAssistant, entry_id: str) -> SignalConfigEntry:
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None or entry.domain != DOMAIN:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="entry_not_found",
            translation_placeholders={"entry_id": entry_id},
        )
    if entry.state is not ConfigEntryState.LOADED:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="entry_not_loaded",
            translation_placeholders={"entry": entry.title},
        )
    return entry


async def _async_send_message(call: ServiceCall) -> None:
    hass = call.hass
    registry = er.async_get(hass)

    # (config entry id, text mode) -> recipients; entities to record per entry
    batches: dict[tuple[str, str], list[str]] = defaultdict(list)
    recorded: list[SignalNotifyEntity] = []
    forced_mode: str | None = call.data.get(ATTR_TEXT_MODE)

    selected = async_extract_referenced_entity_ids(hass, TargetSelection(call.data))
    for entity_id in sorted(selected.referenced | selected.indirectly_referenced):
        reg_entry = registry.async_get(entity_id)
        if (
            reg_entry is None
            or reg_entry.platform != DOMAIN
            or reg_entry.config_entry_id is None
            or reg_entry.config_subentry_id is None
        ):
            if entity_id in selected.referenced:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="invalid_entity",
                    translation_placeholders={"entity_id": entity_id},
                )
            continue
        entry = _loaded_entry(hass, reg_entry.config_entry_id)
        entity = entry.runtime_data.entities.get(reg_entry.config_subentry_id)
        if entity is None:
            continue
        mode = forced_mode or entity.text_mode
        batches[(entry.entry_id, mode)].append(entity.recipient)
        recorded.append(entity)

    if recipients := call.data.get(ATTR_RECIPIENTS):
        if not (entry_id := call.data.get(ATTR_CONFIG_ENTRY_ID)):
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="config_entry_required"
            )
        _loaded_entry(hass, entry_id)
        batches[(entry_id, forced_mode or TEXT_MODE_NORMAL)].extend(recipients)

    if not batches:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="no_recipients"
        )

    attachments = [
        await _load_file(hass, path) for path in call.data.get(ATTR_ATTACHMENTS, [])
    ] + [
        await _download(hass, url, call.data[ATTR_VERIFY_SSL])
        for url in call.data.get(ATTR_URLS, [])
    ]

    for (entry_id, mode), batch in batches.items():
        entry = _loaded_entry(hass, entry_id)
        await async_send(
            entry.runtime_data.client,
            format_message(call.data[ATTR_MESSAGE], call.data.get(ATTR_TITLE), mode),
            list(dict.fromkeys(batch)),
            text_mode=mode,
            base64_attachments=attachments or None,
        )

    for entity in recorded:
        entity.record_notification()


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the integration's actions."""
    hass.services.async_register(
        DOMAIN, SERVICE_SEND_MESSAGE, _async_send_message, schema=SEND_MESSAGE_SCHEMA
    )
