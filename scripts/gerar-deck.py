"""Gera um deck inteiro a partir de um arquivo de lista, sem passar pelo menu.

O menu (app.cli.menu) faz o mesmo com checkbox e confirmação a cada passo; aqui
é o lote direto, pra rodar em terminal não interativo e pra reconstruir uma
pasta que ficou vazia — caso em que o regerar.py não serve, porque ele parte dos
PNG que já estão lá.

    uv run python scripts/gerar-deck.py teste-molduras.txt
    uv run python scripts/gerar-deck.py listas/vermelho.txt decks/vermelho

Sem a pasta, o destino sai do nome do arquivo, em output/decks/. Ao final grava
o metadata.txt com as modalidades e imprime as cartas que ficaram de fora.
"""

import asyncio
import sys
from pathlib import Path

from playwright.async_api import async_playwright

from app.cards import fichas
from app.cards.service import (
    completar_moldura_do_ingles,
    completar_traducao_parcial,
    preferir_traducao_do_arena,
    traduzir_terreno_basico,
)
from app.config import HEADLESS, OUTPUT_DIR
from app.deck import legalidade
from app.deck.service import buscar_cartas_do_deck
from app.deck.texto import ler_arquivo
from app.errors import AppError
from app.maker.service import fill_card, moldura_sugerida
from app.print.service import escrever_metadata
from app.slug import slug
from app.vendor.server import ServidorCardConjurer


def _e_ficha(carta) -> bool:
    return (carta.type_line or "").strip().lower().startswith(("token", "emblem"))


async def _com_fichas_traduzidas(cartas: list) -> list:
    """Troca cada ficha da lista pela versão que o app.cards.fichas enriquece.

    A tradução da ficha sai da carta que a cria, então ela precisa da lista
    toda; sem isso, ficha entra em inglês.
    """
    if not any(_e_ficha(carta) for carta in cartas):
        return cartas
    criadoras = [carta for carta in cartas if not _e_ficha(carta)]
    enriquecidas = {}
    for achada in await fichas.descobrir(criadoras):
        enriquecidas[(achada.carta.set, achada.carta.collector_number)] = achada.carta
    return [
        enriquecidas.get((carta.set, carta.collector_number), carta) for carta in cartas
    ]


def _destino(lista: Path, argumentos: list[str]) -> Path:
    if argumentos:
        return Path(OUTPUT_DIR) / argumentos[0]
    return Path(OUTPUT_DIR) / "decks" / slug(lista.stem)


async def main() -> None:
    if not sys.argv[1:]:
        print(__doc__)
        raise SystemExit(2)

    lista = Path(sys.argv[1])
    if not lista.is_file():
        print(f"lista inexistente: {lista}", flush=True)
        raise SystemExit(1)
    destino = _destino(lista, sys.argv[2:])

    pares, avisos = await buscar_cartas_do_deck(ler_arquivo(lista), permitir_ingles=True)
    for aviso in avisos:
        print(f"linha sem carta - {aviso}", flush=True)
    cartas = await _com_fichas_traduzidas([carta for _, carta in pares])

    destino.mkdir(parents=True, exist_ok=True)
    geradas: list[tuple[Path, int]] = []
    de_fora: list[str] = []

    print(f"{len(cartas)} cartas a gerar em {destino}", flush=True)
    servidor = ServidorCardConjurer().start()
    async with async_playwright() as playwright:
        navegador = await playwright.chromium.launch(headless=HEADLESS)
        try:
            for indice, carta in enumerate(cartas, start=1):
                try:
                    await traduzir_terreno_basico(carta)
                    await completar_traducao_parcial(carta)
                    await completar_moldura_do_ingles(carta)
                    caminho = await fill_card(
                        carta,
                        browser=navegador,
                        pasta_destino=destino,
                        moldura=moldura_sugerida(carta),
                        preferir_arena=preferir_traducao_do_arena(carta),
                    )
                    geradas.append((caminho, carta.copias))
                    print(f"{indice}/{len(cartas)} OK {caminho.name}", flush=True)
                except AppError as erro:
                    de_fora.append(f"{carta.nome_exibido}: {erro.message}")
                    print(f"{indice}/{len(cartas)} RECUSOU {carta.nome_exibido}", flush=True)
                except Exception as erro:  # noqa: BLE001 - 1 carta nao derruba o lote
                    de_fora.append(f"{carta.nome_exibido}: {erro}")
                    print(f"{indice}/{len(cartas)} FALHOU {carta.nome_exibido}: {erro}", flush=True)
        finally:
            await navegador.close()
            servidor.stop()

    escrever_metadata(destino, geradas, await legalidade.analisar_deck(cartas))
    print(f"\ngeradas {len(geradas)}, de fora {len(de_fora)}", flush=True)
    for linha in de_fora:
        print(f"  - {linha}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
