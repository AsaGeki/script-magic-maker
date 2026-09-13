// Os quatro campos do rodape que a excecao a mao pode sobrescrever (ver
// excecoes.toml). O gerador so redesenha o rodape no bottomInfoEdited(), entao
// escrever no campo sem chamar ele nao muda a imagem.
(args) => {
    for (const [id, valor] of Object.entries(args.campos)) {
        const campo = document.querySelector('#' + id);
        if (campo) {
            campo.value = valor;
        }
    }
    return bottomInfoEdited();
}
