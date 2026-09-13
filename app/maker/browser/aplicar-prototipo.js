// A moldura de prototipo tem uma faixa propria por cima da caixa de regras, com
// o custo alternativo, o lembrete e o poder/resistencia menores. O Scryfall
// manda tudo isso no mesmo texto, separado por uma marca de secao
// ("//PRT-Prototype_Mech//"), e o import escreve o conjunto na caixa de regras.
//
// O corte sai do texto que o gerador guardou ainda com a marca (ver
// texto-com-marca-de-secao-guardado): no campo de regras ela ja foi removida.
() => {
    const partes = (card.textoComSecoes || '').split(/^\/\/[^\/\n]+\/\/\r?\n?/m);
    // Fora do formato esperado a carta segue com o texto inteiro na caixa de
    // regras, em vez de sair repartida errado.
    if (partes.length < 2) {
        return drawTextBuffer();
    }
    const linhas = partes[1].split('\n').filter((linha) => linha.trim());
    // A historia entra depois do texto de regras, ja no campo: o texto guardado
    // e so a parte de regras.
    const historia = card.text.rules.text.split('{flavor}')[1];

    card.text.rules.text =
        partes[0].replace(/\n+$/, '') + (historia === undefined ? '' : '{flavor}' + historia);
    card.text.mana2.text = linhas[0];
    card.text.rules2.text = linhas[1];
    card.text.pt2.text = linhas[2];
    return drawTextBuffer();
}
