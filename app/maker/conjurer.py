"""Automação do Card Conjurer.

Em vez de preencher campo a campo, chama as funções globais do próprio
gerador: ele já sabe importar do Scryfall no idioma escolhido, escolher a
moldura, buscar a arte e compor as camadas.

A imagem sai lida direto do `cardCanvas` — o `downloadCard()` do site faz o
mesmo `toDataURL`, mas passando por um `<a download>` que não interessa aqui.
"""

import base64
import re
import time
from pathlib import Path
from types import TracebackType

import httpx
from playwright.sync_api import Page, sync_playwright

from app.cards.enums import Layout
from app.cards.models import ScryfallCard
from app.config import settings
from app.errors import ErroDoCardConjurer
from app.maker.browser import MOLDURA_PADRAO, filtrar_rede
from app.vendor.server import ServidorCardConjurer

# Amostra reduzida do canvas, usada só pra saber se o desenho parou de mudar.
_IMPRESSAO_DIGITAL = """() => {
    if (typeof cardCanvas === 'undefined' || !cardCanvas.width) { return null; }
    const mini = document.createElement('canvas');
    mini.width = 32;
    mini.height = 44;
    mini.getContext('2d').drawImage(cardCanvas, 0, 0, mini.width, mini.height);
    return mini.toDataURL();
}"""

_SELECIONAR_IMPRESSAO = """(i) => {
    document.querySelector('#import-index').value = String(i);
    changeCardIndex();
}"""

INTERVALO_AMOSTRA = 0.3
AMOSTRAS_IGUAIS = 3  # leituras seguidas sem mudança = desenho terminou
TEMPO_LIMITE_DESENHO = 45.0
TEMPO_LIMITE_IMPORT = 30_000  # milissegundos, como o Playwright espera
TEMPO_LIMITE_MOLDURA = 20_000

# Moldura carregada na abertura só pra existir um card.text: sem ele, tanto
# changeCardIndex() quanto autoFrame() quebram. A moldura definitiva vem depois,
# do autoFrame, que troca o pacote sozinho conforme a cor e o tipo da carta.
GRUPO_INICIAL = "Standard-3"
PACOTE_INICIAL = "M15Regular-1"

# Cada uma dessas rende duas imagens, uma por face, e o fluxo daqui salva uma só.
LAYOUTS_DE_DUAS_FACES = frozenset(
    {
        Layout.TRANSFORM,
        Layout.MODAL_DFC,
        Layout.MELD,
        Layout.REVERSIBLE_CARD,
        Layout.DOUBLE_FACED_TOKEN,
        Layout.ART_SERIES,
    }
)


class Conjurer:
    """Dirige o Card Conjurer numa página só, reaproveitada entre cartas."""

    def __init__(
        self,
        servidor: ServidorCardConjurer | None = None,
        headless: bool | None = None,
        moldura: str = MOLDURA_PADRAO,
        arte_mtgpics: bool = True,
    ) -> None:
        self.servidor = servidor or ServidorCardConjurer()
        self.headless = settings.headless if headless is None else headless
        self.moldura = moldura
        self.arte_mtgpics = arte_mtgpics
        self._playwright = None
        self._browser = None
        self._page: Page | None = None
        self._servidor_proprio = servidor is None

    # --- ciclo de vida ---

    def __enter__(self) -> "Conjurer":
        return self.start()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.stop()

    def start(self) -> "Conjurer":
        if self._servidor_proprio:
            self.servidor.start()
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=self.headless)
        contexto = self._browser.new_context(viewport={"width": 1400, "height": 1000})
        contexto.route("**/*", filtrar_rede)
        page = contexto.new_page()
        # enableImportCollectorInfo preenche número, raridade, edição e idioma no
        # rodapé; autoLoadFrameVersion faz o pacote de molduras se aplicar sozinho.
        # enableCollectorInfo precisa vir escrito daqui: quando a chave não existe,
        # o Card Conjurer grava 'true' mas não marca a caixa correspondente, e o
        # rodapé só apareceria na segunda visita à página.
        page.add_init_script(
            "localStorage.setItem('enableImportCollectorInfo', 'true');"
            "localStorage.setItem('autoLoadFrameVersion', 'true');"
            "localStorage.setItem('enableCollectorInfo', 'true');"
        )
        # O parâmetro mtgpics liga a arte em 1920x1080; sem ele fica no art_crop 626x457.
        page.goto(f"{self.servidor.url}/creator/?mtgpics=1", wait_until="load")
        page.wait_for_function("typeof fetchScryfallData === 'function'")
        self._page = page
        self._carregar_moldura_inicial()
        return self

    def _carregar_moldura_inicial(self) -> None:
        """Carrega um pacote de molduras pra existir um card.text.

        A página abre com o objeto `card` sem `text`, e nesse estado tanto o
        import quanto a moldura automática quebram. Escolher um grupo e um
        pacote é o que a interface faz quando alguém entra na aba Frame.
        """
        page = self.page
        page.select_option("#selectFrameGroup", GRUPO_INICIAL)
        page.wait_for_function(
            "document.querySelector('#selectFramePack').options.length > 0",
            timeout=TEMPO_LIMITE_MOLDURA,
        )
        page.select_option("#selectFramePack", PACOTE_INICIAL)
        page.wait_for_function(
            "typeof card !== 'undefined' && card.text && card.text.title",
            timeout=TEMPO_LIMITE_MOLDURA,
        )

    def stop(self) -> None:
        if self._browser is not None:
            self._browser.close()
            self._browser = None
        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None
        self._page = None
        if self._servidor_proprio:
            self.servidor.stop()

    @property
    def page(self) -> Page:
        if self._page is None:
            raise ErroDoCardConjurer("O Conjurer não foi iniciado; use dentro de um 'with'.")
        return self._page

    # --- geração ---

    def gerar(self, carta: ScryfallCard, destino: Path | None = None) -> Path:
        """Monta a carta no gerador e salva o PNG. Devolve o caminho do arquivo."""
        if carta.layout in LAYOUTS_DE_DUAS_FACES:
            raise ErroDoCardConjurer(
                f"{carta.nome_exibido} é uma carta de {carta.layout}, que rende duas "
                "imagens; o gerador aqui ainda produz uma face só."
            )
        page = self.page

        page.select_option("#import-language", carta.lang)
        page.select_option("#autoFrame", self.moldura)
        # Com todas as impressões na lista, o gerador casa a arte pela ilustração
        # da impressão escolhida em vez de pegar a primeira que aparecer.
        page.check("#importAllPrints")

        # O import do gerador busca pelo nome em inglês e traz a impressão do idioma.
        nome_busca = carta.name.split(" // ")[0]
        page.evaluate("(nome) => fetchScryfallData(nome, importCard)", nome_busca)
        try:
            page.wait_for_function(
                "document.querySelector('#import-index').options.length > 0",
                timeout=TEMPO_LIMITE_IMPORT,
            )
        except Exception as erro:
            raise ErroDoCardConjurer(
                f"O Card Conjurer não trouxe nenhuma impressão para {carta.name!r}."
            ) from erro

        # O importCard() já aplica a primeira impressão sozinho. Deixar essa
        # rodada terminar antes de trocar de impressão evita que a consulta da
        # edição, que é assíncrona, escreva o número do colecionador duas vezes.
        self._esperar_desenho()
        if self._selecionar_impressao(carta):
            self._esperar_desenho()
        if self.arte_mtgpics:
            self._aplicar_arte_mtgpics(carta)
        return self._salvar(carta, destino)

    def _aplicar_arte_mtgpics(self, carta: ScryfallCard) -> bool:
        """Troca a arte do Scryfall pela do MTGPics, que é bem maior.

        O gerador até tenta o MTGPics sozinho, mas passando por um proxy de
        CORS de terceiro. Baixar aqui e entregar a imagem pronta evita esse
        intermediário. Quando o MTGPics não tem a carta, fica o art_crop.
        """
        try:
            resposta = httpx.get(
                carta.arte_mtgpics,
                timeout=20.0,
                follow_redirects=True,
                headers={"User-Agent": settings.scryfall_user_agent},
            )
        except httpx.HTTPError:
            return False

        tipo = resposta.headers.get("content-type", "")
        if resposta.status_code != 200 or not tipo.startswith("image/"):
            return False

        data_url = f"data:{tipo};base64,{base64.b64encode(resposta.content).decode()}"
        self.page.evaluate("(src) => uploadArt(src, 'autoFit')", data_url)
        self._esperar_desenho()
        return True

    def _selecionar_impressao(self, carta: ScryfallCard) -> bool:
        """Escolhe no gerador a mesma impressão que a consulta trouxe.

        O import lista todas as impressões do nome; casar pelo id do Scryfall
        garante a mesma arte, edição e número que a API devolveu. Quando o id
        não está na lista, fica a primeira opção — mesma carta, outra tiragem.

        Devolve se precisou mesmo trocar de impressão.
        """
        indice = self.page.evaluate(
            "(id) => scryfallCard.findIndex(c => c.id === id)",
            carta.id,
        )
        if indice is None or indice < 0:
            indice = 0
        atual = self.page.evaluate("() => Number(document.querySelector('#import-index').value)")
        if indice == atual:
            return False
        self.page.evaluate(_SELECIONAR_IMPRESSAO, indice)
        return True

    def _esperar_desenho(self) -> None:
        """Espera o canvas parar de mudar.

        O gerador não avisa quando terminou: a arte, o símbolo de expansão e as
        camadas de moldura chegam cada uma no seu tempo. Então a saída é
        amostrar o desenho até ele se repetir.
        """
        limite = time.monotonic() + TEMPO_LIMITE_DESENHO
        anterior = None
        iguais = 0
        while time.monotonic() < limite:
            atual = self.page.evaluate(_IMPRESSAO_DIGITAL)
            if atual is not None and atual == anterior:
                iguais += 1
                if iguais >= AMOSTRAS_IGUAIS:
                    return
            else:
                iguais = 0
            anterior = atual
            time.sleep(INTERVALO_AMOSTRA)
        raise ErroDoCardConjurer(f"O desenho não estabilizou em {TEMPO_LIMITE_DESENHO:.0f}s.")

    def _salvar(self, carta: ScryfallCard, destino: Path | None) -> Path:
        data_url = self.page.evaluate("() => cardCanvas.toDataURL('image/png')")
        if not data_url or not data_url.startswith("data:image/png;base64,"):
            raise ErroDoCardConjurer("O canvas não devolveu uma imagem PNG.")

        caminho = destino or (settings.output_dir / nome_de_arquivo(carta))
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_bytes(base64.b64decode(data_url.split(",", 1)[1]))
        return caminho

    def dimensoes(self) -> tuple[int, int]:
        """Tamanho do canvas de saída, pra conferir a resolução."""
        largura, altura = self.page.evaluate("() => [cardCanvas.width, cardCanvas.height]")
        return largura, altura


def nome_de_arquivo(carta: ScryfallCard) -> str:
    """Nome do arquivo: carta, edição e número, sem caractere proibido."""
    base = f"{carta.nome_exibido}-{carta.set}-{carta.collector_number}"
    limpo = re.sub(r'[<>:"/\\|?*]', "", base).strip()
    return f"{limpo.replace(' ', '_')}.png"
