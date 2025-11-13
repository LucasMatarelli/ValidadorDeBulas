# --- IMPORTS ---
import streamlit as st
import fitz  # PyMuPDF
import docx
import re
import spacy
from thefuzz import fuzz
from spellchecker import SpellChecker
import difflib
import unicodedata
from collections import Counter

# ----------------- [NOVO] CONFIGURAÇÃO CENTRALIZADA -----------------
# Toda a lógica de bulas, seções, aliases e regras de "ignorar"
# foi movida para este único dicionário para fácil manutenção.
CONFIG_BULAS = {
    "Paciente": {
        "secoes": [
            {"nome": "APRESENTAÇÕES", "prefixo": "", "ignorar_comp": True, "ignorar_orto": True},
            {"nome": "COMPOSIÇÃO", "prefixo": "", "ignorar_comp": True, "ignorar_orto": True},
            {"nome": "PARA QUE ESTE MEDICAMENTO É INDICADO", "prefixo": "1.", "ignorar_comp": False, "ignorar_orto": False},
            {"nome": "COMO ESTE MEDICAMENTO FUNCIONA?", "prefixo": "2.", "ignorar_comp": False, "ignorar_orto": False},
            {"nome": "QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?", "prefixo": "3.", "ignorar_comp": False, "ignorar_orto": False},
            {"nome": "O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?", "prefixo": "4.", "ignorar_comp": False, "ignorar_orto": False},
            {"nome": "ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?", "prefixo": "5.", "ignorar_comp": False, "ignorar_orto": False}, # [CORREÇÃO] Não está mais ignorado
            {"nome": "COMO DEVO USAR ESTE MEDICAMENTO?", "prefixo": "6.", "ignorar_comp": False, "ignorar_orto": False},
            {"nome": "O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?", "prefixo": "7.", "ignorar_comp": False, "ignorar_orto": False},
            {"nome": "QUAIS OS MALES QUE ESTE MEDICAMENTO PODE CAUSAR?", "prefixo": "8.", "ignorar_comp": False, "ignorar_orto": False},
            {"nome": "O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?", "prefixo": "9.", "ignorar_comp": False, "ignorar_orto": False},
            {"nome": "DIZERES LEGAIS", "prefixo": "", "ignorar_comp": True, "ignorar_orto": True}
        ],
        "aliases": {
            "INDICAÇÕES": "PARA QUE ESTE MEDICAMENTO É INDICADO?",
            "CONTRAINDICAÇÕES": "QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?",
            "POSOLOGIA E MODO DE USAR": "COMO DEVO USAR ESTE MEDICAMENTO?",
            "REAÇÕES ADVERSAS": "QUAIS OS MALES QUE ESTE MEDICAMENTO PODE CAUSAR?",
            "QUAIS OS MALES QUE ESTE MEDICAMENTO PODE ME CAUSAR?": "QUAIS OS MALES QUE ESTE MEDICAMENTO PODE CAUSAR?",
            "SUPERDOSE": "O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?",
            "CUIDADOS DE ARMAZENAMENTO DO MEDICAMENTO": "ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?"
        }
    },
    "Profissional": {
        "secoes": [
            {"nome": "APRESENTAÇÕES", "prefixo": "", "ignorar_comp": True, "ignorar_orto": True},
            {"nome": "COMPOSIÇÃO", "prefixo": "", "ignorar_comp": True, "ignorar_orto": True},
            {"nome": "INDICAÇÕES", "prefixo": "1.", "ignorar_comp": False, "ignorar_orto": False},
            {"nome": "RESULTADOS DE EFICÁCIA", "prefixo": "2.", "ignorar_comp": False, "ignorar_orto": False},
            {"nome": "CARACTERÍSTICAS FARMACOLÓGICAS", "prefixo": "3.", "ignorar_comp": False, "ignorar_orto": False},
            {"nome": "CONTRAINDICAÇÕES", "prefixo": "4.", "ignorar_comp": False, "ignorar_orto": False},
            {"nome": "ADVERTÊNCIAS E PRECAUÇÕES", "prefixo": "5.", "ignorar_comp": False, "ignorar_orto": False},
            {"nome": "INTERAÇÕES MEDICAMENTOSAS", "prefixo": "6.", "ignorar_comp": False, "ignorar_orto": False},
            {"nome": "CUIDADOS DE ARMAZENAMENTO DO MEDICAMENTO", "prefixo": "7.", "ignorar_comp": False, "ignorar_orto": False},
            {"nome": "POSOLOGIA E MODO DE USAR", "prefixo": "8.", "ignorar_comp": False, "ignorar_orto": False},
            {"nome": "REAÇÕES ADVERSAS", "prefixo": "9.", "ignorar_comp": False, "ignorar_orto": False},
            {"nome": "SUPERDOSE", "prefixo": "10.", "ignorar_comp": False, "ignorar_orto": False},
            {"nome": "DIZERES LEGAIS", "prefixo": "", "ignorar_comp": True, "ignorar_orto": True}
        ],
        "aliases": {
            "PARA QUE ESTE MEDICAMENTO É INDICADO?": "INDICAÇÕES",
            "QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?": "CONTRAINDICAÇÕES",
            "COMO DEVO USAR ESTE MEDICAMENTO?": "POSOLOGIA E MODO DE USAR",
            "QUAIS OS MALES QUE ESTE MEDICAMENTO PODE CAUSAR?": "REAÇÕES ADVERSAS",
            "O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?": "SUPERDOSE",
            "ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?": "CUIDADOS DE ARMAZENAMENTO DO MEDICAMENTO"
        }
    }
}

# Funções "helper" que leem a configuração
def get_config(tipo_bula):
    return CONFIG_BULAS.get(tipo_bula, CONFIG_BULAS["Paciente"])

def get_secoes_config(tipo_bula):
    return get_config(tipo_bula)["secoes"]

def get_aliases(tipo_bula):
    return get_config(tipo_bula)["aliases"]

def get_secoes_por_tipo(tipo_bula):
    return [s["nome"] for s in get_secoes_config(tipo_bula)]

def get_secoes_ignorar(tipo_bula, tipo_ignore):
    # tipo_ignore pode ser 'ignorar_comp' ou 'ignorar_orto'
    return [s["nome"] for s in get_secoes_config(tipo_bula) if s[tipo_ignore]]
# ----------------- FIM DA CONFIGURAÇÃO -----------------


hide_streamlit_UI = """
<style>
[data-testid="stHeader"], [data-testid="main-menu-button"], footer, [data-testid="stStatusWidget"] {
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

# ----------------- [MELHORIA] EXTRAÇÃO DE TEXTO -----------------
def limpar_texto_extraido(texto):
    """Limpa um bloco de texto de caracteres indesejados."""
    if not texto:
        return ""
    caracteres_invisiveis = ['\u00AD', '\u200B', '\u200C', '\u200D', '\uFEFF']
    for char in caracteres_invisiveis:
        texto = texto.replace(char, '')
    texto = texto.replace('\r\n', '\n').replace('\r', '\n')
    texto = texto.replace('\u00A0', ' ')
    texto = re.sub(r'[ \t]+', ' ', texto)
    return texto.strip()

@st.cache_data(show_spinner=False)
def extrair_texto_estruturado(arquivo, tipo_arquivo):
    """
    Extrai o texto e a estrutura (tamanho da fonte, negrito) do arquivo.
    Retorna uma lista de dicionários, onde cada um é uma "linha" de texto.
    """
    linhas_estruturadas = []
    if arquivo is None:
        return [], "Arquivo não enviado."
    
    try:
        arquivo.seek(0)
        
        if tipo_arquivo == 'pdf':
            doc = fitz.open(stream=arquivo.read(), filetype="pdf")
            for page in doc:
                blocks = page.get_text("dict", flags=fitz.TEXTFLAGS_INHIBIT_SPACES)["blocks"]
                for b in blocks:
                    if b['type'] == 0:  # Bloco de texto
                        for l in b["lines"]:
                            line_text = ""
                            font_sizes = []
                            is_bold = False
                            for s in l["spans"]:
                                line_text += s["text"]
                                font_sizes.append(round(s["size"]))
                                if "bold" in s["font"].lower():
                                    is_bold = True
                            
                            line_text_limpo = limpar_texto_extraido(line_text)
                            if line_text_limpo:
                                linhas_estruturadas.append({
                                    "texto": line_text_limpo,
                                    "fonte": Counter(font_sizes).most_common(1)[0][0] if font_sizes else 0,
                                    "negrito": is_bold,
                                    "y_coord": l["bbox"][1] # Coordenada Y para ordenação
                                })
            doc.close()
            # Remove hifenização
            i = 0
            while i < len(linhas_estruturadas) - 1:
                linha_atual = linhas_estruturadas[i]
                linha_prox = linhas_estruturadas[i+1]
                if linha_atual["texto"].endswith('-'):
                    # Heurística simples de hifenização
                    if abs(linha_atual["y_coord"] - linha_prox["y_coord"]) < 20: # Estão próximas
                        linha_atual["texto"] = linha_atual["texto"][:-1] + linha_prox["texto"]
                        linhas_estruturadas.pop(i+1)
                    else:
                        i += 1
                else:
                    i += 1

        elif tipo_arquivo == 'docx':
            doc = docx.Document(arquivo)
            for p in doc.paragraphs:
                texto_limpo = limpar_texto_extraido(p.text)
                if texto_limpo:
                    # DOCX não nos dá tamanho de fonte confiável, então "enganamos" o sistema
                    # marcando tudo com a mesma fonte e sem negrito.
                    # A detecção de título para DOCX dependerá apenas do fuzzy matching.
                    is_bold_docx = any(run.bold for run in p.runs)
                    font_size_docx = 10 # Tamanho padrão
                    if p.style and 'heading' in p.style.name.lower():
                         is_bold_docx = True
                         font_size_docx = 12 # Fonte maior para cabeçalho
                    
                    linhas_estruturadas.append({
                        "texto": texto_limpo,
                        "fonte": font_size_docx,
                        "negrito": is_bold_docx,
                        "y_coord": len(linhas_estruturadas) # Apenas para manter a ordem
                    })
        
        # Filtro de rodapé final
        padrao_rodape = re.compile(r'bula (?:do|para o) paciente|página \d+\s*de\s*\d+', re.IGNORECASE)
        linhas_filtradas = [l for l in linhas_estruturadas if not padrao_rodape.search(l["texto"])]
        
        # Truncar após ANVISA
        indice_anvisa = -1
        regex_anvisa = r"(aprovad[ao]\s+pela\s+anvisa\s+em|data\s+de\s+aprovação\s+na\s+anvisa:)\s*([\d]{1,2}/[\d]{1,2}/[\d]{2,4})"
        for i, linha in enumerate(linhas_filtradas):
            if re.search(regex_anvisa, linha["texto"], re.IGNORECASE):
                indice_anvisa = i
                break
        
        if indice_anvisa != -1:
            linhas_filtradas = linhas_filtradas[:indice_anvisa + 1]

        return linhas_filtradas, None

    except Exception as e:
        return [], f"Erro ao ler o arquivo {tipo_arquivo}: {e}"

# ----------------- NORMALIZAÇÃO -----------------
def normalizar_texto_simples(texto):
    """Normalização leve para comparação, mantendo pontuação."""
    texto = ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')
    texto = texto.lower()
    return ' '.join(texto.split()) # Remove espaços duplicados

def normalizar_texto_comparacao(texto):
    """Normalização agressiva para fuzzy matching e comparação de conteúdo."""
    texto = ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')
    texto = re.sub(r'[^\w\s]', '', texto)
    texto = ' '.join(texto.split())
    return texto.lower()

def normalizar_titulo_para_comparacao(texto):
    """Normalização robusta para títulos, removendo acentos, pontuação e numeração inicial."""
    texto_norm = normalizar_texto_comparacao(texto)
    texto_norm = re.sub(r'^\d+\s*[\.\-)]*\s*', '', texto_norm).strip()
    return texto_norm

def _create_anchor_id(secao_nome, prefix):
    """Cria um ID HTML seguro para a âncora."""
    norm = normalizar_texto_comparacao(secao_nome)
    norm_safe = re.sub(r'[^a-z0-9\-]', '-', norm)
    return f"anchor-{prefix}-{norm_safe}"

# ----------------- [MELHORIA] MAPEAMENTO DE SEÇÕES -----------------
def encontrar_fonte_padrao(linhas_estruturadas):
    """Encontra o tamanho de fonte mais comum (texto corrido)."""
    tamanhos = [l["fonte"] for l in linhas_estruturadas if l["texto"] and not l["negrito"] and len(l["texto"]) > 50]
    if not tamanhos:
        tamanhos = [l["fonte"] for l in linhas_estruturadas if l["texto"] and len(l["texto"]) > 50]
    if not tamanhos:
        return 10 # Um palpite razoável
    
    return Counter(tamanhos).most_common(1)[0][0]

def mapear_secoes(linhas_estruturadas, tipo_bula):
    """Mapeia seções usando estrutura de fonte (PDF) ou fuzzy matching (DOCX)."""
    mapa = []
    config_secoes = get_secoes_config(tipo_bula)
    aliases = get_aliases(tipo_bula)
    
    # Cria um mapa de todos os títulos possíveis para o canônico
    titulos_possiveis = {}
    for secao in config_secoes:
        titulos_possiveis[secao["nome"]] = secao["nome"]
    for alias, canonico in aliases.items():
        if any(s["nome"] == canonico for s in config_secoes):
            titulos_possiveis[alias] = canonico

    # Normaliza todos os títulos possíveis uma vez
    titulos_norm = {normalizar_titulo_para_comparacao(t): c for t, c in titulos_possiveis.items()}
    
    fonte_padrao = encontrar_fonte_padrao(linhas_estruturadas)
    
    for idx, linha in enumerate(linhas_estruturadas):
        linha_limpa = linha["texto"].strip()
        if not linha_limpa or len(linha_limpa) < 4:
            continue
        
        # --- [LÓGICA DE DETECÇÃO DE TÍTULO] ---
        # 1. É negrito E fonte maior ou igual ao padrão? (PDF)
        # 2. OU tem mais de 3 palavras E menos de 20? (DOCX fallback)
        is_possivel_titulo = (
            (linha["negrito"] and linha["fonte"] >= fonte_padrao) or
            (3 < len(linha_limpa.split()) < 20)
        )
        
        if not is_possivel_titulo:
            continue
            
        linha_norm = normalizar_titulo_para_comparacao(linha_limpa)
        if not linha_norm:
            continue

        best_match_score = 0
        best_match_canonico = None
        
        # Tenta encontrar um match exato primeiro (mais rápido)
        if linha_norm in titulos_norm:
            best_match_score = 100
            best_match_canonico = titulos_norm[linha_norm]
        else:
            # Se falhar, usa fuzzy matching
            for titulo_norm_config, titulo_canonico in titulos_norm.items():
                score = fuzz.token_set_ratio(titulo_norm_config, linha_norm)
                if score > best_match_score:
                    best_match_score = score
                    best_match_canonico = titulo_canonico
        
        if best_match_score >= 98:
            if not mapa or mapa[-1]['canonico'] != best_match_canonico:
                mapa.append({
                    'canonico': best_match_canonico,
                    'titulo_encontrado': linha_limpa,
                    'linha_inicio_idx': idx, # Salva o índice da linha
                    'score': best_match_score
                })
                
    mapa.sort(key=lambda x: x['linha_inicio_idx'])
    return mapa

def obter_dados_secao(secao_canonico, mapa_secoes, linhas_estruturadas):
    """Extrai o conteúdo de uma seção com base nos índices do mapa."""
    
    for i, secao_mapa in enumerate(mapa_secoes):
        if secao_mapa['canonico'] != secao_canonico:
            continue

        titulo_encontrado = secao_mapa['titulo_encontrado']
        linha_inicio_idx = secao_mapa['linha_inicio_idx']
        
        # O conteúdo começa na linha *seguinte* ao título
        idx_conteudo_inicio = linha_inicio_idx + 1
        
        # O conteúdo termina na linha *anterior* ao próximo título
        idx_conteudo_fim = len(linhas_estruturadas) # Por padrão, vai até o fim
        if i + 1 < len(mapa_secoes):
            idx_conteudo_fim = mapa_secoes[i+1]['linha_inicio_idx']
            
        # Pega as linhas de texto do conteúdo
        linhas_conteudo = [
            linhas_estruturadas[idx]["texto"] 
            for idx in range(idx_conteudo_inicio, idx_conteudo_fim)
        ]
        
        conteudo_final = "\n".join(linhas_conteudo).strip()
        
        # Lógica para "quebrar" títulos mesclados (Ex: "9. ... ?É pouco provável...")
        match = re.match(r'^(.+?[?\.])\s*([A-ZÁÉÍÓÚÂÊÔÃÕÇ].*)$', titulo_encontrado)
        if match and len(titulo_encontrado.split()) > 3:
            titulo_real = match.group(1).strip()
            conteudo_extra = match.group(2).strip()
            
            titulo_encontrado = titulo_real
            conteudo_final = f"{conteudo_extra}\n{conteudo_final}".strip()

        return True, titulo_encontrado, conteudo_final

    return False, None, ""

# ----------------- [MELHORIA] COMPARAÇÃO DE CONTEÚDO -----------------
def verificar_secoes_e_conteudo(linhas_ref, linhas_belfar, tipo_bula):
    secoes_config = get_secoes_config(tipo_bula)
    secoes_analisadas = []
    diferencas_titulos = []
    similaridades_secoes = [] # Para o score

    mapa_ref = mapear_secoes(linhas_ref, tipo_bula)
    mapa_belfar = mapear_secoes(linhas_belfar, tipo_bula)

    for secao_cfg in secoes_config:
        secao_canonico = secao_cfg["nome"]
        
        encontrou_ref, _, conteudo_ref = obter_dados_secao(secao_canonico, mapa_ref, linhas_ref)
        encontrou_belfar, titulo_belfar, conteudo_belfar = obter_dados_secao(secao_canonico, mapa_belfar, linhas_belfar)

        if not encontrou_belfar:
            secoes_analisadas.append({
                'secao_config': secao_cfg,
                'conteudo_ref': conteudo_ref if encontrou_ref else "Seção não encontrada na Referência",
                'conteudo_belfar': "Seção não encontrada no documento Belfar",
                'titulo_encontrado_belfar': None,
                'tem_diferenca': True,
                'ignorada': False,
                'faltante': True
            })
            continue

        if encontrou_ref and encontrou_belfar:
            titulo_real_encontrado = titulo_belfar
            
            # Checa diferença de título
            if normalizar_titulo_para_comparacao(secao_canonico) != normalizar_titulo_para_comparacao(titulo_real_encontrado):
                diferencas_titulos.append({'secao_esperada': secao_canonico, 'titulo_encontrado': titulo_real_encontrado})

            # Checa se deve ignorar
            if secao_cfg["ignorar_comp"]:
                secoes_analisadas.append({
                    'secao_config': secao_cfg,
                    'conteudo_ref': conteudo_ref,
                    'conteudo_belfar': conteudo_belfar,
                    'titulo_encontrado_belfar': titulo_real_encontrado,
                    'tem_diferenca': False,
                    'ignorada': True,
                    'faltante': False
                })
                continue # Pula para a próxima seção
                
            # Compara conteúdo
            tem_diferenca = False
            if normalizar_texto_comparacao(conteudo_ref) != normalizar_texto_comparacao(conteudo_belfar):
                tem_diferenca = True
                similaridades_secoes.append(0)
            else:
                similaridades_secoes.append(100)

            secoes_analisadas.append({
                'secao_config': secao_cfg,
                'conteudo_ref': conteudo_ref,
                'conteudo_belfar': conteudo_belfar,
                'titulo_encontrado_belfar': titulo_real_encontrado,
                'tem_diferenca': tem_diferenca,
                'ignorada': False,
                'faltante': False
            })

    score = sum(similaridades_secoes) / len(similaridades_secoes) if similaridades_secoes else 100.0
    secoes_faltantes = [s['secao_config']['nome'] for s in secoes_analisadas if s['faltante']]
    diferencas_conteudo = [s for s in secoes_analisadas if s['tem_diferenca'] and not s['faltante']]
    
    return secoes_faltantes, diferencas_conteudo, score, diferencas_titulos, secoes_analisadas

# ----------------- ORTOGRAFIA -----------------
def checar_ortografia_inteligente(linhas_belfar_estruturadas, linhas_ref_estruturadas, tipo_bula):
    if not nlp:
        return []
        
    texto_para_checar_lista = []
    secoes_ignorar_orto = get_secoes_ignorar(tipo_bula, 'ignorar_orto')
    secoes_todas = get_secoes_por_tipo(tipo_bula)
    
    mapa_secoes = mapear_secoes(linhas_belfar_estruturadas, tipo_bula)
    
    # Constrói o vocabulário de referência
    vocab_referencia = set(
        re.findall(r'\b[a-záéíóúâêôãõçü]+\b', 
                   normalizar_texto_comparacao(" ".join([l["texto"] for l in linhas_ref_estruturadas]))
        )
    )
    
    # Constrói o texto para checar
    texto_completo_belfar = " ".join([l["texto"] for l in linhas_belfar_estruturadas])
    doc = nlp(texto_completo_belfar)
    entidades = {ent.text.lower() for ent in doc.ents}
    
    for secao_nome in secoes_todas:
        if secao_nome in secoes_ignorar_orto:
            continue
        encontrou, _, conteudo = obter_dados_secao(secao_nome, mapa_secoes, linhas_belfar_estruturadas)
        if encontrou and conteudo:
            texto_para_checar_lista.append(conteudo)
            
    texto_final_para_checar = "\n".join(texto_para_checar_lista)
    if not texto_final_para_checar:
        return []

    try:
        spell = SpellChecker(language='pt')
        palavras_a_ignorar = {"alair", "belfar", "peticionamento", "urotrobel"}
        
        spell.word_frequency.load_words(
            vocab_referencia.union(entidades).union(palavras_a_ignorar)
        )
        
        palavras = re.findall(r'\b[a-záéíóúâêôãõçü]+\b', normalizar_texto_comparacao(texto_final_para_checar))
        erros = spell.unknown(palavras)
        return list(sorted(set([e for e in erros if len(e) > 3])))[:20]

    except Exception as e:
        st.warning(f"Erro no módulo de ortografia: {e}")
        return []

# ----------------- DIFERENÇAS PALAVRA A PALAVRA -----------------
def marcar_diferencas_palavra_por_palavra(texto_ref, texto_belfar, eh_referencia):
    """Marca diferenças inline usando <mark>. Usa normalização leve."""
    
    # Usa a normalização leve que mantém pontuação
    ref_norm = normalizar_texto_simples(texto_ref)
    bel_norm = normalizar_texto_simples(texto_belfar)

    # Tokeniza os textos normalizados
    ref_tokens_norm = re.findall(r'\n|[\w]+|[^\w\s]', ref_norm, re.UNICODE)
    bel_tokens_norm = re.findall(r'\n|[\w]+|[^\w\s]', bel_norm, re.UNICODE)
    
    # Tokeniza os textos ORIGINAIS
    ref_tokens_orig = re.findall(r'\n|[\w]+|[^\w\s]', texto_ref, re.UNICODE)
    bel_tokens_orig = re.findall(r'\n|[\w]+|[^\w\s]', texto_belfar, re.UNICODE)

    # Garante que o número de tokens seja o mesmo
    if len(ref_tokens_norm) != len(ref_tokens_orig) or len(bel_tokens_norm) != len(bel_tokens_orig):
        # Se a tokenização falhar, recorre à tokenização mais simples
        ref_tokens_norm = ref_norm.split()
        ref_tokens_orig = texto_ref.split()
        bel_tokens_norm = bel_norm.split()
        bel_tokens_orig = texto_belfar.split()

    matcher = difflib.SequenceMatcher(None, ref_tokens_norm, bel_tokens_norm, autojunk=False)
    indices = set()
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != 'equal':
            indices.update(range(i1, i2) if eh_referencia else range(j1, j2))

    tokens_originais = ref_tokens_orig if eh_referencia else bel_tokens_orig
    marcado = []
    
    for idx, tok in enumerate(tokens_originais):
        if tok == '\n':
            marcado.append('<br>')
        elif idx in indices and tok.strip() != '':
            marcado.append(f"<mark style='background-color: #ffff99; padding: 2px;'>{tok}</mark>")
        else:
            marcado.append(tok)
    
    # Lógica de "colagem" inteligente
    resultado = ""
    for i, tok in enumerate(marcado):
        if i == 0 or tok == '<br>' or marcado[i-1] == '<br>':
            resultado += tok
        elif re.match(r'^[^\w\s]$', tok) or tok.startswith('<mark'): # Se for pontuação ou marcação
             resultado += tok
        elif re.match(r'^[^\w\s]$', marcado[i-1]) and not marcado[i-1].startswith('<mark'): # Se o anterior for pontuação
             resultado += tok
        else:
            resultado += " " + tok
            
    resultado = re.sub(r'\s+([.,;:!?)])', r'\1', resultado)
    resultado = re.sub(r'(\()\s+', r'\1', resultado)
    resultado = re.sub(r"(</mark>)\s+(<mark[^>]*>)", " ", resultado) # Junta marcações
    return resultado

# ----------------- [MELHORIA] CONSTRUÇÃO DE HTML -----------------
def construir_html_completo(secoes_analisadas, erros_ortograficos, eh_referencia):
    """Constrói o HTML da visualização lado-a-lado a partir dos dados analisados."""
    html_final = []
    secoes_ignorar_orto_nomes = [s['secao_config']['nome'] for s in secoes_analisadas if s['secao_config']['ignorar_orto']]
    
    # Marcação de erros ortográficos
    texto_completo_belfar = "\n".join([s['conteudo_belfar'] for s in secoes_analisadas])
    mapa_erros = {}
    if erros_ortograficos and not eh_referencia:
        for erro in erros_ortograficos:
            pattern = r'(?<![<>a-zA-Z])(?<!mark>)(?<!;>)\b(' + re.escape(erro) + r')\b(?![<>])'
            mapa_erros[pattern] = r"<mark style='background-color: #FFDDC1; padding: 2px;'>\1</mark>"

    # Marcação da data ANVISA
    regex_anvisa = r"((?:aprovad[ao]\s+pela\s+anvisa\s+em|data\s+de\s+aprovação\s+na\s+anvisa:)\s*[\d]{1,2}/[\d]{1,2}/[\d]{2,4})"
    anvisa_pattern = re.compile(regex_anvisa, re.IGNORECASE)
    
    for diff in secoes_analisadas:
        if diff['faltante']:
            continue
            
        secao_cfg = diff['secao_config']
        secao_canonico = secao_cfg['nome']
        prefixo = secao_cfg['prefixo']
        
        # Usa o título encontrado (Belfar) ou o canônico (Ref)
        if eh_referencia:
            titulo_display = f"{prefixo} {secao_canonico}".strip()
        else:
            titulo_display = f"{prefixo} {diff['titulo_encontrado_belfar'] or secao_canonico}".strip()
            
        html_final.append(f"<h3 style='font-size: 16px; font-weight: bold; color: #111;'>{titulo_display}</h3>")
        
        # Pega o conteúdo correto (Ref ou Belfar)
        conteudo = diff['conteudo_ref'] if eh_referencia else diff['conteudo_belfar']
        
        # Aplica marcações
        if diff['tem_diferenca'] and not diff['ignorada']:
            conteudo_marcado = marcar_diferencas_palavra_por_palavra(
                diff['conteudo_ref'], diff['conteudo_belfar'], eh_referencia
            )
        else:
            conteudo_marcado = conteudo.replace('\n', '<br>')
            
        # Aplica ortografia (apenas em Belfar e se não for ignorada)
        if not eh_referencia and secao_canonico not in secoes_ignorar_orto_nomes:
            for pattern, replacement in mapa_erros.items():
                conteudo_marcado = re.sub(pattern, replacement, conteudo_marcado, flags=re.IGNORECASE)
        
        # Aplica ANVISA
        conteudo_marcado = anvisa_pattern.sub(
            r"<mark style='background-color: #cce5ff; padding: 2px; font-weight: 500;'>\1</mark>",
            conteudo_marcado
        )

        anchor_id = _create_anchor_id(secao_canonico, "ref" if eh_referencia else "bel")
        html_final.append(f"<div id='{anchor_id}' style='scroll-margin-top: 20px;'>{conteudo_marcado}</div><br>")

    return "".join(html_final)

# ----------------- RELATÓRIO -----------------
def gerar_relatorio_final(linhas_ref, linhas_belfar, nome_ref, nome_belfar, tipo_bula):
    
    js_scroll_script = """
    <script>
    if (!window.handleBulaScroll) {
        window.handleBulaScroll = function(anchorIdRef, anchorIdBel) {
            var containerRef = document.getElementById('container-ref-scroll');
            var containerBel = document.getElementById('container-bel-scroll');
            var anchorRef = document.getElementById(anchorIdRef);
            var anchorBel = document.getElementById(anchorIdBel);

            if (!containerRef || !containerBel || !anchorRef || !anchorBel) {
                console.error("Erro: Elemento de scroll ou âncora não encontrado.");
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
                } catch (e) {
                    console.error("Erro durante a rolagem interna:", e);
                }
            }, 700); 
        }
    }
    </script>
    """
    st.markdown(js_scroll_script, unsafe_allow_html=True)

    st.header("Relatório de Auditoria Inteligente")
    
    # Extrai data ANVISA (procura no texto completo)
    texto_ref_completo = "\n".join([l["texto"] for l in linhas_ref])
    texto_belfar_completo = "\n".join([l["texto"] for l in linhas_belfar])
    regex_anvisa = r"(aprovad[ao]\s+pela\s+anvisa\s+em|data\s+de\s+aprovação\s+na\s+anvisa:)\s*([\d]{1,2}/[\d]{1,2}/[\d]{2,4})"
    match_ref = re.search(regex_anvisa, texto_ref_completo, re.IGNORECASE)
    match_belfar = re.search(regex_anvisa, texto_belfar_completo, re.IGNORECASE)
    data_ref = match_ref.group(2).strip() if match_ref else "Não encontrada"
    data_belfar = match_belfar.group(2).strip() if match_belfar else "Não encontrada"

    # --- Execução da Análise ---
    secoes_faltantes, _, score_similaridade_conteudo, diferencas_titulos, secoes_analisadas = \
        verificar_secoes_e_conteudo(linhas_ref, linhas_belfar, tipo_bula)
    
    erros_ortograficos = checar_ortografia_inteligente(linhas_belfar, linhas_ref, tipo_bula)
    # --- Fim da Análise ---

    st.subheader("Dashboard de Veredito")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Conformidade de Conteúdo", f"{score_similaridade_conteudo:.0f}%")
    col2.metric("Erros Ortográficos", len(erros_ortograficos))
    col3.metric("Data ANVISA (BELFAR)", data_belfar)
    col4.metric("Seções Faltantes", f"{len(secoes_faltantes)}")

    st.divider()
    st.subheader("Detalhes dos Problemas Encontrados")
    st.info(f"ℹ️ **Datas de Aprovação ANVISA:**\n - Referência: `{data_ref}`\n - BELFAR: `{data_belfar}`")

    if diferencas_titulos:
        st.warning(f"⚠️ **Títulos com nomes diferentes ({len(diferencas_titulos)})**:\n" + 
                   "\n".join([f" - Esperado: `{d['secao_esperada']}` | Encontrado: `{d['titulo_encontrado']}`" for d in diferencas_titulos]))
        
    if secoes_analisadas:
        st.markdown("##### Análise Detalhada de Conteúdo das Seções")
        
        expander_caixa_style = (
            "height: 350px; overflow-y: auto; border: 2px solid #d0d0d0; border-radius: 6px; "
            "padding: 16px; background-color: #ffffff; font-size: 14px; line-height: 1.8; "
            "font-family: 'Georgia', 'Times New Roman', serif; text-align: justify;"
        )
        
        for diff in secoes_analisadas:
            secao_cfg = diff['secao_config']
            secao_canonico_raw = secao_cfg['nome']
            prefixo = secao_cfg['prefixo']
            
            titulo_display = f"{prefixo} {secao_canonico_raw}".strip()

            if diff.get('faltante', False):
                expander_label = f"📄 {titulo_display} - 🚨 SEÇÃO FALTANTE"
                expander_expanded = True
            elif diff['ignorada']:
                expander_label = f"📄 {titulo_display} - ⚠️ COMPARAÇÃO IGNORADA"
                expander_expanded = False
            elif diff['tem_diferenca']:
                expander_label = f"📄 {titulo_display} - ❌ CONTEÚDO DIVERGENTE"
                expander_expanded = True 
            else:
                expander_label = f"📄 {titulo_display} - ✅ CONTEÚDO IDÊNTICO"
                expander_expanded = False 

            with st.expander(expander_label, expanded=expander_expanded):
                
                anchor_id_ref = _create_anchor_id(secao_canonico_raw, "ref")
                anchor_id_bel = _create_anchor_id(secao_canonico_raw, "bel")
                
                if diff.get('faltante', False):
                    st.error(f"**A seção \"{secao_canonico_raw}\" não foi encontrada no documento Belfar.**")
                    if "não encontrada na Referência" in diff['conteudo_ref']:
                         st.warning(f"**A seção \"{secao_canonico_raw}\" também não foi encontrada no documento de Referência.**")
                    continue

                if diff['ignorada']:
                    expander_html_ref = diff['conteudo_ref'].replace('\n', '<br>')
                    expander_html_belfar = diff['conteudo_belfar'].replace('\n', '<br>')
                else:
                    expander_html_ref = marcar_diferencas_palavra_por_palavra(
                        diff['conteudo_ref'], diff['conteudo_belfar'], eh_referencia=True
                    )
                    expander_html_belfar = marcar_diferencas_palavra_por_palavra(
                        diff['conteudo_ref'], diff['conteudo_belfar'], eh_referencia=False
                    )
                
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

    if not any([secoes_faltantes, [s for s in secoes_analisadas if s['tem_diferenca']], diferencas_titulos]) and len(erros_ortograficos) < 5:
        st.success("🎉 **Bula aprovada!** Nenhum problema crítico encontrado.")

    st.divider()
    st.subheader("Visualização Lado a Lado com Destaques")
    st.markdown(
        "**Legenda:** <mark style='background-color: #ffff99; padding: 2px;'>Amarelo</mark> = Divergências | "
        "<mark style='background-color: #FFDDC1; padding: 2px;'>Rosa</mark> = Erros ortográficos | "
        "<mark style='background-color: #cce5ff; padding: 2px;'>Azul</mark> = Data ANVISA",
        unsafe_allow_html=True
    )

    # --- [MELHORIA] Constrói o HTML a partir dos dados, sem `replace()` ---
    html_ref_marcado = construir_html_completo(secoes_analisadas, [], eh_referencia=True)
    html_belfar_marcado = construir_html_completo(secoes_analisadas, erros_ortograficos, eh_referencia=False)
    # --- FIM DA MELHORIA ---

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
    pdf_belfar = st.file_uploader("EnvIE o PDF ou DOCX Belfar", type=["pdf", "docx"], key="belfar")

if st.button("🔍 Iniciar Auditoria Completa", use_container_width=True, type="primary"):
    if pdf_ref and pdf_belfar:
        with st.spinner("🔄 Processando e analisando as bulas..."):
            
            tipo_ref = 'docx' if pdf_ref.name.endswith('.docx') else 'pdf'
            tipo_belfar = 'docx' if pdf_belfar.name.endswith('.docx') else 'pdf'
            
            # [MELHORIA] Usa a nova função de extração estruturada
            with st.spinner("Lendo documento de Referência..."):
                linhas_ref, erro_ref = extrair_texto_estruturado(pdf_ref, tipo_ref)
            with st.spinner("Lendo documento Belfar..."):
                linhas_belfar, erro_belfar = extrair_texto_estruturado(pdf_belfar, tipo_belfar)

            if erro_ref or erro_belfar:
                st.error(f"Erro ao processar arquivos: {erro_ref or erro_belfar}")
            elif not linhas_ref or not linhas_belfar:
                st.error("Erro: Um dos arquivos não pôde ser lido ou está vazio.")
            else:
                gerar_relatorio_final(linhas_ref, linhas_belfar, pdf_ref.name, pdf_belfar.name, tipo_bula_selecionado)
    else:
        st.warning("⚠️ Por favor, envie ambos os arquivos PDF ou DOCX para iniciar a auditoria.")

st.divider()
st.caption("Sistema de Auditoria de Bulas vPerfeito | Detecção por Fonte | Config Central")
