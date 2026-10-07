from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


PROJECT_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    amh_db_host: str
    amh_db_port: int = 5432
    amh_db_name: str
    amh_db_user: str
    amh_db_password: SecretStr
    amh_uid_hmac_key_hex: SecretStr
    amh_oidc_issuer: str
    amh_oidc_client_id: str
    amh_oidc_client_secret: SecretStr
    amh_oidc_redirect_uri: str
    amh_oidc_state_secret: SecretStr
    amh_api_client_id: str
    amh_api_client_secret: SecretStr
    amh_nfc_agent_token: SecretStr
    amh_nfc_mysim_client_token: SecretStr
    amh_keycloak_admin_client_id: str = "amh_user_admin_dev"
    amh_keycloak_admin_client_secret: SecretStr


    model_config = SettingsConfigDict(
        env_file=PROJECT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def database_url(self) -> URL:
        return URL.create(
            drivername="postgresql+psycopg",
            username=self.amh_db_user,
            password=self.amh_db_password.get_secret_value(),
            host=self.amh_db_host,
            port=self.amh_db_port,
            database=self.amh_db_name,
        )

    @property
    def uid_hmac_key(self) -> bytes:
        value = self.amh_uid_hmac_key_hex.get_secret_value()

        if len(value) != 64:
            raise ValueError("AMH_UID_HMAC_KEY_HEX debe contener 64 caracteres hexadecimales")

        try:
            return bytes.fromhex(value)
        except ValueError as exc:
            raise ValueError("AMH_UID_HMAC_KEY_HEX no es hexadecimal válido") from exc
        
settings = Settings()