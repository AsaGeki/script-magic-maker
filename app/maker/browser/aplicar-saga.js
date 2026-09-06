// A moldura de saga troca a caixa de regras por quatro blocos numerados. Quem
// desenha o numeral e a divisoria e o versionSaga.js, a partir da altura e da
// contagem de capitulos de cada bloco; aqui so entram os valores.
//
// Os campos vivem no painel que o versionSaga.js acrescenta ao carregar, entao
// a espera abaixo e por ele, nao por rede.
(args) => {
    const { lembrete, blocos } = args;
    // Espaco entre o fim do lembrete e a linha de tipo, e altura que um numeral
    // ocupa: um bloco de tres capitulos leva tres numerais empilhados, e abaixo
    // disso eles vazam pra fora do bloco.
    const TOTAL = 0.5358;
    const POR_CAPITULO = 0.056;

    // Cada bloco leva primeiro o que os numerais dele exigem; so o que sobra e
    // repartido pelo tamanho do texto.
    const alturas = () => {
        const pisos = blocos.map((bloco) => bloco.capitulos * POR_CAPITULO);
        const sobra = TOTAL - pisos.reduce((a, b) => a + b, 0);
        if (sobra <= 0) {
            const excesso = pisos.reduce((a, b) => a + b, 0) / TOTAL;
            return pisos.map((piso) => piso / excesso);
        }
        const pesos = blocos.map((bloco) => bloco.texto.length);
        const soma = pesos.reduce((a, b) => a + b, 0);
        return pisos.map((piso, i) => piso + (sobra * pesos[i]) / soma);
    };

    const preencher = () => {
        card.text.reminder.text = lembrete ? '{i}' + lembrete : '';
        const altura = alturas();
        for (let i = 0; i < 4; i++) {
            card.text['ability' + i].text = blocos[i] ? blocos[i].texto : '';
            document.querySelector('#saga-height-' + i).value = Math.round((altura[i] || 0) * card.height);
            document.querySelector('#saga-chapters-' + i).value = blocos[i] ? blocos[i].capitulos : 0;
        }
        sagaEdited();
    };

    return new Promise((resolve, reject) => {
        const inicio = Date.now();
        const tentar = () => {
            if (document.querySelector('#saga-chapters-3') && typeof sagaEdited == 'function') {
                preencher();
                resolve();
            } else if (Date.now() - inicio > 10000) {
                reject(new Error('versionSaga.js nao carregou'));
            } else {
                setTimeout(tentar, 50);
            }
        };
        tentar();
    });
}
