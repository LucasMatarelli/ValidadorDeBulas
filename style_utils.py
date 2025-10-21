import streamlit as st

def hide_streamlit_toolbar():
    """Função para injetar CSS e esconder a toolbar do Streamlit."""
    hide_toolbar_css = """
    <style>
        [data-testid="stToolbar"] {
            visibility: hidden;
            height: 0%;
            position: fixed;
        }
        [data-testid="stDecoration"] {
            visibility: hidden;
            height: 0%;
            position: fixed;
        }
        [data-testid="stStatusWidget"] {
            visibility: hidden;
            height: 0%;
            position: fixed;
        }
        #MainMenu {
            visibility: hidden;
            height: 0%;
        }
        header {
            visibility: hidden;
            height: 0%;
        }
        footer {
            visibility: hidden;
            height: 0%;
        }
    </style>
    """
    st.markdown(hide_toolbar_css, unsafe_allow_html=True)
