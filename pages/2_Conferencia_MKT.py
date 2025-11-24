# pages/2_Conferencia_MKT.py
#
# Versão v49 - "O Retorno do Rei" (Visual Clássico + Correção MKT)
# - VISUAL: Restaurado CSS e classes (.ref-title, .bel-title) das versões v42/v45.
# - BUGFIX: Corrigido erro onde tags HTML apareciam escritas na tela.
# - FUNCIONALIDADE: Mantida a função `reconstruir_paragrafos` para o MKT não ficar enxuto.
# - FUNCIONALIDADE: Mantido bloqueio de Bula Profissional.

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

# ----------------- UI / CSS (O CLÁSSICO) -----------------
st.set_page_config(layout="wide", page_title="Auditoria de Bulas", page_icon="🔬")
GLOBAL_CSS = """
<style>
/* Esconder elementos Streamlit padrao */
[data-testid="stHeader"] { display: none !important; }
footer { display: none !important; }

/* Container visual global */
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
  margin: 12px 0 8px;
  padding-top: 8px;
  border-top: 1px solid #eee;
}

/* Cores específicas dos Títulos (Visual Antigo) */
.ref-title { color: #0b5686; } /* Azul Anvisa */
.bel-title { color: #0b8a3e; } /* Verde Belfar */

/* Estilos de destaque */
mark.diff { background-color: #ffff99; padding: 0 2px; color: black; }
mark.ort { background-color: #ffdfd9; padding: 0 2px; color: black; border-bottom: 1px dashed red; }
mark.anvisa { background-color: #DDEEFF; padding: 0 2px; color: black; border: 1px solid #0000FF; }

.stExpander > div[role="button"] { font-weight: 700; color: #333; }
.small-muted { color:#666; font-size:12px; }
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
                        # Margens (igual v45)
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

            linhas_temp = texto.split('\n')
            linhas_filtradas_info = []
            for linha in linhas_temp:
                l_up = linha.upper().strip()
                if re.match(r'^\s*INFORMA[ÇC][OÕ]ES\s+(AO|PARA(\s+O)?)\s+PACIENTE.*', l_up): continue
                if re.match(r'^\s*BULA\s+PARA\s+(O\s+)?PACIENTE.*', l_up): continue
                linhas_filtradas_info.append(linha)
            texto = '\n'.join(linhas_filtradas_info)

            # Ruídos (igual v45)
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
                texto = re.sub(r'(?m)^\s*\d{1,2}\.\s*', '', texto)

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
    if re.match(r'^\d+\s*[\.\-)]*\s+[A-ZÁÉÍÓÚÂÊÔÃÕÇ]', first_line): return True
    if first_line.isupper() and not first_line.endswith('.'): return True
    return False

# ----------------- RECONSTRUÇÃO DE PARÁGRAFOS (ESSA FICA!) -----------------
def reconstruir_paragrafos(texto):
    """
    Pega o texto que está quebrado linha a linha (MKT) e junta em parágrafos.
    Isso é o que faz o texto 'ir até o fim' da caixa.
    """
    if not texto: return ""
    linhas = texto.split('\n')
    linhas_reconstruidas = []
    buffer = ""
    for linha in linhas:
        linha = linha.strip()
        if not linha:
            if buffer:
                linhas_reconstruidas.append(buffer); buffer = ""
            if linhas_reconstruidas and linhas_reconstruidas[-1] != "":
                linhas_reconstruidas.append("")
            continue
        if is_titulo_secao(linha):
            if buffer:
                linhas_reconstruidas.append(buffer); buffer = ""
            linhas_reconstruidas.append(linha)
            continue
        if buffer:
            if buffer.endswith('-'):
                buffer = buffer[:-1] + linha
            elif not buffer.endswith(('.', ':', '!', '?')):
                buffer += " " + linha
            else:
                linhas_reconstruidas.append(buffer); buffer = linha
        else:
            buffer = linha
    if buffer: linhas_reconstruidas.append(buffer)
    texto_final = "\n".join(linhas_reconstruidas)
    return re.sub(r'\n{2,}', '\n\n', texto_final)

# ----------------- CONFIGURAÇÃO DE SEÇÕES -----------------
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
    titulos_possiveis = {normalizar_titulo_para_comparacao(s): s for s in secoes_esperadas}
    for alias, canon in aliases.items():
        if canon in secoes_esperadas:
            titulos_possiveis[normalizar_titulo_para_comparacao(alias)] = canon
    for idx, linha in enumerate(linhas):
        l_strip = linha.strip()
        if not l_strip or not is_titulo_secao(l_strip): continue
        norm = normalizar_titulo_para_comparacao(l_strip)
        best_score = 0; best_canon = None
        for t_norm, canon in titulos_possiveis.items():
            score = fuzz.token_set_ratio(t_norm, norm)
            if score > best_score: best_score = score; best_canon = canon
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
    return True, info['titulo_encontrado'], f"{conteudo}" if conteudo else ""

# ----------------- HELPERS DE QUALIFIERS -----------------
def _extrair_linhas_qualificadoras_iniciais(texto, max_lines=4):
    if not texto: return [], texto
    linhas = texto.split('\n'); qualifiers = []; i = 0
    while i < min(len(linhas), max_lines):
        ln = linhas[i].strip(); ln_up = ln.upper()
        if not ln: i += 1; continue
        if 'USO NASAL' in ln_up and 'ADULTO' in ln_up:
            qualifiers.append(ln); i += 1; continue
        if 'USO NASAL' in ln_up and i+1 < len(linhas) and 'ADULTO' in linhas[i+1].upper():
            qualifiers.append(ln); qualifiers.append(linhas[i+1].strip()); i += 2; continue
        break
    return qualifiers, '\n'.join(linhas[i:]).strip()

def realocar_qualifiers_inplace(conteudos, src_section='COMPOSIÇÃO', dst_section='APRESENTAÇÕES'):
    src = conteudos.get(src_section); dst = conteudos.get(dst_section)
    if not src or not dst or not src.get('cb', "").strip() or not dst.get('eb', False): return
    qualifiers_bel, restante_bel = _extrair_linhas_qualificadoras_iniciais(src['cb'], max_lines=4)
    if not qualifiers_bel: return
    qual_text = ' '.join(q for q in qualifiers_bel if q.strip())
    if not qual_text or re.search(r'\b(?:cont[eé]m|mg\b|ml\b|equivalente|q\.s\.p|qsp)\b', qual_text, re.I): return
    if len(restante_bel.strip()) < 30: return
    dst_norm = normalizar_texto(dst.get('cb', ""))
    if normalizar_texto(qual_text) in dst_norm: src['cb'] = restante_bel; return
    dst['cb'] = f"{qual_text}\n\n{dst['cb']}".strip()
    src['cb'] = restante_bel

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
        if i in indices and t.strip(): out.append(f"<mark class='diff'>{t}</mark>")
        else: out.append(t)
    res = ""
    for i, t in enumerate(out):
        if i == 0: res += t; continue
        prev = re.sub(r'<[^>]+>', '', out[i-1]); curr = re.sub(r'<[^>]+>', '', t)
        if not re.match(r'^[.,;:!?)\\]$', curr) and curr != '\n' and prev != '\n': res += " " + t
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
        else: final.append(re.sub(regex, lambda m: f"<mark class='ort'>{m.group(1)}</mark>", hlib.unescape(p), flags=re.I))
    return "".join(final)

# ----------------- CONSTRUÇÃO HTML (O RETORNO DO CLÁSSICO) -----------------
# Essa função volta a usar as classes CSS (.section-title, .ref-title)
# e não mais estilos inline dinâmicos, o que resolve o bug da visualização.

def construir_html_secoes(dados_secao, nome_secao, eh_referencia, aplicar_numeracao=True):
    # Recupera o título correto
    titulo = dados_secao['tr'] if eh_referencia else dados_secao['tb']
    conteudo = dados_secao['cr'] if eh_referencia else dados_secao['cb']
    
    # Se não tiver título capturado, usa o nome da seção
    if not titulo: titulo = nome_secao
    
    # Remove numeração se solicitado (para ficar limpo se necessario)
    # Mas no seu caso, MKT precisa numerar, entao deixamos padrão True.
    
    # Define a classe de cor baseada no tipo (Azul ou Verde)
    classe_titulo = "ref-title" if eh_referencia else "bel-title"
    
    html = f"<div class='section-title {classe_titulo}'>{titulo}</div>"
    
    # Tratamento de quebras de linha para HTML
    conteudo_html = conteudo.replace("\n", "<br>")
    
    html += f"<div>{conteudo_html}</div>"
    return html

# ----------------- COMPARAÇÃO E RELATÓRIO -----------------
def validar_paciente(txt):
    tn = normalizar_texto(txt)
    if any(t in tn for t in ["resultados de eficacia", "propriedades farmacocinetica", "posologia e modo de usar"]): return False
    ct = sum(1 for t in ["como este medicamento funciona", "o que devo saber antes de usar", "onde como e por quanto tempo"] if t in tn)
    return ct >= 1

def gerar_relatorio(ref, bel, nome_ref, nome_bel):
    st.header("Relatório de Auditoria Inteligente")
    secoes = obter_secoes_por_tipo("Paciente")
    
    l_ref = ref.split('\n'); l_bel = bel.split('\n')
    m_ref = mapear_secoes(ref, secoes); m_bel = mapear_secoes(bel, secoes)
    
    conteudos = {}
    for sec in secoes:
        er, tr, cr = obter_dados_secao(sec, m_ref, l_ref)
        eb, tb, cb = obter_dados_secao(sec, m_bel, l_bel)
        conteudos[sec] = {'cr': cr, 'cb': cb, 'eb': eb, 'er': er, 'tr': tr, 'tb': tb} # Guardamos Títulos
    realocar_qualifiers_inplace(conteudos)

    data_comp = []
    missing = []
    sim_scores = []
    ignorar = [s.upper() for s in obter_secoes_ignorar_comparacao()]
    
    # Diff Títulos
    tit_ref = {m['canonico']: m['titulo_encontrado'] for m in m_ref}
    tit_bel = {m['canonico']: m['titulo_encontrado'] for m in m_bel}
    diff_titles = set()
    for k, v in tit_ref.items():
        if k in tit_bel and normalizar_titulo_para_comparacao(v) != normalizar_titulo_para_comparacao(tit_bel[k]):
            diff_titles.add(k)

    for sec in secoes:
        item = conteudos[sec]
        cr, cb, eb = item['cr'], item['cb'], item['eb']
        
        if not eb: 
            missing.append(sec)
            data_comp.append({'secao': sec, 'status': 'faltante', 'data': item})
            continue
            
        status = 'identica'
        if sec.upper() not in ignorar:
            if sec in diff_titles or normalizar_texto(cr) != normalizar_texto(cb):
                status = 'diferente'
                sim_scores.append(0)
            else: sim_scores.append(100)
        
        data_comp.append({'secao': sec, 'status': status, 'data': item})

    erros = checar_ortografia(bel, ref)
    score = sum(sim_scores)/len(sim_scores) if sim_scores else 100
    
    rx_anvisa = r"((?:aprovad[ao][\s\n]+pela[\s\n]+anvisa[\s\n]+em|data[\s\n]+de[\s\n]+aprova\w+[\s\n]+na[\s\n]+anvisa:)[\s\n]*([\d]{1,2}\s*/\s*[\d]{1,2}\s*/\s*[\d]{2,4}))"
    m_dt_ref = re.search(rx_anvisa, ref, re.I | re.DOTALL)
    dt_ref_txt = m_dt_ref.group(2).replace('\n', '') if m_dt_ref else "N/A"
    
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Conformidade", f"{score:.0f}%")
    c2.metric("Erros Ortográficos", len(erros))
    c3.metric("Data ANVISA (Ref)", dt_ref_txt)
    c4.metric("Faltantes", len(missing))
    
    st.divider()
    if missing: st.error(f"Seções Faltantes: {', '.join(missing)}")
    else: st.success("✅ Todas seções presentes")
    st.markdown("---")
    
    ph_start, ph_end = "__AZ_S__", "__AZ_E__"
    
    # ---------------- PREPARAÇÃO DO TEXTO COMPLETO (LADO A LADO) ----------------
    # Vamos construir o HTML completo concatenando as seções geradas
    html_full_ref = ""
    html_full_bel = ""

    for item_comp in data_comp:
        sec = item_comp['secao']
        st_code = item_comp['status']
        data = item_comp['data']
        
        cr, cb = data['cr'], data['cb']
        
        # Marcação Diff
        if st_code == 'diferente':
            hr = marcar_diferencas(cr, cb, True)
            hb = marcar_diferencas(cr, cb, False)
        else: hr, hb = cr, cb
        
        # Marcação Azul
        hr = re.sub(rx_anvisa, f"{ph_start}\\1{ph_end}", hr, flags=re.I|re.DOTALL)
        hb = re.sub(rx_anvisa, f"{ph_start}\\1{ph_end}", hb, flags=re.I|re.DOTALL)
        
        # Marcação Ortografia
        hb = aplicar_marcas_ort(hb, erros)
        
        # Substitui placeholders pelos SPANs (não style inline, classes CSS)
        hr = hr.replace(ph_start, "<mark class='anvisa'>").replace(ph_end, "</mark>")
        hb = hb.replace(ph_start, "<mark class='anvisa'>").replace(ph_end, "</mark>")
        
        # Atualiza o dicionário de dados processados para usar no Expander e no Full
        data['html_ref_final'] = hr
        data['html_bel_final'] = hb
        
        # Constrói o HTML usando o método CLÁSSICO (Divs com Classes)
        # Passamos 'data' que tem os títulos originais (tr, tb)
        # Mas passamos o 'hr/hb' já marcado como conteúdo
        dados_ref = data.copy(); dados_ref['cr'] = hr
        dados_bel = data.copy(); dados_bel['cb'] = hb
        
        chunk_ref = construir_html_secoes(dados_ref, sec, True)
        chunk_bel = construir_html_secoes(dados_bel, sec, False)
        
        html_full_ref += chunk_ref
        html_full_bel += chunk_bel
        
        # --- RENDERIZA O EXPANDER ---
        label = f"📄 {sec} - {'❌ DIVERGENTE' if st_code=='diferente' else '✅ IDÊNTICO'}"
        with st.expander(label):
            c1, c2 = st.columns(2)
            with c1: st.markdown(f"**ANVISA**<div class='bula-box'>{chunk_ref}</div>", unsafe_allow_html=True)
            with c2: st.markdown(f"**MKT**<div class='bula-box'>{chunk_bel}</div>", unsafe_allow_html=True)

    if erros: st.info(f"Erros: {', '.join(erros)}")
    
    st.divider()
    st.subheader("Visualização Lado a Lado")
    
    c1, c2 = st.columns(2, gap="large")
    with c1: st.markdown(f"**{nome_ref}**<div class='bula-box-full'>{html_full_ref}</div>", unsafe_allow_html=True)
    with c2: st.markdown(f"**{nome_bel}**<div class='bula-box-full'>{html_full_bel}</div>", unsafe_allow_html=True)

# ----------------- MAIN -----------------
st.title("🔬 Inteligência Artificial para Auditoria de Bulas (v49)")
st.warning("⚠️ Módulo exclusivo para **Bula do Paciente**.")

col1, col2 = st.columns(2)
with col1:
    st.subheader("📄 Arquivo ANVISA")
    f_ref = st.file_uploader("Envie o arquivo da Anvisa (.docx ou .pdf)", type=["docx", "pdf"], key="ref")
with col2:
    st.subheader("📄 Arquivo MKT")
    f_bel = st.file_uploader("Envie o PDF do Marketing", type="pdf", key="belfar")

if st.button("🔍 Iniciar Auditoria Completa", type="primary"):
    if f_ref and f_bel:
        with st.spinner("Processando..."):
            t_ref, e1 = extrair_texto(f_ref, 'docx' if f_ref.name.endswith('docx') else 'pdf', False)
            t_bel, e2 = extrair_texto(f_bel, 'pdf', True)
            
            if e1 or e2: st.error(f"Erro: {e1 or e2}")
            elif not validar_paciente(t_ref) or not validar_paciente(t_bel):
                st.error("⛔ Bloqueio: Um dos arquivos não parece ser Bula do Paciente.")
            else:
                # [MANTIDA CORREÇÃO DE QUEBRAS DE TÍTULO PARA ANVISA]
                t_ref = truncar_apos_anvisa(t_ref)
                
                # [MANTIDA CORREÇÃO DE PARÁGRAFOS PARA MKT]
                t_bel = reconstruir_paragrafos(t_bel) 
                t_bel = truncar_apos_anvisa(t_bel)
                
                gerar_relatorio(t_ref, t_bel, f_ref.name, f_bel.name)
    else: st.warning("Envie ambos os arquivos.")
