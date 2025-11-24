# pages/2_Conferencia_MKT.py
#
# Versão v47 - Reflow de Texto MKT + Correção Data Azul
# - NOVO: Função `reconstruir_paragrafos` -> Pega o texto "fatiado" do MKT e junta
#   as linhas para formar parágrafos completos, melhorando visual e comparação.
# - AJUSTE: Regex da Data ANVISA blindado contra quebras de linha para garantir o azul.
# - MANTIDO: Bloqueio de Bula Profissional e filtros de limpeza.

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
    # [AJUSTE v47] Regex permite quebras de linha (\s+) dentro da frase chave
    regex_anvisa = r"((?:aprovad[ao]\s+pela\s+anvisa\s+em|data\s+de\s+aprova\w+\s+na\s+anvisa:)\s*([\d]{1,2}\s*/\s*[\d]{1,2}\s*/\s*[\d]{2,4}))"
    match = re.search(regex_anvisa, texto, re.IGNORECASE | re.DOTALL)
    if not match: return texto
    cut_off_position = match.end(1)
    pos_match = re.search(r'^\s*\.', texto[cut_off_position:], re.IGNORECASE)
    if pos_match: cut_off_position += pos_match.end()
    return texto[:cut_off_position]

# ----------------- EXTRAÇÃO DE TEXTO -----------------
def extrair_texto(arquivo, tipo_arquivo, is_marketing_pdf=False):
    if arquivo is None: return "", f"Arquivo {tipo_arquivo} não enviado."
    try:
        arquivo.seek(0)
        texto = ""
        full_text_list = []

        if tipo_arquivo == 'pdf':
            with fitz.open(stream=arquivo.read(), filetype="pdf") as doc:
                if is_marketing_pdf:
                    for page in doc:
                        rect = page.rect
                        # Margens e Clipping para remover cabeçalho/rodapé físico
                        margin_y = rect.height * 0.08
                        margin_x = rect.width * 0.12
                        mid_x = rect.width / 2
                        
                        clip_esq = fitz.Rect(margin_x, margin_y, mid_x, rect.height - margin_y)
                        clip_dir = fitz.Rect(mid_x, margin_y, rect.width - margin_x, rect.height - margin_y)

                        t_esq = page.get_text("text", clip=clip_esq, sort=True)
                        t_dir = page.get_text("text", clip=clip_dir, sort=True)
                        full_text_list.append(t_esq)
                        full_text_list.append(t_dir)
                else:
                    for page in doc:
                        full_text_list.append(page.get_text("text", sort=True))
            texto = "\n\n".join(full_text_list)
        elif tipo_arquivo == 'docx':
            doc = docx.Document(arquivo)
            texto = "\n".join([p.text for p in doc.paragraphs])

        if texto:
            invis = ['\u00AD', '\u200B', '\u200C', '\u200D', '\uFEFF']
            for c in invis: texto = texto.replace(c, '')
            texto = texto.replace('\r\n', '\n').replace('\r', '\n')
            texto = texto.replace('\u00A0', ' ')

            # Limpeza de linhas inúteis (cabeçalhos repetitivos)
            linhas_temp = texto.split('\n')
            linhas_filtradas_info = []
            for linha in linhas_temp:
                l_up = linha.upper().strip()
                if re.match(r'^\s*INFORMA[ÇC][OÕ]ES\s+(AO|PARA(\s+O)?)\s+PACIENTE.*', l_up): continue
                if re.match(r'^\s*BULA\s+PARA\s+(O\s+)?PACIENTE.*', l_up): continue
                linhas_filtradas_info.append(linha)
            texto = '\n'.join(linhas_filtradas_info)

            # Regex de ruídos específicos do MKT
            ruidos_linha = (
                r'bula do paciente|página \d+\s*de\s*\d+|Tipologie|Tipologia|Merida|Medida'
                r'|Impressãe|Impressão|Papel[\.:]? Ap|Cor:? Preta|artes@belfar'
                r'|Times New Roman|^\s*FRENTE\s*$|^\s*VERSO\s*$|^\s*\d+\s*mm\s*$'
                r'|^\s*BELFAR\s*$|^\s*REZA\s*$|^\s*BUL\d+\s*$|BUL_CLORIDRATO'
                r'|\d{2}\s\d{4}\s\d{4}|^\s*[\w_]*BUL\d+V\d+[\w_]*\s*$'
                r'|^\s*[A-Za-z]{5,}_[A-Za-z_]+\s*$'
            )
            padrao_ruido_linha = re.compile(ruidos_linha, re.IGNORECASE)

            ruidos_inline = (
                r'BUL_CLORIDRATO_[\w\d_]+|New\s*Roman|Times\s*New|(?<=\s)mm(?=\s)'
                r'|\b\d+([,.]\d+)?\s*mm\b|\b[\w_]*BUL\d+V\d+\b'
                r'|\b(150|300|00150|00300)\s*,\s*00\b'
            )
            padrao_ruido_inline = re.compile(ruidos_inline, re.IGNORECASE)

            texto = padrao_ruido_inline.sub(' ', texto)
            
            if is_marketing_pdf:
                texto = re.sub(r'(?m)^\s*\d{1,2}\.\s*', '', texto) # Remove numeração solta

            linhas = texto.split('\n')
            linhas_limpas = []
            for linha in linhas:
                ls = linha.strip()
                if padrao_ruido_linha.search(ls): continue
                l_clean = re.sub(r'\s{2,}', ' ', ls).strip()
                if is_marketing_pdf and not re.search(r'[A-Za-z]', l_clean): continue
                if l_clean: linhas_limpas.append(l_clean)
                elif not linhas_limpas or linhas_limpas[-1] != "": linhas_limpas.append("")
            
            texto = "\n".join(linhas_limpas)
            texto = re.sub(r'\n{3,}', '\n\n', texto).strip()
            return texto, None
    except Exception as e:
        return "", f"Erro: {e}"

# ----------------- LÓGICA DE TÍTULOS -----------------
def is_titulo_secao(linha):
    ln = linha.strip()
    if len(ln) < 4 or len(ln.split('\n')) > 2 or len(ln.split()) > 20: return False
    first_line = ln.split('\n')[0]
    # Regra 1: Numeração + Letra (ex: 1. PARA QUE...)
    if re.match(r'^\d+\s*[\.\-)]*\s+[A-ZÁÉÍÓÚÂÊÔÃÕÇ]', first_line): return True
    # Regra 2: Tudo maiúsculo sem ponto final
    if first_line.isupper() and not first_line.endswith('.'): return True
    return False

# ----------------- RECONSTRUÇÃO DE PARÁGRAFOS (NOVO v47) -----------------
def reconstruir_paragrafos(texto):
    """
    [v47] Função crucial para o MKT:
    Pega o texto que está quebrado linha a linha (coluna estreita) e 
    junta em parágrafos contínuos, respeitando os Títulos.
    """
    if not texto: return ""
    
    linhas = texto.split('\n')
    linhas_reconstruidas = []
    buffer = ""
    
    for linha in linhas:
        linha = linha.strip()
        
        # 1. Se a linha for vazia, descarrega o buffer e adiciona quebra
        if not linha:
            if buffer:
                linhas_reconstruidas.append(buffer)
                buffer = ""
            if linhas_reconstruidas and linhas_reconstruidas[-1] != "":
                linhas_reconstruidas.append("") # Adiciona espaçamento visual
            continue
            
        # 2. Se a linha for um TÍTULO
        if is_titulo_secao(linha):
            if buffer:
                linhas_reconstruidas.append(buffer)
                buffer = ""
            linhas_reconstruidas.append(linha) # Adiciona o título como linha isolada
            continue
            
        # 3. É conteúdo. Vamos decidir se juntamos com a anterior (buffer)
        if buffer:
            # Se o buffer termina com hífen, junta sem espaço (ex: pro-\nblema -> problema)
            if buffer.endswith('-'):
                buffer = buffer[:-1] + linha
            # Se o buffer termina com pontuação final, provavelmente acabou a frase.
            # Mas em listas de composição, pode não ter ponto. 
            # Heurística: Se a linha atual começa com Minúscula, é continuação certa.
            # Se começa com Maiúscula, pode ser nova frase ou nome próprio.
            # Para MKT (coluna estreita), assumimos continuação se não tiver ponto final.
            elif not buffer.endswith(('.', ':', '!', '?')):
                buffer += " " + linha
            else:
                # Buffer terminou com ponto. Descarrega e começa novo.
                linhas_reconstruidas.append(buffer)
                buffer = linha
        else:
            buffer = linha
            
    if buffer:
        linhas_reconstruidas.append(buffer)
        
    texto_final = "\n".join(linhas_reconstruidas)
    # Garante espaçamento duplo entre parágrafos
    texto_final = re.sub(r'\n{2,}', '\n\n', texto_final)
    return texto_final

# ----------------- SEÇÕES E ALIASES -----------------
def obter_secoes_por_tipo(tipo_bula):
    return [
        "APRESENTAÇÕES", "COMPOSIÇÃO",
        "1.PARA QUE ESTE MEDICAMENTO É INDICADO?", "2.COMO ESTE MEDICAMENTO FUNCIONA?",
        "3.QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?", "4.O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?",
        "5.ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?", "6.COMO DEVO USAR ESTE MEDICAMENTO?",
        "7.O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?",
        "8.QUAIS OS MALES QUE ESTE MEDICAMENTO PODE ME CAUSAR?",
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
        "QUAIS OS MALES QUE ESTE MEDICAMENTO PODE ME CAUSAR?": "8.QUAIS OS MALES QUE ESTE MEDICAMENTO PODE ME CAUSAR?",
        "O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?": "9.O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?",
    }

def obter_secoes_ignorar_comparacao(): return ["APRESENTAÇÕES", "COMPOSIÇÃO", "DIZERES LEGAIS"]
def obter_secoes_ignorar_ortografia(): return ["APRESENTAÇÕES", "COMPOSIÇÃO", "DIZERES LEGAIS"]

# ----------------- MAPEAMENTO E DADOS -----------------
def mapear_secoes(texto, secoes_esperadas):
    mapa = []
    linhas = texto.split('\n')
    aliases = obter_aliases_secao()
    
    # Cria dicionário de lookup normalizado
    titulos_possiveis = {normalizar_titulo_para_comparacao(s): s for s in secoes_esperadas}
    for alias, canon in aliases.items():
        if canon in secoes_esperadas:
            titulos_possiveis[normalizar_titulo_para_comparacao(alias)] = canon

    for idx, linha in enumerate(linhas):
        l_strip = linha.strip()
        if not l_strip or not is_titulo_secao(l_strip): continue
        
        norm = normalizar_titulo_para_comparacao(l_strip)
        best_score = 0
        best_canon = None
        
        for t_norm, canon in titulos_possiveis.items():
            score = fuzz.token_set_ratio(t_norm, norm)
            if score > best_score:
                best_score = score
                best_canon = canon
        
        if best_score > 85:
            if not mapa or mapa[-1]['canonico'] != best_canon:
                mapa.append({'canonico': best_canon, 'titulo_encontrado': l_strip, 'linha_inicio': idx})
    
    mapa.sort(key=lambda x: x['linha_inicio'])
    return mapa

def obter_dados_secao(secao_canonico, mapa, linhas):
    idx = -1
    for i, m in enumerate(mapa):
        if m['canonico'] == secao_canonico: idx = i; break
    if idx == -1: return False, None, ""
    
    info = mapa[idx]
    inicio = info['linha_inicio'] + 1
    fim = mapa[idx+1]['linha_inicio'] if idx+1 < len(mapa) else len(linhas)
    
    conteudo = "\n".join(linhas[inicio:fim]).strip()
    return True, info['titulo_encontrado'], f"{info['titulo_encontrado']}\n\n{conteudo}" if conteudo else info['titulo_encontrado']

# ----------------- ORTOGRAFIA E MARCAÇÃO -----------------
def marcar_diferencas(ref, bel, eh_ref):
    def tok(t): return re.findall(r'\n|[A-Za-z0-9_À-ÿ]+|[^\w\s]', t or "")
    def n(t): return normalizar_texto(t) if re.match(r'[A-Za-z0-9_À-ÿ]+$', t) else t
    
    t1, t2 = tok(ref), tok(bel)
    n1, n2 = [n(t) for t in t1], [n(t) for t in t2]
    
    matcher = difflib.SequenceMatcher(None, n1, n2, autojunk=False)
    indices = set()
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != 'equal': indices.update(range(i1, i2) if eh_ref else range(j1, j2))
        
    tokens = t1 if eh_ref else t2
    out = []
    for i, t in enumerate(tokens):
        if i in indices and t.strip(): out.append(f"<mark style='background-color:#ffff99;padding:2px;'>{t}</mark>")
        else: out.append(t)
        
    res = ""
    for i, t in enumerate(out):
        if i == 0: res += t; continue
        prev_raw = re.sub(r'<[^>]+>', '', out[i-1])
        curr_raw = re.sub(r'<[^>]+>', '', t)
        if not re.match(r'^[.,;:!?)\\]$', curr_raw) and curr_raw != '\n' and prev_raw != '\n':
            res += " " + t
        else: res += t
    return re.sub(r"(</mark>)\s+(<mark[^>]*>)", " ", res)

def checar_ortografia(texto, ref):
    if not nlp or not texto: return []
    try:
        ignorar = {"alair", "belfar", "peticionamento", "urotrobel", "contato", "iobeguane"}
        vocab_ref = set(re.findall(r'\b[a-záéíóúâêôãõçü]+\b', ref.lower()))
        doc = nlp(texto)
        ents = {e.text.lower() for e in doc.ents}
        vocab_final = vocab_ref.union(ents).union(ignorar)
        
        spell = SpellChecker(language='pt')
        spell.word_frequency.load_words(vocab_final)
        
        palavras = re.findall(r'\b[a-záéíóúâêôãõçü]+\b', texto.lower())
        return list(sorted(set([e for e in spell.unknown(palavras) if len(e) > 3])))[:20]
    except: return []

def aplicar_marcas_ort(html, erros):
    if not erros: return html
    import html as hlib
    regex = r'\b(' + '|'.join(re.escape(e) for e in erros) + r')\b'
    parts = re.split(r'(<[^>]+>)', html)
    final = []
    for p in parts:
        if p.startswith('<'): final.append(p)
        else:
            final.append(re.sub(regex, lambda m: f"<mark style='background-color:#ffcccb;border:1px dashed red;'>{m.group(1)}</mark>", hlib.unescape(p), flags=re.I))
    return "".join(final)

# ----------------- COMPARAÇÃO E RELATÓRIO -----------------
def validar_paciente(txt):
    tn = normalizar_texto(txt)
    # Termos de bula profissional que PROIBEM
    if any(t in tn for t in ["resultados de eficacia", "propriedades farmacocinetica", "posologia e modo de usar"]):
        return False
    # Termos de bula paciente OBRIGATÓRIOS (pelo menos 2)
    ct = sum(1 for t in ["como este medicamento funciona", "o que devo saber antes de usar", "onde como e por quanto tempo"] if t in tn)
    return ct >= 1

def formatar_leitura(html, numerar=True):
    if not html: return ""
    try:
        validos = {normalizar_titulo_para_comparacao(s) for s in obter_secoes_por_tipo("Paciente")}
        validos.update(normalizar_titulo_para_comparacao(a) for a in obter_aliases_secao())
    except: validos = set()

    style_h = "font-family:'Georgia';font-weight:700;font-size:16px;margin-top:16px;margin-bottom:12px;color:#0b5686;"
    lines = html.split('\n')
    out = []
    
    for ln in lines:
        ls = ln.strip()
        if not ls: 
            out.append(""); continue
        
        txt_raw = re.sub(r'<[^>]+>', '', ls).strip()
        is_title = False
        if txt_raw:
            norm = normalizar_titulo_para_comparacao(txt_raw)
            if norm in validos: is_title = True
            elif is_titulo_secao(txt_raw):
                # Fuzzy check
                for v in validos:
                    if fuzz.ratio(norm, v) > 85: is_title = True; break
        
        if is_title:
            color = "#000000" if "#ffff99" in ls else "#0b5686"
            # Remove spaces/newlines inside title
            clean_title = re.sub(r'\s+', ' ', ls.replace('\n', ' ').replace('<br>', ' '))
            if not numerar: # Se quisesse remover numeros (não é o caso agora)
                clean_title = re.sub(r'^\s*(\d+\s*[\.\-)]*\s*)', '', clean_title)
            out.append(f"<div style='{style_h}color:{color};'>{clean_title}</div>")
        else:
            out.append(ls)
            
    final = "<br>".join(out)
    return re.sub(r'(<br\s*/?>\s*){3,}', '<br><br>', final) # Limpa excesso de BR

def gerar_relatorio(ref, bel, nome_ref, nome_bel):
    st.header("Relatório de Auditoria Inteligente")
    secoes = obter_secoes_por_tipo("Paciente")
    
    # Processamento
    l_ref = ref.split('\n')
    l_bel = bel.split('\n')
    m_ref = mapear_secoes(ref, secoes)
    m_bel = mapear_secoes(bel, secoes)
    
    data_comp = []
    missing = []
    sim_scores = []
    ignorar = [s.upper() for s in obter_secoes_ignorar_comparacao()]
    
    # Identificar títulos diferentes
    tit_ref = {m['canonico']: m['titulo_encontrado'] for m in m_ref}
    tit_bel = {m['canonico']: m['titulo_encontrado'] for m in m_bel}
    diff_titles = set()
    for k, v in tit_ref.items():
        if k in tit_bel and normalizar_titulo_para_comparacao(v) != normalizar_titulo_para_comparacao(tit_bel[k]):
            diff_titles.add(k)

    for sec in secoes:
        er, tr, cr = obter_dados_secao(sec, m_ref, l_ref)
        eb, tb, cb = obter_dados_secao(sec, m_bel, l_bel)
        
        if not eb: 
            missing.append(sec)
            data_comp.append({'secao': sec, 'status': 'faltante', 'cr': cr, 'cb': ""})
            continue
            
        status = 'identica'
        if sec.upper() not in ignorar:
            if sec in diff_titles or normalizar_texto(cr) != normalizar_texto(cb):
                status = 'diferente'
                sim_scores.append(0)
            else: sim_scores.append(100)
        
        data_comp.append({'secao': sec, 'status': status, 'cr': cr, 'cb': cb})

    # Ortografia e Data Anvisa
    erros = checar_ortografia(bel, ref)
    score = sum(sim_scores)/len(sim_scores) if sim_scores else 100
    
    # Regex Data ANVISA Blindado
    rx_anvisa = r"((?:aprovad[ao][\s\n]+pela[\s\n]+anvisa[\s\n]+em|data[\s\n]+de[\s\n]+aprova\w+[\s\n]+na[\s\n]+anvisa:)[\s\n]*([\d]{1,2}\s*/\s*[\d]{1,2}\s*/\s*[\d]{2,4}))"
    
    m_dt_ref = re.search(rx_anvisa, ref, re.I | re.DOTALL)
    m_dt_bel = re.search(rx_anvisa, bel, re.I | re.DOTALL)
    dt_ref_txt = m_dt_ref.group(2).replace('\n', '') if m_dt_ref else "N/A"
    
    # Dashboard
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Conformidade", f"{score:.0f}%")
    c2.metric("Erros Ortográficos", len(erros))
    c3.metric("Data ANVISA (Ref)", dt_ref_txt)
    c4.metric("Faltantes", len(missing))
    
    st.divider()
    if missing: st.error(f"Seções Faltantes: {', '.join(missing)}")
    else: st.success("Todas seções presentes")
    
    # Highlights setup
    tag_azul = "<mark style='background-color:#DDEEFF;border:1px solid blue;padding:1px;'>"
    ph_start, ph_end = "__AZ_S__", "__AZ_E__"
    
    # Expander logic
    style_box = "height:350px;overflow-y:auto;border:2px solid #ccc;padding:10px;background:#fff;font-family:'Georgia';line-height:1.6;"
    
    for item in data_comp:
        sec = item['secao']
        st_code = item['status']
        cr, cb = item['cr'], item['cb']
        
        # 1. Highlight Amarelo
        if st_code == 'diferente':
            hr = marcar_diferencas(cr, cb, True)
            hb = marcar_diferencas(cr, cb, False)
        else: hr, hb = cr, cb
        
        # 2. Highlight Azul (ANVISA)
        hr = re.sub(rx_anvisa, f"{ph_start}\\1{ph_end}", hr, flags=re.I|re.DOTALL)
        hb = re.sub(rx_anvisa, f"{ph_start}\\1{ph_end}", hb, flags=re.I|re.DOTALL)
        
        # 3. Highlight Vermelho (Ortografia - só no bel)
        hb = aplicar_marcas_ort(hb, erros)
        
        # 4. Swap placeholders
        hr = hr.replace(ph_start, tag_azul).replace(ph_end, "</mark>")
        hb = hb.replace(ph_start, tag_azul).replace(ph_end, "</mark>")
        
        # 5. Format HTML
        html_r = formatar_leitura(hr, True)
        html_b = formatar_leitura(hb, True)
        
        label = f"📄 {sec} - {'❌ DIVERGENTE' if st_code=='diferente' else '✅ IDÊNTICO'}"
        with st.expander(label):
            c1, c2 = st.columns(2)
            with c1: st.markdown(f"**ANVISA**<div style='{style_box}'>{html_r}</div>", unsafe_allow_html=True)
            with c2: st.markdown(f"**MKT**<div style='{style_box}'>{html_b}</div>", unsafe_allow_html=True)
            
    if erros: st.info(f"Erros: {', '.join(erros)}")
    
    st.divider()
    st.subheader("Visualização Lado a Lado")
    
    # Full view generation (reusing logic)
    # Aplica placeholder no texto bruto
    full_ref_ph = re.sub(rx_anvisa, f"{ph_start}\\1{ph_end}", ref, flags=re.I|re.DOTALL)
    full_bel_ph = re.sub(rx_anvisa, f"{ph_start}\\1{ph_end}", bel, flags=re.I|re.DOTALL)
    
    # Marca diferenças no texto completo usando o dicionario de problemas
    # Para simplificar aqui, marcamos diff apenas onde mapeamos erro antes? 
    # Melhor: reconstruir html das seções
    
    # (Simplificação para visualização completa robusta)
    full_html_r = ""
    full_html_b = ""
    for item in data_comp:
        # Recalcula marks locais (já feito acima, reutilizar seria ideal mas loop simples resolve)
        st_code = item['status']
        cr, cb = item['cr'], item['cb']
        if st_code == 'diferente':
            hr_s = marcar_diferencas(cr, cb, True)
            hb_s = marcar_diferencas(cr, cb, False)
        else: hr_s, hb_s = cr, cb
        
        full_html_r += hr_s + "\n\n"
        full_html_b += hb_s + "\n\n"
        
    # Aplica Azul e Vermelho no Full
    full_html_r = re.sub(rx_anvisa, f"{ph_start}\\1{ph_end}", full_html_r, flags=re.I|re.DOTALL)
    full_html_b = re.sub(rx_anvisa, f"{ph_start}\\1{ph_end}", full_html_b, flags=re.I|re.DOTALL)
    full_html_b = aplicar_marcas_ort(full_html_b, erros)
    
    full_html_r = full_html_r.replace(ph_start, tag_azul).replace(ph_end, "</mark>")
    full_html_b = full_html_b.replace(ph_start, tag_azul).replace(ph_end, "</mark>")
    
    final_view_r = formatar_leitura(full_html_r, True)
    final_view_b = formatar_leitura(full_html_b, True)
    
    style_full = "height:700px;overflow-y:auto;border:1px solid #ddd;padding:20px;background:#fff;box-shadow:0 4px 12px rgba(0,0,0,0.08);"
    c1, c2 = st.columns(2, gap="large")
    with c1: st.markdown(f"**{nome_ref}**<div style='{style_full}'>{final_view_r}</div>", unsafe_allow_html=True)
    with c2: st.markdown(f"**{nome_bel}**<div style='{style_full}'>{final_view_b}</div>", unsafe_allow_html=True)

# ----------------- MAIN -----------------
st.set_page_config(layout="wide", page_title="Auditoria de Bulas", page_icon="🔬")
st.title("🔬 Inteligência Artificial para Auditoria de Bulas (v47)")
st.warning("⚠️ Módulo exclusivo para **Bula do Paciente**.")

c1, c2 = st.columns(2)
f_ref = c1.file_uploader("ANVISA (docx/pdf)", ["docx","pdf"])
f_bel = c2.file_uploader("MKT (pdf)", ["pdf"])

if st.button("🔍 Iniciar Auditoria", type="primary"):
    if f_ref and f_bel:
        with st.spinner("Processando..."):
            t_ref, e1 = extrair_texto(f_ref, 'docx' if f_ref.name.endswith('docx') else 'pdf', False)
            t_bel, e2 = extrair_texto(f_bel, 'pdf', True)
            
            if e1 or e2: st.error(f"Erro: {e1 or e2}")
            elif not validar_paciente(t_ref) or not validar_paciente(t_bel):
                st.error("⛔ Bloqueio: Um dos arquivos não parece ser Bula do Paciente.")
            else:
                # [Aplicação da Nova Lógica v47]
                t_ref = reconstruir_paragrafos(t_ref)
                t_ref = truncar_apos_anvisa(t_ref)
                
                t_bel = reconstruir_paragrafos(t_bel)
                t_bel = truncar_apos_anvisa(t_bel)
                
                gerar_relatorio(t_ref, t_bel, f_ref.name, f_bel.name)
    else: st.warning("Envie ambos os arquivos.")
