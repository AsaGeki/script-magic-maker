// A moldura de planeswalker troca a caixa de regras por ate quatro blocos de
// habilidade, cada um com o custo de lealdade desenhado na lateral. Quem desenha
// as faixas e os simbolos e o versionPlaneswalker.js, a partir da altura e do
// custo de cada bloco; aqui so entram os valores.
//
// O gerador reparte esse texto durante o import, mas ali os campos de habilidade
// ainda nao existem - a moldura vem depois. Por isso o corte sai daqui, do texto
// que ele guardou (ver texto-com-marca-de-secao-guardado).
//
// Os campos vivem no painel que o versionPlaneswalker.js acrescenta ao carregar,
// entao a espera abaixo e por ele, nao por rede.
(args) => {
    // Custo de lealdade: "+1:", "0:", "−7:" (o Scryfall usa o sinal de menos de
    // verdade) e "−X:". Linha sem isso e habilidade estatica, que sai sem
    // simbolo.
    const CUSTO = /^([+−-]?[0-9X]+):\s*([\s\S]*)$/;
    const BLOCOS = 4;
    // A coluna de habilidades vai do topo da caixa (card.text.ability0.y) ate
    // onde a lateral dela ainda e reta: na mascara (planeswalker/text.svg) isso
    // e 1877.7 de 2100, e dali pra baixo ela curva pro canto arredondado. Texto
    // depois disso sai por fora da caixa.
    const FIM = 1877.7 / 2100;
    // O gerador reparte essa coluna em partes iguais e vai ate 0.2915 a partir
    // do mesmo topo; e nessa medida que as posicoes dos simbolos de lealdade
    // foram calibradas (ver planeswalkerAbilityLayout).
    const COLUNA_CALIBRADA = 0.2915;

    const preencher = () => {
        const linhas = (card.textoComSecoes || '').split('\n').filter((linha) => linha.trim());
        // Mais habilidades do que blocos: as duas ultimas entram juntas, como o
        // gerador faz no import.
        while (linhas.length > BLOCOS) {
            const ultima = linhas.pop();
            linhas[linhas.length - 1] += '\n' + ultima;
        }
        const textos = linhas.map((linha) => {
            const achado = linha.match(CUSTO);
            return {
                custo: achado ? achado[1].replace('−', '-') : '',
                texto: achado ? achado[2] : linha,
            };
        });

        // A carta impressa mantem a mesma letra em todos os blocos e varia a
        // altura de cada faixa; repartir a coluna em partes iguais deixaria a
        // habilidade curta enorme e a longa ilegivel. O piso e pra habilidade de
        // uma linha nao virar uma tira.
        const PISO = 40;
        const inicio = card.text.ability0.y;
        const pesos = textos.map((bloco) => Math.max(bloco.texto.length, PISO));
        const soma = pesos.reduce((a, b) => a + b, 0);
        const alturas = pesos.map((peso) => ((FIM - inicio) * peso) / soma);

        // O simbolo de lealdade fica em posicao fixa por contagem de blocos (ver
        // planeswalkerAbilityLayout), calibrada para blocos de altura igual. A
        // fracao do bloco onde ele cai nessa calibragem e o que se mantem quando
        // as alturas mudam; o desvio vai no campo de deslocamento.
        const alturaIgual = COLUNA_CALIBRADA / textos.length;
        const calibrado = planeswalkerAbilityLayout[0][textos.length - 1];
        const fracao = calibrado.map((y, i) => (y - (inicio + i * alturaIgual)) / alturaIgual);

        let topo = inicio;
        for (let i = 0; i < BLOCOS; i++) {
            const bloco = textos[i];
            card.text['ability' + i].text = bloco ? bloco.texto : '';
            document.querySelector('#planeswalker-cost-' + i).value = bloco ? bloco.custo : '';
            document.querySelector('#planeswalker-height-' + i).value = bloco
                ? Math.round(alturas[i] * card.height)
                : 0;
            document.querySelector('#planeswalker-shift-' + i).value = bloco
                ? Math.round((topo + fracao[i] * alturas[i] - calibrado[i]) * card.height)
                : 0;
            topo += bloco ? alturas[i] : 0;
        }
        card.text.loyalty.text = args.lealdade;
        planeswalkerEdited();
    };

    return new Promise((resolve, reject) => {
        const inicio = Date.now();
        const tentar = () => {
            if (
                document.querySelector('#planeswalker-height-3') &&
                typeof planeswalkerEdited == 'function'
            ) {
                preencher();
                resolve();
            } else if (Date.now() - inicio > 10000) {
                reject(new Error('versionPlaneswalker.js nao carregou'));
            } else {
                setTimeout(tentar, 50);
            }
        };
        tentar();
    });
}
