// Depois do import, de proposito: o changeCardIndex() busca os dados da
// impressao pelo nome, e um nome que o Scryfall nao acha volta sem o campo do
// ilustrador.
(nome) => {
    if (card.text.title) {
        card.text.title.text = nome;
    }
}
