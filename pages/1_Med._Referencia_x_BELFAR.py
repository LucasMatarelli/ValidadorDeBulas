# --- IMPORTS ---

import streamlit as st
# from style_utils import hide_streamlit_toolbar # Removi a dependência que não estava no código
import fitz  # PyMuPDF
import docx
import re
import spacy
from thefuzz import fuzz
from spellchecker import SpellChecker
import difflib
import unicodedata

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

# ----------------- EXTRAÇÃO -----------------
# --- [INÍCIO DA CORREÇÃO v18.27] ---
# Revertido para get_text("text") para preservar quebras de linha de tópicos
def extrair_texto(arquivo, tipo_arquivo):
    if arquivo is None:
        return "", f"Arquivo {tipo_arquivo} não enviado."
    try:
        arquivo.seek(0)
        texto = ""
        if tipo_arquivo == 'pdf':
            full_text_list = []
            with fitz.open(stream=arquivo.read(), filetype="pdf") as doc:
                for page in doc:
                    # Usa get_text("text") para preservar a formatação (quebras de linha)
                    full_text_list.append(page.get_text("text", sort=True))
            texto = "\n".join(full_text_list)
        elif tipo_arquivo == 'docx':
            doc = docx.Document(arquivo)
            texto = "\n".join([p.text for p in doc.paragraphs])
            
        if texto:
            caracteres_invisiveis = ['\u00AD', '\u200B', '\u200C', '\u200D', '\uFEFF']
            for char in caracteres_invisiveis:
                texto = texto.replace(char, '')
            texto = texto.replace('\r\n', '\n').replace('\r', '\n')
            texto = texto.replace('\u00A0', ' ')
            
            texto = re.sub(r'(\w+)-\n(\w+)', r'\1\2', texto, flags=re.IGNORECASE)

            linhas = texto.split('\n')
            padrao_rodape = re.compile(r'bula do paciente|página \d+\s*de\s*\d+', re.IGNORECASE)
            linhas_filtradas = [linha for linha in linhas if not padrao_rodape.search(linha.strip())]
            texto = "\n".join(linhas_filtradas)

            texto = re.sub(r'\n{3,}', '\n\n', texto) 
            texto = re.sub(r'[ \t]+', ' ', texto) 
            texto = texto.strip()

        return texto, None
    except Exception as e:
        return "", f"Erro ao ler o arquivo {tipo_arquivo}: {e}"
# --- [FIM DA CORREÇÃO v18.27] ---

def truncar_apos_anvisa(texto):
    if not isinstance(texto, str):
        return texto
    # --- [CORREÇÃO v18.25] --- Adiciona \s* para datas com espaço
    regex_anvisa = r"(aprovad[ao]\s+pela\s+anvisa\s+em|data\s+de\s+aprovação\s+na\s+anvisa:)\s*([\d]{1,2}\s*/\s*[\d]{1,2}\s*/\s*[\d]{2,4})"
    match = re.search(regex_anvisa, texto, re.IGNORECASE)
    if match:
        end_of_line_pos = texto.find('\n', match.end())
        if end_of_line_pos != -1:
            return texto[:end_of_line_pos]
        else:
            return texto
    return texto

# ----------------- CONFIGURAÇÃO DE SEÇÕES -----------------
# Funções de seção v18.12 (mantidas)
def obter_secoes_por_tipo(tipo_bula):
    secoes = {
        "Paciente": [
            "APRESENTAÇÕES", "COMPOSIÇÃO", "PARA QUE ESTE MEDICAMENTO É INDICADO",
            "COMO ESTE MEDICAMENTO FUNCIONA?", "QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?",
            "O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?",
            "ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?",
            "COMO DEVO USAR ESTE MEDICAMENTO?",
            "O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?",
            "QUAIS OS MALES QUE ESTE MEDICAMENTO PODE CAUSAR?",
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
        "REAÇÕES ADVERSAS": "QUAIS OS MALES QUE ESTE MEDICAMENTO PODE CAUSAR?",
        "QUAIS OS MALES QUE ESTE MEDICAMENTO PODE ME CAUSAR?": "QUAIS OS MALES QUE ESTE MEDICAMENTO PODE CAUSAR?",
        "SUPERDOSE": "O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?",
        "CUIDADOS DE ARMAZENAMENTO DO MEDICAMENTO": "ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?"
    }

def obter_secoes_ignorar_ortografia():
    return ["COMPOSIÇÃO", "DIZERES LEGAIS"]

# --- [CORREÇÃO v18.17] ---
def obter_secoes_ignorar_comparacao():
    # Removida a Seção 5 ("ONDE...") da lista de ignorados
    return ["COMPOSIÇÃO", "DIZERES LEGAIS", "APRESENTAÇÕES"]
# --- [FIM DA CORREÇÃO] ---

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


# --- [INÍCIO DA FUNÇÃO (v18.25) - CORRIGIDA] ---
def corrigir_quebras_em_titulos(texto, tipo_bula):
    """
    Corrige títulos que foram quebrados em múltiplas linhas (ex: "COMPOSIÇÃO"
    em uma linha e "DO MEDICAMENTO" em outra) juntando-os.
    Preserva quebras de parágrafo (\n\n) e quebras de linha de conteúdo.
    """
    linhas = texto.split("\n")
    linhas_corrigidas = []
    buffer = ""

    # Pega a lista de títulos conhecidos para checagem
    secoes_base = obter_secoes_por_tipo(tipo_bula)
    aliases = obter_aliases_secao()
    secoes_conhecidas_norm = {normalizar_titulo_para_comparacao(s) for s in secoes_base + list(aliases.keys())}
    
    for linha in linhas:
        linha_strip = linha.strip()

        if not linha_strip:
            if buffer: 
                linhas_corrigidas.append(buffer)
                buffer = ""
            linhas_corrigidas.append("") 
            continue
        
        # Checa se é um TÍTULO COMPLETO conhecido
        linha_norm = normalizar_titulo_para_comparacao(linha_strip)
        eh_titulo_conhecido = False
        if is_titulo_secao(linha_strip): # Usa o checker básico primeiro
             for s_norm in secoes_conhecidas_norm:
                if fuzz.ratio(linha_norm, s_norm) > 95:
                    eh_titulo_conhecido = True
                    break
        
        # Checa se é um FRAGMENTO de título (curto, maiúsculo, poucas palavras)
        eh_fragmento = (
            linha_strip.isupper() and 
            len(linha_strip.split()) < 5 and 
            len(linha_strip) < 35 # Mais restritivo
        )
        
        if eh_titulo_conhecido:
            if buffer: linhas_corrigidas.append(buffer) # Descarrega o buffer anterior
            buffer = linha_strip # Começa um novo título
        
        elif buffer and eh_fragmento: # É um fragmento e estamos em um buffer
            buffer += " " + linha_strip # Junta ao título
            
        else: # É linha de conteúdo
            if buffer: linhas_corrigidas.append(buffer); buffer = "" # Descarrega o título
            linhas_corrigidas.append(linha_strip) # Adiciona o conteúdo
    
    if buffer: linhas_corrigidas.append(buffer)
    return "\n".join(linhas_corrigidas)
# --- [FIM DA FUNÇÃO] ---


# ----------------- ARQUITETURA DE MAPEAMENTO DE SEÇÕES -----------------
# Funções de mapeamento v18.15 (mantidas)
def is_titulo_secao(linha):
    linha = linha.strip()
    if len(linha) < 4:
        return False
    if re.match(r'^\d+\.\s+[A-Z]', linha): # Ex: 9. O QUE FAZER...
        return True
    if len(linha.split()) > 20:
        return False
    if linha.endswith('.') or linha.endswith(':'):
        return False
    if re.search(r'>\s*<', linha):
        return False
    if len(linha) > 100: 
        return False
    
    if linha.isupper():
        return True
    
    upper_chars = sum(1 for c in linha if c.isupper())
    lower_chars = sum(1 for c in linha if c.islower())
    
    if upper_chars > lower_chars and lower_chars < 10:
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

    for idx, linha in enumerate(linhas):
        linha_limpa = linha.strip()
        
        if not is_titulo_secao(linha_limpa):
            continue

        linha_norm = normalizar_texto(linha_limpa)
        if not linha_norm:
            continue

        best_match_score = 0
        best_match_canonico = None

        for titulo_possivel, titulo_canonico in titulos_possiveis.items():
            score = fuzz.token_set_ratio(normalizar_titulo_para_comparacao(titulo_possivel), normalizar_titulo_para_comparacao(linha_limpa))
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

def obter_dados_secao(secao_canonico, mapa_secoes, linhas_texto, tipo_bula):
    TITULOS_OFICIAIS = {
        "Paciente": [
            "APRESENTAÇÕES", "COMPOSIÇÃO", "PARA QUE ESTE MEDICAMENTO É INDICADO",
            "COMO ESTE MEDICAMENTO FUNCIONA?", "QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?",
            "O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?",
            "ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?",
            "COMO DEVO USAR ESTE MEDICAMENTO?",
            "O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?",
            "QUAIS OS MALES QUE ESTE MEDICAMENTO PODE CAUSAR?",
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
    titulos_norm_set = {normalizar_titulo_para_comparacao(t) for t in titulos_lista}
    
    aliases = obter_aliases_secao()
    for alias, canonico in aliases.items():
        if canonico in titulos_lista:
                titulos_norm_set.add(normalizar_titulo_para_comparacao(alias))


    for i, secao_mapa in enumerate(mapa_secoes):
        if secao_mapa['canonico'] != secao_canonico:
            continue

        titulo_encontrado = secao_mapa['titulo_encontrado']
        linha_inicio = secao_mapa['linha_inicio']
        linha_inicio_conteudo = linha_inicio + 1

        prox_idx = None
        for j in range(linha_inicio_conteudo, len(linhas_texto)):
            linha_atual = linhas_texto[j].strip()
            linha_atual_norm = normalizar_titulo_para_comparacao(linha_atual)
            
            if linha_atual_norm in titulos_norm_set:
                prox_idx = j 
                break 

        linha_fim = prox_idx if prox_idx is not None else len(linhas_texto)

        conteudo = [linhas_texto[idx] for idx in range(linha_inicio_conteudo, linha_fim)]
        conteudo_final = "\n".join(conteudo).strip()
        return True, titulo_encontrado, conteudo_final

    return False, None, ""

# ----------------- COMPARAÇÃO DE CONTEÚDO -----------------

# --- [FUNÇÃO (v18.16) - MANTIDA] ---
# Retorna 'relatorio_completo'
def verificar_secoes_e_conteudo(texto_ref, texto_belfar, tipo_bula):
    secoes_esperadas = obter_secoes_por_tipo(tipo_bula)
    secoes_faltantes = []
    diferencas_titulos = []
    similaridade_geral = []
    relatorio_completo = [] 
    
    secoes_ignorar_upper = [s.upper() for s in obter_secoes_ignorar_comparacao()]

    linhas_ref = texto_ref.split('\n')
    linhas_belfar = texto_belfar.split('\n')
    mapa_ref = mapear_secoes(texto_ref, secoes_esperadas)
    mapa_belfar = mapear_secoes(texto_belfar, secoes_esperadas)

    secoes_belfar_encontradas = {m['canonico']: m for m in mapa_belfar}

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
                relatorio_completo.append({
                    'secao': secao,
                    'status': 'faltante',
                    'conteudo_ref': conteudo_ref,
                    'conteudo_belfar': "",
                    'titulo_encontrado': None
                })
                continue

        if encontrou_ref and encontrou_belfar:
            secao_comp = normalizar_titulo_para_comparacao(secao)
            titulo_real_encontrado = titulo_belfar if titulo_belfar else melhor_titulo
            titulo_belfar_comp = normalizar_titulo_para_comparacao(titulo_real_encontrado)

            if secao_comp != titulo_belfar_comp:
                if not any(d['secao_esperada'] == secao for d in diferencas_titulos):
                    diferencas_titulos.append({'secao_esperada': secao, 'titulo_encontrado': titulo_real_encontrado})

            if secao.upper() in secoes_ignorar_upper:
                similaridade_geral.append(100)
                relatorio_completo.append({
                    'secao': secao,
                    'status': 'ignorada',
                    'conteudo_ref': conteudo_ref,
                    'conteudo_belfar': conteudo_belfar,
                    'titulo_encontrado': titulo_real_encontrado
                })
                continue

            if normalizar_texto(conteudo_ref) != normalizar_texto(conteudo_belfar):
                relatorio_completo.append({
                    'secao': secao,
                    'status': 'diferente',
                    'conteudo_ref': conteudo_ref,
                    'conteudo_belfar': conteudo_belfar,
                    'titulo_encontrado': titulo_real_encontrado
                })
                similaridade_geral.append(0)
            else:
                relatorio_completo.append({
                    'secao': secao,
                    'status': 'identica',
                    'conteudo_ref': conteudo_ref,
                    'conteudo_belfar': conteudo_belfar,
                    'titulo_encontrado': titulo_real_encontrado
                })
                similaridade_geral.append(100)

    return secoes_faltantes, relatorio_completo, similaridade_geral, diferencas_titulos
# --- [FIM DA FUNÇÃO] ---


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
                linhas_conteudo = conteudo.split('\n')
                if len(linhas_conteudo) > 1:
                    texto_filtrado_para_checar.append('\n'.join(linhas_conteudo[1:]))

        texto_final_para_checar = '\n'.join(texto_filtrado_para_checar)
        if not texto_final_para_checar:
            return []

        spell = SpellChecker(language='pt')
        palavras_a_ignorar = {"alair", "belfar", "peticionamento", "urotrobel"}
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

# --- [INÍCIO DA CORREÇÃO v18.27] ---
# Corrigido para ignorar \n na comparação de diff, evitando falsos positivos
def marcar_diferencas_palavra_por_palavra(texto_ref, texto_belfar, eh_referencia):
    if texto_ref is None: texto_ref = ""
    if texto_belfar is None: texto_belfar = ""

    def tokenizar(txt):
        return re.findall(r'\n|[A-Za-zÀ-ÖØ-öø-ÿ0-9_]+|[^\w\s]', txt, re.UNICODE)

    def norm(tok):
        # Apenas normaliza palavras, mantém outros tokens (como pontuação)
        if re.match(r'[A-Za-zÀ-ÖØ-öø-ÿ0-9_]+$', tok):
            return normalizar_texto(tok)
        return tok

    ref_tokens = tokenizar(texto_ref)
    bel_tokens = tokenizar(texto_belfar)
    
    # CRÍTICO: Filtra os \n ANTES de passar para o SequenceMatcher
    ref_norm = [norm(t) for t in ref_tokens if t != '\n']
    bel_norm = [norm(t) for t in bel_tokens if t != '\n']

    matcher = difflib.SequenceMatcher(None, ref_norm, bel_norm, autojunk=False)
    
    # Mapeia os índices do diff (sem \n) de volta para os tokens originais (com \n)
    def map_indices_to_original_tokens(tokens, norm_tokens, tag, i1, i2, j1, j2):
        # Converte índices normalizados (i1, i2) para índices de token (com \n)
        def convert_norm_idx_to_token_idx(tokens, norm_idx):
            norm_count = 0
            for token_idx, token in enumerate(tokens):
                if token == '\n':
                    continue
                if norm_count == norm_idx:
                    return token_idx
                norm_count += 1
            return len(tokens) # Se não encontrar, retorna o final

        if eh_referencia:
            token_start = convert_norm_idx_to_token_idx(ref_tokens, i1)
            token_end = convert_norm_idx_to_token_idx(ref_tokens, i2)
            return range(token_start, token_end)
        else:
            token_start = convert_norm_idx_to_token_idx(bel_tokens, j1)
            token_end = convert_norm_idx_to_token_idx(bel_tokens, j2)
            return range(token_start, token_end)

    indices = set()
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != 'equal':
            indices.update(map_indices_to_original_tokens(
                ref_tokens if eh_referencia else bel_tokens,
                ref_norm if eh_referencia else bel_norm,
                tag, i1, i2, j1, j2
            ))

    tokens = ref_tokens if eh_referencia else bel_tokens
    marcado = []
    for idx, tok in enumerate(tokens):
        if idx in indices and tok.strip() != '':
            marcado.append(f"<mark style='background-color: #ffff99; padding: 2px;'>{tok}</mark>")
        else:
            marcado.append(tok)

    # Lógica de re-join (mantida)
    resultado = ""
    for i, tok in enumerate(tokens): 
        if i == 0:
            resultado += marcado[i] 
            continue
        
        raw_tok_anterior = tokens[i-1] 
        raw_tok = tokens[i]

        if not re.match(r'^[.,;:!?)\\]$', raw_tok) and \
           raw_tok != '\n' and \
           raw_tok_anterior != '\n' and \
           not re.match(r'^[(\\[]$', raw_tok_anterior):
            resultado += " " + marcado[i] 
        else:
            resultado += marcado[i] 
            
    resultado = re.sub(r"(</mark>)\s+(<mark[^>]*>)", " ", resultado)
    return resultado
# --- [FIM DA CORREÇÃO v18.27] ---

# ----------------- MARCAÇÃO POR SEÇÃO COM ÍNDICES -----------------

def marcar_divergencias_html(texto_original, relatorio_completo, erros_ortograficos, tipo_bula, eh_referencia=False):
    texto_trabalho = texto_original
    if texto_trabalho is None: texto_trabalho = ""
    
    if relatorio_completo:
        for diff in relatorio_completo:
            if diff['status'] != 'diferente':
                continue

            conteudo_ref = diff['conteudo_ref']
            conteudo_belfar = diff['conteudo_belfar']
            conteudo_a_marcar = conteudo_ref if eh_referencia else conteudo_belfar
            
            if conteudo_a_marcar is None: continue

            conteudo_marcado = marcar_diferencas_palavra_por_palavra(
                conteudo_ref,
                conteudo_belfar,
                eh_referencia
            )
            
            secao_canonico = diff['secao']
            anchor_id = _create_anchor_id(secao_canonico, "ref" if eh_referencia else "bel")
            conteudo_com_ancora = f"<div id='{anchor_id}' style='scroll-margin-top: 20px;'>{conteudo_marcado}</div>"

            if conteudo_a_marcar and conteudo_a_marcar in texto_trabalho:
                try:
                    texto_trabalho = texto_trabalho.replace(conteudo_a_marcar, conteudo_com_ancora, 1)
                except re.error: 
                    pass 

    if erros_ortograficos and not eh_referencia:
        for erro in erros_ortograficos:
            pattern = r'\b(' + re.escape(erro) + r')\b(?![^<]*?>)'
            texto_trabalho = re.sub(
                pattern,
                r"<mark style='background-color: #FFDDC1; padding: 2px;'>\1</mark>",
                texto_trabalho,
                flags=re.IGNORECASE
            )
            
    # --- [INÍCIO DA CORREÇÃO v18.25] ---
    # Adiciona \s* para permitir espaços na data (ex: 05 / 02 / 2025)
    regex_anvisa = r"((?:aprovad[ao]\s+pela\s+anvisa\s+em|data\s+de\s+aprovação\s+na\s+anvisa:)\s*[\d]{1,2}\s*/\s*[\d]{1,2}\s*/\s*[\d]{2,4})"
    # --- [FIM DA CORREÇÃO v18.25] ---
    
    def remove_marks_da_data(match):
        frase_anvisa = match.group(1)
        frase_limpa = re.sub(r'<mark.*?>|</mark>', '', frase_anvisa) 
        return f"<mark style='background-color: #cce5ff; padding: 2px; font-weight: 500;'>{frase_limpa}</mark>"

    # Aplica a marcação azul da data ANVISA
    texto_trabalho = re.sub(
        regex_anvisa,
        remove_marks_da_data,
        texto_trabalho,
        count=1, # Aplica apenas na primeira ocorrência
        flags=re.IGNORECASE
    )

    return texto_trabalho


# --- [FUNÇÃO DE LAYOUT (v18.27) - CORRIGIDA PARA TÓPICOS] ---
def formatar_html_para_leitura(html_content, tipo_bula, aplicar_numeracao=False):
    if html_content is None:
        return ""

    # 1. Normaliza quebras múltiplas
    html_content = re.sub(r'\n{2,}', '[[PARAGRAPH]]', html_content)

    # 2. Pega os títulos
    titulos_base = obter_secoes_por_tipo(tipo_bula)
    aliases = list(obter_aliases_secao().keys())
    titulos_unicos = sorted(list(set(titulos_base + aliases)), key=len, reverse=True)
    
    # 3. Formata Títulos e Tópicos
    linhas_formatadas = []
    # Regex para Tópicos (inclui hífen, traço, bullet e o 'minus sign' da Belfar)
    topic_regex = re.compile(r'^\s*[-–•*−]')
    
    for linha in html_content.split('\n'):
        linha_strip = linha.strip()
        
        if not linha_strip: 
            linhas_formatadas.append(linha) # Preserva quebra de parágrafo original
            continue
        
        # Testa se a linha é um título
        titulo_limpo = re.sub(r'</?mark[^>]*>', '', linha_strip, flags=re.IGNORECASE)
        titulo_limpo = re.sub(r'\s+', ' ', titulo_limpo).strip()
        
        eh_titulo = False
        if is_titulo_secao(titulo_limpo): 
             for t_check in titulos_unicos:
                if fuzz.ratio(normalizar_texto(t_check), normalizar_texto(titulo_limpo)) > 95:
                    eh_titulo = True
                    break
        
        if eh_titulo:
            linhas_formatadas.append(f"[[PARAGRAPH]]<strong>{linha_strip}</strong>")
        
        # Testa se é um tópico (graças ao get_text("text"), o tópico estará no início da linha)
        elif topic_regex.search(linha_strip):
            linhas_formatadas.append(f"[[LIST_ITEM]]{linha_strip}")
        
        else:
            # É uma linha de conteúdo normal
            linhas_formatadas.append(linha)

    html_content = "\n".join(linhas_formatadas)

    # 4. Lista e quebras (LÓGICA CORRIGIDA)
    # O que sobrou de \n é texto contínuo, vira espaço
    html_content = html_content.replace('\n', ' ') 
    
    # Substitui os placeholders
    html_content = html_content.replace('[[PARAGRAPH]]', '<br><br>') # Restaura parágrafos
    html_content = html_content.replace('[[LIST_ITEM]]', '<br>') # Restaura quebras de TÓPICO
    
    # 5. Limpeza final
    html_content = re.sub(r'(<br\s*/?>\s*){3,}', '<br><br>', html_content) 
    html_content = re.sub(r'(<br><br>\s*)+<strong>', r'<br><br><strong>', html_content) 
    html_content = re.sub(r'\s{2,}', ' ', html_content) 
    # Remove <br> indesejados antes de tópicos que seguem títulos
    html_content = re.sub(r'(<strong>.*?</strong>)(\s*<br>\s*)(<br>\s*[-–•*−])', r'\1\3', html_content)
    # Limpa <br> que pode ter sobrado de um \n entre o : e o primeiro tópico
    html_content = re.sub(r'(:)(\s*<br>\s*)(<br>\s*[-–•*−])', r'\1\3', html_content)
    html_content = re.sub(r'\s+<br>', '<br>', html_content)

    return html_content
# --- [FIM DA FUNÇÃO DE LAYOUT] ---


# ----------------- RELATÓRIO -----------------

def gerar_relatorio_final(texto_ref, texto_belfar, nome_ref, nome_belfar, tipo_bula):
    
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


    st.header("Relatório de Auditoria Inteligente")
    regex_anvisa = r"(aprovad[ao]\s+pela\s+anvisa\s+em|data\s+de\s+aprovação\s+na\s+anvisa:)\s*([\d]{1,2}\s*/\s*[\d]{1,2}\s*/\s*[\d]{2,4})"
    match_ref = re.search(regex_anvisa, texto_ref.lower())
    match_belfar = re.search(regex_anvisa, texto_belfar.lower())
    data_ref = match_ref.group(2).strip() if match_ref else "Não encontrada"
    data_belfar = match_belfar.group(2).strip() if match_belfar else "Não encontrada"

    secoes_faltantes, relatorio_completo, similaridades, diferencas_titulos = verificar_secoes_e_conteudo(texto_ref, texto_belfar, tipo_bula)
    
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
    st.info(f"ℹ️ **Datas de Aprovação ANVISA:**\n - Referência: `{data_ref}`\n - BELFAR: `{data_belfar}`")

    if secoes_faltantes:
        st.error(f"🚨 **Seções faltantes na bula BELFAR ({len(secoes_faltantes)})**:\n" + "\n".join([f" - {s}" for s in secoes_faltantes]))
    else:
        st.success("✅ Todas as seções obrigatórias estão presentes")
        
    st.subheader("Análise de Conteúdo Seção por Seção")
    
    expander_caixa_style = (
        "height: 350px; overflow-y: auto; border: 2px solid #d0d0d0; border-radius: 6px; "
        "padding: 16px; background-color: #ffffff; font-size: 14px; line-height: 1.8; "
        "font-family: 'Georgia', 'Times New Roman', serif; text-align: justify; "
        "white-space: normal; overflow-wrap: break-word;"
    )

    for item in relatorio_completo:
        secao_canonico_raw = item['secao']
        status = item['status']
        
        titulo_display = item.get('titulo_encontrado') or secao_canonico_raw
        if not titulo_display:
            titulo_display = secao_canonico_raw
        
        secao_canonico_norm = normalizar_texto(secao_canonico_raw)
        if "o que fazer se alguem usar uma quantidade maior" in secao_canonico_norm:
            if not normalizar_texto(titulo_display).startswith("9"):
                titulo_display = f"9. {titulo_display}"
        
        if status == 'diferente':
            expander_title = f"📄 {titulo_display} - ❌ CONTEÚDO DIVERGENTE"
        elif status == 'ignorada':
            expander_title = f"📄 {titulo_display} - ℹ️ IGNORADA (Regra de Negócio)"
        else: # 'identica'
            expander_title = f"📄 {titulo_display} - ✅ CONTEÚDO IDÊNTICO"

        with st.expander(expander_title):
            secao_canonico = item['secao']
            anchor_id_ref = _create_anchor_id(secao_canonico, "ref")
            anchor_id_bel = _create_anchor_id(secao_canonico, "bel")
            
            conteudo_ref_bruto = item['conteudo_ref']
            conteudo_belfar_bruto = item['conteudo_belfar']

            # --- [INÍCIO DA CORREÇÃO v18.26] ---
            if status == 'diferente':
                # Só marca com amarelo se for diferente
                html_ref_bruto_expander = marcar_diferencas_palavra_por_palavra(
                    conteudo_ref_bruto, conteudo_belfar_bruto, eh_referencia=True
                )
                html_belfar_bruto_expander = marcar_diferencas_palavra_por_palavra(
                    conteudo_ref_bruto, conteudo_belfar_bruto, eh_referencia=False
                )
            else:
                # Se for 'identica' ou 'ignorada', apenas passa o texto cru
                html_ref_bruto_expander = conteudo_ref_bruto
                html_belfar_bruto_expander = conteudo_belfar_bruto
            # --- [FIM DA CORREÇÃO v18.26] ---

            expander_html_ref = formatar_html_para_leitura(html_ref_bruto_expander, tipo_bula, aplicar_numeracao=True)
            expander_html_belfar = formatar_html_para_leitura(html_belfar_bruto_expander, tipo_bula, aplicar_numeracao=False)
            
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

    if erros_ortograficos:
        st.info(f"📝 **Possíveis erros ortográficos ({len(erros_ortograficos)} palavras):**\n" + ", ".join(erros_ortograficos))

    diferencas_encontradas = any(item['status'] == 'diferente' for item in relatorio_completo)

    if not any([secoes_faltantes, diferencas_encontradas, diferencas_titulos]) and len(erros_ortograficos) < 5:
        st.success("🎉 **Bula aprovada!** Nenhum problema crítico encontrado.")

    st.divider()
    st.subheader("🎨 Visualização Lado a Lado com Destaques")
    st.markdown(
        "**Legenda:** <mark style='background-color: #ffff99; padding: 2px;'>Amarelo</mark> = Divergências | "
        "<mark style='background-color: #FFDDC1; padding: 2px;'>Rosa</mark> = Erros ortográficos | "
        "<mark style='background-color: #cce5ff; padding: 2px;'>Azul</mark> = Data ANVISA",
        unsafe_allow_html=True
    )

    html_ref_bruto = marcar_divergencias_html(
        texto_original=texto_ref, relatorio_completo=relatorio_completo, erros_ortograficos=[], tipo_bula=tipo_bula, eh_referencia=True
    )
    html_belfar_bruto = marcar_divergencias_html(
        texto_original=texto_belfar, relatorio_completo=relatorio_completo, erros_ortograficos=erros_ortograficos, tipo_bula=tipo_bula, eh_referencia=False
    )
    
    html_ref_marcado = formatar_html_para_leitura(html_ref_bruto, tipo_bula, aplicar_numeracao=True)
    html_belfar_marcado = formatar_html_para_leitura(html_belfar_bruto, tipo_bula, aplicar_numeracao=False)

    caixa_style = (
        "height: 700px; overflow-y: auto; border: 1px solid #ddd; border-radius: 8px; "
        "padding: 24px 32px; background-color: #ffffff; "
        "font-family: '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Roboto', 'Helvetica', 'Arial', 'sans-serif'; font-size: 15px; "
        "line-height: 1.7; box-shadow: 0 4px 12px rgba(0,0,0,0.08); "
        "text-align: justify; color: #333333; "
        "white-space: normal; overflow-wrap: break-word;"
    )
    
    col1, col2 = st.columns(2, gap="medium")
    with col1:
        st.markdown(f"**📄 {nome_ref}**")
        st.markdown(f"<div id='container-ref-scroll' style='{caixa_style}'>{html_ref_marcado}</div>", unsafe_allow_html=True)
    with col2:
        st.markdown(f"**📄 {nome_belfar}**")
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
    st.subheader("📄 Med. Referência")
    pdf_ref = st.file_uploader("Envie o PDF ou DOCX de referência", type=["pdf", "docx"], key="ref")
with col2:
    st.subheader("📄 Med. BELFAR")
    pdf_belfar = st.file_uploader("Envie o PDF ou DOCX Belfar", type=["pdf", "docx"], key="belfar")

if st.button("🔍 Iniciar Auditoria Completa", use_container_width=True, type="primary"):
    if pdf_ref and pdf_belfar:
        with st.spinner("🔄 Processando e analisando as bulas..."):
            
            tipo_ref = 'docx' if pdf_ref.name.endswith('.docx') else 'pdf'
            tipo_belfar = 'docx' if pdf_belfar.name.endswith('.docx') else 'pdf'
            
            texto_ref, erro_ref = extrair_texto(pdf_ref, tipo_ref)
            texto_belfar, erro_belfar = extrair_texto(pdf_belfar, tipo_belfar)

            # --- [INÍCIO DA MODIFICAÇÃO v18.25] ---
            # Chama a função de correção de títulos aqui (agora passa o tipo_bula)
            if not erro_ref:
                texto_ref = corrigir_quebras_em_titulos(texto_ref, tipo_bula_selecionado)
                texto_ref = truncar_apos_anvisa(texto_ref)
            if not erro_belfar:
                texto_belfar = corrigir_quebras_em_titulos(texto_belfar, tipo_bula_selecionado)
                texto_belfar = truncar_apos_anvisa(texto_belfar)
            # --- [FIM DA MODIFICAÇÃO v18.25] ---

            if erro_ref or erro_belfar:
                st.error(f"Erro ao processar arquivos: {erro_ref or erro_belfar}")
            elif not texto_ref or not texto_belfar:
                st.error("Erro: Um dos arquivos está vazio ou não pôde ser lido corretamente.")
            else:
                gerar_relatorio_final(texto_ref, texto_belfar, "Bula Referência", "Bula BELFAR", tipo_bula_selecionado)
    else:
        st.warning("⚠️ Por favor, envie ambos os arquivos PDF ou DOCX para iniciar a auditoria.")

st.divider()
st.caption("Sistema de Auditoria de Bulas v18.27 | Correção Extração de Texto (tópicos), Data ANVISA (Regex) e Falsos Positivos")
