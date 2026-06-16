from dataclasses import dataclass
from pathlib import Path
from shutil import copyfile

from django.conf import settings
from django.utils import timezone
from django.utils.text import slugify


TEMPLATES_IDENTIFICADORES_DIR = settings.BASE_DIR / "identificadores" / "templates_pptx"
ARQUIVOS_GERADOS_DIR = settings.BASE_DIR / "identificadores" / "arquivos_gerados"


@dataclass(frozen=True)
class ModeloIdentificador:
    id: str
    nome: str
    arquivo: Path

    @property
    def disponivel(self) -> bool:
        return self.arquivo.exists()

    @property
    def iniciais(self) -> str:
        return "".join(parte[0] for parte in self.nome.split()[:2]).upper()


MODELOS_IDENTIFICADOR = (
    ("abo_goias", "ABO Goias", "template-abo_goias.pptx"),
    ("advant", "Advant", "template-advant.pptx"),
    ("dentistica", "Dentistica", "template-dentistica.pptx"),
    ("endoscience", "EndoScience", "template-endoscience.pptx"),
    ("lorm", "LORM", "template-lorm.pptx"),
    ("oralmed", "Oralmed", "template-oralmed.pptx"),
    ("orthoevidence", "OrthoEvidence", "template-orthoevidence.pptx"),
    ("ped", "PED", "template-ped.pptx"),
    ("periomax", "Perio Max", "template-periomax.pptx"),
    ("radiologia", "Radiologia", "template-radiologia.pptx"),
    ("reabilitacao_oral", "Reabilitacao Oral", "template-reabilitacao_oral.pptx"),
    ("symmetry", "Symmetry", "template-symmetry.pptx"),
)


def listar_modelos() -> list[ModeloIdentificador]:
    return [
        ModeloIdentificador(
            id=modelo_id,
            nome=nome,
            arquivo=TEMPLATES_IDENTIFICADORES_DIR / arquivo,
        )
        for modelo_id, nome, arquivo in MODELOS_IDENTIFICADOR
    ]


def buscar_modelo(modelo_id: str) -> ModeloIdentificador | None:
    return next((modelo for modelo in listar_modelos() if modelo.id == modelo_id), None)


def gerar_arquivo_identificadores(turma, modelo: ModeloIdentificador) -> Path:
    ARQUIVOS_GERADOS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = timezone.now().strftime("%Y%m%d%H%M%S")
    nome_turma = slugify(turma.nome) or f"turma-{turma.pk}"
    nome_modelo = slugify(modelo.nome) or modelo.id
    destino = ARQUIVOS_GERADOS_DIR / f"identificadores-{nome_turma}-{nome_modelo}-{timestamp}.pptx"
    copyfile(modelo.arquivo, destino)
    return destino


def caminho_arquivo_gerado(nome_arquivo: str) -> Path:
    caminho = (ARQUIVOS_GERADOS_DIR / Path(nome_arquivo).name).resolve()
    raiz = ARQUIVOS_GERADOS_DIR.resolve()
    if raiz not in caminho.parents:
        raise ValueError("Arquivo invalido.")
    return caminho
