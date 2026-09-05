"""Os scripts que rodam dentro da página do Card Conjurer.

Cada `.js` desta pasta é uma função que o `app.maker.service` entrega ao
`page.evaluate()` do Playwright. Ficam em arquivo, e não em string dentro do
Python, pra terem realce, lint e diff de JavaScript de verdade — e pra que a
escapada do Python pare de disputar as barras da expressão regular.

Aqui moram só ajustes nossos, que dependem de dado da carta ou de política
nossa. Correção de defeito do próprio gerador vai em `patches/cardconjurer/`,
que é onde ela sobrevive ao clone (ver `app.vendor.patches`).
"""

from functools import lru_cache
from pathlib import Path

from app.errors import NotFoundError

PASTA = Path(__file__).resolve().parent


@lru_cache(maxsize=None)
def carregar(nome: str) -> str:
    """O conteúdo de `<nome>.js`, pronto pro page.evaluate."""
    arquivo = PASTA / f"{nome}.js"
    if not arquivo.is_file():
        raise NotFoundError(f"Script de navegador nao encontrado: {arquivo}")
    return arquivo.read_text(encoding="utf-8")
