"""Correções nossas aplicadas ao clone do Card Conjurer.

O gerador vem de `app.vendor.repo` e fica fora do controle de versão, então
correção escrita direto no arquivo dele sumiria no clone seguinte e não
chegaria em outra máquina. Os patches ficam versionados em
`patches/cardconjurer/` e o setup aplica depois do clone.

Cada patch deixa no código a marca `script-magic-maker: <nome>`. É por ela que
`pendentes()` sabe se o clone está corrigido sem chamar o git — o alvo e a
marca saem do próprio arquivo de patch, não de uma lista mantida aqui.
"""

import re
import shutil
import subprocess
from pathlib import Path

from app.config import CARDCONJURER_DIR
from app.errors import BadRequestError

PASTA_DE_PATCHES = Path(__file__).resolve().parents[2] / "patches" / "cardconjurer"

_MARCA = re.compile(r"script-magic-maker:\s*([a-z0-9-]+)")
_ARQUIVO_ALVO = re.compile(r"^\+\+\+ b/(.+)$", re.MULTILINE)


def listar() -> list[Path]:
    """Os patches na ordem em que devem ser aplicados (nome numerado)."""
    if not PASTA_DE_PATCHES.is_dir():
        return []
    return sorted(PASTA_DE_PATCHES.glob("*.patch"))


def _alvos_e_marcas(patch: Path) -> tuple[list[Path], set[str]]:
    texto = patch.read_text(encoding="utf-8")
    alvos = [Path(caminho.strip()) for caminho in _ARQUIVO_ALVO.findall(texto)]
    marcas = {
        nome
        for linha in texto.splitlines()
        if linha.startswith("+")
        for nome in _MARCA.findall(linha)
    }
    return alvos, marcas


def _ja_aplicado(patch: Path, raiz: Path) -> bool:
    alvos, marcas = _alvos_e_marcas(patch)
    if not marcas:
        raise BadRequestError(
            f"{patch.name} não deixa marca 'script-magic-maker: <nome>' no código; "
            "sem ela não dá pra saber se o clone já está corrigido."
        )
    presentes: set[str] = set()
    for alvo in alvos:
        arquivo = raiz / alvo
        if not arquivo.is_file():
            continue
        conteudo = arquivo.read_text(encoding="utf-8", errors="replace")
        presentes |= {marca for marca in marcas if f"script-magic-maker: {marca}" in conteudo}
    return marcas <= presentes


def pendentes(diretorio: Path | None = None) -> list[Path]:
    """Os patches que ainda não estão no clone."""
    raiz = diretorio or CARDCONJURER_DIR
    return [patch for patch in listar() if not _ja_aplicado(patch, raiz)]


def aplicar(diretorio: Path | None = None) -> list[Path]:
    """Aplica no clone os patches que faltam. Devolve os que foram aplicados.

    Falha alto: patch que não aplica significa que o upstream mexeu no trecho,
    e seguir sem ele geraria carta errada em silêncio.
    """
    raiz = diretorio or CARDCONJURER_DIR
    faltando = pendentes(raiz)
    if not faltando:
        return []

    if shutil.which("git") is None:
        raise BadRequestError("git não encontrado no PATH; ele é necessário pros patches.")

    aplicados = []
    for patch in faltando:
        resultado = subprocess.run(
            ["git", "apply", "--whitespace=nowarn", str(patch)],
            cwd=raiz,
            capture_output=True,
            text=True,
        )
        if resultado.returncode != 0:
            raise BadRequestError(
                f"O patch {patch.name} não aplicou no Card Conjurer "
                f"(git saiu com {resultado.returncode}): {resultado.stderr.strip()}. "
                "O upstream provavelmente mexeu no trecho; refaça o patch."
            )
        aplicados.append(patch)
    return aplicados
