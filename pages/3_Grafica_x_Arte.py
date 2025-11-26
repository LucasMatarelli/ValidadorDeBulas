# -*- coding: utf-8 -*-

# Aplicativo Streamlit: Auditoria de Bulas (v69 - A Definitiva)
# - Correção Fatal: Fail-over automático para OCR se o texto vier vazio/quebrado.
# - Limpeza: Regex atualizado com base nos logs (remove mm, marcas de corte, 450).
# - Comparação: Ignora pontuação/formatação na validação de status (reduz falso positivo).

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
from collections import namedtuple
import html

# ----------------- CONFIGURAÇÕES GERAIS -----------------
st.set_page_config(layout="wide", page_title="Auditoria de Bulas v69", page_icon="🛡️")

GLOBAL_CSS = """
<style>
[data-testid="stHeader"] { display: none !important; }
footer { display: none !important; }

.bula-box {
  height: 600px;
  overflow-y: auto;
  border: 1px solid #dcdcdc;
  border-radius: 8px;
  padding: 25px;
  background: #ffffff;
  font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif;
  font-size: 15px;
  line-height: 1.8;
  color: #222;
  text-align: justify;
  white-space: pre-wrap;
}

.section-title {
  font-size: 16px;
  font-weight: 800;
  color: #1a1a1a;
  margin: 20px 0 15px;
  border-bottom: 2px solid #eee;
  padding-bottom: 8px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

/* Destaques */
mark.diff { background-color: #ffff99; padding: 2px 0; border-radius: 2px; font-weight: 600; }
mark.ort { background-color: #ffdfd9; padding: 0 2px; text-decoration: underline wavy #ff5555; }
mark.anvisa { background-color: #cce5ff; color: #004085; padding: 2px 6px; font-weight: 800; border-radius: 4px; border: 1px solid #b8daff; }
.status-ok { color: #28a745; font-weight: bold; }
.status-err { color: #dc3545; font-weight: bold; }
</style>
"""
st.markdown(GLOBAL_CSS, unsafe_allow_html=True)

# ----------------- FERRAMENTAS DE TEXTO -----------------

def normalizar_para_comparacao_rigida(texto):
    """
    Remove TUDO que não é letra ou número para comparação de STATUS.
    Isso evita que uma vírgula ou espaço a mais acuse 'DIVERGENTE'.
    """
    if not texto: return ""
    # Remove acentos
    t = ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')
    # Remove pontuação e espaços extras, deixa só alfanumérico minúsculo
    t = re.sub(r'[^a-z0-9]', '', t.lower())
    return t

def limpar_lixo_grafica_belfar(texto: str) -> str:
    """Regex cirúrgico para remover artefatos da Belfar e marcas de corte."""
    if not texto: return ""
    
    padroes_lixo = [
        # --- Artefatos Específicos do Log ---
        r"^\s*[-–—_]\s*$",       # Linhas só com traço
        r"^\s*[:;]\s*$",         # Linhas só com dois pontos
        r"\b450\b",              # Número solto comum em marca de corte
        r"\d{1,3}[.,]\d{2}\s*mm\s*-?", # Ex: 210,00 mm, 30,00 mm-
        r"\d{1,3}\s*mm\b",       # Ex: 150 mm
        
        # --- Cabeçalhos/Rodapés Técnicos ---
        r"(?i)FRENTE\s*$",
        r"(?i)VERSO\s*$",
        r"(?i)Tipologia da bula.*",
        r"(?i)BELSPAN.*",
        r"(?i)BELFAR.*",         # Cuidado: pode remover o nome da empresa no rodapé, mas é necessário para limpar a arte
        r"BUL\d+[A-Z0-9]*",      # Códigos de bula ex: BUL22122V03
        r"(?i)Medida da bula:.*",
        r"(?i)Impressão:.*",
        r"(?i)Papel:.*",
        r"(?i)Cor:.*",
        r"(?i)1ª PROVA.*",       # Identificador de prova gráfica
        r"(?i)contato:.*",
        r"\d{2}\s*\d{4,5}-\d{4}", # Telefones soltos
        r"artes@belfar.*",
        
        # --- Sujeira de OCR ---
        r"^\s*[.,]\s*$",         # Pontos isolados
        r"^\s*\|\s*$",           # Barras isoladas
        r"q\.?\s*s\.?\s*p\.?",   # q.s.p (às vezes atrapalha, mas se for título ok, aqui removemos se estiver solto)
    ]
    
    # Executa limpeza
    for padrao in padroes_lixo:
        texto = re.sub(padrao, " ", texto, flags=re.IGNORECASE|re.MULTILINE)
        
    return texto

def corrigir_erros_ocr_comuns(texto: str) -> str:
    if not texto: return ""
    correcoes = {
        r"€": "e", 
        r"(?i)\binbem\b": "inibem", 
        r"(?i)\b3elspan\b": "Belspan", 
        r"(?i)\b1lfar\b": "Belfar", 
        r"(?i)\b3elcomplex\b": "Belcomplex",
        r"(\d+),\s+(\d+)": r"\1,\2", # Corrige espaço após vírgula em números (4, 08 -> 4,08)
        r"m\s*g\b": "mg", # m g -> mg
        r"m\s*l\b": "ml", # m l -> ml
    }
    for padrao, correcao in correcoes.items():
        texto = re.sub(padrao, correcao, texto, flags=re.MULTILINE)
    return texto

def fluir_texto(texto: str) -> str:
    """Reconstroi o fluxo do texto após a remoção dos artefatos."""
    linhas = texto.split('\n')
    novo_texto = []
    buffer = ""
    
    for linha in linhas:
        linha = linha.strip()
        if not linha:
            if buffer:
                novo_texto.append(buffer)
                buffer = ""
            continue # Ignora linhas vazias múltiplas
        
        # Se for tópico (1., •, -) ou título UPPERCASE curto, força quebra
        if re.match(r'^(\d+\.|[-•*])\s+', linha) or (linha.isupper() and len(linha) < 60 and not buffer.endswith(',')):
            if buffer: novo_texto.append(buffer)
            buffer = linha
        else:
            # Junta com a anterior
            if buffer:
                if buffer.endswith('-'):
                    buffer = buffer[:-1] + linha
                else:
                    buffer += " " + linha
            else:
                buffer = linha
            
    if buffer: novo_texto.append(buffer)
    return "\n\n".join(novo_texto) # Usa quebra dupla para parágrafos

# ----------------- ENGINE DE EXTRAÇÃO (FAIL-SAFE) -----------------

def executar_ocr(arquivo_bytes):
    """OCR robusto via Tesseract."""
    texto_ocr = ""
    with fitz.open(stream=io.BytesIO(arquivo_bytes), filetype="pdf") as doc:
        for page in doc:
            pix = page.get_pixmap(dpi=300) # Alta resolução
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            # psm 3 é bom para detectar colunas automaticamente, comum em bulas
            try:
                texto_ocr += pytesseract.image_to_string(img, lang='por', config='--psm 3') + "\n"
            except Exception as e:
                print(f"Erro Tesseract: {e}")
    return texto_ocr

def extrair_texto_definitivo(arquivo, tipo_arquivo):
    if arquivo is None: return "", f"Arquivo {tipo_arquivo} ausente."
    
    try:
        arquivo.seek(0)
        arquivo_bytes = arquivo.read()
        texto = ""
        usou_ocr = False
        
        if tipo_arquivo == 'pdf':
            # 1. Tenta extração nativa
            with fitz.open(stream=io.BytesIO(arquivo_bytes), filetype="pdf") as doc:
                text_native = ""
                for page in doc:
                    text_native += page.get_text("text") + "\n"
            
            # 2. Avalia qualidade da extração nativa
            # Se tiver menos de 100 caracteres ou muitos caracteres estranhos, considera FALHA
            chars_validos = re.sub(r'[^a-zA-Z0-9ãõéíáóúç]', '', text_native)
            
            if len(chars_validos) < 100:
                # FALHA DETECTADA -> Aciona OCR (Fail-Safe)
                texto = executar_ocr(arquivo_bytes)
                usou_ocr = True
            else:
                texto = text_native

        elif tipo_arquivo == 'docx':
            doc = docx.Document(io.BytesIO(arquivo_bytes))
            texto = "\n".join([p.text for p in doc.paragraphs])
        
        # Pós-Processamento Obrigatório
        if texto:
            texto = texto.replace('\r', '\n')
            texto = limpar_lixo_grafica_belfar(texto)
            if usou_ocr:
                texto = corrigir_erros_ocr_comuns(texto)
            
            # Remove cabeçalhos repetidos que sobraram
            texto = re.sub(r'Belcomplex B\s+mononitrato.*', '', texto, flags=re.IGNORECASE) 
            
            texto = fluir_texto(texto)
            
        return texto, None
        
    except Exception as e:
        return "", f"Erro fatal ao ler arquivo: {e}"

# ----------------- LÓGICA DE SEÇÕES -----------------

def normalizar_titulo(texto):
    if not texto: return ""
    t = ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')
    t = re.sub(r'[^a-zA-Z]', '', t).lower()
    return t

def encontrar_secoes(texto_completo):
    """
    Mapeia o texto baseado nos títulos obrigatórios da Anvisa.
    Usa Fuzzy Matching para tolerar erros de OCR nos títulos.
    """
    secoes_padrao = [
        "PARA QUE ESTE MEDICAMENTO E INDICADO",
        "COMO ESTE MEDICAMENTO FUNCIONA",
        "QUANDO NAO DEVO USAR ESTE MEDICAMENTO",
        "O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO",
        "ONDE COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO",
        "COMO DEVO USAR ESTE MEDICAMENTO",
        "O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO",
        "QUAIS OS MALES QUE ESTE MEDICAMENTO PODE ME CAUSAR",
        "O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO",
        "DIZERES LEGAIS"
    ]
    
    # Pré-processa o texto para busca de títulos
    linhas = texto_completo.split('\n\n')
    mapa = {}
    
    idx_atual = 0
    titulo_atual = "INICIO"
    conteudo_buffer = []
    
    # Varredura inteligente
    for linha in linhas:
        linha_clean = normalizar_titulo(linha)
        # Verifica se a linha é um título
        encontrou_titulo = None
        melhor_score = 0
        
        for sec in secoes_padrao:
            sec_clean = normalizar_titulo(sec)
            # Score alto necessário (90+)
            score = fuzz.ratio(linha_clean, sec_clean)
            
            # Match perfeito ou numérico (Ex: "1. PARA QUE...")
            match_num = re.search(r'^\d+\.?\s*' + re.escape(sec[:10]), normalizar_titulo(linha), re.I)
            
            if score > 85 or match_num:
                if score > melhor_score:
                    melhor_score = score
                    encontrou_titulo = sec
        
        if encontrou_titulo:
            # Salva o buffer anterior
            if titulo_atual:
                mapa[titulo_atual] = "\n\n".join(conteudo_buffer).strip()
            # Inicia nova seção
            titulo_atual = encontrou_titulo
            conteudo_buffer = []
        else:
            conteudo_buffer.append(linha)
            
    # Salva o último
    if titulo_atual:
        mapa[titulo_atual] = "\n\n".join(conteudo_buffer).strip()
        
    return mapa

# ----------------- ENGINE DE COMPARAÇÃO -----------------

def comparar_secoes(ref_map, bel_map):
    secoes_ordem = [
        "PARA QUE ESTE MEDICAMENTO E INDICADO",
        "COMO ESTE MEDICAMENTO FUNCIONA",
        "QUANDO NAO DEVO USAR ESTE MEDICAMENTO",
        "O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO",
        "ONDE COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO",
        "COMO DEVO USAR ESTE MEDICAMENTO",
        "O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO",
        "QUAIS OS MALES QUE ESTE MEDICAMENTO PODE ME CAUSAR",
        "O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO",
        "DIZERES LEGAIS"
    ]
    
    resultados = []
    
    for sec in secoes_ordem:
        txt_ref = ref_map.get(sec, "")
        txt_bel = bel_map.get(sec, "")
        
        # Comparação Rígida (Semântica)
        # Removemos pontuação para o Status.
        clean_ref = normalizar_para_comparacao_rigida(txt_ref)
        clean_bel = normalizar_para_comparacao_rigida(txt_bel)
        
        status = "OK"
        if not txt_bel and txt_ref:
            status = "FALTANTE"
        elif clean_ref != clean_bel:
            # Tolerância extra: Fuzzy Ratio no texto limpo > 98%
            if fuzz.ratio(clean_ref, clean_bel) > 98:
                status = "OK" # É apenas sujeira mínima
            else:
                status = "DIVERGENTE"
        
        if not txt_ref: status = "INFO" # Seção que não existe na Ref (ex: rodapés extras)
        
        resultados.append({
            "titulo": sec,
            "ref": txt_ref,
            "bel": txt_bel,
            "status": status
        })
        
    return resultados

def gerar_html_diff(texto1, texto2):
    """Gera visualização de diferenças mantendo pontuação para leitura humana."""
    d = difflib.SequenceMatcher(None, texto1.split(), texto2.split())
    html_out = []
    for tag, i1, i2, j1, j2 in d.get_opcodes():
        if tag == 'replace':
            old = " ".join(texto1.split()[i1:i2])
            new = " ".join(texto2.split()[j1:j2])
            html_out.append(f"<mark class='diff' title='Era: {old}'>{new}</mark>")
        elif tag == 'delete':
            pass # Não mostra o que foi deletado da Ref, foca no que está na Bula
        elif tag == 'insert':
            new = " ".join(texto2.split()[j1:j2])
            html_out.append(f"<mark class='diff'>{new}</mark>")
        elif tag == 'equal':
            html_out.append(" ".join(texto2.split()[j1:j2]))
    return " ".join(html_out)

# ----------------- MAIN UI -----------------

st.title("🛡️ Validador de Bulas Infalível (v69)")
st.caption("Sistema de Auditoria com Fail-Safe de OCR e Limpeza Cirúrgica")
st.divider()

c1, c2 = st.columns(2)
f_ref = c1.file_uploader("1. Arte Vigente (Word/PDF)", key="f1")
f_bel = c2.file_uploader("2. Arquivo da Gráfica (PDF)", key="f2")

if st.button("🚀 VALIDAR AGORA", type="primary", use_container_width=True):
    if not (f_ref and f_bel):
        st.warning("Por favor, anexe os dois arquivos.")
        st.stop()
        
    with st.spinner("Processando... (Isso pode levar alguns segundos se o OCR for ativado)"):
        # 1. Extração
        txt_ref, err1 = extrair_texto_definitivo(f_ref, f_ref.name.split('.')[-1])
        txt_bel, err2 = extrair_texto_definitivo(f_bel, f_bel.name.split('.')[-1])
        
        if err1 or err2:
            st.error(f"Erro na leitura: {err1} {err2}")
            st.stop()
            
        # 2. Segmentação
        map_ref = encontrar_secoes(txt_ref)
        map_bel = encontrar_secoes(txt_bel)
        
        # 3. Comparação
        analise = comparar_secoes(map_ref, map_bel)
        
        # 4. Cálculo de Score
        total = len(analise)
        ok = len([x for x in analise if x['status'] == 'OK'])
        score = (ok / total * 100) if total > 0 else 0
        
        # 5. Exibição
        st.metric("Índice de Conformidade", f"{score:.1f}%")
        
        for item in analise:
            cor_icon = "🟢" if item['status'] == "OK" else "🔴"
            if item['status'] == "FALTANTE": cor_icon = "⚠️"
            if item['status'] == "INFO": cor_icon = "ℹ️"
            
            with st.expander(f"{cor_icon} {item['titulo']} - [{item['status']}]"):
                col_a, col_b = st.columns(2)
                
                with col_a:
                    st.markdown("**Texto Vigente (Referência):**")
                    st.markdown(f"<div class='bula-box'>{html.escape(item['ref'])}</div>", unsafe_allow_html=True)
                
                with col_b:
                    st.markdown("**Texto Gráfica (Validado):**")
                    # Se tiver erro, mostra diff, se não, mostra limpo
                    if item['status'] != "OK":
                        diff_html = gerar_html_diff(item['ref'], item['bel'])
                        st.markdown(f"<div class='bula-box'>{diff_html}</div>", unsafe_allow_html=True)
                    else:
                        st.markdown(f"<div class='bula-box'>{html.escape(item['bel'])}</div>", unsafe_allow_html=True)
