import csv
from collections import Counter
from datetime import datetime
from getpass import getpass
from pathlib import Path

import httpx
from sqlalchemy import select, text

from app.db import SessionLocal
from app.models import UserEmail, UserATurnosLink


TEAM_ID = "15945"


def main():
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

    if payload.get("status") is not True:
        raise RuntimeError("aTurnos no indica una consulta correcta.")

    page = payload.get("data")
    if not isinstance(page, dict) or not isinstance(page.get("data"), list):
        raise RuntimeError("Respuesta de aTurnos inesperada.")

    users = page["data"]

    if len(users) != int(page["total"]):
        raise RuntimeError(
            "La respuesta esta paginada o incompleta. "
            "No se genera una propuesta parcial."
        )

    if any(
        not isinstance(user, dict)
        or str(user.get("id_aturno")) != TEAM_ID
        or not user.get("id_user")
        for user in users
    ):
        raise RuntimeError("Hay usuarios sin ID o de otro equipo.")

    id_counts = Counter(str(user["id_user"]) for user in users)
    email_counts = Counter(
        str(user.get("email") or "").strip().lower()
        for user in users
    )

    with SessionLocal.begin() as db:
        db.execute(text("SET TRANSACTION READ ONLY"))

        if db.scalar(text("SELECT current_database()")) != "amh_dev":
            raise RuntimeError("La conexion no apunta a amh_dev.")

        linked_ids = set(
            db.scalars(
                select(UserATurnosLink.id_user).where(
                    UserATurnosLink.id_aturno == TEAM_ID
                )
            ).all()
        )

        known_emails = set(
            db.scalars(select(UserEmail.email_normalized)).all()
        )

    candidates = []
    summary = Counter()

    for user in users:
        external_id = str(user["id_user"])
        email = str(user.get("email") or "").strip().lower()
        original_name = str(user.get("username") or "").strip()

        if str(user.get("active")) != "1":
            summary["inactivos"] += 1
            continue

        if external_id in linked_ids:
            summary["enlazados"] += 1
            continue

        if email in known_emails:
            summary["correo_existente"] += 1
            print(f"[REVISAR] {external_id}: correo ya presente en AMH")
            continue

        if (
            id_counts[external_id] != 1
            or not original_name
            or len(email) > 320
            or email.count("@") != 1
            or "." not in email.rsplit("@", 1)[-1]
            or any(c.isspace() for c in email)
            or email.endswith("@aturnos.com")
            or email_counts[email] != 1
        ):
            summary["otros_conflictos"] += 1
            print(f"[REVISAR] {external_id}: datos incompletos o conflictivos")
            continue

        # Propuesta editable, no una separacion definitiva.
        parts = original_name.split(maxsplit=1)
        name = parts[0]
        surname = parts[1] if len(parts) == 2 else ""

        candidates.append(
            {
                "id_aturno": TEAM_ID,
                "id_user": external_id,
                "nombre_original": original_name,
                "name": name,
                "surname": surname,
                "email": email,
                "username": f"aturnos_{TEAM_ID}_{external_id}",
                "revisado": "NO",
            }
        )

    output = (
        Path(__file__).resolve().parent
        / (
            "aturnos_propuesta_"
            + datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            + ".csv"
        )
    )

    with output.open("x", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "id_aturno",
                "id_user",
                "nombre_original",
                "name",
                "surname",
                "email",
                "username",
                "revisado",
            ],
            delimiter=";",
        )
        writer.writeheader()
        writer.writerows(candidates)

    print(f"\nYa enlazados: {summary['enlazados']}")
    print(f"Inactivos excluidos: {summary['inactivos']}")
    print(f"Correos existentes sin enlace: {summary['correo_existente']}")
    print(f"Otros conflictos: {summary['otros_conflictos']}")
    print(f"Candidatos preparados: {len(candidates)}")
    print(f"\nArchivo: {output}")
    print("\nNo se han modificado AMH, Keycloak ni aTurnos.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"\nERROR: {exc}")
        raise SystemExit(1)