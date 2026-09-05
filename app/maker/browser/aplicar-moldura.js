// autoFrame() e cardFrameProperties() (do proprio gerador) decidem a moldura
// procurando "Land", "Artifact", "Vehicle", "Creature" e "Add" DENTRO da linha
// de tipo e do texto de regras, tudo literal em ingles. Com a carta em
// portugues nenhuma dessas comparacoes bate: terreno vira moldura de artefato,
// veiculo perde a caixa de P/R propria, e a cor do terreno (que sai do "Add"
// do texto) nunca e encontrada. Emprestar a linha de tipo e o texto em ingles
// so durante a chamada resolve todas de uma vez, sem tocar em vendor/.
//
// Restaurar logo depois e seguro porque as funcoes de moldura recebem o texto
// por argumento - o valor ja foi lido quando esta linha roda. E escrever em
// card.text[...].text direto (em vez de passar pela caixa de texto da
// interface) nao dispara textEdited(), que agendaria um autoFrame() novo, com
// o portugues de volta, 500ms depois.
(args) => {
    const tipoPt = card.text.type.text;
    const regrasPt = card.text.rules.text;
    card.text.type.text = args.tipoIngles;
    card.text.rules.text = args.regrasIngles;
    autoFrame();
    card.text.type.text = tipoPt;
    card.text.rules.text = regrasPt;
}
