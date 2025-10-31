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
# --- [FUNÇÃO CORRIGIDA PARA O LAYOUT] ---
def extrair_texto_pdf_com_ocr(arquivo_bytes):
    """
    Tenta extrair texto de um PDF. Se o resultado for fraco (sinal de texto em curva),
    usa OCR como alternativa (fallback).
    """
    # --- TENTATIVA 1: Extração Direta (Rápida e Ideal) ---
    texto_direto = ""
    with fitz.open(stream=io.BytesIO(arquivo_bytes), filetype="pdf") as doc:
        for page in doc:
            # --- [CORREÇÃO DE LAYOUT] ---
            # Troca de "blocks" para "text" para preservar quebras de linha
            texto_direto += page.get_text("text", sort=True) + "\n"

    # Se a extração direta funcionar bem (mais de 100 caracteres), retorna o resultado
    if len(texto_direto.strip()) > 100:
        return texto_direto

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


# ----------------- FUNÇÃO DE EXTRAÇÃO PRINCIPAL (MODIFICADA) -----------------
# --- [FUNÇÃO CORRIGIDA PARA O LAYOUT] ---
def extrair_texto(arquivo, tipo_arquivo):
    if arquivo is None:
        return "", f"Arquivo {tipo_arquivo} não enviado."
    try:
        arquivo.seek(0)
        texto = ""
        
        if tipo_arquivo == 'pdf':
            # Usa a nova função que tem o fallback para OCR
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
            
            # --- FILTRO DE RUÍDO APRIMORADO ---
            padrao_ruido_linha = re.compile(
                r'bula do paciente|página \d+\s*de\s*\d+'  # Rodapé padrão
                r'|(Tipologie|Tipologia) da bula:.*|(Merida|Medida) da (bula|trúa):?.*' # Ruído do MKT (com erros)
                r'|(Impressãe|Impressão):? Frente/Verso|Papel[\.:]? Ap \d+gr' # Ruído do MKT (com erros)
                r'|Cor:? Preta|contato:?|artes@belfar\.com\.br' # Ruído do MKT
                r'|BUL_CLORIDRATO_DE_NAFAZOLINA_BUL\d+V\d+' # Nome do arquivo
                r'|CLORIDRATO DE NAFAZOLINA: Times New Roman' # Ruído do MKT
                r'|^\s*FRENTE\s*$|^\s*VERSO\s*$' # Indicador de página
                r'|^\s*\d+\s*mm\s*$' # Medidas (ex: 190 mm, 300 mm)
                r'|^\s*-\s*Normal e Negrito\. Corpo \d+\s*$' # Linha de formatação
                r'|^\s*BELFAR\s*$|^\s*REZA\s*$|^\s*GEM\s*$|^\s*ALTEFAR\s*$|^\s*RECICLAVEL\s*$|^\s*BUL\d+\s*$' # Ruído do rodapé
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

        return texto, None
    except Exception as e:
        return "", f"Erro ao ler o arquivo {tipo_arquivo}: {e}"
        
def truncar_apos_anvisa(texto):
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

# ----------------- CONFIGURAÇÃO DE SEÇÕES -----------------
def obter_secoes_por_tipo(tipo_bula):
    secoes = {
        "Paciente": [
            "APRESENTAÇÕES", "COMPOSIÇÃO", "PARA QUE ESTE MEDICAMENTO É INDICADO",
            "COMO ESTE MEDICAMENTO FUNCIONA?", "QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?",
            "O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?",
            "ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?",
            "COMO DEVO USAR ESTE MEDICAMENTO?",
            "O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?",
            "QUAIS OS MALES QUE ESTE MEDICAMENTO PODE ME CAUSAR?",
            "O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?",
            "DIZERES LEGAIS"
        ],
        "Profissional": [
            "APRESENTAÇÕES", "COMPOSIÇÃO", "INDICAÇÕES", "RESULTADOS DE EFICÁCIA",
            "CARACTERÍSTICAS FARMACOLÓGICAS", "CONTRAINDICAÇÕES",
            "ADVERTÊNCIAS E PRECAUÇÕES", "INTERAÇÕES MEDICAMENTOSAS",
            "CUIDADOS DE ARMAZENAMENTO DO MEDICAMENTO", "POSOLOGIA E MODO DE USAR",
            "REAÇÕES ADVERSAS", "SUPERDOSE", "DIZERES LEGAIS"
        ]
    }
    return secoes.get(tipo_bula, [])

def obter_aliases_secao():
    return {
        "INDICAÇÕES": "PARA QUE ESTE MEDICAMENTO É INDICADO?",
        "CONTRAINDICAÇÕES": "QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?",
        "POSOLOGIA E MODO DE USAR": "COMO DEVO USAR ESTE MEDICAMENTO?",
        "REAÇÕES ADVERSAS": "QUAIS OS MALES QUE ESTE MEDICAMENTO PODE ME CAUSAR?",
        "SUPERDOSE": "O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?",
        "CUIDADOS DE ARMAZENAMENTO DO MEDICAMENTO": "ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?"
    }

def obter_secoes_ignorar_ortografia():
    return ["COMPOSIÇÃO", "DIZERES LEGAIS"]

def obter_secoes_ignorar_comparacao():
    return ["COMPOSIÇÃO", "DIZERES LEGAIS", "APRESENTAÇÕES", "ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?"]

# ----------------- NORMALIZAÇÃO -----------------
def normalizar_texto(texto):
    texto = ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')
    texto = re.sub(r'[^\w\s]', '', texto)
    texto = ' '.join(texto.split())
    return texto.lower()

def normalizar_titulo_para_comparacao(texto):
    """Normalização robusta para títulos, removendo acentos, pontuação e numeração inicial."""
    texto_norm = normalizar_texto(texto)
    texto_norm = re.sub(r'^\d+\s*[\.\-)]*\s*', '', texto_norm).strip()
    return texto_norm

# --- [NOVA FUNÇÃO ADICIONADA] ---
def _create_anchor_id(secao_nome, prefix):
    """Cria um ID HTML seguro para a âncora."""
    norm = normalizar_texto(secao_nome)
    norm_safe = re.sub(r'[^a-z0-9\-]', '-', norm)
    return f"anchor-{prefix}-{norm_safe}"

# ----------------- ARQUITETURA DE MAPEAMENTO DE SEÇÕES (VERSÃO FINAL) -----------------
def is_titulo_secao(linha):
    """Retorna True se a linha for um possível título de seção puro."""
    linha = linha.strip()
    # Mantido os limites do seu código (12 palavras, 80 caracteres)
    if len(linha) < 4 or len(linha.split()) > 12: 
        return False
    if linha.endswith('.') or linha.endswith(':'):
        return False
    if re.search(r'\>\s*\<', linha):
        return False
    if len(linha) > 80:
        return False
    return True

# --- FUNÇÃO MANTIDA DO SEU SCRIPT (ESTÁ CORRETA) ---
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

        # --- LÓGICA DE DETECÇÃO DE TÍTULO DE 1 OU 2 LINHAS ---
        best_match_score_1_linha = 0
        best_match_canonico_1_linha = None
        for titulo_possivel, titulo_canonico in titulos_possiveis.items():
            score = fuzz.token_set_ratio(normalizar_titulo_para_comparacao(titulo_possivel), normalizar_titulo_para_comparacao(linha_limpa))
            if score > best_match_score_1_linha:
                best_match_score_1_linha = score
                best_match_canonico_1_linha = titulo_canonico

        best_match_score_2_linhas = 0
        best_match_canonico_2_linhas = None
        titulo_combinado = ""
        if (idx + 1) < len(linhas):
            linha_seguinte = linhas[idx + 1].strip()
            if len(linha_seguinte.split()) < 7:
                titulo_combinado = f"{linha_limpa} {linha_seguinte}"
                for titulo_possivel, titulo_canonico in titulos_possiveis.items():
                    score = fuzz.token_set_ratio(normalizar_titulo_para_comparacao(titulo_possivel), normalizar_titulo_para_comparacao(titulo_combinado))
                    if score > best_match_score_2_linhas:
                        best_match_score_2_linhas = score
                        best_match_canonico_2_linhas = titulo_canonico
        
        limiar_score = 95
        
        if best_match_score_2_linhas > best_match_score_1_linha and best_match_score_2_linhas >= limiar_score:
            if not mapa or mapa[-1]['canonico'] != best_match_canonico_2_linhas:
                mapa.append({
                    'canonico': best_match_canonico_2_linhas,
                    'titulo_encontrado': titulo_combinado,
                    'linha_inicio': idx,
                    'score': best_match_score_2_linhas,
                    'num_linhas_titulo': 2
                })
            idx += 2
        elif best_match_score_1_linha >= limiar_score:
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
            idx += 1
            
    mapa.sort(key=lambda x: x['linha_inicio'])
    return mapa

# --- [FUNÇÃO SUBSTITUÍDA] ---
def obter_dados_secao(secao_canonico, mapa_secoes, linhas_texto, tipo_bula):
    """
    Extrai o conteúdo de uma seção, procurando ativamente pelo próximo título para determinar o fim.
    Esta versão verifica se o próximo título está em uma única linha ou dividido em duas linhas consecutivas.
    """
    # Títulos oficiais da bula para o tipo selecionado
    TITULOS_OFICIAIS = {
        "Paciente": [
            "APRESENTAÇÕES", "COMPOSIÇÃO", "PARA QUE ESTE MEDICAMENTO É INDICADO",
            "COMO ESTE MEDICAMENTO FUNCIONA?", "QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?",
            "O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?",
            "ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?",
            "COMO DEVO USAR ESTE MEDICAMENTO?",
            "O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?",
            "QUAIS OS MALES QUE ESTE MEDICAMENTO PODE ME CAUSAR?",
            "O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?",
            "DIZERES LEGAIS"
        ],
        "Profissional": [
            "APRESENTAÇÕES", "COMPOSIÇÃO", "INDICAÇÕES", "RESULTADOS DE EFICÁCIA",
            "CARACTERÍSTICAS FARMACOLÓGICAS", "CONTRAINDICAÇÕES",
            "ADVERTÊNCIAS E PRECAUÇÕES", "INTERAÇÕES MEDICAMENTOSAS",
            "CUIDADOS DE ARMAZENAMENTO DO MEDICAMENTO", "POSOLOGIA E MODO DE USAR",
            "REAÇÕES ADVERSAS", "SUPERDOSE", "DIZERES LEGAIS"
        ]
    }

    titulos_lista = TITULOS_OFICIAIS.get(tipo_bula, [])
    # Normaliza a lista de títulos oficiais uma vez para otimizar a busca
    titulos_norm_set = {normalizar_titulo_para_comparacao(t) for t in titulos_lista}

    for i, secao_mapa in enumerate(mapa_secoes):
        if secao_mapa['canonico'] != secao_canonico:
            continue

        titulo_encontrado = secao_mapa['titulo_encontrado']
        linha_inicio = secao_mapa['linha_inicio']
        # Usa a num_linhas_titulo do seu mapear_secoes
        num_linhas_titulo = secao_mapa.get('num_linhas_titulo', 1) 
        
        # O conteúdo começa DEPOIS do título (1 ou 2 linhas)
        linha_inicio_conteudo = linha_inicio + num_linhas_titulo

        # --- LÓGICA DE BUSCA APRIMORADA (1 ou 2 linhas) ---
        prox_idx = None
        for j in range(linha_inicio_conteudo, len(linhas_texto)):
            # Verifica a linha atual (busca de 1 linha)
            linha_atual = linhas_texto[j].strip()
            linha_atual_norm = normalizar_titulo_para_comparacao(linha_atual)

            # Verificamos se algum título oficial está CONTIDO na linha normalizada
            encontrou_titulo_1_linha = False
            for titulo_oficial_norm in titulos_norm_set:
                # Adicionado 'and len(linha_atual_norm) > 0' para evitar linhas vazias
                if titulo_oficial_norm in linha_atual_norm and len(linha_atual_norm) > 0:
                    encontrou_titulo_1_linha = True
                    break 
            
            if encontrou_titulo_1_linha:
                prox_idx = j 
                break 

            # Se não encontrou, verifica a combinação da linha atual + próxima (busca de 2 linhas)
            if (j + 1) < len(linhas_texto):
                linha_seguinte = linhas_texto[j + 1].strip()
                titulo_duas_linhas = f"{linha_atual} {linha_seguinte}"
                titulo_duas_linhas_norm = normalizar_titulo_para_comparacao(titulo_duas_linhas)

                encontrou_titulo_2_linhas = False
                for titulo_oficial_norm in titulos_norm_set:
                     # Adicionado 'and len(titulo_duas_linhas_norm) > 0'
                    if titulo_oficial_norm in titulo_duas_linhas_norm and len(titulo_duas_linhas_norm) > 0:
                        encontrou_titulo_2_linhas = True
                        break 
                
                if encontrou_titulo_2_linhas:
                    prox_idx = j 
                    break 
        # --- FIM DA LÓGICA DE BUSCA ---

        linha_fim = prox_idx if prox_idx is not None else len(linhas_texto)

        conteudo = [linhas_texto[idx] for idx in range(linha_inicio_conteudo, linha_fim)]
        conteudo_final = "\n".join(conteudo).strip()
        
        return True, titulo_encontrado, conteudo_final

    return False, None, ""

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
                        # Usa .get('num_linhas_titulo', 1) para ser compatível com seu mapear_secoes
                        conteudo_mkt = "\n".join(linhas_mkt[m['linha_inicio'] + m.get('num_linhas_titulo', 1) : next_section_start])
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
            if secao_nome.upper() in [s.upper() for s in secoes_ignorar]:
                continue
            encontrou, _, conteudo = obter_dados_secao(secao_nome, mapa_secoes, linhas_texto, tipo_bula)
            if encontrou and conteudo:
                # Modificado para pegar o conteúdo todo
                texto_filtrado_para_checar.append(conteudo) 

        texto_final_para_checar = '\n'.join(texto_filtrado_para_checar)
        if not texto_final_para_checar:
            return []

        spell = SpellChecker(language='pt')
        palavras_a_ignorar = {"alair", "belfar", "peticionamento", "urotrobel", "contato"}
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

    # --- LÓGICA DE RECONSTRUÇÃO DE TEXTO CORRIGIDA ---
    # Esta lógica junta os tokens de forma mais inteligente,
    # evitando espaços antes de pontuação ou depois de quebras de linha.
    resultado = ""
    for i, tok in enumerate(marcado):
        if i == 0:
            resultado += tok
            continue

        tok_anterior_raw = re.sub(r'^<mark[^>]*>|</mark>$', '', marcado[i-1])
        raw_tok = re.sub(r'^<mark[^>]*>|</mark>$', '', tok)

        # Adiciona espaço SE:
        # O token atual NÃO é pontuação, NÃO é newline, E
        # O token anterior NÃO é newline, NÃO é parêntese de abertura
        if not re.match(r'^[.,;:!?)\]]$', raw_tok) and \
           raw_tok != '\n' and \
           tok_anterior_raw != '\n' and \
           not re.match(r'^[(\[]$', tok_anterior_raw):
            resultado += " " + tok
        else:
            resultado += tok
    # --- FIM DA CORREÇÃO ---
            
    resultado = re.sub(r"(</mark>)\s+(<mark[^>]*>)", " ", resultado)
    return resultado

# ----------------- MARCAÇÃO POR SEÇÃO COM ÍNDICES -----------------
# --- [FUNÇÃO SUBSTITUÍDA] ---
def marcar_divergencias_html(texto_original, secoes_problema, erros_ortograficos, tipo_bula, eh_referencia=False):
    # ... (início da função)
    if secoes_problema:
for diff in secoes_problema:
            conteudo_ref = diff['conteudo_anvisa']      # <-- CORRIGIDO
            conteudo_belfar = diff['conteudo_mkt']      # <-- CORRIGIDO
            conteudo_a_marcar = conteudo_ref if eh_referencia else conteudo_belfar
            conteudo_marcado = marcar_diferencas_palavra_por_palavra(
                conteudo_ref, 
                conteudo_belfar,
                eh_referencia
            )
            
            # --- [NOVA LÓGICA] ---
            # Cria o ID da âncora e envolve o conteúdo marcado com ele
            secao_canonico = diff['secao']
            anchor_id = _create_anchor_id(secao_canonico, "ref" if eh_referencia else "bel")
            # Adiciona a âncora (div) em volta do conteúdo
            # scroll-margin-top adiciona um "padding" ao rolar, para o título não ficar colado no topo
            conteudo_com_ancora = f"<div id='{anchor_id}' style='scroll-margin-top: 20px;'>{conteudo_marcado}</div>"

            # Garante que o conteúdo a marcar não seja vazio para evitar replace em todo o texto
            if conteudo_a_marcar and conteudo_a_marcar in texto_trabalho:
                # Substitui o conteúdo original pelo conteúdo marcado E com âncora
                texto_trabalho = texto_trabalho.replace(conteudo_a_marcar, conteudo_com_ancora, 1)
            # --- [FIM DA NOVA LÓGICA] ---

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

# ----------------- RELATÓRIO -----------------
# --- [FUNÇÃO SUBSTITUÍDA] ---
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
    st.info(f"ℹ️ **Datas de Aprovação ANVISA:**\n   - Referência: `{data_ref}`\n   - BELFAR: `{data_belfar}`") # Mantido seu recuo

    if secoes_faltantes:
        st.error(f"🚨 **Seções faltantes na bula BELFAR ({len(secoes_faltantes)})**:\n" + "\n".join([f"   - {s}" for s in secoes_faltantes]))
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
            
            # --- [INÍCIO DA LÓGICA DE NUMERAÇÃO] ---
            
            secao_canonico_raw = diff['secao'] # Pega o nome canônico (Ex: "QUAIS OS MALES...")
            titulo_display = diff.get('titulo_encontrado') or secao_canonico_raw
            
            if not titulo_display: 
                titulo_display = secao_canonico_raw

            # --- [NOVA LÓGICA PARA FORÇAR O NÚMERO 9] ---
            secao_canonico_norm = normalizar_texto(secao_canonico_raw)
            if "o que fazer se alguem usar uma quantidade maior" in secao_canonico_norm:
                if not normalizar_texto(titulo_display).startswith("9"):
                    titulo_display = f"9. {titulo_display}"
            # --- [FIM DA NOVA LÓGICA] ---

            with st.expander(f"📄 {titulo_display} - ❌ CONTEÚDO DIVERGENTE"):
            # --- [FIM DA LÓGICA DE NUMERAÇÃO] ---
            
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
                
                # --- [LINHA CORRIGIDA - SEM O ERRO DE SINTAXE] ---
                html_bel_box = f"<div onclick='window.handleBulaScroll(\"{anchor_id_ref}\", \"{anchor_id_bel}\")' style='{clickable_style}' title='Clique para ir à seção' onmouseover='this.style.backgroundColor=\"#f0f8ff\"' onmouseout='this.style.backgroundColor=\"#ffffff\"'>{expander_html_belfar}</div>"
                # --- [FIM DA CORREÇÃO] ---

                c1, c2 = st.columns(2)
                with c1:
                    st.markdown("**Referência:** (Clique na caixa para rolar)")
                    st.markdown(html_ref_box, unsafe_allow_html=True)
                with c2:
                    st.markdown("**BELFAR:** (Clique na caixa para rolar)")
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

    html_ref_marcado = marcar_divergencias_html(texto_original=texto_ref, secoes_problema=diferencas_conteudo, erros_ortograficos=[], tipo_bula=tipo_bula, eh_referencia=True).replace('\n', '<br>')
    html_belfar_marcado = marcar_divergencias_html(texto_original=texto_belfar, secoes_problema=diferencas_conteudo, erros_ortograficos=erros_ortograficos, tipo_bula=tipo_bula, eh_referencia=False).replace('\n', '<br>')

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

if st.button("🔍 Iniciar Auditoria Completa", use_container_width=True, type="primary"):
    if pdf_ref and pdf_belfar:
        with st.spinner("🔄 Processando e analisando as bulas..."):
            
            # Determina dinamicamente o tipo de arquivo da Anvisa
            tipo_arquivo_ref = 'docx' if pdf_ref.name.lower().endswith('.docx') else 'pdf'
            texto_ref, erro_ref = extrair_texto(pdf_ref, tipo_arquivo_ref)
            
            texto_belfar, erro_belfar = extrair_texto(pdf_belfar, 'pdf')

            if not erro_ref:
                texto_ref = truncar_apos_anvisa(texto_ref)
            if not erro_belfar:
                texto_belfar = truncar_apos_anvisa(texto_belfar)

            if erro_ref or erro_belfar:
                st.error(f"Erro ao processar arquivos: {erro_ref or erro_belfar}") # Corrigido erro de variável
            else:
                gerar_relatorio_final(texto_ref, texto_belfar, "Arquivo da Anvisa", "Arquivo Marketing", tipo_bula_selecionado)
    else:
        st.warning("⚠️ Por favor, envie ambos os arquivos para iniciar a auditoria.")

st.divider()
st.caption("Sistema de AuditorIA de Bulas v19.0 | OCR & Layout Fix")  
