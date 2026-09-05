// O nome nao pode ser trocado antes de importCard(): o changeCardIndex() usa o
// nome pra buscar os dados da impressao e, com um nome que o Scryfall nao acha,
// o campo do ilustrador volta vazio e o credito some da carta. Trocar o texto
// do titulo depois do import nao passa por busca nenhuma.
(nome) => {
    if (card.text.title) {
        card.text.title.text = nome;
    }
}
