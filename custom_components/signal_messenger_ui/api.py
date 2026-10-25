"""Async client for the signal-cli-rest-api."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import aiohttp
from homeassistant.util.json import json_loads

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)


class SignalError(Exception):
    """Base error for the Signal REST API."""


class SignalConnectionError(SignalError):
    """The REST API could not be reached."""


class SignalApiError(SignalError):
    """The REST API returned an error response."""


@dataclass(frozen=True, slots=True)
class SignalGroup:
    """A Signal group the account is a member of."""

    id: str
    name: str


class SignalApiClient:
    """Minimal client for the endpoints this integration needs."""

    def __init__(
        self, session: aiohttp.ClientSession, base_url: str, number: str | None = None
    ) -> None:
        """Initialize the client."""
        self._session = session
        self._base_url = base_url.rstrip("/")
        self.number = number

    async def _request(
        self, method: str, path: str, json: dict[str, Any] | None = None
    ) -> Any:
        """Perform a request and return the decoded JSON body (or None)."""
        try:
            async with self._session.request(
                method, f"{self._base_url}{path}", json=json, timeout=REQUEST_TIMEOUT
            ) as resp:
                text = await resp.text()
                try:
                    body: Any = json_loads(text) if text else None
                except ValueError:
                    body = None
                if resp.status >= 400:
                    message = (
                        body.get("error") if isinstance(body, dict) else text
                    ) or f"HTTP {resp.status}"
                    raise SignalApiError(message)
                return body
        except (aiohttp.ClientError, TimeoutError) as err:
            raise SignalConnectionError(str(err) or type(err).__name__) from err

    async def async_get_about(self) -> dict[str, Any]:
        """Return version and mode information of the REST API."""
        return await self._request("GET", "/v1/about")

    async def async_list_accounts(self) -> list[str]:
        """Return the accounts registered with the REST API."""
        accounts = await self._request("GET", "/v1/accounts") or []
        result: list[str] = []
        for account in accounts:
            # Older versions return plain numbers, newer ones {"number", "aci"}.
            if isinstance(account, str):
                result.append(account)
            elif isinstance(account, dict) and (
                ident := account.get("number") or account.get("aci")
            ):
                result.append(ident)
        return result

    async def async_list_groups(self) -> list[SignalGroup]:
        """Return the groups of the configured account."""
        groups = await self._request("GET", f"/v1/groups/{self.number}") or []
        return [
            SignalGroup(id=group["id"], name=group.get("name") or group["id"])
            for group in groups
            if group.get("id")
        ]

    async def async_send(
        self,
        message: str,
        recipients: list[str],
        *,
        text_mode: str = "normal",
        base64_attachments: list[str] | None = None,
    ) -> dict[str, Any] | None:
        """Send a message to one or more recipients."""
        payload: dict[str, Any] = {
            "message": message,
            "number": self.number,
            "recipients": recipients,
            "text_mode": text_mode,
        }
        if base64_attachments:
            payload["base64_attachments"] = base64_attachments
        return await self._request("POST", "/v2/send", json=payload)
