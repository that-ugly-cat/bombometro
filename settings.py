"""Explicit deployment modes; public access is a deliberate operator setting."""

import os
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    mode: str = "lab"
    public_host: str = ""
    revision: str = "workshop"

    @classmethod
    def from_env(cls):
        mode = os.getenv("APP_MODE", "lab")
        host = os.getenv("PUBLIC_HOST", "").lower()
        revision = os.getenv("APP_REVISION", "workshop")
        if mode not in {"lab", "public"}:
            raise ValueError("APP_MODE must be lab or public")
        if mode == "public":
            if not valid_host(host):
                raise ValueError("PUBLIC_HOST must be one DNS hostname, without scheme, path or port")
            if not re.fullmatch(r"[0-9a-f]{40}", revision):
                raise ValueError("Public mode requires APP_REVISION as a full reviewed Git commit")
        return cls(mode, host, revision)


def valid_host(value):
    return bool(len(value) <= 253 and re.fullmatch(
        r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+", value))
