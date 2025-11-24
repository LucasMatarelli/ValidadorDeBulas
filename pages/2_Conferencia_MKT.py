# pages/2_Conferencia_MKT.py
#
# Versão v59 - Filtro "Nuclear" de Lixo Gráfico
# - NOVO: Função `filtrar_linhas_tecnicas` que deleta a linha INTEIRA se encontrar lixo.
# - ALVO: Remove especificamente "Times New Roman", "Black", "AZOLINA: Tim", códigos "1042400 - 12/23".
# - UI: Layout original mantido.

import re
import difflib
import unicodedata
import io
import streamlit as st
import fitz  # PyMuPDF
import docx
import spacy
from thefuzz import fuzz
from spellchecker import SpellChecker
from collections import namedtuple

# ----------------- UI / CSS (LAYOUT MANTIDO) -----------------
st.set_page_config(layout="wide", page_title="Auditoria de Bulas", page_icon="🔬")

GLOBAL_CSS = """
<style>
/* Ajuste do Container Principal */
.main .block-container {
    padding-top: 2rem !important;
    padding-bottom: 2rem !important;
    max-width: 95% !important;
}

[data-testid="stHeader"] { display: none !important; }
footer { display: none !important; }

.bula-box {
  height: 350px;
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

.section-title {
  font-size: 15px;
  font-weight: 700;
  color: #222;
  margin: 12px 0 8px;
  padding-top: 8px;
  border-top: 1px solid #eee;
}

.ref-title { color: #0b5686; }
.bel-title { color: #0b8a3e; }

mark.diff { background-color: #ffff99; padding: 0 2px; color: black; }
mark.ort { background-color: #ffdfd9; padding: 0 2px; color: black; border-bottom: 1px dashed red; }
mark.anvisa { background-color: #DDEEFF; padding: 0 2px; color: black; border: 1px solid #0000FF; }

.stExpander > div[role="button"] { font-weight: 700; color: #333; }
</style>
"""
st.markdown(GLOBAL_CSS, unsafe_allow_html=True)

# ----------------- MODELO NLP -----------------
@st.cache_resource
def carregar_modelo_spacy():
    try:
        return spacy.load("pt_core_news_lg")
    except OSError:
        return None

nlp = carregar_modelo_spacy()

# ----------------- UTILITÁRIOS -----------------
def normalizar_texto(texto):
    if not isinstance(texto, str): return ""
    texto = texto.replace('\n', ' ')
    texto = ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')
    texto = re.sub(r'[^\w\s]', '', texto)
    texto = ' '.join(texto.split())
    return texto.lower()

def normalizar_titulo_para_comparacao(texto):
    texto_norm = normalizar_texto(texto or "")
    texto_norm = re.sub(r'^\d+\s*[\.\-)]*\s*', '', texto_norm).strip()
    return texto_norm

def truncar_apos_anvisa(texto):
    if not isinstance(texto, str): return texto
    regex_anvisa = r"((?:aprovad[ao][\s\n]+pela[\s\n]+anvisa[\s\n]+em|data[\s\n]+de[\s\n]+aprova\w+[\s\n]+na[\s\n]+anvisa:)[\s\n]*([\d]{1,2}\s*/\s*[\d]{1,2}\s*/\s*[\d]{2,4}))"
    match = re.search(regex_anvisa, texto, re.IGNORECASE | re.DOTALL)
    if not match: return texto
    cut_off_position = match.end(1)
    pos_match = re.search(r'^\s*\.', texto[cut_off_position:], re.IGNORECASE)
    if pos_match: cut_off_position += pos_match.end()
    return texto[:cut_off_position]

def _create_anchor_id(secao_nome, prefix):
    norm = normalizar_texto(secao_nome)
    norm_safe = re.sub(r'[^a-z0-9\-]', '-', norm)
    return f"anchor-{prefix}-{norm_safe}"

# ----------------- FILTRAGEM AVANÇADA (ANTI-LIXO) -----------------
def filtrar_linhas_tecnicas(texto):
    """
    Remove linhas inteiras que contenham termos técnicos de impressão/gráfica.
    Isso é mais agressivo e seguro que substituir palavras.
    """
    linhas = texto.split('\n')
    linhas_limpas = []
    
    # Termos que, se encontrados, condenam a linha inteira à morte
    termos_proibidos = [
        # Fontes e Estilos
        r'Times New Roman', r'Myriad Pro', r'Arial', r'Helvética', r'Futura',
        r'Regular', r'Bold', r'Italic', r'Condensed',
        
        # Cores (Inglês e PT)
        r'\bBlack\b', r'\bCyan\b', r'\bMagenta\b', r'\bYellow\b', r'\bPantone\b',
        r'Cores?:', r'Preto', r'Color', r'Colors',
        
        # Termos das suas fotos
        r'AZOLINA:\s*Tim',  # O fragmento específico
        r'NAFAZOLINA:\s*Times',
        r'\d{6,}\s*-\s*\d{2}/\d{2}', # Padrão 1042400 - 12/23
        
        # Cabeçalhos técnicos
        r'Tipologia', r'Dimensão', r'Dimensões', r'Formato', 
        r'bula do paciente', r'página \d+', 
        r'FRENTE', r'VERSO', r'BELFAR', r'PHARMA',
        r'Cód\.?:', r'Ref\.?:', r'Laetus', r'Pharmacode', 
        r'Cód\. de barras', r'Farm\. Resp',
        
        # Medidas
        r'\d+\s*mm\b', r'\d+\s*x\s*\d+\s*mm'
    ]
    
    # Compila para ficar rápido
    regex_proibidos = [re.compile(p, re.IGNORECASE) for p in termos_proibidos]
    
    for linha in linhas:
        linha_strip = linha.strip()
        deletar = False
        
        # 1. Checa se tem termo proibido
        for pattern in regex_proibidos:
            if pattern.search(linha_strip):
                deletar = True
                break
        
        # 2. Checa se é linha de medida isolada (ex: "200 x 150")
        if re.match(r'^\s*\d{2,4}\s*[xX]\s*\d{2,4}\s*$', linha_strip):
            deletar = True
            
        # 3. Checa se é apenas um número de controle longo isolado
        if re.match(r'^\s*\d{6,}\s*$', linha_strip):
            deletar = True

        if not deletar:
            linhas_limpas.append(linha)
            
    return "\n".join(linhas_limpas)

# ----------------- EXTRAÇÃO -----------------
def extrair_texto(arquivo, tipo_arquivo, is_marketing_pdf=False):
    if arquivo is None: return "", f"Arquivo {tipo_arquivo} não enviado."
    try:
        arquivo.seek(0)
        texto_completo = ""

        if tipo_arquivo == 'pdf':
            with fitz.open(stream=arquivo.read(), filetype="pdf") as doc:
                for page in doc:
                    rect = page.rect
                    # Margem aumentada para 12% (cabeçalho/rodapé)
                    margem_y = rect.height * 0.12 
                    
                    if is_marketing_pdf:
                        # Split Column: Lê Esquerda -> Lê Direita
                        meio_x = rect.width / 2
                        
                        clip_esq = fitz.Rect(0, margem_y, meio_x, rect.height - margem_y)
                        texto_esq = page.get_textpage(clip=clip_esq).extractText()
                        
                        clip_dir = fitz.Rect(meio_x, margem_y, rect.width, rect.height - margem_y)
                        texto_dir = page.get_textpage(clip=clip_dir).extractText()
                        
                        texto_completo += texto_esq + "\n" + texto_dir + "\n"
                    else:
                        # Anvisa: Usa blocks
                        blocks = page.get_text("blocks", sort=True)
                        for b in blocks:
                            if b[6] == 0:
                                if b[1] >= margem_y and b[3] <= (rect.height - margem_y):
                                    texto_completo += b[4] + "\n"

        elif tipo_arquivo == 'docx':
            doc = docx.Document(arquivo)
            texto_completo = "\n".join([p.text for p in doc.paragraphs])

        if texto_completo:
            # Limpezas básicas
            invis = ['\u00AD', '\u200B', '\u200C', '\u200D', '\uFEFF']
            for c in invis: texto_completo = texto_completo.replace(c, '')
            texto_completo = texto_completo.replace('\r\n', '\n').replace('\r', '\n').replace('\u00A0', ' ')

            # 1. Aplica o filtro "NUCLEAR" de linhas técnicas
            texto_completo = filtrar_linhas_tecnicas(texto_completo)
            
            # 2. Limpezas residuais
            if is_marketing_pdf:
                # Remove paginação solta "1 de 2" ou "1."
                texto_completo = re.sub(r'(?m)^\s*\d{1,2}\.\s*$', '', texto_completo)

            texto_completo = re.sub(r'\n{3,}', '\n\n', texto_completo)
            return texto_completo.strip(), None

    except Exception as e:
        return "", f"Erro: {e}"

# ----------------- REPARAÇÃO E RECONSTRUÇÃO -----------------
def is_titulo_secao(linha):
    ln = linha.strip()
    if len(ln) < 4 or len(ln.split('\n')) > 2 or len(ln.split()) > 20: return False
    first = ln.split('\n')[0]
    if re.match(r'^\d+\s*[\.\-)]*\s+[A-ZÁÉÍÓÚÂÊÔÃÕÇ]', first): return True
    if first.isupper() and not first.endswith('.'): return True
    return False

def reparar_titulos_quebrados(linhas):
    secoes_conhecidas_norm = [normalizar_titulo_para_comparacao(s) for s in obter_secoes_por_tipo()]
    linhas_corrigidas = []
    i = 0
    while i < len(linhas):
        atual = linhas[i].strip()
        if i == len(linhas) - 1:
            linhas_corrigidas.append(linhas[i])
            break
        proxima = linhas[i+1].strip()
        juntas = atual + " " + proxima
        juntas_norm = normalizar_titulo_para_comparacao(juntas)
        eh_titulo = False
        for s_norm in secoes_conhecidas_norm:
            if fuzz.ratio(juntas_norm, s_norm) > 90:
                eh_titulo = True; break
        if eh_titulo:
            linhas_corrigidas.append(juntas); i += 2
        else:
            linhas_corrigidas.append(linhas[i]); i += 1
    return linhas_corrigidas

def reconstruir_paragrafos(texto):
    if not texto: return ""
    linhas = texto.split('\n')
    
    # Repara títulos
    linhas = reparar_titulos_quebrados(linhas)
    
    linhas_out = []
    buffer = ""
    padrao_tabela = re.compile(r'\.{3,}|_{3,}|q\.s\.p|^\s*[-•]\s+')

    for linha in linhas:
        l_strip = linha.strip()
        
        # Filtro Extra: Se a linha ficou vazia ou muito curta e sem sentido após limpeza
        if not l_strip or (len(l_strip) < 3 and not re.match(r'^\d+\.?$', l_strip)):
            if buffer: linhas_out.append(buffer); buffer = ""
            linhas_out.append("")
            continue
            
        if is_titulo_secao(l_strip):
            if buffer: linhas_out.append(buffer); buffer = ""
            linhas_out.append(l_strip)
            continue
            
        if padrao_tabela.search(l_strip):
            if buffer: linhas_out.append(buffer); buffer = ""
            linhas_out.append(l_strip)
            continue

        if buffer:
            if buffer.endswith('-'):
                buffer = buffer[:-1] + l_strip
            elif not buffer.endswith(('.', ':', '!', '?')):
                buffer += " " + l_strip
            else:
                linhas_out.append(buffer)
                buffer = l_strip
        else:
            buffer = l_strip
            
    if buffer: linhas_out.append(buffer)
    return "\n".join(linhas_out)

# ----------------- CONFIGURAÇÃO DE SEÇÕES -----------------
def obter_secoes_por_tipo():
    return [
        "APRESENTAÇÕES", "COMPOSIÇÃO",
        "1.PARA QUE ESTE MEDICAMENTO É INDICADO?", "2.COMO ESTE MEDICAMENTO FUNCIONA?",
        "3.QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?", "4.O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?",
        "5.ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?", "6.COMO DEVO USAR ESTE MEDICAMENTO?",
        "7.O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?",
        "8.QUAIS OS MALES QUE ESTE MEDICAMENTO PODE CAUSAR?",
        "9.O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?",
        "DIZERES LEGAIS"
    ]

def obter_aliases_secao():
    return {
        "PARA QUE ESTE MEDICAMENTO É INDICADO?": "1.PARA QUE ESTE MEDICAMENTO É INDICADO?",
        "COMO ESTE MEDICAMENTO FUNCIONA?": "2.COMO ESTE MEDICAMENTO FUNCIONA?",
        "QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?": "3.QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?",
        "O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?": "4.O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?",
        "ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICamento?": "5.ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?",
        "COMO DEVO USAR ESTE MEDICAMENTO?": "6.COMO DEVO USAR ESTE MEDICAMENTO?",
        "O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?": "7.O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?",
        "QUAIS OS MALES QUE ESTE MEDICAMENTO PODE ME CAUSAR?": "8.QUAIS OS MALES QUE ESTE MEDICAMENTO PODE CAUSAR?",
        "O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?": "9.O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?",
    }

def obter_secoes_ignorar_comparacao(): return ["APRESENTAÇÕES", "COMPOSIÇÃO", "DIZERES LEGAIS"]
def obter_secoes_ignorar_ortografia(): return ["COMPOSIÇÃO", "DIZERES LEGAIS"]

# ----------------- MAPEAMENTO -----------------
HeadingCandidate = namedtuple("HeadingCandidate", ["index", "raw", "norm", "numeric", "matched_canon", "score"])

def construir_heading_candidates(linhas, secoes_esperadas, aliases):
    titulos_possiveis = {s: s for s in secoes_esperadas}
    for a, c in aliases.items():
        if c in secoes_esperadas: titulos_possiveis[a] = c
    titulos_norm = {k: normalizar_titulo_para_comparacao(k) for k in titulos_possiveis.keys()}
    candidates = []
    for i, linha in enumerate(linhas):
        raw = (linha or "").strip()
        if not raw: continue
        norm = normalizar_titulo_para_comparacao(raw)
        best_score = 0; best_canon = None
        mnum = re.match(r'^\s*(\d{1,2})\s*[\.\)\-]?\s*(.*)$', raw)
        numeric = int(mnum.group(1)) if mnum else None
        letters = re.findall(r'[A-Za-zÀ-ÖØ-öø-ÿ]', raw)
        is_upper = len(letters) and sum(1 for ch in letters if ch.isupper()) / len(letters) >= 0.6
        starts_with_cap = raw and (raw[0].isupper() or raw[0].isdigit())

        for t_possivel, t_canon in titulos_possiveis.items():
            t_norm = titulos_norm.get(t_possivel, "")
            if not t_norm: continue
            score = fuzz.token_set_ratio(t_norm, norm)
            if t_norm in norm: score = max(score, 95)
            if score > best_score: best_score = score; best_canon = t_canon
        
        is_candidate = False
        if numeric is not None: is_candidate = True
        elif best_score >= 88: is_candidate = True
        elif is_upper and len(raw.split()) <= 10: is_candidate = True
        elif starts_with_cap and len(raw.split()) <= 6 and re.search(r'[A-ZÁÉÍÓÚÂÊÔÃÕÇ]', raw): is_candidate = True
        
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
            if c.index <= last_idx: continue
            if c.matched_canon == sec: found = c; break
        if not found:
            for c in candidates:
                if c.index <= last_idx: continue
                if c.numeric == (sec_idx + 1): found = c; break
        if not found:
            for c in candidates:
                if c.index <= last_idx: continue
                if sec_norm and sec_norm in c.norm: found = c; break
        if not found:
            for c in candidates:
                if c.index <= last_idx: continue
                if fuzz.token_set_ratio(sec_norm, c.norm) >= 92: found = c; break
        if found:
            mapa.append({'canonico': sec, 'titulo_encontrado': found.raw, 'linha_inicio': found.index, 'score': found.score})
            last_idx = found.index
    mapa = sorted(mapa, key=lambda x: x['linha_inicio'])
    return mapa, candidates, linhas

def obter_dados_secao_v2(secao_canonico, mapa_secoes, linhas_texto):
    entrada = None
    for m in mapa_secoes:
        if m['canonico'] == secao_canonico: entrada = m; break
    if not entrada: return False, None, ""
    linha_inicio = entrada['linha_inicio']
    if secao_canonico.strip().upper() == "DIZERES LEGAIS": linha_fim = len(linhas_texto)
    else:
        sorted_map = sorted(mapa_secoes, key=lambda x: x['linha_inicio'])
        prox_idx = None
        for m in sorted_map:
            if m['linha_inicio'] > linha_inicio: prox_idx = m['linha_inicio']; break
        linha_fim = prox_idx if prox_idx is not None else len(linhas_texto)
    conteudo_lines = []
    for i in range(linha_inicio + 1, linha_fim):
        line_norm = normalizar_titulo_para_comparacao(linhas_texto[i])
        if line_norm in {normalizar_titulo_para_comparacao(s) for s in obter_secoes_por_tipo()}: break
        conteudo_lines.append(linhas_texto[i])
    conteudo_final = "\n".join(conteudo_lines).strip()
    return True, entrada['titulo_encontrado'], conteudo_final

# ----------------- VERIFICAÇÃO -----------------
def verificar_secoes_e_conteudo(texto_ref, texto_belfar):
    secoes_esperadas = obter_secoes_por_tipo()
    ignore_comparison = [s.upper() for s in obter_secoes_ignorar_comparacao()]
    secoes_faltantes, diferencas_conteudo, similaridades_secoes, diferencas_titulos = [], [], [], []
    secoes_analisadas = []

    mapa_ref, _, linhas_ref = mapear_secoes_deterministico(texto_ref, secoes_esperadas)
    mapa_belfar, _, linhas_belfar = mapear_secoes_deterministico(texto_belfar, secoes_esperadas)

    for sec in secoes_esperadas:
        encontrou_ref, titulo_ref, conteudo_ref = obter_dados_secao_v2(sec, mapa_ref, linhas_ref)
        encontrou_belfar, titulo_belfar, conteudo_belfar = obter_dados_secao_v2(sec, mapa_belfar, linhas_belfar)

        if not encontrou_ref and not encontrou_belfar:
            secoes_faltantes.append(sec)
            secoes_analisadas.append({
                'secao': sec, 'conteudo_ref': "Seção não encontrada", 'conteudo_belfar': "Seção não encontrada",
                'titulo_encontrado_ref': None, 'titulo_encontrado_belfar': None,
                'tem_diferenca': True, 'ignorada': False, 'faltante': True
            })
            continue

        if not encontrou_belfar:
            secoes_faltantes.append(sec)
            secoes_analisadas.append({
                'secao': sec, 'conteudo_ref': conteudo_ref if encontrou_ref else "Seção não encontrada",
                'conteudo_belfar': "Seção não encontrada", 'titulo_encontrado_ref': titulo_ref, 'titulo_encontrado_belfar': None,
                'tem_diferenca': True, 'ignorada': False, 'faltante': True
            })
            continue

        if sec.upper() in ignore_comparison:
            secoes_analisadas.append({
                'secao': sec, 'conteudo_ref': conteudo_ref or "", 'conteudo_belfar': conteudo_belfar or "",
                'titulo_encontrado_ref': titulo_ref, 'titulo_encontrado_belfar': titulo_belfar,
                'tem_diferenca': False, 'ignorada': True, 'faltante': False
            })
            continue

        tem_diferenca = False
        if normalizar_texto(conteudo_ref or "") != normalizar_texto(conteudo_belfar or ""):
            tem_diferenca = True
            diferencas_conteudo.append({'secao': sec, 'conteudo_ref': conteudo_ref, 'conteudo_belfar': conteudo_belfar})
            similaridades_secoes.append(0)
        else:
            similaridades_secoes.append(100)

        secoes_analisadas.append({
            'secao': sec, 'conteudo_ref': conteudo_ref, 'conteudo_belfar': conteudo_belfar,
            'titulo_encontrado_ref': titulo_ref, 'titulo_encontrado_belfar': titulo_belfar,
            'tem_diferenca': tem_diferenca, 'ignorada': False, 'faltante': False
        })
    return secoes_faltantes, diferencas_conteudo, similaridades_secoes, diferencas_titulos, secoes_analisadas

# ----------------- ORTOGRAFIA & DIFF -----------------
def checar_ortografia_inteligente(texto_para_checar, texto_referencia):
    if not texto_para_checar: return []
    try:
        secoes_ignorar = [s.upper() for s in obter_secoes_ignorar_ortografia()]
        secoes_todas = obter_secoes_por_tipo()
        texto_filtrado = []
        mapa, _, linhas = mapear_secoes_deterministico(texto_para_checar, secoes_todas)
        for sec in secoes_todas:
            if sec.upper() in secoes_ignorar: continue
            enc, _, cont = obter_dados_secao_v2(sec, mapa, linhas)
            if enc and cont: texto_filtrado.append(cont)
        texto_final = '\n'.join(texto_filtrado)
        if not texto_final: return []
        spell = SpellChecker(language='pt')
        palavras_ignorar = {"alair", "belfar", "peticionamento", "urotrobel", "nebacetin", "neomicina", "bacitracina", "sac"}
        vocab_ref_raw = set(re.findall(r'\b[a-zA-ZÀ-ÖØ-öø-ÿ0-9\-]+\b', (texto_referencia or "").lower()))
        spell.word_frequency.load_words(vocab_ref_raw.union(palavras_ignorar))
        entidades = set()
        if nlp:
            doc = nlp(texto_final)
            entidades = {ent.text.lower() for ent in doc.ents}
        palavras = re.findall(r'\b[a-zA-ZÀ-ÖØ-öø-ÿ]+\b', texto_final)
        palavras = [p for p in palavras if len(p) > 2]
        possiveis_erros = set(spell.unknown([p.lower() for p in palavras]))
        erros_filtrados = []
        vocab_norm = set(normalizar_texto(w) for w in vocab_ref_raw)
        for e in possiveis_erros:
            e_raw = e.lower()
            e_norm = normalizar_texto(e_raw)
            if e_raw in vocab_ref_raw or e_norm in vocab_norm: continue
            if e_raw in entidades or e_raw in palavras_ignorar: continue
            erros_filtrados.append(e_raw)
        return sorted(set(erros_filtrados))[:60]
    except: return []

def marcar_diferencas_palavra_por_palavra(texto_ref, texto_belfar, eh_referencia):
    def tokenizar(txt): return re.findall(r'\n|[A-Za-zÀ-ÖØ-öø-ÿ0-9_•]+|[^\w\s]', txt or "", re.UNICODE)
    def norm(tok):
        if tok == '\n': return ' '
        if re.match(r'[A-Za-zÀ-ÖØ-öø-ÿ0-9_•]+$', tok): return normalizar_texto(tok)
        return tok
    ref_tokens = tokenizar(texto_ref)
    bel_tokens = tokenizar(texto_belfar)
    ref_norm = [norm(t) for t in ref_tokens]
    bel_norm = [norm(t) for t in bel_tokens]
    matcher = difflib.SequenceMatcher(None, ref_norm, bel_norm, autojunk=False)
    indices = set()
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != 'equal': indices.update(range(i1, i2) if eh_referencia else range(j1, j2))
    tokens = ref_tokens if eh_referencia else bel_tokens
    marcado = []
    for idx, tok in enumerate(tokens):
        if tok == '\n': marcado.append('<br>'); continue
        if idx in indices and tok.strip() != '': marcado.append(f"<mark class='diff'>{tok}</mark>")
        else: marcado.append(tok)
    resultado = ""
    for i, tok in enumerate(marcado):
        if i == 0: resultado += tok; continue
        raw_tok = re.sub(r'^<mark[^>]*>|</mark>$', '', tok)
        if tok == '<br>' or marcado[i-1] == '<br>': resultado += tok
        elif re.match(r'^[^\w\s]$', raw_tok): resultado += tok
        else: resultado += " " + tok
    resultado = re.sub(r'\s+([.,;:!?)])', r'\1', resultado)
    resultado = re.sub(r'(\()\s+', r'\1', resultado)
    resultado = re.sub(r"(</mark>)\s+(<mark[^>]*>)", " ", resultado)
    return resultado

# ----------------- CONSTRUÇÃO HTML -----------------
def construir_html_secoes(secoes_analisadas, erros_ortograficos, eh_referencia=False):
    html_map = {}
    prefixos_paciente = {
        "PARA QUE ESTE MEDICAMENTO É INDICADO": "1.", "COMO ESTE MEDICAMENTO FUNCIONA?": "2.",
        "QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?": "3.", "O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?": "4.",
        "ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?": "5.", "COMO DEVO USAR ESTE MEDICAMENTO?": "6.",
        "O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?": "7.", "QUAIS OS MALES QUE ESTE MEDICAMENTO PODE CAUSAR?": "8.",
        "O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?": "9."
    }
    prefixos_map = prefixos_paciente
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
            tit = f"{prefixo} {secao_canonico}".strip()
            title_html = f"<div class='section-title ref-title'>{tit}</div>"
            conteudo = diff['conteudo_ref'] or ""
        else:
            tit_enc = diff.get('titulo_encontrado_belfar') or diff.get('titulo_encontrado_ref') or secao_canonico
            tit = f"{prefixo} {tit_enc}".strip() if prefixo and not tit_enc.strip().startswith(prefixo) else tit_enc
            title_html = f"<div class='section-title bel-title'>{tit}</div>"
            conteudo = diff['conteudo_belfar'] or ""
        if diff.get('ignorada', False):
            conteudo_html = (conteudo or "").replace('\n', '<br>')
        else:
            conteudo_html = marcar_diferencas_palavra_por_palavra(diff.get('conteudo_ref') or "", diff.get('conteudo_belfar') or "", eh_referencia)
        if not eh_referencia and not diff.get('ignorada', False):
            for pat, repl in mapa_erros.items():
                try: conteudo_html = re.sub(pat, repl, conteudo_html, flags=re.IGNORECASE)
                except: pass
        conteudo_html = anvisa_pattern.sub(r"<mark class='anvisa'>\1</mark>", conteudo_html)
        anchor_id = _create_anchor_id(secao_canonico, "ref" if eh_referencia else "bel")
        html_map[secao_canonico] = f"<div id='{anchor_id}' style='scroll-margin-top: 20px;'>{title_html}<div style='margin-top:6px;'>{conteudo_html}</div></div>"
    return html_map

def gerar_relatorio_final(texto_ref, texto_belfar, nome_ref, nome_belfar, tipo_bula):
    st.header("Relatório de Auditoria Inteligente")
    rx_anvisa = r"(aprovad[ao]\s+pela\s+anvisa\s+em|data\s+de\s+aprovação\s+na\s+anvisa:)\s*([\d]{1,2}/[\d]{1,2}/[\d]{2,4})"
    m_ref = re.search(rx_anvisa, texto_ref or "", re.IGNORECASE)
    m_bel = re.search(rx_anvisa, texto_belfar or "", re.IGNORECASE)
    data_ref = m_ref.group(2).strip() if m_ref else "Não encontrada"
    data_bel = m_bel.group(2).strip() if m_bel else "Não encontrada"

    secoes_faltantes, diferencas_conteudo, similaridades, diferencas_titulos, secoes_analisadas = verificar_secoes_e_conteudo(texto_ref, texto_belfar)
    erros = checar_ortografia_inteligente(texto_belfar, texto_ref)
    score = sum(similaridades)/len(similaridades) if similaridades else 100.0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Conformidade", f"{score:.0f}%")
    c2.metric("Erros Ortográficos", len(erros))
    c3.metric("Data ANVISA (Ref)", data_ref)
    c4.metric("Data ANVISA (Bel)", data_bel)

    st.divider()
    st.subheader("Seções (clique para expandir)")
    
    prefixos_paciente = {
        "PARA QUE ESTE MEDICAMENTO É INDICADO": "1.", "COMO ESTE MEDICAMENTO FUNCIONA?": "2.",
        "QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?": "3.", "O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?": "4.",
        "ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?": "5.", "COMO DEVO USAR ESTE MEDICAMENTO?": "6.",
        "O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?": "7.", "QUAIS OS MALES QUE ESTE MEDICAMENTO PODE CAUSAR?": "8.",
        "O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?": "9."
    }
    prefixos_map = prefixos_paciente

    html_ref = construir_html_secoes(secoes_analisadas, [], True)
    html_bel = construir_html_secoes(secoes_analisadas, erros, False)

    for diff in secoes_analisadas:
        sec = diff['secao']
        pref = prefixos_map.get(sec, "")
        tit = f"{pref} {sec}" if pref else sec
        status = "✅ Idêntico"
        if diff.get('faltante'): status = "🚨 FALTANTE"
        elif diff.get('ignorada'): status = "⚠️ Ignorada"
        elif diff.get('tem_diferenca'): status = "❌ Divergente"

        with st.expander(f"{tit} — {status}", expanded=(diff.get('tem_diferenca') or diff.get('faltante'))):
            c1, c2 = st.columns([1,1], gap="large")
            with c1:
                st.markdown(f"**Ref: {nome_ref}**", unsafe_allow_html=True)
                st.markdown(f"<div class='bula-box'>{html_ref.get(sec, '<i>N/A</i>')}</div>", unsafe_allow_html=True)
            with c2:
                st.markdown(f"**Bel: {nome_belfar}**", unsafe_allow_html=True)
                st.markdown(f"<div class='bula-box'>{html_bel.get(sec, '<i>N/A</i>')}</div>", unsafe_allow_html=True)

    st.divider()
    st.subheader("🎨 Visualização Completa")
    full_order = [s['secao'] for s in secoes_analisadas]
    h_r = "".join([html_ref.get(s, "") for s in full_order])
    h_b = "".join([html_bel.get(s, "") for s in full_order])
    
    cr, cb = st.columns(2, gap="large")
    with cr: st.markdown(f"**📄 {nome_ref}**<div class='bula-box-full'>{h_r}</div>", unsafe_allow_html=True)
    with cb: st.markdown(f"**📄 {nome_belfar}**<div class='bula-box-full'>{h_b}</div>", unsafe_allow_html=True)

# ----------------- VALIDAÇÃO DE TIPO -----------------
def detectar_tipo_arquivo_por_score(texto):
    if not texto: return "Indeterminado"
    titulos_paciente = ["como este medicamento funciona", "o que devo saber antes de usar"]
    titulos_profissional = ["resultados de eficacia", "caracteristicas farmacologicas"]
    t_norm = normalizar_texto(texto)
    score_pac = sum(1 for t in titulos_paciente if t in t_norm)
    score_prof = sum(1 for t in titulos_profissional if t in t_norm)
    if score_pac > score_prof: return "Paciente"
    elif score_prof > score_pac: return "Profissional"
    return "Indeterminado"

# ----------------- MAIN -----------------
st.title("🔬 Inteligência Artificial para Auditoria de Bulas (v59)")
st.markdown("Sistema com validação RÍGIDA e Limpeza Gráfica: Se os títulos das seções indicarem o tipo errado de bula, a comparação será bloqueada.")

st.divider()
tipo_bula_selecionado = "Paciente" # Fixo

col1, col2 = st.columns(2)
with col1:
    st.subheader("📄 Documento de Referência")
    pdf_ref = st.file_uploader("PDF/DOCX Referência", type=["pdf", "docx"], key="ref")
with col2:
    st.subheader("📄 Documento BELFAR")
    pdf_belfar = st.file_uploader("PDF/DOCX Belfar", type=["pdf", "docx"], key="belfar")

if st.button("🔍 Iniciar Auditoria Completa", use_container_width=True, type="primary"):
    if not (pdf_ref and pdf_belfar):
        st.warning("⚠️ Envie ambos os arquivos.")
    else:
        with st.spinner("Lendo arquivos, removendo lixo gráfico e validando estrutura..."):
            # Extração MKT (Split-Column) e Anvisa (Padrão)
            texto_ref_raw, erro_ref = extrair_texto(pdf_ref, 'docx' if pdf_ref.name.endswith('.docx') else 'pdf', is_marketing_pdf=False)
            texto_belfar_raw, erro_belfar = extrair_texto(pdf_belfar, 'docx' if pdf_belfar.name.endswith('.docx') else 'pdf', is_marketing_pdf=True)

            if erro_ref or erro_belfar:
                st.error(f"Erro de leitura: {erro_ref or erro_belfar}")
            else:
                detectado_ref = detectar_tipo_arquivo_por_score(texto_ref_raw)
                detectado_bel = detectar_tipo_arquivo_por_score(texto_belfar_raw)
                
                erro = False
                if detectado_ref == "Profissional": 
                    st.error(f"🚨 Arquivo ANVISA parece Bula Profissional. Use Paciente."); erro=True
                if detectado_bel == "Profissional":
                    st.error(f"🚨 Arquivo MKT parece Bula Profissional. Use Paciente."); erro=True
                
                if not erro:
                    # Aplica reconstrução de parágrafos (Correção MKT)
                    t_ref = reconstruir_paragrafos(texto_ref_raw)
                    t_ref = truncar_apos_anvisa(t_ref)
                    
                    t_bel = reconstruir_paragrafos(texto_belfar_raw)
                    t_bel = truncar_apos_anvisa(t_bel)
                    
                    gerar_relatorio_final(t_ref, t_bel, pdf_ref.name, pdf_belfar.name, tipo_bula_selecionado)

st.divider()
st.caption("Sistema de Auditoria de Bulas v59 | Filtro 'Nuclear' de Lixo Gráfico.")
