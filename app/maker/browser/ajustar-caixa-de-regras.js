// O gerador encolhe a fonte ate o texto caber na ALTURA da caixa de regras, e
// essa caixa (0.9178 nas molduras M15, Borderless e Etched) desce por tras da
// caixa de poder/resistencia (0.902) e do selo holografico (0.9005 no
// triangular, 0.9034 no oval). Baixar o fim dela ate o que vier primeiro faz o
// encolhimento parar antes de invadir.
() => {
    const regras = card.text.rules;
    if (!regras) { return; }

    const folga = 0.004;
    const limites = [];
    const pr = card.text.pt;
    if (pr && pr.text) { limites.push(pr.y - folga); }
    const selo = card.frames.find((quadro) => (quadro.name || '').includes('Holo Stamp'));
    if (selo && selo.bounds) { limites.push(selo.bounds.y - folga); }
    if (!limites.length) { return; }

    const limite = Math.min(...limites);
    if (regras.y + regras.height > limite) {
        regras.height = limite - regras.y;
    }
}
