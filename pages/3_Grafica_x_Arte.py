# -*- coding: utf-8 -*-

# Aplicativo Streamlit: Auditoria de Bulas (v70 - Correção de Segmentação e Falso Positivo)
# - Correção Principal: Resolve o problema das "Caixas Vazias" na Referência usando busca global de headers.
# - Validação: "Blind Compare" -> Remove formatação/pontuação para decidir se é Verde ou Vermelho.
# - Visual: Se o status for OK, não mostra diff colorido, apenas o texto limpo.

import streamlit as st
import fitz  # PyMuPDF
import docx
import re
import io
from PIL import Image
import pytesseract
from thefuzz import fuzz
import html
import unicodedata

# ----------------- CONFIGURAÇÃO DA PÁGINA -----------------
st.set_page_config(layout="wide", page_title="Auditoria de Bulas v70", page_icon="💊")

CSS = """
<style>
[data-testid="stHeader"] { display: none !important; }
.bula-box {
    height: 500px;
    overflow-y: auto;
    border: 1px solid #ddd;
    border-radius: 5px;
    padding: 20px;
    background: #f9f9f9;
    font-family: 'Segoe UI', sans-serif;
    font-size: 14px;
    line-height: 1.6;
    color: #333;
    white-space: pre-wrap;
}
.status-badge {
    padding: 5px 10px;
    border-radius: 4px;
    font-weight: bold;
    color: white;
    display: inline-block;
    margin-bottom: 10px;
}
.ok { background-color: #28a745; }
.erro { background-color: #dc3545; }
.alerta { background-color: #ffc107; color: #000; }
mark.diff { background-color: #ffcccc; color: #990000; padding: 0 2px; text-decoration: line-through; }
mark.new { background-color: #ccffcc; color: #006600; padding: 0 2px; }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

# ----------------- 1. EXTRAÇÃO E OCR (Mantida a detecção de curvas) -----------------

def verificar_curvas(doc):
    """Verifica se o PDF é imagem (curvas) ou texto."""
    try:
        texto = ""
        for i, page in enumerate(doc):
            if i > 1: break
            texto += page.get_text()
        return len(texto.strip()) < 50
    except:
        return True

def ocr_tesseract(arquivo_bytes):
    texto = ""
    with fitz.open(stream=io.BytesIO(arquivo_bytes), filetype="pdf") as doc:
        for page in doc:
            pix = page.get_pixmap(dpi=200) # DPI médio para velocidade
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            try:
                texto += pytesseract.image_to_string(img, lang='por') + "\n"
            except:
                pass
    return texto

def extrair_texto(arquivo):
    if not arquivo: return ""
    try:
        arquivo.seek(0)
        ext = arquivo.name.split('.')[-1].lower()
        texto = ""
        
        if ext == 'pdf':
            b = arquivo.read()
            with fitz.open(stream=io.BytesIO(b), filetype="pdf") as doc:
                if verificar_curvas(doc):
                    texto = ocr_tesseract(b)
                else:
                    for page in doc:
                        texto += page.get_text() + "\n"
        elif ext == 'docx':
            doc = docx.Document(arquivo)
            texto = "\n".join([p.text for p in doc.paragraphs])
            
        # Limpeza básica inicial
        texto = texto.replace('\r', '\n')
        # Remove lixo de rodapé repetitivo da belfar para não atrapalhar
        texto = re.sub(r'(?i)belfar.*?(\d{2})?\s*mm', '', texto)
        return texto
    except Exception as e:
        return f"Erro: {e}"

# ----------------- 2. SEGMENTAÇÃO ROBUSTA (A SOLUÇÃO) -----------------

def normalizar_titulo(t):
    # Remove tudo que não for letra para comparar titulos
    return re.sub(r'[^a-zA-Z]', '', t).lower()

def segmentar_texto(texto_completo):
    """
    Divide o texto procurando pelos headers obrigatórios.
    Não depende de quebras de linha perfeitas.
    """
    headers_map = {
        "INDICACOES": "1. PARA QUE ESTE MEDICAMENTO É INDICADO?",
        "COMOFUNCIONA": "2. COMO ESTE MEDICAMENTO FUNCIONA?",
        "NAOUSAR": "3. QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?",
        "SABERANTES": "4. O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?",
        "ONDEGUARDAR": "5. ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?",
        "COMOUSAR": "6. COMO DEVO USAR ESTE MEDICAMENTO?",
        "ESQUECER": "7. O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?",
        "MALES": "8. QUAIS OS MALES QUE ESTE MEDICAMENTO PODE ME CAUSAR?",
        "SUPERDOSE": "9. O QUE FAZER SE ALGUÉM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?",
        "DIZERES": "DIZERES LEGAIS"
    }
    
    # Prepara o texto para busca (remove acentos e deixa caixa alta)
    texto_norm = ''.join(c for c in unicodedata.normalize('NFD', texto_completo) if unicodedata.category(c) != 'Mn').upper()
    
    # Mapeia onde começa cada seção
    indices = []
    for chave, titulo_bonito in headers_map.items():
        # Tenta achar o título (aceita variações leves de OCR ou números faltando)
        # Ex: Procura "PARA QUE ESTE MEDICAMENTO"
        termo_busca = normalizar_titulo(titulo_bonito)[1:15].upper() # Pega só "PARAQUEESTEMED"
        
        # Busca no texto normalizado (que só tem letras e números, ou limpo)
        # Como o texto_norm não está limpo de chars, vamos usar busca aproximada no texto bruto
        
        # Estratégia de busca: Regex flexível no texto original
        # Procura: Numeral opcional + pedaço do texto
        keywords = titulo_bonito.replace('?', '').split()[1:5] # ["PARA", "QUE", "ESTE", "MEDICAMENTO"]
        regex = r"(?i)(\d{1,2}\.?\s*)?" + r"\s+".join(keywords)
        
        match = re.search(regex, texto_completo)
        if match:
            indices.append((match.start(), titulo_bonito))
            
    # Ordena pelo aparecimento no texto
    indices.sort(key=lambda x: x[0])
    
    secoes_encontradas = {}
    
    for i in range(len(indices)):
        start_idx = indices[i][0]
        titulo_atual = indices[i][1]
        
        # O fim é o começo da próxima seção ou o fim do texto
        if i < len(indices) - 1:
            end_idx = indices[i+1][0]
        else:
            end_idx = len(texto_completo)
            
        conteudo = texto_completo[start_idx:end_idx]
        
        # Remove a primeira linha (que é o próprio título) para pegar só o corpo
        # Mas faz isso com cuidado
        linhas = conteudo.split('\n')
        # Tenta achar onde termina o título na primeira linha ou segunda
        corpo = "\n".join(linhas[1:]).strip() # Assume que a 1a linha é titulo
        if len(corpo) < 5: # Se ficou vazio, pode ser que o titulo ocupou 2 linhas
             corpo = "\n".join(linhas[2:]).strip()
             
        secoes_encontradas[titulo_atual] = corpo
        
    return secoes_encontradas

# ----------------- 3. COMPARAÇÃO E VISUALIZAÇÃO -----------------

def limpar_sujeira_fina(texto):
    """Remove artefatos visuais reportados (mm, 450, traços)"""
    if not texto: return ""
    t = re.sub(r'450', '', texto)
    t = re.sub(r'\d+,\d+\s*mm', '', t) # 210,00 mm
    t = re.sub(r'[-_]{2,}', '', t) # traços
    t = re.sub(r'^\s*[:\.]\s*$', '', t, flags=re.MULTILINE) # pontos isolados
    return t.strip()

def normalizar_para_status(texto):
    """
    Normalização AGRESSIVA para definir Status (Verde/Vermelho).
    Remove pontuação, acento, espaço. Só compara LETRAS.
    """
    if not texto: return ""
    # Remove acentos
    t = ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')
    # Só letras minúsculas
    t = re.sub(r'[^a-z]', '', t.lower())
    return t

def gerar_diff_html(ref, bel):
    import difflib
    a = ref.split()
    b = bel.split()
    matcher = difflib.SequenceMatcher(None, a, b)
    html_out = []
    
    for opcode, a0, a1, b0, b1 in matcher.get_opcodes():
        if opcode == 'equal':
            html_out.append(" ".join(b[b0:b1]))
        elif opcode == 'insert':
            html_out.append(f"<mark class='new'>{' '.join(b[b0:b1])}</mark>")
        elif opcode == 'delete':
            # Opcional: mostrar o que foi deletado (riscado)
            # html_out.append(f"<mark class='diff'>{' '.join(a[a0:a1])}</mark>")
            pass
        elif opcode == 'replace':
            html_out.append(f"<mark class='new'>{' '.join(b[b0:b1])}</mark>")
            
    return " ".join(html_out)

# ----------------- MAIN APP -----------------

st.title("Validador de Bulas v70")
st.markdown("**Foco:** Preencher as seções vazias e ignorar diferenças de pontuação.")
st.divider()

col1, col2 = st.columns(2)
file_ref = col1.file_uploader("1. Referência (Word/PDF)", key="ref")
file_bel = col2.file_uploader("2. Gráfica (PDF)", key="bel")

if st.button("🔍 Comparar Arquivos", type="primary", use_container_width=True):
    if not file_ref or not file_bel:
        st.warning("Anexe os dois arquivos.")
        st.stop()
        
    with st.spinner("Lendo e Segmentando..."):
        # 1. Leitura
        txt_ref = extrair_texto(file_ref)
        txt_bel = extrair_texto(file_bel)
        
        # 2. Segmentação
        map_ref = segmentar_texto(txt_ref)
        map_bel = segmentar_texto(txt_bel)
        
        # Lista padrão de seções para iterar
        secoes_ordem = [
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
        
        # Métricas
        total_divergencias = 0
        
        for sec in secoes_ordem:
            # Obtém conteúdo cru
            conteudo_ref = limpar_sujeira_fina(map_ref.get(sec, ""))
            conteudo_bel = limpar_sujeira_fina(map_bel.get(sec, ""))
            
            # Normaliza para decisão de status
            norm_ref = normalizar_para_status(conteudo_ref)
            norm_bel = normalizar_para_status(conteudo_bel)
            
            # Lógica de Status
            status = "OK"
            cor = "ok"
            
            if not conteudo_ref and not conteudo_bel:
                continue # Seção vazia em ambos, pula
                
            if not conteudo_ref and conteudo_bel:
                status = "ERRO: Seção não encontrada na Referência"
                cor = "alerta"
                total_divergencias += 1
            elif not conteudo_bel:
                status = "ERRO: Seção não encontrada na Gráfica"
                cor = "erro"
                total_divergencias += 1
            elif norm_ref != norm_bel:
                # Fuzzy check para tolerar errinhos minimos de OCR (ex: 1 letra trocada)
                ratio = fuzz.ratio(norm_ref, norm_bel)
                if ratio > 97:
                    status = "OK (Diferenças Irrelevantes)"
                    cor = "ok"
                else:
                    status = f"DIVERGENTE ({ratio}% similaridade)"
                    cor = "erro"
                    total_divergencias += 1
            
            # Exibição
            with st.expander(f"{sec}", expanded=(cor != "ok")):
                st.markdown(f"<span class='status-badge {cor}'>{status}</span>", unsafe_allow_html=True)
                
                c1, c2 = st.columns(2)
                
                with c1:
                    st.markdown("**Texto Original (Referência):**")
                    if not conteudo_ref:
                        st.warning("⚠️ Texto não detectado. O título está escrito exatamente como na bula padrão?")
                    st.markdown(f"<div class='bula-box'>{html.escape(conteudo_ref)}</div>", unsafe_allow_html=True)
                
                with c2:
                    st.markdown("**Texto Gráfica:**")
                    # Se for OK, mostra texto limpo. Se for Erro, mostra Diff.
                    if cor == "ok":
                        st.markdown(f"<div class='bula-box'>{html.escape(conteudo_bel)}</div>", unsafe_allow_html=True)
                    else:
                        diff_view = gerar_diff_html(conteudo_ref, conteudo_bel)
                        st.markdown(f"<div class='bula-box'>{diff_view}</div>", unsafe_allow_html=True)

        if total_divergencias == 0:
            st.success("✅ Nenhuma divergência crítica encontrada!")
