"""Config flow for the Signal Messenger UI integration."""

from __future__ import annotations

import logging
import re
from typing import Any

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.const import CONF_NAME, CONF_URL, CONF_VERIFY_SSL
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
import voluptuous as vol

from .api import SignalApiClient, SignalError
from .const import (
    CONF_NUMBER,
    CONF_RECIPIENT,
    CONF_RECIPIENT_TYPE,
    CONF_TEXT_MODE,
    DOMAIN,
    RECIPIENT_TYPE_GROUP,
    RECIPIENT_TYPE_NUMBER,
    SUBENTRY_TYPE_RECIPIENT,
    TEXT_MODE_NORMAL,
    TEXT_MODES,
)

_LOGGER = logging.getLogger(__name__)

# E.164 phone number or a Signal ACI (UUID).
RECIPIENT_RE = re.compile(
    r"^(\+[1-9]\d{6,14}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$",
    re.IGNORECASE,
)

TEXT_MODE_SELECTOR = SelectSelector(
    SelectSelectorConfig(
        options=TEXT_MODES, translation_key=CONF_TEXT_MODE, mode=SelectSelectorMode.LIST
    )
)


def _server_schema(defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_URL, default=defaults.get(CONF_URL, "")): TextSelector(
                TextSelectorConfig(type=TextSelectorType.URL)
            ),
            vol.Required(
                CONF_VERIFY_SSL, default=defaults.get(CONF_VERIFY_SSL, True)
            ): bool,
        }
    )


def create_client(
    hass: HomeAssistant, data: dict[str, Any], number: str | None = None
) -> SignalApiClient:
    """Create an API client from config entry data."""
    return SignalApiClient(
        async_get_clientsession(hass, verify_ssl=data[CONF_VERIFY_SSL]),
        data[CONF_URL],
        number or data.get(CONF_NUMBER),
    )


class SignalMessengerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Signal Messenger UI."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        self._server: dict[str, Any] = {}
        self._accounts: list[str] = []

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Return subentries supported by this integration."""
        return {SUBENTRY_TYPE_RECIPIENT: RecipientSubentryFlowHandler}

    async def _async_validate_server(
        self, user_input: dict[str, Any]
    ) -> tuple[dict[str, str], list[str]]:
        """Check the REST API is reachable and return its accounts."""
        client = create_client(self.hass, user_input)
        try:
            await client.async_get_about()
            accounts = await client.async_list_accounts()
        except SignalError as err:
            _LOGGER.debug("Cannot connect to %s: %s", user_input[CONF_URL], err)
            return {"base": "cannot_connect"}, []
        return {}, accounts

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the REST API URL."""
        errors: dict[str, str] = {}
        if user_input is not None:
            errors, accounts = await self._async_validate_server(user_input)
            if not errors:
                self._server = user_input
                self._accounts = accounts
                return await self.async_step_account()
        return self.async_show_form(
            step_id="user",
            data_schema=_server_schema(user_input or {}),
            errors=errors,
        )

    async def async_step_account(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick the sender account."""
        errors: dict[str, str] = {}
        if user_input is not None:
            number = user_input[CONF_NUMBER].strip()
            if not RECIPIENT_RE.match(number):
                errors[CONF_NUMBER] = "invalid_number"
            else:
                await self.async_set_unique_id(number)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=number, data={**self._server, CONF_NUMBER: number}
                )

        number_selector: SelectSelector | TextSelector
        if self._accounts:
            number_selector = SelectSelector(
                SelectSelectorConfig(options=self._accounts, custom_value=True)
            )
        else:
            number_selector = TextSelector(
                TextSelectorConfig(type=TextSelectorType.TEL)
            )
        return self.async_show_form(
            step_id="account",
            data_schema=vol.Schema({vol.Required(CONF_NUMBER): number_selector}),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the REST API URL."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            errors, _ = await self._async_validate_server(user_input)
            if not errors:
                return self.async_update_reload_and_abort(
                    entry, data_updates=user_input
                )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_server_schema(user_input or dict(entry.data)),
            errors=errors,
        )


class RecipientSubentryFlowHandler(ConfigSubentryFlow):
    """Add or change a recipient (phone number or group)."""

    def __init__(self) -> None:
        """Initialize the flow."""
        self._groups: dict[str, str] = {}

    def _recipient_configured(self, recipient: str) -> bool:
        return any(
            sub.data.get(CONF_RECIPIENT) == recipient
            for sub in self._get_entry().subentries.values()
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Choose the kind of recipient."""
        return self.async_show_menu(
            step_id="user", menu_options=[RECIPIENT_TYPE_NUMBER, RECIPIENT_TYPE_GROUP]
        )

    async def async_step_number(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Add a phone number recipient."""
        errors: dict[str, str] = {}
        if user_input is not None:
            recipient = user_input[CONF_RECIPIENT].strip()
            if not RECIPIENT_RE.match(recipient):
                errors[CONF_RECIPIENT] = "invalid_number"
            elif self._recipient_configured(recipient):
                return self.async_abort(reason="already_configured")
            else:
                return self.async_create_entry(
                    title=user_input[CONF_NAME],
                    data={
                        CONF_RECIPIENT_TYPE: RECIPIENT_TYPE_NUMBER,
                        CONF_RECIPIENT: recipient,
                        CONF_TEXT_MODE: user_input[CONF_TEXT_MODE],
                    },
                    unique_id=recipient,
                )
        return self.async_show_form(
            step_id="number",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Required(CONF_NAME): str,
                        vol.Required(CONF_RECIPIENT): TextSelector(
                            TextSelectorConfig(type=TextSelectorType.TEL)
                        ),
                        vol.Required(
                            CONF_TEXT_MODE, default=TEXT_MODE_NORMAL
                        ): TEXT_MODE_SELECTOR,
                    }
                ),
                user_input,
            ),
            errors=errors,
        )

    async def async_step_group(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Add a group recipient."""
        if user_input is not None:
            recipient = user_input[CONF_RECIPIENT]
            if self._recipient_configured(recipient):
                return self.async_abort(reason="already_configured")
            return self.async_create_entry(
                title=user_input.get(CONF_NAME)
                or self._groups.get(recipient, recipient),
                data={
                    CONF_RECIPIENT_TYPE: RECIPIENT_TYPE_GROUP,
                    CONF_RECIPIENT: recipient,
                    CONF_TEXT_MODE: user_input[CONF_TEXT_MODE],
                },
                unique_id=recipient,
            )

        client = create_client(self.hass, dict(self._get_entry().data))
        try:
            groups = await client.async_list_groups()
        except SignalError as err:
            _LOGGER.debug("Cannot list groups: %s", err)
            return self.async_abort(reason="cannot_connect")
        self._groups = {group.id: group.name for group in groups}
        if not self._groups:
            return self.async_abort(reason="no_groups")

        return self.async_show_form(
            step_id="group",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_RECIPIENT): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                SelectOptionDict(value=group_id, label=name)
                                for group_id, name in self._groups.items()
                            ],
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Optional(CONF_NAME): str,
                    vol.Required(
                        CONF_TEXT_MODE, default=TEXT_MODE_NORMAL
                    ): TEXT_MODE_SELECTOR,
                }
            ),
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Change name and text mode of a recipient."""
        subentry = self._get_reconfigure_subentry()
        if user_input is not None:
            return self.async_update_and_abort(
                self._get_entry(),
                subentry,
                title=user_input[CONF_NAME],
                data={**subentry.data, CONF_TEXT_MODE: user_input[CONF_TEXT_MODE]},
            )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME, default=subentry.title): str,
                    vol.Required(
                        CONF_TEXT_MODE,
                        default=subentry.data.get(CONF_TEXT_MODE, TEXT_MODE_NORMAL),
                    ): TEXT_MODE_SELECTOR,
                }
            ),
            description_placeholders={"recipient": subentry.data[CONF_RECIPIENT]},
        )
