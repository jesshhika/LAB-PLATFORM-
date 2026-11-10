import base64
import ipaddress
import json
import os
from datetime import UTC, datetime, timedelta

from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from fastapi import HTTPException

from api.app.core.config import get_settings


def encrypt_guac_token(payload: dict[str, object], key: str) -> str:
    key_bytes = key.encode("utf-8")
    if len(key_bytes) != 32:
        raise ValueError("GUAC_CRYPT_KEY must be exactly 32 UTF-8 bytes.")

    iv = os.urandom(16)
    padder = padding.PKCS7(algorithms.AES.block_size).padder()
    padded = padder.update(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    padded += padder.finalize()

    encryptor = Cipher(algorithms.AES(key_bytes), modes.CBC(iv)).encryptor()
    ciphertext = encryptor.update(padded) + encryptor.finalize()
    envelope = {
        "iv": base64.b64encode(iv).decode("ascii"),
        "value": base64.b64encode(ciphertext).decode("ascii"),
    }
    return base64.b64encode(json.dumps(envelope, separators=(",", ":")).encode("utf-8")).decode(
        "ascii"
    )


def require_private_ip(value: str) -> str:
    try:
        address = ipaddress.ip_address(value)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail="The lab VM has no valid private IP.") from exc
    if not (
        isinstance(address, ipaddress.IPv4Address)
        and any(
            address in network
            for network in (
                ipaddress.ip_network("10.0.0.0/8"),
                ipaddress.ip_network("172.16.0.0/12"),
                ipaddress.ip_network("192.168.0.0/16"),
            )
        )
    ):
        raise HTTPException(status_code=409, detail="The lab VM must have a private IP.")
    return str(address)


def read_key_vault_secret(secret_name: str | None) -> str:
    settings = get_settings()
    if not settings.key_vault_url or not secret_name:
        raise HTTPException(status_code=503, detail="Session credentials are not configured.")
    credential = DefaultAzureCredential(exclude_interactive_browser_credential=True)
    try:
        client = SecretClient(vault_url=settings.key_vault_url, credential=credential)
        return client.get_secret(secret_name).value or ""
    finally:
        credential.close()


def build_connection_token(
    *,
    session_id: str,
    host: str,
    username: str,
    password: str,
    key: str,
    now: datetime | None = None,
    read_only: bool = False,
) -> tuple[str, datetime]:
    expires_at = (now or datetime.now(UTC)) + timedelta(minutes=2)
    payload: dict[str, object] = {
        "expiration": int(expires_at.timestamp() * 1000),
        "session_id": session_id,
        "connection": {
            "type": "rdp",
            "settings": {
                "hostname": require_private_ip(host),
                "port": "3389",
                "username": username,
                "password": password,
                "security": "nla",
                "ignore-cert": True,
                "enable-wallpaper": False,
                "resize-method": "display-update",
                "enable-drive": False,
                "disable-copy": False,
                "disable-input": True if read_only else False,
            },
        }
    }
    return encrypt_guac_token(payload, key), expires_at
