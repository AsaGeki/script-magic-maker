// Amostra reduzida do canvas, usada so pra saber se o desenho parou de mudar.
// A altura tem que dar pelo menos um pixel a uma linha do rodape: menor que
// isso ela se dissolve no fundo, duas leituras saem iguais e o desenho e dado
// por pronto antes de o rodape existir.
() => {
    if (typeof cardCanvas === 'undefined' || !cardCanvas.width) { return null; }
    const mini = document.createElement('canvas');
    mini.width = 200;
    mini.height = 280;
    mini.getContext('2d').drawImage(cardCanvas, 0, 0, mini.width, mini.height);
    return mini.toDataURL();
}
