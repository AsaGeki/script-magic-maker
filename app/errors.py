"""Erros de domínio conhecidos - diferente de bug (500), são situações
esperadas (carta não encontrada, dado inválido) que a API converte pra uma
resposta HTTP tratada em vez de deixar estourar como erro interno."""


class AppError(Exception):
    status_code = 400

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class NotFoundError(AppError):
    status_code = 404


class BadRequestError(AppError):
    status_code = 400


class ConflictError(AppError):
    status_code = 409


class UpstreamError(AppError):
    """Falha ao falar com serviço de fora (Scryfall, MTGPics)."""

    status_code = 502
