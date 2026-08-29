"""Ajuste do terminal antes de escrever qualquer coisa.

O console do Windows abre em página de código legada, e aí acento vira lixo na
tela. Reconfigurar a saída pra UTF-8 resolve sem depender de o usuário mexer no
terminal dele.
"""

import sys


def configurar_stdio() -> None:
    for fluxo in (sys.stdout, sys.stderr):
        reconfigurar = getattr(fluxo, "reconfigure", None)
        if reconfigurar is not None:
            reconfigurar(encoding="utf-8", errors="replace")
