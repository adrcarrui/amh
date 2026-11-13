from collections import Counter, defaultdict
from getpass import getpass

import httpx
from sqlalchemy import text

from app.db import engine


TEAM_ID = "15945"


def main():
    token = getpass("Token de acceso de aTurnos: ").strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()

    if not token or any(ord(char) < 33 or ord(char) > 126 for char in token):
        raise ValueError(
            "Token vacio o con caracteres no validos. "
            "Pegalo con clic derecho."
        )

    print(f"\nConsultando usuarios del equipo {TEAM_ID}...")

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
        raise RuntimeError("La respuesta no tiene la estructura esperada.")

    users = page["data"]
    total = int(page["total"])

    # Impide presentar una comparacion parcial como completa.
    if len(users) != total:
        raise RuntimeError(
            f"La API indica {total} usuarios, pero llegaron {len(users)}. "
            "Hay que incorporar paginacion antes de continuar."
        )

    if any(
        not isinstance(user, dict)
        or str(user.get("id_aturno")) != TEAM_ID
        or not user.get("id_user")
        for user in users
    ):
        raise RuntimeError("Hay registros sin identificador o de otro equipo.")

    # La transaccion de PostgreSQL solo permite lecturas.
    with engine.connect() as connection:
        with connection.begin():
            connection.execute(text("SET TRANSACTION READ ONLY"))

            database = connection.scalar(text("SELECT current_database()"))
            if database != "amh_dev":
                raise RuntimeError(
                    f"Se esperaba amh_dev; conexion detectada: {database}"
                )

            amh_user_count = connection.scalar(
                text("SELECT count(*) FROM users")
            )

            rows = connection.execute(
                text("""
                    SELECT
                        u.id,
                        u.name,
                        u.surname,
                        u.is_blocked,
                        e.email_normalized
                    FROM users AS u
                    JOIN user_emails AS e ON e.user_id = u.id
                """)
            ).mappings().all()

    by_email = defaultdict(dict)
    for row in rows:
        email = row["email_normalized"].strip().lower()
        by_email[email][str(row["id"])] = row

    email_counts = Counter(
        str(user.get("email") or "").strip().lower()
        for user in users
    )
    id_counts = Counter(str(user["id_user"]) for user in users)
    summary = Counter()

    print(f"\nBase AMH: {database}")
    print(f"Usuarios AMH: {amh_user_count}")
    print(f"Usuarios aTurnos recibidos: {len(users)}")
    print("\nRESULTADO DE LA COMPARACION\n")

    for user in users:
        external_id = str(user["id_user"])
        name = str(user.get("username") or "").strip()
        email = str(user.get("email") or "").strip().lower()
        matches = list(by_email.get(email, {}).values())

        reasons = []

        if id_counts[external_id] > 1:
            reasons.append("ID repetido en aTurnos")

        if str(user.get("active")) != "1":
            reasons.append("active distinto de 1")

        if not name:
            reasons.append("sin nombre")

        if not email or email.count("@") != 1 or any(
            char.isspace() for char in email
        ):
            reasons.append("correo ausente o formato a revisar")
        elif email.endswith("@aturnos.com"):
            reasons.append("revisar correo de aTurnos")

        if email and email_counts[email] > 1:
            reasons.append("correo repetido en aTurnos")

        if len(matches) > 1:
            reasons.append("correo asociado a varios usuarios AMH")

        if any(match["is_blocked"] for match in matches):
            reasons.append("usuario AMH bloqueado")

        if reasons:
            category = "REVISAR"
            detail = "; ".join(reasons)
        elif len(matches) == 1:
            category = "COINCIDENCIA"
            match = matches[0]
            detail = (
                f"AMH: {match['name']} {match['surname']} "
                f"({match['id']})"
            )
        else:
            category = "NUEVO"
            detail = "sin coincidencia por correo en AMH"

        summary[category] += 1
        print(f"[{category}] {external_id} | {name} | {detail}")

    print("\nRESUMEN")
    for category in ("COINCIDENCIA", "NUEVO", "REVISAR"):
        print(f"{category}: {summary[category]}")

    print("\nNo se han modificado AMH, Keycloak ni aTurnos.")
    print("Las coincidencias por correo son candidatas a revision.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"\nERROR: {exc}")
        raise SystemExit(1)