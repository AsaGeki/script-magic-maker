// A caixa da linha de tipo vai ate a borda direita, por baixo do simbolo de
// edicao. O campo e oneLine, entao a fonte encolhe ate caber na LARGURA - cabe,
// e ainda invade o simbolo. Encurtar a caixa antes dele resolve pelo mesmo
// encolhimento.
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
