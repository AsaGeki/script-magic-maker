"""Cronometro das operacoes do CLI - spinner com segundos correndo ao vivo
enquanto espera o Scryfall/Card Conjurer, e quanto levou no final.

So embrulha trabalho de verdade (rede, navegador) - nunca um prompt do
questionary, senao o contador mediria quanto tempo o usuario levou pra
responder, nao quanto tempo o sistema levou.
"""

import asyncio
import time
from contextlib import asynccontextmanager

from rich.console import Console

INTERVALO_ATUALIZACAO = 0.5


@asynccontextmanager
async def cronometrar(console: Console, mensagem: str):
    """`async with cronometrar(console, "Buscando..."):` - mostra um spinner
    com os segundos correndo, e ao sair imprime quanto levou de verdade."""
    inicio = time.monotonic()
    parar = asyncio.Event()

    async def atualizar(status) -> None:
        while not parar.is_set():
            status.update(f"{mensagem} [dim]({time.monotonic() - inicio:.0f}s)[/dim]")
            try:
                await asyncio.wait_for(parar.wait(), timeout=INTERVALO_ATUALIZACAO)
            except TimeoutError:
                pass

    with console.status(mensagem) as status:
        tarefa = asyncio.create_task(atualizar(status))
        try:
            yield
        finally:
            parar.set()
            await tarefa

    console.print(f"[dim]{mensagem} — {time.monotonic() - inicio:.1f}s[/dim]")
