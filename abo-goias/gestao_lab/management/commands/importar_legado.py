"""Importa equipes e laboratórios migrados do sistema legado CODA."""

from django.core.management.base import BaseCommand
from gestao_lab.models import Equipe, Laboratorio


def _fmt_cnpj(valor: str) -> str:
    digitos = "".join(c for c in str(valor) if c.isdigit())
    if len(digitos) < 14:
        digitos = digitos.zfill(14)
    if len(digitos) != 14:
        return ""
    return (
        f"{digitos[:2]}.{digitos[2:5]}.{digitos[5:8]}/{digitos[8:12]}-{digitos[12:14]}"
    )


def _limpar_tel(valor: str) -> str:
    digitos = "".join(c for c in str(valor) if c.isdigit())
    return digitos if len(digitos) >= 8 else ""


def _limpar_email(valor: str) -> str:
    v = valor.strip()
    return v if "@" in v and len(v) > 3 else ""


class Command(BaseCommand):
    help = "Importa equipes e laboratórios do sistema legado CODA (idempotente)."

    EQUIPES = [
        {"nome": "Dentística", "coordenador": "Rafael Decurcio"},
        {"nome": "Endoscience", "coordenador": "Daniel Decurcio"},
        {"nome": "OrthoEvidence", "coordenador": "Régis Murilo"},
        {"nome": "LORM", "coordenador": "Luciana Rezende"},
        {"nome": "Advant", "coordenador": "Leandro Cardoso"},
        {"nome": "PED", "coordenador": "Anelise Daher"},
        {"nome": "Oralmed", "coordenador": "Camila de Freitas"},
        {"nome": "Periomax", "coordenador": "Juliano Miguel"},
        {"nome": "Reabilitação Oral", "coordenador": "Sicknan Soares"},
        {"nome": "Getúlio", "coordenador": "Getúlio Marães"},
        {"nome": "Clinica III", "coordenador": ""},
        {"nome": "UniFan", "coordenador": ""},
    ]

    LABORATORIOS = [
        {
            "nome": "UNIARTE COMÉRCIO MATERIAIS ODONTOLÓGICOS LTDA",
            "telefone": "6230947748",
            "whatsapp": "62983060269",
            "email": "uniartelaboratorio@terra.com.br",
            "cnpj": "07939350000167",
            "equipes": ["Dentística"],
        },
        {
            "nome": "ORTOQUALY APARELHOS ORTODONTICOS LTDA - ME",
            "telefone": "6235416724",
            "whatsapp": "62981881782",
            "email": "ortopatrik@hotmail.com",
            "cnpj": "01248368000136",
            "equipes": ["OrthoEvidence", "Clinica III", "PED", "UniFan"],
        },
        {
            "nome": "BELO SORISSO ATELIE DE PROTESE DENTARIA LTDA",
            "telefone": "",
            "whatsapp": "62991175944",
            "email": "",
            "cnpj": "47341210000107",
            "equipes": ["UniFan"],
        },
        {
            "nome": "GERALDO NONATO VASCONCELOS FIGUEIREDO",
            "telefone": "",
            "whatsapp": "62986223835",
            "email": "",
            "cnpj": "17029188000101",
            "equipes": ["Advant", "Clinica III"],
        },
        {
            "nome": "LABORATORIO LOYOLA LTDA",
            "telefone": "62999210660",
            "whatsapp": "62999800660",
            "email": "isadorafloyola@gmail.com",
            "cnpj": "03858289000172",
            "equipes": ["UniFan"],
        },
        {
            "nome": "LABORATORIO PROTETICO E TREINAMENTO ME - 3D",
            "telefone": "62995794644",
            "whatsapp": "62981350723",
            "email": "financeirolab3d@hotmail.com",
            "cnpj": "20174048000123",
            "equipes": ["Reabilitação Oral"],
        },
        {
            "nome": "NÚCLEO LABORATORIO DE PROTESE DENTARIA LTD",
            "telefone": "6232857057",
            "whatsapp": "62986183572",
            "email": "labornucleo@hotmail.com",
            "cnpj": "01560369000111",
            "equipes": ["Getúlio"],
        },
        {
            "nome": "MARCOS MARTINS MONTEIRO EIRELI - ME - 3M",
            "telefone": "",
            "whatsapp": "62991088340",
            "email": "",
            "cnpj": "22606100000107",
            "equipes": ["Reabilitação Oral"],
        },
        {
            "nome": "ORTHO EVIDENCE ODONTOLOGIA LTDA",
            "telefone": "6239542758",
            "whatsapp": "62986503331",
            "email": "",
            "cnpj": "41018431000162",
            "equipes": ["OrthoEvidence"],
        },
        {
            "nome": "VITORINO LABORATORIO DE PROTESES ODONTOLOGICAS",
            "telefone": "",
            "whatsapp": "62996759008",
            "email": "",
            "cnpj": "12089075000170",
            "equipes": ["Reabilitação Oral", "UniFan"],
        },
        {
            "nome": "PERFIL PRÓTESE DENTARIA",
            "telefone": "",
            "whatsapp": "62995764043",
            "email": "perfilprotese@gmail.com",
            "cnpj": "14803165000106",
            "equipes": ["Reabilitação Oral"],
        },
        {
            "nome": "ATELIÊ DE PROTESE DENTARIA JEAN DE PAULA",
            "telefone": "",
            "whatsapp": "62982876833",
            "email": "jeandepaula.lab@hotmail.com",
            "cnpj": "",
            "equipes": ["Advant"],
        },
        {
            "nome": "OFICINA DE PROTESE LTDA ME",
            "telefone": "62986580527",
            "whatsapp": "62984618541",
            "email": "",
            "cnpj": "11022295000113",
            "equipes": ["Reabilitação Oral", "Clinica III"],
        },
        {
            "nome": "IGF1 SERVICOS ODONTOLOGICOS LTDA",
            "telefone": "1155230475",
            "whatsapp": "11981206775",
            "email": "",
            "cnpj": "35754366000130",
            "equipes": ["Clinica III", "Dentística"],
        },
        {
            "nome": "CADDESIGN LABORATÓRIO DE PRÓTESE DENTÁRIA",
            "telefone": "6299883721",
            "whatsapp": "6299883721",
            "email": "lab.cadesignsl@gmail.com",
            "cnpj": "41414385000110",
            "equipes": ["UniFan"],
        },
        {
            "nome": "LABORATÓRIO SILVA",
            "telefone": "6232843933",
            "whatsapp": "62992036501",
            "email": "laboratoriosilvaa@gmail.com",
            "cnpj": "48195773000105",
            "equipes": ["UniFan"],
        },
        {
            "nome": "LADENTES",
            "telefone": "",
            "whatsapp": "62993022000",
            "email": "",
            "cnpj": "",
            "equipes": ["Reabilitação Oral"],
        },
        {
            "nome": "GLOW CADCAM 3D ODONTOLOGIA DIGITAL LTDA",
            "telefone": "",
            "whatsapp": "6298699901",
            "email": "",
            "cnpj": "53162928000139",
            "equipes": ["Reabilitação Oral"],
        },
        {
            "nome": "RO DIGITAL",
            "telefone": "",
            "whatsapp": "62991470957",
            "email": "SICKNAN@UFG.BR",
            "cnpj": "10932296000132",
            "equipes": ["Reabilitação Oral"],
        },
        {
            "nome": "LABORATÓRIO DE PRÓTESES ATELIÊ HG LTDA",
            "telefone": "62981164881",
            "whatsapp": "62981164881",
            "email": "hilsebrando76@hotmail.com",
            "cnpj": "32865742000176",
            "equipes": ["Reabilitação Oral"],
        },
        {
            "nome": "DENTDESIGN LABORATÓRIO DE PRÓTESE LTDA",
            "telefone": "1144610387",
            "whatsapp": "11994242205",
            "email": "adm@dentdesign.com.br",
            "cnpj": "13322957000104",
            "equipes": ["Dentística"],
        },
        {
            "nome": "FAST LAB SC LTDA",
            "telefone": "62984328887",
            "whatsapp": "62996951100",
            "email": "labadvant@gmail.com",
            "cnpj": "59373782000157",
            "equipes": ["Advant"],
        },
        {
            "nome": "ESTETICA E FUNÇÃO LTDA",
            "telefone": "6293008558",
            "whatsapp": "",
            "email": "rafaeldecurcio@gmail.com",
            "cnpj": "45642171000152",
            "equipes": ["Dentística"],
        },
    ]

    def handle(self, *args, **options):
        equipes_criadas = equipes_existentes = 0
        for dados in self.EQUIPES:
            _, criado = Equipe.objects.get_or_create(
                nome=dados["nome"],
                defaults={"coordenador": dados["coordenador"]},
            )
            if criado:
                equipes_criadas += 1
            else:
                equipes_existentes += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Equipes — criadas: {equipes_criadas},"
                f" já existentes: {equipes_existentes}."
            )
        )

        indice_equipes = {e.nome: e for e in Equipe.objects.all()}

        labs_criados = labs_existentes = 0
        for dados in self.LABORATORIOS:
            cnpj = _fmt_cnpj(dados["cnpj"]) if dados["cnpj"] else ""
            tel = _limpar_tel(dados["telefone"])
            wpp = _limpar_tel(dados["whatsapp"])
            email = _limpar_email(dados["email"])

            lab, criado = Laboratorio.objects.get_or_create(
                nome=dados["nome"],
                defaults={
                    "telefone": tel,
                    "whatsapp": wpp,
                    "email": email,
                    "cnpj": cnpj,
                },
            )

            equipes_lab = [
                indice_equipes[nome]
                for nome in dados["equipes"]
                if nome in indice_equipes
            ]
            if equipes_lab:
                lab.equipes.set(equipes_lab)

            if criado:
                labs_criados += 1
            else:
                labs_existentes += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Laboratórios — criados: {labs_criados},"
                f" já existentes: {labs_existentes}."
            )
        )
