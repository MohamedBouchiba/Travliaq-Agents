"""Configuration centralisée de l'application."""

from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration de l'application."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

    # Supabase
    supabase_url: Optional[str] = None
    supabase_service_role_key: Optional[str] = None

    # PostgreSQL Direct
    pg_host: Optional[str] = None
    pg_database: Optional[str] = None
    pg_user: Optional[str] = None
    pg_password: Optional[str] = None
    pg_port: int = 5432
    pg_sslmode: str = "require"

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_reload: bool = True
    api_workers: int = 1

    # Règles de flux
    has_destination: str = "no"
    only_flights: str = "no"
    dates_type: str = "flexible"
    budget_precise: str = "no"

    # LLM API Keys & Providers
    model_provider: str = "openai"
    model_name: str = "gpt-4o-mini"
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    groq_api_key: Optional[str] = None
    azure_openai_api_key: Optional[str] = None
    azure_openai_endpoint: Optional[str] = None
    azure_openai_api_version: Optional[str] = None
    azure_openai_deployment: Optional[str] = None

    # CrewAI
    max_rpm: int = 50
    temperature: float = 0.3
    max_iter: int = 5
    verbose: bool = True
    crew_output_dir: str = "output/crew_runs"

    # Logging
    log_level: str = "INFO"

    @property
    def pg_connection_string(self) -> str:
        """Génère la chaîne de connexion PostgreSQL."""
        if not all([self.pg_host, self.pg_database, self.pg_user, self.pg_password]):
            return ""
        return (
            f"host={self.pg_host} "
            f"dbname={self.pg_database} "
            f"user={self.pg_user} "
            f"password={self.pg_password} "
            f"port={self.pg_port} "
            f"sslmode={self.pg_sslmode} "
            f"target_session_attrs=read-write"
        )


# Instance globale
settings = Settings()
