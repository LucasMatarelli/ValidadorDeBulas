# -*- coding: utf-8 -*-
# Aplicativo Streamlit: Auditoria de Bulas (versão corrigida)
# Principais correções nesta versão:
# - Fix: NÃO pular mais exibição da "Referência" quando a seção está faltando no Belfar
# - Fix: Detecção de títulos mais robusta (limiar fuzzy reduzido, verificações por substring,
#        fallback para localizar títulos diretamente nas linhas) — corrige casos onde "DIZERES LEGAIS"
#        ou a seção 5 não apareciam.
# - Fix: Detecção de início de seção a partir de cabeçalhos numéricos ("9.", "9)", "10-") para evitar
#        vazamento de conteúdo entre seções (ex.: seção 9 aparecendo dentro da 8).
# - Fix: Redução de falsos positivos em checagem ortográfica:
#        agora filtramos pelos vocabulários de referência (formas normalizadas e originais),
#        entidades reconhecidas pelo SpaCy e pelo status is_oov do lexema no modelo SpaCy
#        (quando disponível). Isso reduz marcações de palavras válidas como erros.
#
# Uso: Substitua seu arquivo atual por este. Requisitos anteriores permanecem (streamlit, fitz, spacy, thefuzz, spellchecker, etc).

import streamlit as st
import fitz # PyMuPDF
import docx
import re
import spacy
from thefuzz import fuzz
from spellchecker import SpellChecker
import difflib
import unicodedata
from collections import defaultdict

# --- UI tweaks (esconde ferramentas do Streamlit) ---
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

# ----------------- MODELO NLP -----------------
@st.cache_resource
def carregar_modelo_spacy():
    """Carrega modelo SpaCy pt_core_news_lg se disponível."""
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
                    # Mantém layout com get_text("text", sort=True)
                    page_text = page.get_text("text", sort=True)
                    full_text_list.append(page_text)
            texto = "\n".join(full_text_list)
        elif tipo_arquivo == 'docx':
            doc = docx.Document(arquivo)
            texto = "\n".join([p.text for p in doc.paragraphs])
            
        if texto:
            # Limpeza básica
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
    texto_norm = normalizar_texto(texto)
    # remove número inicial (ex: "9.", "10)", "5 -")
    texto_norm = re.sub(r'^\s*(\d{1,2})\s*[\.\)\-]?\s*', '', texto_norm).strip()
    return texto_norm

def _create_anchor_id(secao_nome, prefix):
    norm = normalizar_texto(secao_nome)
    norm_safe = re.sub(r'[^a-z0-9\-]', '-', norm)
    return f"anchor-{prefix}-{norm_safe}"

# ----------------- DETECTAR TÍTULOS E MAPEAR -----------------
def is_titulo_secao(linha):
    linha = (linha or "").strip()
    if not linha or len(linha) < 4:
        return False
    # Título de seção começa com maiúscula ou número
    if linha[0].islower():
        return False
    if len(linha.split()) > 20:
        return False
    if linha.endswith(':'):
        return False
    if re.search(r'\>\s*\<', linha):
        return False
    if len(linha) > 160:
        return False
    return True

def mapear_secoes(texto_completo, secoes_esperadas):
    """
    Mapeia títulos no texto usando fuzzy matching e heurísticas.
    Tornamos o matching mais permissivo (limiar reduzido e substring) para
    não perder títulos como "DIZERES LEGAIS" em diferentes formatações.
    """
    mapa = []
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

    aliases = obter_aliases_secao()
    titulos_possiveis = {}
    for secao in secoes_esperadas:
        titulos_possiveis[secao] = secao
    for alias, canonico in aliases.items():
        if canonico in secoes_esperadas:
            titulos_possiveis[alias] = canonico

    # Normaliza possíveis títulos canônicos (set para lookup)
    titulos_norm = {k: normalizar_titulo_para_comparacao(k) for k in titulos_possiveis.keys()}

    for idx, linha in enumerate(linhas):
        linha_limpa = linha.strip()
        if not is_titulo_secao(linha_limpa):
            continue

        linha_norm = normalizar_titulo_para_comparacao(linha_limpa)
        if not linha_norm:
            continue

        best_score = 0
        best_canonico = None

        for titulo_possivel, titulo_canonico in titulos_possiveis.items():
            t_norm = titulos_norm.get(titulo_possivel, normalizar_titulo_para_comparacao(titulo_possivel))
            # fuzzy score
            score = fuzz.token_set_ratio(t_norm, linha_norm)
            # substring boost: if normalized canonical is substring of line, treat as strong match
            if t_norm and t_norm in linha_norm:
                score = max(score, 95)
            if score > best_score:
                best_score = score
                best_canonico = titulo_canonico

        # Limiar mais permissivo: 88. Isso evita perda de títulos por pequenas variações.
        if best_score >= 88:
            # evita duplicar entradas consecutivas idênticas
            if not mapa or mapa[-1]['canonico'] != best_canonico:
                mapa.append({
                    'canonico': best_canonico,
                    'titulo_encontrado': linha_limpa,
                    'linha_inicio': idx,
                    'score': best_score
                })

    mapa.sort(key=lambda x: x['linha_inicio'])
    return mapa

# ----------------- EXTRAÇÃO DE CONTEÚDO DA SEÇÃO -----------------
def obter_dados_secao(secao_canonico, mapa_secoes, linhas_texto, tipo_bula):
    """
    Extrai o conteúdo de uma seção, determinando fim pela próxima seção.
    Inclui fallback: se mapa_secoes não apontar a seção, busca diretamente nas linhas.
    Também detecta cabeçalhos numéricos (9., 10), evitando vazamentos.
    """
    TITULOS_OFICIAIS = {
        "Paciente": obter_secoes_por_tipo("Paciente"),
        "Profissional": obter_secoes_por_tipo("Profissional")
    }

    titulos_lista = TITULOS_OFICIAIS.get(tipo_bula, [])
    titulos_norm_set = {normalizar_titulo_para_comparacao(t) for t in titulos_lista}

    aliases = obter_aliases_secao()
    for alias, canonico in aliases.items():
        if canonico in titulos_lista:
            titulos_norm_set.add(normalizar_titulo_para_comparacao(alias))

    # define secao_num (posição) quando possível
    secao_num = None
    try:
        if secao_canonico in titulos_lista:
            secao_num = titulos_lista.index(secao_canonico) + 1
    except Exception:
        secao_num = None

    # 1) Tenta usar mapa_secoes (extraído por fuzzy matching)
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

            # próximo título canônico exato
            if linha_atual_norm in titulos_norm_set:
                prox_idx = j
                break

            # títulos em 2 ou 3 linhas
            if (j + 1) < len(linhas_texto):
                titulo_duas_linhas_norm = normalizar_titulo_para_comparacao(f"{linha_atual} {linhas_texto[j+1].strip()}")
                if titulo_duas_linhas_norm in titulos_norm_set:
                    prox_idx = j
                    break
            if (j + 2) < len(linhas_texto):
                titulo_tres_linhas_norm = normalizar_titulo_para_comparacao(f"{linha_atual} {linhas_texto[j+1].strip()} {linhas_texto[j+2].strip()}")
                if titulo_tres_linhas_norm in titulos_norm_set:
                    prox_idx = j
                    break

            # verifica cabeçalhos numéricos (ex.: "9.", "10)")
            num_match = re.match(r'^\s*(\d{1,2})\s*[\.\)\-]?\s*(.*)$', linha_atual)
            if num_match:
                try:
                    found_num = int(num_match.group(1))
                    if found_num >= 1 and found_num <= len(titulos_lista):
                        if secao_num is None or found_num != secao_num:
                            prox_idx = j
                            break
                except Exception:
                    pass

            # fuzzy check: se a linha se assemelha a algum título (limiar alto)
            for t_norm in titulos_norm_set:
                if fuzz.token_set_ratio(t_norm, linha_atual_norm) >= 92:
                    prox_idx = j
                    break
            if prox_idx is not None:
                break

        linha_fim = prox_idx if prox_idx is not None else len(linhas_texto)
        conteudo = [linhas_texto[idx] for idx in range(linha_inicio_conteudo, linha_fim)]
        conteudo_final = "\n".join(conteudo).strip()
        return True, titulo_encontrado, conteudo_final

    # 2) Fallback: buscar título diretamente nas linhas_texto
    for idx, linha in enumerate(linhas_texto):
        linha_norm = normalizar_titulo_para_comparacao(linha.strip())
        if not linha_norm:
            continue
        # verifica correspondência direta / substring / fuzzy
        if linha_norm in titulos_norm_set:
            # encontrado título canônico
            linha_inicio = idx
            linha_inicio_conteudo = linha_inicio + 1
            prox_idx = None
            for j in range(linha_inicio_conteudo, len(linhas_texto)):
                ln = linhas_texto[j].strip()
                ln_norm = normalizar_titulo_para_comparacao(ln)
                if ln_norm in titulos_norm_set:
                    prox_idx = j
                    break
                # detect numeric headings
                nm = re.match(r'^\s*(\d{1,2})\s*[\.\)\-]?\s*(.*)$', ln)
                if nm:
                    try:
                        found_num = int(nm.group(1))
                        if found_num >= 1 and found_num <= len(titulos_lista):
                            prox_idx = j
                            break
                    except Exception:
                        pass
                # fuzzy
                for t_norm in titulos_norm_set:
                    if fuzz.token_set_ratio(t_norm, ln_norm) >= 92:
                        prox_idx = j
                        break
                if prox_idx is not None:
                    break
            linha_fim = prox_idx if prox_idx is not None else len(linhas_texto)
            conteudo = [linhas_texto[k] for k in range(linha_inicio_conteudo, linha_fim)]
            conteudo_final = "\n".join(conteudo).strip()
            # título encontrado original (usa a linha como título)
            return True, linhas_texto[linha_inicio].strip(), conteudo_final

    # 3) não encontrado
    return False, None, ""

# ----------------- COMPARAÇÃO DE CONTEÚDO -----------------
def verificar_secoes_e_conteudo(texto_ref, texto_belfar, tipo_bula):
    secoes_esperadas = obter_secoes_por_tipo(tipo_bula)
    secoes_faltantes, diferencas_conteudo, similaridades_secoes, diferencas_titulos = [], [], [], []
    secoes_analisadas = [] 
    secoes_ignorar_upper = [s.upper() for s in obter_secoes_ignorar_comparacao()]

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

    texto_ref_processado = pre_processar_texto(texto_ref)
    texto_belfar_processado = pre_processar_texto(texto_belfar)

    linhas_ref = texto_ref_processado.split('\n')
    linhas_belfar = texto_belfar_processado.split('\n')
    mapa_ref = mapear_secoes(texto_ref_processado, secoes_esperadas)
    mapa_belfar = mapear_secoes(texto_belfar_processado, secoes_esperadas)

    for secao in secoes_esperadas:
        encontrou_ref, titulo_ref, conteudo_ref = obter_dados_secao(secao, mapa_ref, linhas_ref, tipo_bula)
        encontrou_belfar, titulo_belfar, conteudo_belfar = obter_dados_secao(secao, mapa_belfar, linhas_belfar, tipo_bula)

        if not encontrou_belfar:
            secoes_faltantes.append(secao)
            secoes_analisadas.append({
                'secao': secao,
                'conteudo_ref': conteudo_ref if encontrou_ref else "Seção não encontrada na Referência",
                'conteudo_belfar': "Seção não encontrada no documento Belfar",
                'titulo_encontrado_ref': titulo_ref,
                'titulo_encontrado_belfar': None,
                'tem_diferenca': True,
                'ignorada': False,
                'faltante': True
            })
            continue

        if encontrou_ref or encontrou_belfar:
            titulo_real_encontrado_belfar = titulo_belfar or secao
            if secao.upper() in secoes_ignorar_upper:
                secoes_analisadas.append({
                    'secao': secao,
                    'conteudo_ref': conteudo_ref,
                    'conteudo_belfar': conteudo_belfar,
                    'titulo_encontrado_ref': titulo_ref,
                    'titulo_encontrado_belfar': titulo_real_encontrado_belfar,
                    'tem_diferenca': False,
                    'ignorada': True,
                    'faltante': False
                })
                continue

            tem_diferenca = False
            if normalizar_texto(conteudo_ref) != normalizar_texto(conteudo_belfar):
                tem_diferenca = True
                diferencas_conteudo.append({
                    'secao': secao, 
                    'conteudo_ref': conteudo_ref, 
                    'conteudo_belfar': conteudo_belfar,
                    'titulo_encontrado_ref': titulo_ref,
                    'titulo_encontrado_belfar': titulo_real_encontrado_belfar
                })
                similaridades_secoes.append(0)
            else:
                similaridades_secoes.append(100)

            secoes_analisadas.append({
                'secao': secao,
                'conteudo_ref': conteudo_ref,
                'conteudo_belfar': conteudo_belfar,
                'titulo_encontrado_ref': titulo_ref,
                'titulo_encontrado_belfar': titulo_real_encontrado_belfar,
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
        mapa_secoes = mapear_secoes(texto_proc_para_checar, secoes_todas)
        linhas_texto = texto_proc_para_checar.split('\n')

        for secao_nome in secoes_todas:
            if secao_nome.upper() in [s.upper() for s in secoes_ignorar]:
                continue
            encontrou, _, conteudo = obter_dados_secao(secao_nome, mapa_secoes, linhas_texto, tipo_bula)
            if encontrou and conteudo:
                # pulamos a primeira linha do bloco (que geralmente é título)
                linhas_conteudo = conteudo.split('\n')
                if len(linhas_conteudo) >= 1:
                    texto_filtrado_para_checar.append('\n'.join(linhas_conteudo))

        texto_final_para_checar = '\n'.join(texto_filtrado_para_checar)
        if not texto_final_para_checar:
            return []

        # SpellChecker (pt) — garantimos vocabulário de referência como autorizado
        spell = SpellChecker(language='pt')
        palavras_a_ignorar = {"alair", "belfar", "peticionamento", "urotrobel", "nebacetin", "nebacetin", "neomicina", "bacitracina"}
        # vocabulário de referência: formas originais e normalizadas
        vocab_referencia_raw = set(re.findall(r'\b[a-zA-ZÀ-ÖØ-öø-ÿ0-9\-]+\b', texto_referencia.lower()))
        vocab_referencia_norm = set(normalizar_texto(w) for w in vocab_referencia_raw)
        # carrega vocabulário extra no corretor para reduzir falsos positivos
        spell.word_frequency.load_words(vocab_referencia_raw.union(palavras_a_ignorar))

        # usa spaCy para coletar entidades e lexemas conhecidos
        entidades = set()
        if nlp:
            doc = nlp(texto_proc_para_checar)
            entidades = {ent.text.lower() for ent in doc.ents}

        # tokens a checar
        palavras = re.findall(r'\b[a-zA-ZÀ-ÖØ-öø-ÿ]+\b', texto_final_para_checar)
        palavras = [p for p in palavras if len(p) > 2]  # ignorar tokens curtos

        possiveis_erros = spell.unknown([p.lower() for p in palavras])

        # Filtra falsos positivos: se palavra está no vocab_referencia (raw ou normalized) ou é entidade, remove.
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
            # se spaCy diz que não é OOV (ou seja, é conhecido), então ignora
            if nlp:
                try:
                    lex = nlp.vocab[e_raw]
                    if not getattr(lex, "is_oov", True):
                        # palavra conhecida — ignora
                        continue
                except Exception:
                    pass
            # passa filtro: realmente parece desconhecida
            erros_filtrados.append(e_raw)

        # retorna uma lista curta ordenada e única
        erros_unicos = sorted(set(erros_filtrados))
        return erros_unicos[:40]

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

# ----------------- CONSTRUÇÃO DO HTML (LADO A LADO) -----------------
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

    # Não pulamos a exibição da Referência se a seção estiver faltando no Belfar.
    for diff in secoes_analisadas:
        secao_canonico = diff['secao']
        prefixo = prefixos_map.get(secao_canonico, "")

        # Título exibido
        if eh_referencia:
            titulo_display = f"{prefixo} {secao_canonico}".strip()
            html_final.append(f"<h3 style='font-size: 16px; font-weight: bold; color: #111;'>{titulo_display}</h3>")
        else:
            # usa título encontrado no Belfar quando disponível; senão usa canônico
            titulo_encontrado = diff.get('titulo_encontrado_belfar') or diff.get('titulo_encontrado_ref') or secao_canonico
            if prefixo and not titulo_encontrado.strip().startswith(prefixo):
                titulo_display = f"{prefixo} {titulo_encontrado}".strip()
            else:
                titulo_display = titulo_encontrado
            html_final.append(f"<h3 style='font-size: 16px; font-weight: bold; color: #111;'>{titulo_display}</h3>")

        # Conteúdo
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
                    # mesmo faltando no Belfar, exibimos o conteúdo da Referência se houver
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
st.caption("Sistema de Auditoria de Bulas v21.2 | Correção de Vazamento de Seção e melhorias")
