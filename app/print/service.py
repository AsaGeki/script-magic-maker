"""Orquestra o fluxo de PDF: repete cada carta pelas copias que o deck pede e
monta as folhas (layout.py). Consumido pelo menu (app.cli.menu), sem nenhum
questionary aqui - so a logica de montagem."""

from pathlib import Path

from PIL import Image

from app.deck.legalidade import AnaliseDoDeck
from app.print import layout

ARQUIVO_METADATA = "metadata.txt"

# Aceito so na leitura, pra pasta de deck que nao tem metadata.txt.
ARQUIVO_COPIAS = "copias.txt"

SECAO_MODALIDADES = "[modalidades]"
SECAO_TRAVADAS = "[cartas-fora]"
SECAO_COPIAS = "[copias]"


def repetir_por_copias(pares: list[tuple[Path, int]]) -> list[Path]:
    """1 entrada por copia a imprimir, na ordem em que veio."""
    return [caminho for caminho, copias in pares for _ in range(max(1, copias))]


def escrever_metadata(
    pasta: Path,
    pares: list[tuple[Path, int]],
    analise: AnaliseDoDeck | None = None,
) -> None:
    """Grava o metadata.txt da pasta: veredito por modalidade, cartas que travam
    cada uma e quantas copias de cada arquivo o deck pede. A secao `[copias]` e
    a que o fluxo de PDF le de volta pra nao perguntar a quantidade de novo."""
    linhas: list[str] = []

    if analise is not None:
        linhas.append(SECAO_MODALIDADES)
        for veredito in analise.vereditos:
            estado = "sim" if veredito.pode_entrar else "nao"
            motivo = "; ".join(veredito.impedimentos)
            linhas.append(f"{veredito.formato:<12}{estado:<6}{motivo}".rstrip())
        linhas.append("")

        if analise.travadas:
            linhas.append(SECAO_TRAVADAS)
            for travada in analise.travadas:
                linhas.append(f"{travada.nome:<38}{' '.join(travada.formatos)}")
            linhas.append("")

    linhas.append(SECAO_COPIAS)
    linhas += [f"{copias} {caminho.name}" for caminho, copias in pares]
    (pasta / ARQUIVO_METADATA).write_text("\n".join(linhas) + "\n", encoding="utf-8")


def _copias_do_texto(texto: str, com_secoes: bool) -> dict[str, int]:
    """Le linhas `<quantidade> <arquivo>`. Com secoes, so conta o que vem
    depois de `[copias]`."""
    copias: dict[str, int] = {}
    dentro = not com_secoes
    for linha in texto.splitlines():
        limpa = linha.strip()
        if limpa.startswith("["):
            dentro = limpa == SECAO_COPIAS
            continue
        partes = limpa.split(maxsplit=1)
        if dentro and len(partes) == 2 and partes[0].isdigit():
            copias[partes[1]] = int(partes[0])
    return copias


def ler_copias(pasta: Path) -> dict[str, int]:
    """Quantidade de cada arquivo, pelo metadata.txt da pasta. Cai no copias.txt
    quando a pasta veio da versao antiga, e vazio quando nao tem nenhum dos dois
    (pasta montada a mao)."""
    metadata = pasta / ARQUIVO_METADATA
    if metadata.is_file():
        return _copias_do_texto(metadata.read_text(encoding="utf-8"), com_secoes=True)

    antigo = pasta / ARQUIVO_COPIAS
    if antigo.is_file():
        return _copias_do_texto(antigo.read_text(encoding="utf-8"), com_secoes=False)

    return {}


def tem_metadata(pasta: Path) -> bool:
    """Se a pasta se declara um deck. E o metadata.txt que diz quantas copias
    de cada carta imprimir, entao pasta sem ele nao e deck pro fluxo de PDF."""
    return (pasta / ARQUIVO_METADATA).is_file()


def conferir_copias(pasta: Path) -> tuple[list[str], list[str]]:
    """O que divergiu entre os png da pasta e a secao `[copias]`: os arquivos
    que estao na pasta e nao foram registrados, e os registrados que nao
    existem mais."""
    registradas = ler_copias(pasta)
    no_disco = {imagem.name for imagem in pasta.glob("*.png")}
    return sorted(no_disco - registradas.keys()), sorted(registradas.keys() - no_disco)


def impressao_do_arquivo(nome: str) -> tuple[str, str] | None:
    """Edicao e numero de colecionador que o nome do png carrega, no formato
    `<nome-da-carta>-<edicao>-<numero>.png` que o app.maker grava. None quando
    o arquivo foi renomeado e perdeu o par."""
    partes = Path(nome).stem.rsplit("-", 2)
    if len(partes) != 3:
        return None
    _, edicao, numero = partes
    return edicao, numero


def montar_lote(
    caminhos_cartas: list[Path], *, marca_corte: bool = True
) -> list[Image.Image]:
    """Folhas de frente prontas pro pdf.exportar_pdf."""
    return layout.montar_folhas_frente(caminhos_cartas, marca_corte=marca_corte)
