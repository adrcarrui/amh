from __future__ import annotations

import os

from smartcard.Exceptions import CardConnectionException, NoCardException
from smartcard.System import readers


GET_UID_APDU = [0xFF, 0xCA, 0x00, 0x00, 0x00]


class ReaderError(Exception):
    pass


def list_readers() -> list[str]:
    return [str(reader) for reader in readers()]


def _select_reader():
    available = list(readers())
    configured_name = os.environ.get("AMH_NFC_READER_NAME")

    if configured_name:
        matches = [
            reader
            for reader in available
            if str(reader) == configured_name
        ]
    else:
        matches = [
            reader
            for reader in available
            if "ACR122" in str(reader).upper()
        ]

    if len(matches) != 1:
        raise ReaderError(
            f"Se esperaba un único ACR122U; encontrados: {len(matches)}. "
            "Configura AMH_NFC_READER_NAME si hay varios lectores."
        )

    return matches[0]


def read_uid_once() -> str | None:
    """Lee una tarjeta presente. Devuelve None si no hay tarjeta."""
    reader = _select_reader()
    connection = None

    try:
        connection = reader.createConnection()
        connection.connect()

        data, sw1, sw2 = connection.transmit(GET_UID_APDU)
        if (sw1, sw2) != (0x90, 0x00):
            raise ReaderError(
                f"El lector rechazó GET UID: {sw1:02X} {sw2:02X}"
            )

        if not data:
            raise ReaderError("El lector devolvió un UID vacío")

        return "".join(f"{byte:02X}" for byte in data)

    except NoCardException:
        return None
    except CardConnectionException as exc:
        raise ReaderError("Error de conexión con la tarjeta") from exc
    finally:
        if connection is not None:
            try:
                connection.disconnect()
            except Exception:
                pass