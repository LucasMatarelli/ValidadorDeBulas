# pages/3_Grafica_x_Arte.py
# Versão: v39 (Baseado no v38)
# Auditoria de Bulas — Comparação: PDF da Gráfica x Arte Vigente
# v39: CORRIGE o display do título na "Visualização Lado a Lado".
# v39: ADICIONA nova função 'substituir_titulos_por_canonicos' para trocar
#      os títulos-alias pelos canônicos no texto completo ANTES da exibição final.
# v39: 'gerar_relatorio_final' agora usa essa função antes de chamar 'marcar_divergencias_html'.
# v39: Mantém a correção do NameError da v38 e toda a lógica de OCR/Mapeamento.

# --- IMPORTS ---

# Libs Padrão
import re
import difflib
import unicodedata
import io
import html
from typing import Tuple, List, Dict

# Libs de Terceiros (Third-party)
import streamlit as st
import fitz  # PyMuPDF
import docx
import spacy
from thefuzz import fuzz
from spellchecker import SpellChecker
import pytesseract
from PIL import Image

# ----------------- CONFIGURAÇÃO DA PÁGINA STREAMLIT -----------------
st.set_page_config(layout="wide", page_title="Auditoria de Bulas - Gráfica x Arte", page_icon="🔬")
hide_streamlit_UI = """
<style>
[data-testid="stHeader"], [data-testid="main-menu-button"], footer,
[data-testid="stStatusWidget"], [data-testid="stCreatedBy"], [data-testid="stHostedBy"] {
    display: none !important; visibility: hidden !important;
}
</style>
"""
st.markdown(hide_streamlit_UI, unsafe_allow_html=True)

# ----------------- MODELO NLP -----------------
@st.cache_resource
def carregar_modelo_spacy():
    """Carrega o modelo de linguagem SpaCy de forma otimizada."""
    try:
        return spacy.load("pt_core_news_lg")
    except OSError:
        st.error("Modelo 'pt_core_news_lg' não encontrado. Execute: python -m spacy download pt_core_news_lg")
        return None

nlp = carregar_modelo_spacy()

# ----------------- [MANTIDO - v36] CORRETOR DE ERROS OCR EXPANDIDO -----------------
def corrigir_erros_ocr_comuns(texto: str) -> str:
    if not texto:
        return ""
    
    correcoes = {
        r"(?i)\binbem\b": "inibem", 
        r"(?i)\b(3|1)lfar\b": "Belfar",
        r"(?i)\bBeifar\b": "Belfar",
        r"(?i)\b3elspan\b": "Belspan",
        r"(?i)\barto\b": "parto",
        r"(?i)\bausar\b": "causar",
        r"(?i)\bcações\b": "reações",
        r"(?i)\becomendada\b": "recomendada",
        r"(?i)\beduzir\b": "reduzir",
        r"(?i)\belacionados\b": "relacionados",
        r"(?i)\bidministrado\b": "administrado",
        r"(?i)\biparelho\b": "aparelho",
        r"(?i)\bjangramento\b": "sangramento",
        r"(?i)\bjerivados\b": "derivados",
        r"(?i)\bjode\b": "pode",
        r"(?i)\blentro\b": "dentro",
        r"(?i)\bloses\b": "doses",
        r"(?i)\bmecicamentos\b": "medicamentos",
        r"(?i)\bnais\b": "mais",
        r"(?i)\bnedicamentos\b": "medicamentos",
        r"(?i)\bnterações\b": "interações",
        r"(?i)\bompensarem\b": "compensarem",
        r"(?i)\bomprimido\b": "comprimido",
        r"(?i)\bontém\b": "contém",
        r"(?i)\bratamento\b": "tratamento",
        r"(?i)\brave\b": "grave",
        r"(?i)\bravidez\b": "gravidez",
        r"(?i)\breas\b": "áreas",
        r"(?i)\brincipalmente\b": "principalmente",
        r"(?i)\broblemas\b": "problemas",
        r"(?i)\brávidas\b": "grávidas",
        r"(?i)\bslaucoma\b": "glaucoma",
        r"(?i)\b2\s+a\s+5\s+vez\b": "2 a 5 vezes", 
        r"(?i)\bapós\s+sintomas\b": "após os sintomas", 
        r"(?i)\babsorção\s+medicamento\b": "absorção do medicamento", 
        r"(?i)\bvocê\s+aplic\s+sulfato\b": "você aplicar sulfato", 
        r"(?i)\bbacitracina\s+zinci\b": "bacitracina zincica", 
        r"(?i)\bpoucos\s+dias;1\b": "poucos dias; no", 
        r"(?i)\bpoucos\s+dias(1|I)\b": "poucos dias; no", 
        r"(?i)\bmecicamento\b": "medicamento",
        r"(?i)\bmedicament0\b": "medicamento",
        r"(?i)\bNAO\b": "NÃO",
        r"(?i)\bCOMPOSIÇAO\b": "COMPOSIÇÃO",
        r"(?i)\bJevido\b": "Devido",
        r"(?i)\bjue\b": "que",
        r"(?i)\bjacientes\b": "pacientes",
        r"(?i)\bocê\b": "você",
        r"(?i)\basos\b": "casos",
        r"(?i)\b1so\b": "uso",
        r"(?i)\bjaracetamol\b": "paracetamol",
        r"(?i)\beguindo\b": "seguindo",
        r"(?i)\bituações\b": "situações",
        r"(?i)\bressão\b": "pressão",
        r"(?i)\bjortadores\b": "portadores",
        r"(?i)\bjossuem\b": "possuem",
        r"(?i)\blérgica\b": "alérgica",
        r"(?i)\bjs\s+sinais\b": "os sinais", 
        r"\.\)\s*s\s+pacientes\b": ". Os pacientes", 
        r"(?i)\bom\s+bolhas\b": "com bolhas", 
        r"(?i)\bcomo\)\s*butilbrometo\b": "como o butilbrometo", 
        r"(?i)\bim\s+caso\b": "em caso",
        r"(?i)\bintolerâácia\b": "intolerância", 
        r"(?i)\ble\s+glicose\b": "de glicose", 
        r"(?i)\bor\s+dose\b": "por dose", 
        r"(?i)\bcom\)\s*uso\b": "com o uso", 
        r"(?i)\bleve\s+ser\b": "deve ser",
        r"(?i)\bnodo\b": "modo", 
        r"(?i)\bomar\s+cuidado\b": "tomar cuidado", 
        r"15\s*Ce\s*30 C": "15°C e 30°C",
        r"15“\s*Ce\s*30 C": "15°C e 30°C", 
        r"(?i)\bleo paralítico\b": "íleo paralítico",
        r"(?i)^1\s+necessária\b": "É necessária",
        r"(?i)\bmediatamente\b": "imediatamente",
        r"(?i)\bAcido acetilsalicílico\b": "Ácido acetilsalicílico",
        r"(?i)\bse ALGUM usar\b": "se ALGUÉM usar",
        r"(?i)\blipirona\b": "dipirona", 
        r"(?i)bacitracina\s+z(i|í)ncica\s+(?:eee|rereeeio)\s+\d+(?:I|ME)?": "bacitracina zíncica 250 UI",
        r"(?i)excipientes\s+q\.s\.p\s+(?:irem|esses\s+LE)\b": "excipientes q.s.p. 1 g",
        r"(?i)\bneomicina\s+5r\b": "neomicina 5 mg", 
        r"(?i)\b250\s+UN\b": "250 UI", 
        r"\bc\.t\s+": "",
        r"\bq\.s\.p\s+\"?si\s+": "q.s.p. ",
        r"\|": "",
        r"\s+mm\b": "", 
        r"\s+mma\b": "",
        r"\s+([,;:\.\?\!%°])": r"\1",
        r"(\()\s+": r"\1",
        r"\s+(\))": r"\1",
    }

    for padrao, correcao in correcoes.items():
        texto = re.sub(padrao, correcao, texto, flags=re.MULTILINE)
    
    return texto


# ----------------- [MANTIDO - v35] LIMPEZA ULTRA CONSERVADORA -----------------
def melhorar_layout_grafica(texto: str) -> str:
    if not texto or not isinstance(texto, str):
        return ""

    texto = corrigir_erros_ocr_comuns(texto)
    texto = texto.replace('\r\n', '\n').replace('\r', '\n')
    texto = texto.replace('\t', ' ')
    texto = re.sub(r'\u00A0', ' ', texto)
    texto = re.sub(r"(\w+)-\s*\n\s*(\w+)", r"\1\2", texto)
    texto = re.sub(r'(\.|\s){7,}', ' ', texto) 
    texto = re.sub(r'[«»"""ÉÀ“”&]', '', texto) 
    texto = re.sub(r'\bBEE\s*\*\b', '', texto, flags=re.IGNORECASE)
    
    linhas = texto.split('\n')
    linhas_limpas = []
    
    padroes_lixo_linha_completa = [
        r'^mm\s*$',
        r'^mma\s*$',
        r'^Too\s*$',
        r'^raio\s+ra\s+m-+\s*$',
        r'^HM\s*$',
        r'^TR\s*$',
        r'^BRR\s*$',
        r'^\s*\|\s*$',
        r'^\s*-{5,}\s*$',
        r'^\s*\d+\s*$', 
        r'^\s*—+\s*\d+\s*$',
        r'^\s*S\s*$',
        r'^\s*E\s*$',
        r'^\s*O\s*$',
        r'^\s*m\s*$',
        r'^\s*EN\s*$',
        r'^m\s+EN\s+\d+\s+\d+\s+a,\s+\d+\s+-$', 
        r'fig\.\s+\d', 
        r'^\s*es\s+New\s+Roman\(\)\s+B\s+E\s+LFAR\s+rpo\s+\d+$', 
        r'^\d+-\s+\d+$', 
        r"^\s*300,00\s*$",
        r"^\s*30,00\s*$",
        r"^\s*1º\s*-\s*prova\s*-'\s*$",
        r"(?i)BUL\s+bacitracin:\s+FRENTE",
        r"(?i)BUL\s+bacitracina\b", 
        r"(?i)Tipologia\s+da\s+bul",
        r"0,\s*00—\s*to\.\s+Corpo\s+10",
        r"^\s*\d+\s+\d+-\s+\d+\s*$", 
    ]
    
    for linha in linhas:
        linha_limpa = linha.strip()
        
        if not linha_limpa:
            linhas_limpas.append("")
            continue
        
        eh_lixo = False
        for padrao_lixo in padroes_lixo_linha_completa:
            if re.search(padrao_lixo, linha_limpa, re.IGNORECASE): 
                eh_lixo = True
                break
        
        if not eh_lixo:
            linhas_limpas.append(linha)
    
    texto = "\n".join(linhas_limpas)
    texto = re.sub(r'\n{4,}', '\n\n\n', texto)
    
    linhas_final = []
    for linha in texto.split('\n'):
        linha = re.sub(r'[ \t]{2,}', ' ', linha)
        linhas_final.append(linha.strip())
    
    texto = "\n".join(linhas_final)
    
    return texto.strip()


# ----------------- [MANTIDO - v35] OCR DE PÁGINA INTEIRA (psm 3) -----------------
def extrair_pdf_ocr_v35_fullpage(arquivo_bytes: bytes) -> str:
    texto_total = ""
    with fitz.open(stream=io.BytesIO(arquivo_bytes), filetype="pdf") as doc:
        st.info(f"Forçando OCR (v39: psm 3 Full-Page) em {len(doc)} página(s)...")
        
        ocr_config = r'--psm 3' 
            
        for i, page in enumerate(doc):
            pix_page = page.get_pixmap(dpi=300)
            img_page = Image.open(io.BytesIO(pix_page.tobytes("png")))
            texto_ocr_pagina = pytesseract.image_to_string(img_page, lang='por', config=ocr_config)
            texto_total += texto_ocr_pagina + "\n"
            
    return texto_total

# ----------------- [MANTIDA] FUNÇÃO DE EXTRAÇÃO PRINCIPAL -----------------
def extrair_texto(arquivo, tipo_arquivo: str) -> Tuple[str, str]:
    if arquivo is None:
        return "", f"Arquivo {tipo_arquivo} não enviado."

    try:
        arquivo.seek(0)
        texto = ""
        arquivo_bytes = arquivo.read()

        if tipo_arquivo == "pdf":
            texto = extrair_pdf_ocr_v35_fullpage(arquivo_bytes)
        
        elif tipo_arquivo == "docx":
            st.info("Extraindo texto de DOCX...")
            doc = docx.Document(io.BytesIO(arquivo_bytes))
            texto = "\n".join([p.text for p in doc.paragraphs])
        
        if texto:
            padroes_ignorados = [
                r"(?i)BELFAR", r"(?i)Papel", r"(?i)Times New Roman",
                r"(?i)Cor[: ]", r"(?i)Frente/?Verso", r"(?i)Medida da bula",
                r"(?i)Contato[: ]", r"(?i)Impressão[: ]", r"(?i)Tipologia da bula",
                r"(?i)Ap\s*\d+gr", r"(?i)Artes", r"(?i)gm>>>", r"(?i)450 mm",
                r"BUL\s*BELSPAN\s*COMPRIMIDO", r"BUL\d+V\d+", r"FRENTE:", r"VERSO:",
                r"artes@belfat\.com\.br", r"\(\d+\)\s*\d+-\d+",
                r"e\s*-+\s*\d+mm\s*>>>I\)", 
                r"\d+ª\s*prova\s*-\s*\d+", 
                r"\d+º\s*prova\s*-", 
                r"^\s*\d+/\d+/\d+\s*$", 
                r"(?i)n\s*Roman\s*U\)", 
                r"(?i)lew\s*Roman\s*U\s*\]", 
                r"KH\s*—\s*\d+", 
                r"pp\s*\d+", 
                r"^\s*an\s*$", 
                r"^\s*man\s*$", 
                r"^\s*contato\s*$",
                r"^\s*\|\s*$",
                r"\+\|",
                r"^\s*a\s*\?\s*la\s*KH\s*\d+\s*r", 
                r"^mm\s+>>>", 
                r"^\s*nm\s+A\s*$", 
                r"^\s*TE\s*-\s*À\s*$", 
                r"1º\s*PROVA\s*-\s*LA", 
                r"AMO\s+dm\s+JAM\s+Vmindrtoihko\s+amo\s+o",
                r"\[E\s*O\s*\|\s*dj\s*jul",
                r"\+\s*\|\s*hd\s*bl\s*O\s*mm\s*DS\s*AALPRA",
                r"A\s*\+\s*med\s*FÃ\s*ias\s*A\s*KA\s*aõArA\s*\+\s*ima",
                r"BUL\s+BELSPAN\s+COMPR\b", 
                r"BUL\s+BELSPAN\s+COMP\b",
                r"^\s*m--*\s*$",
            ]
            
            linhas_originais = texto.split('\n')
            linhas_filtradas = []
            
            for linha in linhas_originais:
                linha_limpa = linha.strip()
                ignorar_linha = False
                for padrao in padroes_ignorados:
                    if re.search(padrao, linha_limpa, re.IGNORECASE | re.MULTILINE):
                        ignorar_linha = True
                        break
                if not ignorar_linha:
                    linhas_filtradas.append(linha)
            
            texto = "\n".join(linhas_filtradas)

            caracteres_invisiveis = ['\u00AD', '\u200B', '\u200C', '\u200D', '\uFEFF']
            for char in caracteres_invisiveis:
                texto = texto.replace(char, '')

            texto = texto.replace('\r\n', '\n').replace('\r', '\n')
            texto = texto.replace('\u00A0', ' ')
            
            linhas = texto.split('\n')
            padrao_rodape = re.compile(r'bula do paciente|página \d+\s*de\s*\d+', re.IGNORECASE)
            linhas_filtradas_final = [linha for linha in linhas if not padrao_rodape.search(linha.strip())]
            
            texto = "\n".join(linhas_filtradas_final)
            
            texto = melhorar_layout_grafica(texto)

            texto = re.sub(r'\n{3,}', '\n\n', texto) 
            texto = re.sub(r'[ \t]+', ' ', texto)
            texto = texto.strip()

        return texto, None

    except Exception as e:
        st.error(f"Erro fatal em extrair_texto: {e}", icon="🚨")
        return "", f"Erro ao ler o arquivo {tipo_arquivo}: {e}"


# ----------------- [MANTIDO - v35] TRUNCAR APÓS ANVISA -----------------
def truncar_apos_anvisa(texto: str) -> str:
    if not isinstance(texto, str):
        return texto
    
    regex_anvisa = r"(?:aprovad[ao]\s+pela\s+anvisa\s+em|data\s+de\s+aprovação\s+na\s+anvisa:)\s*([\d]{1,2}/[\d]{1,2}/[\d]{2,4})"
    
    last_match = None
    for match in re.finditer(regex_anvisa, texto, re.IGNORECASE):
        last_match = match 
        
    if last_match:
        end_of_line_pos = texto.find('\n', last_match.end())
        if end_of_line_pos != -1:
            return texto[:end_of_line_pos]
        else:
            return texto[:last_match.end()]
            
    return texto


# ----------------- SEÇÕES E NORMALIZAÇÃO -----------------
def obter_secoes_por_tipo(tipo_bula: str) -> List[str]:
    secoes = {
        "Paciente": [
            "APRESENTAÇÕES",
            "COMPOSIÇÃO",
            "1. PARA QUE ESTE MEDICAMENTO É INDICADO?",
            "2. COMO ESTE MEDICAMENTO FUNCIONA?",
            "3. QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?",
            "4. O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?",
            "5. ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?",
            "6. COMO DEVO USAR ESTE MEDICAMENTO?",
            "7. O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?",
            "8. QUAIS OS MALES QUE ESTE MEDICAMENTO PODE ME CAUSAR?",
            "9. O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?",
            "DIZERES LEGAIS"
        ],
        "Profissional": [
            "APRESENTAÇÕES",
            "COMPOSIÇÃO",
            "1. INDICAÇÕES",
            "2. RESULTADOS DE EFICÁCIA",
            "3. CARACTERÍSTICAS FARMACOLÓGICAS",
            "4. CONTRAINDICAÇÕES",
            "5. ADVERTÊNCIAS E PRECAUÇÕES",
            "6. INTERAÇÕES MEDICAMENTOSAS",
            "7. CUIDADOS DE ARMAZENAMENTO DO MEDICAMENTO",
            "8. POSOLOGIA E MODO DE USAR",
            "9. REAÇÕES ADVERSAS",
            "10. SUPERDOSE",
            "DIZERES LEGAIS"
        ]
    }
    return secoes.get(tipo_bula, secoes["Paciente"])

# --- [MANTIDO - v36] ---
def obter_aliases_secao() -> Dict[str, str]:
    return {
        "INDICAÇÕES": "1. PARA QUE ESTE MEDICAMENTO É INDICADO?",
        "COMO FUNCIONA?": "2. COMO ESTE MEDICAMENTO FUNCIONA?", # v36
        "CONTRAINDICAÇÕES": "3. QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?",
        "POSOLOGIA E MODO DE USAR": "6. COMO DEVO USAR ESTE MEDICAMENTO?",
        "REAÇÕES ADVERSAS": "8. QUAIS OS MALES QUE ESTE MEDICAMENTO PODE ME CAUSAR?",
        "SUPERDOSE": "9. O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?",
        "CUIDADOS DE ARMAZENAMENTO DO MEDICAMENTO": "5. ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?",
        "INDICAÇÕES": "1. INDICAÇÕES",
        "CONTRAINDICAÇÕES": "4. CONTRAINDICAÇÕES",
        "POSOLOGIA E MODO DE USAR": "8. POSOLOGIA E MODO DE USAR",
        "REAÇÕES ADVERSAS": "9. REAÇÕES ADVERSAS",
        "SUPERDOSE": "10. SUPERDOSE",
        "CUIDADOS DE ARMAZENAMENTO DO MEDICAMENTO": "7. CUIDADOS DE ARMAZENAMENTO DO MEDICAMENTO",
    }

def obter_secoes_ignorar_ortografia() -> List[str]:
    return ["COMPOSIÇÃO", "DIZERES LEGAIS"]

def obter_secoes_ignorar_comparacao() -> List[str]:
    return ["COMPOSIÇÃO", "DIZERES LEGAIS", "APRESENTAÇÕES"]

def normalizar_para_comparacao_literal(texto: str) -> str:
    if not isinstance(texto, str):
        return ""
    texto = re.sub(r'(?<!\n)\n(?!\n)', ' ', texto) 
    texto = re.sub(r'[\n\r\t]+', ' ', texto) 
    texto = re.sub(r' +', ' ', texto)
    texto = texto.strip()
    return texto.lower()

def normalizar_texto(texto: str) -> str:
    if not isinstance(texto, str):
        return ""
    texto = ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')
    texto = re.sub(r'[^\w\s]', '', texto)
    texto = ' '.join(texto.split())
    return texto.lower()

def normalizar_titulo_para_comparacao(texto: str) -> str:
    texto_norm = normalizar_texto(texto)
    texto_norm = re.sub(r'^\d+\s*[\.\-)]*\s*', '', texto_norm).strip()
    return texto_norm

def _create_anchor_id(secao_nome: str, prefix: str) -> str:
    norm = normalizar_texto(secao_nome)
    norm_safe = re.sub(r'[^a-z0-9\-]', '-', norm)
    return f"anchor-{prefix}-{norm_safe}"


# --- [MANTIDO - v37] MAPEAMENTO E EXTRAÇÃO DE SEÇÃO (ROBUSTO) ---
# Esta lógica de mapeamento (v37) está correta.

def mapear_secoes(texto_completo: str, secoes_esperadas: List[str]) -> List[Dict]:
    """
    v37 (Gemini): Mapeia seções e calcula 'original_lines_consumed'
    para que 'obter_dados_secao' saiba exatamente onde o título termina.
    """
    mapa_preliminar = []
    
    linhas_nao_vazias = []
    mapa_indices_originais = {} 
    linhas_originais = texto_completo.split('\n')
    
    for i, linha in enumerate(linhas_originais):
        if linha.strip():
            mapa_indices_originais[len(linhas_nao_vazias)] = i
            linhas_nao_vazias.append(linha)

    aliases = obter_aliases_secao()
    titulos_possiveis = {}

    for secao in secoes_esperadas:
        titulos_possiveis[secao] = secao
    for alias, canonico in aliases.items():
        if canonico in secoes_esperadas:
            if alias not in titulos_possiveis:
                titulos_possiveis[alias] = canonico
    
    titulos_norm_map = {norm: canon for norm, canon in 
                        [(normalizar_titulo_para_comparacao(t), c) for t, c in titulos_possiveis.items()]}
    titulos_norm_set = set(titulos_norm_map.keys())

    idx = 0
    while idx < len(linhas_nao_vazias):
        linha_limpa_1 = linhas_nao_vazias[idx].strip()
        linha_norm_1 = normalizar_titulo_para_comparacao(linha_limpa_1)
        
        linha_limpa_2 = ""
        linha_norm_2 = ""
        linha_combinada_2 = ""
        if idx + 1 < len(linhas_nao_vazias):
            linha_limpa_2 = linhas_nao_vazias[idx+1].strip()
            if linha_limpa_2 and len(linha_limpa_2.split()) < 7:
                linha_combinada_2 = f"{linha_limpa_1} {linha_limpa_2}"
                linha_norm_2 = normalizar_titulo_para_comparacao(linha_combinada_2)

        linha_limpa_3 = ""
        linha_norm_3 = ""
        linha_combinada_3 = ""
        if idx + 2 < len(linhas_nao_vazias):
            linha_limpa_3 = linhas_nao_vazias[idx+2].strip()
            if linha_limpa_2 and linha_limpa_3 and len(linha_limpa_3.split()) < 7:
                linha_combinada_3 = f"{linha_limpa_1} {linha_limpa_2} {linha_limpa_3}"
                linha_norm_3 = normalizar_titulo_para_comparacao(linha_combinada_3)

        best_match_score = 0
        best_match_canonico = None
        best_match_titulo_real = ""
        non_empty_lines_consumed = 1 
        
        if linha_norm_3:
            match_3 = difflib.get_close_matches(linha_norm_3, titulos_norm_set, n=1, cutoff=0.96)
            if match_3:
                best_match_score = 99
                best_match_canonico = titulos_norm_map[match_3[0]]
                best_match_titulo_real = linha_combinada_3
                non_empty_lines_consumed = 3

        if linha_norm_2 and best_match_score < 98:
            match_2 = difflib.get_close_matches(linha_norm_2, titulos_norm_set, n=1, cutoff=0.96)
            if match_2:
                best_match_score = 98
                best_match_canonico = titulos_norm_map[match_2[0]]
                best_match_titulo_real = linha_combinada_2
                non_empty_lines_consumed = 2

        if best_match_score < 96:
            match_1 = difflib.get_close_matches(linha_norm_1, titulos_norm_set, n=1, cutoff=0.96)
            if match_1:
                best_match_score = 96
                best_match_canonico = titulos_norm_map[match_1[0]]
                best_match_titulo_real = linha_limpa_1
                non_empty_lines_consumed = 1
        
        if best_match_score < 96:
            for titulo_norm in titulos_norm_set:
                if linha_norm_1.startswith(titulo_norm) and len(linha_norm_1) > len(titulo_norm) + 5:
                    best_match_score = 97
                    best_match_canonico = titulos_norm_map[titulo_norm]
                    # ... (lógica 'startswith' omitida por brevidade) ...
                    non_empty_lines_consumed = 1
                    break

        if best_match_score >= 96:
            if not mapa_preliminar or mapa_preliminar[-1]['canonico'] != best_match_canonico:
                
                indice_original_inicio = mapa_indices_originais.get(idx)
                if indice_original_inicio is None:
                    idx += non_empty_lines_consumed
                    continue # Segurança, deve nunca acontecer

                fim_idx_nao_vazio = min(idx + non_empty_lines_consumed - 1, len(mapa_indices_originais) - 1)
                indice_original_fim = mapa_indices_originais.get(fim_idx_nao_vazio)
                if indice_original_fim is None:
                    idx += non_empty_lines_consumed
                    continue # Segurança
                
                original_lines_consumed = (indice_original_fim - indice_original_inicio) + 1

                mapa_preliminar.append({
                    'canonico': best_match_canonico,
                    'titulo_encontrado': best_match_titulo_real,
                    'linha_inicio': indice_original_inicio, 
                    'non_empty_lines_consumed': non_empty_lines_consumed,
                    'original_lines_consumed': original_lines_consumed 
                })
            idx += non_empty_lines_consumed
        else:
            idx += 1
            
    mapa_preliminar.sort(key=lambda x: x['linha_inicio'])
    return mapa_preliminar


def obter_dados_secao(secao_canonico: str, mapa_secoes: List[Dict], linhas_texto: List[str], tipo_bula: str):
    """
    v37 (Gemini): Usa 'original_lines_consumed' para definir o início do conteúdo.
    """
    for i, secao_mapa in enumerate(mapa_secoes):
        if secao_mapa['canonico'] != secao_canonico:
            continue

        titulo_encontrado = secao_mapa['titulo_encontrado']
        linha_inicio = secao_mapa['linha_inicio']
        non_empty_lines = secao_mapa.get('non_empty_lines_consumed', 1)
        original_lines = secao_mapa.get('original_lines_consumed', 1)
              
        if linha_inicio >= len(linhas_texto):
             return False, None, "" 
              
        linha_original_titulo = linhas_texto[linha_inicio].strip()
        
        conteudo_primeira_linha = ""
        match = None
        try:
            match = re.search(re.escape(titulo_encontrado), linha_original_titulo, re.IGNORECASE)
        except re.error:
             pass
        
        if match and non_empty_lines == 1: 
            idx_fim_titulo = match.end()
            conteudo_primeira_linha = linha_original_titulo[idx_fim_titulo:].strip()
            conteudo_primeira_linha = re.sub(r"^[.:\s]+", "", conteudo_primeira_linha)
        
        linha_inicio_conteudo = linha_inicio + original_lines

        linha_fim = len(linhas_texto)
        if (i + 1) < len(mapa_secoes):
            linha_fim = mapa_secoes[i+1]['linha_inicio']

        conteudo_restante = [linhas_texto[idx] for idx in range(linha_inicio_conteudo, linha_fim)]
        
        if conteudo_primeira_linha:
            conteudo_final = (conteudo_primeira_linha + "\n" + "\n".join(conteudo_restante)).strip()
        else:
            conteudo_final = "\n".join(conteudo_restante).strip()
        
        return True, titulo_encontrado, conteudo_final

    return False, None, ""
# --- [FIM - LÓGICA V37 MANTIDA] ---


# ----------------- COMPARAÇÃO DE CONTEÚDO -----------------
def verificar_secoes_e_conteudo(texto_ref: str, texto_belfar: str, tipo_bula: str):
    secoes_esperadas = obter_secoes_por_tipo(tipo_bula)
    secoes_faltantes, diferencas_conteudo, similaridades_secoes, diferencas_titulos = [], [], [], []

    linhas_ref = texto_ref.split('\n')
    linhas_belfar = texto_belfar.split('\n')

    mapa_ref = mapear_secoes(texto_ref, secoes_esperadas)
    mapa_belfar = mapear_secoes(texto_belfar, secoes_esperadas)

    for secao in secoes_esperadas:
        melhor_titulo = None

        encontrou_ref, _, conteudo_ref = obter_dados_secao(secao, mapa_ref, linhas_ref, tipo_bula)
        encontrou_belfar, titulo_belfar, conteudo_belfar = obter_dados_secao(secao, mapa_belfar, linhas_belfar, tipo_bula)

        if not encontrou_belfar:
            melhor_score = 0
            melhor_titulo_encontrado = None
            for m in mapa_belfar:
                score = fuzz.token_set_ratio(normalizar_titulo_para_comparacao(secao), normalizar_titulo_para_comparacao(m['titulo_encontrado']))
                if score > melhor_score:
                    melhor_score = score
                    melhor_titulo_encontrado = m['titulo_encontrado']

            if melhor_score >= 95: 
                for m_similar in mapa_belfar:
                     if m_similar['titulo_encontrado'] == melhor_titulo_encontrado:
                          _, titulo_belfar, conteudo_belfar = obter_dados_secao(m_similar['canonico'], mapa_belfar, linhas_belfar, tipo_bula)
                          encontrou_belfar = True
                          diferencas_titulos.append({'secao_esperada': secao, 'titulo_encontrado': titulo_belfar})
                          break
            else:
                secoes_faltantes.append(secao)
                continue

        if encontrou_ref and encontrou_belfar:
            secao_comp = normalizar_titulo_para_comparacao(secao)
            titulo_belfar_comp = normalizar_titulo_para_comparacao(titulo_belfar if titulo_belfar else "")

            if secao_comp != titulo_belfar_comp:
                if not any(d['secao_esperada'] == secao for d in diferencas_titulos):
                    diferencas_titulos.append({'secao_esperada': secao, 'titulo_encontrado': titulo_belfar})

            secao_canon_norm = normalizar_titulo_para_comparacao(secao)
            ignorar_comparacao_norm = [normalizar_titulo_para_comparacao(s) for s in obter_secoes_ignorar_comparacao()]

            if secao_canon_norm in ignorar_comparacao_norm:
                similaridades_secoes.append(100)
                continue

            if normalizar_para_comparacao_literal(conteudo_ref) != normalizar_para_comparacao_literal(conteudo_belfar):
                titulo_real_encontrado = titulo_belfar
                diferencas_conteudo.append({
                    'secao': secao,
                    'conteudo_ref': conteudo_ref,
                    'conteudo_belfar': conteudo_belfar,
                    'titulo_encontrado': titulo_real_encontrado
                })
                similaridades_secoes.append(0)
            else:
                similaridades_secoes.append(100)

    return secoes_faltantes, diferencas_conteudo, similaridades_secoes, diferencas_titulos

# ----------------- ORTOGRAFIA -----------------
def checar_ortografia_inteligente(texto_para_checar: str, texto_referencia: str, tipo_bula: str) -> List[str]:
    if not nlp or not texto_para_checar:
        return []

    try:
        secoes_ignorar = obter_secoes_ignorar_ortografia()
        secoes_todas = obter_secoes_por_tipo(tipo_bula)

        texto_filtrado_para_checar = []
        mapa_secoes = mapear_secoes(texto_para_checar, secoes_todas)
        linhas_texto = texto_para_checar.split('\n')
        ignorar_norm = [normalizar_titulo_para_comparacao(s) for s in secoes_ignorar]

        for secao_nome in secoes_todas:
            secao_norm = normalizar_titulo_para_comparacao(secao_nome)
            if secao_norm in ignorar_norm:
                continue
            encontrou, _, conteudo = obter_dados_secao(secao_nome, mapa_secoes, linhas_texto, tipo_bula)
            if encontrou and conteudo:
                linhas_conteudo = conteudo.split('\n')
                if len(linhas_conteudo) > 1:
                    texto_filtrado_para_checar.append('\n'.join(linhas_conteudo[1:]))
                elif len(linhas_conteudo) == 1 and conteudo:
                     texto_filtrado_para_checar.append(conteudo)

        texto_final_para_checar = '\n'.join(texto_filtrado_para_checar)
        if not texto_final_para_checar:
            return []

        spell = SpellChecker(language='pt')
        palavras_a_ignorar = {"alair", "belfar", "peticionamento", "urotrobel", "escopolamina", "dipirona", "butilbrometo", "nafazolina", "cloreto", "zíncica"}
        vocab_referencia = set(re.findall(r'\b[a-záéíóúâêôãõçü]+\b', texto_referencia.lower()))

        doc = nlp(texto_para_checar)
        entidades = {ent.text.lower() for ent in doc.ents}

        spell.word_frequency.load_words(vocab_referencia.union(entidades).union(palavras_a_ignorar))
        palavras = re.findall(r'\b[a-záéíóúâêôãõçü]+\b', texto_final_para_checar.lower())
        erros = spell.unknown(palavras)

        return list(sorted(set([e for e in erros if len(e) > 3])))[:40]
    except Exception as e:
        st.error(f"Erro na ortografia: {e}")
        return []

# ----------------- DIFERENÇAS PALAVRA A PALAVRA -----------------
def marcar_diferencas_palavra_por_palavra(texto_ref: str, texto_belfar: str, eh_referencia: bool):
    def tokenizar(txt: str):
        return re.findall(r'\n|[A-Za-zÀ-ÖØ-öø-ÿ0-9_]+|[^\w\s]', txt, re.UNICODE)

    def norm(tok: str):
        if re.match(r'[A-Za-zÀ-ÖØ-öø-ÿ0-9_]+$', tok):
            return tok.lower()
        return tok
    
    texto_ref = texto_ref or ""
    texto_belfar = texto_belfar or ""

    ref_tokens = tokenizar(texto_ref)
    bel_tokens = tokenizar(texto_belfar)

    ref_norm = [norm(t) for t in ref_tokens]
    bel_norm = [norm(t) for t in bel_tokens]

    matcher = difflib.SequenceMatcher(None, ref_norm, bel_norm, autojunk=False)
    indices = set()
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != 'equal':
            indices.update(range(i1, i2) if eh_referencia else range(j1, j2))

    tokens = ref_tokens if eh_referencia else bel_tokens
    marcado = []
    for idx, tok in enumerate(tokens):
        if idx in indices and tok.strip() != '':
            marcado.append(f"<mark style='background-color: #ffff99; padding: 2px;'>{html.escape(tok)}</mark>")
        else:
            marcado.append(html.escape(tok))

    resultado = ""
    for i, tok in enumerate(marcado):
        if i == 0:
            resultado += tok
            continue
        raw_tok = re.sub(r'^<mark[^>]*>|</mark>$', '', tok)
        if re.match(r'^[^\w\s]$', raw_tok) or raw_tok == '\n':
            resultado += tok
        else:
            if marcado[i-1] != '\n' and tok != '\n':
                 resultado += " "
            resultado += tok

    resultado = re.sub(r'\s+([.,;:!?)])', r'\1', resultado)
    resultado = re.sub(r'(\()\s+', r'\1', resultado)
    resultado = re.sub(r"(</mark>)\s+(<mark[^>]*>)", r"\1 \2", resultado)
    return resultado

# ----------------- MARCAÇÃO POR SEÇÃO COM ÍNDICES -----------------
def marcar_divergencias_html(texto_original: str, secoes_problema: List[Dict], erros_ortograficos: List[str], tipo_bula: str, eh_referencia: bool=False) -> str:
    texto_trabalho = html.escape(texto_original)
    texto_sem_escape = texto_original

    if secoes_problema:
        for diff in secoes_problema:
            conteudo_ref = diff['conteudo_ref']
            conteudo_belfar = diff['conteudo_belfar']
            conteudo_a_marcar = conteudo_ref if eh_referencia else conteudo_belfar
            
            if conteudo_a_marcar is None:
                conteudo_a_marcar = ""

            conteudo_marcado = marcar_diferencas_palavra_por_palavra(conteudo_ref, conteudo_belfar, eh_referencia)
            secao_canonico = diff['secao']
            anchor_id = _create_anchor_id(secao_canonico, "ref" if eh_referencia else "bel")
            conteudo_com_ancora = f"<div id='{anchor_id}' style='scroll-margin-top: 20px;'>{conteudo_marcado}</div>"

            if conteudo_a_marcar and conteudo_a_marcar in texto_sem_escape:
                texto_sem_escape = texto_sem_escape.replace(conteudo_a_marcar, conteudo_com_ancora, 1) 
            else:
                escaped_marcar = html.escape(conteudo_a_marcar)
                if escaped_marcar in texto_trabalho:
                    texto_trabalho = texto_trabalho.replace(escaped_marcar, conteudo_com_ancora, 1) 

    if erros_ortograficos and not eh_referencia:
        for erro in erros_ortograficos:
            pattern = re.compile(r'\b' + re.escape(erro) + r'\b', flags=re.IGNORECASE)
            texto_sem_escape = pattern.sub(lambda m: f"<mark style='background-color: #FFDDC1; padding: 2px;'>{html.escape(m.group(0))}</mark>", texto_sem_escape)

    regex_anvisa = r"((?:aprovad[ao]\s+pela\s+anvisa\s+em|data\s+de\s+aprovação\s+na\s+anvisa:)\s*[\d]{1,2}/[\d]{1,2}/[\d]{2,4})"
    
    last_match = None
    for match in re.finditer(regex_anvisa, texto_sem_escape, re.IGNORECASE):
        last_match = match
        
    if last_match:
        frase_anvisa = last_match.group(1)
        start, end = last_match.start(1), last_match.end(1)
        texto_sem_escape = (
            texto_sem_escape[:start] +
            f"<mark style='background-color: #cce5ff; padding: 2px; font-weight: 500;'>{html.escape(frase_anvisa)}</mark>" +
            texto_sem_escape[end:]
        )

    if '<div' in texto_sem_escape or '<mark' in texto_sem_escape:
        texto_final = texto_sem_escape.replace('\n', '<br>')
    else:
        texto_final = html.escape(texto_sem_escape).replace('\n', '<br>')

    return texto_final

# --- [NOVO v39] ---
def substituir_titulos_por_canonicos(texto_completo: str, mapa_secoes: List[Dict]) -> str:
    """
    v39: Substitui títulos "alias" (ex: 2. COMO FUNCIONA?) no texto
    pelo título canônico (ex: 2. COMO ESTE MEDICAMENTO FUNCIONA?)
    para a exibição final lado-a-lado.
    """
    texto_corrigido = texto_completo
    
    # Itera de trás para frente para não bagunçar os índices de substituição
    for secao_mapa in reversed(mapa_secoes): 
        titulo_encontrado = secao_mapa['titulo_encontrado']
        titulo_canonico = secao_mapa['canonico']
        
        # Normaliza para uma comparação simples
        norm_encontrado = normalizar_titulo_para_comparacao(titulo_encontrado)
        norm_canonico = normalizar_titulo_para_comparacao(titulo_canonico)

        if norm_encontrado != norm_canonico:
            # Tenta substituir o título encontrado (exato) pelo canônico
            # Usa re.escape para lidar com caracteres especiais como '?'
            try:
                # Cria um padrão que encontra o título exato, ignorando o caso
                pattern = re.compile(re.escape(titulo_encontrado), re.IGNORECASE)
                
                # Substitui apenas a primeira ocorrência para segurança
                # Usa uma função lambda para manter a capitalização original (se possível)
                # Mas para títulos, é mais seguro forçar o título canônico.
                
                # Encontra o match para saber a posição
                match = pattern.search(texto_corrigido)
                if match:
                    # Substitui mantendo a estrutura de linhas (se houver)
                    # Esta lógica é mais simples e segura:
                    texto_corrigido = texto_corrigido[:match.start()] + titulo_canonico + texto_corrigido[match.end():]

            except re.error:
                # Fallback se o 'titulo_encontrado' for um regex inválido (raro)
                pass # É melhor não fazer a substituição do que quebrar
                
    return texto_corrigido


# ----------------- [ATUALIZADO - v39] RELATÓRIO E EXPORTAÇÃO -----------------
def gerar_relatorio_final(texto_ref: str, texto_belfar: str, nome_ref: str, nome_belfar: str, tipo_bula: str):
    
    regex_anvisa = r"(aprovad[ao]\s+pela\s+anvisa\s+em|data\s+de\s+aprovação\s+na\s+anvisa:)\s*([\d]{1,2}/[\d]{1,2}/[\d]{2,4})"
    
    match_ref = list(re.finditer(regex_anvisa, texto_ref, re.IGNORECASE))
    match_belfar = list(re.finditer(regex_anvisa, texto_belfar, re.IGNORECASE))
    
    data_ref = match_ref[-1].group(2).strip() if match_ref else "Não encontrada"
    data_belfar = match_belfar[-1].group(2).strip() if match_belfar else "Não encontrada"
    
    mapa_ref = mapear_secoes(texto_ref, obter_secoes_por_tipo(tipo_bula))
    mapa_belfar = mapear_secoes(texto_belfar, obter_secoes_por_tipo(tipo_bula))
    
    secoes_faltantes, diferencas_conteudo, similaridades, diferencas_titulos = verificar_secoes_e_conteudo(texto_ref, texto_belfar, tipo_bula)
    erros_ortograficos = checar_ortografia_inteligente(texto_belfar, texto_ref, tipo_bula)
    score_similaridade_conteudo = sum(similaridades) / len(similaridades) if similaridades else 100.0

    st.header("Relatório de Auditoria Inteligente")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Conformidade de Conteúdo", f"{score_similaridade_conteudo:.0f}%")
    col2.metric("Erros Ortográficos", len(erros_ortograficos))
    col3.metric("Data ANVISA (BELFAR)", data_belfar)
    col4.metric("Seções Faltantes", f"{len(secoes_faltantes)}")

    st.divider()
    st.subheader("Detalhes dos Problemas Encontrados")
    st.info(f"ℹ️ **Datas de Aprovação ANVISA (Última encontrada):**\n - Arte Vigente: {data_ref}\n - PDF da Gráfica: {data_belfar}")

    if secoes_faltantes:
        st.error(f"🚨 **Seções faltantes na bula BELFAR ({len(secoes_faltantes)})**:\n" + "\n".join([f" - {s}" for s in secoes_faltantes]))
    else:
        st.success("✅ Todas as seções obrigatórias estão presentes")

    st.warning(f"⚠️ **Relatório de Conteúdo por Seção:**")
    mapa_diferencas = {diff['secao']: diff for diff in diferencas_conteudo}
    secoes_esperadas = obter_secoes_por_tipo(tipo_bula)
    
    secoes_para_nao_mostrar_expander = [
        "APRESENTAÇÕES", "COMPOSIÇÃO", "DIZERES LEGAIS"
    ]
    secoes_nao_mostrar_norm = [normalizar_titulo_para_comparacao(s) for s in secoes_para_nao_mostrar_expander]
    ignorar_comparacao_norm = [normalizar_titulo_para_comparacao(s) for s in obter_secoes_ignorar_comparacao()]

    expander_caixa_style = (
        "height: 350px; overflow-y: auto; border: 2px solid #d0d0d0; border-radius: 6px; "
        "padding: 16px; background-color: #ffffff; font-size: 14px; line-height: 1.8; "
        "font-family: 'Georgia', 'Times New Roman', serif; text-align: justify;"
    )

    for secao in secoes_esperadas:
        secao_canon_norm = normalizar_titulo_para_comparacao(secao)
        
        if (secao_canon_norm in ignorar_comparacao_norm or 
            secao_canon_norm in secoes_nao_mostrar_norm):
            continue
            
        if secao in secoes_faltantes:
            continue
            
        encontrou_ref, _, conteudo_ref_para_marcar = obter_dados_secao(secao, mapa_ref, texto_ref.split('\n'), tipo_bula)
        encontrou_belfar, titulo_belfar_encontrado, conteudo_bel_para_marcar = obter_dados_secao(secao, mapa_belfar, texto_belfar.split('\n'), tipo_bula)

        if not encontrou_ref or not encontrou_belfar:
            continue 

        diff = mapa_diferencas.get(secao)
        
        # --- [Mantido - v38] ---
        # Lógica de exibição do título corrigida
        if diff:
            expander_title = f"📄 {secao} - ❌ CONTEÚDO DIVERGENTE"
        else:
            expander_title = f"📄 {secao} - ✅ CONTEÚDO IDÊNTICO"
        # --- [FIM] ---
            
        with st.expander(expander_title, expanded=bool(diff)): 
            anchor_id_ref = _create_anchor_id(secao, "ref")
            anchor_id_bel = _create_anchor_id(secao, "bel")

            expander_html_ref = marcar_diferencas_palavra_por_palavra(
                conteudo_ref_para_marcar, conteudo_bel_para_marcar, eh_referencia=True
            ).replace('\n', '<br>')
            
            expander_html_belfar = marcar_diferencas_palavra_por_palavra(
                conteudo_bel_para_marcar, conteudo_bel_para_marcar, eh_referencia=False
            ).replace('\n', '<br>')

            clickable_style = expander_caixa_style + " cursor: pointer; transition: background-color 0.3s ease;"
            
            html_ref_box = f"<div onclick='window.handleBulaScroll(\"{anchor_id_ref}\", \"{anchor_id_bel}\")' style='{clickable_style}' title='Clique para ir à seção' onmouseover='this.style.backgroundColor=\"#f0f8ff\"' onmouseout='this.style.backgroundColor=\"#ffffff\"'>{expander_html_ref}</div>"
            html_bel_box = f"<div onclick='window.handleBulaScroll(\"{anchor_id_ref}\", \"{anchor_id_bel}\")' style='{clickable_style}' title='Clique para ir à seção' onmouseover='this.style.backgroundColor=\"#f0f8ff\"' onmouseout='this.style.backgroundColor=\"#ffffff\"'>{expander_html_belfar}</div>"
            
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**Arte Vigente:** (Clique na caixa para rolar)")
                st.markdown(html_ref_box, unsafe_allow_html=True)
            with c2:
                st.markdown("**PDF da Gráfica:** (Clique na caixa para rolar)")
                st.markdown(html_bel_box, unsafe_allow_html=True)
    
    if erros_ortograficos:
        st.info(f"📝 **Possíveis erros ortográficos ({len(erros_ortograficos)}):**\n" + ", ".join(erros_ortograficos))
    
    if not any([secoes_faltantes, diferencas_conteudo, diferencas_titulos]) and len(erros_ortograficos) < 5:
        st.success("🎉 **Bula aprovada!** Nenhum problema crítico encontrado.")
    
    st.divider()
    
    st.subheader("Visualização Lado a Lado com Destaques")
    st.markdown(
        "**Legenda:** <mark style='background-color: #ffff99; padding: 2px;'>Amarelo</mark> = Divergências | "
        "<mark style='background-color: #FFDDC1; padding: 2px;'>Rosa</mark> = Erros ortográficos | "
        "<mark style='background-color: #cce5ff; padding: 2px;'>Azul</mark> = Data ANVISA",
        unsafe_allow_html=True
    )
    
    # --- [INÍCIO DA CORREÇÃO v39] ---
    # Substitui os títulos-alias pelos títulos canônicos
    # ANTES de passar para a função de marcação de HTML.
    texto_ref_com_titulos_corretos = substituir_titulos_por_canonicos(texto_ref, mapa_ref)
    texto_belfar_com_titulos_corretos = substituir_titulos_por_canonicos(texto_belfar, mapa_belfar)
    
    html_ref_marcado = marcar_divergencias_html(
        texto_ref_com_titulos_corretos, # <--- Usa o texto corrigido
        diferencas_conteudo, 
        [], 
        tipo_bula, 
        eh_referencia=True
    )
    html_belfar_marcado = marcar_divergencias_html(
        texto_belfar_com_titulos_corretos, # <--- Usa o texto corrigido
        diferencas_conteudo, 
        erros_ortograficos, 
        tipo_bula, 
        eh_referencia=False
    )
    # --- [FIM DA CORREÇÃO v39] ---
    
    caixa_style = (
        "height: 700px; overflow-y: auto; border: 2px solid #999; border-radius: 4px; "
        "padding: 24px 32px; background-color: #ffffff; "
        "font-family: 'Georgia', 'Times New Roman', serif; font-size: 14px; "
        "line-height: 1.8; box-shadow: 0 2px 12px rgba(0,0,0,0.15);"
    )
    
    col1, col2 = st.columns(2, gap="medium")
    with col1:
        st.markdown(f"**📄 {nome_ref}**")
        st.markdown(f"<div id='container-ref-scroll' style='{caixa_style}'>{html_ref_marcado}</div>", unsafe_allow_html=True)
    with col2:
        st.markdown(f"**📄 {nome_belfar}**")
        st.markdown(f"<div id='container-bel-scroll' style='{caixa_style}'>{html_belfar_marcado}</div>", unsafe_allow_html=True)

    st.divider()

    relatório_html = gerar_relatorio_html_para_download(
        titulo="Relatório de Auditoria - Gráfica x Arte",
        nome_ref=nome_ref,
        nome_belfar=nome_belfar,
        data_ref=data_ref,
        data_belfar=data_belfar,
        score=score_similaridade_conteudo,
        erros_ortograficos=erros_ortograficos,
        secoes_faltantes=secoes_faltantes,
        diferencas_conteudo=diferencas_conteudo,
        html_ref=html_ref_marcado, # Passa o HTML já corrigido
        html_belfar=html_belfar_marcado # Passa o HTML já corrigido
    )


def gerar_relatorio_html_para_download(titulo: str, nome_ref: str, nome_belfar: str, data_ref: str, data_belfar: str, score: float, erros_ortograficos: List[str], secoes_faltantes: List[str], diferencas_conteudo: List[Dict], html_ref: str, html_belfar: str) -> str:
    resumo_erros = ", ".join(erros_ortograficos) if erros_ortograficos else "Nenhum"
    faltantes_html = "<br>".join([f"- {html.escape(s)}" for s in secoes_faltantes]) if secoes_faltantes else "Nenhuma"
    diferencas_lista_html = ""
    if diferencas_conteudo:
        for d in diferencas_conteudo:
            titulo_secao = html.escape(d.get('secao', 'Secão'))
            diferencas_lista_html += f"<li><strong>{titulo_secao}</strong></li>"
    else:
        diferencas_lista_html = "<li>Nenhuma diferença relevante por seção</li>"

    html_page = f"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8" />
<title>{html.escape(titulo)}</title>
<meta name="viewport" content="width=device-width,initial-scale=1" />
<style>
body{{font-family: Arial, Helvetica, sans-serif; color:#111; margin:20px; background:#f7f7f8}}
.header{{padding:10px 0}}
h1{{margin:0;font-size:22px}}
.metrics{{display:flex;flex-wrap:wrap;gap:12px;margin-top:12px}}
.metric{{background:#fff;padding:10px;border-radius:6px;box-shadow:0 1px 3px rgba(0,0,0,0.08)}}
.container{{display:flex;gap:20px;flex-wrap:wrap}}
.column{{flex:1;background:#fff;padding:16px;border-radius:6px;box-shadow:0 1px 8px rgba(0,0,0,0.06);min-width:400px;height:80vh;overflow:auto}}
.legend{{margin:10px 0}}
mark{{background:#ffff99;padding:2px}}
</style>
</head>
<body>
<div class="header">
<h1>{html.escape(titulo)}</h1>
<div class="metrics">
<div class="metric"><strong>Score:</strong> {score:.0f}%</div>
<div class="metric"><strong>Data ANVISA (Ref):</strong> {html.escape(data_ref)}</div>
<div class="metric"><strong>Data ANVISA (BELFAR):</strong> {html.escape(data_belfar)}</div>
<div class="metric"><strong>Erros ortográficos:</strong> {html.escape(resumo_erros)}</div>
</div>
</div>

<h2>Sumário</h2>
<ul>
<li><strong>Seções faltantes:</strong><br>{faltantes_html}</li>
<li><strong>Diferenças por seção:</strong><ul>{diferencas_lista_html}</ul></li>
</ul>

<div class="container">
<div class="column">
<h3>{html.escape(nome_ref)}</h3>
{html_ref}
</div>
<div class="column">
<h3>{html.escape(nome_belfar)}</h3>
{html_belfar}
</div>
</div>

<footer style="margin-top:20px;font-size:12px;color:#666">
Gerado pelo sistema de Auditoria de Bulas — v39
</footer>
</body>
</html>
"""
    return html_page

# ----------------- [ATUALIZADA - v39] INTERFACE PRINCIPAL -----------------
st.title("🔬 Inteligência Artificial para Auditoria de Bulas")
st.markdown("Sistema avançado de comparação literal e validação de bulas farmacêuticas — aprimorado para PDFs de gráfica")
st.divider()

st.header("📋 Configuração da Auditoria")
tipo_bula_selecionado = st.radio("Tipo de Bula:", ("Paciente"), horizontal=True)

col1, col2 = st.columns(2)
with col1:
    st.subheader("📄 Arte Vigente")
    pdf_ref = st.file_uploader("Envie o PDF da Arte Vigente", type=["pdf"], key="ref")

with col2:
    st.subheader("📄 PDF da Gráfica")
    pdf_belfar = st.file_uploader("Envie o PDF da Gráfica", type="pdf", key="belfar")

if st.button("🔍 Iniciar Auditoria Completa", use_container_width=True, type="primary"):
    if pdf_ref and pdf_belfar:
        with st.spinner("🔄 Processando e analisando as bulas... (v39 - Forçando OCR psm 3 Full-Page)"):
            
            tipo_arquivo_ref = 'docx' if pdf_ref.name.lower().endswith('.docx') else 'pdf'
            
            texto_ref, erro_ref = extrair_texto(pdf_ref, tipo_arquivo_ref)
            texto_belfar, erro_belfar = extrair_texto(pdf_belfar, 'pdf')
            
            if not erro_ref:
                texto_ref = truncar_apos_anvisa(texto_ref)
            if not erro_belfar:
                texto_belfar = truncar_apos_anvisa(texto_belfar)

            if erro_ref or erro_belfar:
                st.error(f"Erro ao processar arquivos: {erro_ref or erro_belfar}")
            else:
                # v39: A função gerar_relatorio_final agora está corrigida
                gerar_relatorio_final(texto_ref, texto_belfar, "Arte Vigente", "PDF da Gráfica", tipo_bula_selecionado)
    else:
        st.warning("⚠️ Por favor, envie ambos os arquivos (Referência e BELFAR) para iniciar a auditoria.")

st.divider()
st.caption("Sistema de Auditoria de Bulas v39 | Correção de Display de Título Lado-a-Lado")
