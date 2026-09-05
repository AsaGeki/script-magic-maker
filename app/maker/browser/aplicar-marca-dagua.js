// A cor entra antes da imagem: uploadWatermark() so reposiciona no onload, e
// watermarkLeftColor() ja redesenha com o que estiver carregado.
(args) => {
    document.querySelector('#watermark-left').value = args.cor;
    watermarkLeftColor(args.cor);
    uploadWatermark(args.imagem, 'resetWatermark');
}
