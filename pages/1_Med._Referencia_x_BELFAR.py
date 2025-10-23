# --- IMPORTS ---
import streamlit as st
from streamlit.components.v1 import html as st_html # Import specific function

# (Restante dos imports como antes)
import fitz # PyMuPDF
import docx
import re
import spacy
from thefuzz import fuzz
from spellchecker import SpellChecker
import difflib
import unicodedata

# ... (hide_streamlit_UI e todas as funções de `carregar_modelo_spacy` até `marcar_divergencias_html` permanecem EXATAMENTE IGUAIS) ...
# --- IMPORTS ---
# (Restante dos imports como antes)

hide_streamlit_UI = """
<style>
/* Esconde o cabeçalho do Streamlit Cloud (com 'Fork' e GitHub) */
[data-testid="stHeader"] {
display: none !important;
visibility: hidden !important;
}
/* Esconde o menu hamburger (dentro do app) */
[data-testid="main-menu-button"] {
display: none !important;
}
/* Esconde o rodapé genérico (garantia extra) */
footer {
display: none !important;
visibility: hidden !important;
}

/* --- NOVOS SELETORES (MAIS AGRESSIVOS) PARA O BADGE INFERIOR --- */

/* Esconde o container principal do badge */
[data-testid="stStatusWidget"] {
display: none !important;
visibility: hidden !important;
}

/* Esconde o 'Created by' */
[data-testid="stCreatedBy"] {
display: none !important;
visibility: hidden !important;
}

/* Esconde o 'Hosted with Streamlit' */
[data-testid="stHostedBy"] {
display: none !important;
visibility: hidden !important;
}
</style>
"""
st.markdown(hide_streamlit_UI, unsafe_allow_html=True)
# ... (restante dos imports e funções até gerar_relatorio_final)


# ----------------- RELATÓRIO -----------------
def gerar_relatorio_final(texto_ref, texto_belfar, nome_ref, nome_belfar, tipo_bula):

    # <<< [MUDANÇA AQUI 1] >>>
    # REMOVEMOS o CSS .btn-scroll-nav daqui.
    # Mantemos APENAS o script que define a função GLOBAL handleBulaScroll.
    global_js_script = """
    <script>
    // 1. A função de rolagem (como estava antes)
    if (!window.handleBulaScroll) {
        window.handleBulaScroll = function(anchorIdRef, anchorIdBel) {
            console.log("Chamada handleBulaScroll:", anchorIdRef, anchorIdBel);
            var parentDoc = window.parent.document; // Precisamos buscar no documento pai
            var containerRef = parentDoc.getElementById('container-ref-scroll');
            var containerBel = parentDoc.getElementById('container-bel-scroll');
            var anchorRef = parentDoc.getElementById(anchorIdRef);
            var anchorBel = parentDoc.getElementById(anchorIdBel);

            if (!containerRef || !containerBel) {
                console.error("ERRO: Containers 'container-ref-scroll' ou 'container-bel-scroll' não encontrados no documento pai.");
                return;
            }
            if (!anchorRef || !anchorBel) {
                console.error("ERRO: Âncoras '" + anchorIdRef + "' ou '" + anchorIdBel + "' não encontradas no documento pai.");
                return;
            }
            // Rola a PÁGINA PRINCIPAL (do pai)
            containerRef.scrollIntoView({ behavior: 'smooth', block: 'start' });
            setTimeout(() => {
                try {
                    // Cálculos relativos aos containers no PAI
                    var topPosRef = anchorRef.offsetTop - containerRef.offsetTop;
                    containerRef.scrollTo({ top: topPosRef - 20, behavior: 'smooth' });
                    anchorRef.style.transition = 'background-color 0.5s ease-in-out';
                    anchorRef.style.backgroundColor = '#e6f7ff';
                    setTimeout(() => { anchorRef.style.backgroundColor = 'transparent'; }, 2500);

                    var topPosBel = anchorBel.offsetTop - containerBel.offsetTop;
                    containerBel.scrollTo({ top: topPosBel - 20, behavior: 'smooth' });
                    anchorBel.style.transition = 'background-color 0.5s ease-in-out';
                    anchorBel.style.backgroundColor = '#e6f7ff';
                    setTimeout(() => { anchorBel.style.backgroundColor = 'transparent'; }, 2500);
                    console.log("Rolagem interna EXECUTADA.");
                } catch (e) {
                    console.error("Erro durante a rolagem interna:", e);
                }
            }, 700);
        }
        console.log("Função window.handleBulaScroll DEFINIDA na janela principal.");
    }
    // NÃO precisamos mais do listener global aqui.
    </script>
    """
    # Injeta APENAS o script global uma vez no topo do relatório
    st.markdown(global_js_script, unsafe_allow_html=True)
    # --- [FIM DA MUDANÇA 1] ---

    st.header("Relatório de Auditoria Inteligente")
    regex_anvisa = r"(aprovad[ao]\s+pela\s+anvisa\s+em|data\s+de\s+aprovação\s+na\s+anvisa:)\s*([\d]{1,2}/[\d]{1,2}/[\d]{2,4})"
    match_ref = re.search(regex_anvisa, texto_ref.lower())
    match_belfar = re.search(regex_anvisa, texto_belfar.lower())
    data_ref = match_ref.group(2).strip() if match_ref else "Não encontrada"
    data_belfar = match_belfar.group(2).strip() if match_belfar else "Não encontrada"

    secoes_faltantes, diferencas_conteudo, similaridades, diferencas_titulos = verificar_secoes_e_conteudo(texto_ref, texto_belfar, tipo_bula)
    erros_ortograficos = checar_ortografia_inteligente(texto_belfar, texto_ref, tipo_bula)
    score_similaridade_conteudo = sum(similaridades) / len(similaridades) if similaridades else 100.0

    st.subheader("Dashboard de Veredito")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Conformidade de Conteúdo", f"{score_similaridade_conteudo:.0f}%")
    col2.metric("Erros Ortográficos", len(erros_ortograficos))
    col3.metric("Data ANVISA (BELFAR)", data_belfar)
    col4.metric("Seções Faltantes", f"{len(secoes_faltantes)}")

    st.divider()
    st.subheader("Detalhes dos Problemas Encontrados")
    st.info(f"ℹ️ **Datas de Aprovação ANVISA:**\n - Referência: `{data_ref}`\n - BELFAR: `{data_belfar}`")

    if secoes_faltantes:
        st.error(f"🚨 **Seções faltantes na bula BELFAR ({len(secoes_faltantes)})**:\n" + "\n".join([f" - {s}" for s in secoes_faltantes]))
    else:
        st.success("✅ Todas as seções obrigatórias estão presentes")

    if diferencas_conteudo:
        st.warning(f"⚠️ **Diferenças de conteúdo encontradas ({len(diferencas_conteudo)} seções):**")
        expander_caixa_style = (
            "height: 350px; overflow-y: auto; border: 2px solid #d0d0d0; border-radius: 6px; "
            "padding: 16px; background-color: #ffffff; font-size: 14px; line-height: 1.8; "
            "font-family: 'Georgia', 'Times New Roman', serif; text-align: justify;"
        )

        for diff in diferencas_conteudo:
            with st.expander(f"📄 {diff['secao']} - ❌ CONTEÚDO DIVERGENTE"):

                secao_canonico = diff['secao']
                anchor_id_ref = _create_anchor_id(secao_canonico, "ref")
                anchor_id_bel = _create_anchor_id(secao_canonico, "bel")

                # <<< [MUDANÇA AQUI 2] >>>
                # Construímos a string HTML completa para o st.html()
                # Inclui o <style>, o <button> com onclick chamando window.parent
                
                # Escapar as aspas dentro do onclick para não quebrar a string f-string
                escaped_anchor_ref = anchor_id_ref.replace("'", "\\'")
                escaped_anchor_bel = anchor_id_bel.replace("'", "\\'")

                html_content_for_iframe = f"""
                <style>
                /* Estilos SÓ para este botão, dentro do iframe */
                .btn-scroll-nav {{
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                    border: none;
                    padding: 12px 24px;
                    border-radius: 8px;
                    cursor: pointer;
                    font-weight: 600;
                    font-size: 14px;
                    margin-bottom: 5px; /* Reduzido para caber melhor */
                    width: 100%;
                    box-shadow: 0 4px 6px rgba(0,0,0,0.1);
                    transition: all 0.3s ease;
                    text-align: center;
                    text-decoration: none;
                    display: inline-block;
                    box-sizing: border-box;
                    user-select: none;
                }}
                .btn-scroll-nav:hover {{
                    transform: translateY(-2px);
                    box-shadow: 0 6px 12px rgba(0,0,0,0.15);
                }}
                .btn-scroll-nav:active {{
                    transform: translateY(0);
                    box-shadow: 0 4px 6px rgba(0,0,0,0.1);
                }}
                .debug-text {{
                     font-size: 11px; color: #666; margin-top: 0px; margin-bottom: 10px; text-align: center;
                }}
                </style>

                <button class="btn-scroll-nav"
                        type="button"
                        onclick="console.log('Botão no IFRAME clicado!'); window.parent.handleBulaScroll('{escaped_anchor_ref}', '{escaped_anchor_bel}');"
                >
                    🎯 Ir para esta seção na visualização lado a lado ⬇️
                </button>
                <p class='debug-text'>
                    💡 Dica: Abra o Console (F12) para ver logs de debug
                </p>
                """

                # Usamos st_html para renderizar o botão com estilo e onclick funcional
                st_html(html_content_for_iframe, height=90) # Ajuste a altura conforme necessário
                # --- [FIM DA MUDANÇA 2] ---

                expander_html_ref = marcar_diferencas_palavra_por_palavra(
                    diff['conteudo_ref'], diff['conteudo_belfar'], eh_referencia=True
                ).replace('\n', '<br>')
                expander_html_belfar = marcar_diferencas_palavra_por_palavra(
                    diff['conteudo_ref'], diff['conteudo_belfar'], eh_referencia=False
                ).replace('\n', '<br>')

                c1, c2 = st.columns(2)
                with c1:
                    st.markdown("**📄 Referência:**")
                    st.markdown(f"<div style='{expander_caixa_style}'>{expander_html_ref}</div>", unsafe_allow_html=True)
                with c2:
                    st.markdown("**📄 BELFAR:**")
                    st.markdown(f"<div style='{expander_caixa_style}'>{expander_html_belfar}</div>", unsafe_allow_html=True)
    else:
        st.success("✅ Conteúdo das seções está idêntico")

    if erros_ortograficos:
        st.info(f"📝 **Possíveis erros ortográficos ({len(erros_ortograficos)} palavras):**\n" + ", ".join(erros_ortograficos))

    if not any([secoes_faltantes, diferencas_conteudo, diferencas_titulos]) and len(erros_ortograficos) < 5:
        st.success("🎉 **Bula aprovada!** Nenhum problema crítico encontrado.")

    st.divider()
    st.subheader("Visualização Lado a Lado com Destaques")
    st.markdown(
        "**Legenda:** <mark style='background-color: #ffff99; padding: 2px;'>Amarelo</mark> = Divergências | "
        "<mark style='background-color: #FFDDC1; padding: 2px;'>Rosa</mark> = Erros ortográficos | "
        "<mark style='background-color: #cce5ff; padding: 2px;'>Azul</mark> = Data ANVISA",
        unsafe_allow_html=True
    )

    html_ref_marcado = marcar_divergencias_html(texto_original=texto_ref, secoes_problema=diferencas_conteudo, erros_ortograficos=[], tipo_bula=tipo_bula, eh_referencia=True).replace('\n', '<br>')
    html_belfar_marcado = marcar_divergencias_html(texto_original=texto_belfar, secoes_problema=diferencas_conteudo, erros_ortograficos=erros_ortograficos, tipo_bula=tipo_bula, eh_referencia=False).replace('\n', '<br>')

    caixa_style = (
        "height: 700px; overflow-y: auto; border: 2px solid #999; border-radius: 4px; "
        "padding: 24px 32px; background-color: #ffffff; "
        "font-family: 'Georgia', 'Times New Roman', serif; font-size: 14px; "
        "line-height: 1.8; box-shadow: 0 2px 12px rgba(0,0,0,0.15); "
        "text-align: justify; color: #000000;"
    )
    col1, col2 = st.columns(2, gap="medium")
    with col1:
        st.markdown(f"**📄 {nome_ref}**")
        # ID do container principal
        st.markdown(f"<div id='container-ref-scroll' style='{caixa_style}'>{html_ref_marcado}</div>", unsafe_allow_html=True)
    with col2:
        st.markdown(f"**📄 {nome_belfar}**")
        # ID do container principal
        st.markdown(f"<div id='container-bel-scroll' style='{caixa_style}'>{html_belfar_marcado}</div>", unsafe_allow_html=True)

# ----------------- INTERFACE -----------------
st.set_page_config(layout="wide", page_title="Auditoria de Bulas", page_icon="🔬")
st.title("🔬 Inteligência Artificial para Auditoria de Bulas")
st.markdown("Sistema avançado de comparação literal e validação de bulas farmacêuticas")
st.divider()

st.header("📋 Configuração da Auditoria")
tipo_bula_selecionado = st.radio("Tipo de Bula:", ("Paciente", "Profissional"), horizontal=True)
col1, col2 = st.columns(2)
with col1:
    st.subheader("📄 Med. Referência")
    pdf_ref = st.file_uploader("Envie o PDF de referência", type="pdf", key="ref")
with col2:
    st.subheader("📄 Med. BELFAR")
    pdf_belfar = st.file_uploader("Envie o PDF Belfar", type="pdf", key="belfar")

if st.button("🔍 Iniciar Auditoria Completa", use_container_width=True, type="primary"):
    if pdf_ref and pdf_belfar:
        with st.spinner("🔄 Processando e analisando as bulas..."):
            texto_ref, erro_ref = extrair_texto(pdf_ref, 'pdf')
            texto_belfar, erro_belfar = extrair_texto(pdf_belfar, 'pdf')

            if not erro_ref:
                texto_ref = truncar_apos_anvisa(texto_ref)
            if not erro_belfar:
                texto_belfar = truncar_apos_anvisa(texto_belfar)

            if erro_ref or erro_belfar:
                st.error(f"Erro ao processar arquivos: {erro_ref or erro_belfar}")
            else:
                gerar_relatorio_final(texto_ref, texto_belfar, "Bula Referência", "Bula BELFAR", tipo_bula_selecionado)
    else:
        st.warning("⚠️ Por favor, envie ambos os arquivos PDF para iniciar a auditoria.")

st.divider()
st.caption("Sistema de Auditoria de Bulas v18.0 | Arquitetura de Mapeamento Final")
