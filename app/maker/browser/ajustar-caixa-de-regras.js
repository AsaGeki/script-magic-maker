// O gerador encolhe a fonte ate o texto caber na ALTURA da caixa de regras, e
// essa caixa (0.9178 nas molduras M15, Borderless e Etched) desce por tras do
// que a moldura escreve embaixo dela: poder/resistencia (0.902), selo
// holografico (0.9005 no triangular, 0.9034 no oval), o P/R do outro lado na
// transformada (0.842) e a faixa da modal (0.892). Baixar o fim dela ate o que
// vier primeiro faz o encolhimento parar antes de invadir.
//
// So conta quem divide coluna com o texto: na moldura de nivel o
// poder/resistencia fica ao lado da faixa, e nao embaixo - encurtar por causa
// dele espremeria a caixa em um quarto da altura.
//
// Caixa girada fica de fora, e caixa girada nenhuma e ajustada: com rotacao o
// x e o y sao a ancora de onde o texto sai, e a largura cresce no eixo virado,
// entao "embaixo" e "na mesma coluna" apontam pra outro lugar. Na moldura
// dividida a linha de tipo cairia dentro da caixa de regras e a zeraria.
() => {
    const regras = card.text.rules;
    if (!regras || regras.rotation) { return; }

    const folga = 0.004;
    const fim = regras.y + regras.height;
    const mesmaColuna = (caixa) =>
        caixa.x < regras.x + regras.width && regras.x < caixa.x + caixa.width;
    const dentro = (caixa) => caixa.y > regras.y && caixa.y < fim;

    const limites = [];
    Object.entries(card.text).forEach(([nome, caixa]) => {
        if (
            nome !== 'rules'
            && caixa.text
            && !caixa.rotation
            && dentro(caixa)
            && mesmaColuna(caixa)
        ) {
            limites.push(caixa.y - folga);
        }
    });
    const selo = card.frames.find((quadro) => (quadro.name || '').includes('Holo Stamp'));
    if (selo && selo.bounds && mesmaColuna(selo.bounds)) { limites.push(selo.bounds.y - folga); }
    if (!limites.length) { return; }

    const limite = Math.min(...limites);
    if (fim > limite) {
        regras.height = limite - regras.y;
    }
}
