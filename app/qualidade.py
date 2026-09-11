"""Portao de qualidade: nada sobe enquanto lint, formato e tipagem nao passarem.

Roda uma vez por processo, no import do pacote `app` (ver `app/__init__.py`),
entao vale igual pro CLI, pra API e pros scripts - nenhum deles precisa lembrar
de chamar. Com o cache do ruff e do ty quente sao ~0,3s.

Nao ha variavel de ambiente pra desligar: o jeito de fazer o programa subir e
deixar o codigo limpo.
"""

import subprocess
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

RAIZ = Path(__file__).resolve().parent.parent

# Rodados pelo interpretador do proprio venv (`-m`), nao pelo que estiver no
# PATH: e o unico que enxerga as versoes travadas no uv.lock.
VERIFICACOES = (
    ("lint", [sys.executable, "-m", "ruff", "check", "."]),
    ("formato", [sys.executable, "-m", "ruff", "format", "--check", "."]),
    ("tipagem", [sys.executable, "-m", "ty", "check"]),
)

_RECADO_DE_INSTALACAO = (
    "As ferramentas de verificacao nao estao instaladas neste ambiente.\n"
    "Rode 'uv sync' pra instalar o grupo dev (ruff e ty)."
)


def _falhas() -> list[tuple[str, str]]:
    falhas: list[tuple[str, str]] = []
    for nome, comando in VERIFICACOES:
        resultado = subprocess.run(  # noqa: S603 - comando fixo, sem entrada de fora
            comando, cwd=RAIZ, capture_output=True, text=True, check=False
        )
        if resultado.returncode != 0:
            falhas.append((nome, f"{resultado.stdout}{resultado.stderr}".strip()))
    return falhas


def garantir_codigo_limpo() -> None:
    """Interrompe a execucao quando alguma verificacao reprova.

    Fora da arvore de codigo (instalacao empacotada, sem `pyproject.toml` do
    lado) nao ha o que verificar e a checagem e pulada.
    """
    if not (RAIZ / "pyproject.toml").is_file():
        return

    falhas = _falhas()
    if not falhas:
        return

    console = Console(stderr=True)
    corpo = []
    for nome, saida in falhas:
        corpo.append(f"[bold]{nome}[/]")
        corpo.append(saida or "(sem detalhe)")
        if "No module named" in saida:
            corpo.append(_RECADO_DE_INSTALACAO)
        corpo.append("")
    corpo.append("[dim]Corrija o que esta acima e rode de novo.[/]")
    console.print(
        Panel(
            "\n".join(corpo).strip(),
            title="A aplicacao nao subiu: codigo reprovado nas verificacoes",
            border_style="red",
        )
    )
    raise SystemExit(1)
