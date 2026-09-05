"""Ultima folha do PDF do deck: em que modalidades ele entra e o que trava.

So texto, sem carta - entra depois das folhas de carta em app.cli.menu. A
analise vem pronta de app.deck.legalidade; aqui e desenho puro.
"""

from PIL import Image, ImageDraw, ImageFont

from app.deck.legalidade import AnaliseDoDeck, NOME_DO_FORMATO
from app.print.layout import A4_ALTURA_PX, A4_LARGURA_PX, mm_para_px

MARGEM_MM = 16
COR_TEXTO = "black"
COR_APAGADA = (110, 110, 110)
COR_LINHA = (190, 190, 190)
COR_SIM = (20, 110, 60)
COR_NAO = (150, 40, 30)

# Familias procuradas na ordem; a primeira que existir vale. Sem nenhuma delas,
# cai pra fonte embutida do Pillow, que ignora tamanho e sai miuda.
FONTES_NORMAIS = ("segoeui.ttf", "arial.ttf", "DejaVuSans.ttf", "calibri.ttf")
FONTES_NEGRITO = ("segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf", "calibrib.ttf")

TAMANHO_TITULO_MM = 7.5
TAMANHO_SECAO_MM = 3.6
TAMANHO_CORPO_MM = 3.1
TAMANHO_MIUDO_MM = 2.5

# Quantas cartas travadas cabem antes de a lista virar "e mais N".
LIMITE_DE_TRAVADAS = 34


def _fonte(nomes: tuple[str, ...], tamanho_mm: float) -> ImageFont.ImageFont:
    tamanho = mm_para_px(tamanho_mm)
    for nome in nomes:
        try:
            return ImageFont.truetype(nome, tamanho)
        except OSError:
            continue
    return ImageFont.load_default()


def _texto(desenho, posicao, conteudo, fonte, cor=COR_TEXTO) -> int:
    """Escreve e devolve a altura ocupada em px."""
    desenho.text(posicao, conteudo, font=fonte, fill=cor)
    caixa = desenho.textbbox(posicao, conteudo, font=fonte)
    return caixa[3] - posicao[1]


def desenhar_ficha(analise: AnaliseDoDeck, nome_do_deck: str) -> Image.Image:
    """Folha A4 com o veredito por modalidade e as cartas que travam."""
    folha = Image.new("RGB", (A4_LARGURA_PX, A4_ALTURA_PX), "white")
    desenho = ImageDraw.Draw(folha)

    titulo = _fonte(FONTES_NEGRITO, TAMANHO_TITULO_MM)
    secao = _fonte(FONTES_NEGRITO, TAMANHO_SECAO_MM)
    corpo = _fonte(FONTES_NORMAIS, TAMANHO_CORPO_MM)
    corpo_forte = _fonte(FONTES_NEGRITO, TAMANHO_CORPO_MM)
    miudo = _fonte(FONTES_NORMAIS, TAMANHO_MIUDO_MM)

    margem = mm_para_px(MARGEM_MM)
    largura_util = A4_LARGURA_PX - margem * 2
    y = margem

    y += _texto(desenho, (margem, y), "Modalidades do deck", titulo) + mm_para_px(2)
    liberados = analise.formatos_liberados
    resumo = (
        ", ".join(v.rotulo for v in liberados)
        if liberados
        else "nenhum formato sancionado - deck casual"
    )
    y += _texto(
        desenho,
        (margem, y),
        f"{nome_do_deck} · {analise.total_de_cartas} cartas · entra em: {resumo}",
        corpo,
        COR_APAGADA,
    ) + mm_para_px(6)

    desenho.line([(margem, y), (margem + largura_util, y)], fill=COR_LINHA, width=4)
    y += mm_para_px(5)

    # --- veredito por formato ---
    coluna_estado = margem + mm_para_px(34)
    coluna_motivo = margem + mm_para_px(48)
    for veredito in analise.vereditos:
        _texto(desenho, (margem, y), veredito.rotulo, corpo_forte)
        _texto(
            desenho,
            (coluna_estado, y),
            "SIM" if veredito.pode_entrar else "NAO",
            corpo_forte,
            COR_SIM if veredito.pode_entrar else COR_NAO,
        )
        motivo = "; ".join(veredito.impedimentos) if veredito.impedimentos else "sem impedimento"
        altura = _texto(
            desenho,
            (coluna_motivo, y),
            motivo,
            corpo,
            COR_APAGADA if veredito.pode_entrar else COR_TEXTO,
        )
        y += altura + mm_para_px(3.4)

    y += mm_para_px(4)
    desenho.line([(margem, y), (margem + largura_util, y)], fill=COR_LINHA, width=4)
    y += mm_para_px(5)

    # --- cartas que travam ---
    if analise.sem_consulta:
        _texto(
            desenho,
            (margem, y),
            f"O Scryfall nao devolveu a legalidade de {analise.sem_consulta} carta(s); "
            "a lista abaixo pode estar incompleta.",
            corpo,
            COR_NAO,
        )
        y += mm_para_px(6)

    if not analise.travadas:
        _texto(
            desenho,
            (margem, y),
            "Nenhuma carta do deck e ilegal nos formatos acima.",
            corpo,
            COR_APAGADA,
        )
    else:
        y += _texto(desenho, (margem, y), "Cartas que travam", secao) + mm_para_px(3.5)

        mostradas = analise.travadas[:LIMITE_DE_TRAVADAS]
        restantes = len(analise.travadas) - len(mostradas)
        por_coluna = (len(mostradas) + 1) // 2
        largura_coluna = largura_util // 2
        topo = y
        altura_linha = mm_para_px(7.4)

        for indice, travada in enumerate(mostradas):
            coluna, linha = divmod(indice, por_coluna) if por_coluna else (0, indice)
            x = margem + coluna * largura_coluna
            alvo = topo + linha * altura_linha
            _texto(desenho, (x, alvo), travada.nome, corpo)
            _texto(
                desenho,
                (x, alvo + mm_para_px(3.5)),
                " ".join(NOME_DO_FORMATO.get(f, f) for f in travada.formatos),
                miudo,
                COR_NAO,
            )

        y = topo + por_coluna * altura_linha + mm_para_px(2)
        if restantes:
            y += _texto(desenho, (margem, y), f"... e mais {restantes} carta(s).", miudo, COR_APAGADA)

    rodape = (
        "Legalidade por carta conforme o Scryfall. Tamanho de deck, limite de copias e "
        "singleton conferidos pelas regras de construcao de cada formato."
    )
    y_rodape = A4_ALTURA_PX - margem - mm_para_px(TAMANHO_MIUDO_MM)
    desenho.line([(margem, y_rodape - mm_para_px(3)), (margem + largura_util, y_rodape - mm_para_px(3))],
                 fill=COR_LINHA, width=4)
    _texto(desenho, (margem, y_rodape), rodape, miudo, COR_APAGADA)
    return folha
