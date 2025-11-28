# pages/2_Conferencia_MKT.py
#
# Versão v121 - CORREÇÃO DE CRASH E RESGATE DE TÍTULOS
# - FIX CRÍTICO: Corrigido erro de Regex "global flags" que travava a higienização de títulos.
# - RESULTADO: A função 'higienizar_titulos' agora roda e separa os títulos colados, fazendo as seções reaparecerem.
# - MANTIDO: OCR forçado para layouts largos (Provas Gráficas).

import re
import difflib
import unicodedata
import io
import streamlit as st
import fitz  # PyMuPDF
import docx
import spacy
from thefuzz import fuzz
from spellchecker import SpellChecker
from collections import namedtuple
from PIL import Image
import pytesseract

# ----------------- UI / CSS -----------------
st.set_page_config(layout="wide", page_title="Auditoria de Bulas", page_icon="🔬")

GLOBAL_CSS = """
<style>
.main .block-container {
    padding-top: 2rem !important;
    padding-bottom: 2rem !important;
    max-width: 95% !important;
}
[data-testid="stHeader"] { display: none !important; }
footer { display: none !important; }

.bula-box {
  height: 400px;
  overflow-y: auto;
  border: 1px solid #dcdcdc;
  border-radius: 6px;
  padding: 18px;
  background: #ffffff;
  font-family: "Georgia", "Times New Roman", serif;
  font-size: 14px;
  line-height: 1.6;
  color: #111;
}

.bula-box-full {
  height: 700px;
  overflow-y: auto;
  border: 1px solid #dcdcdc;
  border-radius: 6px;
  padding: 20px;
  background: #ffffff;
  font-family: "Georgia", "Times New Roman", serif;
  font-size: 14px;
  line-height: 1.6;
  color: #111;
}

.section-title {
  font-size: 15px;
  font-weight: 700;
  color: #222;
  margin: 12px 0 8px;
  padding-top: 8px;
  border-top: 1px solid #eee;
}

.ref-title { color: #0b5686; }
.bel-title { color: #0b8a3e; }

mark.diff { background-color: #ffff99; padding: 0 2px; color: black; }
mark.ort { background-color: #ffdfd9; padding: 0 2px; color: black; border-bottom: 1px dashed red; }
mark.anvisa { background-color: #DDEEFF; padding: 0 2px; color: black; border: 1px solid #0000FF; }

.stExpander > div[role="button"] { font-weight: 700; color: #333; }
</style>
"""
st.markdown(GLOBAL_CSS, unsafe_allow_html=True)

# ----------------- MODELO NLP -----------------
@st.cache_resource
def carregar_modelo_spacy():
    try:
        return spacy.load("pt_core_news_lg")
    except OSError:
        return None

nlp = carregar_modelo_spacy()

# ----------------- UTILITÁRIOS -----------------
def normalizar_texto(texto):
    if not isinstance(texto, str): return ""
    texto = texto.replace('\n', ' ')
    texto = ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')
    texto = re.sub(r'[^\w\s]', '', texto)
    texto = ' '.join(texto.split())
    return texto.lower()

def normalizar_titulo_para_comparacao(texto):
    texto_norm = normalizar_texto(texto or "")
    texto_norm = re.sub(r'^\d+\s*[\.\-)]*\s*', '', texto_norm).strip()
    return texto_norm

def truncar_apos_anvisa(texto):
    if not isinstance(texto, str): return texto
    regex_anvisa = r"((?:aprovad[ao][\s\n]+pela[\s\n]+anvisa[\s\n]+em|data[\s\n]+de[\s\n]+aprova\w+[\s\n]+na[\s\n]+anvisa:)[\s\n]*([\d]{1,2}\s*/\s*[\d]{1,2}\s*/\s*[\d]{2,4}))"
    matches = list(re.finditer(regex_anvisa, texto, re.IGNORECASE | re.DOTALL))
    if not matches: return texto
    last_match = matches[-1]
    cut_off_position = last_match.end(1)
    pos_match = re.search(r'^\s*\.', texto[cut_off_position:], re.IGNORECASE)
    if pos_match: cut_off_position += pos_match.end()
    return texto[:cut_off_position]

def _create_anchor_id(secao_nome, prefix):
    norm = normalizar_texto(secao_nome)
    norm_safe = re.sub(r'[^a-z0-9\-]', '-', norm)
    return f"anchor-{prefix}-{norm_safe}"

# ----------------- LIMPEZA CIRÚRGICA (ATUALIZADA v121) -----------------

def limpar_lixo_grafico(texto):
    """Remove lixo técnico e fragmentos específicos de provas gráficas."""
    texto_limpo = texto
    
    # 1. Padrões de "Ruído Gráfico"
    texto_limpo = re.sub(r'(?m)^.*[\[\]|—>w]{5,}.*$', '', texto_limpo)

    # 2. Remoção de Gibberish
    texto_limpo = re.sub(r'\b[a-z]*([aeiou]{3,}|[rsnt]{4,})[a-z]*\b', '', texto_limpo, flags=re.IGNORECASE)

    lixo_frases = [
        "mma USO ORAL mm USO ADULTO",
        "mem CSA comprimido",
        "MMA 1250 - 12/25",
        "Medida da bula",
        "Can Phete", "gbrangrafica", "Gibran",
        "............", "..........",
        "?. =", " . =",
        "c “ a e"
    ]
    for item in lixo_frases:
        texto_limpo = texto_limpo.replace(item, "")

    # Limpeza flexível de pontuação solta
    texto_limpo = re.sub(r':\s*\.\.\s*o\.?', ':', texto_limpo)

    # 3. Tokens curtos/soltos
    texto_limpo = re.sub(r'\b(mm|cm|gm)\b', '', texto_limpo, flags=re.IGNORECASE)

    # 4. Limpezas Específicas
    padroes_especificos = [
        r'^\s*--- PAGE \d+ ---\s*$',
        r'^\s*\d{1,3}\s*,\s*00\s*$',
        r'^\s*\d{1,3}\s*[xX]\s*\d{1,3}\s*$',
        r'^\s*[\d\.,]+\s*cm\s*$',
        r'^\s*[\d\.,]+\s*mm\s*$', 
        r'^.*Medida da bula:.*$',
        r'^.*Tipologia da bula:.*$',
        r'^.*impressas 1x0.*$',
        r'^.*cor-frente/verso.*$',
        r'^.*papel Ap \d+gr.*$',
        r'^.*Times New Roman.*$', 
        r'^.*Negrito.*Corpo.*$',
        r'^.*PROVA \d+/\d+/\d+.*$',
        r'^.*Favor conferir e enviar aprovação.*$',
        r'^.*Autorizado Sim Não.*$',
        r'^.*Atenção: não autoriz.*$',
        r'^.*Assinatura:.*$',
        r'^.*Resastres.*Aguarde NOVA PROVA.*$',
        r'^.*Gibran.*$',
        r"\s+'\s+", 
        r'.*\(?\s*31\s*\)?\s*3514\s*[-.]\s*2900.*',
        r'^\s*contato\s*$',
        r'.*:\s*19\s*,\s*0\s*x\s*45\s*,\s*0.*',
        r'.*(?:—\s*)+\s*>\s*>\s*>\s*».*',
        r'.*gm\s*>\s*>\s*>.*',              
        r'.*_{3,}.*gm.*', 
        r'.*MMA\s+\d{4}\s*-\s*\d{1,2}/\d{2,4}.*',
        r'.*PROVA\s*-\s*[\d\s/]+.*',       
        r'.*Tipologia.*',                  
        r'.*Normal\s+e.*',                 
        r'^\s*Belcomplex\s+B\s+comprimido\s*$',
        r'^\s*Belcomplex:\s*$',
        r'.*Impress[ãa]o:.*',
        r'.*artes.*belfar.*',
        r'^contato:.*',                    
        r'.*BUL\d+[A-Z0-9]*.*',
        r'.*\(\s*\d+\s*\)\s*BELFAR.*',
        r'^\s*VERSO\s*$', r'^\s*FRENTE\s*$',
        r'^\s*Verso Bula\s*$', r'^\s*Frente Bula\s*$',
        r'.*Cor:\s*Preta.*', r'.*Papel:.*', r'.*Ap\s*\d+gr.*', 
        r'.*bula do paciente.*', r'.*página \d+\s*de\s*\d+.*', 
        r'.*Arial.*', r'.*Helvética.*', 
        r'.*Cores?:.*', r'.*Preto.*', r'.*Pantone.*', 
        r'^\s*BELFAR\s*$', r'^\s*PHARMA\s*$',
        r'.*CNPJ:.*', r'.*SAC:.*', r'.*Farm\. Resp\..*', 
        r'.*Laetus.*', r'.*Pharmacode.*', 
        r'.*\b\d{6,}\s*-\s*\d{2}/\d{2}\b.*', 
        r'.*BUL_CLORIDRATO.*',
        r'^\s*450\s*$',
        r'^\s*22142800\s*$',
        r'.*☑.*', r'.*☐.*',
        r'\.{4,}',
        r'ir ie+r+e+',
        r'c tr tr r+e+',
        r'^[_\W]+$'
    ]
    
    for p in padroes_especificos:
        try:
            texto_limpo = re.sub(r'(?m)^' + p + r'$', '', texto_limpo, flags=re.IGNORECASE)
        except Exception:
            pass
            
        if p == r"\s+'\s+":
             texto_limpo = re.sub(p, ' ', texto_limpo, flags=re.IGNORECASE)
        else:
             if not p.startswith(r'^\s*'): 
                texto_limpo = re.sub(p, '', texto_limpo, flags=re.IGNORECASE)

    texto_limpo = re.sub(r'^\s*[-_.,|:;]\s*$', '', texto_limpo, flags=re.MULTILINE)
    texto_limpo = texto_limpo.replace(" se a administrado ", " se administrado ")
    texto_limpo = texto_limpo.replace("* bicarbonato", "bicarbonato")

    return texto_limpo

def corrigir_padroes_bula(texto):
    """Corrige erros de OCR detectados na auditoria."""
    if not texto: return ""
    
    # CORREÇÕES DE OCR
    texto = re.sub(r'\bMalcato\b', 'Maleato', texto, flags=re.IGNORECASE)
    texto = re.sub(r'\benalaprii\b', 'enalapril', texto, flags=re.IGNORECASE)
    texto = re.sub(r'\bRonam\b', 'Roman', texto, flags=re.IGNORECASE)
    texto = re.sub(r'\bdosc\b', 'dose', texto, flags=re.IGNORECASE)
    texto = re.sub(r'\btritamento\b', 'tratamento', texto, flags=re.IGNORECASE)
    texto = re.sub(r'\bparam\b', 'para', texto, flags=re.IGNORECASE)
    texto = re.sub(r'\bdae:\s*', 'dose: ', texto, flags=re.IGNORECASE)
    texto = re.sub(r'\bcm dosc\b', 'em dose', texto, flags=re.IGNORECASE)
    
    texto = re.sub(r'\bnlguesiomiro\b', 'algum outro', texto, flags=re.IGNORECASE)
    texto = re.sub(r'\brenda uso\b', 'fazendo uso', texto, flags=re.IGNORECASE)
    texto = re.sub(r'\btista\b', 'dentista', texto, flags=re.IGNORECASE)
    texto = re.sub(r'\bIquer\b', 'Qualquer', texto, flags=re.IGNORECASE) 
    
    texto = re.sub(r'(\d+)\s*,\s*(\d+)', r'\1,\2', texto) 
    texto = texto.replace('excipientes ” q', 'excipientes q.s.p.')
    texto = re.sub(r'101\s*excipientes', '10 mg excipientes', texto, flags=re.IGNORECASE)
    
    # Temperatura
    texto = re.sub(r'(\d+)\s*Ca\s*(\d+)', r'\1°C a \2', texto)
    texto = re.sub(r'(\d+)\s*C\b', r'\1°C', texto)
    texto = re.sub(r'(\d+)\s*["”]\s*[Cc]', r'\1°C', texto)
    texto = re.sub(r'(15|25)\s*[°"”]?\s*[Cc]?\s*a\s*300\b', r'\1°C a 30°C', texto)
    texto = re.sub(r'\b300\b', r'30°C', texto) 
    
    # Palavras quebradas
    texto = re.sub(r'\bGuarde\s*-\s*o\b', 'Guarde-o', texto, flags=re.IGNORECASE)
    texto = re.sub(r'\bGuardeo\b', 'Guarde-o', texto, flags=re.IGNORECASE)
    texto = re.sub(r'\butilizá\s*-\s*lo\b', 'utilizá-lo', texto, flags=re.IGNORECASE)
    texto = re.sub(r'\bUtilizalo\b', 'utilizá-lo', texto, flags=re.IGNORECASE)
    texto = re.sub(r'\s+([.,;?!])', r'\1', texto)
    
    return texto

# ----------------- EXTRAÇÃO -----------------

def higienizar_titulos(texto):
    """
    Insere quebras de linha antes de padrões que parecem ser títulos,
    para forçar a separação do parágrafo anterior.
    """
    if not texto: return ""
    
    # Padrões limpos sem flags inline
    padroes_titulo = [
        r"QUANDO\s+N[ÃA]O\s+DEVO\s+USAR",
        r"O\s+QUE\s+DEVO\s+SABER\s+ANTES",
        r"ONDE\s*,?\s*COMO\s+E\s+POR\s+QUANTO",
        r"COMO\s+DEVO\s+USAR",
        r"O\s+QUE\s+DEVO\s+FAZER\s+QUANDO",
        r"QUAIS\s+OS\s+MALES",
        r"O\s+QUE\s+FAZER\s+SE\s+ALGU[EÉ]M"
    ]
    
    texto_higienizado = texto
    for pat in padroes_titulo:
        # APLICAÇÃO DA CORREÇÃO: flags=re.IGNORECASE aqui, não no regex
        texto_higienizado = re.sub(f"(?<!\\n)({pat})", r"\n\n\1", texto_higienizado, flags=re.IGNORECASE)
        
    return texto_higienizado

def recuperar_titulos_perdidos(texto):
    """Recupera títulos perdidos garantindo que consumam toda a linha até o '?'"""
    if not texto: return ""
    
    mapa_recuperacao = [
        (r"(?i)(?:^|\n|[\.\?\!])\s*(\d?\s*QUANDO\s+N[ÃA]O\s+DEVO\s+USAR.*?(?:\?|\.))", r"\n\n3. QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?\n"),
        (r"(?i)(?:^|\n|[\.\?\!])\s*(\d?\s*O\s+QUE\s+DEVO\s+SABER\s+ANTES.*?(?:\?|\.))", r"\n\n4. O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?\n"),
        (r"(?i)(?:^|\n|[\.\?\!])\s*(\d?\s*ONDE\s*,?\s*COMO\s+E\s+POR\s+QUANTO.*?(?:\?|\.))", r"\n\n5. ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?\n"),
        (r"(?i)(?:^|\n|[\.\?\!])\s*(\d?\s*COMO\s+DEVO\s+USAR.*?(?:\?|\.))", r"\n\n6. COMO DEVO USAR ESTE MEDICAMENTO?\n"),
        (r"(?i)(?:^|\n|[\.\?\!])\s*(\d?\s*O\s+QUE\s+DEVO\s+FAZER\s+QUANDO.*?(?:\?|\.))", r"\n\n7. O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?\n"),
        (r"(?i)(?:^|\n|[\.\?\!])\s*(\d?\s*QUAIS\s+OS\s+MALES.*?(?:\?|\.))", r"\n\n8. QUAIS OS MALES QUE ESTE MEDICAMENTO PODE ME CAUSAR?\n"),
        (r"(?i)(?:^|\n|[\.\?\!])\s*(\d?\s*O\s+QUE\s+FAZER\s+SE\s+ALGU[EÉ]M.*?(?:\?|\.))", r"\n\n9. O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?\n"),
    ]
    
    texto_recuperado = texto
    for padrao, substituicao in mapa_recuperacao:
        texto_recuperado = re.sub(padrao, substituicao, texto_recuperado, flags=re.DOTALL)
        
    return texto_recuperado

def forcar_titulos_bula(texto):
    substituicoes = [
        (r"(?:1\.?\s*)?PARA\s*QUE\s*ESTE\s*MEDICAMENTO\s*[\s\S]{0,100}?INDICADO\??", r"\n1. PARA QUE ESTE MEDICAMENTO É INDICADO?\n"),
        (r"(?:2\.?\s*)?COMO\s*ESTE\s*MEDICAMENTO\s*[\s\S]{0,100}?FUNCIONA\??", r"\n2. COMO ESTE MEDICAMENTO FUNCIONA?\n"),
        (r"(?:3\.?\s*)?QUANDO\s*N[ÃA]O\s*DEVO\s*USAR\s*[\s\S]{0,100}?MEDICAMENTO\??", r"\n3. QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?\n"),
        (r"(?:4\.?\s*)?O\s*QUE\s*DEVO\s*SABER[\s\S]{1,100}?USAR[\s\S]{1,100}?MEDICAMENTO\??", r"\n4. O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?\n"),
        (r"(?:5\.?\s*)?ONDE\s*,?\s*COMO\s*E\s*POR\s*QUANTO[\s\S]{1,100}?GUARDAR[\s\S]{1,100}?MEDICAMENTO\??", r"\n5. ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?\n"),
        (r"(?:6\.?\s*)?COMO\s*(?:DEVO\s*USAR\s*ESTE\s*)?MEDICAMENTO.*?(?:\?|\.|=)", r"\n6. COMO DEVO USAR ESTE MEDICAMENTO?\n"), 
        (r"(?:7\.?\s*)?O\s*QUE\s*DEVO\s*FAZER[\s\S]{0,200}?MEDICAMENTO\??", r"\n7. O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?\n"),
        (r"(?:8\.?\s*)?(?:QUAIS\s*)?OS\s*MALES\s*Q(?:UE|uE)\s*ESTE\s*MEDICAMENTO\s*PODE\s*(?:ME\s*)?CAUSAR\??", r"\n8. QUAIS OS MALES QUE ESTE MEDICAMENTO PODE ME CAUSAR?\n"),
        (r"(?:9\.?\s*)?O\s*QUE\s*FAZER\s*SE\s*ALGU[EÉ]M\s*USAR[\s\S]{0,400}?MEDICAMENTO\??", r"\n9. O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?\n"),
    ]
    texto_arrumado = texto
    for padrao, substituto in substituicoes:
        texto_arrumado = re.sub(padrao, substituto, texto_arrumado, flags=re.IGNORECASE | re.DOTALL)
    return texto_arrumado

def limpar_restos_de_titulo(texto):
    restos = [
        r"^DE\s*USAR\s*ESTE\s*MEDICAMENTO\s*\?\s*",
        r"^ESTE\s*MEDICAMENTO\s*\?\s*",
        r"^GUARDAR\s*ESTE\s*MEDICAMENTO\s*\?\s*",
        r"^MEDICAMENTO\s*PODE\s*ME\s*CAUSAR\s*\?\s*",
        r"^sino\s*"
    ]
    texto_limpo = texto
    for resto in restos:
        texto_limpo = re.sub(resto, "", texto_limpo, flags=re.MULTILINE | re.IGNORECASE)
    return texto_limpo

def executar_ocr_paginado(arquivo_bytes):
    textos_paginas = []
    with fitz.open(stream=io.BytesIO(arquivo_bytes), filetype="pdf") as doc:
        for page in doc:
            pix = page.get_pixmap(dpi=300)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            try: 
                # OCR com PSM 1 para melhor detecção de layouts complexos
                txt = pytesseract.image_to_string(img, lang='por', config='--psm 1')
                if len(txt) < 100:
                    txt = pytesseract.image_to_string(img, lang='por', config='--psm 3')
                textos_paginas.append(txt)
            except: 
                textos_paginas.append("")
    return textos_paginas

def verifica_qualidade_texto(texto):
    if not texto: return False
    t_limpo = re.sub(r'\s+', '', unicodedata.normalize('NFD', texto).lower())
    keywords = ["1paraque", "2comoeste", "3quando", "4oque", "8quaisos"]
    hits = sum(1 for k in keywords if k in t_limpo)
    return hits >= 4

def check_is_proof(page):
    rect = page.rect
    width_cm = rect.width / 72 * 2.54
    if width_cm > 35: return True
    return False

def extrair_texto_hibrido(arquivo, tipo_arquivo, is_marketing_pdf=False):
    if arquivo is None: return "", "Arquivo não enviado."
    try:
        arquivo.seek(0)
        arquivo_bytes = arquivo.read()
        texto_completo = ""
        usou_ocr = False
        force_ocr = False

        if tipo_arquivo == 'pdf' and is_marketing_pdf:
            with fitz.open(stream=io.BytesIO(arquivo_bytes), filetype="pdf") as doc:
                if len(doc) > 0 and check_is_proof(doc[0]):
                    st.toast(f"📐 Layout de Bula Gráfica detectado (>35cm). Forçando OCR...", icon="📏")
                    force_ocr = True

        if not force_ocr and tipo_arquivo == 'pdf':
            pages_text = []
            with fitz.open(stream=io.BytesIO(arquivo_bytes), filetype="pdf") as doc:
                for i, page in enumerate(doc):
                    txt = page.get_text() 
                    pages_text.append(txt)
            
            if len(pages_text) >= 2:
                p1_sample = pages_text[0][:1500].upper()
                p1_verso = "VERSO" in p1_sample or "DIZERES LEGAIS" in p1_sample
                p2_sample = pages_text[1][:1500].upper() if len(pages_text) > 1 else ""
                p2_frente = "FRENTE" in p2_sample or "APRESENTAÇÕES" in p2_sample
                if p1_verso and p2_frente: pages_text = [pages_text[1], pages_text[0]]
            
            texto_completo = "\n".join(pages_text)

        elif tipo_arquivo == 'docx':
            doc = docx.Document(io.BytesIO(arquivo_bytes))
            texto_completo = "\n".join([p.text for p in doc.paragraphs])

        if force_ocr or (is_marketing_pdf and not verifica_qualidade_texto(texto_completo)):
            if not force_ocr:
                st.warning(f"⚠️ Seções faltando no texto nativo. Ativando OCR corretivo...", icon="👁️")
            
            ocr_pages = executar_ocr_paginado(arquivo_bytes)
            if len(ocr_pages) >= 2:
                p1_ocr = ocr_pages[0][:2000].upper()
                p1_verso = "VERSO" in p1_ocr or "DIZERES LEGAIS" in p1_ocr
                p2_ocr = ocr_pages[1][:2000].upper() if len(ocr_pages) > 1 else ""
                p2_frente = "FRENTE" in p2_ocr or "APRESENTAÇÕES" in p2_ocr
                if p1_verso and p2_frente: ocr_pages = [ocr_pages[1], ocr_pages[0]]
            
            texto_completo = "\n".join(ocr_pages)
            usou_ocr = True

        if texto_completo:
            invis = ['\u00AD', '\u200B', '\u200C', '\u200D', '\uFEFF']
            for c in invis: texto_completo = texto_completo.replace(c, '')
            texto_completo = texto_completo.replace('\r\n', '\n').replace('\r', '\n').replace('\u00A0', ' ')
            
            texto_completo = limpar_lixo_grafico(texto_completo)
            texto_completo = corrigir_padroes_bula(texto_completo)
            texto_completo = higienizar_titulos(texto_completo) # Tenta separar títulos colados
            texto_completo = recuperar_titulos_perdidos(texto_completo)
            texto_completo = forcar_titulos_bula(texto_completo)
            texto_completo = limpar_restos_de_titulo(texto_completo)
            
            texto_completo = re.sub(r'(?m)^\s*\d{1,2}\.\s*$', '', texto_completo)
            texto_completo = re.sub(r'(?m)^_+$', '', texto_completo)
            texto_completo = re.sub(r'\n{3,}', '\n\n', texto_completo)
            
            return texto_completo.strip(), None

    except Exception as e:
        return "", f"Erro: {e}"

# ----------------- RECONSTRUÇÃO E ANÁLISE -----------------
def reconstruir_paragrafos(texto):
    if not texto: return ""
    linhas = texto.split('\n')
    linhas_out = []
    buffer = ""
    for linha in linhas:
        l_strip = linha.strip()
        if not l_strip or (len(l_strip) < 3 and not re.match(r'^\d+\.?$', l_strip)):
            if buffer: linhas_out.append(buffer); buffer = ""
            if not linhas_out or linhas_out[-1] != "": linhas_out.append("")
            continue
        first = l_strip.split('\n')[0]
        is_title = re.match(r'^\d+\s*[\.\-)]*\s+[A-ZÁÉÍÓÚÂÊÔÃÕÇ]', first) or (first.isupper() and len(first)>4 and not first.strip().endswith('.'))
        if is_title:
            if buffer: linhas_out.append(buffer); buffer = ""
            linhas_out.append(l_strip)
            continue
        if buffer:
            if buffer.endswith('-'): buffer = buffer[:-1] + l_strip
            elif not buffer.endswith(('.', ':', '!', '?')): buffer += " " + l_strip
            else: linhas_out.append(buffer); buffer = l_strip
        else: buffer = l_strip
    if buffer: linhas_out.append(buffer)
    return "\n".join(linhas_out)

def obter_secoes_por_tipo():
    return [
        "APRESENTAÇÕES", "COMPOSIÇÃO",
        "1.PARA QUE ESTE MEDICAMENTO É INDICADO?", "2.COMO ESTE MEDICAMENTO FUNCIONA?",
        "3.QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?", "4.O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?",
        "5.ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?", "6.COMO DEVO USAR ESTE MEDICAMENTO?",
        "7.O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?",
        "8.QUAIS OS MALES QUE ESTE MEDICAMENTO PODE CAUSAR?",
        "9.O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?",
        "DIZERES LEGAIS"
    ]

def obter_aliases_secao():
    return {
        "PARA QUE ESTE MEDICAMENTO É INDICADO?": "1.PARA QUE ESTE MEDICAMENTO É INDICADO?",
        "COMO ESTE MEDICAMENTO FUNCIONA?": "2.COMO ESTE MEDICAMENTO FUNCIONA?",
        "QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?": "3.QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?",
        "O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?": "4.O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?",
        "ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICamento?": "5.ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?",
        "COMO DEVO USAR ESTE MEDICAMENTO?": "6.COMO DEVO USAR ESTE MEDICAMENTO?",
        "O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?": "7.O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?",
        "QUAIS OS MALES QUE ESTE MEDICAMENTO PODE CAUSAR?": "8.QUAIS OS MALES QUE ESTE MEDICAMENTO PODE CAUSAR?",
        "O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?": "9.O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?",
    }

def obter_secoes_ignorar_comparacao(): return ["APRESENTAÇÕES", "COMPOSIÇÃO", "DIZERES LEGAIS"]
def obter_secoes_ignorar_ortografia(): return ["COMPOSIÇÃO", "DIZERES LEGAIS"]

HeadingCandidate = namedtuple("HeadingCandidate", ["index", "raw", "norm", "numeric", "matched_canon", "score"])

def construir_heading_candidates(linhas, secoes_esperadas, aliases):
    titulos_possiveis = {s: s for s in secoes_esperadas}
    for a, c in aliases.items():
        if c in secoes_esperadas: titulos_possiveis[a] = c
    titulos_norm = {k: normalizar_titulo_para_comparacao(k) for k in titulos_possiveis.keys()}
    candidates = []
    for i, linha in enumerate(linhas):
        raw = (linha or "").strip()
        if not raw: continue
        norm = normalizar_titulo_para_comparacao(raw)
        best_score = 0; best_canon = None
        mnum = re.match(r'^\s*(\d{1,2})\s*[\.\)\-]?\s*(.*)$', raw)
        numeric = int(mnum.group(1)) if mnum else None
        for t_possivel, t_canon in titulos_possiveis.items():
            t_norm = titulos_norm.get(t_possivel, "")
            if not t_norm: continue
            score = fuzz.token_set_ratio(t_norm, norm)
            if t_norm in norm: score = max(score, 95)
            if score > best_score: best_score = score; best_canon = t_canon
        is_candidate = False
        if numeric is not None: is_candidate = True
        elif best_score >= 88: is_candidate = True
        if is_candidate:
            candidates.append(HeadingCandidate(index=i, raw=raw, norm=norm, numeric=numeric, matched_canon=best_canon if best_score >= 80 else None, score=best_score))
    unique = {c.index: c for c in candidates}
    return sorted(unique.values(), key=lambda x: x.index)

def mapear_secoes_deterministico(texto_completo, secoes_esperadas):
    linhas = texto_completo.split('\n')
    aliases = obter_aliases_secao()
    candidates = construir_heading_candidates(linhas, secoes_esperadas, aliases)
    mapa = []
    last_idx = -1
    for sec_idx, sec in enumerate(secoes_esperadas):
        sec_norm = normalizar_titulo_para_comparacao(sec)
        found = None
        for c in candidates:
            if c.index <= last_idx: continue
            if c.matched_canon == sec: found = c; break
        if not found:
            for c in candidates:
                if c.index <= last_idx: continue
                if c.numeric == (sec_idx + 1): found = c; break
        if not found:
            for c in candidates:
                if c.index <= last_idx: continue
                if sec_norm and sec_norm in c.norm: found = c; break
        if not found:
            for c in candidates:
                if c.matched_canon == sec or (c.numeric == (sec_idx + 1)):
                    if c.numeric == (sec_idx + 1) or c.score > 95: found = c; break
        if found:
            mapa.append({'canonico': sec, 'titulo_encontrado': found.raw, 'linha_inicio': found.index})
            if found.index > last_idx: last_idx = found.index
    mapa = sorted(mapa, key=lambda x: x['linha_inicio'])
    return mapa, candidates, linhas

def obter_dados_secao_v2(secao_canonico, mapa_secoes, linhas_texto):
    entrada = None
    for m in mapa_secoes:
        if m['canonico'] == secao_canonico: entrada = m; break
    if not entrada: return False, None, ""
    linha_inicio = entrada['linha_inicio']
    if secao_canonico.strip().upper() == "DIZERES LEGAIS": linha_fim = len(linhas_texto)
    else:
        sorted_map = sorted(mapa_secoes, key=lambda x: x['linha_inicio'])
        prox_idx = None
        for m in sorted_map:
            if m['linha_inicio'] > linha_inicio: prox_idx = m['linha_inicio']; break
        linha_fim = prox_idx if prox_idx is not None else len(linhas_texto)
    conteudo_lines = []
    for i in range(linha_inicio + 1, linha_fim):
        line_norm = normalizar_titulo_para_comparacao(linhas_texto[i])
        if line_norm in {normalizar_titulo_para_comparacao(s) for s in obter_secoes_por_tipo()}: break
        conteudo_lines.append(linhas_texto[i])
    return True, entrada['titulo_encontrado'], "\n".join(conteudo_lines).strip()

def verificar_secoes_e_conteudo(texto_ref, texto_belfar):
    secoes_esperadas = obter_secoes_por_tipo()
    ignore_comparison = [s.upper() for s in obter_secoes_ignorar_comparacao()]
    secoes_faltantes, diferencas_conteudo, similaridades_secoes, diferencas_titulos = [], [], [], []
    secoes_analisadas = []

    mapa_ref, _, linhas_ref = mapear_secoes_deterministico(texto_ref, secoes_esperadas)
    mapa_belfar, _, linhas_belfar = mapear_secoes_deterministico(texto_belfar, secoes_esperadas)

    for sec in secoes_esperadas:
        encontrou_ref, titulo_ref, conteudo_ref = obter_dados_secao_v2(sec, mapa_ref, linhas_ref)
        encontrou_belfar, titulo_belfar, conteudo_belfar = obter_dados_secao_v2(sec, mapa_belfar, linhas_belfar)

        if not encontrou_ref and not encontrou_belfar:
            secoes_faltantes.append(sec)
            secoes_analisadas.append({'secao': sec, 'tem_diferenca': True, 'faltante': True, 'ignorada': False, 'conteudo_ref': "", 'conteudo_belfar': ""})
            continue

        if not encontrou_belfar:
            secoes_faltantes.append(sec)
            secoes_analisadas.append({'secao': sec, 'tem_diferenca': True, 'faltante': True, 'ignorada': False, 'conteudo_ref': conteudo_ref, 'conteudo_belfar': ""})
            continue

        if sec.upper() in ignore_comparison:
            secoes_analisadas.append({'secao': sec, 'conteudo_ref': conteudo_ref, 'conteudo_belfar': conteudo_belfar, 'tem_diferenca': False, 'ignorada': True, 'faltante': False})
            continue

        norm_ref = re.sub(r'([.,;?!()\[\]])', r' \1 ', conteudo_ref or "")
        norm_bel = re.sub(r'([.,;?!()\[\]])', r' \1 ', conteudo_belfar or "")
        norm_ref = normalizar_texto(norm_ref)
        norm_bel = normalizar_texto(norm_bel)

        tem_diferenca = False
        if norm_ref != norm_bel:
            tem_diferenca = True
            diferencas_conteudo.append({'secao': sec})
            similaridades_secoes.append(0)
        else:
            similaridades_secoes.append(100)

        secoes_analisadas.append({
            'secao': sec, 'conteudo_ref': conteudo_ref, 'conteudo_belfar': conteudo_belfar,
            'titulo_encontrado_ref': titulo_ref, 'titulo_encontrado_belfar': titulo_belfar,
            'tem_diferenca': tem_diferenca, 'ignorada': False, 'faltante': False
        })
    return secoes_faltantes, diferencas_conteudo, similaridades_secoes, diferencas_titulos, secoes_analisadas

def checar_ortografia_inteligente(texto_para_checar, texto_referencia):
    if not texto_para_checar: return []
    try:
        spell = SpellChecker(language='pt')
        palavras_ignorar = {"alair", "belfar", "peticionamento", "urotrobel", "nebacetin", "sac"}
        vocab_ref_raw = set(re.findall(r'\b[a-zA-ZÀ-ÖØ-öø-ÿ0-9\-]+\b', (texto_referencia or "").lower()))
        spell.word_frequency.load_words(vocab_ref_raw.union(palavras_ignorar))
        palavras = re.findall(r'\b[a-zA-ZÀ-ÖØ-öø-ÿ]+\b', texto_para_checar)
        palavras = [p for p in palavras if len(p) > 2]
        possiveis_erros = set(spell.unknown([p.lower() for p in palavras]))
        erros_filtrados = []
        vocab_norm = set(normalizar_texto(w) for w in vocab_ref_raw)
        for e in possiveis_erros:
            e_norm = normalizar_texto(e)
            if e.lower() not in vocab_ref_raw and e_norm not in vocab_norm:
                erros_filtrados.append(e)
        return sorted(set(erros_filtrados))[:60]
    except: return []

def marcar_diferencas_palavra_por_palavra(texto_ref, texto_belfar, eh_referencia):
    def pre_norm(txt): return re.sub(r'([.,;?!()\[\]])', r' \1 ', txt or "")
    def tokenizar(txt): return re.findall(r'\n|[A-Za-zÀ-ÖØ-öø-ÿ0-9_•]+|[^\w\s]', pre_norm(txt), re.UNICODE)
    def norm(tok): return ' ' if tok == '\n' else (normalizar_texto(tok) if re.match(r'\w+', tok) else tok.strip())

    ref_tokens = tokenizar(texto_ref)
    bel_tokens = tokenizar(texto_belfar)
    ref_norm = [norm(t) for t in ref_tokens]
    bel_norm = [norm(t) for t in bel_tokens]
    matcher = difflib.SequenceMatcher(None, ref_norm, bel_norm, autojunk=False)
    indices = set()
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != 'equal': indices.update(range(i1, i2) if eh_referencia else range(j1, j2))
    
    tokens = ref_tokens if eh_referencia else bel_tokens
    marcado = []
    for idx, tok in enumerate(tokens):
        if tok == '\n': marcado.append('<br>'); continue
        if idx in indices and tok.strip() != '': marcado.append(f"<mark class='diff'>{tok}</mark>")
        else: marcado.append(tok)
    
    resultado = ""
    for i, tok in enumerate(marcado):
        if i == 0: resultado += tok; continue
        raw_tok = re.sub(r'^<mark[^>]*>|</mark>$', '', tok)
        if re.match(r'^[.,;:!?)\\]$', raw_tok) or tok=='<br>' or marcado[i-1]=='<br>': resultado += tok
        else: resultado += " " + tok
    return re.sub(r"(</mark>)\s+(<mark[^>]*>)", " ", resultado)

def construir_html_secoes(secoes_analisadas, erros_ortograficos, eh_referencia=False):
    html_map = {}
    prefixos = {
        "PARA QUE ESTE MEDICAMENTO É INDICADO": "1.", "COMO ESTE MEDICAMENTO FUNCIONA?": "2.",
        "QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?": "3.", "O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?": "4.",
        "ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?": "5.", "COMO DEVO USAR ESTE MEDICAMENTO?": "6.",
        "O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?": "7.", "QUAIS OS MALES QUE ESTE MEDICAMENTO PODE CAUSAR?": "8.",
        "O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?": "9."
    }
    mapa_erros = {}
    if erros_ortograficos and not eh_referencia:
        for erro in erros_ortograficos:
            pattern = r'(?<![<>a-zA-Z])(?<!mark>)(?<!;>)\b(' + re.escape(erro) + r')\b(?![<>])'
            mapa_erros[pattern] = r"<mark class='ort'>\1</mark>"
            
    regex_anvisa = r"((?:aprovad[ao]\s+pela\s+anvisa\s+em|data\s+de\s+aprovação\s+na\s+anvisa:)\s*[\d]{1,2}/[\d]{1,2}/[\d]{2,4})"
    anvisa_pattern = re.compile(regex_anvisa, re.IGNORECASE)

    for diff in secoes_analisadas:
        sec = diff['secao']
        prefixo = prefixos.get(sec, "")
        if eh_referencia:
            tit = f"{prefixo} {sec}".strip()
            title_html = f"<div class='section-title ref-title'>{tit}</div>"
            conteudo = diff['conteudo_ref'] or ""
        else:
            tit_enc = diff.get('titulo_encontrado_belfar') or diff.get('titulo_encontrado_ref') or sec
            tit = f"{prefixo} {tit_enc}".strip() if prefixo and not tit_enc.strip().startswith(prefixo) else tit_enc
            title_html = f"<div class='section-title bel-title'>{tit}</div>"
            conteudo = diff['conteudo_belfar'] or ""

        if diff.get('ignorada', False):
            c_html = (conteudo or "").replace('\n', '<br>')
        else:
            c_html = marcar_diferencas_palavra_por_palavra(diff.get('conteudo_ref') or "", diff.get('conteudo_belfar') or "", eh_referencia)
        
        c_html = re.sub(r'(<br\s*/?>\s*){3,}', '<br><br>', c_html)
        
        if not eh_referencia and not diff.get('ignorada', False):
            for pat, repl in mapa_erros.items():
                try: c_html = re.sub(pat, repl, c_html, flags=re.IGNORECASE)
                except: pass
        
        c_html = anvisa_pattern.sub(r"<mark class='anvisa'>\1</mark>", c_html)
        anchor_id = _create_anchor_id(sec, "ref" if eh_referencia else "bel")
        html_map[sec] = f"<div id='{anchor_id}' style='scroll-margin-top: 20px;'>{title_html}<div style='margin-top:6px;'>{c_html}</div></div>"
    return html_map

def detectar_tipo_arquivo_por_score(texto):
    if not texto: return "Indeterminado"
    titulos_paciente = ["como este medicamento funciona", "o que devo saber antes de usar"]
    titulos_profissional = ["resultados de eficacia", "caracteristicas farmacologicas"]
    t_norm = normalizar_texto(texto)
    score_pac = sum(1 for t in titulos_paciente if t in t_norm)
    score_prof = sum(1 for t in titulos_profissional if t in t_norm)
    if score_pac > score_prof: return "Paciente"
    elif score_prof > score_pac: return "Profissional"
    return "Indeterminado"

def gerar_relatorio_final(texto_ref, texto_belfar, nome_ref, nome_belfar, tipo_bula):
    st.header("Relatório de Auditoria Inteligente")
    rx_anvisa = r"(aprovad[ao]\s+pela\s+anvisa\s+em|data\s+de\s+aprovação\s+na\s+anvisa:)\s*([\d]{1,2}/[\d]{1,2}/[\d]{2,4})"
    m_ref = re.search(rx_anvisa, texto_ref or "", re.IGNORECASE)
    m_bel = re.search(rx_anvisa, texto_belfar or "", re.IGNORECASE)
    data_ref = m_ref.group(2).strip() if m_ref else "Não encontrada"
    data_bel = m_bel.group(2).strip() if m_bel else "Não encontrada"

    secoes_faltantes, diferencas_conteudo, similaridades, diferencas_titulos, secoes_analisadas = verificar_secoes_e_conteudo(texto_ref, texto_belfar)
    erros = checar_ortografia_inteligente(texto_belfar, texto_ref)
    score = sum(similaridades)/len(similaridades) if similaridades else 100.0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Conformidade", f"{score:.0f}%")
    c2.metric("Erros Ortográficos", len(erros))
    c3.metric("Data ANVISA (Ref)", data_ref)
    c4.metric("Data ANVISA (Bel)", data_bel)

    st.divider()
    st.subheader("Seções (clique para expandir)")
    
    html_ref = construir_html_secoes(secoes_analisadas, [], True)
    html_bel = construir_html_secoes(secoes_analisadas, erros, False)
    prefixos = {"PARA QUE ESTE MEDICAMENTO É INDICADO": "1.", "COMO ESTE MEDICAMENTO FUNCIONA?": "2.", "QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?": "3.", "O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?": "4.", "ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?": "5.", "COMO DEVO USAR ESTE MEDICAMENTO?": "6.", "O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?": "7.", "QUAIS OS MALES QUE ESTE MEDICAMENTO PODE CAUSAR?": "8.", "O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?": "9."}

    for diff in secoes_analisadas:
        sec = diff['secao']
        pref = prefixos.get(sec, "")
        tit = f"{pref} {sec}" if pref else sec
        status = "✅ Idêntico"
        if diff.get('faltante'): status = "🚨 FALTANTE"
        elif diff.get('ignorada'): status = "⚠️ Ignorada"
        elif diff.get('tem_diferenca'): status = "❌ Divergente"

        with st.expander(f"{tit} — {status}", expanded=(diff.get('tem_diferenca') or diff.get('faltante'))):
            c1, c2 = st.columns([1,1], gap="large")
            with c1:
                st.markdown(f"**{nome_ref}**", unsafe_allow_html=True)
                st.markdown(f"<div class='bula-box'>{html_ref.get(sec, '<i>N/A</i>')}</div>", unsafe_allow_html=True)
            with c2:
                st.markdown(f"**{nome_belfar}**", unsafe_allow_html=True)
                st.markdown(f"<div class='bula-box'>{html_bel.get(sec, '<i>N/A</i>')}</div>", unsafe_allow_html=True)

    st.divider()
    st.subheader("🎨 Visualização Completa")
    full_order = [s['secao'] for s in secoes_analisadas]
    h_r = "".join([html_ref.get(s, "") for s in full_order])
    h_b = "".join([html_bel.get(s, "") for s in full_order])
    
    cr, cb = st.columns(2, gap="large")
    with cr: st.markdown(f"**📄 {nome_ref}**<div class='bula-box-full'>{h_r}</div>", unsafe_allow_html=True)
    with cb: st.markdown(f"**📄 {nome_belfar}**<div class='bula-box-full'>{h_b}</div>", unsafe_allow_html=True)

# ----------------- MAIN -----------------
st.title("🔬 Inteligência Artificial para Auditoria de Bulas (v121)")
st.markdown("Sistema com validação RÍGIDA: OCR otimizado e correção de regex.")

st.divider()
tipo_bula_selecionado = "Paciente" # Fixo

col1, col2 = st.columns(2)
with col1:
    st.subheader("📄 Arte Vigente")
    pdf_ref = st.file_uploader("PDF/DOCX Referência", type=["pdf", "docx"], key="ref")
with col2:
    st.subheader("📄 PDF da Gráfica")
    pdf_belfar = st.file_uploader("PDF vindo da Gráfica", type=["pdf", "docx"], key="belfar")

if st.button("🔍 Iniciar Auditoria Completa", use_container_width=True, type="primary"):
    if not (pdf_ref and pdf_belfar):
        st.warning("⚠️ Envie ambos os arquivos.")
    else:
        with st.spinner("Lendo arquivos, reordenando páginas e limpando layout..."):
            # Ambos usam extrator inteligente para garantir leitura correta de colunas
            texto_ref_raw, erro_ref = extrair_texto_hibrido(pdf_ref, 'docx' if pdf_ref.name.endswith('.docx') else 'pdf', is_marketing_pdf=True)
            texto_belfar_raw, erro_belfar = extrair_texto_hibrido(pdf_belfar, 'docx' if pdf_belfar.name.endswith('.docx') else 'pdf', is_marketing_pdf=True)

            if erro_ref or erro_belfar:
                st.error(f"Erro de leitura: {erro_ref or erro_belfar}")
            else:
                detectado_ref = detectar_tipo_arquivo_por_score(texto_ref_raw)
                detectado_bel = detectar_tipo_arquivo_por_score(texto_belfar_raw)
                
                erro = False
                if detectado_ref == "Profissional": 
                    st.error(f"🚨 Arquivo ANVISA parece Bula Profissional. Use Paciente."); erro=True
                if detectado_bel == "Profissional":
                    st.error(f"🚨 Arquivo MKT parece Bula Profissional. Use Paciente."); erro=True
                
                if not erro:
                    t_ref = reconstruir_paragrafos(texto_ref_raw)
                    t_ref = truncar_apos_anvisa(t_ref)
                    
                    t_bel = reconstruir_paragrafos(texto_belfar_raw)
                    t_bel = truncar_apos_anvisa(t_bel)
                    
                    gerar_relatorio_final(t_ref, t_bel, pdf_ref.name, pdf_belfar.name, tipo_bula_selecionado)

st.divider()
st.caption("Sistema de Auditoria v121 | FIX CRÍTICO DE REGEX e OCR.")
