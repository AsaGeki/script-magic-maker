"""Leitura de lista de deck em texto.

Cobre o que Moxfield, Archidekt e o MTG Arena exportam: uma carta por linha,
com quantidade na frente e, às vezes, edição e número entre parênteses.

    4 Lightning Bolt
    4x Raio
    1 Kona, Rescue Beastie (DSK) 187
    // Sideboard
    2 Negate

Linhas em branco, comentários (`#` e `//`) e cabeçalhos de seção são
descartados — o cabeçalho vira a seção das linhas seguintes.
"""

import re
from dataclasses import dataclass
from pathlib import Path

from app.errors import ErroDeDeck

MAIN = "main"
SIDEBOARD = "sideboard"
COMMANDER = "commander"

# Cabeçalhos que os sites usam pra separar as partes do deck.
SECOES = {
    "deck": MAIN,
    "main": MAIN,
    "maindeck": MAIN,
    "mainboard": MAIN,
    "sideboard": SIDEBOARD,
    "side": SIDEBOARD,
    "commander": COMMANDER,
    "comandante": COMMANDER,
    "companion": SIDEBOARD,
}

# 4 Nome | 4x Nome | 4 Nome (SET) 123 | Nome (sem quantidade vale 1)
LINHA = re.compile(
    r"""^
    (?:(?P<quantidade>\d+)\s*x?\s+)?
    (?P<nome>.+?)
    (?:\s+\((?P<set>[A-Za-z0-9]{2,6})\)\s*(?P<numero>[A-Za-z0-9\-★]+)?)?
    \s*$
    """,
    re.VERBOSE,
)


@dataclass
class EntradaDeDeck:
    """Uma linha da lista, já separada em partes."""

    quantidade: int
    nome: str
    set: str | None = None
    collector_number: str | None = None
    secao: str = MAIN


def analisar_lista(texto: str) -> list[EntradaDeDeck]:
    """Converte o texto da lista em entradas.

    Uma linha que não casa com o formato é erro: passar despercebido faria o
    deck sair incompleto sem ninguém notar.
    """
    entradas: list[EntradaDeDeck] = []
    secao = MAIN

    for numero_da_linha, bruta in enumerate(texto.splitlines(), start=1):
        linha = bruta.strip()
        if not linha:
            continue

        sem_marca = linha.lstrip("#/").strip()
        if linha.startswith(("#", "//")):
            secao = SECOES.get(sem_marca.lower().rstrip(":"), secao)
            continue
        if sem_marca.lower().rstrip(":") in SECOES and not sem_marca[0].isdigit():
            secao = SECOES[sem_marca.lower().rstrip(":")]
            continue

        casamento = LINHA.match(linha)
        if casamento is None or not casamento.group("nome").strip():
            raise ErroDeDeck(f"Linha {numero_da_linha} não parece uma carta: {bruta!r}")

        entradas.append(
            EntradaDeDeck(
                quantidade=int(casamento.group("quantidade") or 1),
                nome=casamento.group("nome").strip(),
                set=(casamento.group("set") or "").lower() or None,
                collector_number=casamento.group("numero"),
                secao=secao,
            )
        )

    if not entradas:
        raise ErroDeDeck("A lista está vazia.")
    return entradas


def ler_arquivo(caminho: Path) -> list[EntradaDeDeck]:
    """Mesma coisa, lendo de um arquivo."""
    if not caminho.is_file():
        raise ErroDeDeck(f"Arquivo de deck não encontrado: {caminho}")
    return analisar_lista(caminho.read_text(encoding="utf-8"))


def cartas_unicas(entradas: list[EntradaDeDeck]) -> list[EntradaDeDeck]:
    """Junta repetições da mesma carta, somando as quantidades.

    A imagem é gerada uma vez por carta, não uma vez por cópia; quantas cópias
    imprimir é problema da folha de impressão.
    """
    juntas: dict[tuple[str, str | None, str | None], EntradaDeDeck] = {}
    for entrada in entradas:
        chave = (entrada.nome.lower(), entrada.set, entrada.collector_number)
        if chave in juntas:
            juntas[chave].quantidade += entrada.quantidade
        else:
            juntas[chave] = EntradaDeDeck(**vars(entrada))
    return list(juntas.values())
