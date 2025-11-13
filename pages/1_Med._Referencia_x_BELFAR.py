# -*- coding: utf-8 -*-
# Aplicativo Streamlit: Auditoria de Bulas (versão ajustada - extração de seções reforçada)
# Objetivo: garantir que cada seção extraia somente seu conteúdo (sem vazamento de outras seções)
# e que nenhuma seção canônica (ex: "DIZERES LEGAIS", seção 5 etc.) seja omitida.
#
# Principais melhorias nesta versão:
# - Construção de "heading_candidates" (todas as linhas plausíveis como títulos) com:
#     * detecção de títulos por heurística (maiuscula/início, tamanho)
#     * detecção de cabeçalhos numéricos ("9.", "10)", "5 -")
#     * fuzzy match contra títulos canônicos e aliases
# - Mapeamento determinístico das seções canônicas seguindo a ordem prevista:
#     * cada seção canônica é vinculada ao candidate mais provável à frente do texto
#     * os limites das seções são definidos estritamente entre início do título e início do próximo título
# - Fallbacks adicionais para localizar títulos divididos em múltiplas linhas ou com pequenas variações
# - Pequenos ajustes na extração e pre-processamento para preservar layout e evitar perda de títulos
#
# Substitua seu arquivo atual por este. Teste com seus PDFs. Se ainda houver algum caso extremo,
# envie as páginas/textos problemáticos e eu ajusto os heurísticos.

import streamlit as st
import fitz  # PyMuPDF
import docx
import re
import spacy
from thefuzz import fuzz
from spellchecker import SpellChecker
import difflib
import unicodedata
from collections import defaultdict, namedtuple

# UI tweaks
hide_streamlit_UI = """
<style>
[data-testid="stHeader"] { display: none !important; visibility: hidden !important; }
[data-testid="main-menu-button"] { display: none !important; }
footer { display: none !important; visibility: hidden !important; }
[data-testid="stStatusWidget"], [data-testid="stCreatedBy"], [data-testid="stHostedBy"] {
display: none !important; visibility: hidden !important;
}
</style>
"""
st.markdown(hide_streamlit_UI, unsafe_allow_html=True)

# ----------------- NLP -----------------
@st.cache_resource
def carregar_modelo_spacy():
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
                    page_text = page.get_text("text", sort=True)
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

            padrao_rodape = re.compile(r'bula (?:do|para o) paciente|página \d+\s*de\s*\d+', re.IGNORECASE)
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

# ----------------- CONFIGURAÇÃO -----------------
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
        "INDICAÇÕES": "PARA QUE ESTE MEDICAMENTO É INDICADO",
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
    return ["COMPOSIÇÃO", "DIZERES LEGAIS", "APRESENTAÇÕES"]

# ----------------- NORMALIZAÇÃO -----------------
def normalizar_texto(texto):
    texto = '' if texto is None else texto
    texto = ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')
    texto = re.sub(r'[^\w\s]', '', texto)
    texto = ' '.join(texto.split())
    return texto.lower()

def normalizar_titulo_para_comparacao(texto):
    texto = '' if texto is None else texto
    texto_norm = normalizar_texto(texto)
    texto_norm = re.sub(r'^\s*(\d{1,2})\s*[\.\)\-]?\s*', '', texto_norm).strip()
    return texto_norm

def _create_anchor_id(secao_nome, prefix):
    norm = normalizar_texto(secao_nome)
    norm_safe = re.sub(r'[^a-z0-9\-]', '-', norm)
    return f"anchor-{prefix}-{norm_safe}"

# ----------------- HEURÍSTICAS DE TÍTULO -----------------
HeadingCandidate = namedtuple("HeadingCandidate", ["index", "raw", "norm", "numeric", "matched_canon", "score"])

def construir_heading_candidates(linhas, secoes_esperadas, aliases):
    """
    Gera lista de candidatos a título em todo o texto.
    Cada candidato tem:
      - index (linha)
      - raw (linha original)
      - norm (normalizada)
      - numeric (se começava com número)
      - matched_canon (canonical title matched or None)
      - score (fuzzy score)
    """
    titulos_possiveis = {}
    for s in secoes_esperadas:
        titulos_possiveis[s] = s
    for a, c in aliases.items():
        if c in secoes_esperadas:
            titulos_possiveis[a] = c

    titulos_norm = {k: normalizar_titulo_para_comparacao(k) for k in titulos_possiveis.keys()}

    candidates = []
    for i, linha in enumerate(linhas):
        raw = linha.strip()
        if not raw:
            continue
        norm = normalizar_titulo_para_comparacao(raw)

        # Heurística básica: linhas majoritariamente em MAIÚSCULAS ou iniciando com número são candidatas
        is_upper = sum(1 for ch in raw if ch.isalpha() and ch.isupper()) >= max(1, int(len(re.findall(r'[A-Za-z]', raw)) * 0.6))
        starts_with_cap = raw and (raw[0].isupper() or raw[0].isdigit())

        numeric = None
        mnum = re.match(r'^\s*(\d{1,2})\s*[\.\)\-]?\s*(.*)$', raw)
        if mnum:
            try:
                numeric = int(mnum.group(1))
            except Exception:
                numeric = None

        # fuzzy scoring vs all canonical/aliases
        best_score = 0
        best_canon = None
        for titulo_possivel, titulo_canonico in titulos_possiveis.items():
            t_norm = titulos_norm.get(titulo_possivel, normalizar_titulo_para_comparacao(titulo_possivel))
            if not t_norm:
                continue
            score = fuzz.token_set_ratio(t_norm, norm)
            # boost if substring
            if t_norm in norm:
                score = max(score, 95)
            if score > best_score:
                best_score = score
                best_canon = titulo_canonico

        # decide se é candidato: upper-case strong OR numeric OR fuzzy high OR starts_with_cap + short line
        is_candidate = False
        if numeric is not None:
            is_candidate = True
        elif best_score >= 88:
            is_candidate = True
        elif is_upper and len(raw.split()) <= 8:
            is_candidate = True
        elif starts_with_cap and len(raw.split()) <= 6 and re.search(r'[A-ZÁÉÍÓÚÂÊÔÃÕÇ]', raw):
            is_candidate = True

        if is_candidate:
            candidates.append(HeadingCandidate(index=i, raw=raw, norm=norm, numeric=numeric, matched_canon=best_canon if best_score >= 80 else None, score=best_score))
    # ensure unique indices and sorted
    candidates = sorted({c.index: c for c in candidates}.values(), key=lambda x: x.index)
    return candidates

# ----------------- MAPEAMENTO FORTE DAS SEÇÕES -----------------
def mapear_secoes_deterministico(texto_completo, secoes_esperadas):
    linhas = texto_completo.split('\n')
    aliases = obter_aliases_secao()

    candidates = construir_heading_candidates(linhas, secoes_esperadas, aliases)
    # cria lista de títulos normais para lookup
    titulos_lista = [normalizar_titulo_para_comparacao(t) for t in secoes_esperadas]
    titulos_set = set(titulos_lista)

    # para cada seção canônica (na ordem dada), tenta encontrar candidate que corresponda e que esteja após o último mapeado
    mapa = []
    used_indices = set()
    last_idx = -1
    for sec_idx, sec in enumerate(secoes_esperadas):
        sec_norm = normalizar_titulo_para_comparacao(sec)
        found = None
        # 1) procura candidate com matched_canon == sec (prioridade) e index > last_idx
        for c in candidates:
            if c.index <= last_idx:
                continue
            if c.matched_canon == sec:
                found = c
                break
        # 2) procura candidate numeric == sec_idx+1 (ex: section 5)
        if found is None:
            for c in candidates:
                if c.index <= last_idx:
                    continue
                if c.numeric == (sec_idx + 1):
                    found = c
                    break
        # 3) procura candidate whose normalized contains the section norm (substring)
        if found is None:
            for c in candidates:
                if c.index <= last_idx:
                    continue
                if sec_norm and sec_norm in c.norm:
                    found = c
                    break
        # 4) fuzzy match candidate -> sec
        if found is None:
            for c in candidates:
                if c.index <= last_idx:
                    continue
                if fuzz.token_set_ratio(sec_norm, c.norm) >= 92:
                    found = c
                    break
        # 5) fallback: busca a linha exata no texto (procurar a primeira ocorrência do título canônico normalizado)
        if found is None:
            for i in range(last_idx + 1, len(linhas)):
                if normalizar_titulo_para_comparacao(linhas[i]).startswith(sec_norm) or sec_norm in normalizar_titulo_para_comparacao(linhas[i]):
                    found = HeadingCandidate(index=i, raw=linhas[i].strip(), norm=normalizar_titulo_para_comparacao(linhas[i]), numeric=None, matched_canon=sec, score=100)
                    break

        if found:
            mapa.append({'canonico': sec, 'titulo_encontrado': found.raw, 'linha_inicio': found.index, 'score': found.score})
            used_indices.add(found.index)
            last_idx = found.index
        else:
            # seção não encontrada - não adicionamos ao mapa, será marcada como faltante posteriormente
            pass

    # ordena o mapa por linha_inicio
    mapa = sorted(mapa, key=lambda x: x['linha_inicio'])
    return mapa, candidates, linhas

# ----------------- OBTER CONTEÚDO DA SEÇÃO (AGORA USANDO MAPA DETERMINÍSTICO) -----------------
def obter_dados_secao_v2(secao_canonico, mapa_secoes, linhas_texto, tipo_bula):
    """
    Usa o mapa determinístico (mapa_secoes) para extrair conteúdo entre linhas.
    """
    # buscar entrada no mapa
    entrada = None
    for m in mapa_secoes:
        if m['canonico'] == secao_canonico:
            entrada = m
            break
    if not entrada:
        return False, None, ""

    linha_inicio = entrada['linha_inicio']
    # encontrar próximo índice no mapa que seja maior que linha_inicio
    sorted_map = sorted(mapa_secoes, key=lambda x: x['linha_inicio'])
    prox_idx = None
    for m in sorted_map:
        if m['linha_inicio'] > linha_inicio:
            prox_idx = m['linha_inicio']
            break
    linha_fim = prox_idx if prox_idx is not None else len(linhas_texto)
    conteudo_lines = []
    # coletar somente linhas estritamente entre inicio+1 e fim-1 (exclui o título detectado)
    for i in range(linha_inicio + 1, linha_fim):
        # evita incluir outro título detectado erroneamente: se a linha for um candidate cuja norm esteja
        # muito próxima de algum título canônico, pulamos (proteção extra)
        line_norm = normalizar_titulo_para_comparacao(linhas_texto[i])
        # se a linha normalizada exatamente for um título canônico, paramos (defensive)
        if line_norm in {normalizar_titulo_para_comparacao(s) for s in obter_secoes_por_tipo(tipo_bula)}:
            # encontramos início de próxima seção real
            break
        conteudo_lines.append(linhas_texto[i])
    conteudo_final = "\n".join(conteudo_lines).strip()
    return True, entrada['titulo_encontrado'], conteudo_final

# ----------------- CONTEÚDO E VERIFICAÇÃO -----------------
def verificar_secoes_e_conteudo(texto_ref, texto_belfar, tipo_bula):
    secoes_esperadas = obter_secoes_por_tipo(tipo_bula)
    secoes_faltantes, diferencas_conteudo, similaridades_secoes, diferencas_titulos = [], [], [], []
    secoes_analisadas = []

    # cria mapas determinísticos para ambos os textos
    mapa_ref, candidates_ref, linhas_ref = mapear_secoes_deterministico(texto_ref, secoes_esperadas)
    mapa_belfar, candidates_belfar, linhas_belfar = mapear_secoes_deterministico(texto_belfar, secoes_esperadas)

    # para cada seção esperada, extrai conteúdo a partir de mapas
    for sec in secoes_esperadas:
        encontrou_ref, titulo_ref, conteudo_ref = obter_dados_secao_v2(sec, mapa_ref, linhas_ref, tipo_bula)
        encontrou_belfar, titulo_belfar, conteudo_belfar = obter_dados_secao_v2(sec, mapa_belfar, linhas_belfar, tipo_bula)

        if not encontrou_ref and not encontrou_belfar:
            secoes_faltantes.append(sec)
            secoes_analisadas.append({
                'secao': sec,
                'conteudo_ref': "Seção não encontrada na Referência",
                'conteudo_belfar': "Seção não encontrada no documento Belfar",
                'titulo_encontrado_ref': None,
                'titulo_encontrado_belfar': None,
                'tem_diferenca': True,
                'ignorada': False,
                'faltante': True
            })
            continue

        if not encontrou_belfar:
            secoes_faltantes.append(sec)
            secoes_analisadas.append({
                'secao': sec,
                'conteudo_ref': conteudo_ref if encontrou_ref else "Seção não encontrada na Referência",
                'conteudo_belfar': "Seção não encontrada no documento Belfar",
                'titulo_encontrado_ref': titulo_ref,
                'titulo_encontrado_belfar': None,
                'tem_diferenca': True,
                'ignorada': False,
                'faltante': True
            })
            continue

        # comparação
        tem_diferenca = False
        if normalizar_texto(conteudo_ref) != normalizar_texto(conteudo_belfar):
            tem_diferenca = True
            diferencas_conteudo.append({
                'secao': sec,
                'conteudo_ref': conteudo_ref,
                'conteudo_belfar': conteudo_belfar,
                'titulo_encontrado_ref': titulo_ref,
                'titulo_encontrado_belfar': titulo_belfar
            })
            similaridades_secoes.append(0)
        else:
            similaridades_secoes.append(100)

        secoes_analisadas.append({
            'secao': sec,
            'conteudo_ref': conteudo_ref,
            'conteudo_belfar': conteudo_belfar,
            'titulo_encontrado_ref': titulo_ref,
            'titulo_encontrado_belfar': titulo_belfar,
            'tem_diferenca': tem_diferenca,
            'ignorada': False,
            'faltante': False
        })

    return secoes_faltantes, diferencas_conteudo, similaridades_secoes, diferencas_titulos, secoes_analisadas

# ----------------- ORTOGRAFIA (MELHORADA) -----------------
def checar_ortografia_inteligente(texto_para_checar, texto_referencia, tipo_bula):
    if not texto_para_checar:
        return []

    try:
        secoes_ignorar = obter_secoes_ignorar_ortografia()
        secoes_todas = obter_secoes_por_tipo(tipo_bula)
        texto_filtrado_para_checar = []

        def pre_processar_texto(texto_completo):
            linhas_originais = texto_completo.split('\n')
            linhas = []
            regex_split = re.compile(r'^(.+?[?\.])\s*([A-ZÁÉÍÓÚÂÊÔÃÕÇ].*)$')
            for l in linhas_originais:
                match = regex_split.match(l.strip())
                if match:
                    titulo_potencial = match.group(1).strip()
                    conteudo_potencial = match.group(2).strip()
                    if is_titulo_secao(titulo_potencial) and len(titulo_potencial.split()) > 2:
                        linhas.append(titulo_potencial)
                        linhas.append(conteudo_potencial)
                    else:
                        linhas.append(l)
                else:
                    linhas.append(l)
            return "\n".join(linhas)

        texto_proc_para_checar = pre_processar_texto(texto_para_checar)
        mapa_secoes, _, linhas_texto = mapear_secoes_deterministico(texto_proc_para_checar, secoes_todas)

        for secao_nome in secoes_todas:
            if secao_nome.upper() in [s.upper() for s in secoes_ignorar]:
                continue
            encontrou, _, conteudo = obter_dados_secao_v2(secao_nome, mapa_secoes, linhas_texto, tipo_bula)
            if encontrou and conteudo:
                texto_filtrado_para_checar.append(conteudo)

        texto_final_para_checar = '\n'.join(texto_filtrado_para_checar)
        if not texto_final_para_checar:
            return []

        spell = SpellChecker(language='pt')
        palavras_a_ignorar = {"alair", "belfar", "peticionamento", "urotrobel", "nebacetin", "neomicina", "bacitracina"}
        vocab_referencia_raw = set(re.findall(r'\b[a-zA-ZÀ-ÖØ-öø-ÿ0-9\-]+\b', texto_referencia.lower()))
        vocab_referencia_norm = set(normalizar_texto(w) for w in vocab_referencia_raw)
        spell.word_frequency.load_words(vocab_referencia_raw.union(palavras_a_ignorar))

        entidades = set()
        if nlp:
            doc = nlp(texto_proc_para_checar)
            entidades = {ent.text.lower() for ent in doc.ents}

        palavras = re.findall(r'\b[a-zA-ZÀ-ÖØ-öø-ÿ]+\b', texto_final_para_checar)
        palavras = [p for p in palavras if len(p) > 2]

        possiveis_erros = set(spell.unknown([p.lower() for p in palavras]))

        erros_filtrados = []
        for e in possiveis_erros:
            e_raw = e.lower()
            e_norm = normalizar_texto(e_raw)
            if e_raw in vocab_referencia_raw or e_norm in vocab_referencia_norm:
                continue
            if e_raw in entidades:
                continue
            if e_raw in palavras_a_ignorar:
                continue
            if nlp:
                try:
                    lex = nlp.vocab[e_raw]
                    if not getattr(lex, "is_oov", True):
                        continue
                except Exception:
                    pass
            erros_filtrados.append(e_raw)

        erros_unicos = sorted(set(erros_filtrados))
        return erros_unicos[:60]
    except Exception:
        return []

# ----------------- DIFERENÇAS PALAVRA A PALAVRA -----------------
def marcar_diferencas_palavra_por_palavra(texto_ref, texto_belfar, eh_referencia):
    def tokenizar(txt):
        return re.findall(r'\n|[A-Za-zÀ-ÖØ-öø-ÿ0-9_•]+|[^\w\s]', txt, re.UNICODE)

    def norm(tok):
        if tok == '\n':
            return ' '
        if re.match(r'[A-Za-zÀ-ÖØ-öø-ÿ0-9_•]+$', tok):
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
        if tok == '\n':
            marcado.append('<br>')
            continue
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
        if tok == '<br>' or marcado[i-1] == '<br>':
            resultado += tok
        elif re.match(r'^[^\w\s]$', raw_tok):
            resultado += tok
        else:
            resultado += " " + tok

    resultado = re.sub(r'\s+([.,;:!?)])', r'\1', resultado)
    resultado = re.sub(r'(\()\s+', r'\1', resultado)
    resultado = re.sub(r"(</mark>)\s+(<mark[^>]*>)", " ", resultado)
    return resultado

# ----------------- CONSTRUÇÃO DO HTML -----------------
def construir_html_secoes(secoes_analisadas, erros_ortograficos, tipo_bula, eh_referencia=False):
    html_final = []
    prefixos_paciente = {
        "PARA QUE ESTE MEDICAMENTO É INDICADO": "1.", "COMO ESTE MEDICAMENTO FUNCIONA?": "2.",
        "QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?": "3.", "O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?": "4.",
        "ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?": "5.", "COMO DEVO USAR ESTE MEDICAMENTO?": "6.",
        "O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?": "7.", "QUAIS OS MALES QUE ESTE MEDICAMENTO PODE CAUSAR?": "8.",
        "O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?": "9."
    }
    prefixos_profissional = {
        "INDICAÇÕES": "1.", "RESULTADOS DE EFICÁCIA": "2.", "CARACTERÍSTICAS FARMACOLÓGICAS": "3.",
        "CONTRAINDICAÇÕES": "4.", "ADVERTÊNCIAS E PRECAUÇÕES": "5.", "INTERAÇÕES MEDICAMENTOSAS": "6.",
        "CUIDADOS DE ARMAZENAMENTO DO MEDICAMENTO": "7.", "POSOLOGIA E MODO DE USAR": "8.",
        "REAÇÕES ADVERSAS": "9.", "SUPERDOSE": "10."
    }
    prefixos_map = prefixos_paciente if tipo_bula == "Paciente" else prefixos_profissional

    mapa_erros = {}
    if erros_ortograficos and not eh_referencia:
        for erro in erros_ortograficos:
            pattern = r'(?<![<>a-zA-Z])(?<!mark>)(?<!;>)\b(' + re.escape(erro) + r')\b(?![<>])'
            mapa_erros[pattern] = r"<mark style='background-color: #FFDDC1; padding: 2px;'>\1</mark>"

    regex_anvisa = r"((?:aprovad[ao]\s+pela\s+anvisa\s+em|data\s+de\s+aprovação\s+na\s+anvisa:)\s*[\d]{1,2}/[\d]{1,2}/[\d]{2,4})"
    anvisa_pattern = re.compile(regex_anvisa, re.IGNORECASE)

    for diff in secoes_analisadas:
        secao_canonico = diff['secao']
        prefixo = prefixos_map.get(secao_canonico, "")

        if eh_referencia:
            titulo_display = f"{prefixo} {secao_canonico}".strip()
            html_final.append(f"<h3 style='font-size: 16px; font-weight: bold; color: #111;'>{titulo_display}</h3>")
        else:
            titulo_encontrado = diff.get('titulo_encontrado_belfar') or diff.get('titulo_encontrado_ref') or secao_canonico
            if prefixo and not titulo_encontrado.strip().startswith(prefixo):
                titulo_display = f"{prefixo} {titulo_encontrado}".strip()
            else:
                titulo_display = titulo_encontrado
            html_final.append(f"<h3 style='font-size: 16px; font-weight: bold; color: #111;'>{titulo_display}</h3>")

        conteudo = diff['conteudo_ref'] if eh_referencia else diff['conteudo_belfar']
        if diff.get('faltante', False) and not eh_referencia:
            conteudo = "<p style='color: red; font-style: italic;'>Seção não encontrada</p>"

        if diff['tem_diferenca'] and not diff['ignorada'] and not diff.get('faltante', False):
            conteudo_marcado = marcar_diferencas_palavra_por_palavra(diff['conteudo_ref'], diff['conteudo_belfar'], eh_referencia)
        else:
            conteudo_marcado = (conteudo or "").replace('\n', '<br>')

        if not eh_referencia and not diff['ignorada']:
            for pattern, replacement in mapa_erros.items():
                try:
                    conteudo_marcado = re.sub(pattern, replacement, conteudo_marcado, flags=re.IGNORECASE)
                except Exception:
                    pass

        conteudo_marcado = anvisa_pattern.sub(
            r"<mark style='background-color: #cce5ff; padding: 2px; font-weight: 500;'>\1</mark>",
            conteudo_marcado
        )

        anchor_id = _create_anchor_id(secao_canonico, "ref" if eh_referencia else "bel")
        html_final.append(f"<div id='{anchor_id}' style='scroll-margin-top: 20px;'>{conteudo_marcado}</div><br>")

    return "".join(html_final)

# ----------------- RELATÓRIO E INTERFACE -----------------
def gerar_relatorio_final(texto_ref, texto_belfar, nome_ref, nome_belfar, tipo_bula):
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
    regex_anvisa = r"(aprovad[ao]\s+pela\s+anvisa\s+em|data\s+de\s+aprovação\s+na\s+anvisa:)\s*([\d]{1,2}/[\d]{1,2}/[\d]{2,4})"
    match_ref = re.search(regex_anvisa, texto_ref.lower())
    match_belfar = re.search(regex_anvisa, texto_belfar.lower())
    data_ref = match_ref.group(2).strip() if match_ref else "Não encontrada"
    data_belfar = match_belfar.group(2).strip() if match_belfar else "Não encontrada"

    secoes_faltantes, diferencas_conteudo, similaridades, diferencas_titulos, secoes_analisadas = verificar_secoes_e_conteudo(texto_ref, texto_belfar, tipo_bula)
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
        
    if secoes_analisadas:
        st.markdown("##### Análise Detalhada de Conteúdo das Seções")
        expander_caixa_style = (
            "height: 350px; overflow-y: auto; border: 2px solid #d0d0d0; border-radius: 6px; "
            "padding: 16px; background-color: #ffffff; font-size: 14px; line-height: 1.8; "
            "font-family: 'Georgia', 'Times New Roman', serif; text-align: justify;"
        )

        prefixos_paciente = {
            "PARA QUE ESTE MEDICAMENTO É INDICADO": "1.", "COMO ESTE MEDICAMENTO FUNCIONA?": "2.",
            "QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?": "3.", "O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?": "4.",
            "ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?": "5.", "COMO DEVO USAR ESTE MEDICAMENTO?": "6.",
            "O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?": "7.", "QUAIS OS MALES QUE ESTE MEDICAMENTO PODE CAUSAR?": "8.",
            "O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?": "9."
        }
        prefixos_profissional = {
            "INDICAÇÕES": "1.", "RESULTADOS DE EFICÁCIA": "2.", "CARACTERÍSTICAS FARMACOLÓGICAS": "3.",
            "CONTRAINDICAÇÕES": "4.", "ADVERTÊNCIAS E PRECAUÇÕES": "5.", "INTERAÇÕES MEDICAMENTOSAS": "6.",
            "CUIDADOS DE ARMAZENAMENTO DO MEDICAMENTO": "7.", "POSOLOGIA E MODO DE USAR": "8.",
            "REAÇÕES ADVERSAS": "9.", "SUPERDOSE": "10."
        }
        prefixos_map = prefixos_paciente if tipo_bula == "Paciente" else prefixos_profissional

        for diff in secoes_analisadas:
            secao_canonico_raw = diff['secao']
            prefixo = prefixos_map.get(secao_canonico_raw, "")
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
                secao_canonico = diff['secao']
                anchor_id_ref = _create_anchor_id(secao_canonico, "ref")
                anchor_id_bel = _create_anchor_id(secao_canonico, "bel")
                
                if diff.get('faltante', False):
                    st.error(f"**A seção \"{secao_canonico}\" não foi encontrada no documento Belfar.**")
                    if "não encontrada na Referência" in diff['conteudo_ref']:
                        st.warning(f"**A seção \"{secao_canonico}\" também não foi encontrada no documento de Referência.**")
                    expander_html_ref = diff['conteudo_ref'].replace('\n', '<br>') if diff['conteudo_ref'] else "<i>Não encontrada</i>"
                    expander_html_belfar = "<p style='color: red; font-style: italic;'>Seção não encontrada</p>"
                elif diff['ignorada']:
                    expander_html_ref = diff['conteudo_ref'].replace('\n', '<br>')
                    expander_html_belfar = diff['conteudo_belfar'].replace('\n', '<br>')
                else:
                    expander_html_ref = marcar_diferencas_palavra_por_palavra(diff['conteudo_ref'], diff['conteudo_belfar'], eh_referencia=True)
                    expander_html_belfar = marcar_diferencas_palavra_por_palavra(diff['conteudo_ref'], diff['conteudo_belfar'], eh_referencia=False)

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

    html_ref_marcado = construir_html_secoes(secoes_analisadas, [], tipo_bula, eh_referencia=True)
    html_belfar_marcado = construir_html_secoes(secoes_analisadas, erros_ortograficos, tipo_bula, eh_referencia=False)

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

# ----------------- INTERFACE PRINCIPAL -----------------
st.set_page_config(layout="wide", page_title="Auditoria de Bulas", page_icon="🔬")
st.title("🔬 Inteligência Artificial para Auditoria de Bulas (v21.3)")
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
            with st.spinner("Lendo documento de Referência..."):
                texto_ref, erro_ref = extrair_texto(pdf_ref, tipo_ref)
            with st.spinner("Lendo documento Belfar..."):
                texto_belfar, erro_belfar = extrair_texto(pdf_belfar, tipo_belfar)

            if not erro_ref:
                texto_ref = truncar_apos_anvisa(texto_ref)
            if not erro_belfar:
                texto_belfar = truncar_apos_anvisa(texto_belfar)

            if erro_ref or erro_belfar:
                st.error(f"Erro ao processar arquivos: {erro_ref or erro_belfar}")
            else:
                gerar_relatorio_final(texto_ref, texto_belfar, pdf_ref.name, pdf_belfar.name, tipo_bula_selecionado)
    else:
        st.warning("⚠️ Por favor, envie ambos os arquivos PDF ou DOCX para iniciar a auditoria.")

st.divider()
st.caption("Sistema de Auditoria de Bulas v21.3 | Extração de seções reforçada")
