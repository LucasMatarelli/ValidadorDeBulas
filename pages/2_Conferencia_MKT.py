# pages/2_Conferencia_MKT.py
#
# Versão v26.58 (Corrigido e Aprimorado)
# - Corrigida a lógica de extração MKT (removidos blocos duplicados/indent errors).
# - Heurísticas conservadoras para realocar qualifiers (APRESENTAÇÕES).
# - Títulos injetados dentro do conteúdo (para exibição dentro das caixas).
# - Preservadas regras: DIZERES LEGAIS até o fim; ignorar comparação em APRESENTAÇÕES/COMPOSIÇÃO/DIZERES LEGAIS.
# - Código limpo e organizado para facilitar ajustes futuros.

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

# ----------------- MODELO NLP -----------------
@st.cache_resource
def carregar_modelo_spacy():
    try:
        return spacy.load("pt_core_news_lg")
    except OSError:
        st.warning("Modelo 'pt_core_news_lg' não encontrado. Algumas heurísticas de NER ficarão reduzidas.")
        return None

nlp = carregar_modelo_spacy()

# ----------------- EXTRAÇÃO (PDF/DOCX) -----------------
def extrair_texto(arquivo, tipo_arquivo, is_marketing_pdf=False):
    if arquivo is None:
        return "", f"Arquivo {tipo_arquivo} não enviado."
    try:
        arquivo.seek(0)
        texto = ""
        full_text_list = []

        if tipo_arquivo == 'pdf':
            with fitz.open(stream=arquivo.read(), filetype="pdf") as doc:
                if is_marketing_pdf:
                    # Tenta extrair por colunas (duas colunas comuns em MKT)
                    for page in doc:
                        rect = page.rect
                        left = fitz.Rect(0, 0, rect.width / 2, rect.height)
                        right = fitz.Rect(rect.width / 2, 0, rect.width, rect.height)
                        texto_left = page.get_text("text", clip=left, sort=True)
                        texto_right = page.get_text("text", clip=right, sort=True)
                        full_text_list.append(texto_left)
                        full_text_list.append(texto_right)
                else:
                    for page in doc:
                        full_text_list.append(page.get_text("text", sort=True))
            texto = "\n\n".join(full_text_list)

        elif tipo_arquivo == 'docx':
            doc = docx.Document(arquivo)
            texto = "\n".join([p.text for p in doc.paragraphs])

        # Normalizações básicas
        if texto:
            invis = ['\u00AD', '\u200B', '\u200C', '\u200D', '\uFEFF']
            for c in invis:
                texto = texto.replace(c, '')
            texto = texto.replace('\r\n', '\n').replace('\r', '\n')
            texto = texto.replace('\u00A0', ' ')
            # remover ruídos comuns de rodapé/arte
            padrao_rodape = re.compile(r'bula (?:do|para o) paciente|página \d+\s*de\s*\d+|artes@belfar', re.IGNORECASE)
            linhas = texto.split('\n')
            linhas = [l for l in linhas if not padrao_rodape.search(l.strip())]
            texto = "\n".join(linhas)

            # Inline noise
            padrao_ruido_inline = re.compile(r'BUL_CLORIDRATO_DE_[^\s]{1,50}|\bTimes New Roman\b', re.IGNORECASE)
            texto = padrao_ruido_inline.sub(' ', texto)

            # Remove numeração solta no marketing
            if is_marketing_pdf:
                texto = re.sub(r'(?m)^\s*\d{1,2}\.\s*', '', texto)
                texto = re.sub(r'(?<=\s)\d{1,2}\.(?=\s)', ' ', texto)

            # Filtra linhas vazias / sem letras em MKT
            linhas = texto.split('\n')
            linhas_filtradas = []
            for ln in linhas:
                ln_strip = ln.strip()
                if not ln_strip:
                    # preserve single blank separation
                    if not linhas_filtradas or linhas_filtradas[-1] != "":
                        linhas_filtradas.append("")
                    continue
                if is_marketing_pdf and not re.search(r'[A-Za-zÁÉÍÓÚÂÊÔÃÕÇáéíóúâêôãõç]', ln_strip):
                    # descarta linhas sem letras em marketing (ruído)
                    continue
                linhas_filtradas.append(re.sub(r'\s{2,}', ' ', ln_strip))
            texto = "\n".join(linhas_filtradas)
            texto = re.sub(r'\n{3,}', '\n\n', texto)
            texto = re.sub(r'[ \t]+', ' ', texto).strip()

        return texto, None

    except Exception as e:
        return "", f"Erro ao ler o arquivo {tipo_arquivo}: {e}"

# ----------------- UTILITÁRIOS DE NORMALIZAÇÃO -----------------
def normalizar_texto(texto):
    if not isinstance(texto, str):
        return ""
    texto = ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')
    texto = re.sub(r'[^\w\s]', '', texto)
    texto = ' '.join(texto.split())
    return texto.lower()

def normalizar_titulo_para_comparacao(texto):
    t = normalizar_texto(texto or "")
    t = re.sub(r'^\d+\s*[\.\-)]*\s*', '', t).strip()
    return t

# ----------------- CONFIGURAÇÃO DE SEÇÕES -----------------
def obter_secoes_por_tipo(tipo_bula):
    secoes = {
        "Paciente": [
            "APRESENTAÇÕES", "APRESENTACOES", "APRESENTAÇÃO", "APRESENTACAO",
            "COMPOSIÇÃO", "COMPOSICAO", "INFORMAÇÕES AO PACIENTE", "INFORMACOES AO PACIENTE",
            "1.PARA QUE ESTE MEDICAMENTO É INDICADO?",
            "2.COMO ESTE MEDICAMENTO FUNCIONA?",
            "3.QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?",
            "4.O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?",
            "5.ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?",
            "6.COMO DEVO USAR ESTE MEDICAMENTO?",
            "7.O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?",
            "8.QUAIS OS MALES QUE ESTE MEDICAMENTO PODE ME CAUSAR?",
            "9.O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?",
            "DIZERES LEGAIS"
        ],
        "Profissional": [
            "APRESENTAÇÕES", "COMPOSIÇÃO", "INFORMAÇÕES AO PACIENTE",
            "1. INDICAÇÕES", "2. RESULTADOS DE EFICÁCIA", "3. CARACTERÍSTICAS FARMACOLÓGICAS",
            "4. CONTRAINDICAÇÕES", "5. ADVERTÊNCIAS E PRECAUÇÕES",
            "6. INTERAÇÕES MEDICAMENTOSAS", "7. CUIDADOS DE ARMAZENAMENTO DO MEDICAMENTO",
            "8. POSOLOGIA E MODO DE USAR", "9. REAÇÕES ADVERSAS", "10. SUPERDOSE",
            "DIZERES LEGAIS"
        ]
    }
    return secoes.get(tipo_bula, [])

def obter_aliases_secao():
    return {
        "INDICAÇÕES": "1. INDICAÇÕES",
        "PARA QUE ESTE MEDICAMENTO É INDICADO?": "1.PARA QUE ESTE MEDICAMENTO É INDICADO?",
        "COMO ESTE MEDICAMENTO FUNCIONA?": "2.COMO ESTE MEDICAMENTO FUNCIONA?",
        "CONTRAINDICAÇÕES": "4. CONTRAINDICAÇÕES",
        "POSOLOGIA E MODO DE USAR": "8. POSOLOGIA E MODO DE USAR",
        "REAÇÕES ADVERSAS": "9. REAÇÕES ADVERSAS",
        "SUPERDOSE": "10. SUPERDOSE",
        "ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?": "5.ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?"
    }

def obter_secoes_ignorar_comparacao():
    return ["APRESENTAÇÕES", "COMPOSIÇÃO", "DIZERES LEGAIS"]

def obter_secoes_ignorar_ortografia():
    return ["COMPOSIÇÃO", "DIZERES LEGAIS"]

# ----------------- CORREÇÃO DE QUEBRAS EM TÍTULOS -----------------
def corrigir_quebras_em_titulos(texto):
    linhas = texto.split("\n")
    linhas_corrigidas = []
    buffer = ""
    for linha in linhas:
        linha_strip = linha.strip()
        if not linha_strip:
            if buffer:
                linhas_corrigidas.append(buffer)
                buffer = ""
            linhas_corrigidas.append("")
            continue
        is_potential_title = (linha_strip.isupper() and len(linha_strip) < 80) or re.match(r'^\d+\.', linha_strip)
        if is_potential_title:
            if buffer:
                buffer += " " + linha_strip
            else:
                buffer = linha_strip
        else:
            if buffer:
                linhas_corrigidas.append(buffer)
                buffer = ""
            linhas_corrigidas.append(linha_strip)
    if buffer:
        linhas_corrigidas.append(buffer)
    return "\n".join(linhas_corrigidas)

# ----------------- DETECÇÃO E MAPEAMENTO DE TÍTULOS -----------------
def is_titulo_secao(linha):
    linha = (linha or "").strip()
    if len(linha) < 4:
        return False
    if re.match(r'^\d+\.\s+[A-ZÁÉÍÓÚÂÊÔÃÕÇ]', linha):
        return True
    if len(linha.split()) > 20:
        return False
    if linha.endswith('.') or linha.endswith(':'):
        return False
    if len(linha) > 120:
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
    texto_normalizado = re.sub(r'\n{2,}', '\n', texto_completo or "")
    linhas = texto_normalizado.split('\n')
    aliases = obter_aliases_secao()
    titulos_possiveis = {}
    for s in secoes_esperadas:
        titulos_possiveis[s] = s
    for a, c in aliases.items():
        if c in secoes_esperadas:
            titulos_possiveis[a] = c
    titulos_norm_lookup = {normalizar_titulo_para_comparacao(t): c for t, c in titulos_possiveis.items()}
    limiar = 82
    for idx, ln in enumerate(linhas):
        linha = ln.strip()
        if not linha:
            continue
        if not is_titulo_secao(linha):
            continue
        norm = normalizar_titulo_para_comparacao(linha)
        best_score = 0
        best_canon = None
        for t_norm, canon in titulos_norm_lookup.items():
            score = fuzz.token_set_ratio(t_norm, norm)
            if score > best_score:
                best_score = score
                best_canon = canon
        if best_score < limiar:
            # contains fallback
            for t_norm, canon in titulos_norm_lookup.items():
                if t_norm and t_norm in norm:
                    best_score = 90
                    best_canon = canon
                    break
        # small lookahead to catch broken titles
        if best_score < limiar:
            look = (linha + " " + (linhas[idx+1].strip() if idx+1 < len(linhas) else "")).upper()
            for k in ["APRESENTA", "COMPOSI", "DIZERES", "INFORMAÇ", "INFORMAC"]:
                if k in look:
                    for t_norm, canon in titulos_norm_lookup.items():
                        if k.lower() in t_norm:
                            best_canon = canon
                            best_score = 85
                            break
                    if best_canon:
                        break
        if best_score >= limiar and best_canon:
            if not mapa or mapa[-1]['canonico'] != best_canon:
                mapa.append({'canonico': best_canon, 'titulo_encontrado': linha, 'linha_inicio': idx, 'score': best_score, 'num_linhas_titulo': 1})
    mapa.sort(key=lambda x: x['linha_inicio'])
    return mapa

# ----------------- EXTRAÇÃO DO CONTEÚDO POR SEÇÃO (INJETA TÍTULO) -----------------
def obter_dados_secao(secao_canonico, mapa_secoes, linhas_texto_split):
    idx = -1
    for i, m in enumerate(mapa_secoes):
        if m['canonico'] == secao_canonico:
            idx = i
            break
    if idx == -1:
        return False, None, ""
    info = mapa_secoes[idx]
    titulo = info['titulo_encontrado']
    linha_inicio = info['linha_inicio']
    num_linhas_titulo = info.get('num_linhas_titulo', 1)
    linha_inicio_conteudo = linha_inicio + num_linhas_titulo
    linha_fim = len(linhas_texto_split)
    if (idx + 1) < len(mapa_secoes):
        linha_fim = mapa_secoes[idx + 1]['linha_inicio']
    conteudo_lines = [linhas_texto_split[i] for i in range(linha_inicio_conteudo, linha_fim)]
    conteudo_sem_titulo = "\n".join(conteudo_lines).strip()
    if conteudo_sem_titulo:
        conteudo_final = f"{titulo}\n\n{conteudo_sem_titulo}"
    else:
        conteudo_final = titulo
    return True, titulo, conteudo_final

# ----------------- EXTRAI QUALIFIERS INICIAIS (CONSERVADOR) -----------------
def _extrair_linhas_qualificadoras_iniciais(texto, max_lines=4):
    if not texto:
        return [], texto
    linhas = texto.split('\n')
    qualifiers = []
    keys = {'USO', 'NASAL', 'ADULTO', 'EMBALAGENS', 'EMBALAGEM', 'FRASCOS', 'GOTAS', 'ML', 'MG', 'APRESENTA'}
    i = 0
    while i < min(len(linhas), max_lines):
        ln = linhas[i].strip()
        if not ln:
            i += 1
            continue
        ln_up = ln.upper()
        if ln_up in {'APRESENTAÇÃO','APRESENTACAO','APRESENTAÇÕES','APRESENTACOES','COMPOSIÇÃO','COMPOSICAO','DIZERES LEGAIS','INFORMAÇÕES AO PACIENTE','INFORMACOES AO PACIENTE'}:
            break
        words = ln.split()
        wc = len(words)
        alpha = sum(1 for ch in ln if ch.isalpha())
        upper_chars = sum(1 for ch in ln if ch.isalpha() and ch.isupper())
        upper_ratio = (upper_chars/alpha) if alpha > 0 else 0
        contains_key = any(k in ln_up for k in keys)
        is_short = wc <= 12 and len(ln) < 140
        is_upper = upper_ratio > 0.6 and is_short
        looks_like_comp = bool(re.search(r'\b(?:cont[eé]m|equivalente|mg\b|ml\b|ve[ií]culo|veiculo|q\.s\.p|qsp|\d+\s*mg|\d+\s*ml)\b', ln_up))
        if (contains_key and is_short) or is_upper:
            if looks_like_comp and not contains_key:
                break
            qualifiers.append(ln)
            i += 1
            continue
        break
    restante = '\n'.join(linhas[i:]).strip()
    return qualifiers, restante

# ----------------- VERIFICAÇÃO DE SEÇÕES E REALOCAÇÃO SEGURA -----------------
def verificar_secoes_e_conteudo(texto_ref, texto_belfar, tipo_bula):
    secoes_esperadas = obter_secoes_por_tipo(tipo_bula)
    secoes_faltantes = []
    diferencas_titulos = []
    relatorio = []
    similaridade_geral = []
    secoes_ignorar_upper = [s.upper() for s in obter_secoes_ignorar_comparacao()]

    linhas_ref = re.sub(r'\n{2,}', '\n', texto_ref or "").split('\n')
    linhas_belfar = re.sub(r'\n{2,}', '\n', texto_belfar or "").split('\n')

    mapa_ref = mapear_secoes(texto_ref or "", secoes_esperadas)
    mapa_belfar = mapear_secoes(texto_belfar or "", secoes_esperadas)

    conteudos = {}
    for sec in secoes_esperadas:
        encontrou_ref, _, conteudo_ref = obter_dados_secao(sec, mapa_ref, linhas_ref)
        encontrou_bel, _, conteudo_bel = obter_dados_secao(sec, mapa_belfar, linhas_belfar)
        conteudos[sec] = {
            'encontrou_ref': encontrou_ref,
            'conteudo_ref': conteudo_ref or "",
            'encontrou_bel': encontrou_bel,
            'conteudo_bel': conteudo_bel or ""
        }
        if not encontrou_bel:
            secoes_faltantes.append(sec)

    # Realocação estrita: só move qualifiers do topo de COMPOSIÇÃO para APRESENTAÇÕES
    def realocar_qualifiers_inplace(map_conteudos, src_section='COMPOSIÇÃO', dst_section='APRESENTAÇÕES'):
        src = map_conteudos.get(src_section)
        dst = map_conteudos.get(dst_section)
        if not src or not dst:
            return
        if not src.get('conteudo_bel', "").strip():
            return
        qualifiers_bel, restante_bel = _extrair_linhas_qualificadoras_iniciais(src['conteudo_bel'], max_lines=4)
        if not qualifiers_bel:
            return
        # Só mover se destino foi detectado no MKT
        if not dst.get('encontrou_bel', False):
            return
        # evita mover se qualifiers parecem composição
        looks_like_comp = any(re.search(r'\b(?:cont[eé]m|equivalente|mg\b|ml\b|ve[ií]culo|q\.s\.p|qsp)\b', q.upper()) for q in qualifiers_bel)
        if looks_like_comp:
            return
        # Não mover se restante do src ficar muito curto (proteção)
        if len(restante_bel.strip()) < 40:
            return
        # evita duplicação
        dst_norm = normalizar_texto(dst.get('conteudo_bel', ""))
        for q in qualifiers_bel:
            if normalizar_texto(q) in dst_norm:
                # já presente, só atualizar source
                src['conteudo_bel'] = restante_bel
                return
        # Prepend qualifiers after destination title
        qual_text = '\n'.join(q for q in qualifiers_bel if q.strip())
        lines_dst = dst.get('conteudo_bel', "").split('\n')
        title_dst = lines_dst[0] if lines_dst and lines_dst[0].strip() else dst_section
        rest_dst = '\n'.join(lines_dst[1:]).strip() if len(lines_dst) > 1 else ""
        combined = f"{title_dst}\n\n{qual_text}\n\n{rest_dst}".strip()
        dst['conteudo_bel'] = combined
        src['conteudo_bel'] = restante_bel

    # Aplicar realocação conservadora
    realocar_qualifiers_inplace(conteudos, src_section='COMPOSIÇÃO', dst_section='APRESENTAÇÕES')

    # Rebuild relatorio & similarity
    for sec in secoes_esperadas:
        item = conteudos[sec]
        encontrou_ref = item['encontrou_ref']
        encontrou_bel = item['encontrou_bel']
        conteudo_ref = item['conteudo_ref']
        conteudo_bel = item['conteudo_bel']
        if not encontrou_bel:
            relatorio.append({'secao': sec, 'status': 'faltante', 'conteudo_ref': conteudo_ref, 'conteudo_belfar': ""})
            continue
        if encontrou_ref and encontrou_bel:
            if sec.upper() in secoes_ignorar_upper:
                relatorio.append({'secao': sec, 'status': 'identica', 'conteudo_ref': conteudo_ref, 'conteudo_belfar': conteudo_bel})
                similaridade_geral.append(100)
            else:
                if normalizar_texto(conteudo_ref) != normalizar_texto(conteudo_bel):
                    relatorio.append({'secao': sec, 'status': 'diferente', 'conteudo_ref': conteudo_ref, 'conteudo_belfar': conteudo_bel})
                    similaridade_geral.append(0)
                else:
                    relatorio.append({'secao': sec, 'status': 'identica', 'conteudo_ref': conteudo_ref, 'conteudo_belfar': conteudo_bel})
                    similaridade_geral.append(100)

    # Detect title diffs
    titulos_ref_encontrados = {m['canonico']: m['titulo_encontrado'] for m in mapa_ref}
    titulos_belfar_encontrados = {m['canonico']: m['titulo_encontrado'] for m in mapa_belfar}
    for secao_canonico, titulo_ref in titulos_ref_encontrados.items():
        if secao_canonico in titulos_belfar_encontrados:
            titulo_belfar = titulos_belfar_encontrados[secao_canonico]
            if normalizar_titulo_para_comparacao(titulo_ref) != normalizar_titulo_para_comparacao(titulo_belfar):
                diferencas_titulos.append({'secao_esperada': secao_canonico, 'titulo_encontrado': titulo_belfar})

    return secoes_faltantes, relatorio, similaridade_geral, diferencas_titulos

# ----------------- ORTOGRAFIA INTELIGENTE -----------------
def checar_ortografia_inteligente(texto_para_checar, texto_referencia, tipo_bula):
    if not texto_para_checar:
        return []
    try:
        secoes_ignorar = [s.upper() for s in obter_secoes_ignorar_ortografia()]
        secoes_todas = obter_secoes_por_tipo(tipo_bula)
        mapa = mapear_secoes(texto_para_checar, secoes_todas)
        linhas = re.sub(r'\n{2,}', '\n', texto_para_checar).split('\n')
        textos = []
        for sec in secoes_todas:
            if sec.upper() in secoes_ignorar:
                continue
            found, _, c = obter_dados_secao(sec, mapa, linhas)
            if found and c:
                textos.append(c)
        texto_final = "\n".join(textos)
        if not texto_final:
            return []
        spell = SpellChecker(language='pt')
        palavras_a_ignorar = {"alair", "belfar", "peticionamento", "urotrobel", "contato", "iobeguane"}
        vocab_referencia = set(re.findall(r'\b[a-záéíóúâêôãõçü]+\b', (texto_referencia or "").lower()))
        if nlp:
            doc = nlp(texto_para_checar)
            entidades = {ent.text.lower() for ent in doc.ents}
        else:
            entidades = set()
        spell.word_frequency.load_words(vocab_referencia.union(entidades).union(palavras_a_ignorar))
        palavras = re.findall(r'\b[a-záéíóúâêôãõçü]+\b', texto_final.lower())
        erros = spell.unknown(palavras)
        return sorted(set([e for e in erros if len(e) > 3]))[:30]
    except Exception:
        return []

# ----------------- DIFERENÇAS PALAVRA-POR-PALAVRA -----------------
def marcar_diferencas_palavra_por_palavra(texto_ref, texto_belfar, eh_referencia):
    texto_ref = texto_ref or ""
    texto_belfar = texto_belfar or ""
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
        prev_raw = re.sub(r'^<mark[^>]*>|</mark>$', '', marcado[i-1])
        raw_tok = re.sub(r'^<mark[^>]*>|</mark>$', '', tok)
        if not re.match(r'^[.,;:!?)\\]$', raw_tok) and raw_tok != '\n' and prev_raw != '\n' and not re.match(r'^[(\\[]$', prev_raw):
            resultado += " " + tok
        else:
            resultado += tok
    resultado = re.sub(r"(</mark>)\s+(<mark[^>]*>)", " ", resultado)
    return resultado

# ----------------- FORMATAÇÃO HTML PARA LEITURA (TÍTULOS DENTRO DO CONTEÚDO) -----------------
def formatar_html_para_leitura(html_content, aplicar_numeracao=False):
    if not html_content:
        return ""
    cor_titulo = "#0b5686" if aplicar_numeracao else "#0b8a3e"
    estilo_titulo_inline = f"font-family: 'Georgia', 'Times New Roman', serif; font-weight:700; color: {cor_titulo}; font-size:15px; margin-bottom:8px;"
    # remove números soltos no MKT
    if not aplicar_numeracao:
        html_content = re.sub(r'(?:[\n\r]+)\s*\d+\.\s*(?:[\n\r]+)', '\n\n', html_content, flags=re.IGNORECASE)
        html_content = re.sub(r'^\s*\d+\.\s*(?:[\n\r]+)', '', html_content, flags=re.IGNORECASE)
        html_content = re.sub(r'(?:[\n\r]+)\s*\d+\.\s*$', '', html_content, flags=re.IGNORECASE)
    html_content = re.sub(r'\n{2,}', '[[PARAGRAPH]]', html_content)
    titulos_lista = [
        "APRESENTAÇÕES", "APRESENTACOES", "APRESENTAÇÃO", "APRESENTACAO",
        "COMPOSIÇÃO", "COMPOSICAO", "DIZERES LEGAIS", "INFORMAÇÕES AO PACIENTE", "INFORMACOES AO PACIENTE"
    ]
    def render_title(match):
        titulo = match.group(0)
        titulo_limpo = re.sub(r'</?(?:mark|strong)[^>]*>', '', titulo, flags=re.IGNORECASE)
        titulo_sem_num = re.sub(r'^\d+\.\s*', '', titulo_limpo).strip()
        # determine numbering for known titles
        num_prefix = ""
        upper = titulo_limpo.upper()
        if 'PARA QUE' in upper and 'INDICADO' in upper:
            num_prefix = "1. "
        elif 'COMO ESTE MEDICAMENTO FUNCIONA' in upper:
            num_prefix = "2. "
        elif 'QUANDO NÃO DEVO' in upper or 'QUANDO NAO DEVO' in upper:
            num_prefix = "3. "
        elif 'O QUE DEVO SABER ANTES' in upper:
            num_prefix = "4. "
        elif 'ONDE' in upper and 'GUARDAR' in upper:
            num_prefix = "5. "
        elif 'COMO DEVO USAR' in upper:
            num_prefix = "6. "
        elif 'ESQUECER' in upper:
            num_prefix = "7. "
        elif 'QUAIS OS MALES' in upper:
            num_prefix = "8. "
        elif 'QUANTIDADE MAIOR' in upper:
            num_prefix = "9. "
        # don't add numbering for presentation/composition/legal/info
        if any(k in upper for k in ['APRESENTA', 'COMPOSI', 'DIZERES', 'INFORMA']):
            num_prefix = ""
        return f'[[PARAGRAPH]]<div style="{estilo_titulo_inline}">{num_prefix}{titulo_sem_num}</div>'
    for t in titulos_lista:
        html_content = re.sub(t, render_title, html_content, flags=re.IGNORECASE)
    # lists and breaks
    html_content = re.sub(r'(\n)(\s*[-–•*])', r'[[LIST_ITEM]]\2', html_content)
    html_content = html_content.replace('\n', ' ')
    html_content = html_content.replace('[[PARAGRAPH]]', '<br><br>')
    html_content = html_content.replace('[[LIST_ITEM]]', '<br>')
    html_content = re.sub(r'(<br\s*/?>\s*){3,}', '<br><br>', html_content)
    html_content = re.sub(r'\s{2,}', ' ', html_content)
    return html_content

# ----------------- MARCAÇÃO DE DIVERGÊNCIAS -----------------
def marcar_divergencias_html(texto_original, secoes_problema_lista_dicionarios, erros_ortograficos, tipo_bula, eh_referencia=False):
    texto_trabalho = texto_original or ""
    # marcar divergências por substituição de blocos (se encontrados)
    if secoes_problema_lista_dicionarios:
        for diff in secoes_problema_lista_dicionarios:
            if diff.get('status') != 'diferente':
                continue
            conteudo_ref = diff.get('conteudo_ref') or ""
            conteudo_bel = diff.get('conteudo_belfar') or ""
            alvo = conteudo_ref if eh_referencia else conteudo_bel
            if alvo and alvo in texto_trabalho:
                marcado = marcar_diferencas_palavra_por_palavra(conteudo_ref, conteudo_bel, eh_referencia)
                texto_trabalho = texto_trabalho.replace(alvo, marcado, 1)
    # erros ortográficos
    if erros_ortograficos and not eh_referencia:
        for erro in erros_ortograficos:
            pattern = r'\b(' + re.escape(erro) + r')\b(?![^<]*?>)'
            texto_trabalho = re.sub(pattern, r"<mark style='background-color: #FFDDC1; padding: 2px;'>\1</mark>", texto_trabalho, flags=re.IGNORECASE)
    # marcar data ANVISA
    regex_anvisa = r"((?:aprovad[ao]\s+pela\s+anvisa\s+em|data\s+de\s+aprova\w+\s+na\s+anvisa:)\s*[\d]{1,2}\s*/\s*[\d]{1,2}\s*/\s*[\d]{2,4})"
    def clean_anvisa(m):
        s = re.sub(r'<mark.*?>|</mark>', '', m.group(1))
        return f"<mark style='background-color: #cce5ff; padding: 2px; font-weight:500;'>{s}</mark>"
    texto_trabalho = re.sub(regex_anvisa, clean_anvisa, texto_trabalho, count=1, flags=re.IGNORECASE)
    return texto_trabalho

# ----------------- CONSTRUÇÃO HTML POR SEÇÃO -----------------
def construir_html_secoes(secoes_analise, erros_ortograficos, tipo_bula, eh_referencia=False):
    html_map = {}
    for item in secoes_analise:
        sec = item['secao']
        if eh_referencia:
            titulo_display = item.get('titulo_encontrado_ref') or sec
            conteudo = item.get('conteudo_ref') or ""
        else:
            titulo_display = item.get('titulo_encontrado_belfar') or item.get('titulo_encontrado_ref') or sec
            conteudo = item.get('conteudo_belfar') or ""
        # se a seção está marcada como ignorada, não aplica marcações
        if item.get('ignorada', False):
            conteudo_html = (conteudo or "").replace('\n', '<br>')
        else:
            conteudo_html = marcar_diferencas_palavra_por_palavra(item.get('conteudo_ref') or "", item.get('conteudo_belfar') or "", eh_referencia)
            if not eh_referencia and erros_ortograficos:
                for e in erros_ortograficos:
                    conteudo_html = re.sub(r'(?<![>A-Za-z])\b' + re.escape(e) + r'\b', r"<mark class='ort'>\g<0></mark>", conteudo_html, flags=re.IGNORECASE)
        # marcar ANVISA datas
        conteudo_html = re.sub(r"((?:aprovad[ao]\s+pela\s+anvisa\s+em|data\s+de\s+aprova\w+\s+na\s+anvisa:)\s*[\d]{1,2}/[\d]{1,2}/[\d]{2,4})",
                               r"<mark class='anvisa'>\1</mark>", conteudo_html, flags=re.IGNORECASE)
        # inject title inside content is already done upstream via obter_dados_secao, so just wrap
        html_map[sec] = f"<div style='margin-bottom:12px;'>{conteudo_html.replace(chr(10), '<br>')}</div>"
    return html_map

# ----------------- GERAÇÃO DE RELATÓRIO E UI -----------------
def gerar_relatorio_final(texto_ref, texto_belfar, nome_ref, nome_belfar, tipo_bula):
    st.header("Relatório de Auditoria Inteligente")
    secoes_faltantes, relatorio_comparacao_completo, similaridades, diferencas_titulos = verificar_secoes_e_conteudo(texto_ref, texto_belfar, tipo_bula)
    erros_ortograficos = checar_ortografia_inteligente(texto_belfar, texto_ref, tipo_bula)
    score = sum(similaridades) / len(similaridades) if similaridades else 100.0

    # Dashboard
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Conformidade de Conteúdo", f"{score:.0f}%")
    col2.metric("Erros Ortográficos", len(erros_ortograficos))
    # extrai data anvisa das duas fontes (se houver)
    rx = r"(aprovad[ao]\s+pela\s+anvisa\s+em|data\s+de\s+aprova\w+\s+na\s+anvisa:)\s*([\d]{1,2}/[\d]{1,2}/[\d]{2,4})"
    match_ref = re.search(rx, (texto_ref or "").lower())
    match_bel = re.search(rx, (texto_belfar or "").lower())
    data_ref = match_ref.group(2) if match_ref else "Não encontrada"
    data_bel = match_bel.group(2) if match_bel else "Não encontrada"
    col3.metric("Data ANVISA (Ref)", data_ref)
    col4.metric("Seções Faltantes", f"{len(secoes_faltantes)}")

    st.divider()
    st.subheader("Análise Detalhada Seção por Seção")

    # Expanders por seção
    for item in relatorio_comparacao_completo:
        sec = item['secao']
        status = item['status']
        label = f"{sec} — {'✅ Conteúdo Idêntico' if status=='identica' else '❌ Conteúdo Divergente' if status=='diferente' else '🚨 SEÇÃO FALTANTE'}"
        with st.expander(label, expanded=(status != 'identica')):
            colA, colB = st.columns(2)
            with colA:
                st.markdown(f"**Referência: {nome_ref}**")
                texto_html_ref = formatar_html_para_leitura(item.get('conteudo_ref') or "", aplicar_numeracao=True)
                st.markdown(f"<div style='height:320px; overflow-y:auto; border:1px solid #e8e8e8; padding:12px; font-family:Georgia,serif;'>{texto_html_ref}</div>", unsafe_allow_html=True)
            with colB:
                st.markdown(f"**BELFAR: {nome_belfar}**")
                texto_html_bel = formatar_html_para_leitura(item.get('conteudo_belfar') or "", aplicar_numeracao=False)
                if erros_ortograficos and status != 'faltante':
                    # marca erros ortográficos simples
                    for e in erros_ortograficos:
                        texto_html_bel = re.sub(r'(?<![>A-Za-z])\b' + re.escape(e) + r'\b', r"<mark style='background-color:#FFDDC1;'>\g<0></mark>", texto_html_bel, flags=re.IGNORECASE)
                st.markdown(f"<div style='height:320px; overflow-y:auto; border:1px solid #e8e8e8; padding:12px; font-family:Georgia,serif;'>{texto_html_bel}</div>", unsafe_allow_html=True)

    # Visualização completa lado a lado
    st.divider()
    st.subheader("🎨 Visualização Lado a Lado com Destaques")
    html_ref_bruto = marcar_divergencias_html(texto_ref or "", relatorio_comparacao_completo, [], tipo_bula, eh_referencia=True)
    html_bel_bruto = marcar_divergencias_html(texto_belfar or "", relatorio_comparacao_completo, erros_ortograficos, tipo_bula, eh_referencia=False)
    html_ref_marcado = formatar_html_para_leitura(html_ref_bruto, aplicar_numeracao=True)
    html_bel_marcado = formatar_html_para_leitura(html_bel_bruto, aplicar_numeracao=False)

    colR, colB = st.columns(2, gap="large")
    with colR:
        st.markdown(f"**📄 {nome_ref}**")
        st.markdown(f"<div style='max-height:680px; overflow-y:auto; border:1px solid #e8e8e8; padding:18px; font-family:Georgia,serif;'>{html_ref_marcado}</div>", unsafe_allow_html=True)
    with colB:
        st.markdown(f"**📄 {nome_belfar}**")
        st.markdown(f"<div style='max-height:680px; overflow-y:auto; border:1px solid #e8e8e8; padding:18px; font-family:Georgia,serif;'>{html_bel_marcado}</div>", unsafe_allow_html=True)

    if erros_ortograficos:
        st.info("📝 Possíveis erros ortográficos (sugeridos): " + ", ".join(erros_ortograficos))

# ----------------- INTERFACE PRINCIPAL -----------------
st.set_page_config(layout="wide", page_title="Auditoria de Bulas MKT", page_icon="🔬")
st.title("🔬 Inteligência Artificial para Auditoria de Bulas (MKT vs ANVISA)")

st.markdown("Envie o arquivo da ANVISA (pdf/docx) e o PDF Marketing (MKT). Sistema tentará mapear seções e realocar qualificadores de APRESENTAÇÕES de forma conservadora.")

st.divider()
tipo_bula_selecionado = st.radio("Tipo de Bula:", ("Paciente", "Profissional"), horizontal=True)
col1, col2 = st.columns(2)
with col1:
    st.subheader("📄 Arquivo ANVISA")
    pdf_ref = st.file_uploader("Envie o arquivo da Anvisa (.docx ou .pdf)", type=["docx", "pdf"], key="ref")
with col2:
    st.subheader("📄 Arquivo MKT")
    pdf_belfar = st.file_uploader("Envie o PDF do Marketing", type="pdf", key="belfar")

if st.button("🔍 Iniciar Auditoria Completa", use_container_width=True, type="primary"):
    if not (pdf_ref and pdf_belfar):
        st.warning("⚠️ Envie ambos os arquivos para prosseguir.")
    else:
        with st.spinner("Processando..."):
            tipo_ref = 'docx' if pdf_ref.name.lower().endswith('.docx') else 'pdf'
            texto_ref, erro_ref = extrair_texto(pdf_ref, tipo_ref, is_marketing_pdf=False)
            texto_belfar, erro_belfar = extrair_texto(pdf_belfar, 'pdf', is_marketing_pdf=True)
            if erro_ref or erro_belfar:
                st.error(f"Erro de leitura: {erro_ref or erro_belfar}")
            else:
                texto_ref = corrigir_quebras_em_titulos(texto_ref)
                texto_belfar = corrigir_quebras_em_titulos(texto_belfar)
                texto_ref = re.sub(r'\n{3,}', '\n\n', texto_ref).strip()
                texto_belfar = re.sub(r'\n{3,}', '\n\n', texto_belfar).strip()
                gerar_relatorio_final(texto_ref, texto_belfar, pdf_ref.name, pdf_belfar.name, tipo_bula_selecionado)

st.divider()
st.caption("Sistema de Auditoria de Bulas v26.58 (corrigido). Se algo ainda estiver errado, cole aqui as primeiras ~12 linhas extraídas das seções APRESENTAÇÕES e COMPOSIÇÃO do Arquivo MKT para eu ajustar as heurísticas especificamente para seu PDF.")
