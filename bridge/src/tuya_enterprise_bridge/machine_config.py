from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping


class MachineConfigError(ValueError):
    pass


def _required(env: Mapping[str, str], name: str) -> str:
    value = env.get(name, "").strip()
    if not value:
        raise MachineConfigError(f"Missing required environment variable: {name}")
    return value


@dataclass(frozen=True, repr=False)
class MachineSettings:
    tuya_endpoint: str
    tuya_access_id: str
    tuya_access_secret: str
    sf_app_key: str
    central_kitchen_base_url: str
    allowed_machine_numbers: frozenset[str]

    @classmethod
    def from_mapping(cls, env: Mapping[str, str]) -> "MachineSettings":
        allowed = frozenset(
            part.strip().zfill(3)
            for part in env.get("ALLOWED_MACHINE_NUMBERS", "041").split(",")
            if part.strip()
        )
        if allowed != frozenset({"041"}):
            raise MachineConfigError("ALLOWED_MACHINE_NUMBERS must be exactly 041")
        return cls(
            tuya_endpoint=_required(env, "TUYA_MCP_ENDPOINT"),
            tuya_access_id=_required(env, "TUYA_MCP_ACCESS_ID"),
            tuya_access_secret=_required(env, "TUYA_MCP_ACCESS_SECRET"),
            sf_app_key=_required(env, "SF_APP_KEY"),
            central_kitchen_base_url=env.get(
                "CENTRAL_KITCHEN_BASE_URL",
                "https://inventory-api.example.com/api",
            ).rstrip("/"),
            allowed_machine_numbers=allowed,
        )

    @classmethod
    def from_env(cls) -> "MachineSettings":
        return cls.from_mapping(os.environ)

    def __repr__(self) -> str:
        return (
            "MachineSettings(tuya_endpoint=<configured>, "
            "tuya_access_id=<redacted>, tuya_access_secret=<redacted>, "
            "sf_app_key=<redacted>, central_kitchen_base_url=<configured>, "
            f"allowed_machine_numbers={self.allowed_machine_numbers!r})"
        )
