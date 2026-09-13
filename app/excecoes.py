"""Correcoes a mao, por impressao, do que a regra automatica nao alcanca.

As regras do projeto fecham no geral; uma impressao ou outra nao fecha por
regra nenhuma - o gerador le "de qualquer cor" nas regras da Gemstone Caverns e
monta moldura dourada, a Prole Eldrazi tem o oracle da carta-mae discordando do
oracle dela. Aqui a impressao e corrigida a mao, uma de cada vez.

Cada entrada carrega o motivo, e sem ele o arquivo e recusado: lista curada
envelhece calada, e o motivo e o que deixa conferir depois se ela ainda faz
falta. Toda exceção aplicada sai no log.
"""

import logging
import tomllib
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

from app.cards.models import ScryfallCard
from app.config import RAIZ
from app.errors import BadRequestError

logger = logging.getLogger(__name__)

ARQUIVO = RAIZ / "excecoes.toml"

# Campo do arquivo -> campo do ScryfallCard que ele sobrescreve.
CAMPOS_DE_TEXTO = {
    "nome": "printed_name",
    "linha_de_tipo": "printed_type_line",
    "texto": "printed_text",
    "historia": "flavor_text",
}

# Campos do rodape, com o id do campo no gerador.
CAMPOS_DE_RODAPE = {
    "numero": "info-number",
    "raridade": "info-rarity",
    "edicao": "info-set",
    "idioma": "info-language",
}

CORES = frozenset("WUBRG")


@dataclass(frozen=True)
class Excecao:
    """O que forcar numa impressao, e por que."""

    motivo: str
    textos: dict[str, str] = field(default_factory=dict)
    # Uma entrada por face, na ordem em que a carta imprime. Vazio na carta de
    # uma face so, que usa o `textos`.
    faces: list[dict[str, str]] = field(default_factory=list)
    rodape: dict[str, str] = field(default_factory=dict)
    moldura: str | None = None
    cores: list[str] | None = None


def _erro(chave: str, problema: str) -> BadRequestError:
    return BadRequestError(f'{ARQUIVO.name}, entrada "{chave}": {problema}')


def _campos_de_texto(bruta: dict) -> dict[str, str]:
    """Os campos de texto da entrada, com o nome que o ScryfallCard usa."""
    return {
        CAMPOS_DE_TEXTO[campo]: bruta[campo].strip("\n")
        for campo in CAMPOS_DE_TEXTO
        if campo in bruta
    }


def _faces(chave: str, brutas: object) -> list[dict[str, str]]:
    """Uma entrada de texto por face, na ordem em que a carta imprime."""
    if brutas is None:
        return []
    if not isinstance(brutas, list) or not brutas:
        raise _erro(chave, "faces e uma lista com uma tabela por face da carta.")
    faces = []
    for face in brutas:
        if desconhecidos := sorted(set(face) - set(CAMPOS_DE_TEXTO)):
            raise _erro(chave, f"campo desconhecido na face: {', '.join(desconhecidos)}.")
        faces.append(_campos_de_texto(face))
    return faces


def _uma(chave: str, bruta: dict) -> Excecao:
    motivo = bruta.get("motivo")
    if not isinstance(motivo, str) or not motivo.strip():
        raise _erro(chave, "falta o campo motivo dizendo por que a regra nao alcanca.")

    conhecidos = {"motivo", "moldura", "cores", "faces", *CAMPOS_DE_TEXTO, *CAMPOS_DE_RODAPE}
    if desconhecidos := sorted(set(bruta) - conhecidos):
        raise _erro(chave, f"campo desconhecido: {', '.join(desconhecidos)}.")

    faces = _faces(chave, bruta.get("faces"))
    if faces and any(campo in bruta for campo in CAMPOS_DE_TEXTO):
        raise _erro(chave, "com `faces`, o texto vai dentro de cada face, nao solto.")

    cores = bruta.get("cores")
    if cores is not None and (
        not isinstance(cores, list) or any(cor not in CORES for cor in cores)
    ):
        raise _erro(chave, "cores aceita so uma lista de W, U, B, R e G (vazia = incolor).")

    return Excecao(
        # O TOML de tres aspas guarda a quebra de linha que so serve pra caber
        # no arquivo: no motivo ela vira espaco, no texto so as das pontas saem.
        motivo=" ".join(motivo.split()),
        textos=_campos_de_texto(bruta),
        faces=faces,
        rodape={campo: bruta[campo] for campo in CAMPOS_DE_RODAPE if campo in bruta},
        moldura=bruta.get("moldura"),
        cores=cores,
    )


def _ler(caminho: Path) -> dict[tuple[str, str], Excecao]:
    if not caminho.is_file():
        return {}
    bruto = tomllib.loads(caminho.read_text(encoding="utf-8"))
    carregadas: dict[tuple[str, str], Excecao] = {}
    for chave, entrada in bruto.items():
        edicao, barra, numero = chave.partition("/")
        if not barra or not edicao or not numero:
            raise _erro(chave, 'a chave e "<edicao>/<numero>", como "mh3/458".')
        carregadas[(edicao.lower(), numero.lower())] = _uma(chave, entrada)
    return carregadas


@cache
def todas() -> dict[tuple[str, str], Excecao]:
    """O arquivo lido, uma vez por processo."""
    return _ler(ARQUIVO)


def de(carta: ScryfallCard) -> Excecao | None:
    """A excecao desta impressao, se houver."""
    return todas().get((carta.set.lower(), carta.collector_number.lower()))


def aplicar_no_texto(carta: ScryfallCard) -> None:
    """Sobrescreve nome, linha de tipo, regras e historia da impressao.

    Chamado toda vez que a automacao termina de encher a carta - depois do
    Arena e depois da traducao emprestada de uma irma - pra que a excecao seja
    sempre a ultima palavra.
    """
    excecao = de(carta)
    if excecao is None or not (excecao.textos or excecao.faces):
        return
    for campo, valor in excecao.textos.items():
        setattr(carta, campo, valor)
    _aplicar_nas_faces(carta, excecao)
    logger.info(
        "%s %s: %s (excecao a mao)",
        carta.set.upper(),
        carta.collector_number,
        excecao.motivo,
    )


def _aplicar_nas_faces(carta: ScryfallCard, excecao: Excecao) -> None:
    """Escreve o texto de cada face da carta de duas faces.

    A contagem tem que bater: face a mais ou a menos e entrada escrita pra
    outra impressao, e ai o texto sairia na face errada.
    """
    if not excecao.faces:
        return
    faces_da_carta = carta.card_faces or []
    if len(faces_da_carta) != len(excecao.faces):
        raise BadRequestError(
            f"{ARQUIVO.name}, {carta.set.upper()} {carta.collector_number}: "
            f"a entrada tem {len(excecao.faces)} face(s) e a carta tem "
            f"{len(faces_da_carta)}."
        )
    for face, campos in zip(faces_da_carta, excecao.faces, strict=True):
        for campo, valor in campos.items():
            setattr(face, campo, valor)
