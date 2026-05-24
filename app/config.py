from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )

    host: str = "0.0.0.0"
    port: int = 8000
    # Stored as a raw comma-separated string; pydantic-settings v2 tries to
    # JSON-decode list[str] env vars before validators run, so we keep it as
    # str and expose the parsed version via a computed field.
    allowed_origins: str = "http://localhost:5173"

    # Firebase credentials — one of the two must be set:
    #   - FIREBASE_SERVICE_ACCOUNT_PATH  → ruta a un fichero JSON (desarrollo local)
    #   - FIREBASE_SERVICE_ACCOUNT_JSON  → contenido JSON en crudo (producción / Render)
    firebase_service_account_path: str = ""
    firebase_service_account_json: str = ""

    @computed_field  # type: ignore[misc]
    @property
    def allowed_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]


settings = Settings()
