// writeText() troca a ultima letra por um glifo decorativo (area privada do
// Unicode) quando a fonte do campo e exatamente 'belerenb' e a palavra termina
// em f/h/m/n/k, e esse glifo sai como caixa vazia no Chromium do Playwright.
// E so floreio: registrar a MESMA fonte sob outro nome escapa do gatilho, que
// testa o nome literal.
(nomeDaFonte) => {
    Object.values(card.text).forEach((campo) => {
        if (campo.font === 'belerenb') {
            campo.font = nomeDaFonte;
        }
    });
}
