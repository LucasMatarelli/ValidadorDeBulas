# -*- coding: utf-8 -*-
# Aplicativo Streamlit: Auditoria de Bulas (v21.7)
# Ajustes nesta versão:
# - NOVA FUNCIONALIDADE: Verificação automática se o arquivo enviado corresponde ao tipo selecionado (Paciente/Profissional).
# - Removido o "Resumo das Seções".
# - Restaurada a seção "🎨 Visualização Lado a Lado com Destaques".
# - Mantida a regra DIZERES LEGAIS até o fim; COMPOSIÇÃO somente seu conteúdo.
# - Layout de texto/fonte preservado (font-family: Georgia / serif).

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

# ----------------- UI / CSS -----------------
st.set_page_config(layout="wide", page_title="Auditoria de Bulas", page_icon="🔬")
GLOBAL_CSS = """
<style>
/* Esconder elementos Streamlit padrao */
[data-testid="stHeader"] { display: none !important; }
footer { display: none !important; }

/* Container visual global (tipografia igual ao visual anterior) */
.bula-box {
  height: 420px;
  overflow-y: auto;
  border: 1px solid #dcdcdc;
  border-radius: 6px;
  padding: 18px;
  background: #ffffff;
  font-family: "Georgia", "Times New Roman", serif;
  font-size: 14px;
  line-height: 1.6;
  color: #111;
}

/* Container para visualização completa (lado a lado) */
.bula-box-full {
  height: 700px;
  overflow-y: auto;
  border: 1px solid #dcdcdc;
  border-radius: 6px;
  padding: 20px;
  background: #ffffff;
  font-family: "Georgia", "Times New Roman", serif;
  font-size: 14px;
  line-height: 1.6;
  color: #111;
}

/* Titulos de seção */
.section-title {
  font-size: 15px;
  font-weight: 700;
  color: #222;
  margin: 8px 0 12px;
}

/* estilos de destaque */
mark.diff { background-color: #ffff99; padding:0 2px; }
mark.ort { background-color: #ffdfd9; padding:0 2px; }
mark.anvisa { background-color: #cce5ff; padding:0 2px; font-weight:500; }

.stExpander > div[role="button"] { font-weight: 700; color: #333; }

/* Boxes de referência / belfar */
.ref-title { color: #0b5686; font-weight:700; }
.bel-title { color: #0b8a3e; font-weight:700; }

.small-muted { color:#666; font-size:12px; }
.legend { font-size:13px; margin-bottom:8px; }
</style>
"""
st.markdown(GLOBAL_CSS, unsafe_allow_html=True)

# ----------------- MODELO NLP -----------------
@st.cache_resource
def carregar_modelo_spacy():
    try:
        return spacy.load("pt_core_news_lg")
    except OSError:
        st.warning("Aviso: modelo 'pt_core_news_lg' não encontrado. Algumas heurísticas de NER ficarão reduzidas.")
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
            pages = []
            with fitz.open(stream=arquivo.read(), filetype="pdf") as doc:
                for page in doc:
                    pages.append(page.get_text("text", sort=True))
            texto = "\n".join(pages)
        elif tipo_arquivo == 'docx':
            doc = docx.Document(arquivo)
            texto = "\n".join([p.text for p in doc.paragraphs])

        if texto:
            invis = ['\u00AD', '\u200B', '\u200C', '\u200D', '\uFEFF']
            for c in invis:
                texto = texto.replace(c, '')
            texto = texto.replace('\r\n', '\n').replace('\r', '\n')
            texto = texto.replace('\u00A0', ' ')
            texto = re.sub(r'(\w+)-\n(\w+)', r'\1\2', texto, flags=re.IGNORECASE)
            linhas = texto.split('\n')
            padrao_rodape = re.compile(r'bula (?:do|para o) paciente|página \d+\s*de\s*\d+', re.IGNORECASE)
            linhas = [l for l in linhas if not padrao_rodape.search(l.strip())]
            texto = "\n".join(linhas)
            texto = re.sub(r'\n{3,}', '\n\n', texto)
            texto = re.sub(r'[ \t]+', ' ', texto)
            texto = texto.strip()
        return texto, None
    except Exception as e:
        return "", f"Erro ao ler o arquivo {tipo_arquivo}: {e}"

def truncar_apos_anvisa(texto):
    if not isinstance(texto, str):
        return texto
    rx = r"(aprovad[ao]\s+pela\s+anvisa\s+em|data\s+de\s+aprovação\s+na\s+anvisa:)\s*([\d]{1,2}/[\d]{1,2}/[\d]{2,4})"
    m = re.search(rx, texto, re.IGNORECASE)
    if m:
        pos = texto.find('\n', m.end())
        return texto[:pos] if pos != -1 else texto
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
            "ADVERTÊNCIAS E PRECAUCAÇÕES", "INTERAÇÕES MEDICAMENTOSAS",
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
        "SUPERDOSE": "O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?",
        "CUIDADOS DE ARMAZENAMENTO DO MEDICAMENTO": "ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?"
    }

def obter_secoes_ignorar_comparacao():
    return ["APRESENTAÇÕES", "COMPOSIÇÃO", "DIZERES LEGAIS"]

def obter_secoes_ignorar_ortografia():
    return ["COMPOSIÇÃO", "DIZERES LEGAIS"]

# ----------------- NORMALIZAÇÃO -----------------
def normalizar_texto(texto):
    texto = '' if texto is None else texto
    texto = ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')
    texto = re.sub(r'[^\w\s]', '', texto)
    texto = ' '.join(texto.split())
    return texto.lower()

def normalizar_titulo_para_comparacao(texto):
    texto = '' if texto is None else texto
    t = normalizar_texto(texto)
    t = re.sub(r'^\s*(\d{1,2})\s*[\.\)\-]?\s*', '', t).strip()
    return t

def _create_anchor_id(secao_nome, prefix):
    norm = normalizar_texto(secao_nome)
    norm_safe = re.sub(r'[^a-z0-9\-]', '-', norm)
    return f"anchor-{prefix}-{norm_safe}"

# ----------------- DETECÇÃO E MAPEAMENTO -----------------
HeadingCandidate = namedtuple("HeadingCandidate", ["index", "raw", "norm", "numeric", "matched_canon", "score"])

def construir_heading_candidates(linhas, secoes_esperadas, aliases):
    titulos_possiveis = {}
    for s in secoes_esperadas:
        titulos_possiveis[s] = s
    for a, c in aliases.items():
        if c in secoes_esperadas:
            titulos_possiveis[a] = c
    titulos_norm = {k: normalizar_titulo_para_comparacao(k) for k in titulos_possiveis.keys()}
    candidates = []
    for i, linha in enumerate(linhas):
        raw = (linha or "").strip()
        if not raw:
            continue
        norm = normalizar_titulo_para_comparacao(raw)
        letters = re.findall(r'[A-Za-zÀ-ÖØ-öø-ÿ]', raw)
        is_upper = len(letters) and sum(1 for ch in letters if ch.isupper()) / len(letters) >= 0.6
        starts_with_cap = raw and (raw[0].isupper() or raw[0].isdigit())
        numeric = None
        mnum = re.match(r'^\s*(\d{1,2})\s*[\.\)\-]?\s*(.*)$', raw)
        if mnum:
            try:
                numeric = int(mnum.group(1))
            except Exception:
                numeric = None
        best_score = 0
        best_canon = None
        for titulo_possivel, titulo_canonico in titulos_possiveis.items():
            t_norm = titulos_norm.get(titulo_possivel, normalizar_titulo_para_comparacao(titulo_possivel))
            if not t_norm:
                continue
            score = fuzz.token_set_ratio(t_norm, norm)
            if t_norm in norm:
                score = max(score, 95)
            if score > best_score:
                best_score = score
                best_canon = titulo_canonico
        is_candidate = False
        if numeric is not None:
            is_candidate = True
        elif best_score >= 88:
            is_candidate = True
        elif is_upper and len(raw.split()) <= 10:
            is_candidate = True
        elif starts_with_cap and len(raw.split()) <= 6 and re.search(r'[A-ZÁÉÍÓÚÂÊÔÃÕÇ]', raw):
            is_candidate = True
        if is_candidate:
            candidates.append(HeadingCandidate(index=i, raw=raw, norm=norm, numeric=numeric, matched_canon=best_canon if best_score >= 80 else None, score=best_score))
    unique = {c.index: c for c in candidates}
    return sorted(unique.values(), key=lambda x: x.index)

def mapear_secoes_deterministico(texto_completo, secoes_esperadas):
    linhas = texto_completo.split('\n')
    aliases = obter_aliases_secao()
    candidates = construir_heading_candidates(linhas, secoes_esperadas, aliases)
    mapa = []
    last_idx = -1
    for sec_idx, sec in enumerate(secoes_esperadas):
        sec_norm = normalizar_titulo_para_comparacao(sec)
        found = None
        for c in candidates:
            if c.index <= last_idx:
                continue
            if c.matched_canon == sec:
                found = c
                break
        if not found:
            for c in candidates:
                if c.index <= last_idx:
                    continue
                if c.numeric == (sec_idx + 1):
                    found = c
                    break
        if not found:
            for c in candidates:
                if c.index <= last_idx:
                    continue
                if sec_norm and sec_norm in c.norm:
                    found = c
                    break
        if not found:
            for c in candidates:
                if c.index <= last_idx:
                    continue
                if fuzz.token_set_ratio(sec_norm, c.norm) >= 92:
                    found = c
                    break
        if not found:
            for i in range(last_idx + 1, len(linhas)):
                if sec_norm and sec_norm in normalizar_titulo_para_comparacao(linhas[i]):
                    found = HeadingCandidate(index=i, raw=linhas[i].strip(), norm=normalizar_titulo_para_comparacao(linhas[i]), numeric=None, matched_canon=sec, score=100)
                    break
        if found:
            mapa.append({'canonico': sec, 'titulo_encontrado': found.raw, 'linha_inicio': found.index, 'score': found.score})
            last_idx = found.index
    mapa = sorted(mapa, key=lambda x: x['linha_inicio'])
    return mapa, candidates, linhas

# ----------------- EXTRAÇÃO DO CONTEÚDO POR SEÇÃO -----------------
def obter_dados_secao_v2(secao_canonico, mapa_secoes, linhas_texto, tipo_bula):
    entrada = None
    for m in mapa_secoes:
        if m['canonico'] == secao_canonico:
            entrada = m
            break
    if not entrada:
        return False, None, ""

    linha_inicio = entrada['linha_inicio']

    # Regra especial: "DIZERES LEGAIS" pega até o fim do documento sempre
    if secao_canonico.strip().upper() == "DIZERES LEGAIS":
        linha_fim = len(linhas_texto)
    else:
        sorted_map = sorted(mapa_secoes, key=lambda x: x['linha_inicio'])
        prox_idx = None
        for m in sorted_map:
            if m['linha_inicio'] > linha_inicio:
                prox_idx = m['linha_inicio']
                break
        linha_fim = prox_idx if prox_idx is not None else len(linhas_texto)

    conteudo_lines = []
    for i in range(linha_inicio + 1, linha_fim):
        line_norm = normalizar_titulo_para_comparacao(linhas_texto[i])
        if line_norm in {normalizar_titulo_para_comparacao(s) for s in obter_secoes_por_tipo(tipo_bula)}:
            break
        conteudo_lines.append(linhas_texto[i])
    conteudo_final = "\n".join(conteudo_lines).strip()
    return True, entrada['titulo_encontrado'], conteudo_final

# ----------------- VERIFICAÇÃO DE SEÇÕES E CONTEÚDO -----------------
def verificar_secoes_e_conteudo(texto_ref, texto_belfar, tipo_bula):
    secoes_esperadas = obter_secoes_por_tipo(tipo_bula)
    ignore_comparison = [s.upper() for s in obter_secoes_ignorar_comparacao()]
    secoes_faltantes, diferencas_conteudo, similaridades_secoes, diferencas_titulos = [], [], [], []
    secoes_analisadas = []

    mapa_ref, _, linhas_ref = mapear_secoes_deterministico(texto_ref, secoes_esperadas)
    mapa_belfar, _, linhas_belfar = mapear_secoes_deterministico(texto_belfar, secoes_esperadas)

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

        if sec.upper() in ignore_comparison:
            secoes_analisadas.append({
                'secao': sec,
                'conteudo_ref': conteudo_ref or "",
                'conteudo_belfar': conteudo_belfar or "",
                'titulo_encontrado_ref': titulo_ref,
                'titulo_encontrado_belfar': titulo_belfar,
                'tem_diferenca': False,
                'ignorada': True,
                'faltante': False
            })
            continue

        tem_diferenca = False
        if normalizar_texto(conteudo_ref or "") != normalizar_texto(conteudo_belfar or ""):
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

# ----------------- ORTOGRAFIA -----------------
def checar_ortografia_inteligente(texto_para_checar, texto_referencia, tipo_bula):
    if not texto_para_checar:
        return []
    try:
        secoes_ignorar = [s.upper() for s in obter_secoes_ignorar_ortografia()]
        secoes_todas = obter_secoes_por_tipo(tipo_bula)
        texto_filtrado_para_checar = []

        mapa_secoes, _, linhas_texto = mapear_secoes_deterministico(texto_para_checar, secoes_todas)
        for sec in secoes_todas:
            if sec.upper() in secoes_ignorar:
                continue
            encontrou, _, conteudo = obter_dados_secao_v2(sec, mapa_secoes, linhas_texto, tipo_bula)
            if encontrou and conteudo:
                texto_filtrado_para_checar.append(conteudo)

        texto_final_para_checar = '\n'.join(texto_filtrado_para_checar)
        if not texto_final_para_checar:
            return []

        spell = SpellChecker(language='pt')
        palavras_a_ignorar = {"alair", "belfar", "peticionamento", "urotrobel", "nebacetin", "neomicina", "bacitracina"}
        vocab_referencia_raw = set(re.findall(r'\b[a-zA-ZÀ-ÖØ-öø-ÿ0-9\-]+\b', (texto_referencia or "").lower()))
        spell.word_frequency.load_words(vocab_referencia_raw.union(palavras_a_ignorar))

        entidades = set()
        if nlp:
            doc = nlp(texto_final_para_checar)
            entidades = {ent.text.lower() for ent in doc.ents}

        palavras = re.findall(r'\b[a-zA-ZÀ-ÖØ-öø-ÿ]+\b', texto_final_para_checar)
        palavras = [p for p in palavras if len(p) > 2]

        possiveis_erros = set(spell.unknown([p.lower() for p in palavras]))
        erros_filtrados = []
        vocab_norm = set(normalizar_texto(w) for w in vocab_referencia_raw)
        for e in possiveis_erros:
            e_raw = e.lower()
            e_norm = normalizar_texto(e_raw)
            if e_raw in vocab_referencia_raw or e_norm in vocab_norm:
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
        return sorted(set(erros_filtrados))[:60]
    except Exception:
        return []

# ----------------- DIFERENÇAS PALAVRA-A-PALAVRA -----------------
def marcar_diferencas_palavra_por_palavra(texto_ref, texto_belfar, eh_referencia):
    def tokenizar(txt):
        return re.findall(r'\n|[A-Za-zÀ-ÖØ-öø-ÿ0-9_•]+|[^\w\s]', txt or "", re.UNICODE)

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
            marcado.append(f"<mark class='diff'>{tok}</mark>")
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

# ----------------- CONSTRUÇÃO DO HTML POR SEÇÃO -----------------
def construir_html_secoes(secoes_analisadas, erros_ortograficos, tipo_bula, eh_referencia=False):
    html_map = {}
    prefixos_paciente = {
        "PARA QUE ESTE MEDICAMENTO É INDICADO": "1.", "COMO ESTE MEDICAMENTO FUNCIONA?": "2.",
        "QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?": "3.", "O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?": "4.",
        "ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?": "5.", "COMO DEVO USAR ESTE MEDICAMENTO?": "6.",
        "O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?": "7.", "QUAIS OS MALES QUE ESTE MEDICAMENTO PODE CAUSAR?": "8.",
        "O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?": "9."
    }
    prefixos_profissional = {
        "INDICAÇÕES": "1.", "RESULTADOS DE EFICÁCIA": "2.", "CARACTERÍSTICAS FARMACOLÓGICAS": "3.",
        "CONTRAINDICAÇÕES": "4.", "ADVERTÊNCIAS E PRECAUÇÕS": "5.", "INTERAÇÕES MEDICAMENTOSAS": "6.",
        "CUIDADOS DE ARMAZENAMENTO DO MEDICAMENTO": "7.", "POSOLOGIA E MODO DE USAR": "8.",
        "REAÇÕES ADVERSAS": "9.", "SUPERDOSE": "10."
    }
    prefixos_map = prefixos_paciente if tipo_bula == "Paciente" else prefixos_profissional

    mapa_erros = {}
    if erros_ortograficos and not eh_referencia:
        for erro in erros_ortograficos:
            pattern = r'(?<![<>a-zA-Z])(?<!mark>)(?<!;>)\b(' + re.escape(erro) + r')\b(?![<>])'
            mapa_erros[pattern] = r"<mark class='ort'>\1</mark>"

    regex_anvisa = r"((?:aprovad[ao]\s+pela\s+anvisa\s+em|data\s+de\s+aprovação\s+na\s+anvisa:)\s*[\d]{1,2}/[\d]{1,2}/[\d]{2,4})"
    anvisa_pattern = re.compile(regex_anvisa, re.IGNORECASE)

    for diff in secoes_analisadas:
        secao_canonico = diff['secao']
        prefixo = prefixos_map.get(secao_canonico, "")
        if eh_referencia:
            titulo_display = f"{prefixo} {secao_canonico}".strip()
            title_html = f"<div class='section-title ref-title'>{titulo_display}</div>"
            conteudo = diff['conteudo_ref'] or ""
        else:
            titulo_encontrado = diff.get('titulo_encontrado_belfar') or diff.get('titulo_encontrado_ref') or secao_canonico
            titulo_display = f"{prefixo} {titulo_encontrado}".strip() if prefixo and not titulo_encontrado.strip().startswith(prefixo) else titulo_encontrado
            title_html = f"<div class='section-title bel-title'>{titulo_display}</div>"
            conteudo = diff['conteudo_belfar'] or ""

        if diff.get('ignorada', False):
            conteudo_html = (conteudo or "").replace('\n', '<br>')
        else:
            if eh_referencia:
                conteudo_html = marcar_diferencas_palavra_por_palavra(diff.get('conteudo_ref') or "", diff.get('conteudo_belfar') or "", eh_referencia=True)
            else:
                conteudo_html = marcar_diferencas_palavra_por_palavra(diff.get('conteudo_ref') or "", diff.get('conteudo_belfar') or "", eh_referencia=False)

        if not eh_referencia and not diff.get('ignorada', False):
            for pattern, replacement in mapa_erros.items():
                try:
                    conteudo_html = re.sub(pattern, replacement, conteudo_html, flags=re.IGNORECASE)
                except Exception:
                    pass

        conteudo_html = anvisa_pattern.sub(r"<mark class='anvisa'>\1</mark>", conteudo_html)
        anchor_id = _create_anchor_id(secao_canonico, "ref" if eh_referencia else "bel")
        snippet = f"<div id='{anchor_id}' style='scroll-margin-top: 20px;'>{title_html}<div style='margin-top:6px;'>{conteudo_html}</div></div>"
        html_map[secao_canonico] = snippet
    return html_map

# ----------------- RELATÓRIO (EXPANDERS POR SEÇÃO + VISUALIZAÇÃO COMPLETA) -----------------
def gerar_relatorio_final(texto_ref, texto_belfar, nome_ref, nome_belfar, tipo_bula):
    st.header("Relatório de Auditoria Inteligente")
    rx_anvisa = r"(aprovad[ao]\s+pela\s+anvisa\s+em|data\s+de\s+aprovação\s+na\s+anvisa:)\s*([\d]{1,2}/[\d]{1,2}/[\d]{2,4})"
    match_ref = re.search(rx_anvisa, texto_ref or "", re.IGNORECASE)
    match_bel = re.search(rx_anvisa, texto_belfar or "", re.IGNORECASE)
    data_ref = match_ref.group(2).strip() if match_ref else "Não encontrada"
    data_bel = match_bel.group(2).strip() if match_bel else "Não encontrada"

    secoes_faltantes, diferencas_conteudo, similaridades, diferencas_titulos, secoes_analisadas = verificar_secoes_e_conteudo(texto_ref, texto_belfar, tipo_bula)
    erros_ortograficos = checar_ortografia_inteligente(texto_belfar, texto_ref, tipo_bula)
    score_sim = sum(similaridades) / len(similaridades) if similaridades else 100.0

    st.subheader("Dashboard de Veredito")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Conformidade de Conteúdo", f"{score_sim:.0f}%")
    c2.metric("Erros Ortográficos", len(erros_ortograficos))
    c3.metric("Data ANVISA (Referência)", data_ref)
    c4.metric("Data ANVISA (BELFAR)", data_bel)

    st.divider()
    st.subheader("Seções (clique para expandir e ver conteúdo lado a lado)")

    # Mapa de prefixos para numeração
    prefixos_paciente = {
        "PARA QUE ESTE MEDICAMENTO É INDICADO": "1.",
        "COMO ESTE MEDICAMENTO FUNCIONA?": "2.",
        "QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?": "3.",
        "O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?": "4.",
        "ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?": "5.",
        "COMO DEVO USAR ESTE MEDICAMENTO?": "6.",
        "O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?": "7.",
        "QUAIS OS MALES QUE ESTE MEDICAMENTO PODE CAUSAR?": "8.",
        "O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?": "9."
    }
    prefixos_profissional = {
        "INDICAÇÕES": "1.",
        "RESULTADOS DE EFICÁCIA": "2.",
        "CARACTERÍSTICAS FARMACOLÓGICAS": "3.",
        "CONTRAINDICAÇÕES": "4.",
        "ADVERTÊNCIAS E PRECAUÇÕES": "5.",
        "INTERAÇÕES MEDICAMENTOSAS": "6.",
        "CUIDADOS DE ARMAZENAMENTO DO MEDICAMENTO": "7.",
        "POSOLOGIA E MODO DE USAR": "8.",
        "REAÇÕES ADVERSAS": "9.",
        "SUPERDOSE": "10."
    }
    prefixos_map = prefixos_paciente if tipo_bula == "Paciente" else prefixos_profissional

    # construir snippets por seção
    html_ref_map = construir_html_secoes(secoes_analisadas, [], tipo_bula, eh_referencia=True)
    html_bel_map = construir_html_secoes(secoes_analisadas, erros_ortograficos, tipo_bula, eh_referencia=False)

    # Expander por seção com caixas lado a lado
    for diff in secoes_analisadas:
        sec = diff['secao']
        prefixo = prefixos_map.get(sec, "")
        
        # Monta o título do expander com numeração
        if prefixo:
            titulo_expander = f"{prefixo} {sec}"
        else:
            titulo_expander = sec
        
        status = "✅ Conteúdo Idêntico"
        if diff.get('faltante', False):
            status = "🚨 SEÇÃO FALTANTE"
        elif diff.get('ignorada', False):
            status = "⚠️ Comparação Ignorada"
        elif diff.get('tem_diferenca', False):
            status = "❌ Conteúdo Divergente"

        exp_label = f"{titulo_expander} — {status}"
        
        with st.expander(exp_label, expanded=(diff.get('tem_diferenca', False) or diff.get('faltante', False))):
            col1, col2 = st.columns([1,1], gap="large")
            with col1:
                st.markdown(f"**Referência: {nome_ref}**", unsafe_allow_html=True)
                snippet_ref = html_ref_map.get(sec, "<i>Conteúdo não encontrado</i>")
                st.markdown(f"<div class='bula-box'>{snippet_ref}</div>", unsafe_allow_html=True)
            with col2:
                st.markdown(f"**BELFAR: {nome_belfar}**", unsafe_allow_html=True)
                snippet_bel = html_bel_map.get(sec, "<i>Conteúdo não encontrado</i>")
                st.markdown(f"<div class='bula-box'>{snippet_bel}</div>", unsafe_allow_html=True)

            st.markdown("<div class='small-muted'>Clique no título da seção para abrir/fechar. As caixas exibem somente o conteúdo daquela seção.</div>", unsafe_allow_html=True)

    # --- Visualização completa lado a lado ---
    st.divider()
    st.subheader("🎨 Visualização Lado a Lado com Destaques")
    st.markdown("<div class='legend'><strong>Legenda:</strong> <mark class='diff'>Amarelo</mark> = Divergências | <mark class='ort'>Rosa</mark> = Erros ortográficos | <mark class='anvisa'>Azul</mark> = Data ANVISA</div>", unsafe_allow_html=True)

    # Monta o HTML completo concatenando as seções na ordem original detectada
    full_order = [s['secao'] for s in secoes_analisadas]
    html_ref_full = "".join([html_ref_map.get(sec, "") for sec in full_order])
    html_bel_full = "".join([html_bel_map.get(sec, "") for sec in full_order])

    col_ref, col_bel = st.columns(2, gap="large")
    with col_ref:
        st.markdown(f"**📄 {nome_ref}**")
        st.markdown(f"<div id='container-ref-full' class='bula-box-full'>{html_ref_full}</div>", unsafe_allow_html=True)
    with col_bel:
        st.markdown(f"**📄 {nome_belfar}**")
        st.markdown(f"<div id='container-bel-full' class='bula-box-full'>{html_bel_full}</div>", unsafe_allow_html=True)

    if erros_ortograficos:
        st.info(f"📝 Erros ortográficos (sugeridos): {', '.join(erros_ortograficos)}")

# ----------------- CHECKER DE TIPO DE BULA (NOVO) -----------------
def checar_tipo_arquivo(texto, tipo_esperado):
    """Verifica se o texto contém cabeçalhos exclusivos do tipo OPOSTO ao selecionado."""
    if not texto: return False
    t_norm = normalizar_texto(texto)

    # Se o usuário escolheu Paciente, não deve haver termos exclusivos de Profissional
    termos_profissional = [
        "caracteristicas farmacologicas",
        "resultados de eficacia",
        "propriedades farmacocinetica"
    ]
    # Se o usuário escolheu Profissional, não deve haver termos exclusivos de Paciente
    termos_paciente = [
        "como este medicamento funciona",
        "o que devo saber antes de usar",
        "quais os males que este medicamento pode causar"
    ]

    if tipo_esperado == "Paciente":
        # Se escolheu Paciente, mas tem termos de Profissional
        contagem = sum(1 for term in termos_profissional if term in t_norm)
        return contagem >= 2
    elif tipo_esperado == "Profissional":
        # Se escolheu Profissional, mas tem termos de Paciente
        contagem = sum(1 for term in termos_paciente if term in t_norm)
        return contagem >= 2
    return False

# ----------------- INTERFACE PRINCIPAL -----------------
st.title("🔬 Inteligência Artificial para Auditoria de Bulas (v21.7)")
st.markdown("Layout restaurado: expanders por seção + visualização completa lado a lado. Regras: DIZERES LEGAIS até o fim; não comparar APRESENTAÇÕES/COMPOSIÇÃO/DIZERES LEGAIS; COMPOSIÇÃO extrai somente sua seção.")

st.divider()
tipo_bula_selecionado = st.radio("Tipo de Bula:", ("Paciente", "Profissional"), horizontal=True)
col1, col2 = st.columns(2)
with col1:
    st.subheader("📄 Documento de Referência")
    pdf_ref = st.file_uploader("Envie o PDF ou DOCX de referência", type=["pdf", "docx"], key="ref")
with col2:
    st.subheader("📄 Documento BELFAR")
    pdf_belfar = st.file_uploader("Envie o PDF ou DOCX Belfar", type=["pdf", "docx"], key="belfar")

if st.button("🔍 Iniciar Auditoria Completa", use_container_width=True, type="primary"):
    if not (pdf_ref and pdf_belfar):
        st.warning("⚠️ Envie ambos os arquivos para prosseguir.")
    else:
        with st.spinner("Processando..."):
            tipo_ref = 'docx' if pdf_ref.name.lower().endswith('.docx') else 'pdf'
            tipo_bel = 'docx' if pdf_belfar.name.lower().endswith('.docx') else 'pdf'
            texto_ref, erro_ref = extrair_texto(pdf_ref, tipo_ref)
            texto_belfar, erro_belfar = extrair_texto(pdf_belfar, tipo_bel)
            
            # --- NOVA VERIFICAÇÃO DE TIPO DE ARQUIVO ---
            suspeita_ref = checar_tipo_arquivo(texto_ref, tipo_bula_selecionado)
            suspeita_bel = checar_tipo_arquivo(texto_belfar, tipo_bula_selecionado)
            
            if suspeita_ref:
                st.warning(f"⚠️ Atenção: O arquivo de REFERÊNCIA ({pdf_ref.name}) parece ser do tipo oposto ao selecionado ({tipo_bula_selecionado}). Verifique se enviou a bula correta.")
            if suspeita_bel:
                st.warning(f"⚠️ Atenção: O arquivo BELFAR ({pdf_belfar.name}) parece ser do tipo oposto ao selecionado ({tipo_bula_selecionado}). Verifique se enviou a bula correta.")
            # --------------------------------------------

            if not erro_ref:
                texto_ref = truncar_apos_anvisa(texto_ref)
            if not erro_belfar:
                texto_belfar = truncar_apos_anvisa(texto_belfar)
            if erro_ref or erro_belfar:
                st.error(f"Erro de leitura: {erro_ref or erro_belfar}")
            else:
                gerar_relatorio_final(texto_ref, texto_belfar, pdf_ref.name, pdf_belfar.name, tipo_bula_selecionado)

st.divider()
st.caption("Sistema de Auditoria de Bulas v21.7 | Expander por seção + Visualização completa lado a lado. Resposta: Resumo das Seções removido; visual completo restaurado; checagem de tipo incluída.")
