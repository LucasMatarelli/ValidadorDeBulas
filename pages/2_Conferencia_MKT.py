# --- IMPORTS ---

# Libs Padrão
import re
import difflib
import unicodedata
import io

# Libs de Terceiros (Third-party)
import streamlit as st
import fitz  # PyMuPDF
import docx
import spacy
from thefuzz import fuzz
from spellchecker import SpellChecker
import pytesseract
from PIL import Image

# Libs Locais
# from style_utils import hide_streamlit_toolbar # O CSS está abaixo

# --- CONFIGURAÇÃO DA PÁGINA STREAMLIT ---

# Oculta elementos padrão do Streamlit (menu, footer)
hide_streamlit_UI = """
            <style>
            /* Esconde o cabeçalho do Streamlit Cloud (com 'Fork' e GitHub) */
            [data-testid="stHeader"] {
                display: none !important;
                visibility: hidden !important;
            }
            
            /* Esconde o menu hamburger (dentro do app) */
            [data-testid="main-menu-button"] {
                display: none !important;
            }
            
            /* Esconde o rodapé genérico (garantia extra) */
            footer {
                display: none !important;
                visibility: hidden !important;
            }

            /* --- NOVOS SELETORES (MAIS AGRESSIVOS) PARA O BADGE INFERIOR --- */

            /* Esconde o container principal do badge */
            [data-testid="stStatusWidget"] {
                display: none !important;
                visibility: hidden !important;
            }

            /* Esconde o 'Created by' */
            [data-testid="stCreatedBy"] {
                display: none !important;
                visibility: hidden !important;
            }

            /* Esconde o 'Hosted with Streamlit' */
            [data-testid="stHostedBy"] {
                display: none !important;
                visibility: hidden !important;
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


# ----------------- EXTRAÇÃO DE PDF ATUALIZADA COM OCR -----------------
# --- [FUNÇÃO REESCRITA PARA LAYOUT DE 2 COLUNAS] ---
def extrair_texto_pdf_com_ocr(arquivo_bytes):
    """
    Tenta extrair texto de um PDF. Se o resultado for fraco (sinal de texto em curva),
    usa OCR como alternativa (fallback).
    Esta versão é otimizada para PDFs de 2 colunas.
    """
    # --- TENTATIVA 1: Extração Direta por Colunas ---
    texto_direto = ""
    try:
        with fitz.open(stream=io.BytesIO(arquivo_bytes), filetype="pdf") as doc:
            for page in doc:
                # Pega os blocos de texto (x0, y0, x1, y1, "texto", ...)
                blocks = page.get_text("blocks", sort=False) 
                
                # Define o ponto central da página para separar as colunas
                middle_x = page.rect.width / 2
                
                col1_blocks = []
                col2_blocks = []
                
                for b in blocks:
                    x0 = b[0] # Posição x inicial do bloco
                    if x0 < middle_x:
                        col1_blocks.append(b)
                    else:
                        col2_blocks.append(b)
                
                # Ordena cada coluna de cima para baixo (pelo y0)
                col1_blocks.sort(key=lambda b: b[1])
                col2_blocks.sort(key=lambda b: b[1])
                
                # Concatena o texto da Coluna 1
                for b in col1_blocks:
                    texto_direto += b[4] + "\n"
                
                # Concatena o texto da Coluna 2
                for b in col2_blocks:
                    texto_direto += b[4] + "\n"
                
                texto_direto += "\n" # Adiciona uma quebra de página
    
        # Se a extração direta funcionar bem (mais de 100 caracteres), retorna o resultado
        if len(texto_direto.strip()) > 100:
            return texto_direto
            
    except Exception as e:
        # Se a leitura de blocos falhar, tenta a leitura simples
        try:
            with fitz.open(stream=io.BytesIO(arquivo_bytes), filetype="pdf") as doc:
                for page in doc:
                    texto_direto += page.get_text("text") + "\n"
            if len(texto_direto.strip()) > 100:
                return texto_direto
        except Exception as e2:
            pass # Falha, segue para OCR

    # --- TENTATIVA 2: Extração por OCR (Lenta, para arquivos em curva) ---
    st.info("Arquivo 'em curva' detectado. Iniciando leitura com OCR... Isso pode demorar um pouco.")
    texto_ocr = ""
    with fitz.open(stream=io.BytesIO(arquivo_bytes), filetype="pdf") as doc:
        for i, page in enumerate(doc):
            # Renderiza a página como uma imagem de alta qualidade
            pix = page.get_pixmap(dpi=300)
            img_bytes = pix.tobytes("png")
            imagem = Image.open(io.BytesIO(img_bytes))

            # Usa Tesseract OCR para extrair texto da imagem
            texto_ocr += pytesseract.image_to_string(imagem, lang='por') + "\n"
    
    return texto_ocr
# --- [FIM DA REESCRITA] ---


# ----------------- FUNÇÃO DE EXTRAÇÃO PRINCIPAL (MODIFICADA) -----------------
# --- [FUNÇÃO CORRIGIDA PARA O LAYOUT] ---
def extrair_texto(arquivo, tipo_arquivo):
    if arquivo is None:
        return "", f"Arquivo {tipo_arquivo} não enviado."
    try:
        arquivo.seek(0)
        texto = ""
        
        if tipo_arquivo == 'pdf':
            # Usa a nova função que tem o fallback para OCR e a correção de colunas
            texto = extrair_texto_pdf_com_ocr(arquivo.read())
        
        elif tipo_arquivo == 'docx':
            doc = docx.Document(arquivo)
            texto = "\n".join([p.text for p in doc.paragraphs])
        
        # O resto do pré-processamento continua o mesmo
        if texto:
            caracteres_invisiveis = ['\u00AD', '\u200B', '\u200C', '\u200D', '\uFEFF']
            for char in caracteres_invisiveis:
                texto = texto.replace(char, '')
            texto = texto.replace('\r\n', '\n').replace('\r', '\n')
            texto = texto.replace('\u00A0', ' ')
            texto = re.sub(r'(\w+)-\n(\w+)', r'\1\2', texto, flags=re.IGNORECASE)
            
            linhas = texto.split('\n')
            
            # --- [FILTRO DE RUÍDO CORRIGIDO] ---
            padrao_ruido_linha = re.compile(
                r'bula do paciente|página \d+\s*de\s*\d+'  # Rodapé padrão
                r'|(Tipologie|Tipologia) da bula:.*|(Merida|Medida) da (bula|trúa):?.*' # Ruído do MKT (com erros)
                r'|(Impressãe|Impressão):? Frente/Verso|Papel[\.:]? Ap \d+gr' # Ruído do MKT (com erros)
                r'|Cor:? Preta|contato:?|artes@belfar\.com\.br' # Ruído do MKT
                r'|BUL_CLORIDRATO_DE_NAFAZOLINA_BUL\d+V\d+|BUL\d+V\d+' # <-- [MUDANÇA] Filtro genérico
                r'|CLORIDRATO DE NAFAZOLINA: Times New Roman' # Ruído do MKT
                r'|^\s*FRENTE\s*$|^\s*VERSO\s*$' # Indicador de página
                r'|^\s*\d+\s*mm\s*$' # Medidas (ex: 190 mm, 300 mm)
                r'|^\s*-\s*Normal e Negrito\. Corpo \d+\s*$' # Linha de formatação
                r'|^\s*BELFAR\s*$|^\s*REZA\s*$|^\s*GEM\s*$|^\s*ALTEFAR\s*$|^\s*RECICLAVEL\s*$' # Ruído do rodapé
            , re.IGNORECASE)
            
            linhas_filtradas = []
            for linha in linhas:
                linha_strip = linha.strip()
                if not padrao_ruido_linha.search(linha_strip):
                    if len(linha_strip) > 1 or (len(linha_strip) == 1 and linha_strip.isdigit()):
                        # --- [AQUI ESTÁ A CORREÇÃO DE LAYOUT] ---
                        # Salvamos a 'linha' original (com espaços)
                        # e não a 'linha_strip' (sem espaços)
                        linhas_filtradas.append(linha) 
                    elif linha_strip.isupper() and len(linha_strip) > 0: 
                        linhas_filtradas.append(linha_strip)
            
            texto = "\n".join(linhas_filtradas)
            
            texto = re.sub(r'\n{3,}', '\n\n', texto) 
            # --- [CORREÇÃO DE LAYOUT] ---
            # Removida a linha abaixo que destruía a indentação
            # texto = re.sub(r'[ \t]+', ' ', texto) 
            texto = texto.strip()
            
            # --- [NOVA CORREÇÃO DE FORMATAÇÃO] ---
            # Corrige palavras coladas em parênteses (ex: "ergot(exemplo...")
            texto = re.sub(r'(\w)\(', r'\1 (', texto)
            
            # --- [CORREÇÃO TÍTULO GRUDADO] ---
            # Insere quebra de linha antes de títulos numerados que estão grudados
            # Ex: "...texto. 9. O QUE FAZER..."
            padrao_titulo_paciente = r'([.!?])(\s*)(\d+\s*\.\s*(?:PARA|COMO|QUANDO|O QUÊ|O QUE|ONDE|QUAIS)\b)'
            texto = re.sub(padrao_titulo_paciente, r'\1\n\n\3', texto, flags=re.IGNORECASE)
            # --- [FIM DA CORREÇÃO] ---

        return texto, None
    except Exception as e:
        return "", f"Erro ao ler o arquivo {tipo_arquivo}: {e}"
        
# --- [FUNÇÃO 'truncar_apos_anvisa' REMOVIDA] ---
# A lógica será aplicada inline e SOMENTE ao texto_ref,
# para garantir que o texto_belfar (Marketing) NUNCA seja cortado.


# ----------------- CONFIGURAÇÃO DE SEÇÕES -----------------
# --- [FUNÇÃO ATUALIZADA] ---
def obter_secoes_por_tipo(tipo_bula):
    secoes = {
        "Paciente": [
            "APRESENTAÇÕES", 
            "COMPOSIÇÃO", 
            "1. PARA QUE ESTE MEDICAMENTO É INDICADO?",
            "2. COMO ESTE MEDICAMENTO FUNCIONA?", 
            "3. QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?",
            "4. O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?", # <-- Linha unificada
            "5. ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?", # <-- Linha unificada
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
            "11. REAÇÕES ADVERSAS", # <-- Numeração corrigida
            "12. SUPERDOSE", # <-- Numeração corrigida
            "DIZERES LEGAIS"
        ]
    }
    return secoes.get(tipo_bula, [])

# --- [FUNÇÃO ATUALIZADA] ---
def obter_aliases_secao():
    # Mapeia os novos títulos numerados de Profissional para Paciente
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
    if not isinstance(texto, str): # Adiciona verificação de tipo para evitar TypeErrors
        return ""
    texto = ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')
    texto = re.sub(r'[^\w\s]', '', texto)
    texto = ' '.join(texto.split())
    return texto.lower()

def normalizar_titulo_para_comparacao(texto):
    """Normalização robusta para títulos, removendo acentos, pontuação e numeração inicial."""
    texto_norm = normalizar_texto(texto)
    # Esta linha é a CHAVE: ela remove "1. ", "2. ", etc., para a comparação
    texto_norm = re.sub(r'^\d+\s*[\.\-)]*\s*', '', texto_norm).strip()
    return texto_norm

# --- [NOVA FUNÇÃO ADICIONADA] ---
def _create_anchor_id(secao_nome, prefix):
    """Cria um ID HTML seguro para a âncora."""
    norm = normalizar_texto(secao_nome)
    norm_safe = re.sub(r'[^a-z0-9\-]', '-', norm)
    return f"anchor-{prefix}-{norm_safe}"

# ----------------- ARQUITETURA DE MAPEAMENTO DE SEÇÕES (VERSÃO FINAL) -----------------
# --- [FUNÇÃO CORRIGIDA] ---
def is_titulo_secao(linha):
    """Retorna True se a linha for um possível título de seção puro."""
    linha = linha.strip()
    # --- [MUDANÇA] ---
    # Permitir títulos muito curtos (como "9. O")
    if len(linha) < 2: # Antes era 4
        return False
    # Aumentar o limite de palavras
    if len(linha.split()) > 15: # Antes era 12
        return False
    if linha.endswith('.') or linha.endswith(':'):
        return False
    if re.search(r'\>\s*\<', linha):
        return False
    if len(linha) > 90: # Antes era 80
        return False
    return True
    # --- [FIM DA MUDANÇA] ---

# --- [FUNÇÃO MODIFICADA] ---
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

        # --- LÓGICA DE DETECÇÃO DE TÍTULO DE 1, 2 OU 3 LINHAS ---
        
        # 1. Checa 1 linha
        best_match_score_1_linha = 0
        best_match_canonico_1_linha = None
        for titulo_possivel, titulo_canonico in titulos_possiveis.items():
            # normalizar_titulo_para_comparacao remove o "1. " de ambos
            score = fuzz.token_set_ratio(normalizar_titulo_para_comparacao(titulo_possivel), normalizar_titulo_para_comparacao(linha_limpa))
            if score > best_match_score_1_linha:
                best_match_score_1_linha = score
                best_match_canonico_1_linha = titulo_canonico

        # 2. Checa 2 linhas
        best_match_score_2_linhas = 0
        best_match_canonico_2_linhas = None
        titulo_combinado_2_linhas = ""
        if (idx + 1) < len(linhas):
            linha_seguinte = linhas[idx + 1].strip()
            if len(linha_seguinte.split()) < 7: # Heurística: segunda linha de título é curta
                titulo_combinado_2_linhas = f"{linha_limpa} {linha_seguinte}"
                for titulo_possivel, titulo_canonico in titulos_possiveis.items():
                    score = fuzz.token_set_ratio(normalizar_titulo_para_comparacao(titulo_possivel), normalizar_titulo_para_comparacao(titulo_combinado_2_linhas))
                    if score > best_match_score_2_linhas:
                        best_match_score_2_linhas = score
                        best_match_canonico_2_linhas = titulo_canonico

        # --- [LÓGICA DE 3 LINHAS CORRIGIDA] ---
        # 3. Checa 3 linhas (para casos como a Seção 9)
        best_match_score_3_linhas = 0
        best_match_canonico_3_linhas = None
        titulo_combinado_3_linhas = ""
        if (idx + 2) < len(linhas):
            linha_seguinte = linhas[idx + 1].strip()
            linha_terceira = linhas[idx + 2].strip()
            
            # --- [HEURÍSTICA CORRIGIDA] ---
            # A linha 2 da Seção 9 tem 12 palavras. Aumentado o limite.
            if len(linha_seguinte.split()) < 15 and len(linha_terceira.split()) < 10: 
                titulo_combinado_3_linhas = f"{linha_limpa} {linha_seguinte} {linha_terceira}"
                for titulo_possivel, titulo_canonico in titulos_possiveis.items():
                    score = fuzz.token_set_ratio(normalizar_titulo_para_comparacao(titulo_possivel), normalizar_titulo_para_comparacao(titulo_combinado_3_linhas))
                    if score > best_match_score_3_linhas:
                        best_match_score_3_linhas = score
                        best_match_canonico_3_linhas = titulo_canonico
        # --- [FIM DA CORREÇÃO DE 3 LINHAS] ---
        
        limiar_score = 95
        
        # --- [LÓGICA DE DECISÃO ATUALIZADA] ---
        # Prioriza o melhor match (3 > 2 > 1)
        
        if best_match_score_3_linhas > best_match_score_2_linhas and \
           best_match_score_3_linhas > best_match_score_1_linha and \
           best_match_score_3_linhas >= limiar_score:
            
            # Match de 3 linhas
            if not mapa or mapa[-1]['canonico'] != best_match_canonico_3_linhas:
                mapa.append({
                    'canonico': best_match_canonico_3_linhas,
                    'titulo_encontrado': titulo_combinado_3_linhas,
                    'linha_inicio': idx,
                    'score': best_match_score_3_linhas,
                    'num_linhas_titulo': 3  # <-- Importante
                })
            idx += 3 # <-- Pula 3 linhas
            
        elif best_match_score_2_linhas > best_match_score_1_linha and best_match_score_2_linhas >= limiar_score:
            
            # Match de 2 linhas
            if not mapa or mapa[-1]['canonico'] != best_match_canonico_2_linhas:
                mapa.append({
                    'canonico': best_match_canonico_2_linhas,
                    'titulo_encontrado': titulo_combinado_2_linhas,
                    'linha_inicio': idx,
                    'score': best_match_score_2_linhas,
                    'num_linhas_titulo': 2
                })
            idx += 2 # <-- Pula 2 linhas

        elif best_match_score_1_linha >= limiar_score:
            
            # Match de 1 linha
            if not mapa or mapa[-1]['canonico'] != best_match_canonico_1_linha:
                mapa.append({
                    'canonico': best_match_canonico_1_linha,
                    'titulo_encontrado': linha_limpa,
                    'linha_inicio': idx,
                    'score': best_match_score_1_linha,
                    'num_linhas_titulo': 1
                })
            idx += 1
        else:
            # Nenhum match, avança 1 linha
            idx += 1
        # --- [FIM DA LÓGICA DE DECISÃO] ---
            
    mapa.sort(key=lambda x: x['linha_inicio'])
    return mapa

# --- [FUNÇÃO ATUALIZADA E CORRIGIDA] ---
def obter_dados_secao(secao_canonico, mapa_secoes, linhas_texto, tipo_bula):
    """
    Extrai o conteúdo de uma seção, procurando ativamente pelo próximo título para determinar o fim.
    Esta versão verifica se o próximo título está em uma única linha ou dividido em duas linhas consecutivas.
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

        prox_idx = None
        for j in range(linha_inicio_conteudo, len(linhas_texto)):
            linha_atual = linhas_texto[j].strip()
            linha_atual_norm = normalizar_titulo_para_comparacao(linha_atual) # Remove "1. ", "2. "

            encontrou_titulo_1_linha = False
            for titulo_oficial_norm in titulos_norm_set:
                if titulo_oficial_norm in linha_atual_norm and len(linha_atual_norm) > 0:
                    encontrou_titulo_1_linha = True
                    break 
            
            if encontrou_titulo_1_linha:
                prox_idx = j 
                break 

            if (j + 1) < len(linhas_texto):
                linha_seguinte = linhas_texto[j + 1].strip()
                titulo_duas_linhas = f"{linha_atual} {linha_seguinte}"
                titulo_duas_linhas_norm = normalizar_titulo_para_comparacao(titulo_duas_linhas)

                encontrou_titulo_2_linhas = False
                for titulo_oficial_norm in titulos_norm_set:
                    if titulo_oficial_norm in titulo_duas_linhas_norm and len(titulo_duas_linhas_norm) > 0:
                        encontrou_titulo_2_linhas = True
                        break 
                
                if encontrou_titulo_2_linhas:
                    prox_idx = j 
                    break 

        linha_fim = prox_idx if prox_idx is not None else len(linhas_texto)
        conteudo = [linhas_texto[idx] for idx in range(linha_inicio_conteudo, linha_fim)]
        
        # --- [INÍCIO DA NOVA LÓGICA DE REFLUXO E LIMPEZA - CORRIGIDA] ---
        
        # --- [BUG FIX] ---
        # Adiciona verificação para conteúdo vazio para evitar IndexError
        if not conteudo:
            return True, titulo_encontrado, ""
        # --- [FIM DO BUG FIX] ---

        # 1. Reconstrói os parágrafos
        conteudo_refluxo = [conteudo[0]]
        for i in range(1, len(conteudo)):
            linha_anterior = conteudo_refluxo[-1]
            linha_atual = conteudo[i]
            
            linha_atual_strip = linha_atual.strip()

            # Heurística: Se a linha atual NÃO parece ser um novo parágrafo
            # (não começa com maiúscula, número, ou bullet/asterisco)
            # E a linha anterior NÃO é vazia,
            # E a linha anterior NÃO termina com pontuação de fim de frase.
            
            is_new_paragraph = False
            if not linha_atual_strip:
                is_new_paragraph = True # Keep empty lines as paragraph breaks
            else:
                primeiro_char = linha_atual_strip[0]
                if primeiro_char.isupper() or primeiro_char in "“\"" or re.match(r'^\s*[\d\-\*•]', linha_atual_strip):
                    is_new_paragraph = True
            
            is_end_of_sentence = False
            if not linha_anterior.strip() or re.search(r'[.!?:]$', linha_anterior.strip()):
                is_end_of_sentence = True
                
            if not is_new_paragraph and not is_end_of_sentence:
                # Juntar com a linha anterior
                conteudo_refluxo[-1] = linha_anterior.rstrip() + " " + linha_atual.lstrip()
            else:
                # É uma nova linha
                conteudo_refluxo.append(linha_atual)

        conteudo_final = "\n".join(conteudo_refluxo).strip()

        # 2. Limpa o espaçamento da pontuação
        # Remove espaços ANTES de pontuação: "exemplo , " -> "exemplo,"
        conteudo_final = re.sub(r'\s+([.,;:!?)\]])', r'\1', conteudo_final)
        # Remove espaços DEPOIS de pontuação de abertura: "( exemplo" -> "(exemplo"
        conteudo_final = re.sub(r'([(\[])\s+', r'\1', conteudo_final)
        # Garante espaço DEPOIS da pontuação (se seguido por letra): "exemplo,quadro" -> "exemplo, quadro"
        conteudo_final = re.sub(r'([.,;:!?)\]])(\w)', r'\1 \2', conteudo_final)
        # Garante espaço ANTES da pontuação de abertura (se seguido por letra): "exemplo(quadro" -> "exemplo (quadro"
        conteudo_final = re.sub(r'(\w)([(\[])', r'\1 \2', conteudo_final)
        # --- [FIM DA NOVA LÓGICA] ---
        
        return True, titulo_encontrado, conteudo_final

    return False, None, ""
# --- [FIM DA ATUALIZAÇÃO] ---


# ----------------- COMPARAÇÃO DE CONTEÚDO -----------------
# --- [FUNÇÃO SUBSTITUÍDA] ---
def verificar_secoes_e_conteudo(texto_anvisa, texto_mkt, tipo_bula):
    secoes_esperadas = obter_secoes_por_tipo(tipo_bula)
    secoes_faltantes, diferencas_conteudo, similaridades_secoes, diferencas_titulos = [], [], [], []
    secoes_ignorar_upper = [s.upper() for s in obter_secoes_ignorar_comparacao()]

    linhas_anvisa = texto_anvisa.split('\n')
    linhas_mkt = texto_mkt.split('\n')
    mapa_anvisa = mapear_secoes(texto_anvisa, secoes_esperadas)
    mapa_mkt = mapear_secoes(texto_mkt, secoes_esperadas)

    secoes_mkt_encontradas = {m['canonico']: m for m in mapa_mkt}

    for secao in secoes_esperadas:
        melhor_titulo = None
        encontrou_anvisa, _, conteudo_anvisa = obter_dados_secao(secao, mapa_anvisa, linhas_anvisa, tipo_bula)
        encontrou_mkt, titulo_mkt, conteudo_mkt = obter_dados_secao(secao, mapa_mkt, linhas_mkt, tipo_bula)

        if not encontrou_mkt:
            melhor_score = 0
            melhor_titulo = None
            for m in mapa_mkt:
                # Compara "para que este med" (norm) com "para que este med" (norm)
                score = fuzz.token_set_ratio(normalizar_titulo_para_comparacao(secao), normalizar_titulo_para_comparacao(m['titulo_encontrado']))
                if score > melhor_score:
                    melhor_score = score
                    melhor_titulo = m['titulo_encontrado']
            if melhor_score >= 95:
                diferencas_titulos.append({'secao_esperada': secao, 'titulo_encontrado': melhor_titulo})
                for m in mapa_mkt:
                    if m['titulo_encontrado'] == melhor_titulo:
                        # Lógica para pegar conteúdo da seção encontrada por similaridade
                        next_section_start = len(linhas_mkt)
                        current_index = mapa_mkt.index(m)
                        if current_index + 1 < len(mapa_mkt):
                            next_section_start = mapa_mkt[current_index + 1]['linha_inicio']
                        
                        # Pega o conteúdo a partir da linha *após* o título encontrado
                        conteudo_mkt_raw = "\n".join(linhas_mkt[m['linha_inicio'] + m.get('num_linhas_titulo', 1) : next_section_start])
                        
                        # --- [NOVO] Aplica a mesma lógica de reflow aqui ---
                        # Isso garante que a comparação seja feita no texto limpo
                        temp_mapa = [{'canonico': secao, 'titulo_encontrado': melhor_titulo, 'linha_inicio': 0, 'num_linhas_titulo': 0}]
                        _, _, conteudo_mkt = obter_dados_secao(secao, temp_mapa, conteudo_mkt_raw.split('\n'), tipo_bula)
                        # --- [FIM] ---

                        break
                encontrou_mkt = True
            else:
                secoes_faltantes.append(secao)
                continue

        if encontrou_anvisa and encontrou_mkt:
            secao_comp = normalizar_titulo_para_comparacao(secao)
            # Usa o 'titulo_mkt' (da busca direta) ou 'melhor_titulo' (da busca fuzzy)
            titulo_mkt_comp = normalizar_titulo_para_comparacao(titulo_mkt if titulo_mkt else melhor_titulo)

            if secao_comp != titulo_mkt_comp:
                if not any(d['secao_esperada'] == secao for d in diferencas_titulos):
                    diferencas_titulos.append({'secao_esperada': secao, 'titulo_encontrado': titulo_mkt if titulo_mkt else melhor_titulo})

            if secao.upper() in secoes_ignorar_upper:
                continue

            if normalizar_texto(conteudo_anvisa) != normalizar_texto(conteudo_mkt):
                
                # Define o título que foi realmente encontrado (pode ser da busca normal ou fuzzy)
                titulo_real_encontrado = titulo_mkt if titulo_mkt else melhor_titulo
                
                diferencas_conteudo.append({
                    'secao': secao, # <-- Importante: 'secao' é o nome canônico (ex: "1. PARA QUE...")
                    'conteudo_anvisa': conteudo_anvisa, 
                    'conteudo_mkt': conteudo_mkt,
                    'titulo_encontrado': titulo_real_encontrado # <-- Título "sujo" (ex: "cloridrato... 1. PARA QUE...")
                })
                similaridades_secoes.append(0)
            else:
                similaridades_secoes.append(100)

    return secoes_faltantes, diferencas_conteudo, similaridades_secoes, diferencas_titulos


# ----------------- ORTOGRAFIA -----------------
# --- [FUNÇÃO SUBSTITUÍDA] ---
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
            # Converte '1. PARA QUE...' para 'PARA QUE...'
            secao_nome_upper = normalizar_titulo_para_comparacao(secao_nome).upper() 
            
            if secao_nome.upper() in [s.upper() for s in secoes_ignorar]: # Checa por "COMPOSIÇÃO", "DIZERES LEGAIS"
                continue
                
            encontrou, _, conteudo = obter_dados_secao(secao_nome, mapa_secoes, linhas_texto, tipo_bula)
            if encontrou and conteudo:
                # Modificado para pegar o conteúdo todo
                texto_filtrado_para_checar.append(conteudo) 

        texto_final_para_checar = '\n'.join(texto_filtrado_para_checar)
        if not texto_final_para_checar:
            return []

        spell = SpellChecker(language='pt')
        palavras_a_ignorar = {"alair", "belfar", "peticionamento", "urotrobel", "contato", "dihidroergotamina"} # <-- Adicionado
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
        return []

# ----------------- DIFERENÇAS PALAVRA A PALAVRA -----------------
# --- [FUNÇÃO SUBSTITUÍDA] ---
def marcar_diferencas_palavra_por_palavra(texto_ref, texto_belfar, eh_referencia):
    def tokenizar(txt):
        # Tokeniza por \n OU palavra OU pontuação
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

    # --- [LÓGICA DE RECONSTRUÇÃO DE TEXTO CORRIGIDA E SIMPLIFICADA] ---
    resultado = ""
    for i, tok in enumerate(marcado):
        if i == 0:
            resultado += tok
            continue

        tok_anterior_raw = re.sub(r'^<mark[^>]*>|</mark>$', '', marcado[i-1])
        raw_tok = re.sub(r'^<mark[^>]*>|</mark>$', '', tok)

        # Regra 1: Se o token atual ou anterior for newline, NUNCA adicionar espaço.
        if raw_tok == '\n' or tok_anterior_raw == '\n':
            resultado += tok
        # Regra 2: Se o token atual for pontuação de fechamento/meio, NUNCA adicionar espaço.
        elif re.match(r'^[.,;:!?)\]]$', raw_tok):
            resultado += tok
        # Regra 3: Se o token anterior for pontuação de abertura, NUNCA adicionar espaço.
        elif re.match(r'^[(\[]$', tok_anterior_raw):
            resultado += tok
        # Regra 4: Default (palavra, ou abertura), ADICIONAR espaço.
        else:
            resultado += " " + tok
    # --- FIM DA CORREÇÃO ---
            
    resultado = re.sub(r"(</mark>)\s+(<mark[^>]*>)", " ", resultado)
    return resultado

# ----------------- MARCAÇÃO POR SEÇÃO COM ÍNDICES -----------------
# --- [FUNÇÃO ATUALIZADA - REVERTIDA PARA A VERSÃO SIMPLES E CORRETA] ---
def marcar_divergencias_html(texto_original, secoes_problema, erros_ortograficos, tipo_bula, eh_referencia=False):
    texto_trabalho = texto_original
    if secoes_problema:
        for diff in secoes_problema:
            
            # 1. Pega os conteúdos (já limpos e reformatados pela obter_dados_secao)
            conteudo_ref = diff['conteudo_anvisa']
            conteudo_belfar = diff['conteudo_mkt']
            
            # 2. Gera o HTML marcado (que também está limpo e reformatado)
            conteudo_marcado = marcar_diferencas_palavra_por_palavra(
                conteudo_ref,
                conteudo_belfar,
                eh_referencia
            )
            
            # 3. Pega o conteúdo que será substituído (ref ou belfar)
            conteudo_a_substituir = conteudo_ref if eh_referencia else conteudo_belfar
            
            # 4. Adiciona a âncora
            secao_canonico = diff['secao']
            anchor_id = _create_anchor_id(secao_canonico, "ref" if eh_referencia else "bel")
            conteudo_com_ancora = f"<div id='{anchor_id}' style='scroll-margin-top: 20px;'>{conteudo_marcado}</div>"

            # 5. [A CORREÇÃO]
            # O `texto_original` (passado pela gerar_relatorio_final) já está REFORMATADO.
            # O `conteudo_a_substituir` (vindo da diff) também está REFORMATADO.
            # Uma simples substituição deve funcionar.
            if conteudo_a_substituir and conteudo_a_substituir in texto_trabalho:
                # Substitui o conteúdo limpo pelo conteúdo limpo, marcado e com âncora
                texto_trabalho = texto_trabalho.replace(conteudo_a_substituir, conteudo_com_ancora, 1)
            
            # --- [FIM DA LÓGICA DE SUBSTITUIÇÃO] ---

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
# --- [FIM DA ATUALIZAÇÃO] ---


# ----------------- RELATÓRIO -----------------
# --- [FUNÇÃO SUBSTITUÍDA E CORRIGIDA] ---
def gerar_relatorio_final(texto_ref, texto_belfar, nome_ref, nome_belfar, tipo_bula):
    
    # --- [NOVO] Script Global (Plano C) ---
    js_scroll_script = """
    <script>
    if (!window.handleBulaScroll) {
        window.handleBulaScroll = function(anchorIdRef, anchorIdBel) {
            console.log("Chamada handleBulaScroll:", anchorIdRef, anchorIdBel);
            var containerRef = document.getElementById('container-ref-scroll');
            var containerBel = document.getElementById('container-bel-scroll');
            var anchorRef = document.getElementById(anchorIdRef);
            var anchorBel = document.getElementById(anchorIdBel);
            if (!containerRef || !containerBel) {
                console.error("ERRO: Containers 'container-ref-scroll' ou 'container-bel-scroll' não encontrados.");
                return;
            }
            if (!anchorRef || !anchorBel) {
                console.error("ERRO: Âncoras '" + anchorIdRef + "' ou '" + anchorIdBel + "' não encontradas.");
                return;
            }
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

                    console.log("Rolagem interna EXECUTADA.");
                } catch (e) {
                    console.error("Erro durante a rolagem interna:", e);
                }
            }, 700); 
        }
        console.log("Função window.handleBulaScroll DEFINIDA.");
    }
    </script>
    """
    st.markdown(js_scroll_script, unsafe_allow_html=True)
    # --- [FIM DO SCRIPT] ---

    st.header("Relatório de Auditoria Inteligente")
    regex_anvisa = r"(aprovad[ao]\s+pela\s+anvisa\s+em|data\s+de\s+aprovação\s+na\s+anvisa:)\s*([\d]{1,2}/[\d]{1,2}/[\d]{2,4})"
    
    # Busca datas nos textos originais (e não truncados)
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
    col3.metric("Data ANVISA (Marketing)", data_belfar)
    col4.metric("Seções Faltantes", f"{len(secoes_faltantes)}")

    st.divider()
    st.subheader("Detalhes dos Problemas Encontrados")
    # --- [CORREÇÃO 1: data_bf -> data_belfar] ---
    st.info(f"ℹ️ **Datas de Aprovação ANVISA:**\n   - Arquivo da Anvisa: {data_ref}\n   - Arquivo Marketing: {data_belfar}") # Mantido seu recuo
    # --- [FIM DA CORREÇÃO 1] ---

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
            
            # --- [NOVA LÓGICA DE TÍTULO SIMPLIFICADA] ---
            # O 'secao' (diff['secao']) já é o nome canônico e numerado que queremos.
            # Ex: "1. PARA QUE ESTE MEDICAMENTO É INDICADO?"
            titulo_display = diff['secao']
            # --- [FIM DA LÓGICA] ---

            with st.expander(f"📄 {titulo_display} - ❌ CONTEÚDO DIVERGENTE"):
            
                secao_canonico = diff['secao']
                anchor_id_ref = _create_anchor_id(secao_canonico, "ref")
                anchor_id_bel = _create_anchor_id(secao_canonico, "bel")
                
                expander_html_ref = marcar_diferencas_palavra_por_palavra(
                diff['conteudo_anvisa'], diff['conteudo_mkt'], eh_referencia=True
                ).replace('\n', '<br>')
                expander_html_belfar = marcar_diferencas_palavra_por_palavra(
                diff['conteudo_anvisa'], diff['conteudo_mkt'], eh_referencia=False
                ).replace('\n', '<br>')
                
                clickable_style = expander_caixa_style + " cursor: pointer; transition: background-color 0.3s ease;"
                
                html_ref_box = f"<div onclick='window.handleBulaScroll(\"{anchor_id_ref}\", \"{anchor_id_bel}\")' style='{clickable_style}' title='Clique para ir à seção' onmouseover='this.style.backgroundColor=\"#f0f8ff\"' onmouseout='this.style.backgroundColor=\"#ffffff\"'>{expander_html_ref}</div>"
                
                # --- [CORREÇÃO 2: expander_html_baf -> expander_html_belfar] ---
                html_bel_box = f"<div onclick='window.handleBulaScroll(\"{anchor_id_ref}\", \"{anchor_id_bel}\")' style='{clickable_style}' title='Clique para ir à seção' onmouseover='this.style.backgroundColor=\"#f0f8ff\"' onmouseout='this.style.backgroundColor=\"#ffffff\"'>{expander_html_belfar}</div>"
                # --- [FIM DA CORREÇÃO 2] ---

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
    
    # --- INÍCIO DA MODIFICAÇÃO ESTÉTICA (DO SEU CÓDIGO) ---
    
    # 1. Estilo da Legenda
    legend_style = (
        "font-size: 14px; "
        "background-color: #f0f2f6; "  # Cor de fundo suave (cinza-azulado do Streamlit)
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
    
    # --- [CORREÇÃO DA FORMATAÇÃO DO VISUALIZADOR] ---
    # Precisamos criar uma versão reformatada dos textos *inteiros*
    # para a exibição final, preservando as âncoras.

    # 1. Reformata os textos inteiros, seção por seção
    mapa_ref = mapear_secoes(texto_ref, obter_secoes_por_tipo(tipo_bula))
    mapa_belfar = mapear_secoes(texto_belfar, obter_secoes_por_tipo(tipo_bula))
    
    # Adicionado try/except para depuração, caso obter_dados_secao falhe
    try:
        texto_ref_reformatado = "\n\n".join(
            obter_dados_secao(secao['canonico'], mapa_ref, texto_ref.split('\n'), tipo_bula)[2] 
            for secao in mapa_ref
        )
        texto_belfar_reformatado = "\n\n".join(
            obter_dados_secao(secao['canonico'], mapa_belfar, texto_belfar.split('\n'), tipo_bula)[2] 
            for secao in mapa_belfar
        )
    except Exception as e:
        st.error(f"Erro ao reformatar texto para visualização: {e}")
        texto_ref_reformatado = texto_ref
        texto_belfar_reformatado = texto_belfar


    # 2. Gera o HTML marcado usando os textos reformatados
    html_ref_marcado = marcar_divergencias_html(
        texto_original=texto_ref_reformatado, 
        secoes_problema=diferencas_conteudo, 
        erros_ortograficos=[], 
        tipo_bula=tipo_bula, 
        eh_referencia=True
    ).replace('\n', '<br>')
    
    # --- [CORREÇÃO 3: 'marcar_divergc' -> 'marcar_divergencias_html'] ---
    html_belfar_marcado = marcar_divergencias_html(
        texto_original=texto_belfar_reformatado, 
        secoes_problema=diferencas_conteudo, 
        erros_ortograficos=erros_ortograficos, 
        tipo_bula=tipo_bula, 
        eh_referencia=False
    ).replace('\n', '<br>')
    # --- [FIM DA CORREÇÃO 3] ---


    # 2. Estilo da Caixa de Visualização
    caixa_style = (
        "height: 700px; "  # MUDANÇA: altura fixa para alinhar os botões de scroll
        "overflow-y: auto; "
        "border: 1px solid #e0e0e0; "  # Borda mais suave
        "border-radius: 8px; "  # Cantos mais arredondados
        "padding: 20px 24px; "  # Padding interno
        "background-color: #ffffff; "
        "font-size: 15px; "  # Fonte ligeiramente maior para leitura
        "line-height: 1.7; "  # Melhor espaçamento entre linhas
        "box-shadow: 0 4px 12px rgba(0,0,0,0.08); "  # Sombra mais suave
        "text-align: left; "  # Alinhamento à esquerda é melhor para leitura
    )
    
    col1, col2 = st.columns(2, gap="medium")
    with col1:
        # 3. Título como H4 (um pouco menor que subheader)
        st.markdown(f"#### {nome_ref}") 
        st.markdown(f"<div id='container-ref-scroll' style='{caixa_style}'>{html_ref_marcado}</div>", unsafe_allow_html=True)
    with col2:
        st.markdown(f"#### {nome_belfar}")
        st.markdown(f"<div id='container-bel-scroll' style='{caixa_style}'>{html_belfar_marcado}</div>", unsafe_allow_html=True)
    
    # --- FIM DA MODIFICAÇÃO ESTÉTICA ---

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
            
            # Determina dinamicamente o tipo de arquivo da Anvisa
            tipo_arquivo_ref = 'docx' if pdf_ref.name.lower().endswith('.docx') else 'pdf'
            texto_ref, erro_ref = extrair_texto(pdf_ref, tipo_arquivo_ref)
            
            texto_belfar, erro_belfar = extrair_texto(pdf_belfar, 'pdf')

            # --- [CORREÇÃO DE TRUNCAMENTO (CORTE)] ---
            if not erro_ref:
                # Aplica a lógica de truncamento SOMENTE ao texto_ref
                regex_anvisa_trunc = r"(aprovad[ao]\s+pela\s+anvisa\s+em|data\s+de\s+aprovação\s+na\s+anvisa:)\s*([\d]{1,2}/[\d]{1,2}/[\d]{2,4})"
                match = re.search(regex_anvisa_trunc, texto_ref, re.IGNORECASE)
                if match:
                    end_of_line_pos = texto_ref.find('\n', match.end())
                    if end_of_line_pos != -1:
                        texto_ref = texto_ref[:end_of_line_pos]
            
            # O texto_belfar (Marketing) NÃO é truncado.
            # --- [FIM DA CORREÇÃO] ---

            if erro_ref or erro_belfar:
                st.error(f"Erro ao processar arquivos: {erro_ref or erro_belfar}")
            else:
                gerar_relatorio_final(texto_ref, texto_belfar, "Arquivo da Anvisa", "Arquivo Marketing", tipo_bula_selecionado)
    else:
        st.warning("⚠️ Por favor, envie ambos os arquivos para iniciar a auditoria.")

st.divider()
st.caption("Sistema de AuditorIA de Bulas v19.0 | OCR & Layout Fix")
