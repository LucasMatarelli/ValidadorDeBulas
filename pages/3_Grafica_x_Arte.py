# -*- coding: utf-8 -*-

# Aplicativo Streamlit: Auditoria de Bulas (v62 - Dizeres Legais Ajustados)
# - Ajuste: Regex da Data Anvisa mais robusto (aceita espaços '17 / 04 / 2024').
# - Visual: Garante o marca-texto AZUL na data.
# - Corte: Corta o texto exatamente após o ano da data da Anvisa.

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

# ----------------- UI / CSS -----------------
st.set_page_config(layout="wide", page_title="Auditoria de Bulas", page_icon="🔬")

GLOBAL_CSS = """
<style>
[data-testid="stHeader"] { display: none !important; }
footer { display: none !important; }

.bula-box {
  height: 550px;
  overflow-y: auto;
  border: 1px solid #dcdcdc;
  border-radius: 8px;
  padding: 25px;
  background: #ffffff;
  font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif;
  font-size: 15px;
  line-height: 1.7;
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

/* Destaque Amarelo (Divergência) */
mark.diff { background-color: #ffff99; padding: 2px 4px; border-radius: 3px; font-weight: 600; }

/* Destaque Rosa (Ortografia) */
mark.ort { background-color: #ffdfd9; padding: 2px 4px; border-radius: 3px; text-decoration: underline wavy #ff5555; }

/* Destaque Azul (Data Anvisa) */
mark.anvisa { background-color: #cce5ff; color: #004085; padding: 2px 6px; font-weight: 800; border-radius: 4px; border: 1px solid #b8daff; }

.stExpander > div[role="button"] { font-weight: 600; color: #333; font-size: 15px; }
.ref-title { color: #005a9c; } 
.bel-title { color: #2e7d32; } 
</style>
"""
st.markdown(GLOBAL_CSS, unsafe_allow_html=True)


# ----------------- MODELO NLP -----------------
@st.cache_resource
def carregar_modelo_spacy():
    try:
        return spacy.load("pt_core_news_lg")
    except OSError:
        return None

nlp = carregar_modelo_spacy()


# ----------------- FUNÇÕES DE LIMPEZA E OCR -----------------

def limpar_lixo_grafica_belfar(texto: str) -> str:
    """Remove especificamente o lixo técnico da gráfica Belfar e marcas de corte."""
    if not texto: return ""
    
    padroes_lixo = [
        r"BUL\s*BELSPAN\s*COMPRIMIDO.*",
        r"BUL\d+V\d+",
        r"(?i)Medida da bula:.*",
        r"(?i)Impressão:.*",
        r"(?i)Papel: Ap.*",
        r"(?i)BELSPAN: Times New Roman.*",
        r"(?i)Cor: Preta.*",
        r"(?i)Normal e Negrito.*",
        r"(?i)Negrito\. Corpo \d+",
        r"(?i)BELFAR\s*contato",
        r"\(31\) 3514-\s*2900",
        r"artes.?belfar\.? ?com\.? ?br", 
        r"\d+a\s*prova.*", 
        r"e?[-—_]{5,}\s*190\s*mm.*",
        r"190\s*mm\s*>>",
        r"45\s*[.,]\s*0\s*cm",
        r"4\s*[.,]\s*0\s*cm",
        r"(?i)gm\s*>\s*>\s*>",
        r"(?i)FRENTE\s*Tipologia.*",
        r"^\s*450\s*$",
        r"^\s*-\s*-\s*-\s*gm\s*>.*",
        r"^\s*-\s*$",
        r"^\s*:\s*$",
        r"\|",
        r"(?i)mem\s*CSA", 
        r"p\s*\*\*\s*1",
        r"q\.\s*s\.\s*p\s*\*\*",
    ]
    
    for padrao in padroes_lixo:
        texto = re.sub(padrao, "", texto, flags=re.IGNORECASE|re.MULTILINE)
        
    return texto

def corrigir_erros_ocr_comuns(texto: str) -> str:
    if not texto: return ""
    correcoes = {
        r"€": "e", 
        r"(?i)\binbem\b": "inibem", r"(?i)\b(3|1)lfar\b": "Belfar", r"(?i)\bBeifar\b": "Belfar",
        r"(?i)\b3elspan\b": "Belspan", r"(?i)\barto\b": "parto", r"(?i)\bausar\b": "causar",
        r"(?i)\bcações\b": "reações", r"(?i)\becomendada\b": "recomendada", r"(?i)\beduzir\b": "reduzir",
        r"(?i)\belacionados\b": "relacionados", r"(?i)\bidministrado\b": "administrado",
        r"(?i)\biparelho\b": "aparelho", r"(?i)\bjangramento\b": "sangramento", r"(?i)\bjerivados\b": "derivados",
        r"(?i)\bjode\b": "pode", r"(?i)\blentro\b": "dentro", r"(?i)\bloses\b": "doses",
        r"(?i)\bmecicamentos\b": "medicamentos", r"(?i)\bnais\b": "mais", r"(?i)\bnedicamentos\b": "medicamentos",
        r"(?i)\bnterações\b": "interações", r"(?i)\bompensarem\b": "compensarem", r"(?i)\bomprimido\b": "comprimido",
        r"(?i)\bontém\b": "contém", r"(?i)\bratamento\b": "tratamento", r"(?i)\brave\b": "grave",
        r"(?i)\bravidez\b": "gravidez", r"(?i)\breas\b": "áreas", r"(?i)\brincipalmente\b": "principalmente",
        r"(?i)\broblemas\b": "problemas", r"(?i)\brávidas\b": "grávidas", r"(?i)\bslaucoma\b": "glaucoma",
        r"(?i)\bNAO\b": "NÃO", r"(?i)\bCOMPOSIÇAO\b": "COMPOSIÇÃO", r"(?i)\bJevido\b": "Devido",
        r"(?i)\bjue\b": "que", r"(?i)\bjacientes\b": "pacientes", r"(?i)\bocê\b": "você",
        r"(?i)\basos\b": "casos", r"(?i)\b1so\b": "uso", r"(?i)\bjaracetamol\b": "paracetamol",
        r"(?i)\beguindo\b": "seguindo", r"(?i)\bituações\b": "situações", r"(?i)\bressão\b": "pressão",
        r"(?i)\bjortadores\b": "portadores", r"(?i)\bjossuem\b": "possuem", r"(?i)\blérgica\b": "alérgica",
        r"(?i)\bmediatamente\b": "imediatamente", r"(?i)\bAcido acetilsalicílico\b": "Ácido acetilsalicílico",
        r"(?i)\bse ALGUM usar\b": "se ALGUÉM usar", r"(?i)\blipirona\b": "dipirona",
        r"\s+mm\b": "", r"\s+mma\b": "",
        r"\bMM\b": "", r"\bEE\b": "", r"\bpe\b": "" 
    }
    for padrao, correcao in correcoes.items():
        texto = re.sub(padrao, correcao, texto, flags=re.MULTILINE)
    return texto

def consertar_titulos_quebrados(texto: str) -> str:
    """Junta títulos que quebraram de linha sem duplicar texto."""
    texto = re.sub(r"(?i)(DEVO USAR ESTE)\s*\n\s*\1", r"\1", texto)
    texto = re.sub(r"(?i)(QUANDO NÃO DEVO USAR ESTE)\s*\n\s*(MEDICAMENTO\?)", r"\1 \2", texto)
    texto = re.sub(r"(?i)(O QUE DEVO SABER ANTES DE USAR ESTE)\s*\n\s*(MEDICAMENTO\?)", r"\1 \2", texto)
    texto = re.sub(r"(?i)(INDICADA)\s*\n\s*(DESTE MEDICAMENTO\?)", r"\1 \2", texto)
    return texto

def fluir_texto(texto: str) -> str:
    """Justifica o texto removendo quebras de linha desnecessárias."""
    linhas = texto.split('\n')
    novo_texto = []
    buffer = ""
    
    for linha in linhas:
        linha = linha.strip()
        if not linha:
            if buffer:
                novo_texto.append(buffer)
                buffer = ""
            novo_texto.append("") 
            continue
        
        if buffer and len(linha) > 0 and linha[0].islower():
            buffer += " " + linha
        elif buffer and buffer.endswith("-"):
            buffer = buffer[:-1] + linha
        elif re.match(r'^[-•*]\s+', linha) or re.match(r'^\d+\.', linha):
            if buffer: novo_texto.append(buffer)
            buffer = linha
        elif buffer and not re.search(r'[.!?:;]$', buffer):
             buffer += " " + linha
        else:
            if buffer: novo_texto.append(buffer)
            buffer = linha
            
    if buffer: novo_texto.append(buffer)
    return "\n".join(novo_texto)

def executar_ocr(arquivo_bytes):
    """Executa OCR."""
    texto_ocr = ""
    with fitz.open(stream=io.BytesIO(arquivo_bytes), filetype="pdf") as doc:
        for page in doc:
            pix = page.get_pixmap(dpi=300)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            try:
                texto_ocr += pytesseract.image_to_string(img, lang='por', config='--psm 3') + "\n"
            except:
                pass
    return texto_ocr

# ----------------- EXTRAÇÃO -----------------

def extrair_texto_inteligente(arquivo, tipo_arquivo):
    if arquivo is None: return "", f"Arquivo {tipo_arquivo} não enviado."

    try:
        arquivo.seek(0)
        arquivo_bytes = arquivo.read()
        texto = ""
        usou_ocr = False

        if tipo_arquivo == 'pdf':
            with fitz.open(stream=io.BytesIO(arquivo_bytes), filetype="pdf") as doc:
                for page in doc:
                    texto += page.get_text("text", sort=True) + "\n"
            
            # Verifica se precisa de OCR
            texto_teste = re.sub(r'\s+', '', texto)
            if len(texto_teste) < 100:
                usou_ocr = True
                texto = executar_ocr(arquivo_bytes)

        elif tipo_arquivo == 'docx':
            doc = docx.Document(io.BytesIO(arquivo_bytes))
            texto = "\n".join([p.text for p in doc.paragraphs])

        if texto:
            invis = ['\u00AD', '\u200B', '\u200C', '\u200D', '\uFEFF']
            for c in invis: texto = texto.replace(c, '')
            texto = texto.replace('\r\n', '\n').replace('\r', '\n')
            
            # 1. Remove Lixo
            texto = limpar_lixo_grafica_belfar(texto)
            # 2. Corrige OCR
            texto = corrigir_erros_ocr_comuns(texto)
            # 3. Conserta Títulos
            texto = consertar_titulos_quebrados(texto)
            # 4. Formata Fluido
            texto = fluir_texto(texto)
            
            texto = texto.strip()
            
        return texto, None
    except Exception as e:
        return "", f"Erro: {e}"

def truncar_apos_anvisa(texto):
    """
    Corta o texto APÓS a data da Anvisa, mantendo a data.
    Regex mais robusto para aceitar espaços (31 / 10 / 2025).
    """
    if not isinstance(texto, str): return texto
    # Regex que aceita espaços entre os números e barras/pontos
    rx = r"(?:aprovad[ao]\s+pela\s+anvisa\s+em|data\s+de\s+aprovação\s+na\s+anvisa:?)\s*[\d]{1,2}\s*[./-]\s*[\d]{1,2}\s*[./-]\s*[\d]{2,4}"
    m = re.search(rx, texto, re.IGNORECASE)
    if m:
        # Retorna até o fim da data encontrada
        return texto[:m.end()]
    return texto

# ----------------- SEÇÕES -----------------
def obter_secoes_paciente():
    return [
        "APRESENTAÇÕES", "COMPOSIÇÃO", "PARA QUE ESTE MEDICAMENTO É INDICADO",
        "COMO ESTE MEDICAMENTO FUNCIONA?", "QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?",
        "O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?",
        "ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?",
        "COMO DEVO USAR ESTE MEDICAMENTO?",
        "O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?",
        "QUAIS OS MALES QUE ESTE MEDICAMENTO PODE CAUSAR?",
        "O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?",
        "DIZERES LEGAIS"
    ]

def obter_aliases_secao():
    return {
        "INDICAÇÕES": "PARA QUE ESTE MEDICAMENTO É INDICADO",
        "CONTRAINDICAÇÕES": "QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?",
        "POSOLOGIA E MODO DE USAR": "COMO DEVO USAR ESTE MEDICAMENTO?",
        "REAÇÕES ADVERSAS": "QUAIS OS MALES QUE ESTE MEDICAMENTO PODE CAUSAR?",
        "SUPERDOSE": "O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?",
        "CUIDADOS DE ARMAZENAMENTO DO MEDICAMENTO": "ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?"
    }

def normalizar_titulo_para_comparacao(texto):
    texto = '' if texto is None else texto
    t = ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')
    t = re.sub(r'[^\w\s]', '', t)
    t = re.sub(r'^\s*(\d{1,2})\s*[\.\)\-]?\s*', '', t).strip().lower()
    return t

def _create_anchor_id(secao_nome, prefix):
    norm = normalizar_titulo_para_comparacao(secao_nome)
    return f"anchor-{prefix}-{norm.replace(' ', '-')}"

# ----------------- MAPEAMENTO -----------------
HeadingCandidate = namedtuple("HeadingCandidate", ["index", "raw", "norm", "numeric", "matched_canon", "score"])

def construir_heading_candidates(linhas, secoes_esperadas, aliases):
    titulos_possiveis = {}
    for s in secoes_esperadas: titulos_possiveis[s] = s
    for a, c in aliases.items():
        if c in secoes_esperadas: titulos_possiveis[a] = c
    titulos_norm = {k: normalizar_titulo_para_comparacao(k) for k in titulos_possiveis.keys()}
    candidates = []
    for i, linha in enumerate(linhas):
        raw = (linha or "").strip()
        if not raw: continue
        norm = normalizar_titulo_para_comparacao(raw)
        best_score = 0
        best_canon = None
        mnum = re.match(r'^\s*(\d{1,2})\s*[\.\)\-]?\s*(.*)$', raw)
        numeric = int(mnum.group(1)) if mnum else None
        
        for titulo_possivel, titulo_canonico in titulos_possiveis.items():
            t_norm = titulos_norm.get(titulo_possivel, "")
            if not t_norm: continue
            score = fuzz.token_set_ratio(t_norm, norm)
            if t_norm == norm: score = 100
            if score > best_score:
                best_score = score
                best_canon = titulo_canonico

        is_candidate = False
        if numeric is not None: is_candidate = True
        elif best_score >= 90: is_candidate = True
        
        if is_candidate:
            candidates.append(HeadingCandidate(index=i, raw=raw, norm=norm, numeric=numeric, matched_canon=best_canon if best_score >= 85 else None, score=best_score))
            
    unique = {c.index: c for c in candidates}
    return sorted(unique.values(), key=lambda x: x.index)

def mapear_secoes(texto, secoes_esperadas):
    linhas = texto.split('\n')
    aliases = obter_aliases_secao()
    candidates = construir_heading_candidates(linhas, secoes_esperadas, aliases)
    mapa = []
    last_idx = -1
    for sec_idx, sec in enumerate(secoes_esperadas):
        sec_norm = normalizar_titulo_para_comparacao(sec)
        found = None
        # 1. Tenta match exato/canonico
        for c in candidates:
            if c.index <= last_idx: continue
            if c.matched_canon == sec: found = c; break
        # 2. Tenta numérico
        if not found:
            for c in candidates:
                if c.index <= last_idx: continue
                if c.numeric == (sec_idx + 1): found = c; break
        # 3. Tenta fuzzy forte
        if not found:
            for c in candidates:
                if c.index <= last_idx: continue
                if fuzz.token_set_ratio(sec_norm, c.norm) >= 92: found = c; break
        
        if found:
            mapa.append({'canonico': sec, 'titulo_encontrado': found.raw, 'linha_inicio': found.index})
            last_idx = found.index
    
    mapa = sorted(mapa, key=lambda x: x['linha_inicio'])
    return mapa, linhas

def obter_dados_secao(secao_canonico, mapa, linhas):
    entrada = None
    for m in mapa:
        if m['canonico'] == secao_canonico: entrada = m; break
    if not entrada: return False, None, ""
    
    linha_inicio = entrada['linha_inicio']
    linha_fim = len(linhas)
    for m in mapa:
        if m['linha_inicio'] > linha_inicio:
            linha_fim = m['linha_inicio']
            break
            
    # Pega conteúdo (pula o título)
    conteudo_lines = linhas[linha_inicio+1 : linha_fim]
    conteudo_final = "\n".join([l for l in conteudo_lines if l.strip()]).strip()
    
    return True, entrada['titulo_encontrado'], conteudo_final

# ----------------- VISUALIZAÇÃO -----------------

def marcar_diff(texto_ref, texto_bel):
    def tokenizar(t): return re.findall(r'\w+|[^\w\s]', t or "")
    ref_tok = tokenizar(texto_ref)
    bel_tok = tokenizar(texto_bel)
    
    matcher = difflib.SequenceMatcher(None, [t.lower() for t in ref_tok], [t.lower() for t in bel_tok], autojunk=False)
    out = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal':
            out.append("".join([" " + t if t.isalnum() else t for t in bel_tok[j1:j2]]))
        elif tag == 'replace' or tag == 'insert':
            chunk = bel_tok[j1:j2]
            if len(chunk) == 1 and len(chunk[0]) < 2 and not chunk[0].isalnum():
                 out.append(chunk[0])
            else:
                txt = "".join([" " + t if t.isalnum() else t for t in chunk])
                out.append(f"<mark class='diff'>{txt}</mark>")
    return "".join(out).strip()

def detectar_tipo(texto):
    if not texto: return "Indeterminado"
    norm = normalizar_titulo_para_comparacao(texto)
    prof_terms = ["resultados de eficacia", "caracteristicas farmacologicas", "posologia e modo de usar"]
    for t in prof_terms:
        if t in norm: return "Profissional"
    return "Paciente"

def verificar_conteudo(texto_ref, texto_bel):
    secoes = obter_secoes_paciente()
    mapa_ref, linhas_ref = mapear_secoes(texto_ref, secoes)
    mapa_bel, linhas_bel = mapear_secoes(texto_bel, secoes)
    
    analise = []
    similaridades = []
    
    # Seções que NÃO devem mostrar divergência (apenas texto puro)
    SECOES_IGNORAR_DIFF = ["APRESENTAÇÕES", "COMPOSIÇÃO", "DIZERES LEGAIS"]
    
    for sec in secoes:
        ok_ref, tit_ref, cont_ref = obter_dados_secao(sec, mapa_ref, linhas_ref)
        ok_bel, tit_bel, cont_bel = obter_dados_secao(sec, mapa_bel, linhas_bel)
        
        n_ref = normalizar_titulo_para_comparacao(cont_ref)
        n_bel = normalizar_titulo_para_comparacao(cont_bel)
        
        status = "OK"
        if not ok_bel: status = "FALTANTE"
        elif n_ref != n_bel: status = "DIVERGENTE"
        
        if sec in SECOES_IGNORAR_DIFF:
            status = "INFO"
            
        if status == "OK": similaridades.append(100)
        elif status == "DIVERGENTE": similaridades.append(0)
        
        analise.append({
            'secao': sec,
            'tit_ref': tit_ref, 'cont_ref': cont_ref,
            'tit_bel': tit_bel, 'cont_bel': cont_bel,
            'status': status
        })
        
    score = sum(similaridades)/len(similaridades) if similaridades else 0
    return analise, score

def checar_ortografia(texto, ref_context):
    spell = SpellChecker(language='pt')
    vocab = set(re.findall(r'\w+', ref_context.lower()))
    spell.word_frequency.load_words(vocab)
    spell.word_frequency.load_words(['belfar', 'belspan', 'anvisa', 'mg', 'ml', 'fr', 'drageas'])
    
    palavras = re.findall(r'[a-zA-ZáéíóúâêôãõçÁÉÍÓÚÂÊÔÃÕÇ]{4,}', texto)
    erros = spell.unknown(palavras)
    return list(erros)

# ----------------- MAIN -----------------
st.title("🔬 Inteligência Artificial para Auditoria de Bulas (v62)")
st.markdown("Sistema com validação RÍGIDA: Auditoria exclusiva para **Bula do Paciente**. Bloqueia automaticamente arquivos Profissionais.")
st.divider()

col1, col2 = st.columns(2)
with col1:
    st.subheader("📄 Arte Vigente (Referência)")
    pdf_ref = st.file_uploader("PDF/DOCX Limpo", type=["pdf", "docx"], key="ref")
with col2:
    st.subheader("📄 PDF da Gráfica (Alvo)")
    pdf_belfar = st.file_uploader("PDF vindo da Gráfica", type=["pdf", "docx"], key="belfar")

if st.button("🔍 Iniciar Auditoria Completa", use_container_width=True, type="primary"):
    if not (pdf_ref and pdf_belfar):
        st.warning("⚠️ Envie ambos os arquivos.")
    else:
        with st.spinner("Analisando arquivos (Extração Híbrida + Limpeza de Gráfica)..."):
            texto_ref, erro_ref = extrair_texto_inteligente(pdf_ref, 'docx' if pdf_ref.name.endswith('.docx') else 'pdf')
            texto_belfar, erro_belfar = extrair_texto_inteligente(pdf_belfar, 'docx' if pdf_belfar.name.endswith('.docx') else 'pdf')

            if erro_ref or erro_belfar:
                st.error(f"Erro: {erro_ref or erro_belfar}")
            else:
                # Validação Segura
                type_ref = detectar_tipo(texto_ref)
                type_bel = detectar_tipo(texto_belfar)
                
                if type_ref == "Profissional" or type_bel == "Profissional":
                    st.error("🚨 BLOQUEIO: Arquivo de Bula Profissional detectado. Este sistema valida apenas Bula do Paciente.")
                    st.stop()

                # Processamento
                texto_ref = truncar_apos_anvisa(texto_ref)
                texto_belfar = truncar_apos_anvisa(texto_belfar)
                
                analise, score = verificar_conteudo(texto_ref, texto_belfar)
                erros = checar_ortografia(texto_belfar, texto_ref)
                
                # Extração da data para Header
                rx_anvisa = r"(?:aprovad[ao]\s+pela\s+anvisa\s+em|data\s+de\s+aprovação\s+na\s+anvisa:?)\s*([\d\s./-]+)"
                data_ref_match = re.search(rx_anvisa, texto_ref, re.I)
                data_bel_match = re.search(rx_anvisa, texto_belfar, re.I)
                
                data_ref_str = data_ref_match.group(1).strip() if data_ref_match else "N/A"
                data_bel_str = data_bel_match.group(1).strip() if data_bel_match else "N/A"
                
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Conformidade", f"{score:.0f}%")
                c2.metric("Erros Ortográficos", len(erros))
                c3.metric("Data Ref", data_ref_str)
                c4.metric("Data Bel", data_bel_str)
                
                st.divider()
                
                prefixos = {
                    "PARA QUE ESTE MEDICAMENTO É INDICADO": "1.", "COMO ESTE MEDICAMENTO FUNCIONA?": "2.",
                    "QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?": "3.", "O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?": "4.",
                    "ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?": "5.", "COMO DEVO USAR ESTE MEDICAMENTO?": "6.",
                    "O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?": "7.",
                    "QUAIS OS MALES QUE ESTE MEDICAMENTO PODE CAUSAR?": "8.",
                    "O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?": "9."
                }
                
                for item in analise:
                    sec = item['secao']
                    pref = prefixos.get(sec, "")
                    display_title = f"{pref} {sec}" if pref else sec
                    
                    icon = "✅"
                    if item['status'] == "FALTANTE": icon = "🚨"
                    elif item['status'] == "DIVERGENTE": icon = "❌"
                    elif item['status'] == "INFO": icon = "ℹ️"
                    
                    # Abre expander se houver problema
                    with st.expander(f"{icon} {display_title}", expanded=(item['status'] in ["FALTANTE", "DIVERGENTE"])):
                        c1, c2 = st.columns(2)
                        
                        # Coluna Referência
                        ref_html = html.escape(item['cont_ref'] or "").replace('\n', '<br>')
                        with c1:
                            st.markdown(f"**Arte Vigente**")
                            st.markdown(f"<div class='bula-box'><div class='section-title ref-title'>{display_title}</div>{ref_html}</div>", unsafe_allow_html=True)
                            
                        # Coluna Belfar (Gráfica)
                        bel_content = item['cont_bel'] or ""
                        
                        if item['status'] == "INFO":
                            # Seção INFO: apenas texto puro + destaques especiais (Anvisa)
                            bel_marked = html.escape(bel_content)
                        else:
                            # Outras seções: diff amarelo
                            bel_marked = marcar_diff(item['cont_ref'], bel_content)
                        
                        # Aplica destaque Ortográfico
                        for erro in erros:
                            bel_marked = re.sub(r'\b'+erro+r'\b', f"<mark class='ort'>{erro}</mark>", bel_marked)
                        
                        # Aplica destaque na Data ANVISA (especialmente nos Dizeres Legais)
                        # Usa o regex robusto para encontrar a data mesmo com espaços
                        bel_marked = re.sub(rx_anvisa, r"<mark class='anvisa'>\g<0></mark>", bel_marked, flags=re.I)
                        
                        bel_marked = bel_marked.replace('\n', '<br>')
                        
                        with c2:
                            st.markdown(f"**PDF da Gráfica**")
                            st.markdown(f"<div class='bula-box'><div class='section-title bel-title'>{display_title}</div>{bel_marked}</div>", unsafe_allow_html=True)

st.divider()
st.caption("Sistema de Auditoria v62 | Dizeres Legais & Data Anvisa Ajustados")
