from uuid import UUID

from sqlalchemy import or_, select, text

from app.db import SessionLocal
from app.models import User, UserEmail, UserATurnosLink


TEAM_ID = "15945"

LINKS = [
    {
        "external_id": "900632",
        "amh_id": "24307b6d-e337-49dd-986e-79e0fa775a7a",
        "email": "adrian.cardonaruiz@atexis.com",
    },
    {
        "external_id": "554213",
        "amh_id": "55ea5fbe-bb64-4735-91d9-8584c241b180",
        "email": "rafael.rivera@atexis.com",
    },
    {
        "external_id": "814303",
        "amh_id": "66795c82-cdbb-4457-a7ad-a7e66b0717b4",
        "email": "carlos.domingueznicolas@atexis.com",
    },
    {
        "external_id": "932836",
        "amh_id": "da64398d-8b55-41ca-b99a-2372bbe12f5c",
        "email": "carlos.mejias@atexis.com",
    },
]


def main():
    messages = []
    created = 0
    existing = 0

    # Las cuatro operaciones se confirman juntas.
    # Cualquier error revierte todos los enlaces de esta ejecucion.
    with SessionLocal.begin() as db:
        database = db.scalar(text("SELECT current_database()"))
        if database != "amh_dev":
            raise RuntimeError(
                f"Se esperaba amh_dev; conexion detectada: {database}"
            )

        for item in LINKS:
            amh_id = UUID(item["amh_id"])

            user = db.scalar(
                select(User)
                .where(User.id == amh_id)
                .with_for_update()
            )

            if user is None:
                raise RuntimeError(
                    f"No existe el usuario AMH {amh_id}"
                )

            if user.is_blocked:
                raise RuntimeError(
                    f"El usuario {user.name} {user.surname} esta bloqueado."
                )

            email = db.scalar(
                select(UserEmail).where(
                    UserEmail.user_id == amh_id,
                    UserEmail.email_normalized == item["email"],
                )
            )

            if email is None:
                raise RuntimeError(
                    f"El correo esperado no coincide para {amh_id}."
                )

            links = db.scalars(
                select(UserATurnosLink).where(
                    UserATurnosLink.id_aturno == TEAM_ID,
                    or_(
                        UserATurnosLink.id_user == item["external_id"],
                        UserATurnosLink.user_id == amh_id,
                    ),
                )
            ).all()

            if links:
                if len(links) != 1 or (
                    links[0].user_id != amh_id
                    or links[0].id_user != item["external_id"]
                ):
                    raise RuntimeError(
                        f"Existe un enlace incompatible para "
                        f"{user.name} {user.surname}."
                    )

                existing += 1
                status = "YA EXISTIA"
            else:
                db.add(
                    UserATurnosLink(
                        user_id=amh_id,
                        id_aturno=TEAM_ID,
                        id_user=item["external_id"],
                    )
                )
                db.flush()
                created += 1
                status = "CREADO"

            messages.append(
                f"[{status}] {item['external_id']} -> "
                f"{user.name} {user.surname}"
            )

    # Solo se informa de exito despues de confirmar la transaccion.
    for message in messages:
        print(message)

    print(f"\nEnlaces creados: {created}")
    print(f"Enlaces que ya existian: {existing}")
    print("No se han creado usuarios ni modificado permisos o Keycloak.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"\nERROR: {exc}")
        print("No se han guardado cambios de esta ejecucion.")
        raise SystemExit(1)