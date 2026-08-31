"""Leitura de lista de deck em texto - equivalente ao ydk.py do
script-yugioh-maker, so que aqui o formato e o texto que Moxfield, Archidekt e
o MTG Arena exportam, nao o .ydk numerico da Konami.

    4 Lightning Bolt
    4x Raio
    1 Kona, Rescue Beastie (DSK) 187
    // Sideboard
    2 Negate

Linha em branco, comentario (`#` e `//`) e cabecalho de secao sao descartados -
o cabecalho vira a secao das linhas seguintes.
"""

import re
from dataclasses import dataclass
from pathlib import Path

from app.errors import BadRequestError

MAIN = "main"
SIDEBOARD = "sideboard"
COMMANDER = "commander"

# Cabecalhos que os sites usam pra separar as partes do deck.
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
    """Uma linha da lista, ja separada em partes."""

    quantidade: int
    nome: str
    set: str | None = None
    collector_number: str | None = None
    secao: str = MAIN


def analisar_lista(texto: str) -> list[EntradaDeDeck]:
    """Converte o texto da lista em entradas.

    Linha que nao casa com o formato e erro: passar despercebido faria o deck
    sair incompleto sem ninguem notar.
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
            raise BadRequestError(f"Linha {numero_da_linha} nao parece uma carta: {bruta!r}")

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
        raise BadRequestError("A lista esta vazia")
    return entradas


def ler_arquivo(caminho: Path) -> list[EntradaDeDeck]:
    """Mesma coisa, lendo de um arquivo."""
    if not caminho.is_file():
        raise BadRequestError(f'Arquivo de deck "{caminho}" nao encontrado')
    return analisar_lista(caminho.read_text(encoding="utf-8"))


Chave = tuple[str, str | None, str | None]


def chave_da_entrada(entrada: EntradaDeDeck) -> Chave:
    """O que faz duas linhas serem a mesma carta: nome, edicao e numero.

    Linha sem edicao e linha travada numa impressao contam como cartas
    diferentes de proposito - dividir copias entre variantes e o jeito
    documentado de misturar arte da mesma carta num deck (ver DECK.md).
    """
    return (entrada.nome.lower(), entrada.set, entrada.collector_number)


def cartas_unicas(entradas: list[EntradaDeDeck]) -> list[EntradaDeDeck]:
    """Junta repeticoes da mesma carta, somando as quantidades.

    A imagem e gerada uma vez por carta, nao uma por copia; quantas copias
    imprimir e problema da folha (ver app.print).
    """
    juntas: dict[Chave, EntradaDeDeck] = {}
    for entrada in entradas:
        chave = chave_da_entrada(entrada)
        if chave in juntas:
            juntas[chave].quantidade += entrada.quantidade
        else:
            juntas[chave] = EntradaDeDeck(**vars(entrada))
    return list(juntas.values())


def travar_impressoes(caminho: Path, escolhas: dict[Chave, tuple[str, str]]) -> int:
    """Grava no arquivo a edicao e o numero escolhidos, uma linha por vez.

    Casa pela chave da linha em vez de guardar o numero da linha porque a
    mesma carta pode aparecer repetida na lista - todas as ocorrencias da
    carta escolhida travam na mesma impressao, que e o que cartas_unicas ja
    tinha juntado numa entrada so.

    O resto do arquivo passa intacto: comentario, cabecalho de secao, linha
    em branco e linha que ja vinha travada nao sao tocados. Devolve quantas
    linhas mudaram.
    """
    linhas = caminho.read_text(encoding="utf-8").splitlines()
    trocadas = 0

    for indice, bruta in enumerate(linhas):
        linha = bruta.strip()
        if not linha or linha.startswith(("#", "//")):
            continue
        casamento = LINHA.match(linha)
        if casamento is None or casamento.group("set"):
            continue
        chave = (casamento.group("nome").strip().lower(), None, None)
        if chave not in escolhas:
            continue
        edicao, numero = escolhas[chave]
        linhas[indice] = f"{bruta.rstrip()} ({edicao.upper()}) {numero}"
        trocadas += 1

    if trocadas:
        caminho.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    return trocadas
