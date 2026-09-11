"""Slug compartilhado - nome de carta/deck -> nome de arquivo/pasta seguro
(sem acento/espaco/maiuscula). Usado tanto pro nome do arquivo da carta
(app.maker.service) quanto pro nome das pastas de deck (app.cli.menu)."""

import re
import unicodedata

# Separador entre as partes do nome de arquivo da carta. Duplo porque `slug`
# colapsa toda corrida de nao alfanumerico num traco so: "--" nunca sai de
# dentro de uma parte, entao ele nunca se confunde com o traco que o nome da
# carta ou o numero de colecionador ja carregam ("ELD-1", da PLST).
SEPARADOR = "--"


def slug(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFD", texto)
    sem_acento = "".join(c for c in sem_acento if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-zA-Z0-9]+", "-", sem_acento).strip("-").lower()


def nome_de_arquivo(*partes: str) -> str:
    """Junta as partes num nome que da pra desmontar de volta (ver SEPARADOR).

    Quem desmonta e o app.print.service.impressao_do_arquivo.
    """
    return SEPARADOR.join(slug(parte) for parte in partes)
