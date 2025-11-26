# pages/2_Conferencia_MKT.py
#
# Versão v88 - Limpeza de Lixo Específico e Correção de Anomalias
# - NOVO: Padrões de limpeza para rodapés da Belfar (BUL, PROVA, Email quebrado).
# - CORREÇÃO: Arruma "300" para "30°C" e "Guarde - o" para "Guarde-o".
# - MELHORIA: Validação de Texto Nativo ignora espaços para evitar OCR desnecessário.

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
    match = re.search(regex_anvisa, texto, re.IGNORECASE | re.DOTALL)
    if not match: return texto
    cut_off_position = match.end(1)
    pos_match = re.search(r'^\s*\.', texto[cut_off_position:], re.IGNORECASE)
    if pos_match: cut_off_position += pos_match.end()
    return texto[:cut_off_position]

def _create_anchor_id(secao_nome, prefix):
    norm = normalizar_texto(secao_nome)
    norm_safe = re.sub(r'[^a-z0-9\-]', '-', norm)
    return f"anchor-{prefix}-{norm_safe}"

# ----------------- LIMPEZA E CORREÇÃO (AQUI ESTÁ A MÁGICA) -----------------

def limpar_lixo_grafico(texto):
    """Remove o lixo técnico específico da Belfar e marcas de impressão."""
    padroes_lixo = [
        # --- LIXOS ESPECÍFICOS SOLICITADOS ---
        r'BUL\d+[A-Z0-9]*',                         # BUL22122V03
        r'\(\s*1\s*\)\s*BELFAR',                    # ( 1) BELFAR
        r'\d+\s*PROVA\s*-\s*\d{1,2}\s*/\s*\d{1,2}\s*/\s*\d{4}', # 1 PROVA - 11 / 11 / 2025
        r'31\s*3514\s*-\s*2900',                    # 313514 - 2900
        r'artes[O0o]belfar\.\s*com\.\s*br',         # artesObelfar. com. br
        r'artes\s*@\s*belfar\.com\.br',             # Email correto também
        
        # --- LIXOS GENÉRICOS DE GRÁFICA ---
        r'\b\d{1,3}\s*[,.]\s*\d{0,2}\s*cm\b',       # Medidas cm
        r'\b\d{1,3}\s*[,.]\s*\d{0,2}\s*mm\b',       # Medidas mm
        r'450',                                     # O "450" solto
        r'.*Negrito\.\s*Corpo.*', 
        r'AZOLINA:', r'contato:', 
        r'^\s*VERSO\s*$', r'^\s*FRENTE\s*$', 
        r'.*Frente\s*/\s*Verso.*',
        r'.*Cor:\s*Preta.*', r'.*Papel:.*', r'.*Ap\s*\d+gr.*', 
        r'.*da bula:.*', r'.*AFAZOLINA_BUL.*', 
        r'bula do paciente', r'página \d+\s*de\s*\d+', 
        r'Tipologia', r'Dimensão', r'Formatos?', 
        r'Times New Roman', r'Arial', r'Helvética', 
        r'Cores?:', r'Preto', r'Black', r'Pantone', 
        r'^\s*BELFAR\s*$', r'^\s*PHARMA\s*$',
        r'CNPJ:?', r'SAC:?', r'Farm\. Resp\.?:?', 
        r'Laetus', r'Pharmacode', 
        r'\b\d{6,}\s*-\s*\d{2}/\d{2}\b', 
        r'.*BUL_CLORIDRATO.*', r'.*Impress[ãa]o.*'
    ]
    
    texto_limpo = texto
    for p in padroes_lixo:
        texto_limpo = re.sub(p, ' ', texto_limpo, flags=re.IGNORECASE | re.MULTILINE)
    
    # Remove linhas que sobraram só com pontuação
    texto_limpo = re.sub(r'^\s*[-_.,|:;]\s*$', '', texto_limpo, flags=re.MULTILINE)
    
    return texto_limpo

def corrigir_padroes_bula(texto):
    """
    Corrige erros de leitura (OCR ou Encoding) mostrados nos prints.
    """
    if not texto: return ""
    
    # 1. Correção de Palavras Quebradas/Juntas (O "Amarelinho" da imagem)
    texto = re.sub(r'Guarde\s*-\s*o', 'Guarde-o', texto, flags=re.I)
    texto = re.sub(r'Guardeo', 'Guarde-o', texto, flags=re.I)
    texto = re.sub(r'utilizá\s*-\s*lo', 'utilizá-lo', texto, flags=re.I)
    texto = re.sub(r'Utilizalo', 'utilizá-lo', texto, flags=re.I)
    
    # 2. Correção de Temperatura (15 " C a 300 -> 15°C a 30°C)
    # O padrão '300' aparece muito quando o OCR lê '30°' como '300'
    texto = re.sub(r'(\d+)\s*["”]\s*[Cc]', r'\1°C', texto)  # 15 " C -> 15°C
    texto = re.sub(r'(\d+)\s*Ca\s*(\d+)', r'\1°C a \2', texto) # 15 Ca 30 -> 15°C a 30
    
    # Corrige '300' ou '150' se parecer temperatura (ex: final de frase ou seguido de ponto)
    # Cuidado para não mudar dosagem (mg). Temperatura geralmente é 15-30.
    texto = re.sub(r'\b(15|25|30)\s*00\b', r'\1°C', texto) 
    
    # 3. Pontuação com espaço errado
    texto = re.sub(r'\s+([.,;?!])', r'\1', texto)
    
    return texto

# ----------------- EXTRAÇÃO COM INTELIGÊNCIA -----------------

def forcar_titulos_bula(texto):
    substituicoes = [
        (r"(?:1\.?\s*)?PARA\s*QUE\s*ESTE\s*MEDICAMENTO\s*[\s\S]{0,100}?INDICADO\??", r"\n1. PARA QUE ESTE MEDICAMENTO É INDICADO?\n"),
        (r"(?:2\.?\s*)?COMO\s*ESTE\s*MEDICAMENTO\s*[\s\S]{0,100}?FUNCIONA\??", r"\n2. COMO ESTE MEDICAMENTO FUNCIONA?\n"),
        (r"(?:3\.?\s*)?QUANDO\s*N[ÃA]O\s*DEVO\s*USAR\s*[\s\S]{0,100}?MEDICAMENTO\??", r"\n3. QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?\n"),
        (r"(?:4\.?\s*)?O\s*QUE\s*DEVO\s*SABER[\s\S]{1,100}?USAR[\s\S]{1,100}?MEDICAMENTO\??", r"\n4. O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?\n"),
        (r"(?:5\.?\s*)?ONDE\s*,?\s*COMO\s*E\s*POR\s*QUANTO[\s\S]{1,100}?GUARDAR[\s\S]{1,100}?MEDICAMENTO\??", r"\n5. ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?\n"),
        (r"(?:6\.?\s*)?COMO\s*DEVO\s*USAR\s*ESTE\s*[\s\S]{0,100}?MEDICAMENTO\??", r"\n6. COMO DEVO USAR ESTE MEDICAMENTO?\n"),
        (r"(?:7\.?\s*)?O\s*QUE\s*DEVO\s*FAZER[\s\S]{0,200}?MEDICAMENTO\??", r"\n7. O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?\n"),
        (r"(?:8\.?\s*)?QUAIS\s*OS\s*MALES[\s\S]{0,200}?CAUSAR\??", r"\n8. QUAIS OS MALES QUE ESTE MEDICAMENTO PODE ME CAUSAR?\n"),
        (r"(?:9\.?\s*)?O\s*QUE\s*FAZER\s*SE\s*ALGU[EÉ]M\s*USAR[\s\S]{0,400}?MEDICAMENTO\??", r"\n9. O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?\n"),
    ]
    texto_arrumado = texto
    for padrao, substituto in substituicoes:
        texto_arrumado = re.sub(padrao, substituto, texto_arrumado, flags=re.IGNORECASE | re.DOTALL)
    return texto_arrumado

def executar_ocr(arquivo_bytes):
    """Roda Tesseract."""
    texto_ocr = ""
    with fitz.open(stream=io.BytesIO(arquivo_bytes), filetype="pdf") as doc:
        for page in doc:
            pix = page.get_pixmap(dpi=300)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            try:
                texto_ocr += pytesseract.image_to_string(img, lang='por', config='--psm 3') + "\n"
            except: pass
    return texto_ocr

def verifica_qualidade_texto(texto):
    """
    Verifica se o texto extraído nativamente tem qualidade suficiente.
    Ignora espaços para evitar falso negativo (ex: 'P A R A  Q U E').
    """
    if not texto: return False
    
    # Remove espaços e normaliza para checar a 'alma' do texto
    t_limpo = re.sub(r'\s+', '', unicodedata.normalize('NFD', texto).lower())
    
    # Palavras-chave comprimidas
    keywords = ["paraqueeste", "comodevousar", "dizereslegais", "quandonaodevo", "composicao"]
    
    hits = sum(1 for k in keywords if k in t_limpo)
    
    # Se achou pelo menos 2 seções chaves, consideramos que o texto nativo é válido.
    # Se não achou, provavelmente é lixo ou curvas, então usaremos OCR.
    return hits >= 2

def extrair_texto_hibrido(arquivo, tipo_arquivo, is_marketing_pdf=False):
    if arquivo is None: return "", "Arquivo não enviado."
    try:
        arquivo.seek(0)
        arquivo_bytes = arquivo.read()
        texto_completo = ""
        metodo = "Nativo"

        if tipo_arquivo == 'pdf':
            texto_nativo = ""
            with fitz.open(stream=io.BytesIO(arquivo_bytes), filetype="pdf") as doc:
                for page in doc:
                    if is_marketing_pdf:
                        # Extração por blocos para MKT (tenta manter ordem)
                        blocks = page.get_text("blocks")
                        blocks.sort(key=lambda b: (b[1], b[0]))
                        for b in blocks:
                            if b[6] == 0: texto_nativo += b[4] + "\n"
                    else:
                        texto_nativo += page.get_text() + "\n"
            
            # DECISÃO CRUCIAL: OCR OU NÃO?
            if verifica_qualidade_texto(texto_nativo):
                texto_completo = texto_nativo
                metodo = "Nativo (Validado)"
            else:
                texto_completo = executar_ocr(arquivo_bytes)
                metodo = "OCR (Forçado - Conteúdo insuficiente)"

        elif tipo_arquivo == 'docx':
            doc = docx.Document(io.BytesIO(arquivo_bytes))
            texto_completo = "\n".join([p.text for p in doc.paragraphs])

        if texto_completo:
            invis = ['\u00AD', '\u200B', '\u200C', '\u200D', '\uFEFF']
            for c in invis: texto_completo = texto_completo.replace(c, '')
            texto_completo = texto_completo.replace('\r\n', '\n').replace('\r', '\n').replace('\u00A0', ' ')
            
            # 1. Limpeza Pesada (Lixo de Gráfica)
            texto_completo = limpar_lixo_grafico(texto_completo)
            
            # 2. Correção de Anomalias (Amarelinhos)
            texto_completo = corrigir_padroes_bula(texto_completo)
            
            # 3. Estruturação
            texto_completo = forcar_titulos_bula(texto_completo)
            texto_completo = re.sub(r'(?m)^\s*\d{1,2}\.\s*$', '', texto_completo)
            texto_completo = re.sub(r'(?m)^_+$', '', texto_completo)
            texto_completo = re.sub(r'\n{3,}', '\n\n', texto_completo)
            
            print(f"Arquivo: {getattr(arquivo, 'name', '?')} | Método: {metodo}")
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
        is_title = re.match(r'^\d+\s*[\.\-)]*\s+[A-ZÁÉÍÓÚÂÊÔÃÕÇ]', first) or (first.isupper() and len(first)>4)
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
    mapa_ref, _, linhas_ref = mapear_secoes_deterministico(texto_ref, secoes_esperadas)
    mapa_belfar, _, linhas_belfar = mapear_secoes_deterministico(texto_belfar, secoes_esperadas)
    secoes_analisadas = []
    similaridades_secoes = []

    for sec in secoes_esperadas:
        encontrou_ref, tit_ref, cont_ref = obter_dados_secao_v2(sec, mapa_ref, linhas_ref)
        encontrou_bel, tit_bel, cont_bel = obter_dados_secao_v2(sec, mapa_belfar, linhas_belfar)
        
        tem_diferenca = False
        faltante = False
        
        if not encontrou_ref and not encontrou_bel:
            faltante = True
        elif not encontrou_bel:
            faltante = True
        elif sec not in ["APRESENTAÇÕES", "COMPOSIÇÃO", "DIZERES LEGAIS"]:
            norm_ref = normalizar_texto(re.sub(r'([.,;?!()\[\]])', r' \1 ', cont_ref or ""))
            norm_bel = normalizar_texto(re.sub(r'([.,;?!()\[\]])', r' \1 ', cont_bel or ""))
            if norm_ref != norm_bel:
                tem_diferenca = True
                similaridades_secoes.append(0)
            else:
                similaridades_secoes.append(100)
        
        secoes_analisadas.append({
            'secao': sec, 'conteudo_ref': cont_ref, 'conteudo_belfar': cont_bel,
            'titulo_encontrado_ref': tit_ref, 'titulo_encontrado_belfar': tit_bel,
            'tem_diferenca': tem_diferenca, 'faltante': faltante, 
            'ignorada': sec in ["APRESENTAÇÕES", "COMPOSIÇÃO", "DIZERES LEGAIS"]
        })
    return similaridades_secoes, secoes_analisadas

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
    def tokenizar(txt): return re.findall(r'\n|[A-Za-zÀ-ÖØ-öø-ÿ0-9_•]+|[^\w\s]', txt or "", re.UNICODE)
    def norm(tok): return normalizar_texto(tok) if re.match(r'\w+', tok) else tok.strip()
    ref_tok = tokenizar(texto_ref)
    bel_tok = tokenizar(texto_belfar)
    matcher = difflib.SequenceMatcher(None, [norm(t) for t in ref_tok], [norm(t) for t in bel_tok], autojunk=False)
    indices = set()
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != 'equal': indices.update(range(i1, i2) if eh_referencia else range(j1, j2))
    tokens = ref_tok if eh_referencia else bel_tok
    out = []
    for idx, tok in enumerate(tokens):
        if tok == '\n': out.append('<br>')
        elif idx in indices and tok.strip(): out.append(f"<mark class='diff'>{tok}</mark>")
        else: out.append(tok)
    res = ""
    for i, t in enumerate(out):
        if i>0 and not re.match(r'^[.,;:!?)]', re.sub(r'<[^>]+>', '', t)) and t!='<br>' and out[i-1]!='<br>': res += " "
        res += t
    return res

def construir_html_secoes(secoes_analisadas, erros, eh_referencia):
    html_map = {}
    prefixos = {"PARA QUE ESTE MEDICAMENTO É INDICADO": "1.", "COMO ESTE MEDICAMENTO FUNCIONA?": "2.",
                "QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?": "3.", "O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?": "4.",
                "ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?": "5.", "COMO DEVO USAR ESTE MEDICAMENTO?": "6.",
                "O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?": "7.", "QUAIS OS MALES QUE ESTE MEDICAMENTO PODE CAUSAR?": "8.",
                "O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?": "9."}
    for diff in secoes_analisadas:
        sec = diff['secao']
        prefixo = prefixos.get(sec, "")
        if eh_referencia:
            tit = f"{prefixo} {sec}".strip()
            conteudo = diff['conteudo_ref'] or ""
            title_html = f"<div class='section-title ref-title'>{tit}</div>"
        else:
            tit_enc = diff.get('titulo_encontrado_belfar') or diff.get('titulo_encontrado_ref') or sec
            tit = f"{prefixo} {tit_enc}".strip() if prefixo and not tit_enc.startswith(prefixo) else tit_enc
            conteudo = diff['conteudo_belfar'] or ""
            title_html = f"<div class='section-title bel-title'>{tit}</div>"
        
        if diff.get('ignorada'):
            c_html = (conteudo or "").replace('\n', '<br>')
        else:
            c_html = marcar_diferencas_palavra_por_palavra(diff.get('conteudo_ref'), diff.get('conteudo_belfar'), eh_referencia)
            if not eh_referencia and erros:
                for e in erros:
                    c_html = re.sub(r'(?<![<>a-zA-Z])\b'+re.escape(e)+r'\b(?![<>])', f"<mark class='ort'>{e}</mark>", c_html, flags=re.I)
        
        c_html = re.sub(r'(<br\s*/?>\s*){3,}', '<br><br>', c_html)
        anchor_id = _create_anchor_id(sec, "ref" if eh_referencia else "bel")
        html_map[sec] = f"<div id='{anchor_id}'>{title_html}<div style='margin-top:6px;'>{c_html}</div></div>"
    return html_map

def gerar_relatorio(texto_ref, texto_bel, nome_ref, nome_bel):
    st.header("Relatório de Auditoria")
    simil, analise = verificar_secoes_e_conteudo(texto_ref, texto_bel)
    erros = checar_ortografia_inteligente(texto_bel, texto_ref)
    score = sum(simil)/len(simil) if simil else 100.0
    
    rx = r"(aprovad[ao]\s+pela\s+anvisa\s+em|data\s+de\s+aprovação\s+na\s+anvisa:)\s*([\d]{1,2}/[\d]{1,2}/[\d]{2,4})"
    d_ref = re.search(rx, texto_ref or "", re.I)
    d_bel = re.search(rx, texto_bel or "", re.I)
    
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Conformidade", f"{score:.0f}%")
    c2.metric("Erros Ortográficos", len(erros))
    c3.metric("Data ANVISA (Ref)", d_ref.group(2) if d_ref else "N/A")
    c4.metric("Data ANVISA (Bel)", d_bel.group(2) if d_bel else "N/A")
    
    st.divider()
    html_ref = construir_html_secoes(analise, [], True)
    html_bel = construir_html_secoes(analise, erros, False)
    
    for item in analise:
        sec = item['secao']
        status = "✅ Idêntico"
        if item['faltante']: status = "🚨 FALTANTE"
        elif item['ignorada']: status = "⚠️ Ignorada"
        elif item['tem_diferenca']: status = "❌ Divergente"
        
        with st.expander(f"{sec} — {status}", expanded=(item['tem_diferenca'] or item['faltante'])):
            c1, c2 = st.columns(2, gap="large")
            with c1: 
                st.markdown(f"**{nome_ref}**", unsafe_allow_html=True)
                st.markdown(f"<div class='bula-box'>{html_ref.get(sec, '')}</div>", unsafe_allow_html=True)
            with c2:
                st.markdown(f"**{nome_bel}**", unsafe_allow_html=True)
                st.markdown(f"<div class='bula-box'>{html_bel.get(sec, '')}</div>", unsafe_allow_html=True)

# ----------------- MAIN -----------------
st.title("🔬 Inteligência Artificial para Auditoria de Bulas (v88)")
st.markdown("Sistema Híbrido com Limpeza Avançada de Artefatos e Correção de OCR.")
st.divider()

col1, col2 = st.columns(2)
with col1:
    st.subheader("📄 Arquivo ANVISA")
    pdf_ref = st.file_uploader("PDF/DOCX Referência", type=["pdf", "docx"], key="ref")
with col2:
    st.subheader("📄 PDF da Gráfica")
    pdf_belfar = st.file_uploader("PDF vindo da Gráfica", type=["pdf", "docx"], key="belfar")

if st.button("🔍 Iniciar Auditoria", type="primary", use_container_width=True):
    if not (pdf_ref and pdf_belfar):
        st.warning("Envie os dois arquivos.")
    else:
        with st.spinner("Analisando arquivos (Verificando conteúdo, removendo lixo técnico e corrigindo OCR)..."):
            t_ref, e_ref = extrair_texto_hibrido(pdf_ref, 'docx' if pdf_ref.name.endswith('.docx') else 'pdf', is_marketing_pdf=False)
            t_bel, e_bel = extrair_texto_hibrido(pdf_belfar, 'docx' if pdf_belfar.name.endswith('.docx') else 'pdf', is_marketing_pdf=True)
            
            if e_ref or e_bel:
                st.error(f"Erro: {e_ref or e_bel}")
            else:
                t_ref = reconstruir_paragrafos(truncar_apos_anvisa(t_ref))
                t_bel = reconstruir_paragrafos(truncar_apos_anvisa(t_bel))
                gerar_relatorio(t_ref, t_bel, "Arquivo ANVISA", "PDF da Gráfica")

st.divider()
st.caption("Sistema v88 | Limpeza de Rodapés e Correção de OCR")
