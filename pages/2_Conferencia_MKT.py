#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Sistema: AuditorIA de Bulas v19.0 - Versão corrigida completa
# Objetivo: comparar bulas (Anvisa x Marketing), com OCR, reflow, detecção de seções,
# marcação de diferenças palavra-a-palavra, checagem ortográfica e visualização lado-a-lado.
#
# Observações:
# - Esta é a versão completa do script com as correções solicitadas:
#   * Melhor detecção de títulos (inclui títulos quebrados em 1,2 ou 3 linhas)
#   * Extração de conteúdo de seção mais robusta (usa mapa de seções como fallback)
#   * Reflow de parágrafos ajustado para evitar "puxar" conteúdo da seção seguinte
#   * Correções em marcação HTML, geração do relatório e visualização lado-a-lado
# - Mantenha Tesseract e o modelo SpaCy instalados: `tesseract` + `pt_core_news_lg`
# - Para usar no Streamlit, salve este arquivo e execute `streamlit run bula_auditoria.py`

import re
import difflib
import unicodedata
import io
import spacy
from thefuzz import fuzz
from spellchecker import SpellChecker
import pytesseract
from PIL import Image
import fitz  # PyMuPDF
import docx
import streamlit as st

# ----------------- CONFIGURAÇÃO DA PÁGINA STREAMLIT -----------------
hide_streamlit_UI = """
            <style>
            [data-testid="stHeader"] { display: none !important; visibility: hidden !important; }
            [data-testid="main-menu-button"] { display: none !important; }
            footer { display: none !important; visibility: hidden !important; }
            [data-testid="stStatusWidget"] { display: none !important; visibility: hidden !important; }
            [data-testid="stCreatedBy"] { display: none !important; visibility: hidden !important; }
            [data-testid="stHostedBy"] { display: none !important; visibility: hidden !important; }
            </style>
            """
st.markdown(hide_streamlit_UI, unsafe_allow_html=True)

# ----------------- MODELO NLP -----------------
@st.cache_resource
def carregar_modelo_spacy():
    try:
        return spacy.load("pt_core_news_lg")
    except OSError:
        st.error("Modelo 'pt_core_news_lg' não encontrado. Execute: python -m spacy download pt_core_news_lg")
        return None

nlp = carregar_modelo_spacy()

# ----------------- EXTRAÇÃO DE PDF ATUALIZADA COM OCR -----------------
def extrair_texto_pdf_com_ocr(arquivo_bytes):
    """
    Tenta extrair texto nativo usando PyMuPDF (fitz). Se falhar ou detectar PDF 'em curva' (muito pouco texto),
    faz OCR página-a-página usando pytesseract em imagens rasterizadas (dpi=300).
    Também tenta lidar com layout de 2 colunas: lê colunas esquerda então direita por bloco.
    """
    texto_direto = ""
    try:
        with fitz.open(stream=io.BytesIO(arquivo_bytes), filetype="pdf") as doc:
            for page in doc:
                # blocks = (x0, y0, x1, y1, "text", block_no, block_type)
                blocks = page.get_text("blocks", sort=False)
                # heurística simples de split vertical: meio da página
                middle_x = page.rect.width / 2.0
                col1_blocks = []
                col2_blocks = []
                for b in blocks:
                    x0 = b[0]
                    # se o bloco atravessa o meio, decidir por centro
                    x_center = (b[0] + b[2]) / 2.0
                    if x_center <= middle_x:
                        col1_blocks.append(b)
                    else:
                        col2_blocks.append(b)
                # ordenar por y0 (top)
                col1_blocks.sort(key=lambda b: b[1])
                col2_blocks.sort(key=lambda b: b[1])
                # concatenar coluna esquerda depois direita (por página)
                for b in col1_blocks:
                    texto_direto += (b[4] or "") + "\n"
                for b in col2_blocks:
                    texto_direto += (b[4] or "") + "\n"
                texto_direto += "\n"
        if len(texto_direto.strip()) > 100:
            return texto_direto
    except Exception:
        # tentativa fallback com get_text("text")
        try:
            with fitz.open(stream=io.BytesIO(arquivo_bytes), filetype="pdf") as doc:
                for page in doc:
                    texto_direto += page.get_text("text") + "\n"
            if len(texto_direto.strip()) > 100:
                return texto_direto
        except Exception:
            pass

    # Se chegou aqui: usar OCR
    st.info("Arquivo 'em curva' detectado ou texto nativo insuficiente. Iniciando leitura com OCR... Isso pode demorar um pouco.")
    texto_ocr = ""
    with fitz.open(stream=io.BytesIO(arquivo_bytes), filetype="pdf") as doc:
        for i, page in enumerate(doc, start=1):
            try:
                pix = page.get_pixmap(dpi=300)
                img_bytes = pix.tobytes("png")
                imagem = Image.open(io.BytesIO(img_bytes)).convert("RGB")
                # separa imagem em duas colunas por metade (heurística)
                w, h = imagem.size
                split_x = w // 2
                left_img = imagem.crop((0, 0, split_x, h))
                right_img = imagem.crop((split_x, 0, w, h))
                left_text = pytesseract.image_to_string(left_img, lang='por') or ""
                right_text = pytesseract.image_to_string(right_img, lang='por') or ""
                # juntar, preferindo texto da esquerda primeiro
                page_text = left_text.strip() + "\n" + right_text.strip()
                texto_ocr += page_text + "\n\n"
            except Exception as e:
                # fallback: OCR da imagem inteira
                try:
                    pix = page.get_pixmap(dpi=150)
                    img_bytes = pix.tobytes("png")
                    imagem = Image.open(io.BytesIO(img_bytes)).convert("RGB")
                    texto_ocr += pytesseract.image_to_string(imagem, lang='por') + "\n\n"
                except Exception:
                    st.warning(f"Erro OCR página {i}: {e}")
    return texto_ocr

# ----------------- FUNÇÃO DE EXTRAÇÃO PRINCIPAL -----------------
def extrair_texto(arquivo, tipo_arquivo):
    if arquivo is None:
        return "", f"Arquivo {tipo_arquivo} não enviado."
    try:
        arquivo.seek(0)
        texto = ""
        if tipo_arquivo == 'pdf':
            texto = extrair_texto_pdf_com_ocr(arquivo.read())
        elif tipo_arquivo == 'docx':
            doc = docx.Document(arquivo)
            texto = "\n".join([p.text for p in doc.paragraphs])
        # limpeza básica
        if texto:
            caracteres_invisiveis = ['\u00AD', '\u200B', '\u200C', '\u200D', '\uFEFF']
            for char in caracteres_invisiveis:
                texto = texto.replace(char, '')
            texto = texto.replace('\r\n', '\n').replace('\r', '\n')
            texto = texto.replace('\u00A0', ' ')
            # junta hifenizações no final da linha
            texto = re.sub(r'(\w+)-\n(\w+)', r'\1\2', texto, flags=re.IGNORECASE)
            # remover linhas irrelevantes / ruído conhecido
            linhas = texto.split('\n')
            padrao_ruido_linha = re.compile(
                r'bula do paciente|página \d+\s*de\s*\d+' 
                r'|(Tipologie|Tipologia) da bula:.*|(Merida|Medida) da (bula|trúa):?.*'
                r'|(Impressãe|Impressão):? Frente/Verso|Papel[\.:]? Ap \d+gr'
                r'|Cor:? Preta|contato:?|artes@belfar\.com\.br'
                r'|BUL_CLORIDRATO_DE_NAFAZOLINA_BUL\d+V\d+|BUL\d+V\d+'
                r'|CLORIDRATO DE NAFAZOLINA: Times New Roman'
                r'|^\s*FRENTE\s*$|^\s*VERSO\s*$'
                r'|^\s*\d+\s*mm\s*$'
                r'|^\s*-\s*Normal e Negrito\. Corpo \d+\s*$'
                r'|^\s*BELFAR\s*$|^\s*REZA\s*$|^\s*GEM\s*$|^\s*ALTEFAR\s*$|^\s*RECICLAVEL\s*$'
            , re.IGNORECASE)
            linhas_filtradas = []
            for linha in linhas:
                linha_strip = linha.strip()
                if not padrao_ruido_linha.search(linha_strip):
                    # mantem linhas significativas
                    if len(linha_strip) > 1 or (len(linha_strip) == 1 and linha_strip.isdigit()):
                        linhas_filtradas.append(linha)
                    elif linha_strip.isupper() and len(linha_strip) > 0:
                        linhas_filtradas.append(linha_strip)
            texto = "\n".join(linhas_filtradas)
            texto = re.sub(r'\n{3,}', '\n\n', texto)
            texto = texto.strip()
            # garantir espaço antes de parenteses que grudaram ao fim de palavra
            texto = re.sub(r'(\w)\(', r'\1 (', texto)
        return texto, None
    except Exception as e:
        return "", f"Erro ao ler o arquivo {tipo_arquivo}: {e}"

# ----------------- CONFIGURAÇÃO DE SEÇÕES -----------------
def obter_secoes_por_tipo(tipo_bula):
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
            "1. APRESENTAÇÕES",
            "2. COMPOSIÇÃO",
            "3. INDICAÇÕES",
            "4. RESULTADOS DE EFICÁCIA",
            "5. CARACTERÍSTICAS FARMACOLÓGICAS",
            "6. CONTRAINDICAÇÕES",
            "7. ADVERTÊNCIAS E PRECAUÇÕES",
            "8. INTERAÇÕES MEDICAMENTOSAS",
            "9. CUIDADOS DE ARMAZENAMENTO DO MEDICAMENTO",
            "10. POSOLOGIA E MODO DE USAR",
            "11. REAÇÕES ADVERSAS",
            "12. SUPERDOSE",
            "DIZERES LEGAIS"
        ]
    }
    return secoes.get(tipo_bula, [])

def obter_aliases_secao():
    return {
        "3. INDICAÇÕES": "1. PARA QUE ESTE MEDICAMENTO É INDICADO?",
        "6. CONTRAINDICAÇÕES": "3. QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?",
        "10. POSOLOGIA E MODO DE USAR": "6. COMO DEVO USAR ESTE MEDICAMENTO?",
        "11. REAÇÕES ADVERSAS": "8. QUAIS OS MALES QUE ESTE MEDICAMENTO PODE ME CAUSAR?",
        "12. SUPERDOSE": "9. O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?",
        "9. CUIDADOS DE ARMAZENAMENTO DO MEDICAMENTO": "5. ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?"
    }

def obter_secoes_ignorar_ortografia():
    return ["COMPOSIÇÃO", "DIZERES LEGAIS"]

def obter_secoes_ignorar_comparacao():
    return ["COMPOSIÇÃO", "DIZERES LEGAIS", "APRESENTAÇÕES",
            "5. ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?",
            "9. CUIDADOS DE ARMAZENAMENTO DO MEDICAMENTO"]

# ----------------- NORMALIZAÇÃO -----------------
def normalizar_texto(texto):
    texto = ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')
    texto = re.sub(r'[^\w\s]', '', texto)
    texto = ' '.join(texto.split())
    return texto.lower()

def normalizar_titulo_para_comparacao(texto):
    texto_norm = normalizar_texto(texto)
    texto_norm = re.sub(r'^\d+\s*[\.\-)]*\s*', '', texto_norm).strip()
    return texto_norm

def _create_anchor_id(secao_nome, prefix):
    norm = normalizar_texto(secao_nome)
    norm_safe = re.sub(r'[^a-z0-9\-]', '-', norm)
    return f"anchor-{prefix}-{norm_safe}"

# ----------------- DETECÇÃO E MAPEAMENTO DE SEÇÕES -----------------
def is_titulo_secao(linha):
    linha = linha.strip()
    if not linha or len(linha) < 2:
        return False
    if len(linha) > 130:
        return False
    # evitar títulos com muitos símbolos estranhos
    non_alpha_ratio = len(re.findall(r'[^A-Za-z0-9À-ÖØ-öø-ÿ\s\.\-\(\)\:]', linha)) / max(1, len(linha))
    if non_alpha_ratio > 0.25:
        return False
    # números de seção como "1." "1)" etc
    if re.match(r'^\d+\s*[\.\-\)]', linha):
        return True
    words = linha.split()
    # se tudo em maiúsculas ou maioria dos inícios de palavras capitalizados
    upper_count = sum(1 for w in words if w.isupper())
    capstart_count = sum(1 for w in words if w and w[0].isupper())
    if len(words) <= 8 and (upper_count >= len(words) - 1 or capstart_count >= len(words) - 1):
        return True
    # títulos com tamanho moderado e poucas palavras
    if 1 < len(words) <= 15:
        if linha.endswith('.'):
            return False
        return True
    return False

def mapear_secoes(texto_completo, secoes_esperadas):
    mapa = []
    linhas = texto_completo.split('\n')
    aliases = obter_aliases_secao()
    titulos_possiveis = {}
    for secao in secoes_esperadas:
        titulos_possiveis[secao] = secao
    for alias, canonico in aliases.items():
        if canonico in secoes_esperadas:
            titulos_possiveis[alias] = canonico

    idx = 0
    titulos_norm = {t: normalizar_titulo_para_comparacao(t) for t in titulos_possiveis.keys()}

    while idx < len(linhas):
        linha_limpa = linhas[idx].strip()
        if not is_titulo_secao(linha_limpa):
            idx += 1
            continue

        best = {'score': 0, 'canonico': None, 'titulo_encontrado': None, 'num_linhas_titulo': 1}

        # compara como 1 linha
        for titulo_possivel, canonico in titulos_possiveis.items():
            score = fuzz.token_set_ratio(normalizar_titulo_para_comparacao(titulo_possivel), normalizar_titulo_para_comparacao(linha_limpa))
            if score > best['score']:
                best.update({'score': score, 'canonico': canonico, 'titulo_encontrado': linha_limpa, 'num_linhas_titulo': 1})

        # tenta combinar com a linha seguinte (2 linhas de título)
        if (idx + 1) < len(linhas):
            linha2 = linhas[idx + 1].strip()
            if len(linha2.split()) <= 12:
                combinado = f"{linha_limpa} {linha2}"
                for titulo_possivel, canonico in titulos_possiveis.items():
                    score = fuzz.token_set_ratio(normalizar_titulo_para_comparacao(titulo_possivel), normalizar_titulo_para_comparacao(combinado))
                    if score > best['score']:
                        best.update({'score': score, 'canonico': canonico, 'titulo_encontrado': combinado, 'num_linhas_titulo': 2})

        # tenta 3 linhas de título
        if (idx + 2) < len(linhas):
            linha2 = linhas[idx + 1].strip()
            linha3 = linhas[idx + 2].strip()
            if len(linha2.split()) <= 15 and len(linha3.split()) <= 12:
                combinado3 = f"{linha_limpa} {linha2} {linha3}"
                for titulo_possivel, canonico in titulos_possiveis.items():
                    score = fuzz.token_set_ratio(normalizar_titulo_para_comparacao(titulo_possivel), normalizar_titulo_para_comparacao(combinado3))
                    if score > best['score']:
                        best.update({'score': score, 'canonico': canonico, 'titulo_encontrado': combinado3, 'num_linhas_titulo': 3})

        LIMIAR = 92
        if best['score'] >= LIMIAR:
            # evitar duplicatas imediatas
            if not mapa or mapa[-1]['canonico'] != best['canonico'] or mapa[-1]['linha_inicio'] != idx:
                mapa.append({
                    'canonico': best['canonico'],
                    'titulo_encontrado': best['titulo_encontrado'],
                    'linha_inicio': idx,
                    'score': best['score'],
                    'num_linhas_titulo': best['num_linhas_titulo']
                })
            idx += best['num_linhas_titulo']
        else:
            idx += 1

    mapa.sort(key=lambda x: x['linha_inicio'])
    return mapa

def obter_dados_secao(secao_canonico, mapa_secoes, linhas_texto, tipo_bula):
    """
    Dado um mapa de seções (mapear_secoes), encontra o conteúdo entre o título e o próximo título,
    com heurísticas que também usam a lista completa de títulos esperados como referência.
    Retorna (encontrou(bool), titulo_encontrado(str), conteudo(str)).
    """
    titulos_lista = obter_secoes_por_tipo(tipo_bula)
    titulos_norm_set = {normalizar_titulo_para_comparacao(t) for t in titulos_lista}

    for i, secao_mapa in enumerate(mapa_secoes):
        if secao_mapa['canonico'] != secao_canonico:
            continue

        titulo_encontrado = secao_mapa['titulo_encontrado']
        linha_inicio = secao_mapa['linha_inicio']
        num_linhas_titulo = secao_mapa.get('num_linhas_titulo', 1)
        linha_inicio_conteudo = linha_inicio + num_linhas_titulo

        # procura próximo título a partir da lista de titulos esperados ou próximos no mapa de seções
        prox_idx = None
        j = linha_inicio_conteudo
        while j < len(linhas_texto):
            linha_atual = linhas_texto[j].strip()
            if not linha_atual:
                j += 1
                continue
            linha_atual_norm = normalizar_titulo_para_comparacao(linha_atual)
            # se a linha atual contém um título esperado (heurística)
            if any(linha_atual_norm.startswith(t) or t in linha_atual_norm for t in titulos_norm_set):
                prox_idx = j
                break
            # testar combinação com a próxima linha
            if (j + 1) < len(linhas_texto):
                combinacao = f"{linha_atual} {linhas_texto[j + 1].strip()}"
                combinacao_norm = normalizar_titulo_para_comparacao(combinacao)
                if any(combinacao_norm.startswith(t) or t in combinacao_norm for t in titulos_norm_set):
                    prox_idx = j
                    break
            j += 1

        # fallback: usar mapa_secoes ordenado para achar o próximo título do documento
        if prox_idx is None:
            mapa_ordenado = sorted(mapa_secoes, key=lambda x: x['linha_inicio'])
            try:
                pos = next(k for k, v in enumerate(mapa_ordenado) if v['linha_inicio'] == linha_inicio and v['canonico'] == secao_canonico)
                if pos + 1 < len(mapa_ordenado):
                    prox_idx = mapa_ordenado[pos + 1]['linha_inicio']
                else:
                    prox_idx = len(linhas_texto)
            except StopIteration:
                prox_idx = len(linhas_texto)

        linha_fim = prox_idx if prox_idx is not None else len(linhas_texto)
        conteudo = [linhas_texto[idx] for idx in range(linha_inicio_conteudo, linha_fim)]

        if not conteudo:
            return True, titulo_encontrado, ""

        # Reflow mais conservador: evita juntar linhas quando a linha seguinte parece ser um título
        conteudo_refluxo = [conteudo[0]]
        for k in range(1, len(conteudo)):
            linha_anterior = conteudo_refluxo[-1]
            linha_atual = conteudo[k]
            linha_atual_strip = linha_atual.strip()

            # detectar possível início de parágrafo ou título falso
            is_new_paragraph = False
            if not linha_atual_strip:
                is_new_paragraph = True
            else:
                primeiro_char = linha_atual_strip[0]
                if primeiro_char.isupper() and len(linha_atual_strip.split()) <= 3:
                    # se a linha atual é curta e começa com maiúscula, pode ser título ou item numerado
                    is_new_paragraph = True
                if re.match(r'^[\d\-\*•]', linha_atual_strip):
                    is_new_paragraph = True
                if linha_atual_strip[0] in "“\"(":
                    is_new_paragraph = True

            # detectar final de sentença para juntar
            is_end_of_sentence = bool(re.search(r'[.!?:]\s*$', linha_anterior.strip()))

            if not is_new_paragraph and not is_end_of_sentence:
                conteudo_refluxo[-1] = linha_anterior.rstrip() + " " + linha_atual.lstrip()
            else:
                conteudo_refluxo.append(linha_atual)

        conteudo_final = "\n".join(conteudo_refluxo).strip()
        # limpeza de espaços antes/depois de pontuação
        conteudo_final = re.sub(r'\s+([.,;:!?)\]])', r'\1', conteudo_final)
        conteudo_final = re.sub(r'([(\[])\s+', r'\1', conteudo_final)
        conteudo_final = re.sub(r'([.,;:!?)\]])(\w)', r'\1 \2', conteudo_final)
        conteudo_final = re.sub(r'(\w)([(\[])', r'\1 \2', conteudo_final)
        return True, titulo_encontrado, conteudo_final

    return False, None, ""

# ----------------- COMPARAÇÃO DE CONTEÚDO -----------------
def verificar_secoes_e_conteudo(texto_anvisa, texto_mkt, tipo_bula):
    secoes_esperadas = obter_secoes_por_tipo(tipo_bula)
    secoes_faltantes, diferencas_conteudo, similaridades_secoes, diferencas_titulos = [], [], [], []
    secoes_ignorar_upper = [s.upper() for s in obter_secoes_ignorar_comparacao()]

    linhas_anvisa = texto_anvisa.split('\n')
    linhas_mkt = texto_mkt.split('\n')
    mapa_anvisa = mapear_secoes(texto_anvisa, secoes_esperadas)
    mapa_mkt = mapear_secoes(texto_mkt, secoes_esperadas)

    for secao in secoes_esperadas:
        melhor_titulo = None
        encontrou_anvisa, _, conteudo_anvisa = obter_dados_secao(secao, mapa_anvisa, linhas_anvisa, tipo_bula)
        encontrou_mkt, titulo_mkt, conteudo_mkt = obter_dados_secao(secao, mapa_mkt, linhas_mkt, tipo_bula)

        if not encontrou_mkt:
            # tenta achar título similar no mapa_mkt com alta similaridade
            melhor_score = 0
            melhor_titulo = None
            for m in mapa_mkt:
                score = fuzz.token_set_ratio(normalizar_titulo_para_comparacao(secao), normalizar_titulo_para_comparacao(m['titulo_encontrado']))
                if score > melhor_score:
                    melhor_score = score
                    melhor_titulo = m['titulo_encontrado']
            if melhor_score >= 95 and melhor_titulo:
                # extrair conteúdo do mapeamento encontrado
                for m in mapa_mkt:
                    if m['titulo_encontrado'] == melhor_titulo:
                        next_section_start = len(linhas_mkt)
                        current_index = mapa_mkt.index(m)
                        if current_index + 1 < len(mapa_mkt):
                            next_section_start = mapa_mkt[current_index + 1]['linha_inicio']
                        conteudo_mkt_raw = "\n".join(linhas_mkt[m['linha_inicio'] + m.get('num_linhas_titulo', 1) : next_section_start])
                        temp_mapa = [{'canonico': secao, 'titulo_encontrado': melhor_titulo, 'linha_inicio': 0, 'num_linhas_titulo': 0}]
                        _, _, conteudo_mkt = obter_dados_secao(secao, temp_mapa, conteudo_mkt_raw.split('\n'), tipo_bula)
                        break
                encontrou_mkt = True
            else:
                secoes_faltantes.append(secao)
                continue

        if encontrou_anvisa and encontrou_mkt:
            secao_comp = normalizar_titulo_para_comparacao(secao)
            titulo_mkt_comp = normalizar_titulo_para_comparacao(titulo_mkt if titulo_mkt else (melhor_titulo or ""))
            if secao_comp != titulo_mkt_comp:
                if not any(d['secao_esperada'] == secao for d in diferencas_titulos):
                    diferencas_titulos.append({'secao_esperada': secao, 'titulo_encontrado': titulo_mkt if titulo_mkt else melhor_titulo})

            if secao.upper() in secoes_ignorar_upper:
                continue

            if normalizar_texto(conteudo_anvisa) != normalizar_texto(conteudo_mkt):
                titulo_real_encontrado = titulo_mkt if titulo_mkt else melhor_titulo
                diferencas_conteudo.append({
                    'secao': secao,
                    'conteudo_anvisa': conteudo_anvisa,
                    'conteudo_mkt': conteudo_mkt,
                    'titulo_encontrado': titulo_real_encontrado
                })
                similaridades_secoes.append(0)
            else:
                similaridades_secoes.append(100)

    return secoes_faltantes, diferencas_conteudo, similaridades_secoes, diferencas_titulos

# ----------------- ORTOGRAFIA -----------------
def checar_ortografia_inteligente(texto_para_checar, texto_referencia, tipo_bula):
    if not nlp or not texto_para_checar:
        return []

    try:
        secoes_ignorar = obter_secoes_ignorar_ortografia()
        secoes_todas = obter_secoes_por_tipo(tipo_bula)
        texto_filtrado_para_checar = []

        mapa_secoes = mapear_secoes(texto_para_checar, secoes_todas)
        linhas_texto = texto_para_checar.split('\n')

        for secao_nome in secoes_todas:
            if secao_nome.upper() in [s.upper() for s in secoes_ignorar]:
                continue
            encontrou, _, conteudo = obter_dados_secao(secao_nome, mapa_secoes, linhas_texto, tipo_bula)
            if encontrou and conteudo:
                texto_filtrado_para_checar.append(conteudo)

        texto_final_para_checar = '\n'.join(texto_filtrado_para_checar)
        if not texto_final_para_checar:
            return []

        spell = SpellChecker(language='pt')
        palavras_a_ignorar = {"alair", "belfar", "peticionamento", "urotrobel", "contato", "dihidroergotamina"}
        vocab_referencia = set(re.findall(r'\b[a-záéíóúâêôãõçü]+\b', texto_referencia.lower()))
        doc = nlp(texto_para_checar)
        entidades = {ent.text.lower() for ent in doc.ents}

        # adicionar ao dicionário customizado palavras do texto de referência e entidades
        try:
            spell.word_frequency.load_words(list(vocab_referencia.union(entidades).union(palavras_a_ignorar)))
        except Exception:
            # fallback caso load_words não exista
            for w in vocab_referencia.union(entidades).union(palavras_a_ignorar):
                try:
                    spell.word_frequency.add(w)
                except Exception:
                    pass

        palavras = re.findall(r'\b[a-záéíóúâêôãõçü]+\b', texto_final_para_checar.lower())
        erros = spell.unknown(palavras)
        # filtrar e ordenar
        erros_filtrados = sorted(set([e for e in erros if len(e) > 3]))
        return erros_filtrados[:20]

    except Exception:
        return []

# ----------------- DIFERENÇAS PALAVRA A PALAVRA -----------------
def marcar_diferencas_palavra_por_palavra(texto_ref, texto_belfar, eh_referencia):
    def tokenizar(txt):
        # preserva quebras de linha como token separado
        return re.findall(r'\n|[A-Za-zÀ-ÖØ-öø-ÿ0-9_]+|[^\w\s]', txt, re.UNICODE)

    def norm(tok):
        if re.match(r'[A-Za-zÀ-ÖØ-öø-ÿ0-9_]+$', tok):
            return normalizar_texto(tok)
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

        tok_anterior_raw = re.sub(r'^<mark[^>]*>|</mark>$', '', marcado[i-1])
        raw_tok = re.sub(r'^<mark[^>]*>|</mark>$', '', tok)

        if raw_tok == '\n' or tok_anterior_raw == '\n':
            resultado += tok
        elif re.match(r'^[.,;:!?)\]]$', raw_tok):
            resultado += tok
        elif re.match(r'^[(\[]$', tok_anterior_raw):
            resultado += tok
        else:
            resultado += " " + tok

    # remover espaços indesejados entre marcações consecutivas
    resultado = re.sub(r"(</mark>)\s+(<mark[^>]*>)", r"\1 \2", resultado)
    return resultado

# ----------------- MARCAÇÃO POR SEÇÃO COM ÍNDICES -----------------
def marcar_divergencias_html(texto_original, secoes_problema, erros_ortograficos, tipo_bula, eh_referencia=False):
    texto_trabalho = texto_original
    if secoes_problema:
        for diff in secoes_problema:
            conteudo_ref = diff.get('conteudo_anvisa', '') or ''
            conteudo_belfar = diff.get('conteudo_mkt', '') or ''
            conteudo_a_substituir = conteudo_ref if eh_referencia else conteudo_belfar
            if not conteudo_a_substituir:
                continue
            conteudo_marcado = marcar_diferencas_palavra_por_palavra(conteudo_ref, conteudo_belfar, eh_referencia)
            secao_canonico = diff.get('secao', '')
            anchor_id = _create_anchor_id(secao_canonico, "ref" if eh_referencia else "bel")
            conteudo_com_ancora = f"<div id='{anchor_id}' style='scroll-margin-top: 20px;'>{conteudo_marcado}</div>"
            # substituir apenas a primeira ocorrência para evitar múltiplas substituições
            texto_trabalho = texto_trabalho.replace(conteudo_a_substituir, conteudo_com_ancora, 1)

    # marcar possíveis erros ortográficos (somente no texto do Belfar / marketing)
    if erros_ortograficos and not eh_referencia:
        for erro in erros_ortograficos:
            pattern = r'(?<![<>A-Za-z0-9])\b(' + re.escape(erro) + r')\b(?![<>A-Za-z0-9])'
            texto_trabalho = re.sub(
                pattern,
                r"<mark style='background-color: #FFDDC1; padding: 2px;'>\1</mark>",
                texto_trabalho,
                flags=re.IGNORECASE
            )

    # destacar frase de aprovação ANVISA (se existir)
    regex_anvisa = r"((?:aprovad[ao]\s+pela\s+anvisa\s+em|data\s+de\s+aprovação\s+na\s+anvisa:)\s*[\d]{1,2}/[\d]{1,2}/[\d]{2,4})"
    match = re.search(regex_anvisa, texto_original, re.IGNORECASE)
    if match:
        frase_anvisa = match.group(1)
        texto_trabalho = texto_trabalho.replace(frase_anvisa, f"<mark style='background-color: #cce5ff; padding: 2px; font-weight: 500;'>{frase_anvisa}</mark>", 1)

    return texto_trabalho

# ----------------- RELATÓRIO -----------------
def gerar_relatorio_final(texto_ref, texto_belfar, nome_ref, nome_belfar, tipo_bula):
    # script de scroll sincronizado
    js_scroll_script = """
    <script>
    if (!window.handleBulaScroll) {
        window.handleBulaScroll = function(anchorIdRef, anchorIdBel) {
            var containerRef = document.getElementById('container-ref-scroll');
            var containerBel = document.getElementById('container-bel-scroll');
            var anchorRef = document.getElementById(anchorIdRef);
            var anchorBel = document.getElementById(anchorIdBel);
            if (!containerRef || !containerBel) { return; }
            if (!anchorRef || !anchorBel) { return; }
            containerRef.scrollIntoView({ behavior: 'smooth', 'block': 'start' });
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
    regex_anvisa = r"(?:aprovad[ao]\s+pela\s+anvisa\s+em|data\s+de\s+aprovação\s+na\s+anvisa:)\s*([\d]{1,2}/[\d]{1,2}/[\d]{2,4})"

    match_ref = re.search(regex_anvisa, texto_ref, re.IGNORECASE)
    match_belfar = re.search(regex_anvisa, texto_belfar, re.IGNORECASE)

    data_ref = match_ref.group(1).strip() if match_ref else "Não encontrada"
    data_belfar = match_belfar.group(1).strip() if match_belfar else "Não encontrada"

    secoes_faltantes, diferencas_conteudo, similaridades, diferencas_titulos = verificar_secoes_e_conteudo(texto_ref, texto_belfar, tipo_bula)
    erros_ortograficos = checar_ortografia_inteligente(texto_belfar, texto_ref, tipo_bula)
    score_similaridade_conteudo = sum(similaridades) / len(similaridades) if similaridades else 100.0

    st.subheader("Dashboard de Veredito")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Conformidade de Conteúdo", f"{score_similaridade_conteudo:.0f}%")
    col2.metric("Erros Ortográficos", len(erros_ortograficos))
    col3.metric("Data ANVISA (Marketing)", data_belfar)
    col4.metric("Seções Faltantes", f"{len(secoes_faltantes)}")

    st.divider()
    st.subheader("Detalhes dos Problemas Encontrados")
    st.info(f"ℹ️ **Datas de Aprovação ANVISA:**\n   - Arquivo da Anvisa: {data_ref}\n   - Arquivo Marketing: {data_belfar}")

    if secoes_faltantes:
        st.error(f"🚨 **Seções faltantes na bula Arquivo Marketing ({len(secoes_faltantes)})**:\n" + "\n".join([f"   - {s}" for s in secoes_faltantes]))
    else:
        st.success("✅ Todas as seções obrigatórias estão presentes")

    if diferencas_conteudo:
        st.warning(f"⚠️ **Diferenças de conteúdo encontradas ({len(diferencas_conteudo)} seções):**")
        expander_caixa_style = (
            "height: 350px; overflow-y: auto; border: 2px solid #d0d0d0; border-radius: 6px; "
            "padding: 16px; background-color: #ffffff; font-size: 14px; line-height: 1.8; "
            "font-family: 'Georgia', 'Times New Roman', serif; text-align: justify;"
        )

        for diff in diferencas_conteudo:
            titulo_display = diff.get('secao', 'Seção')
            with st.expander(f"📄 {titulo_display} - ❌ CONTEÚDO DIVERGENTE"):
                secao_canonico = diff.get('secao', '')
                anchor_id_ref = _create_anchor_id(secao_canonico, "ref")
                anchor_id_bel = _create_anchor_id(secao_canonico, "bel")

                expander_html_ref = marcar_diferencas_palavra_por_palavra(
                    diff.get('conteudo_anvisa', ''), diff.get('conteudo_mkt', ''), eh_referencia=True
                ).replace('\n', '<br>')
                expander_html_belfar = marcar_diferencas_palavra_por_palavra(
                    diff.get('conteudo_anvisa', ''), diff.get('conteudo_mkt', ''), eh_referencia=False
                ).replace('\n', '<br>')

                clickable_style = expander_caixa_style + " cursor: pointer; transition: background-color 0.3s ease;"

                html_ref_box = f"<div onclick='window.handleBulaScroll(\"{anchor_id_ref}\", \"{anchor_id_bel}\")' style='{clickable_style}' title='Clique para ir à seção' onmouseover='this.style.backgroundColor=\"#f0f8ff\"' onmouseout='this.style.backgroundColor=\"#ffffff\"'>{expander_html_ref}</div>"
                html_bel_box = f"<div onclick='window.handleBulaScroll(\"{anchor_id_ref}\", \"{anchor_id_bel}\")' style='{clickable_style}' title='Clique para ir à seção' onmouseover='this.style.backgroundColor=\"#f0f8ff\"' onmouseout='this.style.backgroundColor=\"#ffffff\"'>{expander_html_belfar}</div>"

                c1, c2 = st.columns(2)
                with c1:
                    st.markdown("**Arquivo da Anvisa:** (Clique na caixa para rolar)")
                    st.markdown(html_ref_box, unsafe_allow_html=True)
                with c2:
                    st.markdown("**Arquivo Marketing:** (Clique na caixa para rolar)")
                    st.markdown(html_bel_box, unsafe_allow_html=True)
    else:
        st.success("✅ Conteúdo das seções está idêntico")

    if erros_ortograficos:
        st.info(f"📝 **Possíveis erros ortográficos ({len(erros_ortograficos)} palavras):**\n" + ", ".join(erros_ortograficos))

    if not any([secoes_faltantes, diferencas_conteudo, diferencas_titulos]) and len(erros_ortograficos) < 5:
        st.success("🎉 **Bula aprovada!** Nenhum problema crítico encontrado.")

    st.divider()
    st.subheader("Visualização Lado a Lado com Destaques")

    legend_style = (
        "font-size: 14px; "
        "background-color: #f0f2f6; "
        "padding: 10px 15px; "
        "border-radius: 8px; "
        "margin-bottom: 15px;"
    )

    st.markdown(
        f"<div style='{legend_style}'>"
        "<strong>Legenda:</strong> "
        "<mark style='background-color: #ffff99; padding: 2px; margin: 0 2px;'>Amarelo</mark> = Divergências | "
        "<mark style='background-color: #FFDDC1; padding: 2px; margin: 0 2px;'>Rosa</mark> = Erros ortográficos | "
        "<mark style='background-color: #cce5ff; padding: 2px; margin: 0 2px;'>Azul</mark> = Data ANVISA"
        "</div>",
        unsafe_allow_html=True
    )

    mapa_ref = mapear_secoes(texto_ref, obter_secoes_por_tipo(tipo_bula))
    mapa_belfar = mapear_secoes(texto_belfar, obter_secoes_por_tipo(tipo_bula))

    # Reformatar texto por seções detectadas (conservador: usa as seções detectadas no documento)
    try:
        texto_ref_reformatado = []
        for secao in mapa_ref:
            _, _, conteudo = obter_dados_secao(secao['canonico'], mapa_ref, texto_ref.split('\n'), tipo_bula)
            titulo = secao.get('titulo_encontrado', secao.get('canonico', ''))
            texto_ref_reformatado.append(f"{titulo}\n\n{conteudo}")
        texto_ref_reformatado = "\n\n".join(texto_ref_reformatado) if texto_ref_reformatado else texto_ref

        texto_belfar_reformatado = []
        for secao in mapa_belfar:
            _, _, conteudo = obter_dados_secao(secao['canonico'], mapa_belfar, texto_belfar.split('\n'), tipo_bula)
            titulo = secao.get('titulo_encontrado', secao.get('canonico', ''))
            texto_belfar_reformatado.append(f"{titulo}\n\n{conteudo}")
        texto_belfar_reformatado = "\n\n".join(texto_belfar_reformatado) if texto_belfar_reformatado else texto_belfar
    except Exception as e:
        st.error(f"Erro ao reformatar texto para visualização: {e}")
        texto_ref_reformatado = texto_ref
        texto_belfar_reformatado = texto_belfar

    html_ref_marcado = marcar_divergencias_html(
        texto_original=texto_ref_reformatado,
        secoes_problema=diferencas_conteudo,
        erros_ortograficos=[],
        tipo_bula=tipo_bula,
        eh_referencia=True
    ).replace('\n', '<br>')

    html_belfar_marcado = marcar_divergencias_html(
        texto_original=texto_belfar_reformatado,
        secoes_problema=diferencas_conteudo,
        erros_ortograficos=erros_ortograficos,
        tipo_bula=tipo_bula,
        eh_referencia=False
    ).replace('\n', '<br>')

    caixa_style = (
        "height: 700px; "
        "overflow-y: auto; "
        "border: 1px solid #e0e0e0; "
        "border-radius: 8px; "
        "padding: 20px 24px; "
        "background-color: #ffffff; "
        "font-size: 15px; "
        "line-height: 1.7; "
        "box-shadow: 0 4px 12px rgba(0,0,0,0.08); "
        "text-align: left; "
    )

    col1, col2 = st.columns(2, gap="medium")
    with col1:
        st.markdown(f"#### {nome_ref}")
        st.markdown(f"<div id='container-ref-scroll' style='{caixa_style}'>{html_ref_marcado}</div>", unsafe_allow_html=True)
    with col2:
        st.markdown(f"#### {nome_belfar}")
        st.markdown(f"<div id='container-bel-scroll' style='{caixa_style}'>{html_belfar_marcado}</div>", unsafe_allow_html=True)

# ----------------- INTERFACE -----------------
st.set_page_config(layout="wide", page_title="Auditoria de Bulas", page_icon="🔬")
st.title("🔬 Inteligência Artificial para Auditoria de Bulas")
st.markdown("Sistema avançado de comparação literal e validação de bulas farmacêuticas")
st.divider()

st.header("📋 Configuração da Auditoria")
tipo_bula_selecionado = st.radio("Tipo de Bula:", ("Paciente", "Profissional"), horizontal=True)
col1, col2 = st.columns(2)
with col1:
    st.subheader("📄 Arquivo da Anvisa")
    pdf_ref = st.file_uploader("Envie o arquivo da Anvisa (.docx ou .pdf)", type=["docx", "pdf"], key="ref")
with col2:
    st.subheader("📄 Arquivo Marketing")
    pdf_belfar = st.file_uploader("Envie o PDF do Marketing", type="pdf", key="belfar")

if st.button("🔍 Iniciar AuditorIA Completa", use_container_width=True, type="primary"):
    if pdf_ref and pdf_belfar:
        with st.spinner("🔄 Processando e analisando as bulas..."):
            tipo_arquivo_ref = 'docx' if pdf_ref.name.lower().endswith('.docx') else 'pdf'
            texto_ref, erro_ref = extrair_texto(pdf_ref, tipo_arquivo_ref)
            texto_belfar, erro_belfar = extrair_texto(pdf_belfar, 'pdf')

            if not erro_ref:
                # tentar truncar texto_ref até a linha da data ANVISA (correção solicitada)
                regex_anvisa_trunc = r"(?:aprovad[ao]\s+pela\s+anvisa\s+em|data\s+de\s+aprovação\s+na\s+anvisa:)\s*[\d]{1,2}/[\d]{1,2}/[\d]{2,4}"
                match = re.search(regex_anvisa_trunc, texto_ref, re.IGNORECASE)
                if match:
                    # encontra início da linha onde a data aparece e trunca até essa linha (mantendo a linha)
                    start = match.start()
                    # busca o final da linha onde aparece a data
                    end_of_line_pos = texto_ref.find('\n', start)
                    if end_of_line_pos != -1:
                        texto_ref = texto_ref[:end_of_line_pos + 1]  # mantém até o fim da linha
            if erro_ref or erro_belfar:
                st.error(f"Erro ao processar arquivos: {erro_ref or erro_belfar}")
            else:
                gerar_relatorio_final(texto_ref, texto_belfar, "Arquivo da Anvisa", "Arquivo Marketing", tipo_bula_selecionado)
    else:
        st.warning("⚠️ Por favor, envie ambos os arquivos para iniciar a auditoria.")

st.divider()
st.caption("Sistema de AuditorIA de Bulas v19.0 | OCR & Layout Fix")
