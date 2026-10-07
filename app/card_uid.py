import hashlib
import hmac
import re


def normalize_uid(raw_uid: str) -> str:
    if not isinstance(raw_uid, str):
        raise ValueError("UID inválido")

    # Solo se admiten espacios ASCII, tabulaciones, saltos de línea,
    # dos puntos y guiones como separadores.
    uid = re.sub(r"[ \t\r\n:\-]", "", raw_uid).upper()

    # Entre 4 y 10 bytes completos, representados en hexadecimal.
    if (
        len(uid) < 8
        or len(uid) > 20
        or len(uid) % 2 != 0
        or re.fullmatch(r"[0-9A-F]+", uid) is None
    ):
        raise ValueError("UID inválido")

    return uid


def uid_hmac(raw_uid: str, key: bytes) -> str:
    if not isinstance(key, bytes) or len(key) < 32:
        raise ValueError("La clave HMAC debe tener al menos 32 bytes")

    uid_bytes = bytes.fromhex(normalize_uid(raw_uid))
    message = b"AMH:NFC-UID:v1:" + uid_bytes
    return hmac.new(key, message, hashlib.sha256).hexdigest()