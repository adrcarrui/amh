from authlib.integrations.starlette_client import OAuth

from app.config import settings


oauth = OAuth()

oauth.register(
    name="keycloak",
    client_id=settings.amh_oidc_client_id,
    client_secret=settings.amh_oidc_client_secret.get_secret_value(),
    server_metadata_url=(
        f"{settings.amh_oidc_issuer.rstrip('/')}"
        "/.well-known/openid-configuration"
    ),
    client_kwargs={
        "scope": "openid profile email",
        "code_challenge_method": "S256",
    },
)