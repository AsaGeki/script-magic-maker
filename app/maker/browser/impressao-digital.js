// Amostra reduzida do canvas, usada so pra saber se o desenho parou de mudar.
//
// A altura precisa ser grande o bastante pra que uma linha do rodape (o numero
// do colecionador, o credito do ilustrador) ocupe pelo menos um pixel: numa
// amostra menor a linha se dissolve no fundo, duas leituras seguidas saem
// iguais e o desenho e dado como pronto antes de o rodape existir.
() => {
    if (typeof cardCanvas === 'undefined' || !cardCanvas.width) { return null; }
    const mini = document.createElement('canvas');
    mini.width = 200;
    mini.height = 280;
    mini.getContext('2d').drawImage(cardCanvas, 0, 0, mini.width, mini.height);
    return mini.toDataURL();
}
