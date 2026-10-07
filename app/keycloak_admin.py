from urllib.parse import quote
import httpx
from app.config import settings
from urllib.parse import urlsplit
from uuid import UUID

def _users_url() -> str:
    issuer = settings.amh_oidc_issuer.rstrip("/")

    if "/realms/" not in issuer:
        raise RuntimeError("AMH_OIDC_ISSUER no identifica un realm")

    server_base, realm = issuer.rsplit("/realms/", 1)
    if not server_base or not realm or "/" in realm:
        raise RuntimeError("AMH_OIDC_ISSUER no identifica un realm válido")

    return f"{server_base}/admin/realms/{quote(realm, safe='')}/users"


def _service_token(client: httpx.Client) -> str:
    issuer = settings.amh_oidc_issuer.rstrip("/")

    response = client.post(
        f"{issuer}/protocol/openid-connect/token",
        data={
            "grant_type": "client_credentials",
            "client_id": settings.amh_keycloak_admin_client_id,
            "client_secret": (
                settings.amh_keycloak_admin_client_secret.get_secret_value()
            ),
        },
    )

    if response.status_code != 200:
        raise RuntimeError(
            f"Keycloak rechazó la cuenta de servicio: HTTP {response.status_code}"
        )

    token = response.json().get("access_token")
    if not isinstance(token, str) or not token:
        raise RuntimeError("Keycloak no devolvió un access token")

    return token


def check_user_admin_access() -> None:
    """Comprueba credenciales y permiso de consulta, sin crear usuarios."""
    with httpx.Client(timeout=5.0, trust_env=False) as client:
        token = _service_token(client)

        response = client.get(
            _users_url(),
            params={"max": 1},
            headers={"Authorization": f"Bearer {token}"},
        )

        if response.status_code != 200:
            raise RuntimeError(
                "La cuenta de servicio no puede consultar usuarios: "
                f"HTTP {response.status_code}"
            )

def create_keycloak_user(
    *,
    username: str,
    name: str,
    surname: str,
    email: str,
    temporary_password: str,
) -> UUID:
    """Crea un usuario con contraseña temporal y devuelve su ID de Keycloak."""
    with httpx.Client(timeout=5.0, trust_env=False) as client:
        token = _service_token(client)
        users_url = _users_url()

        response = client.post(
            users_url,
            headers={"Authorization": f"Bearer {token}"},
            json={
                "username": username,
                "firstName": name,
                "lastName": surname,
                "email": email,
                "emailVerified": False,
                "enabled": True,
                "credentials": [
                    {
                        "type": "password",
                        "value": temporary_password,
                        "temporary": True,
                    }
                ],
            },
        )

        if response.status_code == 409:
            raise ValueError(
                "El usuario o el email ya existe en Keycloak"
            )
        if response.status_code != 201:
            raise RuntimeError(
                f"Keycloak no creó el usuario: HTTP {response.status_code}"
            )

        location = response.headers.get("Location")
        expected_prefix = urlsplit(users_url).path.rstrip("/") + "/"

        if not location:
            raise RuntimeError(
                "Keycloak creó el usuario pero no devolvió su identificador"
            )

        path = urlsplit(location).path
        if not path.startswith(expected_prefix):
            raise RuntimeError(
                "Keycloak devolvió una ubicación de usuario inesperada"
            )

        user_id_text = path[len(expected_prefix):]
        try:
            return UUID(user_id_text)
        except ValueError as exc:
            raise RuntimeError(
                "Keycloak devolvió un identificador de usuario no válido"
            ) from exc

def delete_newly_created_keycloak_user(user_id: UUID) -> None:
    """Se usa solo para deshacer un alta recién creada que falló en AMH."""
    with httpx.Client(timeout=5.0, trust_env=False) as client:
        token = _service_token(client)

        response = client.delete(
            f"{_users_url()}/{user_id}",
            headers={"Authorization": f"Bearer {token}"},
        )

        if response.status_code not in (204, 404):
            raise RuntimeError(
                "No se pudo deshacer el alta en Keycloak: "
                f"HTTP {response.status_code}; usuario {user_id}"
            )