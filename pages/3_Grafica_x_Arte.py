# -*- coding: utf-8 -*-

# Aplicativo Streamlit: Auditoria de Bulas (v57 - Limpeza Gráfica & Visual Aprimorado)
# - Interface: SEM seleção de tipo (Fixo em "Paciente").
# - Motor: Híbrido (Texto Nativo -> Fallback para OCR Automático).
# - Regra: Bloqueia automaticamente se detectar "Profissional".
# - NOVO: Limpeza agressiva de marcas de corte/impressão e correção de títulos quebrados.
# - NOVO: Texto justificado e fluido nas caixas.

import streamlit as st
import fitz  # PyMuPDF
import docx
import re
import spacy
from spellchecker import SpellChecker
import difflib
import unicodedata
import io
from PIL import Image
import pytesseract
from thefuzz import fuzz
from collections import namedtuple

# ----------------- UI / CSS (Visual Aprimorado) -----------------
st.set_page_config(layout="wide", page_title="Auditoria de Bulas", page_icon="🔬")

GLOBAL_CSS = """
<style>
[data-testid="stHeader"] { display: none !important; }
footer { display: none !important; }

.bula-box {
  height: 500px; /* Aumentei um pouco */
  overflow-y: auto;
  border: 1px solid #dcdcdc;
  border-radius: 8px;
  padding: 25px; /* Mais espaçamento interno */
  background: #ffffff;
  font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif;
  font-size: 15px; /* Fonte levemente maior */
  line-height: 1.7; /* Melhor leitura */
  color: #222;
  text-align: justify; /* Texto "bonitinho" do inicio ao fim */
  white-space: pre-wrap; /* Mantém parágrafos mas permite quebra de linha responsiva */
}

.bula-box-full {
  height: 700px;
  overflow-y: auto;
  border: 1px solid #dcdcdc;
  border-radius: 8px;
  padding: 25px;
  background: #ffffff;
  font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif;
  font-size: 15px;
  line-height: 1.7;
  color: #222;
  text-align: justify;
}

.section-title {
  font-size: 16px;
  font-weight: 800;
  color: #1a1a1a;
  margin: 15px 0 10px;
  border-bottom: 2px solid #eee;
  padding-bottom: 6px;
  text-transform: uppercase;
}

mark.diff { background-color: #ffff99; padding: 2px 4px; border-radius: 4px; font-weight: bold; }
mark.ort { background-color: #ffdfd9; padding: 2px 4px; border-radius: 4px; text-decoration: underline wavy #ff5555; }
mark.anvisa { background-color: #cce5ff; padding: 2px 4px; font-weight:600; border-radius: 4px; }

.stExpander > div[role="button"] { font-weight: 600; color: #333; font-size: 15px; }
.ref-title { color: #005a9c; font-weight:800; } /* Azul mais profissional */
.bel-title { color: #2e7d32; font-weight:800; } /* Verde mais profissional */
.small-muted { color:#666; font-size:12px; }
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


# ----------------- FUNÇÕES DE LIMPEZA E OCR -----------------

def limpar_lixo_grafica_belfar(texto: str) -> str:
    """Remove especificamente o lixo técnico da gráfica Belfar e marcas de corte."""
    if not texto: return ""
    
    # Lista de padrões de lixo para remover (Baseado no seu input)
    padroes_lixo = [
        r"BUL\s*BELSPAN\s*COMPRIMIDO.*",
        r"BUL\d+V\d+",
        r"Medida da bula:.*",
        r"Impressão: Frente.*",
        r"Papel: Ap 56gr.*",
        r"BELSPAN: Times New Roman.*",
        r"Cor: Preta.*",
        r"Normal e Negrito.*Corpo \d+",
        r"Negrito\. Corpo \d+",
        r"BELFAR\s*contato",
        r"\(31\) 3514-\s*2900",
        r"artes@belfar\.com\.br",
        r"artesObelfar\. com\. br", # Erro OCR comum
        r"\d+a\s*prova.*", # 1a prova
        r"\d+/\d+/\d+", # Datas soltas de prova
        r"e?[-—_]{5,}\s*190\s*mm.*", # Linha de corte
        r"190\s*mm\s*>>",
        r"45\s*,\s*0\s*cm",
        r"4\s*\.\s*0\s*cm",
        r"Mm\s*>>>",
        r"\|" # Barras verticais soltas
    ]
    
    # Remove os padrões
    for padrao in padroes_lixo:
        texto = re.sub(padrao, "", texto, flags=re.IGNORECASE)
    
    # Limpeza de quebras de linha excessivas deixadas pela remoção
    texto = re.sub(r'\n{3,}', '\n\n', texto)
    
    return texto

def consertar_titulos_quebrados(texto: str) -> str:
    """Conserta títulos que foram quebrados em duas linhas pelo OCR."""
    # Caso 3: QUANDO NÃO DEVO USAR ESTE [quebra] MEDICAMENTO?
    texto = re.sub(r"(?i)(QUANDO NÃO DEVO USAR ESTE)\s*\n\s*(MEDICAMENTO\?)", r"\1 \2", texto)
    
    # Caso 4: O QUE DEVO SABER ANTES DE USAR ESTE [quebra] MEDICAMENTO?
    texto = re.sub(r"(?i)(O QUE DEVO SABER ANTES DE USAR ESTE)\s*\n\s*(MEDICAMENTO\?)", r"\1 \2", texto)
    
    # Caso 9: O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA [quebra] DESTE MEDICAMENTO?
    texto = re.sub(r"(?i)(INDICADA)\s*\n\s*(DESTE MEDICAMENTO\?)", r"\1 \2", texto)
    
    return texto

def fluir_texto(texto: str) -> str:
    """
    Remove quebras de linha no meio de frases para o texto ficar 'bonitinho' (justificado).
    Mantém quebras apenas se parecer ser um novo parágrafo ou item de lista.
    """
    linhas = texto.split('\n')
    novo_texto = []
    buffer = ""
    
    for linha in linhas:
        linha = linha.strip()
        if not linha:
            if buffer:
                novo_texto.append(buffer)
                buffer = ""
            novo_texto.append("") # Mantém parágrafo vazio
            continue
        
        # Se a linha atual começa com letra minúscula, provavelmente é continuação da anterior
        if buffer and len(linha) > 0 and linha[0].islower():
            buffer += " " + linha
        
        # Se a linha anterior terminava com hífen (quebra de palavra)
        elif buffer and buffer.endswith("-"):
            buffer = buffer[:-1] + linha
            
        # Se parece um tópico (começa com bolinha ou traço), quebra
        elif re.match(r'^[-•*]\s+', linha):
            if buffer: novo_texto.append(buffer)
            buffer = linha
            
        # Caso padrão: junta com espaço se a anterior não terminou com pontuação final forte
        elif buffer and not re.search(r'[.!?:;]$', buffer):
             buffer += " " + linha
        else:
            if buffer: novo_texto.append(buffer)
            buffer = linha
            
    if buffer: novo_texto.append(buffer)
    
    return "\n".join(novo_texto)

def corrigir_erros_ocr_comuns(texto: str) -> str:
    if not texto: return ""
    correcoes = {
        r"(?i)\binbem\b": "inibem", r"(?i)\b(3|1)lfar\b": "Belfar", r"(?i)\bBeifar\b": "Belfar",
        r"(?i)\b3elspan\b": "Belspan", r"(?i)\barto\b": "parto", r"(?i)\bausar\b": "causar",
        r"(?i)\bcações\b": "reações", r"(?i)\becomendada\b": "recomendada", r"(?i)\beduzir\b": "reduzir",
        r"(?i)\belacionados\b": "relacionados", r"(?i)\bidministrado\b": "administrado",
        r"(?i)\biparelho\b": "aparelho", r"(?i)\bjangramento\b": "sangramento", r"(?i)\bjerivados\b": "derivados",
        r"(?i)\bjode\b": "pode", r"(?i)\blentro\b": "dentro", r"(?i)\bloses\b": "doses",
        r"(?i)\bmecicamentos\b": "medicamentos", r"(?i)\bnais\b": "mais", r"(?i)\bnedicamentos\b": "medicamentos",
        r"(?i)\bnterações\b": "interações", r"(?i)\bompensarem\b": "compensarem", r"(?i)\bomprimido\b": "comprimido",
        r"(?i)\bontém\b": "contém", r"(?i)\bratamento\b": "tratamento", r"(?i)\brave\b": "grave",
        r"(?i)\bravidez\b": "gravidez", r"(?i)\breas\b": "áreas", r"(?i)\brincipalmente\b": "principalmente",
        r"(?i)\broblemas\b": "problemas", r"(?i)\brávidas\b": "grávidas", r"(?i)\bslaucoma\b": "glaucoma",
        r"(?i)\bNAO\b": "NÃO", r"(?i)\bCOMPOSIÇAO\b": "COMPOSIÇÃO", r"(?i)\bJevido\b": "Devido",
        r"(?i)\bjue\b": "que", r"(?i)\bjacientes\b": "pacientes", r"(?i)\bocê\b": "você",
        r"(?i)\basos\b": "casos", r"(?i)\b1so\b": "uso", r"(?i)\bjaracetamol\b": "paracetamol",
        r"(?i)\beguindo\b": "seguindo", r"(?i)\bituações\b": "situações", r"(?i)\bressão\b": "pressão",
        r"(?i)\bjortadores\b": "portadores", r"(?i)\bjossuem\b": "possuem", r"(?i)\blérgica\b": "alérgica",
        r"(?i)\bmediatamente\b": "imediatamente", r"(?i)\bAcido acetilsalicílico\b": "Ácido acetilsalicílico",
        r"(?i)\bse ALGUM usar\b": "se ALGUÉM usar", r"(?i)\blipirona\b": "dipirona",
        r"\s+mm\b": "", r"\s+mma\b": "", r"\|": ""
    }
    for padrao, correcao in correcoes.items():
        texto = re.sub(padrao, correcao, texto, flags=re.MULTILINE)
    return texto

def executar_ocr(arquivo_bytes):
    """Executa OCR em todas as páginas do PDF."""
    texto_ocr = ""
    with fitz.open(stream=io.BytesIO(arquivo_bytes), filetype="pdf") as doc:
        for page in doc:
            pix = page.get_pixmap(dpi=300)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            try:
                texto_ocr += pytesseract.image_to_string(img, lang='por', config='--psm 3') + "\n"
            except:
                pass
    return texto_ocr

# ----------------- EXTRAÇÃO INTELIGENTE (HÍBRIDA) -----------------

def extrair_texto_inteligente(arquivo, tipo_arquivo):
    if arquivo is None:
        return "", f"Arquivo {tipo_arquivo} não enviado."

    try:
        arquivo.seek(0)
        arquivo_bytes = arquivo.read()
        texto = ""
        usou_ocr = False

        if tipo_arquivo == 'pdf':
            # 1. Tenta extração nativa
            with fitz.open(stream=io.BytesIO(arquivo_bytes), filetype="pdf") as doc:
                for page in doc:
                    texto += page.get_text("text", sort=True) + "\n"
            
            # 2. Verifica qualidade
            texto_teste = re.sub(r'\s+', '', texto)
            if len(texto_teste) < 100:
                usou_ocr = True
                texto = executar_ocr(arquivo_bytes)

        elif tipo_arquivo == 'docx':
            doc = docx.Document(io.BytesIO(arquivo_bytes))
            texto = "\n".join([p.text for p in doc.paragraphs])

        # Limpeza e Formatação
        if texto:
            # 1. Remove caracteres invisiveis
            invis = ['\u00AD', '\u200B', '\u200C', '\u200D', '\uFEFF']
            for c in invis: texto = texto.replace(c, '')
            texto = texto.replace('\r\n', '\n').replace('\r', '\n')
            
            # 2. Limpa Lixo da Gráfica (Antes de fluir o texto)
            texto = limpar_lixo_grafica_belfar(texto)
            
            # 3. OCR Corrections
            texto = corrigir_erros_ocr_comuns(texto)
            
            # 4. Conserta Títulos Quebrados (CRÍTICO para o OCR)
            texto = consertar_titulos_quebrados(texto)
            
            # 5. Remove hifenização de quebra de linha se não usou OCR
            # (Se usou OCR, a função limpar_texto_grafica trataria, mas aqui garantimos)
            texto = re.sub(r'(\w+)-\n(\w+)', r'\1\2', texto, flags=re.IGNORECASE)
            
            # 6. Fluir texto (Deixar Bonitinho e Justificado)
            texto = fluir_texto(texto)
            
            texto = texto.strip()
            
        return texto, None
    except Exception as e:
        return "", f"Erro ao ler o arquivo: {e}"


def truncar_apos_anvisa(texto):
    if not isinstance(texto, str): return texto
    rx = r"(aprovad[ao]\s+pela\s+anvisa\s+em|data\s+de\s+aprovação\s+na\s+anvisa:)\s*([\d]{1,2}/[\d]{1,2}/[\d]{2,4})"
    m = re.search(rx, texto, re.IGNORECASE)
    if m:
        pos = texto.find('\n', m.end())
        return texto[:pos] if pos != -1 else texto
    return texto


# ----------------- CONFIGURAÇÃO DE SEÇÕES -----------------
def obter_secoes_por_tipo(tipo_bula):
    # Fixo em Paciente
    secoes = [
        "APRESENTAÇÕES", "COMPOSIÇÃO", "PARA QUE ESTE MEDICAMENTO É INDICADO",
        "COMO ESTE MEDICAMENTO FUNCIONA?", "QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?",
        "O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?",
        "ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?",
        "COMO DEVO USAR ESTE MEDICAMENTO?",
        "O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?",
        "QUAIS OS MALES QUE ESTE MEDICAMENTO PODE CAUSAR?",
        "O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?",
        "DIZERES LEGAIS"
    ]
    return secoes


def obter_aliases_secao():
    return {
        "INDICAÇÕES": "PARA QUE ESTE MEDICAMENTO É INDICADO",
        "CONTRAINDICAÇÕES": "QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?",
        "POSOLOGIA E MODO DE USAR": "COMO DEVO USAR ESTE MEDICAMENTO?",
        "REAÇÕES ADVERSAS": "QUAIS OS MALES QUE ESTE MEDICAMENTO PODE CAUSAR?",
        "SUPERDOSE": "O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?",
        "CUIDADOS DE ARMAZENAMENTO DO MEDICAMENTO": "ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?"
    }


def obter_secoes_ignorar_comparacao():
    return ["APRESENTAÇÕES", "COMPOSIÇÃO", "DIZERES LEGAIS"]


def obter_secoes_ignorar_ortografia():
    return ["COMPOSIÇÃO", "DIZERES LEGAIS"]


# ----------------- NORMALIZAÇÃO -----------------
def normalizar_texto(texto):
    texto = '' if texto is None else texto
    texto = ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')
    texto = re.sub(r'[^\w\s]', '', texto)
    texto = ' '.join(texto.split())
    return texto.lower()


def normalizar_titulo_para_comparacao(texto):
    texto = '' if texto is None else texto
    t = normalizar_texto(texto)
    t = re.sub(r'^\s*(\d{1,2})\s*[\.\)\-]?\s*', '', t).strip()
    return t


def _create_anchor_id(secao_nome, prefix):
    norm = normalizar_texto(secao_nome)
    norm_safe = re.sub(r'[^a-z0-9\-]', '-', norm)
    return f"anchor-{prefix}-{norm_safe}"


# ----------------- DETECÇÃO E MAPEAMENTO -----------------
HeadingCandidate = namedtuple("HeadingCandidate", ["index", "raw", "norm", "numeric", "matched_canon", "score"])


def construir_heading_candidates(linhas, secoes_esperadas, aliases):
    titulos_possiveis = {}
    for s in secoes_esperadas: titulos_possiveis[s] = s
    for a, c in aliases.items():
        if c in secoes_esperadas: titulos_possiveis[a] = c
    titulos_norm = {k: normalizar_titulo_para_comparacao(k) for k in titulos_possiveis.keys()}
    candidates = []
    for i, linha in enumerate(linhas):
        raw = (linha or "").strip()
        if not raw: continue
        norm = normalizar_titulo_para_comparacao(raw)
        best_score = 0
        best_canon = None
        mnum = re.match(r'^\s*(\d{1,2})\s*[\.\)\-]?\s*(.*)$', raw)
        numeric = int(mnum.group(1)) if mnum else None

        letters = re.findall(r'[A-Za-zÀ-ÖØ-öø-ÿ]', raw)
        is_upper = len(letters) and sum(1 for ch in letters if ch.isupper()) / len(letters) >= 0.6
        starts_with_cap = raw and (raw[0].isupper() or raw[0].isdigit())

        for titulo_possivel, titulo_canonico in titulos_possiveis.items():
            t_norm = titulos_norm.get(titulo_possivel, "")
            if not t_norm: continue
            score = fuzz.token_set_ratio(t_norm, norm)
            if t_norm in norm: score = max(score, 95)
            if score > best_score:
                best_score = score
                best_canon = titulo_canonico

        is_candidate = False
        if numeric is not None: is_candidate = True
        elif best_score >= 88: is_candidate = True
        elif is_upper and len(raw.split()) <= 10: is_candidate = True
        elif starts_with_cap and len(raw.split()) <= 6 and re.search(r'[A-ZÁÉÍÓÚÂÊÔÃÕÇ]', raw): is_candidate = True

        if is_candidate:
            candidates.append(HeadingCandidate(index=i, raw=raw, norm=norm, numeric=numeric,
                                               matched_canon=best_canon if best_score >= 80 else None,
                                               score=best_score))
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
                if c.index <= last_idx: continue
                if fuzz.token_set_ratio(sec_norm, c.norm) >= 92: found = c; break

        if found:
            mapa.append({'canonico': sec, 'titulo_encontrado': found.raw, 'linha_inicio': found.index,
                         'score': found.score})
            last_idx = found.index
    mapa = sorted(mapa, key=lambda x: x['linha_inicio'])
    return mapa, candidates, linhas


def obter_dados_secao_v2(secao_canonico, mapa_secoes, linhas_texto, tipo_bula):
    entrada = None
    for m in mapa_secoes:
        if m['canonico'] == secao_canonico: entrada = m; break
    if not entrada: return False, None, ""
    linha_inicio = entrada['linha_inicio']
    if secao_canonico.strip().upper() == "DIZERES LEGAIS":
        linha_fim = len(linhas_texto)
    else:
        sorted_map = sorted(mapa_secoes, key=lambda x: x['linha_inicio'])
        prox_idx = None
        for m in sorted_map:
            if m['linha_inicio'] > linha_inicio: prox_idx = m['linha_inicio']; break
        linha_fim = prox_idx if prox_idx is not None else len(linhas_texto)
    conteudo_lines = []
    for i in range(linha_inicio + 1, linha_fim):
        line_norm = normalizar_titulo_para_comparacao(linhas_texto[i])
        if line_norm in {normalizar_titulo_para_comparacao(s) for s in obter_secoes_por_tipo(tipo_bula)}: break
        conteudo_lines.append(linhas_texto[i])
    conteudo_final = "\n".join(conteudo_lines).strip()
    return True, entrada['titulo_encontrado'], conteudo_final


# ----------------- VERIFICAÇÃO DE CONTEÚDO -----------------
def verificar_secoes_e_conteudo(texto_ref, texto_belfar, tipo_bula):
    secoes_esperadas = obter_secoes_por_tipo(tipo_bula)
    ignore_comparison = [s.upper() for s in obter_secoes_ignorar_comparacao()]
    secoes_faltantes, diferencas_conteudo, similaridades_secoes, diferencas_titulos = [], [], [], []
    secoes_analisadas = []

    mapa_ref, _, linhas_ref = mapear_secoes_deterministico(texto_ref, secoes_esperadas)
    mapa_belfar, _, linhas_belfar = mapear_secoes_deterministico(texto_belfar, secoes_esperadas)

    for sec in secoes_esperadas:
        encontrou_ref, titulo_ref, conteudo_ref = obter_dados_secao_v2(sec, mapa_ref, linhas_ref, tipo_bula)
        encontrou_belfar, titulo_belfar, conteudo_belfar = obter_dados_secao_v2(sec, mapa_belfar, linhas_belfar,
                                                                                tipo_bula)

        if not encontrou_ref and not encontrou_belfar:
            secoes_faltantes.append(sec)
            secoes_analisadas.append({
                'secao': sec,
                'conteudo_ref': "Seção não encontrada", 'conteudo_belfar': "Seção não encontrada",
                'titulo_encontrado_ref': None, 'titulo_encontrado_belfar': None,
                'tem_diferenca': True, 'ignorada': False, 'faltante': True
            })
            continue

        if not encontrou_belfar:
            secoes_faltantes.append(sec)
            secoes_analisadas.append({
                'secao': sec,
                'conteudo_ref': conteudo_ref if encontrou_ref else "Seção não encontrada",
                'conteudo_belfar': "Seção não encontrada",
                'titulo_encontrado_ref': titulo_ref, 'titulo_encontrado_belfar': None,
                'tem_diferenca': True, 'ignorada': False, 'faltante': True
            })
            continue

        if sec.upper() in ignore_comparison:
            secoes_analisadas.append({
                'secao': sec,
                'conteudo_ref': conteudo_ref or "", 'conteudo_belfar': conteudo_belfar or "",
                'titulo_encontrado_ref': titulo_ref, 'titulo_encontrado_belfar': titulo_belfar,
                'tem_diferenca': False, 'ignorada': True, 'faltante': False
            })
            continue

        tem_diferenca = False
        if normalizar_texto(conteudo_ref or "") != normalizar_texto(conteudo_belfar or ""):
            tem_diferenca = True
            diferencas_conteudo.append(
                {'secao': sec, 'conteudo_ref': conteudo_ref, 'conteudo_belfar': conteudo_belfar})
            similaridades_secoes.append(0)
        else:
            similaridades_secoes.append(100)

        secoes_analisadas.append({
            'secao': sec,
            'conteudo_ref': conteudo_ref, 'conteudo_belfar': conteudo_belfar,
            'titulo_encontrado_ref': titulo_ref, 'titulo_encontrado_belfar': titulo_belfar,
            'tem_diferenca': tem_diferenca, 'ignorada': False, 'faltante': False
        })
    return secoes_faltantes, diferencas_conteudo, similaridades_secoes, diferencas_titulos, secoes_analisadas


# ----------------- ORTOGRAFIA & DIFF -----------------
def checar_ortografia_inteligente(texto_para_checar, texto_referencia, tipo_bula):
    if not texto_para_checar: return []
    try:
        secoes_ignorar = [s.upper() for s in obter_secoes_ignorar_ortografia()]
        secoes_todas = obter_secoes_por_tipo(tipo_bula)
        texto_filtrado = []
        mapa, _, linhas = mapear_secoes_deterministico(texto_para_checar, secoes_todas)
        for sec in secoes_todas:
            if sec.upper() in secoes_ignorar: continue
            enc, _, cont = obter_dados_secao_v2(sec, mapa, linhas, tipo_bula)
            if enc and cont: texto_filtrado.append(cont)
        texto_final = '\n'.join(texto_filtrado)
        if not texto_final: return []
        spell = SpellChecker(language='pt')
        palavras_ignorar = {"alair", "belfar", "peticionamento", "urotrobel", "nebacetin", "neomicina",
                            "bacitracina"}
        vocab_ref_raw = set(re.findall(r'\b[a-zA-ZÀ-ÖØ-öø-ÿ0-9\-]+\b', (texto_referencia or "").lower()))
        spell.word_frequency.load_words(vocab_ref_raw.union(palavras_ignorar))
        entidades = set()
        if nlp:
            doc = nlp(texto_final)
            entidades = {ent.text.lower() for ent in doc.ents}
        palavras = re.findall(r'\b[a-zA-ZÀ-ÖØ-öø-ÿ]+\b', texto_final)
        palavras = [p for p in palavras if len(p) > 2]
        possiveis_erros = set(spell.unknown([p.lower() for p in palavras]))
        erros_filtrados = []
        vocab_norm = set(normalizar_texto(w) for w in vocab_ref_raw)
        for e in possiveis_erros:
            e_raw = e.lower()
            e_norm = normalizar_texto(e_raw)
            if e_raw in vocab_ref_raw or e_norm in vocab_norm: continue
            if e_raw in entidades or e_raw in palavras_ignorar: continue
            erros_filtrados.append(e_raw)
        return sorted(set(erros_filtrados))[:60]
    except:
        return []


def marcar_diferencas_palavra_por_palavra(texto_ref, texto_belfar, eh_referencia):
    def tokenizar(txt): return re.findall(r'\n|[A-Za-zÀ-ÖØ-öø-ÿ0-9_•]+|[^\w\s]', txt or "", re.UNICODE)

    def norm(tok):
        if tok == '\n': return ' '
        if re.match(r'[A-Za-zÀ-ÖØ-öø-ÿ0-9_•]+$', tok): return normalizar_texto(tok)
        return tok

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
        if tok == '\n':
            marcado.append('<br>'); continue
        if idx in indices and tok.strip() != '':
            marcado.append(f"<mark class='diff'>{tok}</mark>")
        else:
            marcado.append(tok)
    resultado = ""
    for i, tok in enumerate(marcado):
        if i == 0:
            resultado += tok; continue
        raw_tok = re.sub(r'^<mark[^>]*>|</mark>$', '', tok)
        if tok == '<br>' or marcado[i - 1] == '<br>':
            resultado += tok
        elif re.match(r'^[^\w\s]$', raw_tok):
            resultado += tok
        else:
            resultado += " " + tok
    resultado = re.sub(r'\s+([.,;:!?)])', r'\1', resultado)
    resultado = re.sub(r'(\()\s+', r'\1', resultado)
    resultado = re.sub(r"(</mark>)\s+(<mark[^>]*>)", " ", resultado)
    return resultado


# ----------------- CONSTRUÇÃO HTML -----------------
def construir_html_secoes(secoes_analisadas, erros_ortograficos, tipo_bula, eh_referencia=False):
    html_map = {}
    prefixos_paciente = {
        "PARA QUE ESTE MEDICAMENTO É INDICADO": "1.", "COMO ESTE MEDICAMENTO FUNCIONA?": "2.",
        "QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?": "3.", "O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?": "4.",
        "ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?": "5.",
        "COMO DEVO USAR ESTE MEDICAMENTO?": "6.",
        "O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?": "7.",
        "QUAIS OS MALES QUE ESTE MEDICAMENTO PODE CAUSAR?": "8.",
        "O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?": "9."
    }
    # Prefixo profissional apenas para compatibilidade, não será usado
    prefixos_profissional = {} 
    
    prefixos_map = prefixos_paciente 
    mapa_erros = {}
    if erros_ortograficos and not eh_referencia:
        for erro in erros_ortograficos:
            pattern = r'(?<![<>a-zA-Z])(?<!mark>)(?<!;>)\b(' + re.escape(erro) + r')\b(?![<>])'
            mapa_erros[pattern] = r"<mark class='ort'>\1</mark>"
    regex_anvisa = r"((?:aprovad[ao]\s+pela\s+anvisa\s+em|data\s+de\s+aprovação\s+na\s+anvisa:)\s*[\d]{1,2}/[\d]{1,2}/[\d]{2,4})"
    anvisa_pattern = re.compile(regex_anvisa, re.IGNORECASE)
    for diff in secoes_analisadas:
        secao_canonico = diff['secao']
        prefixo = prefixos_map.get(secao_canonico, "")
        if eh_referencia:
            tit = f"{prefixo} {secao_canonico}".strip()
            title_html = f"<div class='section-title ref-title'>{tit}</div>"
            conteudo = diff['conteudo_ref'] or ""
        else:
            tit_enc = diff.get('titulo_encontrado_belfar') or diff.get('titulo_encontrado_ref') or secao_canonico
            # Tenta limpar titulo quebrado no display tb
            tit_enc = tit_enc.replace('\n', ' ') 
            tit = f"{prefixo} {tit_enc}".strip() if prefixo and not tit_enc.strip().startswith(
                prefixo) else tit_enc
            title_html = f"<div class='section-title bel-title'>{tit}</div>"
            conteudo = diff['conteudo_belfar'] or ""
        if diff.get('ignorada', False):
            conteudo_html = (conteudo or "").replace('\n', '<br>')
        else:
            conteudo_html = marcar_diferencas_palavra_por_palavra(diff.get('conteudo_ref') or "",
                                                                  diff.get('conteudo_belfar') or "", eh_referencia)
        if not eh_referencia and not diff.get('ignorada', False):
            for pat, repl in mapa_erros.items():
                try:
                    conteudo_html = re.sub(pat, repl, conteudo_html, flags=re.IGNORECASE)
                except:
                    pass
        conteudo_html = anvisa_pattern.sub(r"<mark class='anvisa'>\1</mark>", conteudo_html)
        anchor_id = _create_anchor_id(secao_canonico, "ref" if eh_referencia else "bel")
        html_map[secao_canonico] = f"<div id='{anchor_id}' style='scroll-margin-top: 20px;'>{title_html}<div style='margin-top:6px;'>{conteudo_html}</div></div>"
    return html_map


def gerar_relatorio_final(texto_ref, texto_belfar, nome_ref, nome_belfar, tipo_bula):
    st.header("Relatório de Auditoria Inteligente")
    rx_anvisa = r"(aprovad[ao]\s+pela\s+anvisa\s+em|data\s+de\s+aprovação\s+na\s+anvisa:)\s*([\d]{1,2}/[\d]{1,2}/[\d]{2,4})"
    m_ref = re.search(rx_anvisa, texto_ref or "", re.IGNORECASE)
    m_bel = re.search(rx_anvisa, texto_belfar or "", re.IGNORECASE)
    data_ref = m_ref.group(2).strip() if m_ref else "Não encontrada"
    data_bel = m_bel.group(2).strip() if m_bel else "Não encontrada"

    secoes_faltantes, diferencas_conteudo, similaridades, diferencas_titulos, secoes_analisadas = verificar_secoes_e_conteudo(
        texto_ref, texto_belfar, tipo_bula)
    erros = checar_ortografia_inteligente(texto_belfar, texto_ref, tipo_bula)
    score = sum(similaridades) / len(similaridades) if similaridades else 100.0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Conformidade", f"{score:.0f}%")
    c2.metric("Erros Ortográficos", len(erros))
    c3.metric("Data ANVISA (Ref)", data_ref)
    c4.metric("Data ANVISA (Bel)", data_bel)

    st.divider()
    st.subheader("Seções (clique para expandir)")

    html_ref = construir_html_secoes(secoes_analisadas, [], tipo_bula, True)
    html_bel = construir_html_secoes(secoes_analisadas, erros, tipo_bula, False)

    # Prefixo para display
    prefixos_paciente = {
        "PARA QUE ESTE MEDICAMENTO É INDICADO": "1.", "COMO ESTE MEDICAMENTO FUNCIONA?": "2.",
        "QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?": "3.", "O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?": "4.",
        "ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?": "5.",
        "COMO DEVO USAR ESTE MEDICAMENTO?": "6.",
        "O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?": "7.",
        "QUAIS OS MALES QUE ESTE MEDICAMENTO PODE CAUSAR?": "8.",
        "O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?": "9."
    }

    for diff in secoes_analisadas:
        sec = diff['secao']
        pref = prefixos_paciente.get(sec, "")
        tit = f"{pref} {sec}" if pref else sec
        status = "✅ Idêntico"
        if diff.get('faltante'):
            status = "🚨 FALTANTE"
        elif diff.get('ignorada'):
            status = "⚠️ Ignorada"
        elif diff.get('tem_diferenca'):
            status = "❌ Divergente"

        with st.expander(f"{tit} — {status}", expanded=(diff.get('tem_diferenca') or diff.get('faltante'))):
            c1, c2 = st.columns([1, 1], gap="large")
            with c1:
                st.markdown(f"**Arte Vigente: {nome_ref}**", unsafe_allow_html=True)
                st.markdown(f"<div class='bula-box'>{html_ref.get(sec, '<i>N/A</i>')}</div>",
                            unsafe_allow_html=True)
            with c2:
                st.markdown(f"**PDF da Gráfica: {nome_belfar}**", unsafe_allow_html=True)
                st.markdown(f"<div class='bula-box'>{html_bel.get(sec, '<i>N/A</i>')}</div>",
                            unsafe_allow_html=True)

    st.divider()
    st.subheader("🎨 Visualização Completa")
    full_order = [s['secao'] for s in secoes_analisadas]
    h_r = "".join([html_ref.get(s, "") for s in full_order])
    h_b = "".join([html_bel.get(s, "") for s in full_order])

    cr, cb = st.columns(2, gap="large")
    with cr: st.markdown(f"<div class='bula-box-full'>{h_r}</div>", unsafe_allow_html=True)
    with cb: st.markdown(f"<div class='bula-box-full'>{h_b}</div>", unsafe_allow_html=True)


# ----------------- VALIDAÇÃO DE TIPO (CORRIGIDA) -----------------
def detectar_tipo_arquivo_por_score(texto):
    if not texto: return "Indeterminado"
    titulos_paciente = [
        "como este medicamento funciona",
        "o que devo saber antes de usar",
        "onde como e por quanto tempo posso guardar",
        "o que devo fazer quando eu me esquecer",
        "quais os males que este medicamento pode causar",
        "o que fazer se alguem usar uma quantidade maior"
    ]
    titulos_profissional = [
        "resultados de eficacia",
        "caracteristicas farmacologicas",
        "interacoes medicamentosas",
        "posologia e modo de usar",
        "reacoes adversas",
        "superdose",
        "propriedades farmacocinetica"
    ]
    t_norm = normalizar_texto(texto)
    score_pac = 0
    for t in titulos_paciente:
        if t in t_norm: score_pac += 1
    score_prof = 0
    for t in titulos_profissional:
        if t in t_norm: score_prof += 1
    if score_pac > score_prof:
        return "Paciente"
    elif score_prof > score_pac:
        return "Profissional"
    else:
        return "Indeterminado"


# ----------------- MAIN APP -----------------
st.title("🔬 Inteligência Artificial para Auditoria de Bulas (v57)")
st.markdown(
    "Sistema com validação RÍGIDA: Auditoria exclusiva para **Bula do Paciente**. Bloqueia automaticamente arquivos Profissionais.")

st.divider()

# CONFIGURAÇÃO INTERNA FIXA: Sempre Bula do Paciente
tipo_bula_selecionado = "Paciente"

col1, col2 = st.columns(2)
with col1:
    st.subheader("📄 Arte Vigente (Referência)")
    pdf_ref = st.file_uploader("PDF/DOCX Limpo", type=["pdf", "docx"], key="ref")
with col2:
    st.subheader("📄 PDF da Gráfica (Alvo)")
    pdf_belfar = st.file_uploader("PDF vindo da Gráfica", type=["pdf", "docx"], key="belfar")

if st.button("🔍 Iniciar Auditoria Completa", use_container_width=True, type="primary"):
    if not (pdf_ref and pdf_belfar):
        st.warning("⚠️ Envie ambos os arquivos.")
    else:
        with st.spinner("Analisando arquivos (Extração Híbrida + OCR se necessário)..."):
            # 1. Extração Híbrida Inteligente
            texto_ref, erro_ref = extrair_texto_inteligente(pdf_ref, 'docx' if pdf_ref.name.endswith('.docx') else 'pdf')
            texto_belfar, erro_belfar = extrair_texto_inteligente(pdf_belfar, 'docx' if pdf_belfar.name.endswith('.docx') else 'pdf')

            if erro_ref or erro_belfar:
                st.error(f"Erro de leitura: {erro_ref or erro_belfar}")
            else:
                # 2. Detecção Automática do Tipo
                detectado_ref = detectar_tipo_arquivo_por_score(texto_ref)
                detectado_bel = detectar_tipo_arquivo_por_score(texto_belfar)

                erro_validacao = False

                # Regra de Bloqueio: O sistema SÓ ACEITA Paciente.
                if detectado_ref == "Profissional":
                    st.error(f"🚨 ERRO CRÍTICO (Arte Vigente): O arquivo '{pdf_ref.name}' foi identificado como **Bula Profissional**.")
                    st.error("Este sistema é exclusivo para validação de **Bula do Paciente**.")
                    erro_validacao = True
                
                if detectado_bel == "Profissional":
                    st.error(f"🚨 ERRO CRÍTICO (PDF Gráfica): O arquivo '{pdf_belfar.name}' foi identificado como **Bula Profissional**.")
                    st.error("Este sistema é exclusivo para validação de **Bula do Paciente**.")
                    erro_validacao = True

                if erro_validacao:
                    st.error(
                        "⛔ A comparação foi bloqueada por segurança.")
                else:
                    # 3. Processamento
                    texto_ref = truncar_apos_anvisa(texto_ref)
                    texto_belfar = truncar_apos_anvisa(texto_belfar)
                    gerar_relatorio_final(texto_ref, texto_belfar, pdf_ref.name, pdf_belfar.name,
                                          tipo_bula_selecionado)

st.divider()
st.caption("Sistema de Auditoria v57 | Limpeza de Gráfica Belfar | Texto Justificado")
