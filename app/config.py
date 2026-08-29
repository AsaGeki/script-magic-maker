"""Leitura da configuração do .env.

Nenhuma variável é obrigatória — todas têm default. Os caminhos relativos são
resolvidos a partir da raiz do projeto, então funcionam de qualquer diretório.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Raiz do projeto: dois níveis acima deste arquivo (app/config.py).
RAIZ = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=RAIZ / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # API FastAPI de consulta.
    port: int = 8000

    # Onde as imagens geradas são salvas.
    output_dir: Path = Path("output")

    # false abre o navegador na tela, útil pra depurar a automação.
    headless: bool = True

    # Fork do Card Conjurer auto-hospedado.
    cardconjurer_dir: Path = Path("vendor/cardconjurer")
    cardconjurer_port: int = 4242

    # O Scryfall pede um User-Agent identificável.
    scryfall_user_agent: str = Field(default="script-magic-maker/0.1.0")

    @field_validator("output_dir", "cardconjurer_dir")
    @classmethod
    def _resolver_caminho(cls, valor: Path) -> Path:
        """Caminho relativo passa a valer a partir da raiz do projeto."""
        return valor if valor.is_absolute() else RAIZ / valor

    @property
    def cardconjurer_url(self) -> str:
        return f"http://127.0.0.1:{self.cardconjurer_port}"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
