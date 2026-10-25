"""Tests for the config flow."""

from __future__ import annotations

import aiohttp
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_NAME, CONF_URL, CONF_VERIFY_SSL
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.signal_messenger_ui.const import (
    CONF_NUMBER,
    CONF_RECIPIENT,
    CONF_TEXT_MODE,
    DOMAIN,
    SUBENTRY_TYPE_RECIPIENT,
)

from .conftest import ALICE, GROUP_ID, SENDER, URL

ABOUT = {"build": 2, "mode": "json-rpc", "version": "0.90", "versions": ["v1", "v2"]}


def _mock_server(aioclient_mock: AiohttpClientMocker, accounts=None) -> None:
    aioclient_mock.get(f"{URL}/v1/about", json=ABOUT)
    aioclient_mock.get(
        f"{URL}/v1/accounts", json=accounts if accounts is not None else [SENDER]
    )


async def test_user_flow(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test the happy path."""
    _mock_server(aioclient_mock, accounts=[{"number": SENDER, "aci": "x"}])
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: URL, CONF_VERIFY_SSL: True}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "account"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_NUMBER: SENDER}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == SENDER
    assert result["data"] == {CONF_URL: URL, CONF_VERIFY_SSL: True, CONF_NUMBER: SENDER}
    assert result["result"].unique_id == SENDER


async def test_user_flow_cannot_connect(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test connection errors are shown and the flow can recover."""
    aioclient_mock.get(f"{URL}/v1/about", exc=aiohttp.ClientError())
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: URL, CONF_VERIFY_SSL: True}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}

    aioclient_mock.clear_requests()
    _mock_server(aioclient_mock, accounts=[])
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: URL, CONF_VERIFY_SSL: True}
    )
    assert result["step_id"] == "account"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_NUMBER: "0170"}
    )
    assert result["errors"] == {CONF_NUMBER: "invalid_number"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_NUMBER: SENDER}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_flow_already_configured(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    config_entry: MockConfigEntry,
) -> None:
    """Test the same account can't be added twice."""
    config_entry.add_to_hass(hass)
    _mock_server(aioclient_mock)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: URL, CONF_VERIFY_SSL: True}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_NUMBER: SENDER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reconfigure(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    setup_entry: MockConfigEntry,
) -> None:
    """Test changing the URL."""
    new_url = "http://other:8080"
    aioclient_mock.get(f"{new_url}/v1/about", json=ABOUT)
    aioclient_mock.get(f"{new_url}/v1/accounts", json=[SENDER])
    result = await setup_entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_URL: new_url, CONF_VERIFY_SSL: False}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert setup_entry.data[CONF_URL] == new_url
    assert setup_entry.data[CONF_VERIFY_SSL] is False


async def _start_subentry(hass: HomeAssistant, entry: MockConfigEntry, step: str):
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_TYPE_RECIPIENT), context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.MENU
    return await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"next_step_id": step}
    )


async def test_subentry_number(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    """Test adding a phone number recipient."""
    result = await _start_subentry(hass, setup_entry, "number")
    assert result["step_id"] == "number"
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {CONF_NAME: "Bob", CONF_RECIPIENT: "12345", CONF_TEXT_MODE: "normal"},
    )
    assert result["errors"] == {CONF_RECIPIENT: "invalid_number"}
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {CONF_NAME: "Bob", CONF_RECIPIENT: "+491722222222", CONF_TEXT_MODE: "styled"},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert hass.states.get("notify.bob") is not None


async def test_subentry_number_duplicate(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    """Test adding an existing recipient aborts."""
    result = await _start_subentry(hass, setup_entry, "number")
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {CONF_NAME: "Alice 2", CONF_RECIPIENT: ALICE, CONF_TEXT_MODE: "normal"},
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_subentry_group(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    setup_entry: MockConfigEntry,
) -> None:
    """Test adding a group recipient from the group list."""
    aioclient_mock.get(
        f"{URL}/v1/groups/{SENDER}",
        json=[
            {"id": GROUP_ID, "name": "Family", "internal_id": "x"},
            {"id": "group.new==", "name": "Neighbours", "internal_id": "y"},
        ],
    )
    result = await _start_subentry(hass, setup_entry, "group")
    assert result["step_id"] == "group"
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_RECIPIENT: "group.new==", CONF_TEXT_MODE: "normal"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Neighbours"


async def test_subentry_group_errors(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    setup_entry: MockConfigEntry,
) -> None:
    """Test group step aborts without groups or connection."""
    aioclient_mock.get(f"{URL}/v1/groups/{SENDER}", json=[])
    result = await _start_subentry(hass, setup_entry, "group")
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_groups"

    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{URL}/v1/groups/{SENDER}", exc=aiohttp.ClientError())
    result = await _start_subentry(hass, setup_entry, "group")
    assert result["reason"] == "cannot_connect"


async def test_subentry_reconfigure(
    hass: HomeAssistant, setup_entry: MockConfigEntry
) -> None:
    """Test renaming a recipient."""
    subentry_id = next(
        sid for sid, sub in setup_entry.subentries.items() if sub.title == "Alice"
    )
    result = await setup_entry.start_subentry_reconfigure_flow(hass, subentry_id)
    assert result["step_id"] == "reconfigure"
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {CONF_NAME: "Alice B", CONF_TEXT_MODE: "styled"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    subentry = setup_entry.subentries[subentry_id]
    assert subentry.title == "Alice B"
    assert subentry.data[CONF_TEXT_MODE] == "styled"
    assert subentry.data[CONF_RECIPIENT] == ALICE
