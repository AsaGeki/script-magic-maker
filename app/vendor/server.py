"""Servidor estático local do Card Conjurer.

O aplicativo não tem backend — o `app.conf` do repositório é um nginx que só
serve arquivo. Qualquer servidor estático resolve, então aqui roda um
ThreadingHTTPServer numa thread do próprio processo: uma dependência a menos
que o Docker e um processo a menos pra sobrar aberto.

Não funciona por file://: o aplicativo carrega molduras e dados por XHR, que o
protocolo de arquivo bloqueia.
"""

import socket
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import TracebackType

from app.config import CARDCONJURER_DIR, CARDCONJURER_PORT
from app.errors import BadRequestError
from app.vendor import patches
from app.vendor.repo import garantir_instalado

TEMPO_LIMITE_SUBIDA = 10.0  # segundos esperando o servidor aceitar conexão


# Sem charset declarado, o navegador lê o JavaScript como Latin-1 e os acentos
# escritos no próprio código viram lixo — as aspas curvas que o curlyQuotes()
# insere no texto da carta saem como "â€™" na imagem. O HTML do Card Conjurer não
# tem <meta charset>, então quem precisa dizer isso é o servidor.
TIPOS_COM_CHARSET = ("text/", "application/javascript", "application/json")

# Só a index da raiz do Card Conjurer é uma página inteira; as outras (creator,
# print, theme...) são fragmentos que começam nesta marca e dependem de alguém
# grudar o cabeçalho e o rodapé em volta. O nginx do repositório não faz isso,
# então quem serve estático precisa montar - sem o cabeçalho a página sobe sem
# nenhum <link> de css, nenhuma @font-face entra no document.fonts e todo texto
# de carta cai na fonte de reserva do navegador.
MARCA_DE_FRAGMENTO = b"<!-- START OF CONTENT -->"
CABECALHO_GLOBAL = Path("globalHTML/header.html")
RODAPE_GLOBAL = Path("globalHTML/footer.html")


class _HandlerSilencioso(SimpleHTTPRequestHandler):
    """Igual ao padrão, sem escrever uma linha por arquivo servido.

    O Card Conjurer pede centenas de arquivos por carta; o log padrão só
    atrapalharia a leitura do terminal.
    """

    def log_message(self, format: str, *args: object) -> None:
        pass

    def guess_type(self, path: str | Path) -> str:
        tipo = super().guess_type(path)
        if tipo.startswith(TIPOS_COM_CHARSET) and "charset=" not in tipo:
            return f"{tipo}; charset=utf-8"
        return tipo

    def do_GET(self) -> None:
        pagina = self._pagina_montada()
        if pagina is None:
            super().do_GET()
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(pagina)))
        self.end_headers()
        self.wfile.write(pagina)

    def _pagina_montada(self) -> bytes | None:
        """A página pedida com cabeçalho e rodapé em volta, ou None quando o
        pedido não é um fragmento (aí o handler padrão serve o arquivo)."""
        caminho = Path(self.translate_path(self.path))
        if caminho.is_dir():
            caminho = caminho / "index.html"
        if caminho.suffix != ".html" or not caminho.is_file():
            return None

        conteudo = caminho.read_bytes()
        if not conteudo.lstrip().startswith(MARCA_DE_FRAGMENTO):
            return None

        raiz = Path(self.directory)
        cabecalho = (raiz / CABECALHO_GLOBAL).read_bytes()
        rodape = (raiz / RODAPE_GLOBAL).read_bytes()
        return cabecalho + conteudo + rodape


def porta_livre(porta: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        return sock.connect_ex((host, porta)) != 0


class ServidorCardConjurer:
    """Serve o fork em http://127.0.0.1:<porta> enquanto o bloco `with` dura."""

    def __init__(self, diretorio: Path | None = None, porta: int | None = None) -> None:
        self.diretorio = diretorio or CARDCONJURER_DIR
        self.porta = porta or CARDCONJURER_PORT
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.porta}"

    @property
    def url_do_criador(self) -> str:
        """A página que a automação abre."""
        return f"{self.url}/creator/"

    def start(self) -> "ServidorCardConjurer":
        garantir_instalado(self.diretorio)
        faltando = patches.pendentes(self.diretorio)
        if faltando:
            nomes = ", ".join(p.name for p in faltando)
            raise BadRequestError(
                f"O Card Conjurer esta sem os patches do projeto ({nomes}). "
                "Rode 'uv run cli.py setup' antes de gerar carta."
            )

        if not porta_livre(self.porta):
            raise BadRequestError(
                f"A porta {self.porta} já está ocupada. Ajuste CARDCONJURER_PORT no .env "
                "ou encerre quem está usando."
            )

        handler = partial(_HandlerSilencioso, directory=str(self.diretorio))
        try:
            self._httpd = ThreadingHTTPServer(("127.0.0.1", self.porta), handler)
        except OSError as erro:
            raise BadRequestError(
                f"Não foi possível subir o servidor na porta {self.porta}: {erro}"
            ) from erro

        self._thread = threading.Thread(
            target=self._httpd.serve_forever,
            name="cardconjurer-http",
            daemon=True,
        )
        self._thread.start()
        self._esperar_responder()
        return self

    def _esperar_responder(self) -> None:
        limite = time.monotonic() + TEMPO_LIMITE_SUBIDA
        while time.monotonic() < limite:
            if not porta_livre(self.porta):
                return
            time.sleep(0.05)
        self.stop()
        raise BadRequestError(
            f"O servidor não respondeu em {TEMPO_LIMITE_SUBIDA:.0f}s na porta {self.porta}."
        )

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def __enter__(self) -> "ServidorCardConjurer":
        return self.start()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.stop()
