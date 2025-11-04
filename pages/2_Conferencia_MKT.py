#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Sistema: AuditorIA de Bulas v20.9 - Prioridade de Extração
# Objetivo: comparar bulas (Anvisa x Marketing), com OCR, reflow, detecção de seções,
# marcação de diferenças palavra-a-palavra, checagem ortográfica e visualização lado-a-lado.
#
# Observações:
# - v20.9:
#   1. Re-prioriza os métodos de extração em `extrair_texto_pdf_com_ocr`.
#   2. Tenta "Modo Blocks" (manual 2 colunas) PRIMEIRO, pois é mais robusto
#      para layouts simples de 2 colunas.
#   3. O "Modo Layout" (automático) vira a Tentativa 2 (Plano B).
#   4. OCR (Tesseract) continua como Tentativa 3 (Plano C).
#   5. Isso corrige PDFs com camadas de texto corrompidas que enganavam o "Modo Layout".
#
# - Mantenha Tesseract e o modelo SpaCy instalados: tesseract + pt_core_news_lg
# - Para usar no Streamlit, salve este arquivo e execute streamlit run seu_arquivo.py

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

# ----------------- FUNÇÕES UTILITÁRIAS (ADICIONADAS) -----------------

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

# ***** FUNÇÃO CORRIGIDA (v20.4) *****
def is_titulo_secao(linha):
    """
    Heurística simples para identificar um provável título de seção.
    v20.4: Melhoria na detecção de "Não-Títulos" (frases de aviso)
    """
    if not linha:
        return False
        
    # --- INÍCIO DA CORREÇÃO v20.4 ---
    # Lista de frases em CAIXA ALTA que NÃO são títulos
    FRASES_A_IGNORAR = {
        "todo medicamento deve ser mantido fora do alcance das criancas", # Normalizado
        "siga corretamente o modo de usar",
        "nao desaparecendo os sintomas procure orientacao medica", # Normalizado
        "em caso de duvidas procure orientacao do farmaceutico" # Adicionado
    }
    
    # Normaliza a linha para checagem (remove acentos, pontuação, etc.)
    linha_norm_check = normalizar_texto(linha) 
    if not linha_norm_check:
        return False
    
    for frase in FRASES_A_IGNORAR:
        # v20.4: Checa se a linha normalizada é um *subconjunto* da frase a ignorar
        # Isso captura linhas quebradas como "TODO MEDICAMENTO DEVE SER MANTIDO"
        if linha_norm_check in frase:
            return False
        # Mantém a checagem de similaridade para casos onde a linha é
        # um pouco diferente mas muito parecida (ex: com 'o' extra)
        if fuzz.token_set_ratio(linha_norm_check, frase) > 95:
            return False
    # --- FIM DA CORREÇÃO v20.4 ---

    # Se for tudo maiúsculo e curto (menos de 15 palavras)
    if linha.isupper() and len(linha.split()) < 15:
        return True
    # Se for Título Capitalizado e curto
    if linha.istitle() and len(linha.split()) < 15:
        return True
    
    # --- INÍCIO DA CORREÇÃO v20.4 (Regex) ---
    # Se tiver um padrão "1. NOME DA SEÇÃO" (agora aceita maiúscula/minúscula)
    if re.match(r'^\d+\.\s+[A-Za-z]', linha):
         return True
    # --- FIM DA CORREÇÃO v20.4 ---
    
    return False

def _create_anchor_id(secao_canonico, prefix):
    """Cria um ID HTML seguro para âncoras."""
    if not secao_canonico:
        secao_canonico = "secao-desconhecida"
    # v20.5: Remove o número inicial (ex: "1. ") para o ID
    secao_limpa = re.sub(r'^\d+\.\s*', '', secao_canonico)
    norm = normalizar_texto(secao_limpa).replace(' ', '-')
    # Garante que não está vazio
    if not norm:
        norm = "secao-default"
    return f"anchor-{prefix}-{norm}"

# --- INÍCIO DA CORREÇÃO v20.8 (Anti-Lixo) ---
def is_garbage_line(linha_norm):
    """Verifica (de forma normalizada) se a linha é lixo de rodapé/metadados."""
    if not linha_norm:
        return False
    GARBAGE_KEYWORDS = [
        'medida da bula', 'tipologia da bula', 'bulcloridrato', 'belfarcombr', 'artesbelfarcombr',
        'contato 31 2105', 'bul_cloridrato', 'verso medida', '190 x 300 mm', 'papel ap 56gr',
        '15000 mm', '21000 mm', 'frente', 'verso', # Adicionado v20.5 para robustez
        'bul 22149v01', 'bula padrao',
        'cor preta normal e negrito corpo 10' # Adicionado v20.8
    ]
    for key in GARBAGE_KEYWORDS:
        if key in linha_norm:
            return True
    return False
# --- FIM DA CORREÇÃO v20.8 ---


# --- LÓGICA DE NEGÓCIO (LISTAS DE SEÇÕES) (v20.5) ---
# !!! IMPORTANTE: Listas atualizadas conforme solicitação (início da numeração em 1) !!!

def obter_secoes_por_tipo(tipo_bula):
    """Retorna a lista de seções canônicas esperadas (v20.5)."""
    # --- INÍCIO DA ATUALIZAÇÃO v20.5 ---
    secoes_paciente = [
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
    ]
    secoes_profissional = [
        " APRESENTAÇÕES", # Mantido espaço inicial conforme solicitado
        " COMPOSIÇÃO", # Mantido espaço inicial conforme solicitado
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
    # --- FIM DA ATUALIZAÇÃO v20.5 ---
    
    if tipo_bula == "Paciente":
        return secoes_paciente
    else:
        return secoes_profissional

def obter_aliases_secao():
    """
    Mapeia títulos alternativos para os canônicos (agora numerados v20.5).
    Mapeamentos conflitantes (SUPERDOSE, REAÇÕES ADVERSAS)
    são tratados dinamicamente em 'mapear_secoes' e 'obter_dados_secao'
    """
    # --- INÍCIO DA ATUALIZAÇÃO v20.5 ---
    return {
        # --- Aliases Paciente ---
        "PARA QUÊ ESTE MEDICAMENTO É INDICADO?": "1. PARA QUE ESTE MEDICAMENTO É INDICADO?",
        "O QUE DEVO SABER ANTES DE USAR ESSE MEDICAMENTO?": "4. O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?",
        "QUAIS OS MALES QUE ESTE MEDICAMENTO PODE ME CAUSAR": "8. QUAIS OS MALES QUE ESTE MEDICAMENTO PODE ME CAUSAR?",
        
        # --- Aliases Profissional ---
        "INDICAÇÕES": "1. INDICAÇÕES", # Conflita com 'PARA QUE...' mas OK
        "ADVERTÊNCIAS": "5. ADVERTÊNCIAS E PRECAUÇÕES",
        "POSOLOGIA": "8. POSOLOGIA E MODO DE USAR",
        
        # Aliases conflitantes (ex: SUPERDOSE, REAÇÕES ADVERSAS) serão tratados dinamicamente
    }
    # --- FIM DA ATUALIZAÇÃO v20.5 ---

def obter_secoes_ignorar_comparacao():
    """Seções que não devem ter seu conteúdo comparado (v20.5)."""
    # --- INÍCIO DA ATUALIZAÇÃO v20.5 ---
    return [
        "APRESENTAÇÕES",
        " APRESENTAÇÕES", # Versão profissional (com espaço)
        "DIZERES LEGAIS"
    ]
    # --- FIM DA ATUALIZAÇÃO v20.5 ---

def obter_secoes_ignorar_ortografia():
    """Seções que não devem ser checadas por ortografia (v20.5)."""
    # --- INÍCIO DA ATUALIZAÇÃO v20.5 ---
    return [
        "COMPOSIÇÃO",
        " COMPOSIÇÃO", # Versão profissional (com espaço)
        "DIZERES LEGAIS"
    ]
    # --- FIM DA ATUALIZAÇÃO v20.5 ---

def obter_secoes_ignorar_verificacao_existencia():
    """
    Seções complexas que não devem ser reportadas como 'faltantes' (v20.5).
    """
    # --- INÍCIO DA ATUALIZAÇÃO v20.5 ---
    return [
        "APRESENTAÇÕES",
        " APRESENTAÇÕES",
        "COMPOSIÇÃO",
        " COMPOSIÇÃO"
    ]
    # --- FIM DA ATUALIZAÇÃO v20.5 ---


# ----------------- EXTRAÇÃO DE PDF (MELHORIA v20.9) -----------------
def extrair_texto_pdf_com_ocr(arquivo_bytes):
    """
    Extração em 3 etapas (v20.9 - Prioridade Corrigida):
    1. Tenta extração com 'blocks' (lógica manual de 2 colunas).
    2. Tenta extração com 'layout' (ótimo para colunas complexas).
    3. Tenta OCR (Tesseract) como último recurso.
    """
    
    # --- Tentativa 1: Modo "Blocks" (Lógica manual de 2 colunas) ---
    texto_direto = ""
    try:
        with fitz.open(stream=io.BytesIO(arquivo_bytes), filetype="pdf") as doc:
            for page in doc:
                blocks = page.get_text("blocks", sort=False)  # (x0,y0,x1,y1,"text", ...)
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

                texto_direto += "\n"  # quebra de página

        if len(texto_direto.strip()) > 100:
            return texto_direto
    except Exception as e:
        pass # Falha, tenta o próximo método

    # --- Tentativa 2: Modo Layout (Bom para colunas complexas) ---
    texto_layout = ""
    try:
        with fitz.open(stream=io.BytesIO(arquivo_bytes), filetype="pdf") as doc:
            for page in doc:
                # flags=fitz.TEXTFLAGS_LAYOUT tenta preservar o layout, inclusive colunas
                texto_layout += page.get_text("text", flags=fitz.TEXTFLAGS_LAYOUT) + "\n"
        
        if len(texto_layout.strip()) > 200: # Limiar razoável
            return texto_layout
    except Exception as e:
        pass # Falha, tenta o próximo método

    # --- Tentativa 3: Fallback OCR ---
    st.info("Arquivo com layout complexo ou camada de texto corrompida. Iniciando OCR (tesseract)...")
    texto_ocr = ""
    try:
        with fitz.open(stream=io.BytesIO(arquivo_bytes), filetype="pdf") as doc:
            for page in doc:
                pix = page.get_pixmap(dpi=300)
                img_bytes = pix.tobytes("png")
                imagem = Image.open(io.BytesIO(img_bytes))
                texto_ocr += pytesseract.image_to_string(imagem, lang='por') + "\n"
    except Exception as e_ocr:
        st.error(f"Falha no OCR: {e_ocr}")
        return texto_ocr # Retorna o que conseguiu (pode ser vazio)

    return texto_ocr
# --- FIM DA MELHORIA v20.9 ---

# ----------------- EXTRAÇÃO DE DOCX (ADICIONADA) -----------------
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

# ----------------- FUNÇÃO DE EXTRAÇÃO PRINCIPAL (ADICIONADA) -----------------
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

# ----------------- MAPEAR SEÇÕES (AJUSTES v20.7 - 'Greedy' Inteligente) -----------------
def mapear_secoes(texto_completo, secoes_esperadas, tipo_bula):
    """
    v20.7: Mapeamento "Greedy" (ganancioso) INTELIGENTE.
    Corrige bug v20.6. Só combina linhas se a linha SEGUINTE
    também parecer um título (via 'is_titulo_secao').
    Impede que o mapeador "coma" o conteúdo da seção.
    """
    mapa = []
    linhas = texto_completo.split('\n')
    
    aliases = obter_aliases_secao()
    # --- INÍCIO DA CORREÇÃO v20.5 (Aliases Dinâmicos) ---
    if tipo_bula == "Paciente":
        aliases["REAÇÕES ADVERSAS"] = "8. QUAIS OS MALES QUE ESTE MEDICAMENTO PODE ME CAUSAR?"
        aliases["SUPERDOSE"] = "9. O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?"
    else: # Profissional
        aliases["REAÇÕES ADVERSAS"] = "9. REAÇÕES ADVERSAS"
        aliases["SUPERDOSE"] = "10. SUPERDOSE"
    # --- FIM DA CORREÇÃO v20.5 ---

    titulos_possiveis = {}
    for secao in secoes_esperadas:
        titulos_possiveis[secao] = secao
    for alias, canonico in aliases.items():
        if canonico in secoes_esperadas:
            titulos_possiveis[alias] = canonico

    idx = 0
    while idx < len(linhas):
        linha_limpa = linhas[idx].strip()
        
        # v20.4: 'is_titulo_secao' agora está mais inteligente
        if not is_titulo_secao(linha_limpa):
            idx += 1
            continue

        # --- INÍCIO DA LÓGICA 'Greedy' v20.7 ---
        
        current_title_lines = [linha_limpa]
        current_title_full = linha_limpa
        current_title_norm = normalizar_titulo_para_comparacao(current_title_full)
        
        best_score = 0
        best_canonico = None
        
        # Checa o score da primeira linha
        for poss, canon in titulos_possiveis.items():
            score = fuzz.token_set_ratio(normalizar_titulo_para_comparacao(poss),
                                         current_title_norm)
            if score > best_score:
                best_score = score
                best_canonico = canon

        best_titulo_encontrado = current_title_full
        best_line_count = 1

        # Loop 'Greedy': Tenta adicionar mais linhas (até 4 adicionais)
        for i in range(1, 5): # Começa de 1 (próxima linha)
            next_line_idx = idx + i
            if next_line_idx >= len(linhas):
                break
                
            linha_seguinte = linhas[next_line_idx].strip()

            # --- CORREÇÃO v20.7 ---
            # Se a próxima linha NÃO parecer um título, PARE.
            if not is_titulo_secao(linha_seguinte):
                break
            # --- FIM DA CORREÇÃO v20.7 ---

            # Se passou, é um fragmento de título. Adicione-o.
            current_title_lines.append(linha_seguinte)
            current_title_full = " ".join(current_title_lines)
            current_title_norm = normalizar_titulo_para_comparacao(current_title_full)

            # Compara o título combinado (2, 3... 5 linhas)
            for poss, canon in titulos_possiveis.items():
                score = fuzz.token_set_ratio(normalizar_titulo_para_comparacao(poss),
                                             current_title_norm)
                
                # Se o score for melhor, salva este como o 'melhor'
                if score > best_score:
                    best_score = score
                    best_canonico = canon
                    best_titulo_encontrado = current_title_full
                    best_line_count = i + 1

        limiar_score = 85 

        # Se o melhor score encontrado (em até 5 linhas) for bom o suficiente
        if best_score >= limiar_score:
            # Evita adicionar a mesma seção duas vezes
            if not mapa or mapa[-1]['canonico'] != best_canonico:
                mapa.append({
                    'canonico': best_canonico, 
                    'titulo_encontrado': best_titulo_encontrado, 
                    'linha_inicio': idx, 
                    'score': best_score, 
                    'num_linhas_titulo': best_line_count
                })
            idx += best_line_count # Pula o número de linhas que formaram o título
        else:
            idx += 1 # Não achou match, avança 1 linha
        # --- FIM DA LÓGICA 'Greedy' v20.7 ---

    mapa.sort(key=lambda x: x['linha_inicio'])
    return mapa

# ----------------- OBTER DADOS DA SESSÃO (USANDO MAPA_SECOES QUANDO POSSÍVEL) -----------------
# ***** FUNÇÃO CORRIGIDA (v20.5) *****
def obter_dados_secao(secao_canonico, mapa_secoes, linhas_texto, tipo_bula):
    """
    Extrai conteúdo de uma seção usando preferencialmente as posições no mapa_secoes.
    Se mapa_secoes não contiver a seção, tenta heurística de busca (fallback).
    
    v20.5: Atualizado para nova numeração e correção de 'continue'
    """
    titulos_lista = obter_secoes_por_tipo(tipo_bula)
    titulos_norm_set = {normalizar_titulo_para_comparacao(t) for t in titulos_lista}
    
    aliases = obter_aliases_secao()
    # --- INÍCIO DA CORREÇÃO v20.5 (Aliases Dinâmicos) ---
    if tipo_bula == "Paciente":
        aliases["REAÇÕES ADVERSAS"] = "8. QUAIS OS MALES QUE ESTE MEDICAMENTO PODE ME CAUSAR?"
        aliases["SUPERDOSE"] = "9. O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?"
    else: # Profissional
        aliases["REAÇÕES ADVERSAS"] = "9. REAÇÕES ADVERSAS"
        aliases["SUPERDOSE"] = "10. SUPERDOSE"
    # --- FIM DA CORREÇÃO v20.5 ---

    # Lista de todos os textos possíveis para este título (canônico + aliases)
    titulos_reais_possiveis = [secao_canonico] + [alias for alias, canon in aliases.items() if canon == secao_canonico]

    # --- LÓGICA PRINCIPAL (USANDO O MAPA) ---
    for idx_map, secao_mapa in enumerate(mapa_secoes):
        if secao_mapa['canonico'] != secao_canonico:
            continue

        linha_inicio = secao_mapa['linha_inicio']
        num_linhas_titulo = secao_mapa.get('num_linhas_titulo', 1)
        
        # 1. Pega o "título" completo que o mapper encontrou
        titulo_raw_completo_detectado = secao_mapa['titulo_encontrado']
        
        # 2. Encontra o melhor (mais longo) alias/título canônico dentro do texto detectado
        best_real_title_match = None
        # v20.4: Adiciona o título canônico (numerado) à lista de busca
        titulos_reais_possiveis_com_canonico = sorted(list(set(titulos_reais_possiveis + [secao_canonico])), key=len, reverse=True)
        
        for title_text in titulos_reais_possiveis_com_canonico:
            index = titulo_raw_completo_detectado.upper().find(title_text.upper())
            if index != -1:
                best_real_title_match = titulo_raw_completo_detectado[index : index + len(title_text)]
                break
        
        conteudo_mesma_linha = ""
        titulo_encontrado_final = secao_mapa['titulo_encontrado']
        
        if best_real_title_match:
            # Divide o texto
            index_fim_titulo = titulo_raw_completo_detectado.upper().find(best_real_title_match.upper()) + len(best_real_title_match)
            titulo_encontrado_final = titulo_raw_completo_detectado[:index_fim_titulo].strip()
            conteudo_mesma_linha = titulo_raw_completo_detectado[index_fim_titulo:]
            # Limpa caracteres iniciais
            conteudo_mesma_linha = re.sub(r'^[?:.]\s*', '', conteudo_mesma_linha.strip()).strip()
        
        # Pega as linhas seguintes
        linha_inicio_conteudo_seguinte = linha_inicio + num_linhas_titulo
        
        # v20.3: Melhoria na detecção do fim da seção
        if idx_map + 1 < len(mapa_secoes):
            linha_fim = mapa_secoes[idx_map + 1]['linha_inicio']
        else:
            linha_fim = len(linhas_texto)

        # Monta o conteúdo
        conteudo = []
        if conteudo_mesma_linha:
            conteudo.append(conteudo_mesma_linha)
            
        # v20.3: Coleta todas as linhas até o próximo título, com melhor filtragem
        if linha_inicio_conteudo_seguinte < linha_fim:
            for i in range(linha_inicio_conteudo_seguinte, linha_fim):
                linha = linhas_texto[i]
                linha_norm = normalizar_texto(linha)
                
                # --- INÍCIO DA CORREÇÃO v20.8 (Bug Seção Branca / Lixo) ---
                # Para se encontrar lixo (metadata, rodapé)
                if is_garbage_line(linha_norm):
                    continue # Pula a linha de lixo e continua
                # --- FIM DA CORREÇÃO v20.8 ---
                        
                # v20.4: Melhoria - para se a linha for um título de outra seção
                # (proteção adicional contra vazamento de conteúdo)
                # 'is_titulo_secao' agora é mais inteligente e ignora frases de aviso
                if is_titulo_secao(linha.strip()):
                    # Verifica se realmente é um título conhecido
                    eh_titulo_conhecido = False
                    for t_norm in titulos_norm_set:
                        # Compara a linha com os títulos normalizados
                        if fuzz.token_set_ratio(normalizar_titulo_para_comparacao(linha.strip()), t_norm) > 85:
                            eh_titulo_conhecido = True
                            break
                    if eh_titulo_conhecido:
                        break
                
                conteudo.append(linha)
        elif not conteudo_mesma_linha:
            return True, titulo_encontrado_final, ""

        # Reflow (junta linhas que pertencem ao mesmo parágrafo)
        if not conteudo:
            return True, titulo_encontrado_final, ""

        # v20.6: Se o conteúdo for apenas linhas em branco, retorna vazio
        if all(not line.strip() for line in conteudo):
             return True, titulo_encontrado_final, ""

        conteudo_refluxo = [conteudo[0]]
        for k in range(1, len(conteudo)):
            prev = conteudo_refluxo[-1]
            cur = conteudo[k]
            cur_strip = cur.strip()

            # Heurística para novo parágrafo
            is_new_para = False
            if not cur_strip:
                is_new_para = True
            else:
                first_char = cur_strip[0]
                if first_char.isupper() or first_char in '""' or re.match(r'^[\d\-\*•]', cur_strip):
                    is_new_para = True

            end_sentence = bool(re.search(r'[.!?:]$', prev.strip()))
            if not is_new_para and not end_sentence:
                conteudo_refluxo[-1] = prev.rstrip() + " " + cur.lstrip()
            else:
                conteudo_refluxo.append(cur)

        conteudo_final = "\n".join(conteudo_refluxo).strip()

        # Limpeza de espaços com pontuação
        conteudo_final = re.sub(r'\s+([.,;:!?)\]])', r'\1', conteudo_final)
        conteudo_final = re.sub(r'([(\[])\s+', r'\1', conteudo_final)
        conteudo_final = re.sub(r'([.,;:!?)\]])(\w)', r'\1 \2', conteudo_final)
        conteudo_final = re.sub(r'(\w)([(\[])', r'\1 \2', conteudo_final)

        return True, titulo_encontrado_final, conteudo_final

    # --- LÓGICA DE FALLBACK (SE NÃO ACHOU NO MAPA) ---
    # v20.3: Melhorias no fallback para garantir que encontra o conteúdo
    
    for i in range(len(linhas_texto)):
        linha_raw = linhas_texto[i].strip()
        if not linha_raw: 
            continue

        # Se esta linha já foi mapeada para OUTRA seção, PULE
        linha_ja_mapeada = False
        for m in mapa_secoes:
            if m['linha_inicio'] == i:
                linha_ja_mapeada = True
                break
        if linha_ja_mapeada:
            continue

        # Compara a linha inteira normalizada
        linha_norm = normalizar_titulo_para_comparacao(linha_raw)
        secao_canon_norm = normalizar_titulo_para_comparacao(secao_canonico)
        
        # v20.3: Usa dois critérios - token_set_ratio E ratio simples
        score_token = fuzz.token_set_ratio(linha_norm, secao_canon_norm)
        score_ratio = fuzz.ratio(linha_norm, secao_canon_norm)
        
        # Aceita se pelo menos um score for alto
        limiar_alto = 98
        limiar_medio = 90
        
        match_encontrado = (score_token >= limiar_alto) or (score_ratio >= limiar_alto) or \
                           (score_token >= limiar_medio and score_ratio >= limiar_medio)
        
        if match_encontrado:
            # Encontrou! Agora divide a linha
            best_real_title_match = None
            # v20.4: Adiciona o canônico na busca do fallback
            titulos_reais_possiveis_com_canonico = sorted(list(set(titulos_reais_possiveis + [secao_canonico])), key=len, reverse=True)
            for title_text in titulos_reais_possiveis_com_canonico:
                index = linha_raw.upper().find(title_text.upper())
                if index != -1:
                    best_real_title_match = linha_raw[index : index + len(title_text)]
                    break
            
            if not best_real_title_match:
                best_real_title_match = linha_raw
            
            index_fim_titulo = linha_raw.upper().find(best_real_title_match.upper()) + len(best_real_title_match)
            titulo_encontrado_final = linha_raw[:index_fim_titulo].strip()
            conteudo_mesma_linha = linha_raw[index_fim_titulo:]
            conteudo_mesma_linha = re.sub(r'^[?:.]\s*', '', conteudo_mesma_linha.strip()).strip()

            # Procura próximo título ou fim
            inicio_linhas_seguintes = i + 1
            fim = len(linhas_texto)
            
            for j in range(inicio_linhas_seguintes, len(linhas_texto)):
                cand = linhas_texto[j].strip()
                cand_norm_check = normalizar_texto(cand)

                # --- INÍCIO DA CORREÇÃO v20.8 (Bug Seção Branca / Lixo) ---
                # Para se encontrar lixo
                if is_garbage_line(cand_norm_check):
                    continue # Pula a linha de lixo e continua
                # --- FIM DA CORREÇÃO v20.8 ---
                
                # v20.4: Para se encontrar outro título de seção (usando 'is_titulo_secao' melhorado)
                if is_titulo_secao(cand):
                    cand_norm = normalizar_titulo_para_comparacao(cand)
                    # Verifica com todos os títulos conhecidos
                    for t_norm in titulos_norm_set:
                        if fuzz.token_set_ratio(t_norm, cand_norm) > 85:
                            fim = j
                            break
                    if fim == j:  # Se já achou o fim, para o loop externo também
                        break
            
            conteudo_linhas_seguintes = linhas_texto[inicio_linhas_seguintes:fim]
            
            conteudo_final_lista = []
            if conteudo_mesma_linha:
                conteudo_final_lista.append(conteudo_mesma_linha)
            conteudo_final_lista.extend(conteudo_linhas_seguintes)
            
            # v20.3: Aplica reflow mesmo no fallback
            if conteudo_final_lista:
                # v20.6: Se o conteúdo for apenas linhas em branco, retorna vazio
                if all(not line.strip() for line in conteudo_final_lista):
                    return True, titulo_encontrado_final, ""
                    
                conteudo_refluxo = [conteudo_final_lista[0]]
                for k in range(1, len(conteudo_final_lista)):
                    prev = conteudo_refluxo[-1]
                    cur = conteudo_final_lista[k]
                    cur_strip = cur.strip()

                    is_new_para = False
                    if not cur_strip:
                        is_new_para = True
                    else:
                        first_char = cur_strip[0]
                        if first_char.isupper() or first_char in '""' or re.match(r'^[\d\-\*•]', cur_strip):
                            is_new_para = True

                    end_sentence = bool(re.search(r'[.!?:]$', prev.strip()))
                    if not is_new_para and not end_sentence:
                        conteudo_refluxo[-1] = prev.rstrip() + " " + cur.lstrip()
                    else:
                        conteudo_refluxo.append(cur)
                
                conteudo = "\n".join(conteudo_refluxo).strip()
            else:
                conteudo = "\n".join(conteudo_final_lista).strip()
            
            return True, titulo_encontrado_final, conteudo

    return False, None, ""

# ----------------- COMPARAÇÃO DE CONTEÚDO -----------------
# ***** FUNÇÃO ATUALIZADA (v20.5) *****
def verificar_secoes_e_conteudo(texto_anvisa, texto_mkt, tipo_bula):
    secoes_esperadas = obter_secoes_por_tipo(tipo_bula)
    secoes_faltantes, diferencas_conteudo, similaridades_secoes, diferencas_titulos = [], [], [], []
    # v20.5: Atualiza listas de ignorar para usar as novas funções (com nova numeração)
    secoes_ignorar_upper = [normalizar_titulo_para_comparacao(s) for s in obter_secoes_ignorar_comparacao()]
    secoes_ignorar_existencia_upper = [normalizar_titulo_para_comparacao(s) for s in obter_secoes_ignorar_verificacao_existencia()]

    linhas_anvisa = texto_anvisa.split('\n')
    linhas_mkt = texto_mkt.split('\n')
    # v20.7: Passa 'tipo_bula' para o 'mapear_secoes' (que agora é greedy inteligente)
    mapa_anvisa = mapear_secoes(texto_anvisa, secoes_esperadas, tipo_bula)
    mapa_mkt = mapear_secoes(texto_mkt, secoes_esperadas, tipo_bula)

    for secao in secoes_esperadas:
    
        checar_existencia = normalizar_titulo_para_comparacao(secao) not in secoes_ignorar_existencia_upper
    
        encontrou_anvisa, _, conteudo_anvisa = obter_dados_secao(secao, mapa_anvisa, linhas_anvisa, tipo_bula)
        encontrou_mkt, titulo_mkt, conteudo_mkt = obter_dados_secao(secao, mapa_mkt, linhas_mkt, tipo_bula)

        # Se 'obter_dados_secao' falhou, é porque a seção não foi encontrada.
        if not encontrou_mkt:
            if checar_existencia: 
                secoes_faltantes.append(secao)
            continue # Pula para a próxima seção

        # Se chegou aqui, 'encontrou_mkt' é True
        if encontrou_anvisa: # 'encontrou_anvisa' é sempre True, exceto em bulas muito mal formatadas
            secao_comp = normalizar_titulo_para_comparacao(secao)
            titulo_mkt_comp = normalizar_titulo_para_comparacao(titulo_mkt or "")
            
            if secao_comp != titulo_mkt_comp:
                if not any(d['secao_esperada'] == secao for d in diferencas_titulos):
                    diferencas_titulos.append({'secao_esperada': secao, 'titulo_encontrado': titulo_mkt})

            # v20.4: Compara com a lista normalizada
            if normalizar_titulo_para_comparacao(secao) in secoes_ignorar_upper:
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

# ----------------- ORTOGRAFIA (v20.5) -----------------
def checar_ortografia_inteligente(texto_para_checar, texto_referencia, tipo_bula):
    if not nlp or not texto_para_checar:
        return []

    try:
        # v20.5: Listas agora usam nova numeração
        secoes_ignorar = obter_secoes_ignorar_ortografia()
        secoes_todas = obter_secoes_por_tipo(tipo_bula)
        texto_filtrado_para_checar = []

        mapa_secoes = mapear_secoes(texto_para_checar, secoes_todas, tipo_bula) # v20.7 passa tipo_bula
        linhas_texto = texto_para_checar.split('\n')

        secoes_ignorar_norm = [normalizar_titulo_para_comparacao(s) for s in secoes_ignorar]

        for secao_nome in secoes_todas:
            # v20.4: Compara normalizado
            if normalizar_titulo_para_comparacao(secao_nome) in secoes_ignorar_norm:
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
            
            # Tenta substituir de forma mais segura
            try:
                # Usa count=1 para substituir apenas a primeira ocorrência
                texto_trabalho = texto_trabalho.replace(conteudo_a_substituir, conteudo_com_ancora, 1)
            except re.error:
                # Fallback se 'conteudo_a_substituir' for um regex inválido (raro, mas possível)
                pass

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
    st.info(f"ℹ️ **Datas de Aprovação ANVISA:**\n    - Arquivo da Anvisa: {data_ref}\n    - Arquivo Marketing: {data_belfar}")

    if secoes_faltantes:
        st.error(f"🚨 **Seções faltantes na bula Arquivo Marketing ({len(secoes_faltantes)})**:\n" + "\n".join([f"    - {s}" for s in secoes_faltantes]))
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

    secoes_canonicas = obter_secoes_por_tipo(tipo_bula)
    mapa_ref = mapear_secoes(texto_ref, secoes_canonicas, tipo_bula)
    mapa_belfar = mapear_secoes(texto_belfar, secoes_canonicas, tipo_bula)

    # --- INÍCIO DA CORREÇÃO DE ESPAÇAMENTO ---
    # Reformatar texto por seções detectadas
    try:
        texto_ref_reformatado_lista = []
        # Itera sobre os canônicos para garantir a ordem
        for secao_canon in secoes_canonicas:
            # Encontra a seção no mapa (se existir)
            encontrou, titulo_real, conteudo = obter_dados_secao(secao_canon, mapa_ref, texto_ref.split('\n'), tipo_bula)
            if encontrou:
                # Adiciona o título em negrito e o conteúdo, separados por uma única quebra de linha
                texto_ref_reformatado_lista.append(f"<strong>{titulo_real}</strong>\n{conteudo}")
        
        # Junta todas as seções com uma quebra de linha dupla (que vira <br><br>)
        texto_ref_reformatado = "\n\n".join(texto_ref_reformatado_lista) if texto_ref_reformatado_lista else texto_ref

        texto_belfar_reformatado_lista = []
        for secao_canon in secoes_canonicas:
            encontrou, titulo_real, conteudo = obter_dados_secao(secao_canon, mapa_belfar, texto_belfar.split('\n'), tipo_bula)
            if encontrou:
                # Adiciona o título em negrito e o conteúdo
                texto_belfar_reformatado_lista.append(f"<strong>{titulo_real}</strong>\n{conteudo}")
        
        # Junta todas as seções com uma quebra de linha dupla
        texto_belfar_reformatado = "\n\n".join(texto_belfar_reformatado_lista) if texto_belfar_reformatado_lista else texto_belfar

    except Exception as e:
        st.error(f"Erro ao reformatar texto para visualização: {e}")
        texto_ref_reformatado = texto_ref
        texto_belfar_reformatado = texto_belfar
    # --- FIM DA CORREÇÃO DE ESPAÇAMENTO ---

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
st.title("🔬 Inteligência Artificial para AuditorIA de Bulas")
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
            
            # Correção aqui: A chamada agora é para a função 'extrair_texto' que existe
            texto_ref, erro_ref = extrair_texto(pdf_ref, tipo_arquivo_ref)
            texto_belfar, erro_belfar = extrair_texto(pdf_belfar, 'pdf')

            # --- INÍCIO DA CORREÇÃO v20.8 ---
            # REMOVIDA a lógica de truncamento de 'texto_ref'
            # Isso corrigia o bug que impedia a data ANVISA e o conteúdo
            # de serem exibidos na visualização lado-a-lado.
            # --- FIM DA CORREÇÃO v20.8 ---
            
            if erro_ref or erro_belfar:
                st.error(f"Erro ao processar arquivos: {erro_ref or erro_belfar}")
            elif not texto_ref or not texto_belfar:
                 st.error("Erro: Um dos arquivos não pôde ser lido ou está vazio.")
            else:
                gerar_relatorio_final(texto_ref, texto_belfar, "Arquivo da Anvisa", "Arquivo Marketing", tipo_bula_selecionado)
    else:
        st.warning("⚠️ Por favor, envie ambos os arquivos para iniciar a auditoria.")

st.divider()
st.caption("Sistema de AuditorIA de Bulas v20.9 | Prioridade de Extração")
