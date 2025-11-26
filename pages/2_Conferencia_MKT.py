# -*- coding: utf-8 -*-

# Aplicativo Streamlit: Auditoria de Bulas (v72 - Força Bruta & Segmentação Numérica)
# - Solução Crítica: Se não encontrar palavras-chave de bula (ex: "PARA QUE"), FORÇA O OCR.
# - Segmentação: Usa os números (1., 2., 3...) para cortar o texto, garantindo que nada fique branco.

import streamlit as st
import fitz  # PyMuPDF
import docx
import re
import spacy
from spellchecker import SpellChecker
import difflib
import unicodedata
import io
from PIL import Image
import pytesseract
from thefuzz import fuzz
import html

# ----------------- UI / CSS -----------------
st.set_page_config(layout="wide", page_title="Auditoria de Bulas v72", page_icon="💊")

GLOBAL_CSS = """
<style>
[data-testid="stHeader"] { display: none !important; }
footer { display: none !important; }

.bula-box {
  height: 550px;
  overflow-y: auto;
  border: 1px solid #ccc;
  border-radius: 6px;
  padding: 20px;
  background: #fdfdfd;
  font-family: "Segoe UI", Arial, sans-serif;
  font-size: 14px;
  line-height: 1.6;
  color: #333;
  white-space: pre-wrap;
}

.section-header {
    background-color: #f0f2f6;
    padding: 10px;
    border-radius: 5px;
    font-weight: bold;
    margin-bottom: 10px;
    border-left: 5px solid #007bff;
}

/* Destaques de Diferença */
mark.diff { background-color: #ffeeba; color: #856404; padding: 0 2px; border-radius: 2px; }
mark.missing { background-color: #f8d7da; color: #721c24; padding: 2px; }
mark.added { background-color: #d4edda; color: #155724; padding: 2px; }

</style>
"""
st.markdown(GLOBAL_CSS, unsafe_allow_html=True)

# ----------------- FERRAMENTAS DE LIMPEZA -----------------

def limpar_sujeira_grafica(texto):
    """Remove artefatos visuais reportados (mm, marcas de corte, telefones)."""
    if not texto: return ""
    
    # Remove acentos para facilitar a limpeza de lixo técnico padronizado
    t = texto
    
    patterns = [
        r"^\s*450\s*$",          # Número de corte solto
        r"\d{1,3}[.,]\d{2}\s*mm", # Medidas (210,00 mm)
        r"\d{1,3}\s*mm\b",       # Medidas simples
        r"[-_]{3,}",             # Linhas longas
        r"(?i)FRENTE\s*$", 
        r"(?i)VERSO\s*$",
        r"1ª PROVA.*",
        r"BELFAR\s*contato",
        r"\d{2}\s*\d{4,5}-\d{4}" # Telefones
    ]
    
    for p in patterns:
        t = re.sub(p, " ", t, flags=re.MULTILINE|re.IGNORECASE)
        
    return t

def normalizar_comparacao(texto):
    """Normaliza removendo tudo que não é letra/número para definir se é DIVERGENTE."""
    if not texto: return ""
    t = unicodedata.normalize('NFD', texto).encode('ascii', 'ignore').decode('utf-8')
    t = re.sub(r'[^a-zA-Z0-9]', '', t.lower())
    return t

# ----------------- ENGINE DE OCR E EXTRAÇÃO -----------------

def executar_ocr(arquivo_bytes):
    """Roda Tesseract com configuração de coluna única para tentar pegar o fluxo."""
    texto = ""
    with fitz.open(stream=io.BytesIO(arquivo_bytes), filetype="pdf") as doc:
        for page in doc:
            pix = page.get_pixmap(dpi=300)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            try:
                # psm 1 = Automatic page segmentation with OSD. 
                # psm 3 = Fully automatic page segmentation, but no OSD. (Geralmente melhor pra bula)
                texto += pytesseract.image_to_string(img, lang='por', config='--psm 3') + "\n"
            except:
                pass
    return texto

def extrair_texto_robusto(arquivo, tipo):
    """
    Tenta ler nativo. Se não achar palavras-chave de bula, FORÇA OCR.
    """
    if not arquivo: return ""
    
    texto = ""
    usou_ocr = False
    arquivo.seek(0)
    b = arquivo.read()
    
    try:
        if tipo == 'pdf':
            # 1. Tenta extração nativa rápida
            with fitz.open(stream=io.BytesIO(b), filetype="pdf") as doc:
                for page in doc:
                    texto += page.get_text() + "\n"
            
            # 2. VERIFICAÇÃO DE SEGURANÇA (A Correção)
            # Normaliza para verificar se leu algo útil
            check = unicodedata.normalize('NFD', texto).lower()
            keywords = ["indicado", "como devo", "quando nao", "quais os males", "dizeres legais", "composicao"]
            
            hits = sum(1 for k in keywords if k in check)
            
            # Se achou menos de 2 termos de bula, assume que o texto é lixo/curvas
            # e roda o OCR por cima.
            if hits < 2:
                texto = executar_ocr(b)
                usou_ocr = True

        elif tipo == 'docx':
            doc = docx.Document(io.BytesIO(b))
            texto = "\n".join([p.text for p in doc.paragraphs])
            
        # Pós-processamento
        texto = texto.replace('\r', '\n')
        texto = limpar_sujeira_grafica(texto)
        
        # Correções de OCR comuns se tiver usado
        if usou_ocr:
            correcoes = {
                r'\|': '', r'I\.': '1.', r'l\.': '1.', 
                r'(?i)belfar': 'BELFAR',
                r'(?i)indica[çc][ãa]o': 'INDICAÇÃO'
            }
            for k, v in correcoes.items():
                texto = re.sub(k, v, texto)
                
        return texto

    except Exception as e:
        return f"Erro fatal: {e}"

# ----------------- SEGMENTAÇÃO POR NUMERAÇÃO (A Prova de Falhas) -----------------

def segmentar_bula(texto_completo):
    """
    Corta o texto procurando explicitamente por '1.', '2.', etc.
    Isso evita que seções fiquem vazias se o título estiver levemente errado.
    """
    secoes_map = {}
    
    # Regex agressivo para achar os inícios de seção (Ex: "1. PARA QUE...")
    # Procura um número, ponto, e texto maiúsculo.
    padrao_secoes = [
        (r"(?:^|\n)\s*1\.?\s*PARA\s*QUE", "1. PARA QUE ESTE MEDICAMENTO É INDICADO?"),
        (r"(?:^|\n)\s*2\.?\s*COMO\s*ESTE", "2. COMO ESTE MEDICAMENTO FUNCIONA?"),
        (r"(?:^|\n)\s*3\.?\s*QUANDO\s*N[ÃA]O", "3. QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?"),
        (r"(?:^|\n)\s*4\.?\s*O\s*QUE\s*DEVO", "4. O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?"),
        (r"(?:^|\n)\s*5\.?\s*ONDE", "5. ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?"),
        (r"(?:^|\n)\s*6\.?\s*COMO\s*DEVO", "6. COMO DEVO USAR ESTE MEDICAMENTO?"),
        (r"(?:^|\n)\s*7\.?\s*O\s*QUE\s*DEVO", "7. O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?"),
        (r"(?:^|\n)\s*8\.?\s*QUAIS\s*OS", "8. QUAIS OS MALES QUE ESTE MEDICAMENTO PODE ME CAUSAR?"),
        (r"(?:^|\n)\s*9\.?\s*O\s*QUE\s*FAZER", "9. O QUE FAZER SE ALGUÉM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?"),
        (r"(?:^|\n)\s*DIZERES\s*LEGAIS", "DIZERES LEGAIS")
    ]
    
    # Encontra as posições de cada seção
    indices = []
    for regex, titulo_padrao in padrao_secoes:
        match = re.search(regex, texto_completo, re.IGNORECASE)
        if match:
            indices.append({'start': match.start(), 'titulo': titulo_padrao})
    
    # Ordena por posição no texto
    indices.sort(key=lambda x: x['start'])
    
    # Corta o texto
    for i in range(len(indices)):
        start = indices[i]['start']
        titulo = indices[i]['titulo']
        
        # O fim desta seção é o começo da próxima
        end = indices[i+1]['start'] if i < len(indices) - 1 else len(texto_completo)
        
        # Pega o conteúdo cru
        raw_content = texto_completo[start:end]
        
        # Remove a primeira linha (que geralmente é o título repetido) para limpar
        linhas = raw_content.split('\n')
        if len(linhas) > 1:
            # Junta tudo menos a primeira linha (título)
            content_clean = "\n".join(linhas[1:]).strip()
        else:
            content_clean = raw_content
            
        secoes_map[titulo] = content_clean
        
    return secoes_map

# ----------------- VISUALIZAÇÃO DE DIFF -----------------

def gerar_html_diff(texto_a, texto_b):
    a = texto_a.split()
    b = texto_b.split()
    matcher = difflib.SequenceMatcher(None, a, b)
    html = []
    
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'replace':
            term = " ".join(b[j1:j2])
            html.append(f"<mark class='diff'>{term}</mark>")
        elif tag == 'delete':
            pass # Não mostra deletados para limpar a vista
        elif tag == 'insert':
            term = " ".join(b[j1:j2])
            html.append(f"<mark class='added'>{term}</mark>")
        elif tag == 'equal':
            html.append(" ".join(b[j1:j2]))
            
    return " ".join(html)

# ----------------- APP PRINCIPAL -----------------

st.title("Auditoria de Bulas v72 (Força Bruta)")
st.caption("Estratégia: Se não ler cabeçalhos, força OCR. Segmenta por números (1, 2, 3...)")
st.divider()

col1, col2 = st.columns(2)
f_ref = col1.file_uploader("1. Arte Vigente (Ref)", key="ref")
f_bel = col2.file_uploader("2. Gráfica (Belfar)", key="bel")

if st.button("🚀 INICIAR COMPARAÇÃO", use_container_width=True, type="primary"):
    if not (f_ref and f_bel):
        st.warning("Anexe os dois arquivos.")
        st.stop()
        
    with st.spinner("Lendo arquivos... (Isso pode demorar se for necessário OCR)"):
        # 1. Extração
        t_ref = extrair_texto_robusto(f_ref, f_ref.name.split('.')[-1].lower())
        t_bel = extrair_texto_robusto(f_bel, f_bel.name.split('.')[-1].lower())
        
        # 2. Segmentação
        map_ref = segmentar_bula(t_ref)
        map_bel = segmentar_bula(t_bel)
        
        # Lista para garantir ordem
        ordem = [
            "1. PARA QUE ESTE MEDICAMENTO É INDICADO?",
            "2. COMO ESTE MEDICAMENTO FUNCIONA?",
            "3. QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?",
            "4. O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?",
            "5. ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?",
            "6. COMO DEVO USAR ESTE MEDICAMENTO?",
            "7. O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?",
            "8. QUAIS OS MALES QUE ESTE MEDICAMENTO PODE ME CAUSAR?",
            "9. O QUE FAZER SE ALGUÉM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?",
            "DIZERES LEGAIS"
        ]
        
        divergencias = 0
        
        for titulo in ordem:
            txt_ref = map_ref.get(titulo, "")
            txt_bel = map_bel.get(titulo, "")
            
            # Validação
            norm_ref = normalizar_comparacao(txt_ref)
            norm_bel = normalizar_comparacao(txt_bel)
            
            status_cor = "green"
            status_txt = "OK"
            
            if not txt_ref and not txt_bel:
                continue # Seção vazia em ambos
                
            if not txt_ref:
                status_cor = "orange"
                status_txt = "ALERTA: Seção Vazia na Referência (Falha de Leitura ou Arte Incompleta)"
                divergencias += 1
            elif not txt_bel:
                status_cor = "red"
                status_txt = "ERRO: Seção Faltante na Gráfica"
                divergencias += 1
            elif norm_ref != norm_bel:
                ratio = fuzz.ratio(norm_ref, norm_bel)
                if ratio > 96:
                    status_cor = "green" # Aceitável (pequenos erros OCR)
                    status_txt = f"OK ({ratio}% Similaridade)"
                else:
                    status_cor = "red"
                    status_txt = f"DIVERGENTE ({ratio}% Similaridade)"
                    divergencias += 1
            
            # Visualização
            icone = "✅" if status_cor == "green" else "❌"
            if status_cor == "orange": icone = "⚠️"
            
            with st.expander(f"{icone} {titulo}", expanded=(status_cor != "green")):
                st.markdown(f"**Status:** :{status_cor}[{status_txt}]")
                c1, c2 = st.columns(2)
                
                with c1:
                    st.caption("Referência")
                    if not txt_ref: st.error("Não foi possível ler esta seção no arquivo original.")
                    st.markdown(f"<div class='bula-box'>{html.escape(txt_ref)}</div>", unsafe_allow_html=True)
                    
                with c2:
                    st.caption("Gráfica")
                    if status_cor == "green":
                         st.markdown(f"<div class='bula-box'>{html.escape(txt_bel)}</div>", unsafe_allow_html=True)
                    else:
                        diff = gerar_html_diff(txt_ref, txt_bel)
                        st.markdown(f"<div class='bula-box'>{diff}</div>", unsafe_allow_html=True)

        if divergencias == 0:
            st.success("Tudo certo! Nenhuma divergência crítica encontrada.")
