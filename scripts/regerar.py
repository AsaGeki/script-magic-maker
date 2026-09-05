"""Regera os PNG que já estão em output/, com os dados e correções de hoje.

Serve pra quando uma correção muda o desenho de toda carta (fonte, moldura,
layout de texto) e as imagens no disco ficaram com a versão antiga. Cada
arquivo é reaberto pela edição e número que o nome carrega, a carta é
reconsultada no Scryfall e o PNG é sobrescrito no lugar.

    uv run python scripts/regerar.py                    # tudo em output/
    uv run python scripts/regerar.py decks/vermelho     # só uma pasta

As fichas passam pelo app.cards.fichas antes de gerar - é de lá que sai o nome
e a linha de tipo em português delas, que não existem no Scryfall.
"""

import asyncio
import sys
from pathlib import Path

from playwright.async_api import async_playwright

from app.cards import fichas
from app.cards.service import (
    completar_moldura_do_ingles,
    completar_traducao_parcial,
    find_card_by_print,
    preferir_traducao_do_arena,
    traduzir_terreno_basico,
)
from app.config import HEADLESS, OUTPUT_DIR
from app.maker.service import fill_card, moldura_sugerida
from app.print.service import impressao_do_arquivo
from app.vendor.server import ServidorCardConjurer

RAIZ = Path(OUTPUT_DIR)


def _e_ficha(carta) -> bool:
    return (carta.type_line or "").strip().lower().startswith(("token", "emblem"))


def _pastas(argumentos: list[str]) -> list[Path]:
    if argumentos:
        return [RAIZ / alvo for alvo in argumentos]
    return [p for p in sorted(RAIZ.rglob("*")) if p.is_dir() and any(p.glob("*.png"))]


async def _cartas_da_pasta(pasta: Path) -> list[tuple[str, object]]:
    """(arquivo, carta) de cada png, com as fichas já enriquecidas."""
    resolvidas = []
    for arquivo in sorted(p.name for p in pasta.glob("*.png")):
        impressao = impressao_do_arquivo(arquivo)
        if impressao is None:
            print(f"  {pasta.name}/{arquivo}: nome sem edicao, pulando", flush=True)
            continue
        carta = await find_card_by_print(*impressao) or await find_card_by_print(
            *impressao, lang="en"
        )
        if carta is None:
            print(f"  {pasta.name}/{arquivo}: nao resolveu", flush=True)
            continue
        resolvidas.append((arquivo, carta))

    if not any(_e_ficha(carta) for _, carta in resolvidas):
        return resolvidas

    criadoras = [carta for _, carta in resolvidas if not _e_ficha(carta)]
    enriquecidas = {}
    for achada in await fichas.descobrir(criadoras):
        ficha = achada.carta
        enriquecidas[(ficha.set, ficha.collector_number)] = ficha
    return [
        (arquivo, enriquecidas.get((carta.set, carta.collector_number), carta))
        for arquivo, carta in resolvidas
    ]


async def main() -> None:
    tarefas = []
    for pasta in _pastas(sys.argv[1:]):
        if not pasta.is_dir():
            print(f"pasta inexistente: {pasta}", flush=True)
            continue
        for arquivo, carta in await _cartas_da_pasta(pasta):
            tarefas.append((pasta, arquivo, carta))

    print(f"{len(tarefas)} cartas a regerar", flush=True)
    servidor = ServidorCardConjurer().start()
    async with async_playwright() as playwright:
        navegador = await playwright.chromium.launch(headless=HEADLESS)
        try:
            for indice, (pasta, arquivo, carta) in enumerate(tarefas, start=1):
                try:
                    await traduzir_terreno_basico(carta)
                    await completar_traducao_parcial(carta)
                    await completar_moldura_do_ingles(carta)
                    await fill_card(
                        carta,
                        browser=navegador,
                        pasta_destino=pasta,
                        moldura=moldura_sugerida(carta),
                        preferir_arena=preferir_traducao_do_arena(carta),
                    )
                    print(
                        f"{indice}/{len(tarefas)} OK {pasta.name}/{carta.nome_exibido}",
                        flush=True,
                    )
                except Exception as erro:  # noqa: BLE001 - 1 carta nao derruba o lote
                    print(f"{indice}/{len(tarefas)} FALHOU {arquivo}: {erro}", flush=True)
        finally:
            await navegador.close()
            servidor.stop()


if __name__ == "__main__":
    asyncio.run(main())
