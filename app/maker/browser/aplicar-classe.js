// A moldura de classe reparte a coluna de texto em niveis de altura variavel.
// O texto de cada nivel sai do preencherNiveisDeClasse, que corta pelas marcas
// de secao do Scryfall; a altura de cada um sai daqui, nos campos que o painel
// de classe deixa pra preencher.
//
// O gerador so chama o preencherNiveisDeClasse durante o import, e ali os
// campos de nivel ainda nao existem - a moldura vem depois. Por isso o texto e
// repartido aqui, do que ficou guardado ainda com as marcas (ver
// texto-com-marca-de-secao-guardado).
//
// Os campos de altura so existem com o versionClass.js carregado, entao a
// espera abaixo e por ele, nao por rede.
() => {
    // Onde a coluna termina, e o cabecalho de custo e nome que o classEdited()
    // soma sozinho antes de cada nivel - por isso ele nao entra nas alturas.
    const FIM = 0.8368;
    const CABECALHO = 0.0481;

    const preencher = () => {
        preencherNiveisDeClasse('', card.textoComSecoes || '');
        const textos = [0, 1, 2, 3]
            .map((i) => card.text['level' + i + 'c'].text || '')
            .filter((texto, i) => i === 0 || texto);
        const sobra = FIM - card.text.level0c.y - (textos.length - 1) * CABECALHO;
        const pesos = textos.map((texto) => Math.max(texto.length, 40));
        const soma = pesos.reduce((a, b) => a + b, 0);
        for (let i = 0; i < 4; i++) {
            const altura = i < textos.length ? (sobra * pesos[i]) / soma : 0;
            document.querySelector('#class-height-' + i).value = Math.round(altura * card.height);
        }
        classEdited();
    };

    return new Promise((resolve, reject) => {
        const inicio = Date.now();
        const tentar = () => {
            if (document.querySelector('#class-height-3') && typeof classEdited == 'function') {
                preencher();
                resolve();
            } else if (Date.now() - inicio > 10000) {
                reject(new Error('versionClass.js nao carregou'));
            } else {
                setTimeout(tentar, 50);
            }
        };
        tentar();
    });
}
