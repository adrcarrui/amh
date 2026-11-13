from collections import Counter


def compare_users(users, links, emails):
    id_counts = Counter(str(user["id_user"]) for user in users)

    email_counts = Counter(
        str(user.get("email") or "").strip().lower()
        for user in users
    )

    seen = set()
    items = []

    for user in users:
        external_id = str(user["id_user"])
        seen.add(external_id)

        name = str(user.get("username") or "").strip()
        email = str(user.get("email") or "").strip().lower()
        linked = links.get(external_id)
        reasons = []

        if id_counts[external_id] > 1:
            reasons.append("ID repetido en aTurnos")

        if not name:
            reasons.append("Sin nombre")

        valid_email = (
            email.count("@") == 1
            and bool(email.split("@")[0])
            and "." in email.rsplit("@", 1)[-1]
            and len(email) <= 320
            and not any(char.isspace() for char in email)
        )

        if not valid_email:
            reasons.append("Correo ausente o no valido")
        elif email.endswith("@aturnos.com"):
            reasons.append("Revisar correo generado por aTurnos")

        if email and email_counts[email] > 1:
            reasons.append("Correo repetido en aTurnos")

        if linked is not None:
            primary_email = (
                linked["primary_email"] or ""
            ).strip().lower()

            if email != primary_email:
                reasons.append(
                    "Correo distinto al principal de AMH; "
                    "pendiente de revision"
                )

            if email in emails and emails[email] != linked["user_id"]:
                reasons.append(
                    "El correo pertenece a otro usuario AMH"
                )

        elif email in emails:
            reasons.append("Correo existente en AMH sin enlace")

        active = str(user.get("active"))

        if active == "0" and linked is not None:
            status = "review"
            reasons.insert(
                0,
                "Usuario enlazado que figura inactivo en aTurnos; "
                "revisar continuidad de acceso",
            )

        elif active == "0":
            status = "inactive"
            reasons.insert(0, "Usuario inactivo en aTurnos")

        elif active != "1":
            status = "review"
            reasons.insert(
                0,
                "Estado active desconocido en aTurnos",
            )

        elif reasons:
            status = "review"

        elif linked is not None:
            status = "linked"
            reasons.append("Identidad enlazada con AMH")

        else:
            status = "new"
            reasons.append(
                "Candidato a alta; revisar nombre y apellidos"
            )

        items.append(
            {
                "id_user": external_id,
                "name": name,
                "email": email or None,
                "status": status,
                "reason": "; ".join(reasons),
                "amh_user_id": (
                    str(linked["user_id"])
                    if linked is not None
                    else None
                ),
                "amh_primary_email": (
                    linked["primary_email"]
                    if linked is not None
                    else None
                ),
                "source_present": True,
            }
        )

    for external_id, linked in links.items():
        if external_id in seen:
            continue

        items.append(
            {
                "id_user": external_id,
                "name": linked["full_name"],
                "email": linked["primary_email"],
                "status": "review",
                "reason": (
                    "No aparece en la consulta actual de aTurnos. "
                    "Puede deberse a fechas o al alcance de la consulta; "
                    "no implica una baja confirmada."
                ),
                "amh_user_id": str(linked["user_id"]),
                "amh_primary_email": linked["primary_email"],
                "source_present": False,
            }
        )

    items.sort(
        key=lambda item: (
            item["name"].casefold(),
            item["id_user"],
        )
    )

    return items