from __future__ import annotations

from typing import Any

from aiohttp import ClientError, ClientSession


class AuthenticationError(ConnectionError):
    """Raised when the read-only status token is rejected."""


class EventPreislisteApi:
    def __init__(self, session: ClientSession, url: str, token: str) -> None:
        self.session = session
        self.url = url.rstrip("/")
        self.token = token

    async def status(self) -> dict[str, Any]:
        try:
            async with self.session.get(
                f"{self.url}/api/status",
                headers={"Authorization": f"Bearer {self.token}"},
                timeout=10,
            ) as response:
                if response.status == 401:
                    raise AuthenticationError("Status token rejected")
                response.raise_for_status()
                data = await response.json()
        except AuthenticationError:
            raise
        except (ClientError, TimeoutError, ValueError) as error:
            raise ConnectionError("Event Price List is unavailable") from error
        if data.get("ok") is not True or not isinstance(data.get("events"), int):
            raise ConnectionError("Invalid Event Price List response")
        return data
