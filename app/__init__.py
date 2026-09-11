"""Pacote da aplicacao.

O import daqui e o portao de qualidade: lint, formato e tipagem rodam antes de
qualquer coisa do projeto existir na memoria (ver app.qualidade). Fica neste
`__init__` de proposito - CLI, API e scripts todos passam por aqui, entao nao
ha entrada nova que possa esquecer de chamar.
"""

from app.qualidade import garantir_codigo_limpo

garantir_codigo_limpo()
