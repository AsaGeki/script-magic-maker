"""Ciclo de vida do fork do Card Conjurer.

O gerador é um aplicativo estático que roda local. Este módulo cuida de trazer
o repositório pro disco e conferir se o que chegou está inteiro.

São ~2,7 GB, quase tudo moldura em `img/frames` — por isso `vendor/` fica fora
do controle de versão e o clone é raso.
"""

import shutil
import subprocess
from pathlib import Path

from app.config import CARDCONJURER_DIR
from app.errors import BadRequestError, NotFoundError

REPOSITORIO = "https://github.com/Investigamer/cardconjurer.git"
BRANCH = "master"

# Se estes existem, o clone veio inteiro: o formulário e o motor de layout.
ARQUIVOS_ESSENCIAIS = (
    Path("creator/index.html"),
    Path("js/creator-23.js"),
)


def esta_instalado(diretorio: Path | None = None) -> bool:
    """Se o fork está no disco e tem os arquivos que a automação usa."""
    raiz = diretorio or CARDCONJURER_DIR
    return all((raiz / arquivo).is_file() for arquivo in ARQUIVOS_ESSENCIAIS)


def clonar(diretorio: Path | None = None, profundidade: int = 1) -> Path:
    """Clona o fork. O histórico não interessa, então o clone é raso.

    A saída do git vai direto pro terminal — são vários gigabytes, e sem o
    progresso à vista parece que travou.
    """
    raiz = diretorio or CARDCONJURER_DIR
    if esta_instalado(raiz):
        return raiz

    if raiz.exists() and any(raiz.iterdir()):
        raise BadRequestError(
            f"{raiz} já existe e não parece um clone válido do Card Conjurer. "
            "Apague a pasta e rode o setup de novo."
        )

    if shutil.which("git") is None:
        raise BadRequestError("git não encontrado no PATH; ele é necessário pro setup.")

    raiz.parent.mkdir(parents=True, exist_ok=True)
    comando = [
        "git",
        "clone",
        "--branch",
        BRANCH,
        "--depth",
        str(profundidade),
        REPOSITORIO,
        str(raiz),
    ]
    resultado = subprocess.run(comando, check=False)
    if resultado.returncode != 0:
        raise BadRequestError(
            f"O clone do Card Conjurer falhou (git saiu com {resultado.returncode})."
        )
    if not esta_instalado(raiz):
        faltando = [str(a) for a in ARQUIVOS_ESSENCIAIS if not (raiz / a).is_file()]
        raise BadRequestError(
            f"O clone terminou mas faltam arquivos essenciais: {', '.join(faltando)}."
        )
    return raiz


def garantir_instalado(diretorio: Path | None = None) -> Path:
    """O caminho do fork, exigindo que o setup já tenha rodado."""
    raiz = diretorio or CARDCONJURER_DIR
    if not esta_instalado(raiz):
        raise NotFoundError(
            f"Card Conjurer nao encontrado em {raiz}. Rode 'uv run cli.py setup' primeiro"
        )
    return raiz


def tamanho_em_disco(diretorio: Path | None = None) -> int:
    """Bytes ocupados pelo clone. Só pra informar no CLI."""
    raiz = diretorio or CARDCONJURER_DIR
    if not raiz.exists():
        return 0
    return sum(f.stat().st_size for f in raiz.rglob("*") if f.is_file())
