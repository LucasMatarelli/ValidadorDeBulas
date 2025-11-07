# --------------------------------------------------------------
#  Auditoria de Bulas – v26.9 (ROBUSTO + OCR FALLBACK + DEBUG)
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
import pytesseract
from PIL import Image

# ====================== CONFIGURAÇÃO DA PÁGINA ======================
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

# ====================== ESTILO GLOBAL ======================
CSS = """
<style>
    .container-scroll {
        max-height: 720px; overflow-y: auto; border: 2px solid #bbb; border-radius: 12px;
        padding: 24px 32px; background: #fafafa; font-family: 'Georgia', serif;
        font-size: 15px; line-height: 1.8; box-shadow: 0 4px 16px rgba(0,0,0,0.12);
        text-align: justify; margin-bottom: 20px; overflow-wrap: break-word; word-break: break-word;
    }
    .container-scroll::-webkit-scrollbar { width: 10px; }
    .container-scroll::-webkit-scrollbar-thumb { background: #999; border-radius: 5px; }
    mark.diff   { background:#ffff99; padding:2px 4px; border-radius:3px; }
    mark.spell  { background:#FFDDC1; padding:2px 4px; border-radius:3px; }
    mark.anvisa { background:#cce5ff; padding:2px 4px; border-radius:3px; font-weight:600; }
    .expander-box {
        height: 350px; overflow-y:auto; border:2px solid #d0d0d0; border-radius:6px;
        padding:14px; background:#fff; font-size:14px; line-height:1.7;
        overflow-wrap: break-word; word-break: break-word;
    }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

# ====================== MODELO NLP ======================
@st.cache_resource
def carregar_modelo_spacy():
    try: return spacy.load("pt_core_news_lg")
    except OSError:
        st.error("Modelo 'pt_core_news_lg' não encontrado. `python -m spacy download pt_core_news_lg`")
        return None
nlp = carregar_modelo_spacy()

# ====================== EXTRAÇÃO HÍBRIDA COM OCR ======================
def extrair_texto_com_ocr(arquivo, tipo_arquivo, is_marketing_pdf=False):
    if not arquivo:
        return "", "Arquivo não enviado."
    arquivo.seek(0)
    bytes_data = arquivo.read()

    # --- TENTATIVA 1: Texto nativo (fitz) ---
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
            return limpar_texto(texto), None
    except Exception as e:
        st.warning(f"Falha na extração nativa: {e}")

    # --- TENTATIVA 2: OCR (imagens) ---
    try:
        st.info("Texto nativo insuficiente. Usando OCR...")
        texto_ocr = ""
        with fitz.open(stream=bytes_data, filetype="pdf") as doc:
            for page_num, page in enumerate(doc):
                if is_marketing_pdf:
                    rect = page.rect
                    clip1 = fitz.Rect(0, 0, rect.width/2, rect.height)
                    clip2 = fitz.Rect(rect.width/2, 0, rect.width, rect.height)
                    for clip in [clip1, clip2]:
                        pix = page.get_pixmap(clip=clip, dpi=300)
                        img = Image.open(io.BytesIO(pix.tobytes("png")))
                        ocr = pytesseract.image_to_string(img, lang='por', config='--psm 6')
                        texto_ocr += ocr + "\n"
                else:
                    pix = page.get_pixmap(dpi=300)
                    img = Image.open(io.BytesIO(pix.tobytes("png")))
                    ocr = pytesseract.image_to_string(img, lang='por', config='--psm 6')
                    texto_ocr += ocr + "\n"
        return limpar_texto(texto_ocr), None
    except Exception as e:
        return "", f"OCR falhou: {e}"

def limpar_texto(texto):
    if not texto: return ""
    # Remover caracteres invisíveis
    invis = ['\u00AD','\u200B','\u200C','\u200D','\uFEFF']
    for c in invis: texto = texto.replace(c, '')
    texto = texto.replace('\r\n','\n').replace('\r','\n').replace('\u00A0',' ')

    # Ruídos específicos
    padrao_ruido = re.compile(
        r'lew Roman U|\(31\) 3514-2900|pp 190|mm — >>>»|a \?|1º prova -|la|KH 190 r|'
        r'BUL.*|FRENTE|VERSO|Times New Roman|Papel.*|Cor.*|Contato.*|artes@belfar\.com\.br',
        re.IGNORECASE
    )
    linhas = [ln for ln in texto.split('\n') if not padrao_ruido.search(ln.strip()) and len(ln.strip()) > 1]
    texto = "\n".join(linhas)
    texto = re.sub(r'\n{3,}', '\n\n', texto)
    texto = re.sub(r'[ \t]+', ' ', texto).strip()
    return texto

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

# ====================== SEÇÕES, MAPEAMENTO, ETC (igual v26.8) ======================
# [MESMAS FUNÇÕES DO CÓDIGO ANTERIOR: obter_secoes_por_tipo, mapear_secoes, etc]
# → Para brevidade, cole-as aqui do código v26.8 (não alteradas)

# ====================== INTERFACE ======================
st.title("Inteligência Artificial para Auditoria de Bulas")
st.markdown("Sistema avançado de comparação literal e validação de bulas farmacêuticas")
st.divider()

st.header("Configuração da Auditoria")
tipo_bula = st.radio("Tipo de Bula:", ("Paciente", "Profissional"), horizontal=True)

col1, col2 = st.columns(2)
with col1:
    st.subheader("Artes Vigentes")
    pdf_ref = st.file_uploader("Envie o arquivo de referência (.docx ou .pdf)", type=["docx", "pdf"], key="ref")
with col2:
    st.subheader("PDF da Gráfica")
    pdf_belfar = st.file_uploader("Envie o PDF do Marketing", type="pdf", key="belfar")

if st.button("Iniciar Auditoria Completa", use_container_width=True, type="primary"):
    if not pdf_ref or not pdf_belfar:
        st.error("Por favor, envie **ambos os arquivos**.")
    else:
        with st.spinner("Extraindo texto com OCR de fallback..."):
            tipo_ref = 'docx' if pdf_ref.name.lower().endswith('.docx') else 'pdf'
            texto_ref, erro_ref = extrair_texto_com_ocr(pdf_ref, tipo_ref, is_marketing_pdf=False)
            texto_belfar, erro_belfar = extrair_texto_com_ocr(pdf_belfar, 'pdf', is_marketing_pdf=True)

            # DEBUG VISUAL
            if st.checkbox("Mostrar texto extraído (debug)"):
                st.subheader("Texto Extraído - Artes Vigentes")
                st.code(texto_ref[:2000] + "..." if len(texto_ref) > 2000 else texto_ref)
                st.subheader("Texto Extraído - PDF da Gráfica")
                st.code(texto_belfar[:2000] + "..." if len(texto_belfar) > 2000 else texto_belfar)

            if erro_ref or erro_belfar:
                st.error(f"Erro: {erro_ref or erro_belfar}")
            elif len(texto_ref.strip()) < 100 or len(texto_belfar.strip()) < 100:
                st.error("Um dos textos extraídos está muito curto. Verifique se os PDFs contêm texto selecionável ou tente outro arquivo.")
            else:
                texto_ref = truncar_apos_anvisa(texto_ref)
                texto_belfar = truncar_apos_anvisa(texto_belfar)
                gerar_relatorio_final(texto_ref, texto_belfar, "Artes Vigentes", "PDF da Gráfica", tipo_bula)

st.divider()
st.caption("Auditoria de Bulas v26.9 | OCR de fallback + robustez total")
