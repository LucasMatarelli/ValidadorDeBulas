# pages/3_Grafica_x_Arte.py
# Versão: v26.8
# Auditoria de Bulas — Comparação: PDF da Gráfica x Arte Vigente
# v26.8: Aplica truncar_apos_anvisa em ambos os textos, corrige mapeamento de seções 2,4,8,9,
# melhora a formatação pós-OCR do PDF da gráfica (limpeza e reconstrução de layout),
# mantém extração híbrida coluna+OCR (--psm 6) e comparação literal.

# --- IMPORTS ---
import re
import difflib
import unicodedata
import io
from typing import Tuple, List, Dict

import streamlit as st
import fitz  # PyMuPDF
import docx
import spacy
from thefuzz import fuzz
from spellchecker import SpellChecker
import pytesseract
from PIL import Image

# --- CONFIGURAÇÃO DA PÁGINA STREAMLIT ---
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

# ----------------- [NOVO] MELHORIA DE LAYOUT PARA PDF DA GRÁFICA -----------------
def melhorar_layout_grafica(texto: str) -> str:
    """
    Aplica uma série de heurísticas para melhorar a formatação resultante
    do OCR de PDFs da gráfica (corrige quebras, junta palavras separadas,
    remove ruídos e normaliza unidades).
    """
    if not texto or not isinstance(texto, str):
        return ""

    # 1) Normalizações básicas
    texto = texto.replace('\r\n', '\n').replace('\r', '\n')
    texto = texto.replace('\t', ' ')

    # 2) Corrige quebras de palavras com hífen no final da linha
    texto = re.sub(r"(\w+)-\n(\w+)", r"\1\2", texto)

    # 3) Junta linhas que foram cortadas indevidamente (heurística):
    # Se a linha termina com palavra curta ou letra e a próxima começa em minúscula, junta.
    linhas = texto.split('\n')
    novas_linhas = []
    i = 0
    while i < len(linhas):
        linha = linhas[i].strip()
        if not linha:
            novas_linhas.append('')
            i += 1
            continue

        # Lookahead para juntar linhas curtas/partidas
        if i + 1 < len(linhas):
            prox = linhas[i+1].strip()
            # Junta quando a próxima começa com minúscula (provável continuação)
            if prox and prox[0].islower():
                linha = linha + ' ' + prox
                i += 2
                # Tentativa de múltiplas junções
                while i < len(linhas) and linhas[i].strip() and linhas[i].strip()[0].islower():
                    linha += ' ' + linhas[i].strip()
                    i += 1
                novas_linhas.append(linha)
                continue

            # Junta quando a linha atual termina com pequena palavra isolada que parece fragmento
            if re.search(r"\b(a|o|de|da|do|e|ou|com|em|no|na|por|para)$", linha, re.IGNORECASE) and prox:
                linha = linha + ' ' + prox
                i += 2
                novas_linhas.append(linha)
                continue

        novas_linhas.append(linha)
        i += 1

    texto = '\n'.join(novas_linhas)

    # 4) Corrigir padrões comuns de OCR observados (exemplos):
    # JO mg -> 10 mg, mm USO -> USO, mma -> USO, mm -> (remove ruído)
    texto = re.sub(r"\bJO\s*mg\b", "10 mg", texto)
    texto = re.sub(r"\bJ0\s*mg\b", "10 mg", texto)
    texto = re.sub(r"\bmm\s+USO\b", "USO", texto, flags=re.IGNORECASE)
    texto = re.sub(r"\bmma\b", "USO", texto, flags=re.IGNORECASE)
    texto = re.sub(r"\bmm\b", "", texto)
    texto = re.sub(r"\bTE\s*-\s*À\b", "", texto)

    # 5) Espaços antes de pontuação
    texto = re.sub(r"\s+([,;:\.\?\!%°])", r"\1", texto)

    # 6) Corrige sequences estranhas de pontuação e aspas
    texto = texto.replace('“', '"').replace('”', '"').replace('«', '"').replace('»', '"')

    # 7) Remover caracteres isolados e ruídos comuns
    texto = re.sub(r"\b[a-zA-Z]\b(?=\s|$)", "", texto)
    texto = re.sub(r"\s{2,}", " ", texto)

    # 8) Reformatar blocos de APRESENTAÇÕES / COMPOSIÇÃO para facilitar leitura
    texto = re.sub(r"\bAPRESENTAÇ(?:OES|ÕES|ÔES)\b", "APRESENTAÇÕES", texto, flags=re.IGNORECASE)
    texto = re.sub(r"\bCOMPOSI[ÇC]AO\b", "COMPOSIÇÃO", texto, flags=re.IGNORECASE)

    # 9) Normalizar várias ocorrências de 'excipientes q.s.p' e espaçamentos
    texto = re.sub(r"excipientes\s+q\.s\.p\W*", "excipientes q.s.p.", texto, flags=re.IGNORECASE)

    # 10) Capitalizar títulos curtos que provavelmente são cabeçalhos
    linhas = texto.split('\n')
    for idx, l in enumerate(linhas):
        s = l.strip()
        # Se tem poucas palavras e é todo minúsculo, transformar em maiúsculas (provável título)
        if 1 <= len(s.split()) <= 6 and s.islower():
            linhas[idx] = s.upper()
        else:
            linhas[idx] = l
    texto = '\n'.join(linhas)

    # 11) Remover linhas que só contenham ruído (
    texto = '\n'.join([ln for ln in texto.split('\n') if ln.strip() and not re.match(r'^[\W_]{2,}$', ln.strip())])

    # 12) Pequena limpeza final
    texto = texto.strip()
    texto = re.sub(r'\n{3,}', '\n\n', texto)

    return texto

# ----------------- [NOVO - v25] CORRETOR DE OCR -----------------
def corrigir_erros_ocr_comuns(texto: str) -> str:
    """
    Corrige erros de OCR comuns e específicos do negócio usando regex, antes da comparação.
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

# ----------------- [NOVO - v25] EXTRAÇÃO HÍBRIDA DE COLUNAS -----------------
def extrair_pdf_hibrido_colunas(arquivo_bytes: bytes) -> str:
    """
    Extrai texto de PDFs com 2 colunas (texto ou imagem).
    Tenta extração direta por colunas com PyMuPDF; se falhar, usa OCR por coluna (--psm 6).
    """
    texto_total_final = ""

    with fitz.open(stream=io.BytesIO(arquivo_bytes), filetype="pdf") as doc:
        st.info(f"Processando {len(doc)} página(s) com lógica de coluna...")

        for i, page in enumerate(doc):
            rect = page.rect
            margin_y = 18
            rect_col_1 = fitz.Rect(0, margin_y, rect.width * 0.5, rect.height - margin_y)
            rect_col_2 = fitz.Rect(rect.width * 0.5, margin_y, rect.width, rect.height - margin_y)

            # --- TENTATIVA 1: Extração Direta (para PDFs de texto) ---
            texto_direto_pagina = ""
            try:
                texto_direto_col_1 = page.get_text("text", clip=rect_col_1, sort=True) or ""
                texto_direto_col_2 = page.get_text("text", clip=rect_col_2, sort=True) or ""
                texto_direto_pagina = (texto_direto_col_1.strip() + "\n" + texto_direto_col_2.strip()).strip()
            except Exception:
                texto_direto_pagina = ""

            # --- VERIFICAÇÃO 1 ---
            # Usa extração direta se resultar em conteúdo razoável
            if len(texto_direto_pagina) > 200:
                texto_total_final += texto_direto_pagina + "\n"
                continue

            # --- TENTATIVA 2: Extração por OCR (para PDFs de imagem) ---
            st.warning(f"Extração direta falhou na pág. {i+1}. Ativando OCR por colunas (pode ser lento)...")
            try:
                ocr_config = r'--psm 6'

                # OCR da Coluna 1
                pix_col_1 = page.get_pixmap(clip=rect_col_1, dpi=300)
                img_col_1 = Image.open(io.BytesIO(pix_col_1.tobytes("png")))
                texto_ocr_col_1 = pytesseract.image_to_string(img_col_1, lang='por', config=ocr_config) or ""

                # OCR da Coluna 2
                pix_col_2 = page.get_pixmap(clip=rect_col_2, dpi=300)
                img_col_2 = Image.open(io.BytesIO(pix_col_2.tobytes("png")))
                texto_ocr_col_2 = pytesseract.image_to_string(img_col_2, lang='por', config=ocr_config) or ""

                texto_ocr_pagina = (texto_ocr_col_1.strip() + "\n" + texto_ocr_col_2.strip()).strip()
                texto_total_final += texto_ocr_pagina + "\n"

            except Exception as e:
                st.error(f"Erro fatal no OCR da pág. {i+1}: {e}")
                continue

    st.success("Extração de PDF concluída.")
    return texto_total_final

# --- [ATUALIZADA] FUNÇÃO DE EXTRAÇÃO PRINCIPAL ---
def extrair_texto(arquivo, tipo_arquivo: str) -> Tuple[str, str]:
    """
    Função principal de extração. Decide qual método usar.
    v26.8: Usa a lógica de colunas para TODOS os PDFs e aplica melhorias de layout
    específicas para o PDF da gráfica (pos-processamento).
    Retorna (texto, erro)
    """
    if arquivo is None:
        return "", f"Arquivo {tipo_arquivo} não enviado."

    try:
        arquivo.seek(0)
        texto = ""
        arquivo_bytes = arquivo.read()

        if tipo_arquivo == "pdf":
            texto = extrair_pdf_hibrido_colunas(arquivo_bytes)
            # Pós-processamento específico para PDFs da gráfica
            texto = melhorar_layout_grafica(texto)

        elif tipo_arquivo == "docx":
            st.info("Extraindo texto de DOCX...")
            doc = docx.Document(io.BytesIO(arquivo_bytes))
            texto = "\n".join([p.text for p in doc.paragraphs])

        # --- [INÍCIO] Bloco de Limpeza (Filtros) ---
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
                r"(?i)n\s*Roman\s*U\)", r"(?i)lew\s*Roman\s*U\)",
                r"KH\s*—\s*\d+", r"pp\s*\d+",
                r"^\s*an\s*$", r"^\s*man\s*$", r"^\s*contato\s*$",
                r"^\s*\|\s*$", r"\+\|",
                # ruídos observados
                r"AMO\s+dm\s+JAM\s+Vmindrtoihko\s+amo\s+o",
                r"\[E\s*O\s*\|\s*dj\s*jul",
                r"\+\s*\|\s*hd\s*bl\s*O\s*mm\s*DS\s*AALPRA",
                r"A\s*\+\s*med\s*FÃ\s*ias\s*A\s*KA\s*aõArA\s*\+\s*ima",
                r"BUL\s+BELSPAN\s+COMPR",
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
            texto = re.sub(r'(\w+)-\n(\w+)', r'\1\2', texto, flags=re.IGNORECASE)

            # Re-filtrar por rodapés padrão
            linhas = texto.split('\n')
            padrao_rodape = re.compile(r'bula do paciente|página \d+\s*de\s*\d+', re.IGNORECASE)
            linhas_filtradas_final = [linha for linha in linhas if not padrao_rodape.search(linha.strip())]

            texto = "\n".join(linhas_filtradas_final)
            texto = re.sub(r'\n{3,}', '\n\n', texto)
            texto = re.sub(r'[ \t]+', ' ', texto)
            texto = texto.strip()
        # --- [FIM] Bloco de Limpeza ---

        # --- [NOVO v25] ---
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
        # Trunca a partir do fim da linha da frase da Anvisa (mantém a frase)
        end_of_line_pos = texto.find('\n', match.end())
        if end_of_line_pos != -1:
            return texto[:end_of_line_pos]
        else:
            return texto
    return texto


# ----------------- CONFIGURAÇÃO DE SEÇÕES NUMERADAS -----------------
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

# --- O RESTANTE DO CÓDIGO (v24/v25) PERMANECE IDÊNTICO ---

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

# ----------------- NORMALIZAÇÃO -----------------
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

# ----------------- ARQUITETURA DE MAPEAMENTO DE SEÇÕES -----------------
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

        linha_norm = normalizar_texto(linha_limpa)
        if not linha_norm:
            continue

        best_match_score = 0
        best_match_canonico = None

        linha_norm_comparacao = normalizar_titulo_para_comparacao(linha_limpa)

        for titulo_possivel, titulo_canonico in titulos_possiveis.items():
            score = fuzz.token_set_ratio(
                normalizar_titulo_para_comparacao(titulo_possivel),
                linha_norm_comparacao
            )
            if score > best_match_score:
                best_match_score = score
                best_match_canonico = titulo_canonico

        if best_match_score >= 98:
            if not mapa or mapa[-1]['canonico'] != best_match_canonico:
                mapa.append({
                    'canonico': best_match_canonico,
                    'titulo_encontrado': linha_limpa,
                    'linha_inicio': idx,
                    'score': best_match_score
                })

    mapa.sort(key=lambda x: x['linha_inicio'])
    return mapa

# --- [MAPEAMENTO v18.4] - FUNÇÃO CORRIGIDA ---
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
                # Causa 1: O título está na mesma linha que o conteúdo
                if linha_atual_norm.startswith(titulo_oficial_norm) and len(linha_atual_norm) > len(titulo_oficial_norm) + 5:
                     encontrou_titulo = True
                     break

                # Causa 2: O título está sozinho (Fuzzy match)
                if fuzz.token_set_ratio(titulo_oficial_norm, linha_atual_norm) >= 98:
                    encontrou_titulo = True
                    break

            if encontrou_titulo:
                prox_idx = j
                break

            # Lógica de 2 linhas (mantida)
            if (j + 1) < len(linhas_texto):
                linha_seguinte = linhas_texto[j + 1].strip()
                titulo_duas_linhas = f"{linha_atual} {linha_seguinte}"
                titulo_duas_linhas_norm = normalizar_titulo_para_comparacao(titulo_duas_linhas)

                encontrou_titulo_2_linhas = False
                for titulo_oficial_norm in titulos_norm_set:
                    if fuzz.token_set_ratio(titulo_oficial_norm, titulo_duas_linhas_norm) >= 98:
                        encontrou_titulo_2_linhas = True
                        break

                if encontrou_titulo_2_linhas:
                    prox_idx = j
                    break

        linha_fim = prox_idx if prox_idx is not None else len(linhas_texto)
        conteudo = [linhas_texto[idx] for idx in range(linha_inicio_conteudo, linha_fim)]
        conteudo_final = "\n".join(conteudo).strip()

        return True, titulo_encontrado, conteudo_final

    return False, None, ""

# ----------------- COMPARAÇÃO DE CONTEÚDO (v24/v25 atualizado) -----------------
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

            if melhor_score >= 95:
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

            # Comparação literal (mantém pontuação e acentos)
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

        spell.word_frequency.load_words(
            vocab_referencia.union(entidades).union(palavras_a_ignorar)
        )

        palavras = re.findall(r'\b[a-záéíóúâêôãõçü]+\b', texto_final_para_checar.lower())
        erros = spell.unknown(palavras)

        return list(sorted(set([e for e in erros if len(e) > 3])))[:20]
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
            marcado.append(f"<mark style='background-color: #ffff99; padding: 2px;'>{tok}</mark>")
        else:
            marcado.append(tok)

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
    texto_trabalho = texto_original

    if secoes_problema:
        for diff in secoes_problema:
            conteudo_ref = diff['conteudo_ref']
            conteudo_belfar = diff['conteudo_belfar']

            conteudo_a_marcar = conteudo_ref if eh_referencia else conteudo_belfar
            conteudo_marcado = marcar_diferencas_palavra_por_palavra(
                conteudo_ref,
                conteudo_belfar,
                eh_referencia
            )

            secao_canonico = diff['secao']
            anchor_id = _create_anchor_id(secao_canonico, "ref" if eh_referencia else "bel")

            conteudo_com_ancora = f"<div id='{anchor_id}' style='scroll-margin-top: 20px;'>{conteudo_marcado}</div>"

            if conteudo_a_marcar in texto_trabalho:
                texto_trabalho = texto_trabalho.replace(conteudo_a_marcar, conteudo_com_ancora)
            else:
                if conteudo_marcado in texto_trabalho:
                     texto_trabalho = texto_trabalho.replace(conteudo_marcado, conteudo_com_ancora)

    if erros_ortograficos and not eh_referencia:
        for erro in erros_ortograficos:
            pattern = r'(?<![<>a-zA-Z])(?<!mark>)(?<!;>)\b(' + re.escape(erro) + r')\b(?![<>])'
            texto_trabalho = re.sub(
                pattern,
                r"<mark style='background-color: #FFDDC1; padding: 2px;'>\1</mark>",
                texto_trabalho,
                flags=re.IGNORECASE
            )

    regex_anvisa = r"((?:aprovad[ao]\s+pela\s+anvisa\s+em|data\s+de\s+aprovação\s+na\s+anvisa:)\s*[\d]{1,2}/[\d]{1,2}/[\d]{2,4})"
    match = re.search(regex_anvisa, texto_original, re.IGNORECASE)

    if match:
        frase_anvisa = match.group(1)
        if frase_anvisa in texto_trabalho:
            texto_trabalho = texto_trabalho.replace(
                frase_anvisa,
                f"<mark style='background-color: #cce5ff; padding: 2px; font-weight: 500;'>{frase_anvisa}</mark>",
                1
            )

    return texto_trabalho

# ----------------- RELATÓRIO (v21 -> atualizado) -----------------
def gerar_relatorio_final(texto_ref: str, texto_belfar: str, nome_ref: str, nome_belfar: str, tipo_bula: str):
    js_scroll_script = """
    <script>
    if (!window.handleBulaScroll) {
        window.handleBulaScroll = function(anchorIdRef, anchorIdBel) {
            var containerRef = document.getElementById('container-ref-scroll');
            var containerBel = document.getElementById('container-bel-scroll');
            var anchorRef = document.getElementById(anchorIdRef);
            var anchorBel = document.getElementById(anchorIdBel);
            if (!containerRef || !containerBel) return;
            if (!anchorRef || !anchorBel) return;
            containerRef.scrollIntoView({ behavior: 'smooth', block: 'start' });
            setTimeout(() => {
                try {
                    var topPosRef = anchorRef.offsetTop - containerRef.offsetTop;
                    containerRef.scrollTo({ top: topPosRef - 20, behavior: 'smooth' });
                    anchorRef.style.transition = 'background-color 0.5s ease-in-out';
                    anchorRef.style.backgroundColor = '#e6f7ff';
                    setTimeout(() => { anchorRef.style.backgroundColor = 'transparent'; }, 2500);
                    var topPosBel = anchorBel.offsetTop - containerBel.offsetTop;
                    containerBel.scrollTo({ top: topPosBel - 20, behavior: 'smooth' });
                    anchorBel.style.transition = 'background-color 0.5s ease-in-out';
                    anchorBel.style.backgroundColor = '#e6f7ff';
                    setTimeout(() => { anchorBel.style.backgroundColor = 'transparent'; }, 2500);
                } catch (e) { console.error(e); }
            }, 700);
        }
    }
    </script>
    """
    st.markdown(js_scroll_script, unsafe_allow_html=True)

    st.header("Relatório de Auditoria Inteligente")

    regex_anvisa = r"(aprovad[ao]\s+pela\s+anvisa\s+em|data\s+de\s+aprovação\s+na\s+anvisa:)\s*([\d]{1,2}/[\d]{1,2}/[\d]{2,4})"
    match_ref = re.search(regex_anvisa, texto_ref.lower())
    match_belfar = re.search(regex_anvisa, texto_belfar.lower())

    data_ref = match_ref.group(2).strip() if match_ref else "Não encontrada"
    data_belfar = match_belfar.group(2).strip() if match_belfar else "Não encontrada"

    secoes_faltantes, diferencas_conteudo, similaridades, diferencas_titulos = verificar_secoes_e_conteudo(texto_ref, texto_belfar, tipo_bula)
    erros_ortograficos = checar_ortografia_inteligente(texto_belfar, texto_ref, tipo_bula)

    score_similaridade_conteudo = sum(similaridades) / len(similaridades) if similaridades else 100.0

    st.subheader("Dashboard de Veredito")
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

    st.warning(f"⚠️ **Relatório de Conteúdo por Seção:**")

    mapa_diferencas = {diff['secao']: diff for diff in diferencas_conteudo}
    secoes_esperadas = obter_secoes_por_tipo(tipo_bula)

    expander_caixa_style = (
        "height: 350px; overflow-y: auto; border: 2px solid #d0d0d0; border-radius: 6px; "
        "padding: 16px; background-color: #ffffff; font-size: 14px; line-height: 1.8; "
        "font-family: 'Georgia', 'Times New Roman', serif; text-align: justify;"
    )

    for secao in secoes_esperadas:
        secao_canon_norm = normalizar_titulo_para_comparacao(secao)
        ignorar_comparacao_norm = [normalizar_titulo_para_comparacao(s) for s in obter_secoes_ignorar_comparacao()]

        if secao_canon_norm in ignorar_comparacao_norm:
            with st.expander(f"📄 {secao} - ℹ️ (Seção não comparada)"):
                st.info("Esta seção (ex: Composição, Dizeres Legais) é ignorada na comparação de conteúdo por padrão.")
            continue

        if secao in mapa_diferencas:
            diff = mapa_diferencas[secao]
            titulo_display = diff.get('titulo_encontrado') or secao

            with st.expander(f"📄 {titulo_display} - ❌ CONTEÚDO DIVERGENTE"):
                secao_canonico = diff['secao']
                anchor_id_ref = _create_anchor_id(secao_canonico, "ref")
                anchor_id_bel = _create_anchor_id(secao_canonico, "bel")

                expander_html_ref = marcar_diferencas_palavra_por_palavra(
                    diff['conteudo_ref'], diff['conteudo_belfar'], eh_referencia=True
                ).replace('\n', '<br>')

                expander_html_belfar = marcar_diferencas_palavra_por_palavra(
                    diff['conteudo_ref'], diff['conteudo_belfar'], eh_referencia=False
                ).replace('\n', '<br>')

                clickable_style = expander_caixa_style + " cursor: pointer; transition: background-color 0.3s ease;"

                html_ref_box = f"<div onclick='window.handleBulaScroll(\"{anchor_id_ref}\", \"{anchor_id_bel}\")' style='{clickable_style}' title='Clique para ir à seção' onmouseover='this.style.backgroundColor=\"#f0f8ff\"' onmouseout='this.style.backgroundColor=\"#ffffff\"'>{expander_html_ref}</div>"

                html_bel_box = f"<div onclick='window.handleBulaScroll(\"{anchor_id_ref}\", \"{anchor_id_bel}\")' style='{clickable_style}' title='Clique para ir à seção' onmouseover='this.style.backgroundColor=\"#f0f8ff\"' onmouseout='this.style.backgroundColor=\"#ffffff\"'>{expander_html_belfar}</div>"

                c1, c2 = st.columns(2)
                with c1:
                    st.markdown("**Referência:** (Clique na caixa para rolar)")
                    st.markdown(html_ref_box, unsafe_allow_html=True)
                with c2:
                    st.markdown("**BELFAR:** (Clique na caixa para rolar)")
                    st.markdown(html_bel_box, unsafe_allow_html=True)

        elif secao not in secoes_faltantes:
            with st.expander(f"📄 {secao} - ✅ CONTEÚDO IDÊNTICO"):
                st.success("O conteúdo desta seção é idêntico em ambos os documentos.")

    if erros_ortograficos:
        st.info(f"📝 **Possíveis erros ortográficos ({len(erros_ortograficos)} palavras):**\n" + ", ".join(erros_ortograficos))

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

    html_ref_marcado = marcar_divergencias_html(
        texto_original=texto_ref,
        secoes_problema=diferencas_conteudo,
        erros_ortograficos=[],
        tipo_bula=tipo_bula,
        eh_referencia=True
    ).replace('\n', '<br>')

    html_belfar_marcado = marcar_divergencias_html(
        texto_original=texto_belfar,
        secoes_problema=diferencas_conteudo,
        erros_ortograficos=erros_ortograficos,
        tipo_bula=tipo_bula,
        eh_referencia=False
    ).replace('\n', '<br>')

    caixa_style = (
        "height: 700px; overflow-y: auto; border: 2px solid #999; border-radius: 4px; "
        "padding: 24px 32px; background-color: #ffffff; "
        "font-family: 'Georgia', 'Times New Roman', serif; font-size: 14px; "
        "line-height: 1.8; box-shadow: 0 2px 12px rgba(0,0,0,0.15); "
        "text-align: justify; color: #000000;"
    )

    col1, col2 = st.columns(2, gap="medium")

    with col1:
        st.markdown(f"**📄 {nome_ref}**")
        st.markdown(f"<div id='container-ref-scroll' style='{caixa_style}'>{html_ref_marcado}</div>", unsafe_allow_html=True)

    with col2:
        st.markdown(f"**📄 {nome_belfar}**")
        st.markdown(f"<div id='container-bel-scroll' style='{caixa_style}'>{html_belfar_marcado}</div>", unsafe_allow_html=True)

# ----------------- INTERFACE -----------------
st.set_page_config(layout="wide", page_title="Auditoria de Bulas - Gráfica x Arte", page_icon="🔬")
st.title("🔬 Auditoria de Bulas — Gráfica x Arte (v26.8)")
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
        with st.spinner("🔄 Processando e analisando as bulas... (v26.8 - Híbrido de Colunas)"):

            tipo_arquivo_ref = 'docx' if pdf_ref.name.lower().endswith('.docx') else 'pdf'

            # Extração da Referência
            texto_ref, erro_ref = extrair_texto(pdf_ref, tipo_arquivo_ref)

            # Extração da Gráfica (sempre pdf)
            texto_belfar, erro_belfar = extrair_texto(pdf_belfar, 'pdf')

            # --- v26.8: Truncar após Anvisa em ambos os textos ---
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
st.caption("Sistema de Auditoria de Bulas v26.8 | Híbrido de Coluna + OCR psm 6 + Corretor + Melhoria de Layout da Gráfica")
