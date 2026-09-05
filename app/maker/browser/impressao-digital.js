// Amostra reduzida do canvas, usada so pra saber se o desenho parou de mudar.
() => {
    if (typeof cardCanvas === 'undefined' || !cardCanvas.width) { return null; }
    const mini = document.createElement('canvas');
    mini.width = 32;
    mini.height = 44;
    mini.getContext('2d').drawImage(cardCanvas, 0, 0, mini.width, mini.height);
    return mini.toDataURL();
}
