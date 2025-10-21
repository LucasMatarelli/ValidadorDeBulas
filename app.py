import streamlit as st
from style_utils import hide_streamlit_toolbar

hide_streamlit_toolbar()

st.set_page_config(
    page_title="Validador de Bulas Belfar",
    page_icon="🔬",
    layout="wide"
)

st.title("🔬 Validador Inteligente de Bulas")
st.subheader("Bem-vindo à ferramenta de análise e comparação de documentos.")
st.divider()

st.info("👈 **Selecione uma das ferramentas de análise na barra lateral para começar.**")

# --- DESCRIÇÕES ATUALIZADAS AQUI ---
st.markdown(
    """
    ### Ferramentas Disponíveis:

    * **Medicamento Referência x Belfar:** Compara a bula de referência com a bula Belfar. Aponta as diferenças entre as duas com marca-texto amarelo, possíveis erros de português em vermelho e a data da ANVISA em azul.

    * **Conferência MKT (Word/PDF vs PDF):** Compara o arquivo da ANVISA (.docx ou .pdf) com o PDF final do Marketing. Aponta as diferenças entre os documentos em amarelo, possíveis erros de português em vermelho e a data da ANVISA em azul.

    * **Gráfica vs Arte Vigente (PDF em Curva vs PDF em Curva):** Compara o PDF da Gráfica (frequentemente 'em curva') com o PDF da Arte Vigente (também pode ser 'em curva'). O sistema lê ambos os arquivos, mesmo se estiverem em curva, e aponta as diferenças entre os dois em amarelo, possíveis erros de português em vermelho e a data da ANVISA em azul.

        **O que é um arquivo 'em curva'?**
        Uma bula em curva é um arquivo PDF onde todo o conteúdo de texto foi convertido em curvas (vetores).
        Isso quer dizer que:
        * O texto original foi transformado em formas geométricas (desenhos), não em caracteres digitáveis.
        * Visualmente parece um texto, mas o computador enxerga apenas imagens/vetores, não letras (exigindo OCR para leitura).
    """
)
# --- FIM DAS DESCRIÇÕES ---

st.sidebar.success("Selecione uma ferramenta acima.")
