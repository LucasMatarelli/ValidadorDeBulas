# --- IMPORTS ---
import streamlit as st
from style_utils import hide_streamlit_toolbar

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
import fitz # PyMuPDF
import docx
import re
import spacy
from thefuzz import fuzz
from spellchecker import SpellChecker
import difflib
import unicodedata

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
        "SUPERDOSE": "O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?",
        "CUIDADOS DE ARMAZENAMENTO DO MEDICAMENTO": "ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?"
    }

def obter_secoes_ignorar_ortografia():
    return ["COMPOSIÇÃO", "DIZERES LEGAIS"]

def obter_secoes_ignorar_comparacao():
    return ["COMPOSIÇÃO", "DIZERES LEGAIS"]

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

# --- [NOVO] ---
# Helper para criar IDs únicos para as âncoras HTML
def _create_anchor_id(secao_nome, prefix):
    """Cria um ID HTML seguro para a âncora."""
    norm = normalizar_texto(secao_nome)
    return f"anchor-{prefix}-{norm.replace(' ', '-')}"

# ----------------- ARQUITETURA DE MAPEAMENTO DE SEÇÕES (VERSÃO FINAL) -----------------
def is_titulo_secao(linha):
    """Retorna True se a linha for um possível título de seção puro."""
    linha = linha.strip()
    if len(linha) < 4 or len(linha.split()) > 12:
        return False
    if linha.endswith('.') or linha.endswith(':'):
        return False
    if re.search(r'\>\s*\<', linha):
        return False
    if len(linha) > 80:
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
    # Normaliza a lista de títulos oficiais uma vez para otimizar a busca
    titulos_norm_set = {normalizar_titulo_para_comparacao(t) for t in titulos_lista}

    for i, secao_mapa in enumerate(mapa_secoes):
        if secao_mapa['canonico'] != secao_canonico:
            continue

        titulo_encontrado = secao_mapa['titulo_encontrado']
        linha_inicio = secao_mapa['linha_inicio']
        linha_inicio_conteudo = linha_inicio + 1

        # --- LÓGICA DE BUSCA APRIMORADA (1 ou 2 linhas) ---
        prox_idx = None
        for j in range(linha_inicio_conteudo, len(linhas_texto)):
            # Verifica a linha atual (busca de 1 linha)
            linha_atual = linhas_texto[j].strip()
            linha_atual_norm = normalizar_titulo_para_comparacao(linha_atual)

            if linha_atual_norm in titulos_norm_set:
                prox_idx = j # Encontrou um título em uma única linha
                break

            # Se não encontrou, verifica a combinação da linha atual + próxima (busca de 2 linhas)
            if (j + 1) < len(linhas_texto):
                linha_seguinte = linhas_texto[j + 1].strip()
                # Concatena a linha atual com a próxima para formar um possível título
                titulo_duas_linhas = f"{linha_atual} {linha_seguinte}"
                titulo_duas_linhas_norm = normalizar_titulo_para_comparacao(titulo_duas_linhas)

                if titulo_duas_linhas_norm in titulos_norm_set:
                    prox_idx = j # Encontrou um título dividido em duas linhas
                    break
        # --- FIM DA LÓGICA DE BUSCA ---

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
            if melhor_score >= 98:
                diferencas_titulos.append({'secao_esperada': secao, 'titulo_encontrado': melhor_titulo})
                for m in mapa_belfar:
                    if m['titulo_encontrado'] == melhor_titulo:
                        conteudo_belfar = "\n".join(linhas_belfar[m['linha_inicio']:mapa_belfar[mapa_belfar.index(m)+1]['linha_inicio']] if mapa_belfar.index(m)+1 < len(mapa_belfar) else linhas_belfar[m['linha_inicio']:])
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
                diferencas_conteudo.append({'secao': secao, 'conteudo_ref': conteudo_ref, 'conteudo_belfar': conteudo_belfar})
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
        raw_tok = re.sub(r'^<mark[^>]*>|</mark>$', '', tok)
        if re.match(r'^[^\w\s]$', raw_tok) or raw_tok == '\n':
            resultado += tok
        else:
            resultado += " " + tok
    resultado = re.sub(r'\s+([.,;:!?)])', r'\1', resultado)
    resultado = re.sub(r'(\()\s+', r'\1', resultado)
    resultado = re.sub(r"(</mark>)\s+(<mark[^>]*>)", " ", resultado)
    return resultado

# ----------------- MARCAÇÃO POR SEÇÃO COM ÍNDICES -----------------
# --- [MODIFICADO] ---
# Esta função agora adiciona um <div id="..."> em volta do conteúdo divergente
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
            
            # --- [NOVA LÓGICA] ---
            # Cria o ID da âncora e envolve o conteúdo marcado com ele
            secao_canonico = diff['secao']
            anchor_id = _create_anchor_id(secao_canonico, "ref" if eh_referencia else "bel")
            # Adiciona a âncora (div) em volta do conteúdo
            # scroll-margin-top adiciona um "padding" ao rolar, para o título não ficar colado no topo
            conteudo_com_ancora = f"<div id='{anchor_id}' style='scroll-margin-top: 20px;'>{conteudo_marcado}</div>"

            if conteudo_a_marcar in texto_trabalho:
                # Substitui o conteúdo original pelo conteúdo marcado E com âncora
                texto_trabalho = texto_trabalho.replace(conteudo_a_marcar, conteudo_com_ancora)
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
# --- [MODIFICADO] ---
def gerar_relatorio_final(texto_ref, texto_belfar, nome_ref, nome_belfar, tipo_bula):
    
    # --- [NOVO] Script JavaScript para a rolagem ---
    # Injeta o script JS que fará a rolagem.
    # Usamos st.html() que é a forma moderna e segura de fazer isso.
    js_scroll_script = """
    <script>
    function scrollToSection(anchorIdRef, anchorIdBelfar) {
        // Encontra os containers de rolagem pelos IDs que definimos
        var containerRef = document.getElementById('container-ref-scroll');
        var containerBel = document.getElementById('container-bel-scroll');
        
        // Encontra os elementos (âncoras) dentro dos containers
        var anchorRef = document.getElementById(anchorIdRef);
        var anchorBel = document.getElementById(anchorIdBel);

        if (containerRef && anchorRef) {
            // Calcula a posição da âncora relativa ao topo do container
            var topPosRef = anchorRef.offsetTop - containerRef.offsetTop;
            // Rola o container para essa posição (com -20px de padding)
            containerRef.scrollTo({ top: topPosRef - 20, behavior: 'smooth' });
            
            // Adiciona um destaque visual temporário
            anchorRef.style.transition = 'background-color 0.5s ease-in-out';
            anchorRef.style.backgroundColor = '#e6f7ff'; // Azul claro
            setTimeout(() => { anchorRef.style.backgroundColor = 'transparent'; }, 2500);
        }
        
        if (containerBel && anchorBel) {
            var topPosBel = anchorBel.offsetTop - containerBel.offsetTop;
            containerBel.scrollTo({ top: topPosBel - 20, behavior: 'smooth' });
            
            // Destaque
            anchorBel.style.transition = 'background-color 0.5s ease-in-out';
            anchorBel.style.backgroundColor = '#e6f7ff';
            setTimeout(() => { anchorBel.style.backgroundColor = 'transparent'; }, 2500);
        }
    }
    </script>
    """
    st.html(js_scroll_script)
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
    st.info(f"ℹ️ **Datas de Aprovação ANVISA:**\n - Referência: `{data_ref}`\n - BELFAR: `{data_belfar}`")

    if secoes_faltantes:
        st.error(f"🚨 **Seções faltantes na bula BELFAR ({len(secoes_faltantes)})**:\n" + "\n".join([f" - {s}" for s in secoes_faltantes]))
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
            with st.expander(f"📄 {diff['secao']} - ❌ CONTEÚDO DIVERGENTE"):
                
                # --- [NOVO] Botão de Rolagem ---
                secao_canonico = diff['secao']
                anchor_id_ref = _create_anchor_id(secao_canonico, "ref")
                anchor_id_bel = _create_anchor_id(secao_canonico, "bel")

                # Botão HTML que chama a função JavaScript
                st.html(f"""
                    <button 
                        onclick="scrollToSection('{anchor_id_ref}', '{anchor_id_bel}')"
                        style="
                            background-color: #007bff; color: white; border: none; 
                            padding: 8px 16px; border-radius: 5px; cursor: pointer;
                            font-weight: bold; margin-bottom: 15px; width: 100%;
                            text-align: center;
                        "
                    >
                        Ir para esta Seção na Comparação Lado a Lado ⬇️
                    </button>
                """)
                # --- [FIM DO BOTÃO] ---
                
                expander_html_ref = marcar_diferencas_palavra_por_palavra(
                    diff['conteudo_ref'], diff['conteudo_belfar'], eh_referencia=True
                ).replace('\n', '<br>')
                expander_html_belfar = marcar_diferencas_palavra_por_palavra(
                    diff['conteudo_ref'], diff['conteudo_belfar'], eh_referencia=False
                ).replace('\n', '<br>')

                c1, c2 = st.columns(2)
                with c1:
                    st.markdown("**Referência:**")
                    st.markdown(f"<div style='{expander_caixa_style}'>{expander_html_ref}</div>", unsafe_allow_html=True)
                with c2:
                    st.markdown("**BELFAR:**")
                    st.markdown(f"<div style='{expander_caixa_style}'>{expander_html_belfar}</div>", unsafe_allow_html=True)
    else:
        st.success("✅ Conteúdo das seções está idêntico")

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

    html_ref_marcado = marcar_divergencias_html(texto_original=texto_ref, secoes_problema=diferencas_conteudo, erros_ortograficos=[], tipo_bula=tipo_bula, eh_referencia=True).replace('\n', '<br>')
    html_belfar_marcado = marcar_divergencias_html(texto_original=texto_belfar, secoes_problema=diferencas_conteudo, erros_ortograficos=erros_ortograficos, tipo_bula=tipo_bula, eh_referencia=False).replace('\n', '<br>')

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
        # --- [MODIFICADO] Adiciona ID ao container de rolagem ---
        st.markdown(f"<div id='container-ref-scroll' style='{caixa_style}'>{html_ref_marcado}</div>", unsafe_allow_html=True)
    with col2:
        st.markdown(f"**📄 {nome_belfar}**")
        # --- [MODIFICADO] Adiciona ID ao container de rolagem ---
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
    pdf_ref = st.file_uploader("Envie o PDF de referência", type="pdf", key="ref")
with col2:
    st.subheader("📄 Med. BELFAR")
    pdf_belfar = st.file_uploader("Envie o PDF Belfar", type="pdf", key="belfar")

if st.button("🔍 Iniciar Auditoria Completa", use_container_width=True, type="primary"):
    if pdf_ref and pdf_belfar:
        with st.spinner("🔄 Processando e analisando as bulas..."):
            texto_ref, erro_ref = extrair_texto(pdf_ref, 'pdf')
            texto_belfar, erro_belfar = extrair_texto(pdf_belfar, 'pdf')

            if not erro_ref:
                texto_ref = truncar_apos_anvisa(texto_ref)
            if not erro_belfar:
                texto_belfar = truncar_apos_anvisa(texto_belfar)

            if erro_ref or erro_belfar:
                st.error(f"Erro ao processar arquivos: {erro_ref or erro_belfar}")
            else:
                gerar_relatorio_final(texto_ref, texto_belfar, "Bula Referência", "Bula BELFAR", tipo_bula_selecionado)
    else:
        st.warning("⚠️ Por favor, envie ambos os arquivos PDF para iniciar a auditoria.")

st.divider()
st.caption("Sistema de Auditoria de Bulas v18.0 | Arquitetura de Mapeamento Final")
