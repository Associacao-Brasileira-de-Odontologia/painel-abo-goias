"""Diagnóstico completo do envio de contratos ao Dental Office.

Uso:
    python manage.py testar_envio_dental              # usa o contrato mais recente
    python manage.py testar_envio_dental --contrato 5  # usa contrato com pk=5
    python manage.py testar_envio_dental --apenas-auth # só testa autenticação
"""

from __future__ import annotations

import base64
import json

from django.core.management.base import BaseCommand, CommandError
from gestao_lab.integrations.dental import DentalAPIError, DentalClient


class Command(BaseCommand):
    help = (
        "Testa o envio de contrato ao Dental Office e exibe a resposta completa da API."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--contrato",
            type=int,
            default=None,
            metavar="PK",
            help="PK do ContratoGerado a testar. Padrão: contrato mais recente.",
        )
        parser.add_argument(
            "--apenas-auth",
            action="store_true",
            help="Apenas testa a autenticação, sem enviar documento.",
        )

    def handle(self, *args, **options):
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write("  DIAGNÓSTICO — Envio ao Dental Office")
        self.stdout.write("=" * 60 + "\n")

        # ── 1. Autenticação ────────────────────────────────────────────
        self.stdout.write(self.style.MIGRATE_HEADING("1. Autenticação"))
        try:
            from gestao_lab.integrations.dental import carregar_config_dental

            config = carregar_config_dental()
            self.stdout.write(f"   auth_url  : {config.auth_url}")
            self.stdout.write(f"   base_url  : {config.base_url}")
            self.stdout.write(f"   client_id : {config.client_id[:6]}****")
            self.stdout.write(f"   verify_tls: {config.verify_tls}")
        except DentalAPIError as exc:
            raise CommandError(f"Configuração inválida: {exc}")

        try:
            client = DentalClient(config)
            token = client._autenticar()
            self.stdout.write(
                self.style.SUCCESS(f"   OK Token obtido: {token[:20]}...")
            )
        except DentalAPIError as exc:
            raise CommandError(f"Falha na autenticação: {exc}")

        if options["apenas_auth"]:
            self.stdout.write("\nFinalizado (--apenas-auth).")
            return

        # ── 2. Carregar contrato ───────────────────────────────────────
        self.stdout.write(self.style.MIGRATE_HEADING("\n2. Contrato"))
        from gestao_contratos.models import ContratoGerado

        pk = options["contrato"]
        if pk:
            try:
                contrato = ContratoGerado.objects.select_related("paciente").get(pk=pk)
            except ContratoGerado.DoesNotExist:
                raise CommandError(f"Contrato pk={pk} não encontrado.")
        else:
            contrato = (
                ContratoGerado.objects.select_related("paciente")
                .order_by("-criado_em")
                .first()
            )
            if not contrato:
                raise CommandError(
                    "Nenhum contrato no banco. Gere um contrato primeiro."
                )

        paciente = contrato.paciente
        self.stdout.write(f"   pk           : {contrato.pk}")
        self.stdout.write(f"   tipo         : {contrato.get_tipo_display()}")
        self.stdout.write(f"   paciente     : {paciente.nome}")
        self.stdout.write(f"   id_dental    : {paciente.id_dental!r}")
        arq = contrato.arquivo.name if contrato.arquivo else "(vazio)"
        arq_pdf = contrato.arquivo_pdf.name if contrato.arquivo_pdf else "(vazio)"
        self.stdout.write(f"   arquivo      : {arq}")
        self.stdout.write(f"   arquivo_pdf  : {arq_pdf}")
        self.stdout.write(f"   status_dental: {contrato.status_envio_dental}")

        if not paciente.id_dental:
            raise CommandError(
                "Paciente sem id_dental — impossível enviar ao Dental Office."
            )

        # ── 3. Obter bytes do documento ────────────────────────────────
        self.stdout.write(self.style.MIGRATE_HEADING("\n3. Leitura do arquivo"))
        arquivo_bytes: bytes | None = None
        extensao = "docx"

        if contrato.arquivo_pdf:
            try:
                contrato.arquivo_pdf.open("rb")
                arquivo_bytes = contrato.arquivo_pdf.read()
                contrato.arquivo_pdf.close()
                extensao = "pdf"
                self.stdout.write(
                    self.style.SUCCESS(f"   OK PDF lido: {len(arquivo_bytes):,} bytes")
                )
            except Exception as exc:
                self.stdout.write(
                    self.style.WARNING(f"   AVISO Falha ao ler PDF: {exc}")
                )

        if not arquivo_bytes and contrato.arquivo:
            try:
                contrato.arquivo.open("rb")
                arquivo_bytes = contrato.arquivo.read()
                contrato.arquivo.close()
                self.stdout.write(
                    self.style.SUCCESS(f"   OK DOCX lido: {len(arquivo_bytes):,} bytes")
                )
            except Exception as exc:
                self.stdout.write(
                    self.style.WARNING(f"   AVISO Falha ao ler DOCX: {exc}")
                )

        if not arquivo_bytes:
            self.stdout.write("   Nenhum arquivo salvo — regenerando DOCX...")
            from gestao_contratos.services.documentos import gerar_contrato

            try:
                arquivo_bytes = gerar_contrato(
                    paciente=paciente,
                    tipo=contrato.tipo,
                    observacoes_clinicas=contrato.observacoes_clinicas,
                    profissional_nome=contrato.profissional_nome,
                    profissional_cro=contrato.profissional_cro,
                    local_assinatura=contrato.local_assinatura,
                )
                self.stdout.write(
                    self.style.SUCCESS(
                        f"   OK DOCX regenerado: {len(arquivo_bytes):,} bytes"
                    )
                )
            except Exception as exc:
                raise CommandError(f"Falha ao gerar documento: {exc}")

        # ── 3b. Converter para PDF se ainda for DOCX ───────────────────
        if extensao == "docx":
            from gestao_contratos.services.pdf_converter import (
                docx_para_pdf,
                pdf_converter_disponivel,
            )

            if pdf_converter_disponivel():
                self.stdout.write("   Convertendo DOCX para PDF...")
                try:
                    arquivo_bytes = docx_para_pdf(arquivo_bytes)
                    extensao = "pdf"
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"   OK PDF gerado: {len(arquivo_bytes):,} bytes"
                        )
                    )
                except RuntimeError as exc:
                    self.stdout.write(
                        self.style.WARNING(
                            f"   AVISO Conversao PDF falhou, enviando DOCX: {exc}"
                        )
                    )
            else:
                self.stdout.write(
                    self.style.WARNING(
                        "   AVISO LibreOffice/Word nao disponivel"
                        " — enviando DOCX (API pode rejeitar)."
                    )
                )

        # ── 4. Envio à API ─────────────────────────────────────────────
        self.stdout.write(self.style.MIGRATE_HEADING("\n4. Envio ao Dental Office"))
        nome_arquivo = (
            f"TESTE Termo {contrato.get_tipo_display()} "
            f"{paciente.nome.split()[0].title()}.{extensao}"
        )
        base = config.base_url.rstrip("/")
        self.stdout.write(
            f"   endpoint     : POST {base}/customers/{paciente.id_dental}/docs"
        )
        self.stdout.write(f"   nome_arquivo : {nome_arquivo!r}")
        self.stdout.write(f"   tamanho      : {len(arquivo_bytes):,} bytes")
        self.stdout.write(
            f"   base64       : {len(base64.b64encode(arquivo_bytes)):,} chars"
        )

        try:
            resposta = client.enviar_documento_paciente(
                id_dental=paciente.id_dental,
                arquivo_bytes=arquivo_bytes,
                nome=nome_arquivo,
                descricao="Teste de diagnóstico via management command.",
                tag_list="contrato",
            )
        except DentalAPIError as exc:
            self.stdout.write(self.style.ERROR(f"   FALHA Erro HTTP/rede: {exc}"))
            raise CommandError(str(exc))

        self.stdout.write(
            self.style.SUCCESS("   OK Requisição concluída sem erro HTTP")
        )
        self.stdout.write("\n   Resposta da API (JSON):")
        self.stdout.write(
            "   "
            + json.dumps(resposta, ensure_ascii=False, indent=4).replace("\n", "\n   ")
        )

        # ── 5. Verificar se há erro na resposta ────────────────────────
        self.stdout.write(self.style.MIGRATE_HEADING("\n5. Análise da resposta"))
        from gestao_contratos.services.envio_dental import _extrair_erro_resposta

        erro = _extrair_erro_resposta(resposta)
        if erro:
            self.stdout.write(self.style.ERROR(f"   FALHA API retornou erro: {erro}"))
        else:
            self.stdout.write(
                self.style.SUCCESS("   OK Nenhum erro detectado na resposta")
            )
            self.stdout.write(
                "   O documento foi enviado com sucesso ao Dental Office."
            )

        self.stdout.write("\n" + "=" * 60 + "\n")
