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
# Lógica de extração v18.12 (mantida)
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
                    blocks = page.get_text("blocks", sort=True) 
                    page_text = "".join([b[4] for b in blocks])
                    full_text_list.append(page_text)
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

def obter_secoes_ignorar_comparacao():
    return ["COMPOSIÇÃO", "DIZERES LEGAIS", "APRESENTAÇÕES", "ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?"]

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

# ----------------- ARQUITETURA DE MAPEAMENTO DE SEÇÕES -----------------
# Funções de mapeamento v18.12 (mantidas)
def is_titulo_secao(linha):
    linha = linha.strip()
    if len(linha) < 4:
        return False
    if len(linha.split()) > 20:
        return False
    if linha.endswith('.') or linha.endswith(':'):
        return False
    if re.search(r'\>\s*\<', linha):
        return False
    if len(linha) > 120:
        return False
    return True

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

            if (j + 1) < len(linhas_texto):
                linha_seguinte = linhas_texto[j + 1].strip()
                titulo_duas_linhas = f"{linha_atual} {linha_seguinte}"
                titulo_duas_linhas_norm = normalizar_titulo_para_comparacao(titulo_duas_linhas)

                if titulo_duas_linhas_norm in titulos_norm_set:
                    prox_idx = j 
                    break 

            if (j + 2) < len(linhas_texto):
                linha_seguinte = linhas_texto[j + 1].strip()
                linha_terceira = linhas_texto[j + 2].strip()
                
                titulo_tres_linhas = f"{linha_atual} {linha_seguinte} {linha_terceira}"
                titulo_tres_linhas_norm = normalizar_titulo_para_comparacao(titulo_tres_linhas)

                if titulo_tres_linhas_norm in titulos_norm_set:
                    prox_idx = j 
                    break 

        linha_fim = prox_idx if prox_idx is not None else len(linhas_texto)

        conteudo = [linhas_texto[idx] for idx in range(linha_inicio_conteudo, linha_fim)]
        conteudo_final = "\n".join(conteudo).strip()
        return True, titulo_encontrado, conteudo_final

    return False, None, ""

# ----------------- COMPARAÇÃO DE CONTEÚDO -----------------

def verificar_secoes_e_conteudo(texto_ref, texto_belfar, tipo_bula):
    secoes_esperadas = obter_secoes_por_tipo(tipo_bula)
    secoes_faltantes, diferencas_conteudo, similaridades_secoes, diferencas_titulos = [], [], [], []
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
                continue

        if encontrou_ref and encontrou_belfar:
            secao_comp = normalizar_titulo_para_comparacao(secao)
            titulo_belfar_comp = normalizar_titulo_para_comparacao(titulo_belfar if titulo_belfar else melhor_titulo)

            if secao_comp != titulo_belfar_comp:
                if not any(d['secao_esperada'] == secao for d in diferencas_titulos):
                    diferencas_titulos.append({'secao_esperada': secao, 'titulo_encontrado': titulo_belfar if titulo_belfar else melhor_titulo})

            if secao.upper() in secoes_ignorar_upper:
                continue

            if normalizar_texto(conteudo_ref) != normalizar_texto(conteudo_belfar):
                
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

def marcar_diferencas_palavra_por_palavra(texto_ref, texto_belfar, eh_referencia):
    def tokenizar(txt):
        return re.findall(r'\n|[A-Za-zÀ-ÖØ-öø-ÿ0-9_]+|[^\w\s]', txt, re.UNICODE)

    def norm(tok):
        if tok == '\n':
            return ' ' 
        
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
    for i, tok in enumerate(tokens): # Modificado para iterar sobre 'tokens' e não 'marcado'
        if i == 0:
            resultado += marcado[i] # Adiciona o token (marcado ou não)
            continue
        
        # Pega o token original (sem marcação) para checagem
        raw_tok_anterior = tokens[i-1] 
        raw_tok = tokens[i]

        if not re.match(r'^[.,;:!?)\\]$', raw_tok) and \
           raw_tok != '\n' and \
           raw_tok_anterior != '\n' and \
           not re.match(r'^[(\\[]$', raw_tok_anterior):
            resultado += " " + marcado[i] # Adiciona o token (marcado ou não)
        else:
            resultado += marcado[i] # Adiciona o token (marcado ou não)
            
    resultado = re.sub(r"(</mark>)\s+(<mark[^>]*>)", " ", resultado)
    return resultado

# ----------------- MARCAÇÃO POR SEÇÃO COM ÍNDICES -----------------

def marcar_divergencias_html(texto_original, secoes_problema, erros_ortograficos, tipo_bula, eh_referencia=False):
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

            # Adiciona checagem 'if conteudo_a_marcar' para evitar erro em seções vazias
            if conteudo_a_marcar and conteudo_a_marcar in texto_trabalho:
                texto_trabalho = texto_trabalho.replace(conteudo_a_marcar, conteudo_com_ancora)

    if erros_ortograficos and not eh_referencia:
        for erro in erros_ortograficos:
            # Regex atualizado para não marcar dentro de tags HTML (evita quebrar <mark>)
            pattern = r'\b(' + re.escape(erro) + r')\b(?![^<]*?>)'
            texto_trabalho = re.sub(
                pattern,
                r"<mark style='background-color: #FFDDC1; padding: 2px;'>\1</mark>",
                texto_trabalho,
                flags=re.IGNORECASE
            )
            
    regex_anvisa = r"((?:aprovad[ao]\s+pela\s+anvisa\s+em|data\s+de\s+aprovação\s+na\s+anvisa:)\s*[\d]{1,2}/[\d]{1,2}/[\d]{2,4})"
    
    # Função helper para garantir que a marcação da data não seja quebrada por outras marcações
    def remove_marks_da_data(match):
        frase_anvisa = match.group(1)
        frase_limpa = re.sub(r'<mark.*?>|</mark>', '', frase_anvisa) # Limpa marks de ortografia/diferença
        return f"<mark style='background-color: #cce5ff; padding: 2px; font-weight: 500;'>{frase_limpa}</mark>"

    texto_trabalho = re.sub(
        regex_anvisa,
        remove_marks_da_data,
        texto_trabalho,
        count=1,
        flags=re.IGNORECASE
    )

    return texto_trabalho


# --- [INÍCIO DA FUNÇÃO DE LAYOUT MODIFICADA] ---
# (Baseada na v26.58 que você enviou)
def formatar_html_para_leitura(html_content, tipo_bula, aplicar_numeracao=False):
    """
    Recebe html_content (texto que pode conter quebras '\n' e marcações)
    e transforma em HTML de leitura (com <br><br>, strong, etc.).
    """
    if html_content is None:
        return ""

    # 1. Normaliza quebras múltiplas no formato temporário
    html_content = re.sub(r'\n{2,}', '[[PARAGRAPH]]', html_content)

    # 2. Pega os títulos que este script (v18.12) conhece
    titulos_base = obter_secoes_por_tipo(tipo_bula)
    aliases = list(obter_aliases_secao().keys())
    # Remove duplicados e garante que os mais longos sejam processados primeiro
    titulos_unicos = sorted(list(set(titulos_base + aliases)), key=len, reverse=True)

    # 3. Cria padrões regex robustos para os títulos (ignora <mark> e números)
    titulos_lista = []
    for t in titulos_unicos:
        # Escapa caracteres como '?'
        t_escaped = re.escape(t)
        
        # --- [INÍCIO DA CORREÇÃO] ---
        # O erro estava aqui. \s é um escape inválido em strings de *substituição* re.
        # Precisamos usar \\s para que o re.sub entenda como "literal \s".
        t_regex = re.sub(r'([A-ZÀ-ÖØ-Þ])', r'(?:<[^>]+>)*\\s*\1', t_escaped, flags=re.IGNORECASE)
        # --- [FIM DA CORREÇÃO] ---
        
        t_regex = re.sub(r'\\ ', r'\\s+', t_regex) # Permite múltiplos espaços
        
        # Padrão final: (Início de linha ou Parágrafo) + (Opcional Num. e Ponto) + (Título com marks) + (Fim de linha ou Parágrafo)
        pattern = rf'(^|\[\[PARAGRAPH\]\])\s*(\d+\.\s*)?({t_regex})\s*($|\[\[PARAGRAPH\]\]|\n)'
        titulos_lista.append(pattern)


    # Sub-função para aplicar o negrito e a quebra de parágrafo
    def aplicar_formatacao_titulo(match):
        inicio = match.group(1) # ^ ou [[PARAGRAPH]]
        numero_opcional = match.group(2) or "" # "1. " ou ""
        titulo_capturado = match.group(3) # O título em si
        fim = match.group(4) # $ ou [[PARAGRAPH]] ou \n

        # Limpa o título de tags <mark> APENAS para re-aplicar o strong
        # (O conteúdo das tags <mark> é preservado)
        titulo_limpo = re.sub(r'</?mark[^>]*>', '', titulo_capturado, flags=re.IGNORECASE)
        # Remove espaços extras causados pelo regex
        titulo_limpo_sem_espaco = re.sub(r'\s+', ' ', titulo_limpo).strip()
        
        # Reconstrói o título com o número (se aplicar_numeracao=True e ele existir)
        # No v18.12, preferimos não forçar a numeração, apenas manter se existir.
        titulo_final = f"{numero_opcional}{titulo_limpo_sem_espaco}"

        # A MÁGICA: Garante a quebra de parágrafo ANTES do título
        return f'{inicio}<strong>{titulo_final}</strong>{fim}'

    # 4. Aplica a formatação de título
    # (Itera para evitar sobreposição complexa de regex)
    # Esta lógica é mais simples que a v26.58 mas resolve o "grudado"
    
    # Primeiro, marca todos os títulos com <strong> e [[PARAGRAPH]]
    # Usamos placeholders para evitar quebra de linha dupla
    
    # Regex simplificado para encontrar títulos do nosso script (v18.12)
    # Pega todos os títulos e cria um grande regex (ex: TÍTULO A|TÍTULO B|...)
    titulos_regex_base = []
    for t in titulos_unicos:
        t_escaped = re.escape(t)
        t_regex = re.sub(r'\\ ', r'\\s+', t_escaped)
        t_regex_sem_pontuacao = t_regex.replace(r'\?', r'') # Remove '?' para match mais amplo
        titulos_regex_base.append(t_regex_sem_pontuacao)

    # (COMPOSIÇÃO|APRESENTAÇÕES|PARA QUE ESTE...)
    pattern_todos_titulos = r'(' + r'|'.join(titulos_regex_base) + r')'
    
    # Regex para encontrar títulos (com ou sem numeração) que estejam no início de uma linha
    # e envolvê-los em <strong>, garantindo a quebra [[PARAGRAPH]]
    
    def formatar_titulo_v18(match):
        # match.group(0) é o texto inteiro encontrado
        titulo_texto = match.group(0).strip()
        
        # Remove tags <mark> para não duplicar
        titulo_limpo = re.sub(r'</?mark[^>]*>', '', titulo_texto, flags=re.IGNORECASE)
        titulo_limpo = re.sub(r'\s+', ' ', titulo_limpo).strip()
        
        # Se for um título conhecido, formata.
        for t_check in titulos_unicos:
            if fuzz.ratio(normalizar_texto(t_check), normalizar_texto(titulo_limpo)) > 95:
                 # Adiciona a quebra de parágrafo ANTES do título
                return f'[[PARAGRAPH]]<strong>{titulo_texto}</strong>'
        
        # Se não for um título conhecido (ex: lixo de extração), retorna como estava
        return match.group(0)

    # Aplica a formatação APENAS em linhas que PARECEM títulos
    # (Início de linha, opc. número, opc. <mark>, texto, opc. </mark>, fim de linha)
    html_content = re.sub(
        r'^(?!\n)\s*(\d+\.\s*)?(<mark[^>]*>)?.*?(</mark>)?\s*$',
        formatar_titulo_v18,
        html_content,
        flags=re.MULTILINE | re.IGNORECASE
    )

    # 5. Lista e quebras
    html_content = re.sub(r'(\n)(\s*[-–•*])', r'[[LIST_ITEM]]\2', html_content)
    html_content = html_content.replace('\n', ' ') # Transforma quebras de formatação em espaço
    html_content = html_content.replace('[[PARAGRAPH]]', '<br><br>') # Restaura parágrafos
    html_content = html_content.replace('[[LIST_ITEM]]', '<br>') # Restaura itens de lista
    
    # 6. Limpeza final
    html_content = re.sub(r'(<br\s*/?>\s*){3,}', '<br><br>', html_content) # Remove quebras triplas
    html_content = re.sub(r'(<br><br>\s*)+<strong>', r'<br><br><strong>', html_content) # Limpa espaço antes de título
    html_content = re.sub(r'\s{2,}', ' ', html_content) # Remove espaços duplicados

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
    st.info(f"ℹ️ **Datas de Aprovação ANVISA:**\n - Referência: `{data_ref}`\n - BELFAR: `{data_belfar}`")

    if secoes_faltantes:
        st.error(f"🚨 **Seções faltantes na bula BELFAR ({len(secoes_faltantes)})**:\n" + "\n".join([f" - {s}" for s in secoes_faltantes]))
    else:
        st.success("✅ Todas as seções obrigatórias estão presentes")
        
    secoes_esperadas = obter_secoes_por_tipo(tipo_bula)
    mapa_diferencas = {diff['secao']: diff for diff in diferencas_conteudo}
    secoes_ignorar_comp = obter_secoes_ignorar_comparacao()
    secoes_ignorar_upper = {s.upper() for s in secoes_ignorar_comp}

    st.subheader("Análise de Conteúdo Seção por Seção")
    
    expander_caixa_style = (
        "height: 350px; overflow-y: auto; border: 2px solid #d0d0d0; border-radius: 6px; "
        "padding: 16px; background-color: #ffffff; font-size: 14px; line-height: 1.8; "
        "font-family: 'Georgia', 'Times New Roman', serif; text-align: justify; "
        "white-space: normal; overflow-wrap: break-word;"
    )

    for secao_canonico_raw in secoes_esperadas:
        
        if secao_canonico_raw in secoes_faltantes:
            continue

        if secao_canonico_raw in mapa_diferencas:
            diff = mapa_diferencas[secao_canonico_raw]
            
            titulo_display = diff.get('titulo_encontrado') or secao_canonico_raw
            if not titulo_display:
                titulo_display = secao_canonico_raw
            
            secao_canonico_norm = normalizar_texto(secao_canonico_raw)
            if "o que fazer se alguem usar uma quantidade maior" in secao_canonico_norm:
                if not normalizar_texto(titulo_display).startswith("9"):
                    titulo_display = f"9. {titulo_display}"
            
            with st.expander(f"📄 {titulo_display} - ❌ CONTEÚDO DIVERGENTE"):
                secao_canonico = diff['secao']
                anchor_id_ref = _create_anchor_id(secao_canonico, "ref")
                anchor_id_bel = _create_anchor_id(secao_canonico, "bel")
                
                # --- [INÍCIO DA MODIFICAÇÃO DE RENDER] ---
                # Usa a nova função de formatação
                
                # 1. Pega o conteúdo de texto cru (com \n)
                conteudo_ref_bruto = diff['conteudo_ref']
                conteudo_belfar_bruto = diff['conteudo_belfar']

                # 2. Adiciona marcações de diferença (ainda com \n)
                html_ref_bruto_expander = marcar_diferencas_palavra_por_palavra(
                    conteudo_ref_bruto, conteudo_belfar_bruto, eh_referencia=True
                )
                html_belfar_bruto_expander = marcar_diferencas_palavra_por_palavra(
                    conteudo_ref_bruto, conteudo_belfar_bruto, eh_referencia=False
                )

                # 3. Formata para HTML (converte \n em <br><br> ou espaço, e adiciona <strong>)
                expander_html_ref = formatar_html_para_leitura(html_ref_bruto_expander, tipo_bula, aplicar_numeracao=True)
                expander_html_belfar = formatar_html_para_leitura(html_belfar_bruto_expander, tipo_bula, aplicar_numeracao=False)
                # --- [FIM DA MODIFICAÇÃO DE RENDER] ---
                
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

        else:
            if secao_canonico_raw.upper() in secoes_ignorar_upper:
                with st.expander(f"📄 {secao_canonico_raw} - ℹ️ IGNORADA (Regra de Negócio)"):
                    st.info("Esta seção é ignorada durante a comparação de conteúdo (ex: Composição, Dizeres Legais) por regras de negócio.")
            else:
                with st.expander(f"📄 {secao_canonico_raw} - ✅ CONTEÚDO IDÊNTICO"):
                    st.success("O conteúdo desta seção na bula BELFAR é idêntico ao da referência.")

    if erros_ortograficos:
        st.info(f"📝 **Possíveis erros ortográficos ({len(erros_ortograficos)} palavras):**\n" + ", ".join(erros_ortograficos))

    if not any([secoes_faltantes, diferencas_conteudo, diferencas_titulos]) and len(erros_ortograficos) < 5:
        st.success("🎉 **Bula aprovada!** Nenhum problema crítico encontrado.")

    st.divider()
    st.subheader("🎨 Visualização Lado a Lado com Destaques")
    st.markdown(
        "**Legenda:** <mark style='background-color: #ffff99; padding: 2px;'>Amarelo</mark> = Divergências | "
        "<mark style='background-color: #FFDDC1; padding: 2px;'>Rosa</mark> = Erros ortográficos | "
        "<mark style='background-color: #cce5ff; padding: 2px;'>Azul</mark> = Data ANVISA",
        unsafe_allow_html=True
    )

    # --- [INÍCIO DA MODIFICAÇÃO DE RENDER] ---
    # 1. Marca o texto cru (com \n)
    html_ref_bruto = marcar_divergencias_html(
        texto_original=texto_ref, secoes_problema=diferencas_conteudo, erros_ortograficos=[], tipo_bula=tipo_bula, eh_referencia=True
    )
    html_belfar_bruto = marcar_divergencias_html(
        texto_original=texto_belfar, secoes_problema=diferencas_conteudo, erros_ortograficos=erros_ortograficos, tipo_bula=tipo_bula, eh_referencia=False
    )
    
    # 2. Formata para HTML (converte \n e aplica <strong>)
    html_ref_marcado = formatar_html_para_leitura(html_ref_bruto, tipo_bula, aplicar_numeracao=True)
    html_belfar_marcado = formatar_html_para_leitura(html_belfar_bruto, tipo_bula, aplicar_numeracao=False)
    # --- [FIM DA MODIFICAÇÃO DE RENDER] ---

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

            if not erro_ref:
                texto_ref = truncar_apos_anvisa(texto_ref)
            if not erro_belfar:
                texto_belfar = truncar_apos_anvisa(texto_belfar)

            if erro_ref or erro_belfar:
                st.error(f"Erro ao processar arquivos: {erro_ref or erro_belfar}")
            else:
                gerar_relatorio_final(texto_ref, texto_belfar, "Bula Referência", "Bula BELFAR", tipo_bula_selecionado)
    else:
        st.warning("⚠️ Por favor, envie ambos os arquivos PDF ou DOCX para iniciar a auditoria.")

st.divider()
st.caption("Sistema de Auditoria de Bulas v18.14 | Correção Regex Escape (formatar_html_para_leitura)")
