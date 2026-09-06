// A cor entra antes da imagem: uploadWatermark() so reposiciona no onload, e
// watermarkLeftColor() ja redesenha com o que estiver carregado.
// A opacidade padrao do gerador e 0.4, pensada pra marca d'agua de guilda atras
// do texto. No terreno basico o simbolo e o unico elemento da caixa e sai quase
// opaco na carta impressa.
(args) => {
    document.querySelector('#watermark-opacity').value = args.opacidade;
    card.watermarkOpacity = args.opacidade / 100;
    document.querySelector('#watermark-left').value = args.cor;
    watermarkLeftColor(args.cor);
    uploadWatermark(args.imagem, 'resetWatermark');
}
