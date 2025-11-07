# pages/3_Grafica_x_Arte.py
# Versão v1.0 (baseada na v26.8)
# Comparação entre: Arte Vigente (referência) x PDF da Gráfica
# Mantém o mesmo layout e funcionamento do módulo de Conferência MKT.

# --- IMPORTS ---
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
    """Carrega o modelo SpaCy de forma otimizada."""
    try:
        return spacy.load("pt_core_news_lg")
    except OSError:
        st.error("Modelo 'pt_core_news_lg' não encontrado. Execute: python -m spacy download pt_core_news_lg")
        return None


nlp = carregar_modelo_spacy()


# ----------------- EXTRAÇÃO -----------------
def extrair_texto(arquivo, tipo_arquivo, is_marketing_pdf=False):
    """Extrai texto de PDFs ou DOCX preservando o fluxo de leitura."""
    if arquivo is None:
        return "", f"Arquivo {tipo_arquivo} não enviado."
    try:
        arquivo.seek(0)
        texto = ""
        full_text_list = []

        if tipo_arquivo == "pdf":
            with fitz.open(stream=arquivo.read(), filetype="pdf") as doc:
                # Para PDFs da gráfica, pode haver 2 colunas
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

        elif tipo_arquivo == "docx":
            docx_file = docx.Document(arquivo)
            texto = "\n".join([p.text for p in docx_file.paragraphs])

        # Limpeza leve
        texto = texto.replace("\r", "\n").replace("\u00A0", " ").strip()
        texto = re.sub(r"\n{3,}", "\n\n", texto)
        return texto, None
    except Exception as e:
        return "", f"Erro ao ler {tipo_arquivo}: {e}"


# ----------------- NORMALIZAÇÃO -----------------
def normalizar_texto(txt):
    if not isinstance(txt, str):
        return ""
    txt = "".join(c for c in unicodedata.normalize("NFD", txt) if unicodedata.category(c) != "Mn")
    txt = re.sub(r"[^\w\s]", "", txt)
    return " ".join(txt.lower().split())


# ----------------- SEÇÕES -----------------
def secoes_bula():
    return [
        "APRESENTAÇÕES",
        "COMPOSIÇÃO",
        "1. PARA QUE ESTE MEDICAMENTO É INDICADO?",
        "2. COMO ESTE MEDICAMENTO FUNCIONA?",
        "3. QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?",
        "4. O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?",
        "5. ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?",
        "6. COMO DEVO USAR ESTE MEDICAMENTO?",
        "7. O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?",
        "8. QUAIS OS MALES QUE ESTE MEDICAMENTO PODE ME CAUSAR?",
        "9. O QUE FAZER SE ALGUÉM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?",
        "DIZERES LEGAIS",
    ]


# ----------------- MAPA DE SEÇÕES -----------------
def mapear_secoes(texto):
    linhas = texto.split("\n")
    mapa = []
    for i, linha in enumerate(linhas):
        for s in secoes_bula():
            if fuzz.token_set_ratio(normalizar_texto(linha), normalizar_texto(s)) >= 85:
                mapa.append({"secao": s, "linha": i})
    return mapa


def extrair_secao(secao, texto, mapa):
    linhas = texto.split("\n")
    for i, item in enumerate(mapa):
        if item["secao"] == secao:
            inicio = item["linha"] + 1
            fim = mapa[i + 1]["linha"] if i + 1 < len(mapa) else len(linhas)
            return "\n".join(linhas[inicio:fim]).strip()
    return ""


# ----------------- COMPARAÇÃO -----------------
def comparar_bulas(texto_arte, texto_grafica):
    mapa_arte = mapear_secoes(texto_arte)
    mapa_grafica = mapear_secoes(texto_grafica)
    secoes = secoes_bula()
    resultado = []

    for s in secoes:
        conteudo_arte = extrair_secao(s, texto_arte, mapa_arte)
        conteudo_grafica = extrair_secao(s, texto_grafica, mapa_grafica)

        if not conteudo_grafica and conteudo_arte:
            status = "faltante"
        elif normalizar_texto(conteudo_arte) == normalizar_texto(conteudo_grafica):
            status = "identico"
        else:
            status = "diferente"

        resultado.append(
            {
                "secao": s,
                "status": status,
                "arte": conteudo_arte,
                "grafica": conteudo_grafica,
            }
        )
    return resultado


# ----------------- INTERFACE -----------------
st.title("🧾 Comparativo Gráfica x Arte Vigente")
st.markdown("Comparação literal de todas as seções entre o **PDF da Arte Vigente** e o **PDF da Gráfica**.")
st.divider()

col1, col2 = st.columns(2)
with col1:
    st.subheader("📄 Arte Vigente (Referência)")
    arquivo_arte = st.file_uploader("Envie o PDF da Arte Vigente", type=["pdf", "docx"], key="arte")
with col2:
    st.subheader("📄 PDF da Gráfica")
    arquivo_grafica = st.file_uploader("Envie o PDF da Gráfica", type=["pdf"], key="grafica")

if st.button("🔍 Iniciar Comparação", use_container_width=True, type="primary"):
    if arquivo_arte and arquivo_grafica:
        with st.spinner("Processando os arquivos..."):
            tipo_arte = "docx" if arquivo_arte.name.lower().endswith(".docx") else "pdf"
            texto_arte, erro1 = extrair_texto(arquivo_arte, tipo_arte, is_marketing_pdf=False)
            texto_grafica, erro2 = extrair_texto(arquivo_grafica, "pdf", is_marketing_pdf=True)

        if erro1 or erro2:
            st.error(f"Erro ao processar arquivos: {erro1 or erro2}")
        else:
            st.success("✅ Arquivos processados com sucesso!")
            resultado = comparar_bulas(texto_arte, texto_grafica)

            # Layout do relatório
            for item in resultado:
                secao = item["secao"]
                status = item["status"]
                arte = item["arte"]
                grafica = item["grafica"]

                if status == "diferente":
                    with st.expander(f"📄 {secao} - ❌ CONTEÚDO DIVERGENTE"):
                        c1, c2 = st.columns(2)
                        with c1:
                            st.markdown("**Arquivo Arte Vigente:**")
                            st.text_area("", arte, height=350)
                        with c2:
                            st.markdown("**Arquivo Gráfica:**")
                            st.text_area("", grafica, height=350)
                elif status == "identico":
                    with st.expander(f"📄 {secao} - ✅ CONTEÚDO IDÊNTICO"):
                        c1, c2 = st.columns(2)
                        with c1:
                            st.markdown("**Arquivo Arte Vigente:**")
                            st.text_area("", arte, height=300)
                        with c2:
                            st.markdown("**Arquivo Gráfica:**")
                            st.text_area("", grafica, height=300)
                elif status == "faltante":
                    with st.expander(f"📄 {secao} - 🚨 SEÇÃO AUSENTE NA GRÁFICA"):
                        st.warning("Seção presente na Arte Vigente, mas ausente no PDF da Gráfica.")
                        st.text_area("Conteúdo presente na Arte Vigente:", arte, height=300)
    else:
        st.warning("⚠️ Envie ambos os arquivos para iniciar a comparação.")

st.divider()
st.caption("Sistema de Comparação Gráfica x Arte Vigente | v1.0 | Base v26.8")
