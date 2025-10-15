import streamlit as st

st.set_page_config(
    page_title="Validador de Bulas Belfar",
    page_icon="🔬",
    layout="wide"
)

st.title("🔬 Validador Inteligente de Bulas")
st.subheader("Bem-vindo à ferramenta de análise e comparação de documentos.")
st.divider()

st.info("👈 **Selecione uma das ferramentas de análise na barra lateral para começar.**")

st.markdown(
    """
    ### Ferramentas Disponíveis:

    - **Medicamento Referência x Belfar:** A ferramenta principal para auditoria completa de conteúdo e ortografia.

    - **Conferência MKT (Word vs PDF):** Ferramenta para checar possíveis erros de português no PDF final do Marketing, usando o Word como referência de vocabulário.

    - **Gráfica vs Arte Vigente (PDF vs PDF):** Ferramenta para checar possíveis erros de português na prova da gráfica, usando a arte vigente como referência de vocabulário.
    """
)
st.sidebar.success("Selecione uma ferramenta acima.")