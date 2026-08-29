"""Navegador do Playwright preparado pro Card Conjurer.

O gerador roda local, então tudo que sai pra internet aqui é exceção listada:
os dados e a arte do Scryfall e a arte do MTGPics. O resto é bloqueado — o que
acelera a página e deixa explícito o que o projeto acessa.
"""

from playwright.sync_api import Route

# Molduras do #autoFrame. O valor é o que o select espera.
MOLDURAS = {
    "regular": "M15Regular-1",
    "regular-fiel": "M15RegularNew",
    "arte-estendida": "M15BoxTopper",
    "arte-estendida-curta": "M15ExtendedArtShort",
    "universes-beyond": "UB",
    "etched": "Etched",
    "borderless": "Borderless",
    "phyrexian": "Praetors",
    "8th": "8th",
    "seventh": "Seventh",
    "full-art-fiel": "FullArtNew",
    "circuit": "Circuit",
}
MOLDURA_PADRAO = "M15Regular-1"

HOSTS_LIBERADOS = (
    "127.0.0.1",
    "localhost",
    "api.scryfall.com",
    "cards.scryfall.io",
    "svgs.scryfall.io",
    "www.mtgpics.com",
    "mtgpics.com",
)


def filtrar_rede(rota: Route) -> None:
    """Deixa passar só o servidor local e as fontes de dados e arte."""
    host = rota.request.url.split("/")[2].split(":")[0]
    if host in HOSTS_LIBERADOS:
        rota.continue_()
    else:
        rota.abort()
