from dataclasses import dataclass
from pathlib import Path

from django.conf import settings


TEMPLATES_IDENTIFICADORES_DIR = settings.BASE_DIR / "identificadores" / "templates_pptx"


@dataclass(frozen=True)
class ModeloIdentificador:
    id: str
    nome: str
    arquivo: Path

    @property
    def disponivel(self) -> bool:
        return self.arquivo.exists()


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
