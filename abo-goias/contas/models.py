"""Modelos da aplicacao de contas.

A aplicacao de contas cuida de login, logout, recuperacao/troca de senha e
do perfil do usuario autenticado, mas nao possui tabelas proprias: usa
``django.contrib.auth.models.User`` e ``django.contrib.auth.models.Group``
diretamente.

Este modulo permanece documentado para deixar claro que a ausencia de
classes de modelo e intencional.
"""
