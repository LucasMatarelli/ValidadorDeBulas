# pages/3_Grafica_x_Arte.py
# Versão: v26.9
# Auditoria de Bulas — Comparação: PDF da Gráfica x Arte Vigente
# v26.9: Aplica truncar_apos_anvisa em ambos os textos, corrige mapeamento de seções,
# melhora a formatação pós-OCR do PDF da gráfica (limpeza e reconstrução de layout),
# mantém extração híbrida coluna+OCR (--psm 6), comparação literal e export HTML do relatório.

import re
import difflib
import unicodedata
import io
import html
from typing import Tuple, List, Dict

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

# ----------------- MELHORIA DE LAYOUT PARA PDF DA GRÁFICA -----------------
def melhorar_layout_grafica(texto: str) -> str:
    """
    Heurísticas para melhorar a formatação resultante do OCR:
    - junta linhas cortadas
    - corrige ruídos comuns
    - normaliza títulos e unidades
    """
    if not texto or not isinstance(texto, str):
        return ""

    # Normalizações básicas
    texto = texto.replace('\r\n', '\n').replace('\r', '\n')
    texto = texto.replace('\t', ' ')
    texto = re.sub(r'\u00A0', ' ', texto)

    # Corrige hífen de quebra
    texto = re.sub(r"(\w+)-\n(\w+)", r"\1\2", texto)

    # Junta linhas pequenas ou continuação (heurística mais agressiva aplicada globalmente)
    linhas = [ln.rstrip() for ln in texto.split('\n')]
    novas = []
    i = 0
    while i < len(linhas):
        linha = linhas[i].strip()
        if not linha:
            novas.append('')
            i += 1
            continue

        # Se próxima começa com minúscula, juntar (provável continuação)
        if i + 1 < len(linhas):
            prox = linhas[i+1].strip()
            if prox and prox[0].islower():
                linha = linha + ' ' + prox
                i += 2
                # tentar juntar múltiplas linhas
                while i < len(linhas) and linhas[i].strip() and linhas[i].strip()[0].islower():
                    linha += ' ' + linhas[i].strip()
                    i += 1
                novas.append(linha)
                continue

            # junta quando linha termina com preposição/artigo (fragmento)
            if re.search(r"\b(a|o|as|os|de|da|do|e|ou|com|em|no|na|por|para)$", linha, re.IGNORECASE) and prox:
                linha = linha + ' ' + prox
                i += 2
                novas.append(linha)
                continue

        novas.append(linha)
        i += 1

    texto = '\n'.join(novas)

    # Corrigir padrões OCR comuns
    texto = re.sub(r"\bJ[O0]\s*mg\b", "10 mg", texto, flags=re.IGNORECASE)
    texto = re.sub(r"\bJO\s*mg\b", "10 mg", texto, flags=re.IGNORECASE)
    texto = re.sub(r"\bmm\s+USO\b", "USO", texto, flags=re.IGNORECASE)
    texto = re.sub(r"\bmma\b", "USO", texto, flags=re.IGNORECASE)
    texto = re.sub(r"\bmm\b", "", texto)
    texto = re.sub(r"(?m)^\s*-\s*$", "", texto)  # linhas com só '-'
    texto = re.sub(r"\s+([,;:\.\?\!%°])", r"\1", texto)

    texto = texto.replace('“', '"').replace('”', '"').replace('«', '"').replace('»', '"')

    # Remover caracteres soltos muito comuns (letras isoladas resultantes de OCR)
    texto = re.sub(r'\b[A-Za-z]\b(?=\s|$)', '', texto)
    texto = re.sub(r'\s{2,}', ' ', texto)

    # Uniformizar cabeçalhos comuns
    texto = re.sub(r"\bAPRESENTAÇ(?:OES|ÕES|ÔES)\b", "APRESENTAÇÕES", texto, flags=re.IGNORECASE)
    texto = re.sub(r"\bCOMPOSI[ÇC]AO\b", "COMPOSIÇÃO", texto, flags=re.IGNORECASE)
    texto = re.sub(r"excipientes\s+q\.s\.p\W*", "excipientes q.s.p.", texto, flags=re.IGNORECASE)

    # Capitalizar títulos curtos em maiúsculas (provável cabeçalho)
    linhas = texto.split('\n')
    for idx, l in enumerate(linhas):
        s = l.strip()
        if 1 <= len(s.split()) <= 6 and s.islower():
            linhas[idx] = s.upper()
        else:
            linhas[idx] = l
    texto = '\n'.join(linhas)

    # Remove linhas com ruído bruto
    texto = '\n'.join([ln for ln in texto.split('\n') if ln.strip() and not re.match(r'^[\W_]{2,}$', ln.strip())])

    # Limpeza final
    texto = texto.strip()
    texto = re.sub(r'\n{3,}', '\n\n', texto)

    return texto

# ----------------- CORRETOR DE OCR -----------------
def corrigir_erros_ocr_comuns(texto: str) -> str:
    """
    Substituições finas para erros recorrentes do OCR.
    """
    if not texto:
        return ""
    correcoes = {
        r"(?i)\b(3|1)lfar\b": "Belfar",
        r"(?i)\bBeifar\b": "Belfar",
        r"(?i)\b3elspan\b": "Belspan",
        r"(?i)USO\s+ADULTO": "USO ADULTO",
        r"(?i)USO\s+ORAL": "USO ORAL",
        r"(?i)\bNAO\b": "NÃO",
        r"(?i)\bCOMPOSIÇAO\b": "COMPOSIÇÃO",
        r"(?i)\bMEDICAMENT0\b": "MEDICAMENTO",
        r"(?i)\bJevido\b": "Devido",
        r"(?i)\"ertilidade\b": "Fertilidade",
        r"(?i)\bjperar\b": "operar",
        r"(?i)\'ombinação\b": "combinação",
        r"(?i)\bjue\b": "que",
        r"(?i)\brereditários\b": "hereditários",
        r"(?i)\bralactosemia\b": "galactosemia",
    }
    for padrao, correcao in correcoes.items():
        texto = re.sub(padrao, correcao, texto)
    return texto

# ----------------- EXTRAÇÃO HÍBRIDA DE COLUNAS -----------------
def extrair_pdf_hibrido_colunas(arquivo_bytes: bytes) -> str:
    """
    Extração robusta de PDFs de duas colunas: tenta get_text por coluna, se fraca -> OCR por coluna (--psm 6).
    """
    texto_total_final = ""
    with fitz.open(stream=io.BytesIO(arquivo_bytes), filetype="pdf") as doc:
        st.info(f"Processando {len(doc)} página(s) com lógica de coluna...")
        for i, page in enumerate(doc):
            rect = page.rect
            margin_y = 18
            rect_col_1 = fitz.Rect(0, margin_y, rect.width * 0.5, rect.height - margin_y)
            rect_col_2 = fitz.Rect(rect.width * 0.5, margin_y, rect.width, rect.height - margin_y)

            texto_direto_col_1 = texto_direto_col_2 = ""
            try:
                texto_direto_col_1 = page.get_text("text", clip=rect_col_1, sort=True) or ""
                texto_direto_col_2 = page.get_text("text", clip=rect_col_2, sort=True) or ""
            except Exception:
                texto_direto_col_1 = texto_direto_col_2 = ""

            texto_direto_pagina = (texto_direto_col_1.strip() + "\n" + texto_direto_col_2.strip()).strip()
            if len(texto_direto_pagina) > 200:
                texto_total_final += texto_direto_pagina + "\n"
                continue

            st.warning(f"Extração direta falhou na pág. {i+1}. Ativando OCR por colunas...")
            try:
                ocr_config = r'--psm 6'
                pix_col_1 = page.get_pixmap(clip=rect_col_1, dpi=300)
                img_col_1 = Image.open(io.BytesIO(pix_col_1.tobytes("png")))
                texto_ocr_col_1 = pytesseract.image_to_string(img_col_1, lang='por', config=ocr_config) or ""

                pix_col_2 = page.get_pixmap(clip=rect_col_2, dpi=300)
                img_col_2 = Image.open(io.BytesIO(pix_col_2.tobytes("png")))
                texto_ocr_col_2 = pytesseract.image_to_string(img_col_2, lang='por', config=ocr_config) or ""

                texto_ocr_pagina = (texto_ocr_col_1.strip() + "\n" + texto_ocr_col_2.strip()).strip()
                texto_total_final += texto_ocr_pagina + "\n"
            except Exception as e:
                st.error(f"Erro no OCR da pág. {i+1}: {e}")
                continue

    st.success("Extração de PDF concluída.")
    return texto_total_final

# ----------------- FUNÇÃO DE EXTRAÇÃO PRINCIPAL -----------------
def extrair_texto(arquivo, tipo_arquivo: str) -> Tuple[str, str]:
    """
    Decide qual método usar para extrair texto.
    Retorna (texto, erro)
    """
    if arquivo is None:
        return "", f"Arquivo {tipo_arquivo} não enviado."
    try:
        arquivo.seek(0)
        arquivo_bytes = arquivo.read()
        texto = ""

        if tipo_arquivo == "pdf":
            texto = extrair_pdf_hibrido_colunas(arquivo_bytes)
            texto = melhorar_layout_grafica(texto)
        elif tipo_arquivo == "docx":
            st.info("Extraindo texto de DOCX...")
            doc = docx.Document(io.BytesIO(arquivo_bytes))
            texto = "\n".join([p.text for p in doc.paragraphs])

        # Bloco de limpeza (remover ruídos conhecidos)
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
                r"^\s*\d+/\d+/\d+\s*$",
                r"KH\s*—\s*\d+",
            ]
            linhas = texto.split('\n')
            linhas_filtradas = []
            for linha in linhas:
                linha_limpa = linha.strip()
                ignorar = False
                for pad in padroes_ignorados:
                    if re.search(pad, linha_limpa, re.IGNORECASE):
                        ignorar = True
                        break
                if not ignorar:
                    linhas_filtradas.append(linha)
            texto = "\n".join(linhas_filtradas)

            for ch in ['\u00AD', '\u200B', '\u200C', '\u200D', '\uFEFF']:
                texto = texto.replace(ch, '')
            texto = re.sub(r'(\w+)-\n(\w+)', r'\1\2', texto, flags=re.IGNORECASE)
            texto = re.sub(r'\n{3,}', '\n\n', texto)
            texto = re.sub(r'[ \t]+', ' ', texto)
            texto = texto.strip()

        texto = corrigir_erros_ocr_comuns(texto)
        return texto, None

    except Exception as e:
        st.error(f"Erro fatal em extrair_texto: {e}", icon="🚨")
        return "", f"Erro ao ler o arquivo {tipo_arquivo}: {e}"

# ----------------- TRUNCAR APÓS ANVISA -----------------
def truncar_apos_anvisa(texto: str) -> str:
    if not isinstance(texto, str):
        return texto
    regex_anvisa = r"(aprovad[ao]\s+pela\s+anvisa\s+em|data\s+de\s+aprovação\s+na\s+anvisa:)\s*([\d]{1,2}/[\d]{1,2}/[\d]{2,4})"
    match = re.search(regex_anvisa, texto, re.IGNORECASE)
    if match:
        end_of_line_pos = texto.find('\n', match.end())
        if end_of_line_pos != -1:
            return texto[:end_of_line_pos]
        else:
            return texto
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
    return secoes.get(tipo_bula, [])

def obter_aliases_secao() -> Dict[str, str]:
    return {
        "INDICAÇÕES": "1. PARA QUE ESTE MEDICAMENTO É INDICADO?",
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
    return ["COMPOSIÇÃO", "DIZERES LEGAIS", "APRESENTAÇÕES", "ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?", "CUIDADOS DE ARMAZENAMENTO DO MEDICAMENTO"]

def normalizar_para_comparacao_literal(texto: str) -> str:
    if not isinstance(texto, str):
        return ""
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

# ----------------- MAPEAMENTO DE SEÇÕES -----------------
def is_titulo_secao(linha: str) -> bool:
    linha = linha.strip()
    if len(linha) < 4: return False
    if len(linha.split()) > 20: return False
    if linha.endswith('.') or linha.endswith(':'): return False
    if re.search(r'\>\s*\<', linha): return False
    if len(linha) > 120: return False
    return True

def mapear_secoes(texto_completo: str, secoes_esperadas: List[str]) -> List[Dict]:
    mapa = []
    linhas = texto_completo.split('\n')
    aliases = obter_aliases_secao()
    titulos_possiveis = {}

    for secao in secoes_esperadas:
        titulos_possiveis[secao] = secao
    for alias, canonico in aliases.items():
        if canonico in secoes_esperadas:
            if alias not in titulos_possiveis:
                titulos_possiveis[alias] = canonico

    for idx, linha in enumerate(linhas):
        linha_limpa = linha.strip()
        if not is_titulo_secao(linha_limpa):
            continue

        linha_norm_comparacao = normalizar_titulo_para_comparacao(linha_limpa)
        if not linha_norm_comparacao:
            continue

        best_match_score = 0
        best_match_canonico = None

        for titulo_possivel, titulo_canonico in titulos_possiveis.items():
            score = fuzz.token_set_ratio(normalizar_titulo_para_comparacao(titulo_possivel), linha_norm_comparacao)
            if score > best_match_score:
                best_match_score = score
                best_match_canonico = titulo_canonico

        # threshold ligeiramente relaxado porque aplicamos heurísticas globais
        if best_match_score >= 96:
            if not mapa or mapa[-1]['canonico'] != best_match_canonico:
                mapa.append({
                    'canonico': best_match_canonico,
                    'titulo_encontrado': linha_limpa,
                    'linha_inicio': idx,
                    'score': best_match_score
                })

    mapa.sort(key=lambda x: x['linha_inicio'])
    return mapa

def obter_dados_secao(secao_canonico: str, mapa_secoes: List[Dict], linhas_texto: List[str], tipo_bula: str):
    titulos_lista = obter_secoes_por_tipo(tipo_bula)
    titulos_norm_set = {normalizar_titulo_para_comparacao(t) for t in titulos_lista}

    for i, secao_mapa in enumerate(mapa_secoes):
        if secao_mapa['canonico'] != secao_canonico:
            continue

        titulo_encontrado = secao_mapa['titulo_encontrado']
        linha_inicio = secao_mapa['linha_inicio']
        linha_inicio_conteudo = linha_inicio + 1

        prox_idx = None
        for j in range(linha_inicio_conteudo, len(linhas_texto)):
            linha_atual = linhas_texto[j].strip()
            if not linha_atual:
                continue

            linha_atual_norm = normalizar_titulo_para_comparacao(linha_atual)
            encontrou_titulo = False

            for titulo_oficial_norm in titulos_norm_set:
                if linha_atual_norm.startswith(titulo_oficial_norm) and len(linha_atual_norm) > len(titulo_oficial_norm) + 5:
                    encontrou_titulo = True
                    break
                if fuzz.token_set_ratio(titulo_oficial_norm, linha_atual_norm) >= 96:
                    encontrou_titulo = True
                    break

            if encontrou_titulo:
                prox_idx = j
                break

            if (j + 1) < len(linhas_texto):
                linha_seguinte = linhas_texto[j + 1].strip()
                titulo_duas_linhas = f"{linha_atual} {linha_seguinte}"
                titulo_duas_linhas_norm = normalizar_titulo_para_comparacao(titulo_duas_linhas)

                for titulo_oficial_norm in titulos_norm_set:
                    if fuzz.token_set_ratio(titulo_oficial_norm, titulo_duas_linhas_norm) >= 96:
                        prox_idx = j
                        break
                if prox_idx is not None:
                    break

        linha_fim = prox_idx if prox_idx is not None else len(linhas_texto)
        conteudo = [linhas_texto[idx] for idx in range(linha_inicio_conteudo, linha_fim)]
        conteudo_final = "\n".join(conteudo).strip()
        return True, titulo_encontrado, conteudo_final

    return False, None, ""

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
            melhor_titulo = None
            for m in mapa_belfar:
                score = fuzz.token_set_ratio(normalizar_titulo_para_comparacao(secao), normalizar_titulo_para_comparacao(m['titulo_encontrado']))
                if score > melhor_score:
                    melhor_score = score
                    melhor_titulo = m['titulo_encontrado']

            if melhor_score >= 92:
                diferencas_titulos.append({'secao_esperada': secao, 'titulo_encontrado': melhor_titulo})
                for m in mapa_belfar:
                    if m['titulo_encontrado'] == melhor_titulo:
                        next_section_start = len(linhas_belfar)
                        current_index = mapa_belfar.index(m)
                        if current_index + 1 < len(mapa_belfar):
                            next_section_start = mapa_belfar[current_index + 1]['linha_inicio']
                        conteudo_belfar = "\n".join(linhas_belfar[m['linha_inicio']+1:next_section_start])
                        break
                encontrou_belfar = True
            else:
                secoes_faltantes.append(secao)
                continue

        if encontrou_ref and encontrou_belfar:
            secao_comp = normalizar_titulo_para_comparacao(secao)
            titulo_belfar_comp = normalizar_titulo_para_comparacao(titulo_belfar if titulo_belfar else melhor_titulo)

            if secao_comp != titulo_belfar_comp:
                if not any(d['secao_esperada'] == secao for d in diferencas_titulos):
                    diferencas_titulos.append({'secao_esperada': secao, 'titulo_encontrado': titulo_belfar if titulo_belfar else melhor_titulo})

            secao_canon_norm = normalizar_titulo_para_comparacao(secao)
            ignorar_comparacao_norm = [normalizar_titulo_para_comparacao(s) for s in obter_secoes_ignorar_comparacao()]

            if secao_canon_norm in ignorar_comparacao_norm:
                similaridades_secoes.append(100)
                continue

            # comparação literal
            if normalizar_para_comparacao_literal(conteudo_ref) != normalizar_para_comparacao_literal(conteudo_belfar):
                titulo_real_encontrado = titulo_belfar if titulo_belfar else melhor_titulo
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

        texto_final_para_checar = '\n'.join(texto_filtrado_para_checar)
        if not texto_final_para_checar:
            return []

        spell = SpellChecker(language='pt')
        palavras_a_ignorar = {"alair", "belfar", "peticionamento", "urotrobel", "escopolamina", "dipirona", "butilbrometo", "nafazolina", "cloreto"}
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
            resultado += " " + tok

    resultado = re.sub(r'\s+([.,;:!?)])', r'\1', resultado)
    resultado = re.sub(r'(\()\s+', r'\1', resultado)
    resultado = re.sub(r"(</mark>)\s+(<mark[^>]*>)", r"\1 \2", resultado)
    return resultado

# ----------------- MARCAÇÃO POR SEÇÃO COM ÍNDICES -----------------
def marcar_divergencias_html(texto_original: str, secoes_problema: List[Dict], erros_ortograficos: List[str], tipo_bula: str, eh_referencia: bool=False) -> str:
    texto_trabalho = html.escape(texto_original)

    # Substituir quebras por <br> apenas ao final para que possamos fazer buscas por trechos
    # mas para substituições internas trabalhamos com texto sem escape ao buscar conteudos originais:
    texto_sem_escape = texto_original

    if secoes_problema:
        for diff in secoes_problema:
            conteudo_ref = diff['conteudo_ref']
            conteudo_belfar = diff['conteudo_belfar']

            conteudo_a_marcar = conteudo_ref if eh_referencia else conteudo_belfar
            conteudo_marcado = marcar_diferencas_palavra_por_palavra(conteudo_ref, conteudo_belfar, eh_referencia)

            secao_canonico = diff['secao']
            anchor_id = _create_anchor_id(secao_canonico, "ref" if eh_referencia else "bel")

            conteudo_com_ancora = f"<div id='{anchor_id}' style='scroll-margin-top: 20px;'>{conteudo_marcado}</div>"

            # Tentar substituir no texto sem escape; caso não encontre, substituir versão escapada
            if conteudo_a_marcar and conteudo_a_marcar in texto_sem_escape:
                texto_sem_escape = texto_sem_escape.replace(conteudo_a_marcar, conteudo_com_ancora)
            else:
                # fallback: substituir pela versão escapada (menos provável de ocorrer)
                escaped_marcar = html.escape(conteudo_a_marcar)
                texto_trabalho = texto_trabalho.replace(escaped_marcar, conteudo_com_ancora)

    # Aplicar marcação de erros ortográficos (apenas no BELFAR)
    if erros_ortograficos and not eh_referencia:
        for erro in erros_ortograficos:
            pattern = re.compile(r'\b' + re.escape(erro) + r'\b', flags=re.IGNORECASE)
            texto_sem_escape = pattern.sub(lambda m: f"<mark style='background-color: #FFDDC1; padding: 2px;'>{html.escape(m.group(0))}</mark>", texto_sem_escape)

    # Mostrar frase ANVISA em azul (primeira ocorrência)
    regex_anvisa = r"((?:aprovad[ao]\s+pela\s+anvisa\s+em|data\s+de\s+aprovação\s+na\s+anvisa:)\s*[\d]{1,2}/[\d]{1,2}/[\d]{2,4})"
    match = re.search(regex_anvisa, texto_sem_escape, re.IGNORECASE)
    if match:
        frase_anvisa = match.group(1)
        texto_sem_escape = texto_sem_escape.replace(frase_anvisa, f"<mark style='background-color: #cce5ff; padding: 2px; font-weight: 500;'>{html.escape(frase_anvisa)}</mark>", 1)

    # Finalmente escapamos qualquer conteúdo que não tenha sido substituído e convertemos quebras em <br>
    # Se já fizemos substituições no texto_sem_escape (com HTML), vamos garantir que o restante esteja escapado
    # Para simplificar, se encontramos tags '<div' no texto_sem_escape assumimos que ele contém HTML de marcação.
    if '<div' in texto_sem_escape or '<mark' in texto_sem_escape:
        # substituir quebras restantes por <br>
        texto_final = texto_sem_escape.replace('\n', '<br>')
    else:
        texto_final = html.escape(texto_sem_escape).replace('\n', '<br>')

    return texto_final

# ----------------- RELATÓRIO E EXPORTAÇÃO -----------------
def gerar_relatorio_final(texto_ref: str, texto_belfar: str, nome_ref: str, nome_belfar: str, tipo_bula: str):
    # Extrair datas ANVISA
    regex_anvisa = r"(aprovad[ao]\s+pela\s+anvisa\s+em|data\s+de\s+aprovação\s+na\s+anvisa:)\s*([\d]{1,2}/[\d]{1,2}/[\d]{2,4})"
    match_ref = re.search(regex_anvisa, texto_ref.lower())
    match_belfar = re.search(regex_anvisa, texto_belfar.lower())

    data_ref = match_ref.group(2).strip() if match_ref else "Não encontrada"
    data_belfar = match_belfar.group(2).strip() if match_belfar else "Não encontrada"

    secoes_faltantes, diferencas_conteudo, similaridades, diferencas_titulos = verificar_secoes_e_conteudo(texto_ref, texto_belfar, tipo_bula)
    erros_ortograficos = checar_ortografia_inteligente(texto_belfar, texto_ref, tipo_bula)

    score_similaridade_conteudo = sum(similaridades) / len(similaridades) if similaridades else 100.0

    # Dashboard
    st.header("Relatório de Auditoria Inteligente")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Conformidade de Conteúdo", f"{score_similaridade_conteudo:.0f}%")
    col2.metric("Erros Ortográficos", len(erros_ortograficos))
    col3.metric("Data ANVISA (BELFAR)", data_belfar)
    col4.metric("Seções Faltantes", f"{len(secoes_faltantes)}")

    st.divider()
    st.subheader("Detalhes dos Problemas Encontrados")
    st.info(f"ℹ️ **Datas de Aprovação ANVISA:**\n - Referência: {data_ref}\n - BELFAR: {data_belfar}")

    if secoes_faltantes:
        st.error(f"🚨 **Seções faltantes na bula BELFAR ({len(secoes_faltantes)})**:\n" + "\n".join([f" - {s}" for s in secoes_faltantes]))
    else:
        st.success("✅ Todas as seções obrigatórias estão presentes")

    # Relatório por seção (expanders)
    mapa_diferencas = {diff['secao']: diff for diff in diferencas_conteudo}
    secoes_esperadas = obter_secoes_por_tipo(tipo_bula)

    for secao in secoes_esperadas:
        secao_canon_norm = normalizar_titulo_para_comparacao(secao)
        ignorar_comparacao_norm = [normalizar_titulo_para_comparacao(s) for s in obter_secoes_ignorar_comparacao()]

        if secao_canon_norm in ignorar_comparacao_norm:
            with st.expander(f"📄 {secao} - ℹ️ (Seção não comparada)"):
                st.info("Esta seção é ignorada na comparação de conteúdo por padrão.")
            continue

        if secao in mapa_diferencas:
            diff = mapa_diferencas[secao]
            titulo_display = diff.get('titulo_encontrado') or secao
            with st.expander(f"📄 {titulo_display} - ❌ CONTEÚDO DIVERGENTE"):
                secao_canonico = diff['secao']
                anchor_id_ref = _create_anchor_id(secao_canonico, "ref")
                anchor_id_bel = _create_anchor_id(secao_canonico, "bel")

                expander_html_ref = marcar_diferencas_palavra_por_palavra(diff['conteudo_ref'], diff['conteudo_belfar'], eh_referencia=True).replace('\n', '<br>')
                expander_html_belfar = marcar_diferencas_palavra_por_palavra(diff['conteudo_ref'], diff['conteudo_belfar'], eh_referencia=False).replace('\n', '<br>')

                clickable_style = "height: 300px; overflow-y:auto; border: 1px solid #ddd; padding: 8px;"

                c1, c2 = st.columns(2)
                with c1:
                    st.markdown("**Referência:**")
                    st.markdown(f"<div style='{clickable_style}'>{expander_html_ref}</div>", unsafe_allow_html=True)
                with c2:
                    st.markdown("**BELFAR:**")
                    st.markdown(f"<div style='{clickable_style}'>{expander_html_belfar}</div>", unsafe_allow_html=True)
        else:
            with st.expander(f"📄 {secao} - ✅ CONTEÚDO IDÊNTICO"):
                st.success("O conteúdo desta seção é idêntico em ambos os documentos.")

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

    html_ref_marcado = marcar_divergencias_html(texto_ref, diferencas_conteudo, [], tipo_bula, eh_referencia=True)
    html_belfar_marcado = marcar_divergencias_html(texto_belfar, diferencas_conteudo, erros_ortograficos, tipo_bula, eh_referencia=False)

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

    # Gerar HTML completo para download
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
        html_ref=html_ref_marcado,
        html_belfar=html_belfar_marcado
    )

    b = relatório_html.encode('utf-8')
    st.download_button("⬇️ Baixar relatório (HTML)", data=b, file_name="relatorio_auditoria_grafica_x_arte.html", mime="text/html", use_container_width=True)

def gerar_relatorio_html_para_download(titulo: str, nome_ref: str, nome_belfar: str, data_ref: str, data_belfar: str, score: float, erros_ortograficos: List[str], secoes_faltantes: List[str], diferencas_conteudo: List[Dict], html_ref: str, html_belfar: str) -> str:
    """
    Gera um HTML standalone contendo os textos marcados e um sumário, para download.
    """
    resumo_erros = ", ".join(erros_ortograficos) if erros_ortograficos else "Nenhum"
    faltantes_html = "<br>".join([f"- {html.escape(s)}" for s in secoes_faltantes]) if secoes_faltantes else "Nenhuma"
    diferencas_lista_html = ""
    if diferencas_conteudo:
        for d in diferencas_conteudo:
            titulo = html.escape(d.get('secao', 'Secão'))
            diferencas_lista_html += f"<li><strong>{titulo}</strong></li>"
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
.metrics{{display:flex;gap:12px;margin-top:12px}}
.metric{{background:#fff;padding:10px;border-radius:6px;box-shadow:0 1px 3px rgba(0,0,0,0.08)}}
.container{{display:flex;gap:20px}}
.column{{flex:1;background:#fff;padding:16px;border-radius:6px;box-shadow:0 1px 8px rgba(0,0,0,0.06);max-height:800px;overflow:auto}}
.legend{{margin:10px 0}}
mark.amarelo{{background:#ffff99;padding:2px}} 
mark.rosa{{background:#FFDDC1;padding:2px}}
mark.azul{{background:#cce5ff;padding:2px}}
pre{{white-space:pre-wrap;word-wrap:break-word;font-family:inherit;font-size:14px}}
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
Gerado pelo sistema de Auditoria de Bulas — v26.9
</footer>
</body>
</html>
"""
    return html_page

# ----------------- INTERFACE PRINCIPAL -----------------
st.title("🔬 Auditoria de Bulas — Gráfica x Arte (v26.9)")
st.markdown("Sistema avançado de comparação literal e validação de bulas farmacêuticas — aprimorado para PDFs de gráfica")
st.divider()

st.header("📋 Configuração da Auditoria")
tipo_bula_selecionado = st.radio("Tipo de Bula:", ("Paciente", "Profissional"), horizontal=True)

col1, col2 = st.columns(2)
with col1:
    st.subheader("📄 Arte Vigente (Referência)")
    pdf_ref = st.file_uploader("Envie o PDF ou DOCX de referência", type=["pdf", "docx"], key="ref")
with col2:
    st.subheader("📄 PDF da Gráfica (com colunas)")
    pdf_belfar = st.file_uploader("Envie o PDF BELFAR", type="pdf", key="belfar")

if st.button("🔍 Iniciar Auditoria Completa", use_container_width=True, type="primary"):
    if pdf_ref and pdf_belfar:
        with st.spinner("🔄 Processando e analisando as bulas... (v26.9 - Híbrido de Colunas)"):
            tipo_arquivo_ref = 'docx' if pdf_ref.name.lower().endswith('.docx') else 'pdf'

            texto_ref, erro_ref = extrair_texto(pdf_ref, tipo_arquivo_ref)
            texto_belfar, erro_belfar = extrair_texto(pdf_belfar, 'pdf')

            # truncar após ANVISA em ambos
            if not erro_ref:
                texto_ref = truncar_apos_anvisa(texto_ref)
            if not erro_belfar:
                texto_belfar = truncar_apos_anvisa(texto_belfar)

            if erro_ref or erro_belfar:
                st.error(f"Erro ao processar arquivos: {erro_ref or erro_belfar}")
            else:
                gerar_relatorio_final(texto_ref, texto_belfar, "Arte Vigente (Referência)", "PDF da Gráfica", tipo_bula_selecionado)
    else:
        st.warning("⚠️ Por favor, envie ambos os arquivos (Referência e BELFAR) para iniciar a auditoria.")

st.divider()
st.caption("Sistema de Auditoria de Bulas v26.9 | Híbrido de Coluna + OCR psm 6 + Corretor + Melhoria de Layout da Gráfica")
