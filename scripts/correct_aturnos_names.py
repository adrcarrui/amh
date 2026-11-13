import argparse
from uuid import UUID

import httpx
from sqlalchemy import select, text

from app.db import SessionLocal
from app.keycloak_admin import _service_token, _users_url
from app.models import User, UserATurnosLink


TEAM_ID = "15945"

CORRECTIONS = [
    (
        "656106",
        ("Pedro", "Nolasco Patón Ruiz"),
        ("Pedro Nolasco", "Patón Ruiz"),
    ),
    (
        "59131",
        ("Juan", "Carlos Perez Chamorro"),
        ("Juan Carlos", "Perez Chamorro"),
    ),
    (
        "291931",
        ("José", "Joaquín Villalón"),
        ("José Joaquín", "Villalón"),
    ),
]


def get_user(db, external_id):
    user = db.scalar(
        select(User)
        .join(
            UserATurnosLink,
            UserATurnosLink.user_id == User.id,
        )
        .where(
            UserATurnosLink.id_aturno == TEAM_ID,
            UserATurnosLink.id_user == external_id,
        )
        .with_for_update(of=User)
    )

    if user is None or not user.keycloak_subject:
        raise RuntimeError(
            f"{external_id}: falta usuario AMH o identidad Keycloak."
        )

    # Valida el identificador antes de construir la URL.
    UUID(user.keycloak_subject)
    return user


def check_names(actual, old, new, system, external_id):
    if actual not in (old, new):
        raise RuntimeError(
            f"{external_id}: nombres inesperados en {system}: {actual!r}"
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    with SessionLocal() as db:
        if db.scalar(text("SELECT current_database()")) != "amh_dev":
            raise RuntimeError("La conexion no apunta a amh_dev.")

    with httpx.Client(timeout=10.0, trust_env=False) as client:
        token = _service_token(client)
        headers = {"Authorization": f"Bearer {token}"}

        # Comprueba los tres casos antes de empezar a modificar.
        for external_id, old, new in CORRECTIONS:
            with SessionLocal.begin() as db:
                user = get_user(db, external_id)
                check_names(
                    (user.name, user.surname),
                    old, new, "AMH", external_id,
                )

                url = f"{_users_url()}/{user.keycloak_subject}"
                response = client.get(url, headers=headers)
                response.raise_for_status()
                profile = response.json()

                check_names(
                    (profile.get("firstName"), profile.get("lastName")),
                    old, new, "Keycloak", external_id,
                )

                print(
                    f"[PROPUESTA] {external_id}: "
                    f"{user.name} / {user.surname} "
                    f"-> {new[0]} / {new[1]}"
                )

        if not args.apply:
            print("\nSIMULACION: no se han guardado cambios.")
            return

        for external_id, old, new in CORRECTIONS:
            with SessionLocal.begin() as db:
                user = get_user(db, external_id)
                check_names(
                    (user.name, user.surname),
                    old, new, "AMH", external_id,
                )

                url = f"{_users_url()}/{user.keycloak_subject}"
                response = client.get(url, headers=headers)
                response.raise_for_status()
                profile = response.json()

                current = (
                    profile.get("firstName"),
                    profile.get("lastName"),
                )
                check_names(
                    current, old, new, "Keycloak", external_id,
                )

                if current != new:
                    # Conserva los demas datos del perfil.
                    profile.pop("access", None)
                    profile["firstName"] = new[0]
                    profile["lastName"] = new[1]

                    response = client.put(
                        url,
                        headers=headers,
                        json=profile,
                    )
                    response.raise_for_status()

                    verification = client.get(url, headers=headers)
                    verification.raise_for_status()
                    saved = verification.json()

                    if (
                        saved.get("firstName"),
                        saved.get("lastName"),
                    ) != new:
                        raise RuntimeError(
                            f"{external_id}: Keycloak no refleja la correccion."
                        )

                user.name = new[0]
                user.surname = new[1]
                db.flush()

            print(f"[CORREGIDO] {external_id}: {new[0]} / {new[1]}")

        print("\nLos tres usuarios coinciden en AMH y Keycloak.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"\nERROR: {exc}")
        print(
            "AMH y Keycloak se actualizan por separado. "
            "Puede haber correcciones parciales; el script admite "
            "repetir la ejecucion con los valores anteriores o corregidos."
        )
        raise SystemExit(1)