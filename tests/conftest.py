"""Fixtures for Signal Messenger UI tests."""

from __future__ import annotations

from homeassistant.config_entries import ConfigSubentryData
from homeassistant.const import CONF_URL, CONF_VERIFY_SSL
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.signal_messenger_ui.const import (
    CONF_NUMBER,
    CONF_RECIPIENT,
    CONF_RECIPIENT_TYPE,
    CONF_TEXT_MODE,
    DOMAIN,
    RECIPIENT_TYPE_GROUP,
    RECIPIENT_TYPE_NUMBER,
    SUBENTRY_TYPE_RECIPIENT,
)

URL = "http://signal.local:8080"
SENDER = "+491700000000"
ALICE = "+491711111111"
GROUP_ID = "group.abc123=="


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations in all tests."""
    return


@pytest.fixture
def config_entry() -> MockConfigEntry:
    """Config entry with a number and a group recipient."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=SENDER,
        unique_id=SENDER,
        data={CONF_URL: URL, CONF_VERIFY_SSL: True, CONF_NUMBER: SENDER},
        subentries_data=[
            ConfigSubentryData(
                subentry_type=SUBENTRY_TYPE_RECIPIENT,
                title="Alice",
                unique_id=ALICE,
                data={
                    CONF_RECIPIENT_TYPE: RECIPIENT_TYPE_NUMBER,
                    CONF_RECIPIENT: ALICE,
                    CONF_TEXT_MODE: "normal",
                },
            ),
            ConfigSubentryData(
                subentry_type=SUBENTRY_TYPE_RECIPIENT,
                title="Family",
                unique_id=GROUP_ID,
                data={
                    CONF_RECIPIENT_TYPE: RECIPIENT_TYPE_GROUP,
                    CONF_RECIPIENT: GROUP_ID,
                    CONF_TEXT_MODE: "styled",
                },
            ),
        ],
    )


@pytest.fixture
async def setup_entry(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> MockConfigEntry:
    """Set up the integration."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    return config_entry
