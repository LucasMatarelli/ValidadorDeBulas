#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Sistema: AuditorIA de Bulas v20.2 - Correção de Conteúdo e Mapeamento de Seções
# Objetivo: comparar bulas (Anvisa x Marketing), com OCR, reflow, detecção de seções,
# marcação de diferenças palavra-a-palavra, checagem ortográfica e visualização lado-a-lado.
#
# Observações:
# - v20.2: Refina a lógica de obtenção de dados de seção para lidar melhor com "roubo" de conteúdo
#          e seções vazias, ajustando o limite do 'token_set_ratio' para 98 no fallback.
# - Mantenha Tesseract e o modelo SpaCy instalados: `tesseract` + `pt_core_news_lg`
# - Para usar no Streamlit, salve este arquivo e execute `streamlit run seu_arquivo.py`

import re
import difflib
import unicodedata
import io
import spacy
from thefuzz import fuzz
from spellchecker import SpellChecker
import pytesseract
from PIL import Image
import fitz # PyMuPDF
import docx
import streamlit as st

# ----------------- CONFIGURAÇÃO DA PÁGINA STREAMLIT -----------------
# Deve ser a primeira chamada do Streamlit
st.set_page_config(layout="wide", page_title="Auditoria de Bulas", page_icon="🔬")

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

# ----------------- FUNÇÕES UTILITÁRIAS -----------------

def normalizar_texto(texto):
    """Remove acentos, pontuação e espaços extras."""
    if not texto:
        return ""
    # Normalização Unicode para remover acentos
    s = ''.join(c for c in unicodedata.normalize('NFD', texto)
                if unicodedata.category(c) != 'Mn')
    # Converte para minúsculas
    s = s.lower()
    # Remove pontuação e caracteres não-alfanuméricos (exceto espaço)
    s = re.sub(r'[^\w\s]', '', s)
    # Remove espaços extras (múltiplos espaços/tabs/newlines)
    s = re.sub(r'\s+', ' ', s).strip()
    return s

def normalizar_titulo_para_comparacao(titulo):
    """Normalização mais agressiva para títulos."""
    return normalizar_texto(titulo)

def is_titulo_secao(linha):
    """
    Heurística simples para identificar um provável título de seção.
    """
    if not linha:
        return False
        
    FRASES_A_IGNORAR = {
        "TODO MEDICAMENTO DEVE SER MANTIDO FORA DO ALCANCE DAS CRIANCAS",
        "SIGA CORRETAMENTE O MODO DE USAR",
        "NAO DESAPARECENDO OS SINTOMAS PROCURE ORIENTACAO MEDICA"
    }
    
    linha_norm_check = normalizar_texto(linha) 
    
    for frase in FRASES_A_IGNORAR:
        if fuzz.token_set_ratio(linha_norm_check, frase) > 95:
            return False

    if linha.isupper() and len(linha.split()) < 15:
        return True
    if linha.istitle() and len(linha.split()) < 15:
        return True
    if re.match(r'^\d+\.\s+[A-Z]', linha):
         return True
    return False

def _create_anchor_id(secao_canonico, prefix):
    """Cria um ID HTML seguro para âncoras."""
    if not secao_canonico:
        secao_canonico = "secao-desconhecida"
    norm = normalizar_texto(secao_canonico).replace(' ', '-')
    if not norm:
        norm = "secao-default"
    return f"anchor-{prefix}-{norm}"

def is_garbage_line(linha_norm):
    """Verifica (de forma normalizada) se a linha é lixo de rodapé/metadados."""
    if not linha_norm:
        return False
    GARBAGE_KEYWORDS = [
        'medida da bula', 'tipologia da bula', 'bulcloridrato', 'belfarcombr', 'artesbelfarcombr',
        'contato 31 2105', 'bul_cloridrato', 'verso medida', '190 x 300 mm', 'papel ap 56gr',
        'bula para o paciente', 'bula para profissional da saude' # Adicionado mais lixo
    ]
    for key in GARBAGE_KEYWORDS:
        if key in linha_norm:
            return True
    return False


# --- LÓGICA DE NEGÓCIO (LISTAS DE SEÇÕES) ---

def obter_secoes_por_tipo(tipo_bula):
    """Retorna a lista de seções canônicas esperadas."""
    secoes_paciente = [
        "IDENTIFICAÇÃO DO MEDICAMENTO",
        "APRESENTAÇÕES",
        "COMPOSIÇÃO",
        "PARA QUE ESTE MEDICAMENTO É INDICADO?",
        "COMO ESTE MEDICAMENTO FUNCIONA?",
        "QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?",
        "O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?",
        "ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?",
        "COMO DEVO USAR ESTE MEDICAMENTO?",
        "O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?",
        "QUAIS OS MALES QUE ESTE MEDICAMENTO PODE ME CAUSAR?",
        "O QUE FAZER SE ALGUÉM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?",
        "DIZERES LEGAIS"
    ]
    secoes_profissional = [
        "IDENTIFICAÇÃO DO MEDICAMENTO",
        "APRESENTAÇÕES",
        "COMPOSIÇÃO",
        "INDICAÇÕES",
        "RESULTADOS DE EFICÁCIA",
        "CARACTERÍSTICAS FARMACOLÓGICAS",
        "CONTRAINDICAÇÕES",
        "ADVERTÊNCIAS E PRECAUÇÕES",
        "INTERAÇÕES MEDICAMENTOSAS",
        "CUIDADOS DE ARMAZENAMENTO DO MEDICAMENTO",
        "POSOLOGIA E MODO DE USAR",
        "REAÇÕES ADVERSAS",
        "SUPERDOSE",
        "DIZERES LEGAIS"
    ]
    if tipo_bula == "Paciente":
        return secoes_paciente
    else:
        return secoes_profissional

def obter_aliases_secao():
    """Mapeia títulos alternativos para os canônicos."""
    return {
        "PARA QUÊ ESTE MEDICAMENTO É INDICADO?": "PARA QUE ESTE MEDICAMENTO É INDICADO?",
        "O QUE DEVO SABER ANTES DE USAR ESSE MEDICAMENTO?": "O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?",
        "QUAIS OS MALES QUE ESTE MEDICAMENTO PODE ME CAUSAR": "QUAIS OS MALES QUE ESTE MEDICAMENTO PODE ME CAUSAR?",
        "SUPERDOSE": "O QUE FAZER SE ALGUÉM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?",
        "REAÇÕES ADVERSAS": "QUAIS OS MALES QUE ESTE MEDICAMENTO PODE ME CAUSAR?"
        # Adicione mais aliases conforme necessário
    }

def obter_secoes_ignorar_comparacao():
    """Seções que não devem ter seu conteúdo comparado."""
    return [
        "IDENTIFICAÇÃO DO MEDICAMENTO",
        "APRESENTAÇÕES",
        "DIZERES LEGAIS"
    ]

def obter_secoes_ignorar_ortografia():
    """Seções que não devem ser checadas por ortografia (ex: nomes, endereços)."""
    return [
        "IDENTIFICAÇÃO DO MEDICAMENTO",
        "COMPOSIÇÃO",
        "DIZERES LEGAIS"
    ]

def obter_secoes_ignorar_verificacao_existencia():
    """
    Seções que são complexas (ex: cabeçalhos) e não devem ser reportadas como 'faltantes'
    se o 'mapper' falhar em encontrá-las.
    """
    return [
        "IDENTIFICAÇÃO DO MEDICAMENTO",
        "APRESENTAÇÕES",
        "COMPOSIÇÃO"
    ]


# ----------------- EXTRAÇÃO DE PDF ATUALIZADA COM OCR -----------------
def extrair_texto_pdf_com_ocr(arquivo_bytes):
    """
    Extração otimizada para PDFs de 2 colunas.
    Usa centro do bloco para decidir coluna e ordena por (y, x) dentro de cada coluna.
    Fallback para OCR com Tesseract quando necessário.
    """
    texto_direto = ""
    try:
        with fitz.open(stream=io.BytesIO(arquivo_bytes), filetype="pdf") as doc:
            for page in doc:
                blocks = page.get_text("blocks", sort=False)
                middle_x = page.rect.width / 2.0

                col1_blocks = []
                col2_blocks = []

                for b in blocks:
                    x0, y0, x1, y1, text = b[0], b[1], b[2], b[3], b[4]
                    center_x = (x0 + x1) / 2.0
                    if center_x <= middle_x:
                        col1_blocks.append((y0, x0, text))
                    else:
                        col2_blocks.append((y0, x0, text))

                col1_blocks.sort(key=lambda t: (t[0], t[1]))
                col2_blocks.sort(key=lambda t: (t[0], t[1]))

                for _, _, txt in col1_blocks:
                    texto_direto += txt + "\n"
                for _, _, txt in col2_blocks:
                    texto_direto += txt + "\n"

                texto_direto += "\n"

        if len(texto_direto.strip()) > 100:
            return texto_direto
    except Exception as e:
        try:
            with fitz.open(stream=io.BytesIO(arquivo_bytes), filetype="pdf") as doc:
                texto_alt = ""
                for page in doc:
                    texto_alt += page.get_text("text") + "\n"
                if len(texto_alt.strip()) > 100:
                    return texto_alt
        except Exception:
            pass

    st.info("Arquivo com layout complexo detectado. Iniciando OCR (tesseract)...")
    texto_ocr = ""
    with fitz.open(stream=io.BytesIO(arquivo_bytes), filetype="pdf") as doc:
        for page in doc:
            pix = page.get_pixmap(dpi=300)
            img_bytes = pix.tobytes("png")
            imagem = Image.open(io.BytesIO(img_bytes))
            texto_ocr += pytesseract.image_to_string(imagem, lang='por') + "\n"

    return texto_ocr

# ----------------- EXTRAÇÃO DE DOCX -----------------
def extrair_texto_docx(arquivo_bytes):
    """Extrai texto de arquivos .docx"""
    try:
        document = docx.Document(io.BytesIO(arquivo_bytes))
        texto_completo = []
        for para in document.paragraphs:
            texto_completo.append(para.text)
        return "\n".join(texto_completo)
    except Exception as e:
        st.error(f"Erro ao ler arquivo DOCX: {e}")
        return ""

# ----------------- FUNÇÃO DE EXTRAÇÃO PRINCIPAL -----------------
def extrair_texto(arquivo, tipo_arquivo):
    """
    Função wrapper que chama o extrator correto (.pdf ou .docx)
    Retorna (texto, erro_msg)
    """
    try:
        arquivo_bytes = arquivo.getvalue()
        if tipo_arquivo == 'pdf':
            texto = extrair_texto_pdf_com_ocr(arquivo_bytes)
            return texto, None
        elif tipo_arquivo == 'docx':
            texto = extrair_texto_docx(arquivo_bytes)
            return texto, None
        else:
            return None, f"Tipo de arquivo não suportado: {tipo_arquivo}"
    except Exception as e:
        return None, f"Erro fatal na extração: {str(e)}"

# ----------------- MAPEAR SEÇÕES -----------------
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
    while idx < len(linhas):
        linha_limpa = linhas[idx].strip()
        
        if not is_titulo_secao(linha_limpa):
            idx += 1
            continue

        best_match_score_current = 0
        best_match_canonico_current = None
        best_match_num_linhas = 0
        titulo_encontrado_raw = ""

        # Tenta matches de 3, 2 e 1 linha
        for n_linhas in [3, 2, 1]:
            if idx + n_linhas <= len(linhas):
                current_lines = [linhas[idx + k].strip() for k in range(n_linhas)]
                current_title_combo = " ".join(current_lines)

                # Heurística para evitar combinações muito longas que não seriam títulos
                if n_linhas == 3 and len(current_title_combo.split()) > 30: continue
                if n_linhas == 2 and len(current_title_combo.split()) > 20: continue
                if n_linhas == 1 and len(current_title_combo.split()) > 15: continue

                for poss, canon in titulos_possiveis.items():
                    score = fuzz.token_set_ratio(normalizar_titulo_para_comparacao(poss),
                                                 normalizar_titulo_para_comparacao(current_title_combo))
                    if score > best_match_score_current:
                        best_match_score_current = score
                        best_match_canonico_current = canon
                        best_match_num_linhas = n_linhas
                        titulo_encontrado_raw = current_title_combo

            if best_match_score_current >= 90: # Limiar para aceitar um título
                break # Se achou um bom match com N linhas, não precisa tentar N-1

        if best_match_score_current >= 90:
            if not mapa or mapa[-1]['canonico'] != best_match_canonico_current:
                mapa.append({
                    'canonico': best_match_canonico_current,
                    'titulo_encontrado': titulo_encontrado_raw,
                    'linha_inicio': idx,
                    'score': best_match_score_current,
                    'num_linhas_titulo': best_match_num_linhas
                })
            idx += best_match_num_linhas
        else:
            idx += 1

    mapa.sort(key=lambda x: x['linha_inicio'])
    return mapa

# ----------------- OBTER DADOS DA SESSÃO (NOVA VERSÃO v20.2) -----------------
def obter_dados_secao(secao_canonico, mapa_secoes, linhas_texto, tipo_bula):
    """
    Extrai conteúdo de uma seção usando preferencialmente as posições no mapa_secoes.
    Se mapa_secoes não contiver a seção, tenta heurística de busca (fallback).
    """
    titulos_lista = obter_secoes_por_tipo(tipo_bula)
    titulos_norm_set = {normalizar_titulo_para_comparacao(t) for t in titulos_lista}
    aliases = obter_aliases_secao()
    titulos_reais_possiveis = [secao_canonico] + [alias for alias, canon in aliases.items() if canon == secao_canonico]

    secao_encontrada_no_mapa = False
    titulo_detectado_no_mapa = None
    linha_inicio_conteudo = -1
    linha_fim_conteudo = -1

    # --- Tenta encontrar a seção no mapa ---
    for idx_map, secao_mapa in enumerate(mapa_secoes):
        if secao_mapa['canonico'] == secao_canonico:
            secao_encontrada_no_mapa = True
            titulo_detectado_no_mapa = secao_mapa['titulo_encontrado']
            linha_inicio_conteudo = secao_mapa['linha_inicio'] + secao_mapa.get('num_linhas_titulo', 1)

            if idx_map + 1 < len(mapa_secoes):
                linha_fim_conteudo = mapa_secoes[idx_map + 1]['linha_inicio']
            else:
                linha_fim_conteudo = len(linhas_texto)
            break

    # --- Se não encontrou no mapa, tenta fallback ---
    if not secao_encontrada_no_mapa:
        for i in range(len(linhas_texto)):
            linha_raw = linhas_texto[i].strip()
            if not linha_raw: continue

            # V20.2: Aumenta o limiar do fallback para 98 para evitar roubo de conteúdo
            score = fuzz.token_set_ratio(normalizar_titulo_para_comparacao(linha_raw),
                                         normalizar_titulo_para_comparacao(secao_canonico))
            if score >= 98: # Limiar mais alto para fallback direto
                secao_encontrada_no_mapa = True
                titulo_detectado_no_mapa = linha_raw
                linha_inicio_conteudo = i + 1

                # Tenta achar o próximo título ou o fim do documento
                for j in range(linha_inicio_conteudo, len(linhas_texto)):
                    cand_linha = linhas_texto[j].strip()
                    cand_norm_check = normalizar_texto(cand_linha)
                    if is_garbage_line(cand_norm_check):
                        linha_fim_conteudo = j
                        break
                    if is_titulo_secao(cand_linha) and \
                       any(fuzz.token_set_ratio(normalizar_titulo_para_comparacao(t), normalizar_titulo_para_comparacao(cand_linha)) > 90
                           for t in titulos_lista + list(aliases.keys())):
                        linha_fim_conteudo = j
                        break
                if linha_fim_conteudo == -1: # Se não achou próximo título, vai até o fim
                    linha_fim_conteudo = len(linhas_texto)
                break

    if not secao_encontrada_no_mapa:
        return False, None, "" # Se a seção não foi encontrada de jeito nenhum

    conteudo_lista_raw = []
    # Conteúdo na mesma linha do título (se houver)
    if titulo_detectado_no_mapa:
        # Tenta remover o título real do texto detectado para pegar só o conteúdo
        best_title_part = ""
        for real_title in sorted(titulos_reais_possiveis, key=len, reverse=True):
            if real_title.upper() in titulo_detectado_no_mapa.upper():
                best_title_part = real_title
                break
        
        if best_title_part:
            idx_start_content = titulo_detectado_no_mapa.upper().find(best_title_part.upper()) + len(best_title_part)
            conteudo_primeira_linha = titulo_detectado_no_mapa[idx_start_content:].strip()
            conteudo_primeira_linha = re.sub(r'^[?:.]\s*', '', conteudo_primeira_linha).strip()
            if conteudo_primeira_linha:
                conteudo_lista_raw.append(conteudo_primeira_linha)

    # Conteúdo das linhas seguintes
    if linha_inicio_conteudo != -1 and linha_fim_conteudo != -1:
        for k in range(linha_inicio_conteudo, linha_fim_conteudo):
            linha = linhas_texto[k].strip()
            if not linha: continue # Ignora linhas vazias na coleta bruta

            # V20.2: Aplica filtro de lixo de rodapé no meio do conteúdo também
            if is_garbage_line(normalizar_texto(linha)):
                break 
            
            conteudo_lista_raw.append(linha)

    # Reflow e limpeza do conteúdo
    if not conteudo_lista_raw:
        return True, titulo_detectado_no_mapa or secao_canonico, "" # Retorna vazio se não tiver conteúdo

    conteudo_refluxo = [conteudo_lista_raw[0]]
    for k in range(1, len(conteudo_lista_raw)):
        prev = conteudo_refluxo[-1]
        cur = conteudo_lista_raw[k]
        cur_strip = cur.strip()

        is_new_para = False
        if not cur_strip:
            is_new_para = True
        else:
            first_char = cur_strip[0]
            if first_char.isupper() or first_char in '“"' or re.match(r'^[\d\-\*•]', cur_strip):
                is_new_para = True

        end_sentence = bool(re.search(r'[.!?:]$', prev.strip()))
        if not is_new_para and not end_sentence:
            conteudo_refluxo[-1] = prev.rstrip() + " " + cur.lstrip()
        else:
            conteudo_refluxo.append(cur)

    conteudo_final = "\n".join(conteudo_refluxo).strip()
    conteudo_final = re.sub(r'\s+([.,;:!?)\]])', r'\1', conteudo_final)
    conteudo_final = re.sub(r'([(\[])\s+', r'\1', conteudo_final)
    conteudo_final = re.sub(r'([.,;:!?)\]])(\w)', r'\1 \2', conteudo_final)
    conteudo_final = re.sub(r'(\w)([(\[])', r'\1 \2', conteudo_final)

    return True, titulo_detectado_no_mapa or secao_canonico, conteudo_final


# ----------------- COMPARAÇÃO DE CONTEÚDO -----------------
def verificar_secoes_e_conteudo(texto_anvisa, texto_mkt, tipo_bula):
    secoes_esperadas = obter_secoes_por_tipo(tipo_bula)
    secoes_faltantes, diferencas_conteudo, similaridades_secoes, diferencas_titulos = [], [], [], []
    secoes_ignorar_upper = [s.upper() for s in obter_secoes_ignorar_comparacao()]
    secoes_ignorar_existencia_upper = [s.upper() for s in obter_secoes_ignorar_verificacao_existencia()]

    linhas_anvisa = texto_anvisa.split('\n')
    linhas_mkt = texto_mkt.split('\n')
    mapa_anvisa = mapear_secoes(texto_anvisa, secoes_esperadas)
    mapa_mkt = mapear_secoes(texto_mkt, secoes_esperadas)

    for secao in secoes_esperadas:
    
        checar_existencia = secao.upper() not in secoes_ignorar_existencia_upper
    
        # A função 'obter_dados_secao' agora está mais robusta
        encontrou_anvisa, _, conteudo_anvisa = obter_dados_secao(secao, mapa_anvisa, linhas_anvisa, tipo_bula)
        encontrou_mkt, titulo_mkt, conteudo_mkt = obter_dados_secao(secao, mapa_mkt, linhas_mkt, tipo_bula)

        if not encontrou_mkt:
            if checar_existencia: 
                secoes_faltantes.append(secao)
            continue

        if encontrou_anvisa:
            secao_comp = normalizar_titulo_para_comparacao(secao)
            titulo_mkt_comp = normalizar_titulo_para_comparacao(titulo_mkt or "")
            
            if secao_comp != titulo_mkt_comp:
                if not any(d['secao_esperada'] == secao for d in diferencas_titulos):
                    diferencas_titulos.append({'secao_esperada': secao, 'titulo_encontrado': titulo_mkt})

            if secao.upper() in secoes_ignorar_upper:
                continue

            if normalizar_texto(conteudo_anvisa) != normalizar_texto(conteudo_mkt):
                diferencas_conteudo.append({
                    'secao': secao,
                    'conteudo_anvisa': conteudo_anvisa,
                    'conteudo_mkt': conteudo_mkt,
                    'titulo_encontrado': titulo_mkt
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

        try:
            spell.word_frequency.load_words(list(vocab_referencia.union(entidades).union(palavras_a_ignorar)))
        except Exception:
            for w in vocab_referencia.union(entidades).union(palavras_a_ignorar):
                try:
                    spell.word_frequency.add(w)
                except Exception:
                    pass

        palavras = re.findall(r'\b[a-záéíóúâêôãõçü]+\b', texto_final_para_checar.lower())
        erros = spell.unknown(palavras)
        erros_filtrados = sorted(set([e for e in erros if len(e) > 3]))
        return erros_filtrados[:20]

    except Exception:
        return []

# ----------------- DIFERENÇAS PALAVRA A PALAVRA -----------------
def marcar_diferencas_palavra_por_palavra(texto_ref, texto_belfar, eh_referencia):
    def tokenizar(txt):
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
            
            try:
                texto_trabalho = texto_trabalho.replace(conteudo_a_substituir, conteudo_com_ancora, 1)
            except re.error:
                pass

    if erros_ortograficos and not eh_referencia:
        for erro in erros_ortograficos:
            pattern = r'(?<![<>A-Za-z0-9])\b(' + re.escape(erro) + r')\b(?![<>A-Za-z0-9])'
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
        texto_trabalho = texto_trabalho.replace(frase_anvisa, f"<mark style='background-color: #cce5ff; padding: 2px; font-weight: 500;'>{frase_anvisa}</mark>", 1)

    return texto_trabalho

# ----------------- RELATÓRIO -----------------
def gerar_relatorio_final(texto_ref, texto_belfar, nome_ref, nome_belfar, tipo_bula):
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

    st.header("Relatório de AuditorIA Inteligente")
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
        st.success("✅ Nenhuma seção obrigatória faltando.")

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

    try:
        texto_ref_reformatado_lista = []
        for secao_canon in obter_secoes_por_tipo(tipo_bula):
            encontrou, titulo_real, conteudo = obter_dados_secao(secao_canon, mapa_ref, texto_ref.split('\n'), tipo_bula)
            if encontrou:
                texto_ref_reformatado_lista.append(f"<strong>{titulo_real}</strong>\n{conteudo}")
        
        texto_ref_reformatado = "\n\n".join(texto_ref_reformatado_lista) if texto_ref_reformatado_lista else texto_ref

        texto_belfar_reformatado_lista = []
        for secao_canon in obter_secoes_por_tipo(tipo_bula):
            encontrou, titulo_real, conteudo = obter_dados_secao(secao_canon, mapa_belfar, texto_belfar.split('\n'), tipo_bula)
            if encontrou:
                texto_belfar_reformatado_lista.append(f"<strong>{titulo_real}</strong>\n{conteudo}")
        
        texto_belfar_reformatado = "\n\n".join(texto_belfar_reformatado_lista) if texto_belfar_reformatado_lista else texto_belfar

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
st.title("🔬 Inteligência Artificial para Auditoria de Bulas")
st.markdown("Sistema avançado de comparação literal e validação de bulas farmacêuticas")
st.divider()

st.header("📋 Configuração da AuditorIA")
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

            if not erro_ref and texto_ref:
                regex_anvisa_trunc = r"(?:aprovad[ao]\s+pela\s+anvisa\s+em|data\s+de\s+aprovação\s+na\s+anvisa:)\s*[\d]{1,2}/[\d]{1,2}/[\d]{2,4}"
                match = re.search(regex_anvisa_trunc, texto_ref, re.IGNORECASE)
                if match:
                    start = match.start()
                    end_of_line_pos = texto_ref.find('\n', start)
                    if end_of_line_pos != -1:
                        texto_ref = texto_ref[:end_of_line_pos + 1]
            
            if erro_ref or erro_belfar:
                st.error(f"Erro ao processar arquivos: {erro_ref or erro_belfar}")
            elif not texto_ref or not texto_belfar:
                 st.error("Erro: Um dos arquivos não pôde ser lido ou está vazio.")
            else:
                gerar_relatorio_final(texto_ref, texto_belfar, "Arquivo da Anvisa", "Arquivo Marketing", tipo_bula_selecionado)
    else:
        st.warning("⚠️ Por favor, envie ambos os arquivos para iniciar a auditoria.")

st.divider()
st.caption("Sistema de AuditorIA de Bulas v20.2 | Correção de Conteúdo e Mapeamento de Seções")
