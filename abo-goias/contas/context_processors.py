from django.http import HttpRequest


def usuario_logado(request: HttpRequest) -> dict:
    """Injeta o usuário autenticado em todos os templates como ``usuario_logado``.

    Permite que o base.html exiba o nome do usuário e o botão de logout sem
    que cada view precise passar ``usuario_logado`` manualmente no contexto.
    Quando a view já passa a variável explicitamente, o valor da view prevalece.
    """
    return {"usuario_logado": request.user if request.user.is_authenticated else None}
