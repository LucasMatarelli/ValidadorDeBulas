# --------------------------------------------------------------
#  Auditoria de Bulas – v26.95 (OCR + LIMPEZA + FORMATAÇÃO)
# --------------------------------------------------------------
import re
import difflib
import unicodedata
import io
import streamlit as st
import fitz  # PyMuPDF
import spacy
from thefuzz import fuzz
from spellchecker import SpellChecker
import pytesseract
from PIL import Image

# ====================== CONFIGURAÇÃO ======================
st.set_page_config(layout="wide", page_title="Auditoria de Bulas", page_icon="microscope")
hide_streamlit_UI = """
<style>
    [data-testid="stHeader"], [data-testid="main-menu-button"], footer,
    [data-testid="stStatusWidget"], [data-testid="stCreatedBy"], [data-testid="stHostedBy"] {
        display: none !important; visibility: hidden !important;
    }
</style>
"""
st.markdown(hide_streamlit_UI, unsafe_allow_html=True)

CSS = """
<style>
    .container-scroll { max-height: 720px; overflow-y: auto; border: 2px solid #bbb; border-radius: 12px;
        padding: 24px 32px; background: #fafafa; font-family: 'Georgia', serif; font-size: 15px; line-height: 1.8;
        box-shadow: 0 4px 16px rgba(0,0,0,0.12); text-align: justify; margin-bottom: 20px;
        overflow-wrap: break-word; word-break: break-word; }
    .container-scroll::-webkit-scrollbar { width: 10px; }
    .container-scroll::-webkit-scrollbar-thumb { background: #999; border-radius: 5px; }
    mark.diff   { background:#ffff99; padding:2px 4px; border-radius:3px; }
    mark.spell  { background:#FFDDC1; padding:2px 4px; border-radius:3px; }
    mark.anvisa { background:#cce5ff; padding:2px 4px; border-radius:3px; font-weight:600; }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

# ====================== OCR + LIMPEZA AGRESSIVA ======================
def extrair_texto_com_ocr(arquivo, tipo_arquivo, is_marketing_pdf=False):
    if not arquivo: return "", "Arquivo não enviado."
    arquivo.seek(0)
    bytes_data = arquivo.read()

    # --- TENTATIVA 1: Texto nativo ---
    try:
        texto = ""
        with fitz.open(stream=bytes_data, filetype="pdf") as doc:
            for page in doc:
                if is_marketing_pdf:
                    rect = page.rect
                    esquerda = fitz.Rect(0, 0, rect.width/2, rect.height)
                    direita = fitz.Rect(rect.width/2, 0, rect.width, rect.height)
                    txt1 = page.get_text("text", clip=esquerda, sort=True)
                    txt2 = page.get_text("text", clip=direita, sort=True)
                    pagina = txt1 + "\n" + txt2
                else:
                    pagina = page.get_text("text", sort=True)
                if len(pagina.strip()) > 100:
                    texto += pagina + "\n\n"
        if len(texto.strip()) > 200:
            return limpar_texto_agressivo(texto), None
    except Exception as e:
        st.warning(f"Falha na extração nativa: {e}")

    # --- TENTATIVA 2: OCR COM DPI ALTO + CONFIGURAÇÃO OTIMIZADA ---
    try:
        st.info("Usando OCR como fallback (DPI 300 + PSM 6)...")
        texto_ocr = ""
        with fitz.open(stream=bytes_data, filetype="pdf") as doc:
            for page in doc:
                if is_marketing_pdf:
                    rect = page.rect
                    for clip in [fitz.Rect(0, 0, rect.width/2, rect.height), fitz.Rect(rect.width/2, 0, rect.width, rect.height)]:
                        pix = page.get_pixmap(clip=clip, dpi=300)
                        img = Image.open(io.BytesIO(pix.tobytes("png")))
                        ocr = pytesseract.image_to_string(img, lang='por', config='--psm 6 -c tessedit_char_whitelist=0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyzáéíóúãõçÁÉÍÓÚÃÕÇ.,;:!?()[]{}"\'- ')
                        texto_ocr += ocr + "\n"
                else:
                    pix = page.get_pixmap(dpi=300)
                    img = Image.open(io.BytesIO(pix.tobytes("png")))
                    ocr = pytesseract.image_to_string(img, lang='por', config='--psm 6 -c tessedit_char_whitelist=0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyzáéíóúãõçÁÉÍÓÚÃÕÇ.,;:!?()[]{}"\'- ')
                    texto_ocr += ocr + "\n"
        return limpar_texto_agressivo(texto_ocr), None
    except Exception as e:
        return "", f"OCR falhou: {e}"

def limpar_texto_agressivo(texto):
    if not texto: return ""
    # Remove caracteres invisíveis e lixo
    invis = ['\u00AD','\u200B','\u200C','\u200D','\uFEFF','\u2060','\u200E','\u200F']
    for c in invis: texto = texto.replace(c, '')
    texto = texto.replace('\r\n','\n').replace('\r','\n').replace('\u00A0',' ')
    # Remove ruídos comuns de PDF
    padrao_ruido = re.compile(
        r'k———190mm|>>>>|<<<|New Roman U|\(31\) 3514-2900|pp 190|mm — >>>»|a \?|1º prova -|la|KH 190 r|'
        r'BUL.*|FRENTE|VERSO|Times New Roman|Papel.*|Cor.*|Contato.*|artes@belfar\.com\.br|'
        r'[\u2500-\u257F]+|[\u2580-\u259F]+|[\u25A0-\u25FF]+|[\u2600-\u26FF]+|[\u2700-\u27BF]+',
        re.IGNORECASE
    )
    linhas = []
    for ln in texto.split('\n'):
        ln = ln.strip()
        if not ln or padrao_ruido.search(ln): continue
        if len(ln) < 3: continue
        # Remove números de página isolados
        if re.fullmatch(r'\d{1,3}', ln): continue
        linhas.append(ln)
    texto = "\n".join(linhas)
    # Junta quebras de linha em títulos
    texto = corrigir_quebras_em_titulos(texto)
    # Remove linhas duplicadas
    linhas_unicas = []
    for ln in texto.split('\n'):
        if ln not in linhas_unicas:
            linhas_unicas.append(ln)
    texto = "\n".join(linhas_unicas)
    texto = re.sub(r'\n{3,}', '\n\n', texto)
    texto = re.sub(r'[ \t]+', ' ', texto).strip()
    return texto

def corrigir_quebras_em_titulos(texto):
    linhas = texto.split("\n")
    buffer = ""
    resultado = []
    for linha in linhas:
        linha = linha.strip()
        if not linha: continue
        # Se for título em MAIÚSCULAS e curto, junta com o anterior
        if linha.isupper() and len(linha) < 70 and re.match(r'^[A-Z0-9\.\s\?\!]+$', linha):
            buffer += (" " + linha) if buffer else linha
        else:
            if buffer:
                resultado.append(buffer)
                buffer = ""
            resultado.append(linha)
    if buffer: resultado.append(buffer)
    return "\n".join(resultado)

# ====================== TRUNCAR APÓS ANVISA ======================
def truncar_apos_anvisa(texto):
    if not texto: return texto
    regex = r"((?:aprovad[ao]\s+pela\s+anvisa\s+em|data\s+de\s+aprova\w+\s+na\s+anvisa:)\s*([\d]{1,2}\s*/\s*[\d]{1,2}\s*/\s*[\d]{2,4}))"
    match = re.search(regex, texto, re.IGNORECASE)
    if not match: return texto
    fim = match.end(1)
    ponto = re.search(r'^\s*\.', texto[fim:])
    if ponto: fim += ponto.end()
    return texto[:fim]

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

# ====================== NORMALIZAÇÃO ======================
def normalizar_texto(texto):
    if not isinstance(texto, str): return ""
    texto = ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')
    texto = re.sub(r'[^\w\s]', '', texto)
    return ' '.join(texto.split()).lower()

def normalizar_titulo_para_comparacao(texto):
    texto_norm = normalizar_texto(texto)
    return re.sub(r'^\d+\s*[\.\-)]*\s*', '', texto_norm).strip()

# ====================== MAPEAMENTO DE SEÇÕES ======================
def is_titulo_secao(linha):
    linha = linha.strip()
    if len(linha) < 4 or len(linha) > 120 or linha.endswith(('.', ':')): return False
    return re.match(r'^\d+\.\s+[A-Z]', linha) or linha.isupper()

def mapear_secoes(texto_completo, secoes_esperadas):
    mapa = []
    linhas = texto_completo.split('\n')
    aliases = obter_aliases_secao()
    titulos_possiveis = {s: s for s in secoes_esperadas}
    for alias, canonico in aliases.items():
        if canonico in secoes_esperadas: titulos_possiveis[alias] = canonico
    titulos_norm_lookup = {normalizar_titulo_para_comparacao(t): c for t, c in titulos_possiveis.items()}
    limiar = 82  # Abaixado para maior tolerância

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
                'score': best_score
            })
    mapa.sort(key=lambda x: x['linha_inicio'])
    return mapa

def obter_dados_secao(secao_canonico, mapa_secoes, linhas_texto):
    idx_secao = next((i for i, m in enumerate(mapa_secoes) if m['canonico'] == secao_canonico), -1)
    if idx_secao == -1: return False, None, ""
    info = mapa_secoes[idx_secao]
    inicio = info['linha_inicio'] + 1
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
            relatorio.append({'secao': secao, 'status': 'faltante', 'conteudo_ref': conteudo_ref or "", 'conteudo_belfar': ""})
            continue

        if encontrou_ref and encontrou_belfar:
            if normalizar_texto(conteudo_ref) != normalizar_texto(conteudo_belfar):
                relatorio.append({'secao': secao, 'status': 'diferente', 'conteudo_ref': conteudo_ref, 'conteudo_belfar': conteudo_belfar})
                similaridade_geral.append(0)
            else:
                relatorio.append({'secao': secao, 'status': 'identica', 'conteudo_ref': conteudo_ref, 'conteudo_belfar': conteudo_belfar})
                similaridade_geral.append(100)

    return relatorio, similaridade_geral

# ====================== MARCAÇÃO ======================
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
    return resultado

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

# ====================== RELATÓRIO FINAL ======================
def gerar_relatorio_final(texto_ref, texto_belfar, nome_ref, nome_belfar, tipo_bula):
    st.header("Relatório de Auditoria Inteligente")
    relatorio, similaridades = verificar_secoes_e_conteudo(texto_ref, texto_belfar, tipo_bula)
    score = sum(similaridades) / len(similaridades) if similaridades else 100.0

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Conformidade", f"{score:.0f}%")
    col2.metric("Seções Faltantes", sum(1 for r in relatorio if r['status'] == 'faltante'))

    match_anvisa = re.search(r"[\d]{1,2}\s*/\s*[\d]{1,2}\s*/\s*[\d]{2,4}", texto_ref, re.I)
    data_anvisa = match_anvisa.group() if match_anvisa else "N/D"
    col3.metric("Data ANVISA", data_anvisa)

    col4.metric("Status", "CONFORME" if score >= 95 else "DIVERGENTE")

    st.divider()
    for item in relatorio:
        secao = item['secao']
        status = item['status']
        if status == 'faltante':
            st.error(f"**{secao}** – FALTANTE")
            continue
        with st.expander(f"**{secao}** – {'IDÊNTICO' if status == 'identica' else 'DIVERGENTE'}"):
            c1, c2 = st.columns(2)
            html_ref = formatar_html_para_leitura(marcar_diferencas_palavra_por_palavra(item['conteudo_ref'], item['conteudo_belfar'], True))
            html_bel = formatar_html_para_leitura(marcar_diferencas_palavra_por_palavra(item['conteudo_ref'], item['conteudo_belfar'], False))
            with c1:
                st.markdown("**Artes Vigentes**")
                st.markdown(f"<div style='height:350px;overflow-y:auto;border:1px solid #ddd;padding:12px;background:#fff;font-size:14px;line-height:1.7;'>{html_ref}</div>", unsafe_allow_html=True)
            with c2:
                st.markdown("**PDF da Gráfica**")
                st.markdown(f"<div style='height:350px;overflow-y:auto;border:1px solid #ddd;padding:12px;background:#fff;font-size:14px;line-height:1.7;'>{html_bel}</div>", unsafe_allow_html=True)

    st.divider()
    st.subheader("Visualização Lado a Lado")
    html_ref = formatar_html_para_leitura(texto_ref)
    html_bel = formatar_html_para_leitura(texto_belfar)
    col1, col2 = st.columns(2, gap="large")
    with col1:
        st.markdown(f"**{nome_ref}**")
        st.markdown(f"<div class='container-scroll'>{html_ref}</div>", unsafe_allow_html=True)
    with col2:
        st.markdown(f"**{nome_belfar}**")
        st.markdown(f"<div class='container-scroll'>{html_bel}</div>", unsafe_allow_html=True)

# ====================== INTERFACE ======================
st.title("Auditoria de Bulas – v26.95")
st.markdown("Sistema com **OCR otimizado + limpeza inteligente**")
st.divider()

tipo_bula = st.radio("Tipo de Bula:", ("Paciente", "Profissional"), horizontal=True)

col1, col2 = st.columns(2)
with col1:
    st.subheader("Artes Vigentes")
    pdf_ref = st.file_uploader("Envie o arquivo de referência (.pdf ou .docx)", type=["pdf", "docx"], key="ref")
with col2:
    st.subheader("PDF da Gráfica")
    pdf_belfar = st.file_uploader("Envie o PDF do Marketing", type="pdf", key="belfar")

if st.button("Iniciar Auditoria", use_container_width=True, type="primary"):
    if not pdf_ref or not pdf_belfar:
        st.error("Envie **ambos os arquivos**.")
    else:
        with st.spinner("Extraindo e limpando texto..."):
            tipo_ref = 'docx' if pdf_ref.name.lower().endswith('.docx') else 'pdf'
            texto_ref, erro_ref = extrair_texto_com_ocr(pdf_ref, tipo_ref, is_marketing_pdf=False)
            texto_belfar, erro_belfar = extrair_texto_com_ocr(pdf_belfar, 'pdf', is_marketing_pdf=True)

            if erro_ref or erro_belfar:
                st.error(f"Erro: {erro_ref or erro_belfar}")
            elif len(texto_ref.strip()) < 100 or len(texto_belfar.strip()) < 100:
                st.error("Texto muito curto. Verifique os arquivos.")
            else:
                texto_ref = truncar_apos_anvisa(corrigir_quebras_em_titulos(texto_ref))
                texto_belfar = truncar_apos_anvisa(corrigir_quebras_em_titulos(texto_belfar))
                gerar_relatorio_final(texto_ref, texto_belfar, "Artes Vigentes", "PDF da Gráfica", tipo_bula)

st.divider()
st.caption("v26.95 | OCR + Limpeza + Formatação Perfeita")
