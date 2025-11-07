# --------------------------------------------------------------
#  Auditoria de Bulas – v26.8+ (Layout Lado a Lado + Marcações Inteligentes)
# --------------------------------------------------------------
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

# ====================== CONFIGURAÇÃO DA PÁGINA ======================
st.set_page_config(layout="wide", page_title="Auditoria de Bulas", page_icon="🔬")
hide_streamlit_UI = """
<style>
    [data-testid="stHeader"], [data-testid="main-menu-button"], footer,
    [data-testid="stStatusWidget"], [data-testid="stCreatedBy"], [data-testid="stHostedBy"] {
        display: none !important; visibility: hidden !important;
    }
</style>
"""
st.markdown(hide_streamlit_UI, unsafe_allow_html=True)

# ====================== ESTILO GLOBAL (CSS) ======================
CSS = """
<style>
    .container-scroll {
        max-height: 720px;
        overflow-y: auto;
        border: 2px solid #bbb;
        border-radius: 12px;
        padding: 24px 32px;
        background: #fafafa;
        font-family: 'Georgia', serif;
        font-size: 15px;
        line-height: 1.8;
        box-shadow: 0 4px 16px rgba(0,0,0,0.12);
        text-align: justify;
        margin-bottom: 20px;
        overflow-wrap: break-word;
        word-break: break-word;
    }
    .container-scroll::-webkit-scrollbar { width: 10px; }
    .container-scroll::-webkit-scrollbar-thumb { background: #999; border-radius: 5px; }

    mark.diff   { background:#ffff99; padding:2px 4px; border-radius:3px; }
    mark.spell  { background:#FFDDC1; padding:2px 4px; border-radius:3px; }
    mark.anvisa { background:#cce5ff; padding:2px 4px; border-radius:3px; font-weight:600; }

    .expander-box {
        height: 360px; overflow-y:auto; border:2px solid #d0d0d0; border-radius:6px;
        padding:14px; background:#fff; font-size:14px; line-height:1.7;
        overflow-wrap: break-word;
        word-break: break-word;
    }
    .clickable { cursor:pointer; transition:background 0.3s; }
    .clickable:hover { background:#f0f8ff !important; }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

# ====================== MODELO NLP ======================
@st.cache_resource
def carregar_modelo_spacy():
    try:
        return spacy.load("pt_core_news_lg")
    except OSError:
        st.error("Modelo 'pt_core_news_lg' não encontrado. `python -m spacy download pt_core_news_lg`")
        return None
nlp = carregar_modelo_spacy()

# ====================== EXTRAÇÃO (v26.8) ======================
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
                    for page in doc:
                        rect = page.rect
                        clip_esquerda = fitz.Rect(0, 0, rect.width / 2, rect.height)
                        clip_direita = fitz.Rect(rect.width / 2, 0, rect.width, rect.height)
                        texto_esquerda = page.get_text("text", clip=clip_esquerda, sort=True)
                        texto_direita = page.get_text("text", clip=clip_direita, sort=True)
                        full_text_list.append(texto_esquerda)
                        full_text_list.append(texto_direita)
                else:
                    for page in doc:
                        full_text_list.append(page.get_text("text", sort=True))
            texto = "\n\n".join(full_text_list)

        elif tipo_arquivo == 'docx':
            doc = docx.Document(arquivo)
            texto = "\n".join([p.text for p in doc.paragraphs])

        if texto:
            # Remover caracteres invisíveis
            invis = ['\u00AD', '\u200B', '\u200C', '\u200D', '\uFEFF']
            for c in invis: texto = texto.replace(c, '')
            texto = texto.replace('\r\n', '\n').replace('\r', '\n').replace('\u00A0', ' ')

            # Filtro de ruído (como solicitado)
            padrao_ruido = re.compile(
                r'lew Roman U|'
                r'\(31\) 3514-2900|'
                r'pp 190|'
                r'mm — >>>»|'
                r'a \?|'
                r'1º prova -|'
                r'la|'
                r'KH 190 r|'
                r'BUL.*|'
                r'FRENTE|'
                r'VERSO|'
                r'Times New Roman|'
                r'Papel.*|'
                r'Cor.*|'
                r'Contato.*|'
                r'artes@belfar\.com\.br',
                re.IGNORECASE
            )
            linhas = [ln for ln in texto.split('\n') if not padrao_ruido.search(ln.strip())]
            texto = "\n".join(linhas)
            texto = re.sub(r'\n{3,}', '\n\n', texto)
            texto = re.sub(r'[ \t]+', ' ', texto).strip()

        return texto, None
    except Exception as e:
        return "", f"Erro ao ler o arquivo {tipo_arquivo}: {e}"

# ====================== TRUNCAR APÓS ANVISA (v26.8) ======================
def truncar_apos_anvisa(texto):
    if not isinstance(texto, str): return texto
    regex_anvisa = r"((?:aprovad[ao]\s+pela\s+anvisa\s+em|data\s+de\s+aprova\w+\s+na\s+anvisa:)\s*([\d]{1,2}\s*/\s*[\d]{1,2}\s*/\s*[\d]{2,4}))"
    match = re.search(regex_anvisa, texto, re.IGNORECASE)
    if not match: return texto
    cut_off = match.end(1)
    pos_ponto = re.search(r'^\s*\.', texto[cut_off:], re.IGNORECASE)
    if pos_ponto: cut_off += pos_ponto.end()
    return texto[:cut_off]

# ====================== SEÇÕES ======================
def obter_secoes_por_tipo(tipo_bula):
    secoes = {
        "Paciente": [
            "APRESENTAÇÕES", "COMPOSIÇÃO",
            "1. PARA QUE ESTE MEDICAMENTO É INDICADO?",
            "2. COMO ESTE MEDICAMENTO FUNCIONA?",
            "3. QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?",
            "4. O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?",
            "5. ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?",
            "6. COMO DEVO USAR ESTE MEDICAMENTO?",
            "7. O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?",
            "8. QUAIS OS MALES QUE ESTE MEDICAMENTO PODE ME CAUSAR?",
            "9. O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?",
            "DIZERES LEGAIS"
        ],
        "Profissional": [
            "APRESENTAÇÕES", "COMPOSIÇÃO",
            "1. INDICAÇÕES", "2. RESULTADOS DE EFICÁCIA",
            "3. CARACTERÍSTICAS FARMACOLÓGICAS", "4. CONTRAINDICAÇÕES",
            "5. ADVERTÊNCIAS E PRECAUÇÕES", "6. INTERAÇÕES MEDICAMENTOSAS",
            "7. CUIDADOS DE ARMAZENAMENTO DO MEDICAMENTO", "8. POSOLOGIA E MODO DE USAR",
            "9. REAÇÕES ADVERSAS", "10. SUPERDOSE", "DIZERES LEGAIS"
        ]
    }
    return secoes.get(tipo_bula, [])

def obter_aliases_secao():
    return {
        "PARA QUE ESTE MEDICAMENTO É INDICADO?": "1. PARA QUE ESTE MEDICAMENTO É INDICADO?",
        "COMO ESTE MEDICAMENTO FUNCIONA?": "2. COMO ESTE MEDICAMENTO FUNCIONA?",
        "QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?": "3. QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?",
        "O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?": "4. O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?",
        "ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?": "5. ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?",
        "COMO DEVO USAR ESTE MEDICAMENTO?": "6. COMO DEVO USAR ESTE MEDICAMENTO?",
        "O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?": "7. O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?",
        "QUAIS OS MALES QUE ESTE MEDICAMENTO PODE ME CAUSAR?": "8. QUAIS OS MALES QUE ESTE MEDICAMENTO PODE ME CAUSAR?",
        "O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?": "9. O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?",
        "INDICAÇÕES": "1. INDICAÇÕES", "RESULTADOS DE EFICÁCIA": "2. RESULTADOS DE EFICÁCIA",
        "CARACTERÍSTICAS FARMACOLÓGICAS": "3. CARACTERÍSTICAS FARMACOLÓGICAS",
        "CONTRAINDICAÇÕES": "4. CONTRAINDICAÇÕES", "ADVERTÊNCIAS E PRECAUÇÕES": "5. ADVERTÊNCIAS E PRECAUÇÕES",
        "INTERAÇÕES MEDICAMENTOSAS": "6. INTERAÇÕES MEDICAMENTOSAS",
        "CUIDADOS DE ARMAZENAMENTO DO MEDICAMENTO": "7. CUIDADOS DE ARMAZENAMENTO DO MEDICAMENTO",
        "POSOLOGIA E MODO DE USAR": "8. POSOLOGIA E MODO DE USAR",
        "REAÇÕES ADVERSAS": "9. REAÇÕES ADVERSAS", "SUPERDOSE": "10. SUPERDOSE"
    }

def obter_secoes_ignorar_ortografia(): return ["COMPOSIÇÃO", "DIZERES LEGAIS"]
def obter_secoes_ignorar_comparacao(): return []

# ====================== NORMALIZAÇÃO ======================
def normalizar_texto(texto):
    if not isinstance(texto, str): return ""
    texto = ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')
    texto = re.sub(r'[^\w\s]', '', texto)
    return ' '.join(texto.split()).lower()

def normalizar_titulo_para_comparacao(texto):
    texto_norm = normalizar_texto(texto)
    return re.sub(r'^\d+\s*[\.\-)]*\s*', '', texto_norm).strip()

# ====================== CORREÇÃO DE TÍTULOS BELFAR ======================
def corrigir_quebras_em_titulos(texto):
    linhas = texto.split("\n")
    linhas_corrigidas = []
    buffer = ""
    for linha in linhas:
        linha_strip = linha.strip()
        if not linha_strip: continue
        if linha_strip.isupper() and len(linha_strip) < 60:
            buffer += (" " + linha_strip) if buffer else linha_strip
        else:
            if buffer: linhas_corrigidas.append(buffer); buffer = ""
            linhas_corrigidas.append(linha_strip)
    if buffer: linhas_corrigidas.append(buffer)
    return "\n".join(linhas_corrigidas)

# ====================== MAPEAMENTO DE SEÇÕES ======================
def is_titulo_secao(linha):
    linha = linha.strip()
    if len(linha) < 4 or len(linha) > 100 or linha.endswith(('.', ':')): return False
    if re.match(r'^\d+\.\s+[A-Z]', linha) or linha.isupper(): return True
    return False

def mapear_secoes(texto_completo, secoes_esperadas):
    mapa = []
    linhas = texto_completo.split('\n')
    aliases = obter_aliases_secao()
    titulos_possiveis = {s: s for s in secoes_esperadas}
    for alias, canonico in aliases.items():
        if canonico in secoes_esperadas: titulos_possiveis[alias] = canonico
    titulos_norm_lookup = {normalizar_titulo_para_comparacao(t): c for t, c in titulos_possiveis.items()}
    limiar = 85

    for idx, linha in enumerate(linhas):
        linha_limpa = linha.strip()
        if not is_titulo_secao(linha_limpa): continue
        norm_linha = normalizar_titulo_para_comparacao(linha_limpa)
        best_score, best_canonico = 0, None
        for titulo_norm, canonico in titulos_norm_lookup.items():
            score = fuzz.token_set_ratio(titulo_norm, norm_linha)
            if score > best_score:
                best_score, best_canonico = score, canonico
        if best_score >= limiar and (not mapa or mapa[-1]['canonico'] != best_canonico):
            mapa.append({
                'canonico': best_canonico,
                'titulo_encontrado': linha_limpa,
                'linha_inicio': idx,
                'score': best_score,
                'num_linhas_titulo': 1
            })
    mapa.sort(key=lambda x: x['linha_inicio'])
    return mapa

def obter_dados_secao(secao_canonico, mapa_secoes, linhas_texto):
    idx_secao = next((i for i, m in enumerate(mapa_secoes) if m['canonico'] == secao_canonico), -1)
    if idx_secao == -1: return False, None, ""
    info = mapa_secoes[idx_secao]
    inicio = info['linha_inicio'] + info.get('num_linhas_titulo', 1)
    fim = len(linhas_texto)
    if idx_secao + 1 < len(mapa_secoes):
        fim = mapa_secoes[idx_secao + 1]['linha_inicio']
    conteudo = "\n".join(linhas_texto[inicio:fim]).strip()
    return True, info['titulo_encontrado'], conteudo

# ====================== COMPARAÇÃO ======================
def verificar_secoes_e_conteudo(texto_ref, texto_belfar, tipo_bula):
    secoes_esperadas = obter_secoes_por_tipo(tipo_bula)
    relatorio = []
    similaridade_geral = []
    linhas_ref = texto_ref.split('\n')
    linhas_belfar = texto_belfar.split('\n')
    mapa_ref = mapear_secoes(texto_ref, secoes_esperadas)
    mapa_belfar = mapear_secoes(texto_belfar, secoes_esperadas)

    for secao in secoes_esperadas:
        encontrou_ref, _, conteudo_ref = obter_dados_secao(secao, mapa_ref, linhas_ref)
        encontrou_belfar, titulo_belfar, conteudo_belfar = obter_dados_secao(secao, mapa_belfar, linhas_belfar)

        if not encontrou_belfar:
            relatorio.append({'secao': secao, 'status': 'faltante', 'conteudo_ref': conteudo_ref, 'conteudo_belfar': ""})
            continue

        if encontrou_ref and encontrou_belfar:
            if normalizar_texto(conteudo_ref) != normalizar_texto(conteudo_belfar):
                relatorio.append({'secao': secao, 'status': 'diferente', 'conteudo_ref': conteudo_ref, 'conteudo_belfar': conteudo_belfar})
                similaridade_geral.append(0)
            else:
                relatorio.append({'secao': secao, 'status': 'identica', 'conteudo_ref': conteudo_ref, 'conteudo_belfar': conteudo_belfar})
                similaridade_geral.append(100)

    return relatorio, similaridade_geral

# ====================== ORTOGRAFIA ======================
def checar_ortografia_inteligente(texto_belfar, texto_ref, tipo_bula):
    if not nlp or not texto_belfar: return []
    try:
        secoes_ignorar = obter_secoes_ignorar_ortografia()
        secoes_todas = obter_secoes_por_tipo(tipo_bula)
        mapa = mapear_secoes(texto_belfar, secoes_todas)
        linhas = texto_belfar.split('\n')
        texto_filtrado = []
        for secao in secoes_todas:
            if secao.upper() in [s.upper() for s in secoes_ignorar]: continue
            ok, _, c = obter_dados_secao(secao, mapa, linhas)
            if ok and c: texto_filtrado.append(c)
        texto_final = '\n'.join(texto_filtrado)
        if not texto_final: return []

        spell = SpellChecker(language='pt')
        vocab_ref = set(re.findall(r'\b[a-záéíóúâêôãõçü]+\b', texto_ref.lower()))
        doc = nlp(texto_belfar)
        entidades = {ent.text.lower() for ent in doc.ents}
        spell.word_frequency.load_words(vocab_ref.union(entidades).union({"alair", "belfar", "escopolamina", "dipirona", "butilbrometo"}))
        palavras = re.findall(r'\b[a-záéíóúâêôãõçü]+\b', texto_final.lower())
        erros = spell.unknown(palavras)
        return list(sorted({e for e in erros if len(e) > 3}))[:20]
    except: return []

# ====================== MARCAÇÃO PALAVRA A PALAVRA ======================
def marcar_diferencas_palavra_por_palavra(texto_ref, texto_belfar, eh_ref):
    def tokenizar(txt): return re.findall(r'\n|[A-Za-zÀ-ÖØ-öø-ÿ0-9_]+|[^\w\s]', txt, re.UNICODE)
    def norm(tok): return normalizar_texto(tok) if re.match(r'[A-Za-zÀ-ÖØ-öø-ÿ0-9_]+$', tok) else tok
    ref_tokens = tokenizar(texto_ref)
    bel_tokens = tokenizar(texto_belfar)
    ref_norm = [norm(t) for t in ref_tokens]
    bel_norm = [norm(t) for t in bel_tokens]
    matcher = difflib.SequenceMatcher(None, ref_norm, bel_norm, autojunk=False)
    indices = set()
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != 'equal': indices.update(range(i1, i2) if eh_ref else range(j1, j2))
    tokens = ref_tokens if eh_ref else bel_tokens
    marcado = []
    for idx, tok in enumerate(tokens):
        if idx in indices and tok.strip(): marcado.append(f"<mark class='diff'>{tok}</mark>")
        else: marcado.append(tok)
    resultado = ""
    for i, tok in enumerate(marcado):
        raw = re.sub(r'^<mark[^>]*>|</mark>$', '', tok)
        if i == 0: resultado += tok; continue
        prev_raw = re.sub(r'^<mark[^>]*>|</mark>$', '', marcado[i-1])
        if raw in ".,;:!?)" or raw == "\n" or prev_raw == "\n" or prev_raw in "([": resultado += tok
        else: resultado += " " + tok
    resultado = re.sub(r"(</mark>)\s+(<mark[^>]*>)", " ", resultado)
    return resultado

# ====================== FORMATAÇÃO PARA LEITURA ======================
def formatar_html_para_leitura(html_content):
    if not html_content: return ""
    html_content = re.sub(r'\n{2,}', '[[PARAGRAPH]]', html_content)
    html_content = re.sub(r'\n([A-Z\s]{4,100})\n', r'[[PARAGRAPH]]\1[[PARAGRAPH]]', html_content)
    html_content = re.sub(r'(\n)(\d+\.\s+[A-Z])', r'[[PARAGRAPH]]\2', html_content)
    titulos_finais = "|".join(["DIZERES LEGAIS", "IDENTIFICAÇÃO DO MEDICAMENTO", "INFORMAÇÕES AO PACIENTE"])
    html_content = re.sub(rf'(\n)({titulos_finais})', r'[[PARAGRAPH]]\2', html_content)
    html_content = re.sub(r'(\n)(\s*[-–•*])', r'[[LIST_ITEM]]\2', html_content)
    html_content = html_content.replace('\n', ' ')
    html_content = html_content.replace('[[PARAGRAPH]]', '<br><br>')
    html_content = html_content.replace('[[LIST_ITEM]]', '<br>')
    return html_content

# ====================== MARCAÇÃO FINAL ======================
def marcar_divergencias_html(texto_original, relatorio, erros_ortograficos, tipo_bula, eh_referencia=False):
    texto = texto_original
    # 1. Divergências
    for item in relatorio:
        if item['status'] != 'diferente': continue
        src = item['conteudo_ref'] if eh_referencia else item['conteudo_belfar']
        marcado = marcar_diferencas_palavra_por_palavra(item['conteudo_ref'], item['conteudo_belfar'], eh_referencia)
        texto = texto.replace(src, marcado, 1)
    # 2. Ortografia
    if not eh_referencia and erros_ortograficos:
        for erro in erros_ortograficos:
            pattern = r'\b(' + re.escape(erro) + r')\b(?![^<]*?>)'
            texto = re.sub(pattern, r"<mark class='spell'>\1</mark>", texto, flags=re.IGNORECASE)
    # 3. ANVISA
    def marca_anvisa(match):
        frase = match.group(1)
        frase_limpa = re.sub(r'<mark.*?>|</mark>', '', frase)
        return f"<mark class='anvisa'>{frase_limpa}</mark>"
    texto = re.sub(r"((?:aprovad[ao]\s+pela\s+anvisa\s+em|data\s+de\s+aprova\w+\s+na\s+anvisa:)\s*([\d]{1,2}\s*/\s*[\d]{1,2}\s*/\s*[\d]{2,4}))", marca_anvisa, texto, count=1, flags=re.IGNORECASE)
    return texto

# ====================== RELATÓRIO FINAL ======================
def gerar_relatorio_final(texto_ref, texto_belfar, nome_ref, nome_belfar, tipo_bula):
    st.header("Relatório de Auditoria Inteligente")
    relatorio, similaridades = verificar_secoes_e_conteudo(texto_ref, texto_belfar, tipo_bula)
    erros_orto = checar_ortografia_inteligente(texto_belfar, texto_ref, tipo_bula)
    score = sum(similaridades) / len(similaridades) if similaridades else 100.0

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Conformidade de Conteúdo", f"{score:.0f}%")
    col2.metric("Erros Ortográficos", len(erros_orto))
    col3.metric("Data ANVISA (Artes Vigentes)", re.search(r"[\d]{1,2}\s*/\s*[\d]{1,2}\s*/\s*[\d]{2,4}", texto_ref, re.I).group() if re.search(...) else "N/D")
    col4.metric("Seções Faltantes", sum(1 for r in relatorio if r['status'] == 'faltante'))

    st.divider()
    st.subheader("Análise Detalhada Seção por Seção")
    expander_style = "height: 350px; overflow-y: auto; border: 2px solid #d0d0d0; border-radius: 6px; padding: 16px; background-color: #ffffff; font-size: 14px; line-height: 1.8; font-family: 'Georgia', serif; text-align: left; overflow-wrap: break-word; word-break: break-word;"
    for item in relatorio:
        secao = item['secao']
        status = item['status']
        if status == 'faltante':
            st.error(f"**{secao}** – FALTANTE no PDF da Gráfica")
            continue
        with st.expander(f"**{secao}** – {'IDÊNTICO' if status == 'identica' else 'DIVERGENTE'}"):
            c1, c2 = st.columns(2)
            html_ref = formatar_html_para_leitura(marcar_diferencas_palavra_por_palavra(item['conteudo_ref'], item['conteudo_belfar'], True))
            html_bel = formatar_html_para_leitura(marcar_diferencas_palavra_por_palavra(item['conteudo_ref'], item['conteudo_belfar'], False))
            with c1:
                st.markdown("**Artes Vigentes**")
                st.markdown(f"<div style='{expander_style}'>{html_ref}</div>", unsafe_allow_html=True)
            with c2:
                st.markdown("**PDF da Gráfica**")
                st.markdown(f"<div style='{expander_style}'>{html_bel}</div>", unsafe_allow_html=True)

    if erros_orto:
        st.info(f"**Possíveis erros ortográficos ({len(erros_orto)}):** " + ", ".join(erros_orto))

    st.divider()
    st.subheader("Visualização Lado a Lado com Destaques")
    st.markdown(
        "<div style='font-size:14px; background:#f0f2f6; padding:10px 15px; border-radius:8px; margin-bottom:15px;'>"
        "<strong>Legenda:</strong> "
        "<mark class='diff'>Amarelo</mark> = Divergência | "
        "<mark class='spell'>Rosa</mark> = Erro ortográfico | "
        "<mark class='anvisa'>Azul</mark> = Data ANVISA"
        "</div>", unsafe_allow_html=True
    )
    html_ref = formatar_html_para_leitura(marcar_divergencias_html(texto_ref, relatorio, [], tipo_bula, True))
    html_bel = formatar_html_para_leitura(marcar_divergencias_html(texto_belfar, relatorio, erros_orto, tipo_bula, False))
    caixa_style = "max-height:700px; overflow-y:auto; border:1px solid #e0e0e0; border-radius:8px; padding:20px 24px; background:#fff; font-size:15px; line-height:1.7; box-shadow:0 4px 12px rgba(0,0,0,0.08); text-align:left; overflow-wrap:break-word; word-break:break-word;"
    title_style = "font-size:1.25rem; font-weight:600; margin-bottom:8px; color:#31333F;"
    col1, col2 = st.columns(2, gap="large")
    with col1:
        st.markdown(f"<div style='{title_style}'>{nome_ref}</div>", unsafe_allow_html=True)
        st.markdown(f"<div style='{caixa_style}'>{html_ref}</div>", unsafe_allow_html=True)
    with col2:
        st.markdown(f"<div style='{title_style}'>{nome_belfar}</div>", unsafe_allow_html=True)
        st.markdown(f"<div style='{caixa_style}'>{html_bel}</div>", unsafe_allow_html=True)

# ====================== INTERFACE ======================
st.title("Inteligência Artificial para Auditoria de Bulas")
st.markdown("Sistema avançado de comparação literal e validação de bulas farmacêuticas")
st.divider()
st.header("Configuração da Auditoria")
tipo_bula_selecionado = st.radio("Tipo de Bula:", ("Paciente", "Profissional"), horizontal=True)
col1, col2 = st.columns(2)
with col1:
    st.subheader("Artes Vigentes")
    pdf_ref = st.file_uploader("Envie o arquivo de referência (.docx ou .pdf)", type=["docx", "pdf"], key="ref")
with col2:
    st.subheader("PDF da Gráfica")
    pdf_belfar = st.file_uploader("Envie o PDF do Marketing", type="pdf", key="belfar")

if st.button("Iniciar Auditoria Completa", use_container_width=True, type="primary"):
    if pdf_ref and pdf_belfar:
        with st.spinner("Processando e analisando as bulas..."):
            tipo_ref = 'docx' if pdf_ref.name.lower().endswith('.docx') else 'pdf'
            texto_ref, erro_ref = extrair_texto(pdf_ref, tipo_ref, is_marketing_pdf=False)
            texto_belfar, erro_belfar = extrair_texto(pdf_belfar, 'pdf', is_marketing_pdf=True)

            if not erro_ref: texto_ref = corrigir_quebras_em_titulos(texto_ref)
            if not erro_belfar: texto_belfar = corrigir_quebras_em_titulos(texto_belfar)

            texto_ref = truncar_apos_anvisa(texto_ref)
            texto_belfar = truncar_apos_anvisa(texto_belfar)

            if erro_ref or erro_belfar:
                st.error(f"Erro ao processar: {erro_ref or erro_belfar}")
            elif not texto_ref or not texto_belfar:
                st.error("Um dos arquivos está vazio.")
            else:
                gerar_relatorio_final(texto_ref, texto_belfar, "Artes Vigentes", "PDF da Gráfica", tipo_bula_selecionado)
    else:
        st.warning("Envie ambos os arquivos para iniciar.")
st.divider()
st.caption("Auditoria de Bulas v26.8+ | Truncamento e marcações aplicadas a ambos os arquivos")
