# -*- coding: utf-8 -*-
# Aplicativo Streamlit: Auditoria de Bulas (Híbrido v50)
# Front-end: v21.9 (Visual Limpo) | Back-end: v41 (OCR Robusto + Limpeza Gráfica)
# Regra: Bloqueia se não for Bula do Paciente.

import streamlit as st
import fitz  # PyMuPDF
import docx
import re
import spacy
from thefuzz import fuzz
from spellchecker import SpellChecker
import difflib
import unicodedata
import io
import html
from typing import Tuple, List, Dict
import pytesseract
from PIL import Image

# ----------------- UI / CSS (Baseado na v21.9) -----------------
st.set_page_config(layout="wide", page_title="Auditoria Gráfica x Arte", page_icon="🔬")

GLOBAL_CSS = """
<style>
[data-testid="stHeader"] { display: none !important; }
footer { display: none !important; }

.bula-box {
  height: 450px;
  overflow-y: auto;
  border: 1px solid #dcdcdc;
  border-radius: 6px;
  padding: 18px;
  background: #ffffff;
  font-family: "Georgia", "Times New Roman", serif;
  font-size: 14px;
  line-height: 1.6;
  color: #111;
}

.bula-box-full {
  height: 700px;
  overflow-y: auto;
  border: 1px solid #dcdcdc;
  border-radius: 6px;
  padding: 20px;
  background: #ffffff;
  font-family: "Georgia", "Times New Roman", serif;
  font-size: 14px;
  line-height: 1.6;
  color: #111;
}

.section-title {
  font-size: 15px;
  font-weight: 700;
  color: #222;
  margin: 8px 0 12px;
  text-transform: uppercase;
  border-bottom: 1px solid #eee;
  padding-bottom: 4px;
}

mark.diff { background-color: #ffff99; padding:0 2px; border-radius: 2px; }
mark.ort { background-color: #ffdfd9; padding:0 2px; border-radius: 2px; }
mark.anvisa { background-color: #cce5ff; padding:0 2px; font-weight:500; border-radius: 2px; }

.stExpander > div[role="button"] { font-weight: 600; color: #333; }
.ref-title { color: #0b5686; font-weight:700; }
.bel-title { color: #0b8a3e; font-weight:700; }
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

# ----------------- FUNÇÕES DE LIMPEZA E OCR (DA v41) -----------------

def corrigir_erros_ocr_comuns(texto: str) -> str:
    if not texto: return ""
    correcoes = {
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
        r"\s+mm\b": "", r"\s+mma\b": "", r"\|": ""
    }
    for padrao, correcao in correcoes.items():
        texto = re.sub(padrao, correcao, texto, flags=re.MULTILINE)
    return texto

def melhorar_layout_grafica(texto: str) -> str:
    """Limpa lixo de PDFs de gráfica (marcas de corte, linhas quebradas, headers técnicos)."""
    if not texto: return ""
    texto = corrigir_erros_ocr_comuns(texto)
    texto = texto.replace('\r\n', '\n').replace('\r', '\n').replace('\t', ' ')
    texto = re.sub(r'\u00A0', ' ', texto)
    # Junta palavras hifenizadas quebradas (ex: com-\npleto -> completo)
    texto = re.sub(r"(\w+)-\s*\n\s*(\w+)", r"\1\2", texto)
    
    linhas = texto.split('\n')
    linhas_limpas = []
    
    # Padrões de lixo comuns em provas gráficas
    padroes_lixo = [
        r'^mm\s*$', r'^mma\s*$', r'^Too\s*$', r'^HM\s*$', r'^TR\s*$', r'^BRR\s*$',
        r'^\s*\|\s*$', r'^\s*-{5,}\s*$', r'^\s*\d+\s*$', r'^\s*S\s*$', r'^\s*E\s*$',
        r'^\s*O\s*$', r'^\s*m\s*$', r'^\s*EN\s*$', r'fig\.\s+\d', r'^\d+-\s+\d+$',
        r"(?i)BUL\s+.*FRENTE", r"(?i)Tipologia\s+da\s+bul", r"0,\s*00—", 
        r"^\s*\d+\s+\d+-\s+\d+\s*$"
    ]
    
    for linha in linhas:
        l = linha.strip()
        if not l:
            linhas_limpas.append("")
            continue
        eh_lixo = any(re.search(p, l, re.IGNORECASE) for p in padroes_lixo)
        if not eh_lixo:
            linhas_limpas.append(linha)
            
    texto = "\n".join(linhas_limpas)
    texto = re.sub(r'\n{3,}', '\n\n', texto)
    texto = re.sub(r'[ \t]{2,}', ' ', texto)
    return texto.strip()

def extrair_pdf_ocr_v35_fullpage(arquivo_bytes: bytes) -> str:
    """OCR Forçado para arquivos em curva/imagem."""
    texto_total = ""
    with fitz.open(stream=io.BytesIO(arquivo_bytes), filetype="pdf") as doc:
        for page in doc:
            pix_page = page.get_pixmap(dpi=300)
            img_page = Image.open(io.BytesIO(pix_page.tobytes("png")))
            # psm 3 é bom para página completa sem estrutura complexa de colunas misturadas
            texto_ocr_pagina = pytesseract.image_to_string(img_page, lang='por', config='--psm 3')
            texto_total += texto_ocr_pagina + "\n"
    return texto_total

def extrair_texto(arquivo, tipo_arquivo, usar_ocr=False):
    """Função de extração unificada."""
    if arquivo is None: return "", "Arquivo não enviado."
    
    try:
        arquivo.seek(0)
        arquivo_bytes = arquivo.read()
        texto = ""

        if tipo_arquivo == 'pdf':
            # Se for PDF da Gráfica (usar_ocr=True), força OCR
            if usar_ocr:
                texto = extrair_pdf_ocr_v35_fullpage(arquivo_bytes)
            else:
                # Tenta extração normal primeiro
                with fitz.open(stream=io.BytesIO(arquivo_bytes), filetype="pdf") as doc:
                    for page in doc:
                        texto += page.get_text("text", sort=True) + "\n"
                
                # Se saiu muito pouco texto, assume que é imagem e faz OCR
                if len(texto.strip()) < 100:
                    texto = extrair_pdf_ocr_v35_fullpage(arquivo_bytes)

        elif tipo_arquivo == 'docx':
            doc = docx.Document(io.BytesIO(arquivo_bytes))
            texto = "\n".join([p.text for p in doc.paragraphs])

        # Limpeza Padrão
        invis = ['\u00AD', '\u200B', '\u200C', '\u200D', '\uFEFF']
        for c in invis: texto = texto.replace(c, '')
        
        texto = texto.replace('\r\n', '\n').replace('\r', '\n')
        
        # Se foi usado OCR ou é PDF da gráfica, aplica limpeza pesada
        if usar_ocr:
            texto = melhorar_layout_grafica(texto)
        else:
            texto = re.sub(r'[ \t]+', ' ', texto)
            texto = texto.strip()
            
        # Remove cabeçalhos/rodapés comuns
        linhas = texto.split('\n')
        padrao_rodape = re.compile(r'bula (?:do|para o) paciente|página \d+\s*de\s*\d+', re.IGNORECASE)
        linhas = [l for l in linhas if not padrao_rodape.search(l.strip())]
        texto = "\n".join(linhas)
        
        return texto, None
    except Exception as e:
        return "", f"Erro ao ler o arquivo: {e}"

def truncar_apos_anvisa(texto):
    if not isinstance(texto, str): return texto
    rx = r"(aprovad[ao]\s+pela\s+anvisa\s+em|data\s+de\s+aprovação\s+na\s+anvisa:)\s*([\d]{1,2}/[\d]{1,2}/[\d]{2,4})"
    m = re.search(rx, texto, re.IGNORECASE)
    if m:
        pos = texto.find('\n', m.end())
        return texto[:pos] if pos != -1 else texto
    return texto

# ----------------- NORMALIZAÇÃO E SEÇÕES -----------------

def normalizar_texto(texto):
    if texto is None: return ""
    texto = ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')
    texto = re.sub(r'[^\w\s]', '', texto)
    texto = ' '.join(texto.split())
    return texto.lower()

def normalizar_titulo_para_comparacao(texto):
    t = normalizar_texto(texto)
    t = re.sub(r'^\s*(\d{1,2})\s*[\.\)\-]?\s*', '', t).strip()
    return t

def obter_secoes_paciente():
    # Lista estrita de Bula do Paciente
    return [
        "APRESENTAÇÕES", "COMPOSIÇÃO", 
        "1. PARA QUE ESTE MEDICAMENTO É INDICADO?",
        "2. COMO ESTE MEDICAMENTO FUNCIONA?", 
        "3. QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?",
        "4. O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?",
        "5. ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?",
        "6. COMO DEVO USAR ESTE MEDICAMENTO?",
        "7. O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?",
        "8. QUAIS OS MALES QUE ESTE MEDICAMENTO PODE ME CAUSAR?",
        "9. O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?",
        "DIZERES LEGAIS"
    ]

def obter_aliases_secao():
    # Aliases para ajudar no OCR se o número for perdido
    return {
        "INDICAÇÕES": "1. PARA QUE ESTE MEDICAMENTO É INDICADO?",
        "COMO FUNCIONA?": "2. COMO ESTE MEDICAMENTO FUNCIONA?",
        "CONTRAINDICAÇÕES": "3. QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?",
        "QUANDO NÃO DEVO USAR": "3. QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?",
        "ADVERTÊNCIAS E PRECAUÇÕES": "4. O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?",
        "ARMAZENAMENTO": "5. ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?",
        "COMO DEVO USAR": "6. COMO DEVO USAR ESTE MEDICAMENTO?",
        "ESQUECIMENTO": "7. O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?",
        "REAÇÕES ADVERSAS": "8. QUAIS OS MALES QUE ESTE MEDICAMENTO PODE ME CAUSAR?",
        "SUPERDOSE": "9. O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?"
    }

# ----------------- MAPEAMENTO (Lógica v41 Robusta) -----------------

def mapear_secoes_robusto(texto_completo, secoes_esperadas):
    """Usa fuzzy matching para tolerar erros de OCR nos títulos."""
    linhas = texto_completo.split('\n')
    aliases = obter_aliases_secao()
    
    # Prepara dicionário de títulos normalizados
    titulos_map = {} # norm -> canonico
    for s in secoes_esperadas:
        titulos_map[normalizar_titulo_para_comparacao(s)] = s
    for alias, canon in aliases.items():
        if canon in secoes_esperadas:
            titulos_map[normalizar_titulo_para_comparacao(alias)] = canon
            
    titulos_norm_keys = list(titulos_map.keys())
    
    mapa = []
    idx = 0
    
    while idx < len(linhas):
        linha = linhas[idx].strip()
        if not linha:
            idx += 1
            continue
            
        linha_norm = normalizar_titulo_para_comparacao(linha)
        
        # Tenta match exato/fuzzy na linha atual
        best_score = 0
        best_canon = None
        
        # 1. Match direto
        match = difflib.get_close_matches(linha_norm, titulos_norm_keys, n=1, cutoff=0.92)
        if match:
            best_score = 95
            best_canon = titulos_map[match[0]]
        
        # 2. Fuzzy mais solto (para OCR ruim)
        if best_score < 90:
            for t_key in titulos_norm_keys:
                score = fuzz.token_set_ratio(linha_norm, t_key)
                if score > best_score and score > 85:
                    best_score = score
                    best_canon = titulos_map[t_key]
                    
        if best_score >= 85:
            # Verifica se não é um falso positivo muito curto
            if len(linha) < 4 and best_score < 98:
                idx += 1
                continue
                
            mapa.append({
                'canonico': best_canon,
                'titulo_encontrado': linha,
                'linha_inicio': idx
            })
            
        idx += 1
        
    # Remove duplicatas mantendo a ordem (assume a primeira ocorrência como válida se próxima)
    # Mas para bulas, às vezes repete. Vamos ordenar por linha.
    mapa = sorted(mapa, key=lambda x: x['linha_inicio'])
    return mapa, linhas

def obter_conteudo_secao(canonico, mapa, linhas):
    """Extrai o texto entre um título e o próximo."""
    entrada = next((m for m in mapa if m['canonico'] == canonico), None)
    if not entrada: return False, None, ""
    
    idx_inicio = entrada['linha_inicio']
    # Acha o próximo título no mapa
    idx_fim = len(linhas)
    for m in mapa:
        if m['linha_inicio'] > idx_inicio:
            idx_fim = m['linha_inicio']
            break
            
    # Pega o conteúdo (pula a linha do título)
    conteudo = "\n".join(linhas[idx_inicio+1 : idx_fim]).strip()
    return True, entrada['titulo_encontrado'], conteudo

# ----------------- VALIDAÇÃO DE TIPO -----------------

def detectar_tipo_arquivo_por_score(texto):
    """Retorna 'Paciente', 'Profissional' ou 'Indeterminado'."""
    if not texto: return "Indeterminado"
    
    t_norm = normalizar_texto(texto)
    
    # Termos fortes de Paciente
    termos_paciente = ["como este medicamento funciona", "o que devo saber antes de usar", 
                       "quais os males que este medicamento pode causar"]
    score_pac = sum(1 for t in termos_paciente if t in t_norm)
    
    # Termos fortes de Profissional
    termos_prof = ["resultados de eficacia", "caracteristicas farmacologicas", 
                   "posologia e modo de usar", "propriedades farmacocinetica"]
    score_prof = sum(1 for t in termos_prof if t in t_norm)
    
    if score_pac > score_prof: return "Paciente"
    if score_prof > score_pac: return "Profissional"
    return "Indeterminado"

# ----------------- COMPARAÇÃO E HTML -----------------

def marcar_diferencas_html(texto_ref, texto_bel):
    """Gera HTML com diff visual palavra por palavra."""
    def tok(t): return re.findall(r'\n|\w+|[^\w\s]', t or "")
    
    ref_tokens = tok(texto_ref)
    bel_tokens = tok(texto_bel)
    
    # Normaliza para comparação, mas mantém original para exibição
    ref_norm = [t.lower() for t in ref_tokens]
    bel_norm = [t.lower() for t in bel_tokens]
    
    matcher = difflib.SequenceMatcher(None, ref_norm, bel_norm, autojunk=False)
    html_out = []
    
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal':
            for t in bel_tokens[j1:j2]:
                html_out.append(t if t != '\n' else '<br>')
        elif tag == 'replace' or tag == 'insert':
            # Texto diferente ou novo na Bula Belfar (destaque amarelo)
            chunk = "".join([t if t != '\n' else '<br>' for t in bel_tokens[j1:j2]])
            html_out.append(f"<mark class='diff'>{chunk}</mark>")
        elif tag == 'delete':
            # Texto que existe na Ref mas sumiu na Belfar (opcional: mostrar riscado? 
            # O padrão v21.9 foca em mostrar o que TEM na belfar destacado).
            # Aqui vamos ignorar o delete visualmente na caixa da direita para não poluir, 
            # já que o diff mostra a divergência.
            pass
            
    # Reconstrói string e ajusta espaços
    res = "".join([(" " + x if not x.startswith("<") and x not in ",.;:!?" else x) for x in html_out]).strip()
    return res

def processar_auditoria(texto_ref, texto_bel):
    secoes = obter_secoes_paciente()
    ignorar_comp = ["APRESENTAÇÕES", "COMPOSIÇÃO", "DIZERES LEGAIS"]
    
    mapa_ref, linhas_ref = mapear_secoes_robusto(texto_ref, secoes)
    mapa_bel, linhas_bel = mapear_secoes_robusto(texto_bel, secoes)
    
    analise = []
    similaridades = []
    erros_orto = []
    
    # Ortografia (Simplificada)
    spell = SpellChecker(language='pt')
    # Adiciona palavras comuns de bula para não marcar erro
    spell.word_frequency.load_words(["belfar", "belspan", "anvisa", "butilbrometo", "escopolamina", "dipirona", "drágeas", "mg", "ml"])
    
    for sec in secoes:
        item = {'secao': sec, 'tem_diferenca': False, 'faltante': False, 'ignorada': False}
        
        has_ref, tit_ref, cont_ref = obter_conteudo_secao(sec, mapa_ref, linhas_ref)
        has_bel, tit_bel, cont_bel = obter_conteudo_secao(sec, mapa_bel, linhas_bel)
        
        item['conteudo_ref'] = cont_ref if has_ref else "Seção não encontrada"
        item['conteudo_belfar'] = cont_bel if has_bel else "Seção não encontrada"
        
        if not has_bel:
            item['faltante'] = True
            item['tem_diferenca'] = True
            analise.append(item)
            continue
            
        if sec in ignorar_comp:
            item['ignorada'] = True
            analise.append(item)
            similaridades.append(100)
            continue
            
        # Comparação
        norm_ref = normalizar_texto(cont_ref)
        norm_bel = normalizar_texto(cont_bel)
        
        if norm_ref != norm_bel:
            item['tem_diferenca'] = True
            similaridades.append(0) # Penaliza divergência
        else:
            similaridades.append(100)
            
        # Checagem ortográfica no conteúdo Belfar
        palavras = re.findall(r'\b[a-zA-ZÀ-ÖØ-öø-ÿ]+\b', cont_bel)
        for p in palavras:
            if len(p) > 3 and p.lower() not in cont_ref.lower(): # Só marca se não estiver na referência
                if p.lower() not in spell:
                    erros_orto.append(p)
                    
        analise.append(item)
        
    score = sum(similaridades)/len(similaridades) if similaridades else 0
    return analise, score, list(set(erros_orto))

# ----------------- MAIN APP -----------------
st.title("🔬 Auditoria de Bulas: Arte Vigente x Gráfica (Híbrido)")
st.markdown("### Validação exclusiva para **Bula do Paciente**")
st.markdown("Sistema utiliza OCR avançado para ler arquivos da Gráfica (curvas) e compara com a Arte Vigente.")

st.divider()

col1, col2 = st.columns(2)
with col1:
    st.subheader("📄 Arte Vigente (Referência)")
    pdf_ref = st.file_uploader("PDF/DOCX limpo", type=["pdf", "docx"], key="ref")
with col2:
    st.subheader("📄 PDF da Gráfica (Em Curva)")
    pdf_belfar = st.file_uploader("PDF vindo da Gráfica", type=["pdf"], key="belfar")

if st.button("🔍 Iniciar Auditoria", use_container_width=True, type="primary"):
    if not (pdf_ref and pdf_belfar):
        st.warning("⚠️ Envie ambos os arquivos.")
    else:
        with st.spinner("Analisando arquivos... (Isso pode levar alguns segundos devido ao OCR)"):
            # 1. Extração (Arte Vigente - Texto Limpo)
            texto_ref, erro_ref = extrair_texto(pdf_ref, 'docx' if pdf_ref.name.endswith('.docx') else 'pdf', usar_ocr=False)
            
            # 2. Extração (Gráfica - Texto Sujo/Curva - Usa OCR e Limpeza v41)
            texto_belfar, erro_belfar = extrair_texto(pdf_belfar, 'pdf', usar_ocr=True)
            
            if erro_ref or erro_belfar:
                st.error(f"Erro na leitura: {erro_ref or erro_belfar}")
            else:
                # 3. Validação de Tipo (Regra Rígida)
                tipo_detectado_ref = detectar_tipo_arquivo_por_score(texto_ref)
                tipo_detectado_bel = detectar_tipo_arquivo_por_score(texto_belfar)
                
                # Verifica se algum é Profissional
                if tipo_detectado_ref == "Profissional" or tipo_detectado_bel == "Profissional":
                    st.error("🚨 **BLOQUEIO DE SEGURANÇA**: O sistema detectou uma Bula **Profissional**.")
                    st.error("Este módulo foi configurado para validar APENAS **Bula do Paciente**.")
                    st.stop()
                
                # 4. Processamento
                texto_ref = truncar_apos_anvisa(texto_ref)
                texto_belfar = truncar_apos_anvisa(texto_belfar)
                
                analise, score, erros = processar_auditoria(texto_ref, texto_belfar)
                
                # 5. Relatório Visual (Estilo v21.9)
                c1, c2, c3 = st.columns(3)
                c1.metric("Conformidade", f"{score:.0f}%")
                c2.metric("Possíveis Erros Ortográficos", len(erros))
                status = "✅ APROVADO" if score == 100 and len(erros) == 0 else "⚠️ ATENÇÃO"
                c3.metric("Status", status)
                
                st.divider()
                st.subheader("Detalhamento por Seção")
                
                for item in analise:
                    titulo = item['secao']
                    status_icon = "✅"
                    if item['faltante']: status_icon = "🚨 FALTANTE"
                    elif item['ignorada']: status_icon = "ℹ️ Ignorada"
                    elif item['tem_diferenca']: status_icon = "❌ Divergente"
                    
                    expanded = item['tem_diferenca'] or item['faltante']
                    
                    with st.expander(f"{status_icon} {titulo}", expanded=expanded):
                        col_a, col_b = st.columns(2)
                        
                        # Gera HTML com diff
                        html_diff = marcar_diferencas_html(item['conteudo_ref'], item['conteudo_belfar'])
                        
                        # Destaca erros ortográficos no HTML
                        for erro in erros:
                            html_diff = re.sub(r'(?<!<mark class=\'diff\'>)\b'+erro+r'\b', f"<mark class='ort'>{erro}</mark>", html_diff, flags=re.IGNORECASE)
                        
                        with col_a:
                            st.markdown("**Arte Vigente**")
                            st.markdown(f"<div class='bula-box'>{html.escape(item['conteudo_ref']).replace(chr(10), '<br>')}</div>", unsafe_allow_html=True)
                        with col_b:
                            st.markdown("**PDF da Gráfica**")
                            st.markdown(f"<div class='bula-box'>{html_diff.replace(chr(10), '<br>')}</div>", unsafe_allow_html=True)

st.divider()
st.caption("Auditoria de Bulas v50 | Motor v41 (OCR) + Interface v21.9")
