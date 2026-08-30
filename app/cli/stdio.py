"""Windows abre o console em pagina de codigo legada e acento vira lixo na
tela - reconfigurar a saida pra UTF-8 resolve sem depender de o usuario mexer
no terminal dele."""

import sys


def configurar_stdio_utf8() -> None:
    for fluxo in (sys.stdout, sys.stderr):
        reconfigurar = getattr(fluxo, "reconfigure", None)
        if reconfigurar is not None:
            reconfigurar(encoding="utf-8", errors="replace")
