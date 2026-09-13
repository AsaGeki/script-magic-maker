// A moldura de nivel reparte a caixa de regras em tres faixas: a de cima com o
// custo de subir de nivel, e as duas de baixo com o que a criatura ganha em
// cada intervalo, cada uma com poder/resistencia proprio. O import do gerador
// escreve tudo junto na caixa de regras, entao a separacao sai daqui - do texto
// ja formatado, pra nao perder o italico do lembrete.
//
// A marca de faixa e a unica linha que termina em intervalo ("NIVEL 1-3",
// "LEVEL 4+"), e o poder/resistencia daquela faixa vem na linha seguinte.
() => {
    const FAIXA = /^(.*?)\s*(\d+-\d+|\d+\+)$/;
    // A palavra e o intervalo dividem a aba em duas linhas; a segunda e menor.
    const ALTURA_DO_INTERVALO = 0.0162;

    const linhas = card.text.rules.text.split('\n');
    const marcas = [];
    linhas.forEach((linha, i) => {
        if (FAIXA.test(linha)) {
            marcas.push(i);
        }
    });
    // Fora do formato esperado a carta segue com o texto inteiro na primeira
    // faixa, em vez de sair repartida errado.
    if (marcas.length !== 2) {
        return drawTextBuffer();
    }

    card.text.rules.text = linhas.slice(0, marcas[0]).join('\n');
    marcas.forEach((marca, ordem) => {
        const achado = linhas[marca].match(FAIXA);
        const fim = ordem + 1 < marcas.length ? marcas[ordem + 1] : linhas.length;
        const campo = ordem + 2;
        card.text['level' + campo].text =
            achado[1] + '\n{fontsize' + scaleHeight(ALTURA_DO_INTERVALO) + '}' + achado[2];
        card.text['pt' + campo].text = linhas[marca + 1];
        card.text['rules' + campo].text = linhas.slice(marca + 2, fim).join('\n');
    });
    return drawTextBuffer();
}
