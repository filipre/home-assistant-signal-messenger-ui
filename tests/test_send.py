"""Tests for sending messages via notify entities and the custom action."""

from __future__ import annotations

import base64
from pathlib import Path

from homeassistant.components.notify import (
    DOMAIN as NOTIFY_DOMAIN,
    SERVICE_SEND_MESSAGE,
)
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.signal_messenger_ui.const import DOMAIN

from .conftest import ALICE, GROUP_ID, SENDER, URL

SEND_URL = f"{URL}/v2/send"


def _payloads(aioclient_mock: AiohttpClientMocker) -> list[dict]:
    return [call[2] for call in aioclient_mock.mock_calls if str(call[1]) == SEND_URL]


async def test_entities_created(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    """Test one notify entity per recipient."""
    assert hass.states.get("notify.alice") is not None
    assert hass.states.get("notify.family") is not None


async def test_notify_send_message(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    setup_entry: MockConfigEntry,
) -> None:
    """Test notify.send_message uses the recipient's text mode."""
    aioclient_mock.post(SEND_URL, json={"timestamp": "1"})
    await hass.services.async_call(
        NOTIFY_DOMAIN,
        SERVICE_SEND_MESSAGE,
        {
            ATTR_ENTITY_ID: ["notify.alice", "notify.family"],
            "message": "Hi",
            "title": "Door",
        },
        blocking=True,
    )
    payloads = sorted(_payloads(aioclient_mock), key=lambda p: p["recipients"])
    assert payloads == [
        {
            "message": "Door\nHi",
            "number": SENDER,
            "recipients": [ALICE],
            "text_mode": "normal",
        },
        {
            "message": "**Door**\nHi",
            "number": SENDER,
            "recipients": [GROUP_ID],
            "text_mode": "styled",
        },
    ]
    assert hass.states.get("notify.alice").state != "unknown"


async def test_notify_send_error(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    setup_entry: MockConfigEntry,
) -> None:
    """Test API errors surface as HomeAssistantError."""
    aioclient_mock.post(SEND_URL, status=400, json={"error": "Unregistered user"})
    with pytest.raises(HomeAssistantError, match="Unregistered user"):
        await hass.services.async_call(
            NOTIFY_DOMAIN,
            SERVICE_SEND_MESSAGE,
            {ATTR_ENTITY_ID: "notify.alice", "message": "Hi"},
            blocking=True,
        )


async def test_action_with_local_attachment(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    setup_entry: MockConfigEntry,
    tmp_path: Path,
) -> None:
    """Test the custom action with a file attachment and ad-hoc recipient."""
    image = tmp_path / "snap.jpg"
    image.write_bytes(b"jpegdata")
    hass.config.allowlist_external_dirs = {str(tmp_path)}
    aioclient_mock.post(SEND_URL, json={"timestamp": "1"})

    await hass.services.async_call(
        DOMAIN,
        "send_message",
        {
            ATTR_ENTITY_ID: "notify.alice",
            "config_entry_id": setup_entry.entry_id,
            "recipients": ["+491733333333"],
            "message": "Motion",
            "text_mode": "styled",
            "attachments": [str(image)],
        },
        blocking=True,
    )
    [payload] = _payloads(aioclient_mock)
    assert payload["recipients"] == [ALICE, "+491733333333"]
    assert payload["text_mode"] == "styled"
    assert payload["base64_attachments"] == [
        "data:image/jpeg;filename=snap.jpg;base64,"
        + base64.b64encode(b"jpegdata").decode()
    ]
    assert hass.states.get("notify.alice").state != "unknown"


async def test_action_splits_groups_and_numbers(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    setup_entry: MockConfigEntry,
) -> None:
    """Test groups and numbers are never sent in the same request."""
    aioclient_mock.post(SEND_URL, json={"timestamp": "1"})
    await hass.services.async_call(
        DOMAIN,
        "send_message",
        {
            ATTR_ENTITY_ID: ["notify.alice", "notify.family"],
            "config_entry_id": setup_entry.entry_id,
            "recipients": ["+491733333333", "group.adhoc=="],
            "message": "Hi",
            "text_mode": "styled",
        },
        blocking=True,
    )
    assert [p["recipients"] for p in _payloads(aioclient_mock)] == [
        [ALICE, "+491733333333"],
        [GROUP_ID, "group.adhoc=="],
    ]


async def test_action_path_not_allowed(
    hass: HomeAssistant, setup_entry: MockConfigEntry, tmp_path: Path
) -> None:
    """Test files outside allowlist_external_dirs are rejected."""
    hass.config.allowlist_external_dirs = set()
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN,
            "send_message",
            {
                ATTR_ENTITY_ID: "notify.alice",
                "message": "x",
                "attachments": [str(tmp_path / "a")],
            },
            blocking=True,
        )
    assert err.value.translation_key == "path_not_allowed"


async def test_action_url_attachment(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    setup_entry: MockConfigEntry,
) -> None:
    """Test downloading URL attachments, allowlist and size limit."""
    image_url = "http://camera.local/snapshot.png"
    aioclient_mock.get(image_url, content=b"png", headers={"Content-Type": "image/png"})
    aioclient_mock.post(SEND_URL, json={"timestamp": "1"})

    hass.config.allowlist_external_urls = set()
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN,
            "send_message",
            {ATTR_ENTITY_ID: "notify.family", "message": "x", "urls": [image_url]},
            blocking=True,
        )
    assert err.value.translation_key == "url_not_allowed"

    hass.config.allowlist_external_urls = {"http://camera.local/"}
    await hass.services.async_call(
        DOMAIN,
        "send_message",
        {ATTR_ENTITY_ID: "notify.family", "message": "x", "urls": [image_url]},
        blocking=True,
    )
    [payload] = _payloads(aioclient_mock)
    assert payload["base64_attachments"] == [
        "data:image/png;filename=snapshot.png;base64,"
        + base64.b64encode(b"png").decode()
    ]


async def test_action_url_too_large(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    setup_entry: MockConfigEntry,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test the attachment size limit."""
    monkeypatch.setattr(
        "custom_components.signal_messenger_ui.services.MAX_ATTACHMENT_BYTES", 2
    )
    image_url = "http://camera.local/big.png"
    aioclient_mock.get(image_url, content=b"toolarge")
    hass.config.allowlist_external_urls = {"http://camera.local/"}
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN,
            "send_message",
            {ATTR_ENTITY_ID: "notify.family", "message": "x", "urls": [image_url]},
            blocking=True,
        )
    assert err.value.translation_key == "attachment_too_large"


async def test_action_validation(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    """Test recipient validation of the custom action."""
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN, "send_message", {"message": "x"}, blocking=True
        )
    assert err.value.translation_key == "no_recipients"

    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN,
            "send_message",
            {"message": "x", "recipients": [ALICE]},
            blocking=True,
        )
    assert err.value.translation_key == "config_entry_required"


async def test_unload(hass: HomeAssistant, setup_entry: MockConfigEntry) -> None:
    """Test unloading the entry."""
    assert await hass.config_entries.async_unload(setup_entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("notify.alice").state == "unavailable"
