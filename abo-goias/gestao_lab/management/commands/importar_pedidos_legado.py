"""Importa pedidos de material do sistema legado CODA.

Uso:
    python manage.py importar_pedidos_legado
    python manage.py importar_pedidos_legado --dry-run
    python manage.py importar_pedidos_legado --apenas-arquivo1
    python manage.py importar_pedidos_legado \\
        --arquivo1 "caminho/Lista de Pedidos Material.csv" \\
        --arquivo2 "caminho/Pedidos para acompanhar entrega.csv"

Coloque os dois arquivos CSV exportados do CODA em gestao_lab/fixtures/ antes
de executar o comando.

Arquivo 1 ("Lista de Pedidos Material.csv"):
    Tem dados completos: Paciente, Aluno, Laboratório, Equipe, Serviço, datas e
    status de faturamento. Todos os 65+ registros são importados com pacientes e
    alunos criados automaticamente usando origem=MANUAL.

Arquivo 2 ("Pedidos para acompanhar entrega.csv"):
    Tem ~250 registros históricos SEM colunas Paciente/Aluno. Importa usando
    registros-placeholder "Paciente (legado CODA)" e "Aluno (legado CODA)".
    Registros já importados pelo arquivo 1 (mesma chave lab+equipe+serviço+
    previsão) são ignorados automaticamente para evitar duplicatas.

O comando é idempotente: ao rodar novamente, registros com a mesma chave
(laboratorio, equipe, descricao_servico[:50], previsao_entrega) são ignorados.
"""

import csv
import hashlib
import io
from datetime import date as date_type
from datetime import datetime
from datetime import time as time_type
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from gestao_lab.models import (
    AlunoLab,
    Equipe,
    Laboratorio,
    OrigemDados,
    Paciente,
    PedidoMaterial,
)

# ─── Helpers de decodificação e parsing ──────────────────────────────────────


def _decode_coda(caminho: str) -> list[dict]:
    """Lê CSV exportado do CODA corrigindo mojibake UTF-8/Latin-1."""
    path = Path(caminho)
    if not path.exists():
        raise CommandError(f"Arquivo não encontrado: {caminho}")

    raw = path.read_bytes()

    # Tenta UTF-8 (com ou sem BOM)
    for enc in ("utf-8-sig", "utf-8"):
        try:
            return list(csv.DictReader(io.StringIO(raw.decode(enc))))
        except UnicodeDecodeError:
            continue

    # Mojibake: bytes UTF-8 salvos/lidos como Latin-1
    latin_text = raw.decode("latin-1")
    try:
        corrected = latin_text.encode("latin-1").decode("utf-8")
        return list(csv.DictReader(io.StringIO(corrected)))
    except (UnicodeDecodeError, UnicodeEncodeError):
        return list(csv.DictReader(io.StringIO(latin_text)))


def _parse_date(s: str) -> "date_type | None":
    if not s or not s.strip():
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _parse_bool(s: str) -> bool:
    return s.strip().lower() in ("true", "1", "yes", "sim")


def _coda_id(prefixo: str, nome: str) -> str:
    """ID estável e único para registros importados do CODA, derivado do nome."""
    digest = hashlib.md5(nome.strip().upper().encode()).hexdigest()[:12]
    return f"CODA-{prefixo}-{digest}"


def _norm_lab(nome: str) -> str:
    """Normaliza nome de laboratório: strip + uppercase + espaços simples."""
    return " ".join(nome.strip().upper().split())


def _chave_pedido(
    lab_pk: int, equipe_pk: int, previsao: "date_type", servico: str
) -> tuple:
    return (lab_pk, equipe_pk, previsao, servico[:50])


# ─── Command ─────────────────────────────────────────────────────────────────


class Command(BaseCommand):
    help = "Importa pedidos de material do sistema legado CODA (idempotente)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--arquivo1",
            default="gestao_lab/fixtures/Lista de Pedidos Material.csv",
            help="Caminho para 'Lista de Pedidos Material.csv'.",
        )
        parser.add_argument(
            "--arquivo2",
            default="gestao_lab/fixtures/Pedidos para acompanhar entrega.csv",
            help="Caminho para 'Pedidos para acompanhar entrega.csv'.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Mostra o que seria importado sem salvar no banco.",
        )
        parser.add_argument(
            "--apenas-arquivo1",
            action="store_true",
            help="Importa apenas o arquivo com dados completos (Paciente/Aluno).",
        )

    def handle(self, *args, **options):
        dry_run: bool = options["dry_run"]
        if dry_run:
            self.stdout.write(
                self.style.WARNING("  [DRY RUN] Nenhum dado será salvo.\n")
            )

        # Índices para lookup rápido
        indice_labs: dict[str, Laboratorio] = {
            _norm_lab(lab.nome): lab for lab in Laboratorio.objects.all()
        }
        indice_equipes: dict[str, Equipe] = {
            eq.nome.strip().upper(): eq for eq in Equipe.objects.all()
        }

        if not indice_labs:
            raise CommandError(
                "Nenhum laboratório encontrado. Execute 'importar_legado' primeiro."
            )

        # Pré-carrega chaves já existentes para deduplicação
        ja_importados: set[tuple] = set()
        for p in PedidoMaterial.objects.select_related("laboratorio", "equipe"):
            ja_importados.add(
                _chave_pedido(
                    p.laboratorio_id,
                    p.equipe_id,
                    p.previsao_entrega,
                    p.descricao_servico,
                )
            )

        # ── Arquivo 1: dados completos ────────────────────────────────────────
        self.stdout.write(f"\nArquivo 1: {options['arquivo1']}")
        rows1 = _decode_coda(options["arquivo1"])
        self.stdout.write(f"  {len(rows1)} registro(s) lido(s).")

        c1 = i1 = e1 = 0
        for row in rows1:
            result = self._importar_completo(
                row, indice_labs, indice_equipes, ja_importados, dry_run
            )
            if result == "criado":
                c1 += 1
            elif result == "ignorado":
                i1 += 1
            else:
                e1 += 1

        self.stdout.write(
            self.style.SUCCESS(f"  Criados: {c1}  Ignorados: {i1}  Erros: {e1}")
        )

        if options["apenas_arquivo1"]:
            self.stdout.write(self.style.SUCCESS(f"\nTotal importado: {c1} pedido(s)."))
            return

        # ── Arquivo 2: sem paciente/aluno ─────────────────────────────────────
        self.stdout.write(f"\nArquivo 2: {options['arquivo2']}")
        rows2 = _decode_coda(options["arquivo2"])
        self.stdout.write(f"  {len(rows2)} registro(s) lido(s).")

        pac_placeholder = alu_placeholder = None
        if not dry_run:
            pac_placeholder, criado = Paciente.objects.get_or_create(
                id_dental="CODA-LEGADO-PAC",
                defaults={
                    "nome": "Paciente (legado CODA)",
                    "ativo": True,
                    "origem": OrigemDados.MANUAL,
                },
            )
            if criado:
                self.stdout.write("  Paciente placeholder criado.")

            alu_placeholder, criado = AlunoLab.objects.get_or_create(
                id_dental="CODA-LEGADO-ALU",
                defaults={
                    "nome": "Aluno (legado CODA)",
                    "ativo": True,
                    "origem": OrigemDados.MANUAL,
                },
            )
            if criado:
                self.stdout.write("  Aluno placeholder criado.")

        c2 = i2 = e2 = 0
        for row in rows2:
            result = self._importar_sem_pessoa(
                row,
                indice_labs,
                indice_equipes,
                ja_importados,
                pac_placeholder,
                alu_placeholder,
                dry_run,
            )
            if result == "criado":
                c2 += 1
            elif result == "ignorado":
                i2 += 1
            else:
                e2 += 1

        self.stdout.write(
            self.style.SUCCESS(f"  Criados: {c2}  Ignorados: {i2}  Erros: {e2}")
        )

        total = c1 + c2
        self.stdout.write(self.style.SUCCESS(f"\nTotal importado: {total} pedido(s)."))

    # ─── Importação arquivo 1 ─────────────────────────────────────────────────

    def _importar_completo(
        self, row: dict, indice_labs, indice_equipes, ja_importados, dry_run
    ) -> str:
        nome_lab = row.get("Laboratório", "").strip()
        nome_equipe = row.get("Equipe", "").strip()
        nome_paciente = row.get("Paciente", "").strip()
        nome_aluno = row.get("Aluno", "").strip()
        servico = row.get("Serviço", "").strip()
        data_entrada = _parse_date(row.get("Data da entrada", ""))
        data_envio = _parse_date(row.get("Data do envio", ""))
        previsao = _parse_date(row.get("Previsão de entrega", ""))
        data_entrega = _parse_date(row.get("Data de entrega", ""))
        status_csv = row.get("Status", "").strip()

        if not previsao:
            self.stderr.write(f"  SKIP sem previsão: {nome_paciente} / {servico[:40]}")
            return "erro"
        if not nome_paciente or not nome_aluno:
            self.stderr.write(f"  SKIP sem paciente/aluno: {servico[:40]}")
            return "erro"

        lab = self._buscar_lab(nome_lab, indice_labs)
        equipe = self._buscar_equipe(nome_equipe, indice_equipes)
        if not lab:
            self.stderr.write(f"  SKIP laboratório não encontrado: '{nome_lab}'")
            return "erro"
        if not equipe:
            self.stderr.write(f"  SKIP equipe não encontrada: '{nome_equipe}'")
            return "erro"

        chave = _chave_pedido(lab.pk, equipe.pk, previsao, servico)
        if chave in ja_importados:
            return "ignorado"

        if dry_run:
            self.stdout.write(
                f"  [DRY] {data_entrada} | {lab.nome[:25]}"
                f" | {nome_paciente[:20]} | {servico[:30]}"
            )
            ja_importados.add(chave)
            return "criado"

        paciente, _ = Paciente.objects.get_or_create(
            id_dental=_coda_id("P", nome_paciente),
            defaults={
                "nome": nome_paciente,
                "ativo": True,
                "origem": OrigemDados.MANUAL,
            },
        )
        aluno, _ = AlunoLab.objects.get_or_create(
            id_dental=_coda_id("A", nome_aluno),
            defaults={"nome": nome_aluno, "ativo": True, "origem": OrigemDados.MANUAL},
        )

        entregue = data_entrega is not None or "entregue" in status_csv.lower()

        # "Confirmar" sem data_envio: usa data_entrada como envio aproximado
        if not data_envio and status_csv.lower() == "confirmar":
            data_envio = data_entrada

        pedido = PedidoMaterial(
            paciente=paciente,
            aluno=aluno,
            laboratorio=lab,
            equipe=equipe,
            previsao_entrega=previsao,
            descricao_servico=servico,
            data_envio=data_envio,
            entregue=entregue,
            data_entrega=data_entrega,
            faturado_paciente=_parse_bool(row.get("Faturado Paciente", "false")),
            faturado_lab=_parse_bool(row.get("Faturado Lab", "false")),
            numero_nota_fiscal=row.get("Num. Nota Fiscal", "").strip(),
            data_vencimento=_parse_date(row.get("Data de vencimento", "")),
        )
        pedido.save()

        self._corrigir_data_criacao(pedido.pk, data_entrada)
        ja_importados.add(chave)
        return "criado"

    # ─── Importação arquivo 2 ─────────────────────────────────────────────────

    def _importar_sem_pessoa(
        self,
        row: dict,
        indice_labs,
        indice_equipes,
        ja_importados,
        pac_placeholder,
        alu_placeholder,
        dry_run,
    ) -> str:
        nome_lab = row.get("Laboratório", "").strip()
        nome_equipe = row.get("Equipe", "").strip()
        servico = row.get("Serviço", "").strip()
        data_entrada = _parse_date(row.get("Data da entrada", ""))
        data_envio = _parse_date(row.get("Data do envio", ""))
        previsao = _parse_date(row.get("Previsão de entrega", ""))
        data_entrega = _parse_date(row.get("Data de entrega", ""))
        status_csv = row.get("Status", "").strip()

        if not previsao:
            return "ignorado"

        lab = self._buscar_lab(nome_lab, indice_labs)
        equipe = self._buscar_equipe(nome_equipe, indice_equipes)
        if not lab or not equipe:
            self.stderr.write(
                f"  SKIP lab/equipe não encontrado: '{nome_lab}' / '{nome_equipe}'"
            )
            return "erro"

        chave = _chave_pedido(lab.pk, equipe.pk, previsao, servico)
        if chave in ja_importados:
            return "ignorado"

        if dry_run:
            self.stdout.write(
                f"  [DRY] {data_entrada} | {lab.nome[:25]} | LEGADO | {servico[:30]}"
            )
            ja_importados.add(chave)
            return "criado"

        entregue = data_entrega is not None or "entregue" in status_csv.lower()

        if not data_envio and status_csv.lower() == "confirmar":
            data_envio = data_entrada

        pedido = PedidoMaterial(
            paciente=pac_placeholder,
            aluno=alu_placeholder,
            laboratorio=lab,
            equipe=equipe,
            previsao_entrega=previsao,
            descricao_servico=servico,
            data_envio=data_envio,
            entregue=entregue,
            data_entrega=data_entrega,
            faturado_paciente=False,
            faturado_lab=False,
        )
        pedido.save()

        self._corrigir_data_criacao(pedido.pk, data_entrada)
        ja_importados.add(chave)
        return "criado"

    # ─── Utilitários ─────────────────────────────────────────────────────────

    def _buscar_lab(self, nome_csv: str, indice: dict) -> "Laboratorio | None":
        normalizado = _norm_lab(nome_csv)
        if normalizado in indice:
            return indice[normalizado]
        # Busca por substring (tolera espaços extras ou siglas)
        for chave, lab in indice.items():
            if normalizado in chave or chave in normalizado:
                return lab
        return None

    def _buscar_equipe(self, nome_csv: str, indice: dict) -> "Equipe | None":
        return indice.get(nome_csv.strip().upper())

    @staticmethod
    def _corrigir_data_criacao(pk: int, data_entrada: "date_type | None") -> None:
        """Sobrescreve criado_em (auto_now_add) com a data real de entrada do CODA."""
        if not data_entrada:
            return
        criado_em = timezone.make_aware(
            datetime.combine(data_entrada, time_type.min),
            timezone.get_current_timezone(),
        )
        PedidoMaterial.objects.filter(pk=pk).update(criado_em=criado_em)
