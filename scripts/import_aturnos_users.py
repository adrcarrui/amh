import argparse
import csv
from collections import Counter
from getpass import getpass
from pathlib import Path
from uuid import UUID

import httpx
from sqlalchemy import select, text

from app.admin_routes import ManagedUserCreate
from app.authorization import has_application_access
from app.db import SessionLocal
from app.models import User, UserEmail, UserATurnosLink
from app.user_creation_service import create_managed_user


TEAM_ID = "15945"
ACTOR_ID = UUID("24307b6d-e337-49dd-986e-79e0fa775a7a")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--limit", type=int, default=1)
    args = parser.parse_args()

    if args.limit < 1:
        raise ValueError("--limit debe ser mayor que cero.")

    with args.csv_path.open(
        encoding="utf-8-sig", newline=""
    ) as file:
        reader = csv.DictReader(file, delimiter=";")
        required = {
            "id_aturno", "id_user", "name", "surname",
            "email", "username", "revisado",
        }
        if not required.issubset(reader.fieldnames or []):
            raise ValueError(
                "Columnas incorrectas. Conserva el CSV separado por punto y coma."
            )

        rows = [
            {key: (value or "").strip() for key, value in row.items()
             if key is not None}
            for row in reader
        ]

    selected = [
        row for row in rows
        if row.get("revisado", "").upper() == "SI"
    ]

    if not selected:
        print("No hay filas marcadas revisado=SI. No se realiza ningun alta.")
        return

    ids = Counter(row["id_user"] for row in selected)
    emails = Counter(row["email"].lower() for row in selected)

    # Valida todas las filas revisadas antes de cualquier alta.
    validated = []
    for row in selected:
        external_id = row["id_user"]

        if (
            row["id_aturno"] != TEAM_ID
            or not external_id.isascii()
            or not external_id.isdecimal()
            or int(external_id) <= 0
            or len(external_id) > 64
        ):
            raise ValueError("Equipo o identificador externo incorrecto.")

        if ids[external_id] != 1 or emails[row["email"].lower()] != 1:
            raise ValueError("Hay identificadores o correos repetidos en el CSV.")

        expected_username = f"aturnos_{TEAM_ID}_{external_id}"
        if row["username"] != expected_username:
            raise ValueError(
                f"Username modificado para el usuario {external_id}."
            )

        data = ManagedUserCreate(
            username=row["username"],
            name=row["name"],
            surname=row["surname"],
            email=row["email"],
        )
        validated.append((external_id, data))

    # Comprueba de nuevo los datos actuales de aTurnos.
    token = getpass("Token de acceso de aTurnos: ").strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()

    if not token or any(ord(c) < 33 or ord(c) > 126 for c in token):
        raise ValueError("Token no valido. Pegalo con clic derecho.")

    with httpx.Client(timeout=60.0) as client:
        response = client.get(
            f"https://www.aturnos.com/apirest/{TEAM_ID}/users",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
        )
        response.raise_for_status()
        payload = response.json()

    token = None
    page = payload.get("data")

    if (
        payload.get("status") is not True
        or not isinstance(page, dict)
        or not isinstance(page.get("data"), list)
        or len(page["data"]) != int(page["total"])
    ):
        raise RuntimeError("Respuesta de aTurnos incorrecta o incompleta.")

    source = {}
    for user in page["data"]:
        if (
            not isinstance(user, dict)
            or str(user.get("id_aturno")) != TEAM_ID
            or not user.get("id_user")
        ):
            raise RuntimeError("Registro inesperado en aTurnos.")

        external_id = str(user["id_user"])
        if external_id in source:
            raise RuntimeError("Identificador repetido en aTurnos.")
        source[external_id] = user

    pending = []
    already_linked = 0

    with SessionLocal.begin() as db:
        db.execute(text("SET TRANSACTION READ ONLY"))

        if db.scalar(text("SELECT current_database()")) != "amh_dev":
            raise RuntimeError("La conexion no apunta a amh_dev.")

        actor = db.get(User, ACTOR_ID)
        if (
            actor is None
            or actor.is_blocked
            or not has_application_access(
                db,
                user_id=ACTOR_ID,
                application_code="amh",
                minimum_role="admin",
            )
        ):
            raise PermissionError("Tu usuario no dispone de acceso admin AMH.")

        for external_id, data in validated:
            current = source.get(external_id)

            if current is None or str(current.get("active")) != "1":
                raise RuntimeError(
                    f"{external_id}: ya no aparece como activo en aTurnos."
                )

            if (
                str(current.get("email") or "").strip().lower()
                != data.email.lower()
            ):
                raise RuntimeError(
                    f"{external_id}: el correo no coincide con aTurnos."
                )

            link = db.scalar(
                select(UserATurnosLink).where(
                    UserATurnosLink.id_aturno == TEAM_ID,
                    UserATurnosLink.id_user == external_id,
                )
            )

            if link is not None:
                linked_email = db.scalar(
                    select(UserEmail.id).where(
                        UserEmail.user_id == link.user_id,
                        UserEmail.email_normalized == data.email.lower(),
                    )
                )
                if linked_email is None:
                    raise RuntimeError(
                        f"{external_id}: enlace existente con otro correo."
                    )
                already_linked += 1
                continue

            existing_email = db.scalar(
                select(UserEmail.id).where(
                    UserEmail.email_normalized == data.email.lower()
                )
            )
            if existing_email is not None:
                raise RuntimeError(
                    f"{external_id}: correo existente sin enlace. "
                    "Requiere revision."
                )

            pending.append((external_id, data))

    batch = pending[:args.limit]

    print(f"\nFilas revisadas: {len(validated)}")
    print(f"Ya enlazadas: {already_linked}")
    print(f"Pendientes: {len(pending)}")
    print(f"Usuarios de este lote: {len(batch)}")

    for external_id, data in batch:
        print(f"[LOTE] {external_id} | {data.name} | {data.surname}")

    if not args.apply:
        print("\nSIMULACION: no se ha modificado ningun sistema.")
        return

    created = 0
    for external_id, data in batch:
        # Cada usuario se confirma por separado.
        # Si falla, se detiene el lote.
        user_id, temporary_password = create_managed_user(
            actor_user_id=ACTOR_ID,
            username=data.username,
            name=data.name,
            surname=data.surname,
            email=data.email,
            aturnos_team_id=TEAM_ID,
            aturnos_user_id=external_id,
        )
        created += 1

        print(f"\n[CREADO] {external_id} -> AMH {user_id}")
        print(f"Usuario Keycloak: {data.username}")
        print(f"Contrasena temporal: {temporary_password}")
        temporary_password = None

    print(f"\nAltas completadas en este lote: {created}")
    print("No se han concedido permisos de aplicacion.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"\nERROR: {exc}")
        print(
            "Ejecucion detenida. Las altas ya confirmadas permanecen. "
            "Si el error indica un resultado incierto, revisalo antes de reintentar."
        )
        raise SystemExit(1)