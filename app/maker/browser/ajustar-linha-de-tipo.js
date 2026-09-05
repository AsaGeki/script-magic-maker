// A caixa da linha de tipo vai ate a borda direita da carta, passando por baixo
// do simbolo de edicao. Como o campo e oneLine, o gerador encolhe a fonte ate
// caber na LARGURA da caixa - e cabendo ali, ainda assim invade o simbolo. Em
// ingles quase nao aparece; em portugues a linha e mais longa ("Criatura
// Lendaria - Dinossauro Anciao") e a ultima palavra sai por baixo do simbolo.
// Encurtar a caixa antes do simbolo faz o mesmo encolhimento resolver sozinho.
() => {
    const tipo = card.text.type;
    if (!tipo || card.setSymbolX == null) { return; }
    const folga = card.width * 0.012;
    const inicioDoSimbolo = card.width * card.setSymbolX;
    const fimDoTipo = card.width * (tipo.x + tipo.width);
    if (fimDoTipo > inicioDoSimbolo - folga) {
        tipo.width = (inicioDoSimbolo - folga) / card.width - tipo.x;
    }
}
