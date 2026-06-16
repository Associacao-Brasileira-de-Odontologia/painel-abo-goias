from dataclasses import dataclass
import math
from pathlib import Path
import re
import zipfile
from xml.etree import ElementTree as ET

from django.conf import settings
from django.utils import timezone
from django.utils.text import slugify


TEMPLATES_IDENTIFICADORES_DIR = settings.BASE_DIR / "identificadores" / "templates_pptx"
ARQUIVOS_GERADOS_DIR = settings.BASE_DIR / "identificadores" / "arquivos_gerados"
IDENTIFICADORES_POR_SLIDE = 3
CAPACIDADE_TEMPLATE = 48


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


@dataclass(frozen=True)
class ArquivoIdentificadoresGerado:
    caminho: Path
    total_paginas: int
    total_identificadores: int


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


def montar_local_aluno(aluno) -> str:
    cidade = (getattr(aluno, "cidade", "") or "").strip()
    uf = (getattr(aluno, "uf", "") or "").strip()

    if cidade and uf:
        return f"{cidade} - {uf}"
    if cidade or uf:
        return cidade or uf

    return ""


def montar_dados_identificadores(alunos) -> dict[str, str]:
    dados = {}
    alunos = list(alunos)[:CAPACIDADE_TEMPLATE]

    for indice in range(1, CAPACIDADE_TEMPLATE + 1):
        aluno = alunos[indice - 1] if indice <= len(alunos) else None
        dados[f"Nome{indice}"] = aluno.nome.strip() if aluno else ""
        dados[f"Local{indice}"] = montar_local_aluno(aluno) if aluno else ""

    return dados


def substituir_placeholders_no_slide(xml_bytes: bytes, valores: dict[str, str]) -> bytes:
    ns = {
        "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
        "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    }

    try:
        ET.register_namespace("a", ns["a"])
        ET.register_namespace("p", ns["p"])
        ET.register_namespace("r", "http://schemas.openxmlformats.org/officeDocument/2006/relationships")
        root = ET.fromstring(xml_bytes)

        for shape in root.findall(".//p:sp", ns):
            text_nodes = shape.findall(".//a:t", ns)
            if not text_nodes:
                continue

            texto_original = "".join(node.text or "" for node in text_nodes)
            if "{{" not in texto_original:
                continue

            texto_novo = texto_original
            for chave, valor in valores.items():
                texto_novo = texto_novo.replace(f"{{{{{chave}}}}}", valor)

            texto_novo = re.sub(r"\{\{[^}]+\}\}", "", texto_novo)
            text_nodes[0].text = texto_novo

            for node in text_nodes[1:]:
                node.text = ""

        return ET.tostring(root, encoding="utf-8", xml_declaration=True)
    except Exception:
        return xml_bytes


def obter_numero_slide(caminho: str) -> int | None:
    match = re.search(r"slide(\d+)\.xml(?:\.rels)?$", caminho, re.IGNORECASE)
    return int(match.group(1)) if match else None


def deve_remover_parte_slide(caminho: str, total_slides: int) -> bool:
    prefixes = (
        "ppt/slides/slide",
        "ppt/slides/_rels/slide",
        "ppt/notesSlides/notesSlide",
        "ppt/notesSlides/_rels/notesSlide",
    )

    if not caminho.startswith(prefixes):
        return False

    numero_slide = obter_numero_slide(caminho)
    return numero_slide is not None and numero_slide > total_slides


def atualizar_rels_apresentacao(xml_bytes: bytes, total_slides: int) -> tuple[bytes, set[str]]:
    ns = {"rel": "http://schemas.openxmlformats.org/package/2006/relationships"}
    ET.register_namespace("", ns["rel"])
    root = ET.fromstring(xml_bytes)
    rids_removidos = set()

    for rel in list(root):
        rel_type = rel.attrib.get("Type", "")
        target = rel.attrib.get("Target", "")
        numero_slide = obter_numero_slide(target)

        if rel_type.endswith("/slide") and numero_slide and numero_slide > total_slides:
            rids_removidos.add(rel.attrib.get("Id"))
            root.remove(rel)

    return ET.tostring(root, encoding="utf-8", xml_declaration=True), rids_removidos


def atualizar_presentation_xml(xml_bytes: bytes, rids_removidos: set[str]) -> bytes:
    ns = {
        "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
        "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    }
    ET.register_namespace("p", ns["p"])
    ET.register_namespace("r", ns["r"])
    root = ET.fromstring(xml_bytes)
    slide_list = root.find("p:sldIdLst", ns)

    if slide_list is not None:
        for slide_id in list(slide_list):
            rid = slide_id.attrib.get(f"{{{ns['r']}}}id")
            if rid in rids_removidos:
                slide_list.remove(slide_id)

    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def atualizar_content_types(xml_bytes: bytes, total_slides: int) -> bytes:
    ns = {"ct": "http://schemas.openxmlformats.org/package/2006/content-types"}
    ET.register_namespace("", ns["ct"])
    root = ET.fromstring(xml_bytes)

    for override in list(root):
        part_name = override.attrib.get("PartName", "")
        if part_name.startswith("/ppt/slides/slide") or part_name.startswith("/ppt/notesSlides/notesSlide"):
            numero_slide = obter_numero_slide(part_name)
            if numero_slide and numero_slide > total_slides:
                root.remove(override)

    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def gerar_arquivo_identificadores(turma, modelo: ModeloIdentificador, alunos) -> ArquivoIdentificadoresGerado:
    ARQUIVOS_GERADOS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = timezone.now().strftime("%Y%m%d%H%M%S")
    nome_turma = slugify(turma.nome) or f"turma-{turma.pk}"
    nome_modelo = slugify(modelo.nome) or modelo.id
    destino = ARQUIVOS_GERADOS_DIR / f"identificadores-{nome_turma}-{nome_modelo}-{timestamp}.pptx"
    alunos_template = list(alunos)[:CAPACIDADE_TEMPLATE]
    total_slides = max(1, math.ceil(len(alunos_template) / IDENTIFICADORES_POR_SLIDE))
    valores = montar_dados_identificadores(alunos_template)

    with zipfile.ZipFile(modelo.arquivo, "r") as source:
        rels_xml, rids_removidos = atualizar_rels_apresentacao(
            source.read("ppt/_rels/presentation.xml.rels"),
            total_slides,
        )

        with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as target:
            for item in source.infolist():
                if deve_remover_parte_slide(item.filename, total_slides):
                    continue

                data = source.read(item.filename)

                if item.filename == "ppt/_rels/presentation.xml.rels":
                    data = rels_xml
                elif item.filename == "ppt/presentation.xml":
                    data = atualizar_presentation_xml(data, rids_removidos)
                elif item.filename == "[Content_Types].xml":
                    data = atualizar_content_types(data, total_slides)
                elif item.filename.startswith("ppt/slides/slide") and item.filename.endswith(".xml"):
                    data = substituir_placeholders_no_slide(data, valores)

                target.writestr(item, data)

    return ArquivoIdentificadoresGerado(
        caminho=destino,
        total_paginas=total_slides,
        total_identificadores=len(alunos_template),
    )


def caminho_arquivo_gerado(nome_arquivo: str) -> Path:
    caminho = (ARQUIVOS_GERADOS_DIR / Path(nome_arquivo).name).resolve()
    raiz = ARQUIVOS_GERADOS_DIR.resolve()
    if raiz not in caminho.parents:
        raise ValueError("Arquivo invalido.")
    return caminho
