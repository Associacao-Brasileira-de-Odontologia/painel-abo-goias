"""Management command to import data from legacy CSV spreadsheets."""

import csv
import hashlib
import re
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError
from django.utils.timezone import make_aware

from gestao_cme.models import Abrigo, Aluno, Movimentacao, OrigemDados, Turma


def _fix(text: str) -> str:
    """Fix mojibake: UTF-8 bytes stored as Latin-1 chars."""
    if not text:
        return text
    try:
        return text.encode("latin-1").decode("utf-8")
    except (UnicodeDecodeError, UnicodeEncodeError):
        return text


def _norm(name: str) -> str:
    """Normalise name for fuzzy matching."""
    return " ".join(name.lower().split())


def _row_hash(parts: list) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()


class Command(BaseCommand):
    help = "Importa alunos (abrigos) e movimentações de planilhas CSV legadas."

    def add_arguments(self, parser):
        parser.add_argument(
            "--alunos", metavar="ARQUIVO", help="CSV com alunos e seus abrigos"
        )
        parser.add_argument(
            "--movimentacoes",
            metavar="ARQUIVO",
            help="CSV com histórico de movimentações",
        )
        parser.add_argument(
            "--criar-inativos",
            action="store_true",
            help="Cria registros de Aluno/Turma para alunos inativos do CSV",
        )
        parser.add_argument(
            "--resolver-vinculos",
            action="store_true",
            help=(
                "Atualiza movimentações LEGADO sem aluno FK "
                "resolvendo pelo nome/abrigo"
            ),
        )

    def handle(self, *args, **options):
        self.verbosity = options["verbosity"]
        nenhuma_acao = (
            not options["alunos"]
            and not options["movimentacoes"]
            and not options["resolver_vinculos"]
        )
        if nenhuma_acao:
            raise CommandError(
                "Informe ao menos --alunos, --movimentacoes ou --resolver-vinculos."
            )
        if options["alunos"]:
            self._import_alunos(
                options["alunos"], criar_inativos=options["criar_inativos"]
            )
        if options["movimentacoes"]:
            self._import_movimentacoes(options["movimentacoes"])
        if options["resolver_vinculos"]:
            self._resolver_vinculos()

    # ------------------------------------------------------------------
    # Fase 1: vincular alunos existentes aos seus abrigos
    #         (com --criar-inativos também cria alunos/turmas ausentes)
    # ------------------------------------------------------------------
    def _import_alunos(self, path: str, criar_inativos: bool = False):
        self.stdout.write(self.style.MIGRATE_HEADING(f"Importando alunos: {path}"))

        aluno_idx: dict[str, Aluno] = {}
        for a in Aluno.objects.select_related("turma", "abrigo"):
            aluno_idx[_norm(a.nome)] = a

        abrigo_idx = {a.identificador: a for a in Abrigo.objects.all()}

        turma_idx: dict[str, Turma] = {}
        for t in Turma.objects.all():
            turma_idx[_norm(t.nome)] = t

        atualizados = 0
        criados = 0
        sem_match = []

        with open(path, encoding="utf-8-sig", errors="replace", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                duplicado = _fix(row.get("Duplicado", "")).strip().lower()
                if duplicado == "true":
                    continue

                nome_raw = _fix(row.get("Aluno", "")).strip()
                if not nome_raw:
                    continue

                abrigo_str = row.get("Abrigo", "").strip()
                ocupado_str = row.get("Ocupado", "false").strip().lower()
                ativo_str = row.get("Ativo", "true").strip().lower()
                turma_raw = _fix(row.get("Turma", "")).strip()
                email_raw = _fix(row.get("Email", "")).strip()

                ocupado = ocupado_str == "true"
                ativo = ativo_str == "true"

                # Garante que o abrigo existe
                abrigo = None
                if abrigo_str and abrigo_str.isdigit():
                    if abrigo_str not in abrigo_idx:
                        abrigo = Abrigo.objects.create(
                            identificador=abrigo_str,
                            ocupado=ocupado,
                            origem=OrigemDados.LEGADO,
                        )
                        abrigo_idx[abrigo_str] = abrigo
                    else:
                        abrigo = abrigo_idx[abrigo_str]

                aluno = aluno_idx.get(_norm(nome_raw))

                if aluno is None:
                    if criar_inativos:
                        # Garante turma
                        turma = turma_idx.get(_norm(turma_raw))
                        if turma is None and turma_raw:
                            slug = (
                                hashlib.md5(turma_raw.encode()).hexdigest()[:6].upper()
                            )
                            codigo_candidato = f"LEG-{slug}"
                            turma, _ = Turma.objects.get_or_create(
                                codigo=codigo_candidato,
                                defaults={
                                    "nome": turma_raw,
                                    "ativo": False,
                                    "origem": OrigemDados.LEGADO,
                                },
                            )
                            turma_idx[_norm(turma_raw)] = turma

                        # Cria aluno
                        matricula_base = email_raw or f"LEGADO-{nome_raw[:40]}"
                        matricula = matricula_base[:80]
                        if Aluno.objects.filter(matricula=matricula).exists():
                            matricula = f"{matricula[:70]}-{abrigo_str or 'X'}"[:80]

                        aluno = Aluno.objects.create(
                            nome=nome_raw.upper(),
                            matricula=matricula,
                            turma=turma,
                            abrigo=abrigo,
                            ativo=ativo,
                            origem=OrigemDados.LEGADO,
                        )
                        aluno_idx[_norm(nome_raw)] = aluno
                        criados += 1
                        continue  # abrigo já foi setado no create
                    else:
                        sem_match.append(nome_raw)
                        continue

                if abrigo and aluno.abrigo_id != abrigo.pk:
                    aluno.abrigo = abrigo
                    aluno.save(update_fields=["abrigo"])
                    atualizados += 1

        msg_parts = [f"{atualizados} vinculados a abrigos"]
        if criar_inativos:
            msg_parts.append(f"{criados} criados (inativos)")
        msg_parts.append(f"{len(sem_match)} nao encontrados no BD")
        self.stdout.write(self.style.SUCCESS("  Alunos: " + ", ".join(msg_parts)))

        if self.verbosity >= 2:
            for n in sem_match[:30]:
                self.stdout.write(f"    x {n}")

    # ------------------------------------------------------------------
    # Fase 2: importar movimentações históricas
    # ------------------------------------------------------------------
    def _import_movimentacoes(self, path: str):
        self.stdout.write(
            self.style.MIGRATE_HEADING(f"Importando movimentações: {path}")
        )

        abrigo_aluno: dict[str, Aluno] = {}
        nome_aluno: dict[str, Aluno] = {}
        for a in Aluno.objects.select_related("turma", "abrigo").all():
            if a.abrigo:
                abrigo_aluno[a.abrigo.identificador] = a
            key = _norm(a.nome)
            if key not in nome_aluno:
                nome_aluno[key] = a

        turma_idx: dict[str, Turma] = {}
        for t in Turma.objects.all():
            turma_idx[_norm(t.nome)] = t
            turma_idx[_norm(t.codigo)] = t

        existing = set(Movimentacao.objects.values_list("row_hash", flat=True))

        criados = ignorados = erros = 0
        batch: list[Movimentacao] = []
        BATCH = 500

        with open(path, encoding="utf-8-sig", errors="replace", newline="") as fh:
            reader = csv.DictReader(fh)
            for lineno, row in enumerate(reader, start=2):
                try:
                    mov = self._parse_row(row, abrigo_aluno, nome_aluno, turma_idx)
                except Exception as exc:
                    erros += 1
                    if self.verbosity >= 2:
                        self.stdout.write(
                            self.style.WARNING(
                                f"  Linha {lineno} - erro: {exc} | {row}"
                            )
                        )
                    continue

                if mov is None:
                    erros += 1
                    continue

                if mov.row_hash in existing:
                    ignorados += 1
                    continue

                existing.add(mov.row_hash)
                batch.append(mov)

                if len(batch) >= BATCH:
                    Movimentacao.objects.bulk_create(batch, ignore_conflicts=True)
                    criados += len(batch)
                    batch = []
                    if self.verbosity >= 1:
                        self.stdout.write(f"  ... {criados} importadas")

        if batch:
            Movimentacao.objects.bulk_create(batch, ignore_conflicts=True)
            criados += len(batch)

        self.stdout.write(
            self.style.SUCCESS(
                f"  Movimentacoes: {criados} criadas, "
                f"{ignorados} ja existentes, {erros} erros/invalidas"
            )
        )

    # ------------------------------------------------------------------
    # Fase 3: resolver vínculos aluno→movimentação nos registros já salvos
    # ------------------------------------------------------------------
    def _resolver_vinculos(self):
        self.stdout.write(
            self.style.MIGRATE_HEADING("Resolvendo vinculos aluno -> movimentacao")
        )

        abrigo_aluno: dict[str, Aluno] = {}
        nome_aluno: dict[str, Aluno] = {}
        for a in Aluno.objects.select_related("turma", "abrigo").all():
            if a.abrigo:
                abrigo_aluno[a.abrigo.identificador] = a
            key = _norm(a.nome)
            if key not in nome_aluno:
                nome_aluno[key] = a

        turma_idx: dict[str, Turma] = {}
        for t in Turma.objects.all():
            turma_idx[_norm(t.nome)] = t

        sem_aluno = Movimentacao.objects.filter(
            aluno__isnull=True, origem=OrigemDados.LEGADO
        )
        total = sem_aluno.count()
        self.stdout.write(f"  Movimentacoes sem aluno FK: {total}")

        resolvidos = 0
        nao_resolvidos = 0
        batch_update = []
        BATCH = 500

        for mov in sem_aluno.iterator(chunk_size=500):
            nome_raw = mov.aluno_nome or ""
            aluno = None
            aluno_nome = nome_raw

            # Tenta pelo padrão "NNN - Nome"
            m = re.match(r"^\s*(\d+)\s*-\s*(.+)$", nome_raw.strip())
            if m:
                abrigo_id, aluno_nome = m.group(1), m.group(2).strip()
                aluno = abrigo_aluno.get(abrigo_id)

            if aluno is None:
                if " - " in nome_raw:
                    aluno_nome = nome_raw.split(" - ", 1)[1].strip()
                aluno = nome_aluno.get(_norm(aluno_nome))

            if aluno is None:
                # Remove prefixo "- " gerado por abrigo vazio na planilha
                stripped = re.sub(r"^[-\s]+", "", nome_raw).strip()
                aluno = nome_aluno.get(_norm(stripped))
                if aluno:
                    aluno_nome = stripped

            if aluno is None:
                aluno = nome_aluno.get(_norm(nome_raw))

            if aluno:
                turma = aluno.turma
                if turma is None:
                    turma = turma_idx.get(_norm(mov.turma_nome or ""))

                mov.aluno = aluno
                mov.turma = turma
                mov.aluno_nome = aluno.nome
                mov.aluno_codigo_externo = aluno.matricula or ""
                mov.turma_nome = turma.nome if turma else mov.turma_nome
                batch_update.append(mov)
                resolvidos += 1
            else:
                nao_resolvidos += 1

            if len(batch_update) >= BATCH:
                Movimentacao.objects.bulk_update(
                    batch_update,
                    [
                        "aluno",
                        "turma",
                        "aluno_nome",
                        "aluno_codigo_externo",
                        "turma_nome",
                    ],
                )
                batch_update = []
                if self.verbosity >= 1:
                    self.stdout.write(f"  ... {resolvidos} resolvidos")

        if batch_update:
            Movimentacao.objects.bulk_update(
                batch_update,
                ["aluno", "turma", "aluno_nome", "aluno_codigo_externo", "turma_nome"],
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"  Resolvidos: {resolvidos}, ainda sem match: {nao_resolvidos}"
            )
        )

    # ------------------------------------------------------------------
    def _parse_row(self, row, abrigo_aluno, nome_aluno, turma_idx):
        data_str = row.get("Data", "").strip()
        nome_raw = _fix(row.get("Nome", "").strip())
        turma_raw = _fix(row.get("Turma", "").strip())
        retirado_raw = row.get("Retirado", "false").strip().lower()
        pacote_str = row.get("Pacote", "").strip()

        # Coluna "Movimentação" pode aparecer com mojibake no header
        tipo_raw = ""
        for col in row:
            col_fixed = _fix(col)
            if "movimenta" in col_fixed.lower() or "movimenta" in col.lower():
                tipo_raw = _fix(row[col].strip())
                break

        if not data_str or not nome_raw:
            return None

        try:
            dt = make_aware(datetime.strptime(data_str, "%d/%m/%Y, %H:%M"))
        except ValueError:
            return None

        tipo_fixed = _fix(tipo_raw).lower()
        if "ntrada" in tipo_fixed:
            tipo = Movimentacao.Tipo.ENTRADA
        elif "a" in tipo_fixed and ("da" in tipo_fixed or "ida" in tipo_fixed):
            tipo = Movimentacao.Tipo.SAIDA
        else:
            return None

        retirado = retirado_raw == "true"

        aluno = None
        aluno_nome = nome_raw

        m = re.match(r"^\s*(\d+)\s*-\s*(.+)$", nome_raw.strip())
        if m:
            abrigo_id = m.group(1)
            aluno_nome = m.group(2).strip()
            aluno = abrigo_aluno.get(abrigo_id)

        if aluno is None:
            if " - " in nome_raw:
                aluno_nome = nome_raw.split(" - ", 1)[1].strip()
            aluno = nome_aluno.get(_norm(aluno_nome))

        turma = None
        if aluno:
            turma = aluno.turma
        if turma is None and turma_raw:
            turma = turma_idx.get(_norm(turma_raw))

        row_hash = _row_hash([data_str, nome_raw, tipo, pacote_str, retirado_raw])

        return Movimentacao(
            data_hora=dt,
            tipo=tipo,
            aluno=aluno,
            turma=turma,
            aluno_nome=aluno.nome if aluno else aluno_nome,
            aluno_codigo_externo=aluno.matricula if aluno else "",
            turma_nome=(turma.nome if turma else turma_raw),
            pacote_codigo=pacote_str,
            retirado=retirado,
            arquivo_origem="planilha_legado",
            row_hash=row_hash,
            origem=OrigemDados.LEGADO,
        )
