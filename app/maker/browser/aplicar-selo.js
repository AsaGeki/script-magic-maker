// O selo holografico do rodape da caixa de regras. As imagens estao no gerador
// (pacote M15HoloStamps e pasta ub/regular/stamp), mas nenhuma moldura
// automatica poe a camada - quem sabe se a impressao leva selo, e de que
// formato, e o Scryfall.
//
// A cor e a da moldura, tirada do card.frames. Caixa de poder/resistencia e
// coroa de lendaria ficam de fora: tem cor propria e vem antes na pilha.
(args) => {
    const CORES = {
        'White': 'W', 'Blue': 'U', 'Black': 'B', 'Red': 'R', 'Green': 'G',
        'Multicolored': 'M', 'Artifact': 'A', 'Land': 'L', 'Colorless': 'C'
    };
    const DESENHOS = {
        'oval': {
            src: (letra) => '/img/frames/m15/holoStamps/m15HoloStamp' + letra + '.png',
            bounds: {x: 0.436, y: 0.9034, width: 0.128, height: 0.0458}
        },
        'triangle': {
            src: (letra) => '/img/frames/m15/ub/regular/stamp/' + letra.toLowerCase() + '.png',
            bounds: {x: 0.4254, y: 0.9005, width: 0.1494, height: 0.0486}
        }
    };

    const desenho = DESENHOS[args.formato];
    if (!desenho) { return null; }

    const daMoldura = card.frames.find((quadro) => {
        const nome = quadro.name || '';
        if (/Power\/Toughness|Crown|Cover|Stamp/.test(nome)) { return false; }
        return CORES[nome.split(' ')[0]] !== undefined;
    });
    if (!daMoldura) { return null; }

    const cor = daMoldura.name.split(' ')[0];
    const selo = {
        'name': cor + ' Holo Stamp',
        'src': desenho.src(CORES[cor]),
        'masks': [],
        'bounds': desenho.bounds
    };
    card.frames.unshift(selo);
    addFrame([], selo);
    return selo.src;
}
