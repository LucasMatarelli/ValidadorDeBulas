# pages/2_Conferencia_MKT.py
#
# Versão v79 (ROBUSTA)
# - NOVIDADE: Aba "Debug / Texto Puro" para visualizar o que foi lido.
# - NOVIDADE: Opção de "Forçar Leitura em 2 Colunas" na tela (resolve layouts complexos).
# - CORREÇÃO: "Cola" títulos quebrados (ex: "8." numa linha e "QUAIS OS MALES" na outra).
# - CORREÇÃO: Normalização agressiva de espaços para evitar quebras de palavras.

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
from collections import namedtuple

# ----------------- UI / CSS -----------------
st.set_page_config(layout="wide", page_title="Auditoria de Bulas", page_icon="🔬")

GLOBAL_CSS = """
<style>
.main .block-container {
    padding-top: 2rem !important;
    padding-bottom: 2rem !important;
    max-width: 95% !important;
}
[data-testid="stHeader"] { display: none !important; }
footer { display: none !important; }

.bula-box {
  height: 400px;
  overflow-y: auto;
  border: 1px solid #dcdcdc;
  border-radius: 6px;
  padding: 18px;
  background: #ffffff;
  font-family: "Segoe UI", "Roboto", sans-serif;
  font-size: 14px;
  line-height: 1.6;
  color: #222;
}

.bula-box-debug {
  height: 200px;
  overflow-y: auto;
  border: 1px dashed #aaa;
  background: #f0f0f0;
  font-family: "Courier New", monospace;
  font-size: 12px;
  padding: 10px;
}

.section-title {
  font-size: 16px;
  font-weight: 700;
  color: #222;
  margin: 15px 0 10px;
  padding-top: 10px;
  border-top: 1px solid #eee;
  text-transform: uppercase;
}

.ref-title { color: #0b5686; }
.bel-title { color: #0b8a3e; }

mark.diff { background-color: #fff59d; padding: 0 2px; color: black; border-radius: 2px; }
mark.ort { background-color: #ffccbc; padding: 0 2px; color: black; border-bottom: 2px solid #ff5722; }
mark.anvisa { background-color: #e3f2fd; padding: 0 2px; color: #0d47a1; border: 1px solid #90caf9; }

.stExpander > div[role="button"] { font-weight: 600; color: #333; }
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

# ----------------- UTILITÁRIOS -----------------
def normalizar_texto(texto):
    if not isinstance(texto, str): return ""
    texto = texto.replace('\n', ' ')
    texto = ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')
    texto = re.sub(r'[^\w\s]', '', texto)
    texto = ' '.join(texto.split())
    return texto.lower()

def normalizar_titulo_para_comparacao(texto):
    texto_norm = normalizar_texto(texto or "")
    texto_norm = re.sub(r'^\d+\s*[\.\-)]*\s*', '', texto_norm).strip()
    return texto_norm

def truncar_apos_anvisa(texto):
    if not isinstance(texto, str): return texto
    regex_anvisa = r"((?:aprovad[ao][\s\n]+pela[\s\n]+anvisa[\s\n]+em|data[\s\n]+de[\s\n]+aprova\w+[\s\n]+na[\s\n]+anvisa:)[\s\n]*([\d]{1,2}\s*/\s*[\d]{1,2}\s*/\s*[\d]{2,4}))"
    match = re.search(regex_anvisa, texto, re.IGNORECASE | re.DOTALL)
    if not match: return texto
    cut_off_position = match.end(1)
    pos_match = re.search(r'^\s*\.', texto[cut_off_position:], re.IGNORECASE)
    if pos_match: cut_off_position += pos_match.end()
    return texto[:cut_off_position]

def _create_anchor_id(secao_nome, prefix):
    norm = normalizar_texto(secao_nome)
    norm_safe = re.sub(r'[^a-z0-9\-]', '-', norm)
    return f"anchor-{prefix}-{norm_safe}"

# ----------------- LIMPEZA DE LIXO -----------------
def limpar_lixo_grafico(texto):
    padroes_lixo = [
        r'.*31\s*2105.*', r'.*w\s*Roman.*',
        r'AZOLINA:', r'contato:', r'artes\s*@\s*belfar\.com\.br',
        r'^\s*VERSO\s*$', r'^\s*FRENTE\s*$',
        r'.*Frente\s*/\s*Verso.*',
        r'.*-\s*\.\s*Cor.*', r'.*Cor:\s*Preta.*',
        r'.*Papel:.*', r'.*Ap\s*\d+gr.*', 
        r'.*da bula:.*', r'.*AFAZOLINA_BUL.*',
        r'bula do paciente', r'página \d+\s*de\s*\d+', r'^\s*\d+\s*$',
        r'Tipologia', r'Dimensão', r'Dimensões', r'Formato',
        r'Times New Roman', r'Myriad Pro', r'Arial', r'Helvética',
        r'Cores?:', r'Preto', r'Black', r'Cyan', r'Magenta', r'Yellow', r'Pantone',
        r'^\s*\d+[,.]?\d*\s*mm\s*$', r'\b\d{2,4}\s*x\s*\d{2,4}\s*mm\b',
        r'^\s*BELFAR\s*$', r'^\s*PHARMA\s*$',
        r'CNPJ:?', r'SAC:?', r'Farm\. Resp\.?:?', r'CRF-?MG',
        r'Cód\.?:?', r'Ref\.?:?', r'Laetus', r'Pharmacode',
        r'.*AZOLINA:\s*Tim.*', r'.*NAFAZOLINA:\s*Times.*', 
        r'\b\d{6,}\s*-\s*\d{2}/\d{2}\b', 
        r'^\s*[\w_]*BUL\d+V\d+[\w_]*\s*$',
        r'.*New\s*Roman.*', r'.*r?po\s*10.*',
        r'.*BUL_CLORIDRATO.*', r'.*Impress[ãa]o.*', r'.*Normal\s*e\s*Negrito.*'
    ]
    texto_limpo = texto
    for p in padroes_lixo:
        texto_limpo = re.sub(p, ' ', texto_limpo, flags=re.IGNORECASE | re.MULTILINE)
    return texto_limpo

# ----------------- RECONSTRUÇÃO DE TÍTULOS QUEBRADOS -----------------
def reparar_titulos_quebrados(texto):
    """
    Resolve o problema onde o título está em duas linhas.
    Ex: 
    Linha 1: "8."
    Linha 2: "QUAIS OS MALES..."
    Vira: "8. QUAIS OS MALES..."
    """
    linhas = texto.split('\n')
    novas_linhas = []
    i = 0
    while i < len(linhas):
        linha_atual = linhas[i].strip()
        
        # Se for a última linha, só adiciona
        if i + 1 >= len(linhas):
            novas_linhas.append(linhas[i])
            i += 1
            continue
            
        proxima_linha = linhas[i+1].strip()
        
        # Padrão: Linha atual é só número (ex: "8" ou "8.") e próxima linha é maiúscula
        if re.match(r'^\d+\.?$', linha_atual) and len(proxima_linha) > 5 and proxima_linha.isupper():
            novas_linhas.append(f"{linha_atual} {proxima_linha}") # Junta
            i += 2 # Pula a próxima pois já foi usada
        else:
            novas_linhas.append(linhas[i])
            i += 1
            
    return '\n'.join(novas_linhas)

def forcar_titulos_bula(texto):
    # Primeiro repara títulos divididos
    texto = reparar_titulos_quebrados(texto)
    
    # Depois padroniza
    substituicoes = [
        (r"(?:1\.?\s*)?PARA\s*QUE\s*ESTE\s*MEDICAMENTO\s*[\s\S]{0,100}?INDICADO\??",
         r"\n\n1. PARA QUE ESTE MEDICAMENTO É INDICADO?\n"),

        (r"(?:2\.?\s*)?COMO\s*ESTE\s*MEDICAMENTO\s*[\s\S]{0,100}?FUNCIONA\??",
         r"\n\n2. COMO ESTE MEDICAMENTO FUNCIONA?\n"),

        (r"(?:3\.?\s*)?QUANDO\s*N[ÃA]O\s*DEVO\s*USAR\s*[\s\S]{0,100}?MEDICAMENTO\??",
         r"\n\n3. QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?\n"),

        (r"(?:4\.?\s*)?O\s*QUE\s*DEVO\s*SABER[\s\S]{1,100}?USAR[\s\S]{1,100}?MEDICAMENTO\??",
         r"\n\n4. O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?\n"),

        (r"(?:5\.?\s*)?ONDE\s*,?\s*COMO\s*E\s*POR\s*QUANTO[\s\S]{1,100}?GUARDAR[\s\S]{1,100}?MEDICAMENTO\??",
         r"\n\n5. ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?\n"),
         
        (r"(?:6\.?\s*)?COMO\s*DEVO\s*USAR\s*ESTE\s*[\s\S]{0,100}?MEDICAMENTO\??",
         r"\n\n6. COMO DEVO USAR ESTE MEDICAMENTO?\n"),

        (r"(?:7\.?\s*)?O\s*QUE\s*DEVO\s*FAZER[\s\S]{0,200}?MEDICAMENTO\??", 
         r"\n\n7. O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?\n"),
         
        (r"(?:8\.?\s*)?QUAIS\s*OS\s*MALES[\s\S]{0,200}?CAUSAR\??", 
         r"\n\n8. QUAIS OS MALES QUE ESTE MEDICAMENTO PODE CAUSAR?\n"),
         
        (r"(?:9\.?\s*)?O\s*QUE\s*FAZER\s*SE\s*ALGU[EÉ]M\s*USAR[\s\S]{0,200}?MEDICAMENTO\??", 
         r"\n\n9. O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?\n"),
    ]
    
    for padrao, substituto in substituicoes:
        texto = re.sub(padrao, substituto, texto, flags=re.IGNORECASE | re.DOTALL)
    return texto

# ----------------- EXTRAÇÃO -----------------
def extrair_texto(arquivo, tipo_arquivo, is_marketing_pdf=False, modo_coluna="auto"):
    if arquivo is None: return "", f"Arquivo {tipo_arquivo} não enviado."
    try:
        arquivo.seek(0)
        texto_completo = ""

        if tipo_arquivo == 'pdf':
            with fitz.open(stream=arquivo.read(), filetype="pdf") as doc:
                for page in doc:
                    
                    if is_marketing_pdf and modo_coluna == "2col":
                        # --- MODO FORÇADO 2 COLUNAS ---
                        blocks = page.get_text("blocks") # Lê blocos crus
                        meio_pagina = page.rect.width / 2
                        col_esq = [b for b in blocks if (b[0] + b[2])/2 < meio_pagina and b[6]==0]
                        col_dir = [b for b in blocks if (b[0] + b[2])/2 >= meio_pagina and b[6]==0]
                        
                        col_esq.sort(key=lambda x: x[1]) # Ordena por Y (Cima para Baixo)
                        col_dir.sort(key=lambda x: x[1])
                        
                        for b in col_esq + col_dir:
                            texto_completo += b[4] + "\n"
                            
                    else:
                        # --- MODO AUTOMÁTICO (PADRÃO) ---
                        # sort=True faz o PyMuPDF tentar adivinhar a ordem
                        blocks = page.get_text("blocks", sort=True)
                        for b in blocks:
                            if b[6] == 0:
                                texto_completo += b[4] + "\n"

        elif tipo_arquivo == 'docx':
            doc = docx.Document(arquivo)
            texto_completo = "\n".join([p.text for p in doc.paragraphs])

        if texto_completo:
            # Limpeza inicial básica
            texto_completo = texto_completo.replace('\r\n', '\n').replace('\r', '\n')
            
            # Remove caracteres invisíveis que quebram regex
            texto_completo = ''.join(c for c in texto_completo if c.isprintable() or c == '\n')
            
            texto_completo = limpar_lixo_grafico(texto_completo)
            
            if is_marketing_pdf:
                texto_completo = forcar_titulos_bula(texto_completo)
                texto_completo = re.sub(r'(?m)^\s*\d{1,2}\.\s*$', '', texto_completo) # Remove números de página soltos
                texto_completo = re.sub(r'(?m)^_+$', '', texto_completo)

            texto_completo = re.sub(r'\n{3,}', '\n\n', texto_completo)
            return texto_completo.strip(), None

    except Exception as e:
        return "", f"Erro: {e}"

# ----------------- RECONSTRUÇÃO DE PARÁGRAFOS -----------------
def is_titulo_secao(linha):
    ln = linha.strip()
    if len(ln) < 4: return False
    first = ln.split('\n')[0]
    # Regex robusto para pegar "1. NOME" ou apenas "NOME" se for muito maiúsculo
    if re.match(r'^\d+\s*[\.\-)]*\s*[A-ZÁÉÍÓÚÂÊÔÃÕÇ]', first): return True
    if first.isupper() and not first.endswith('.') and len(first) > 5: return True
    return False

def reconstruir_paragrafos(texto):
    if not texto: return ""
    texto = forcar_titulos_bula(texto)
    
    linhas = texto.split('\n')
    linhas_out = []
    buffer = ""
    padrao_tabela = re.compile(r'\.{3,}|_{3,}|q\.s\.p|^\s*[-•]\s+')

    for linha in linhas:
        l_strip = linha.strip()
        
        # Ignora linhas vazias ou muito curtas (números de página)
        if not l_strip or (len(l_strip) < 3 and not re.match(r'^\d+\.?$', l_strip)):
            if buffer: linhas_out.append(buffer); buffer = ""
            if not linhas_out or linhas_out[-1] != "": linhas_out.append("")
            continue
            
        if is_titulo_secao(l_strip):
            if buffer: linhas_out.append(buffer); buffer = ""
            linhas_out.append(l_strip)
            continue
            
        if padrao_tabela.search(l_strip):
            if buffer: linhas_out.append(buffer); buffer = ""
            linhas_out.append(l_strip)
            continue

        if buffer:
            if buffer.endswith('-'):
                buffer = buffer[:-1] + l_strip
            elif not buffer.endswith(('.', ':', '!', '?')):
                buffer += " " + l_strip
            else:
                linhas_out.append(buffer); buffer = l_strip
        else:
            buffer = l_strip
            
    if buffer: linhas_out.append(buffer)
    return "\n".join(linhas_out)

# ----------------- CONFIGURAÇÃO DE SEÇÕES -----------------
def obter_secoes_por_tipo():
    return [
        "APRESENTAÇÕES", "COMPOSIÇÃO",
        "1.PARA QUE ESTE MEDICAMENTO É INDICADO?", "2.COMO ESTE MEDICAMENTO FUNCIONA?",
        "3.QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?", "4.O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?",
        "5.ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?", "6.COMO DEVO USAR ESTE MEDICAMENTO?",
        "7.O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?",
        "8.QUAIS OS MALES QUE ESTE MEDICAMENTO PODE CAUSAR?",
        "9.O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?",
        "DIZERES LEGAIS"
    ]

def obter_aliases_secao():
    return {
        "PARA QUE ESTE MEDICAMENTO É INDICADO?": "1.PARA QUE ESTE MEDICAMENTO É INDICADO?",
        "COMO ESTE MEDICAMENTO FUNCIONA?": "2.COMO ESTE MEDICAMENTO FUNCIONA?",
        "QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?": "3.QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?",
        "O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?": "4.O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?",
        "ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICamento?": "5.ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?",
        "COMO DEVO USAR ESTE MEDICAMENTO?": "6.COMO DEVO USAR ESTE MEDICAMENTO?",
        "O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?": "7.O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?",
        "QUAIS OS MALES QUE ESTE MEDICAMENTO PODE ME CAUSAR?": "8.QUAIS OS MALES QUE ESTE MEDICAMENTO PODE CAUSAR?",
        "O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?": "9.O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?",
    }

def obter_secoes_ignorar_comparacao(): return ["APRESENTAÇÕES", "COMPOSIÇÃO", "DIZERES LEGAIS"]
def obter_secoes_ignorar_ortografia(): return ["COMPOSIÇÃO", "DIZERES LEGAIS"]

# ----------------- MAPEAMENTO ROBUSTO -----------------
HeadingCandidate = namedtuple("HeadingCandidate", ["index", "raw", "norm", "numeric", "matched_canon", "score"])

def construir_heading_candidates(linhas, secoes_esperadas, aliases):
    titulos_possiveis = {s: s for s in secoes_esperadas}
    for a, c in aliases.items():
        if c in secoes_esperadas: titulos_possiveis[a] = c
    titulos_norm = {k: normalizar_titulo_para_comparacao(k) for k in titulos_possiveis.keys()}
    candidates = []
    
    for i, linha in enumerate(linhas):
        raw = (linha or "").strip()
        if len(raw) < 5: continue # Ignora linhas muito curtas
        
        norm = normalizar_titulo_para_comparacao(raw)
        best_score = 0; best_canon = None
        
        # Tenta extrair número inicial (ex: "8" de "8. Quais...")
        mnum = re.match(r'^\s*(\d{1,2})\s*[\.\)\-]', raw)
        numeric = int(mnum.group(1)) if mnum else None
        
        for t_possivel, t_canon in titulos_possiveis.items():
            t_norm = titulos_norm.get(t_possivel, "")
            if not t_norm: continue
            
            # Fuzzy match
            score = fuzz.token_set_ratio(t_norm, norm)
            
            # Boost se for match exato da string normalizada
            if t_norm == norm: score = 100
            
            if score > best_score: best_score = score; best_canon = t_canon
        
        is_candidate = False
        if numeric is not None and best_score > 60: is_candidate = True # Tem número e parece título
        elif best_score >= 85: is_candidate = True # Texto muito parecido
        
        if is_candidate:
            candidates.append(HeadingCandidate(index=i, raw=raw, norm=norm, numeric=numeric, matched_canon=best_canon if best_score >= 75 else None, score=best_score))
            
    unique = {c.index: c for c in candidates}
    return sorted(unique.values(), key=lambda x: x.index)

def mapear_secoes_deterministico(texto_completo, secoes_esperadas):
    linhas = texto_completo.split('\n')
    aliases = obter_aliases_secao()
    candidates = construir_heading_candidates(linhas, secoes_esperadas, aliases)
    mapa = []
    last_idx = -1
    
    for sec_idx, sec in enumerate(secoes_esperadas):
        sec_norm = normalizar_titulo_para_comparacao(sec)
        found = None
        
        # 1. Match pelo nome canônico exato ou fuzzy alto
        for c in candidates:
            if c.index <= last_idx: continue
            if c.matched_canon == sec: found = c; break
            
        # 2. Match pelo número da seção (se houver)
        if not found:
            for c in candidates:
                if c.index <= last_idx: continue
                if c.numeric == (sec_idx + 1): # Ex: Seção índice 0 espera número 1? 
                    # Ajuste para índices do vetor secoes_esperadas que tem items sem número antes
                    # Simplificação: Tenta achar o número no início da string crua da seção esperada
                    num_esperado_match = re.match(r'^(\d+)\.', sec)
                    if num_esperado_match:
                        if c.numeric == int(num_esperado_match.group(1)):
                            found = c; break
                            
        # 3. Match por similaridade textual forte
        if not found:
            for c in candidates:
                if c.index <= last_idx: continue
                if fuzz.token_set_ratio(sec_norm, c.norm) >= 90: found = c; break
        
        if found:
            mapa.append({'canonico': sec, 'titulo_encontrado': found.raw, 'linha_inicio': found.index, 'score': found.score})
            last_idx = found.index
            
    mapa = sorted(mapa, key=lambda x: x['linha_inicio'])
    return mapa, candidates, linhas

def obter_dados_secao_v2(secao_canonico, mapa_secoes, linhas_texto):
    entrada = None
    for m in mapa_secoes:
        if m['canonico'] == secao_canonico: entrada = m; break
    if not entrada: return False, None, ""
    
    linha_inicio = entrada['linha_inicio']
    
    # Determina onde termina esta seção
    sorted_map = sorted(mapa_secoes, key=lambda x: x['linha_inicio'])
    prox_idx = None
    for m in sorted_map:
        if m['linha_inicio'] > linha_inicio: prox_idx = m['linha_inicio']; break
    
    linha_fim = prox_idx if prox_idx is not None else len(linhas_texto)
    
    conteudo_lines = []
    for i in range(linha_inicio + 1, linha_fim):
        # Validação extra: Se a linha parecer MUITO um título de outra seção, para.
        line_norm = normalizar_titulo_para_comparacao(linhas_texto[i])
        if len(line_norm) > 10 and line_norm.isupper():
             # Checa se bate com alguma seção esperada
             if any(fuzz.ratio(line_norm, normalizar_titulo_para_comparacao(s)) > 90 for s in obter_secoes_por_tipo()):
                 break
        conteudo_lines.append(linhas_texto[i])
        
    conteudo_final = "\n".join(conteudo_lines).strip()
    return True, entrada['titulo_encontrado'], conteudo_final

# ----------------- VERIFICAÇÃO -----------------
def verificar_secoes_e_conteudo(texto_ref, texto_belfar):
    secoes_esperadas = obter_secoes_por_tipo()
    ignore_comparison = [s.upper() for s in obter_secoes_ignorar_comparacao()]
    secoes_faltantes, diferencas_conteudo, similaridades_secoes, diferencas_titulos = [], [], [], []
    secoes_analisadas = []

    mapa_ref, _, linhas_ref = mapear_secoes_deterministico(texto_ref, secoes_esperadas)
    mapa_belfar, _, linhas_belfar = mapear_secoes_deterministico(texto_belfar, secoes_esperadas)

    for sec in secoes_esperadas:
        encontrou_ref, titulo_ref, conteudo_ref = obter_dados_secao_v2(sec, mapa_ref, linhas_ref)
        encontrou_belfar, titulo_belfar, conteudo_belfar = obter_dados_secao_v2(sec, mapa_belfar, linhas_belfar)

        if not encontrou_ref and not encontrou_belfar:
            secoes_faltantes.append(sec)
            secoes_analisadas.append({
                'secao': sec, 'conteudo_ref': "Seção não encontrada", 'conteudo_belfar': "Seção não encontrada",
                'titulo_encontrado_ref': None, 'titulo_encontrado_belfar': None,
                'tem_diferenca': True, 'ignorada': False, 'faltante': True
            })
            continue

        if not encontrou_belfar:
            secoes_faltantes.append(sec)
            secoes_analisadas.append({
                'secao': sec, 'conteudo_ref': conteudo_ref if encontrou_ref else "Seção não encontrada",
                'conteudo_belfar': "Seção não encontrada", 'titulo_encontrado_ref': titulo_ref, 'titulo_encontrado_belfar': None,
                'tem_diferenca': True, 'ignorada': False, 'faltante': True
            })
            continue

        if sec.upper() in ignore_comparison:
            secoes_analisadas.append({
                'secao': sec, 'conteudo_ref': conteudo_ref or "", 'conteudo_belfar': conteudo_belfar or "",
                'titulo_encontrado_ref': titulo_ref, 'titulo_encontrado_belfar': titulo_belfar,
                'tem_diferenca': False, 'ignorada': True, 'faltante': False
            })
            continue

        norm_ref = re.sub(r'([.,;?!()\[\]])', r' \1 ', conteudo_ref or "")
        norm_bel = re.sub(r'([.,;?!()\[\]])', r' \1 ', conteudo_belfar or "")
        norm_ref = normalizar_texto(norm_ref)
        norm_bel = normalizar_texto(norm_bel)

        tem_diferenca = False
        if norm_ref != norm_bel:
            tem_diferenca = True
            diferencas_conteudo.append({'secao': sec, 'conteudo_ref': conteudo_ref, 'conteudo_belfar': conteudo_belfar})
            similaridades_secoes.append(0)
        else:
            similaridades_secoes.append(100)

        secoes_analisadas.append({
            'secao': sec, 'conteudo_ref': conteudo_ref, 'conteudo_belfar': conteudo_belfar,
            'titulo_encontrado_ref': titulo_ref, 'titulo_encontrado_belfar': titulo_belfar,
            'tem_diferenca': tem_diferenca, 'ignorada': False, 'faltante': False
        })
    return secoes_faltantes, diferencas_conteudo, similaridades_secoes, diferencas_titulos, secoes_analisadas

# ----------------- ORTOGRAFIA -----------------
def checar_ortografia_inteligente(texto_para_checar, texto_referencia):
    if not texto_para_checar: return []
    try:
        secoes_ignorar = [s.upper() for s in obter_secoes_ignorar_ortografia()]
        secoes_todas = obter_secoes_por_tipo()
        texto_filtrado = []
        mapa, _, linhas = mapear_secoes_deterministico(texto_para_checar, secoes_todas)
        for sec in secoes_todas:
            if sec.upper() in secoes_ignorar: continue
            enc, _, cont = obter_dados_secao_v2(sec, mapa, linhas)
            if enc and cont: texto_filtrado.append(cont)
        texto_final = '\n'.join(texto_filtrado)
        if not texto_final: return []
        spell = SpellChecker(language='pt')
        palavras_ignorar = {"alair", "belfar", "peticionamento", "urotrobel", "nebacetin", "neomicina", "bacitracina", "sac"}
        vocab_ref_raw = set(re.findall(r'\b[a-zA-ZÀ-ÖØ-öø-ÿ0-9\-]+\b', (texto_referencia or "").lower()))
        spell.word_frequency.load_words(vocab_ref_raw.union(palavras_ignorar))
        entidades = set()
        if nlp:
            doc = nlp(texto_final)
            entidades = {ent.text.lower() for ent in doc.ents}
        palavras = re.findall(r'\b[a-zA-ZÀ-ÖØ-öø-ÿ]+\b', texto_final)
        palavras = [p for p in palavras if len(p) > 2]
        possiveis_erros = set(spell.unknown([p.lower() for p in palavras]))
        erros_filtrados = []
        vocab_norm = set(normalizar_texto(w) for w in vocab_ref_raw)
        for e in possiveis_erros:
            e_raw = e.lower()
            e_norm = normalizar_texto(e_raw)
            if e_raw in vocab_ref_raw or e_norm in vocab_norm: continue
            if e_raw in entidades or e_raw in palavras_ignorar: continue
            erros_filtrados.append(e_raw)
        return sorted(set(erros_filtrados))[:60]
    except: return []

def marcar_diferencas_palavra_por_palavra(texto_ref, texto_belfar, eh_referencia):
    def pre_norm(txt): return re.sub(r'([.,;?!()\[\]])', r' \1 ', txt or "")
    def tokenizar(txt): return re.findall(r'\n|[A-Za-zÀ-ÖØ-öø-ÿ0-9_•]+|[^\w\s]', pre_norm(txt), re.UNICODE)
    def norm(tok):
        if tok == '\n': return ' '
        if re.match(r'[A-Za-zÀ-ÖØ-öø-ÿ0-9_•]+$', tok): return normalizar_texto(tok)
        return tok.strip()

    ref_tokens = tokenizar(texto_ref)
    bel_tokens = tokenizar(texto_belfar)
    ref_norm = [norm(t) for t in ref_tokens]
    bel_norm = [norm(t) for t in bel_tokens]
    matcher = difflib.SequenceMatcher(None, ref_norm, bel_norm, autojunk=False)
    indices = set()
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != 'equal': indices.update(range(i1, i2) if eh_referencia else range(j1, j2))
    tokens = ref_tokens if eh_referencia else bel_tokens
    marcado = []
    for idx, tok in enumerate(tokens):
        if tok == '\n': marcado.append('<br>'); continue
        if idx in indices and tok.strip() != '': marcado.append(f"<mark class='diff'>{tok}</mark>")
        else: marcado.append(tok)
    resultado = ""
    for i, tok in enumerate(marcado):
        if i == 0: resultado += tok; continue
        raw_tok = re.sub(r'^<mark[^>]*>|</mark>$', '', tok)
        if re.match(r'^[.,;:!?)\\]$', raw_tok): resultado += tok
        elif tok == '<br>' or marcado[i-1] == '<br>' or re.match(r'^[(]$', re.sub(r'<[^>]+>', '', marcado[i-1])):
            resultado += tok
        else: resultado += " " + tok
    return re.sub(r"(</mark>)\s+(<mark[^>]*>)", " ", resultado)

# ----------------- HTML -----------------
def construir_html_secoes(secoes_analisadas, erros_ortograficos, eh_referencia=False):
    html_map = {}
    prefixos_paciente = {
        "PARA QUE ESTE MEDICAMENTO É INDICADO": "1.", "COMO ESTE MEDICAMENTO FUNCIONA?": "2.",
        "QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?": "3.", "O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?": "4.",
        "ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?": "5.", "COMO DEVO USAR ESTE MEDICAMENTO?": "6.",
        "O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?": "7.", "QUAIS OS MALES QUE ESTE MEDICAMENTO PODE CAUSAR?": "8.",
        "O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?": "9."
    }
    prefixos_map = prefixos_paciente
    mapa_erros = {}
    if erros_ortograficos and not eh_referencia:
        for erro in erros_ortograficos:
            pattern = r'(?<![<>a-zA-Z])(?<!mark>)(?<!;>)\b(' + re.escape(erro) + r')\b(?![<>])'
            mapa_erros[pattern] = r"<mark class='ort'>\1</mark>"
            
    regex_anvisa = r"((?:aprovad[ao]\s+pela\s+anvisa\s+em|data\s+de\s+aprovação\s+na\s+anvisa:)\s*[\d]{1,2}/[\d]{1,2}/[\d]{2,4})"
    anvisa_pattern = re.compile(regex_anvisa, re.IGNORECASE)
    
    for diff in secoes_analisadas:
        secao_canonico = diff['secao']
        prefixo = prefixos_map.get(secao_canonico, "")
        if eh_referencia:
            tit = f"{prefixo} {secao_canonico}".strip()
            title_html = f"<div class='section-title ref-title'>{tit}</div>"
            conteudo = diff['conteudo_ref'] or ""
        else:
            tit_enc = diff.get('titulo_encontrado_belfar') or diff.get('titulo_encontrado_ref') or secao_canonico
            tit = f"{prefixo} {tit_enc}".strip() if prefixo and not tit_enc.strip().startswith(prefixo) else tit_enc
            title_html = f"<div class='section-title bel-title'>{tit}</div>"
            conteudo = diff['conteudo_belfar'] or ""
        
        if diff.get('ignorada', False):
            conteudo_html = (conteudo or "").replace('\n', '<br>')
        else:
            conteudo_html = marcar_diferencas_palavra_por_palavra(diff.get('conteudo_ref') or "", diff.get('conteudo_belfar') or "", eh_referencia)
        
        conteudo_html = re.sub(r'(<br\s*/?>\s*){3,}', '<br><br>', conteudo_html)
        
        if not eh_referencia and not diff.get('ignorada', False):
            for pat, repl in mapa_erros.items():
                try: conteudo_html = re.sub(pat, repl, conteudo_html, flags=re.IGNORECASE)
                except: pass
        conteudo_html = anvisa_pattern.sub(r"<mark class='anvisa'>\1</mark>", conteudo_html)
        anchor_id = _create_anchor_id(secao_canonico, "ref" if eh_referencia else "bel")
        html_map[secao_canonico] = f"<div id='{anchor_id}' style='scroll-margin-top: 20px;'>{title_html}<div style='margin-top:6px;'>{conteudo_html}</div></div>"
    return html_map

def gerar_relatorio_final(texto_ref, texto_belfar, nome_ref, nome_belfar):
    st.header("Relatório de Auditoria Inteligente")
    rx_anvisa = r"(aprovad[ao]\s+pela\s+anvisa\s+em|data\s+de\s+aprovação\s+na\s+anvisa:)\s*([\d]{1,2}/[\d]{1,2}/[\d]{2,4})"
    m_ref = re.search(rx_anvisa, texto_ref or "", re.IGNORECASE)
    m_bel = re.search(rx_anvisa, texto_belfar or "", re.IGNORECASE)
    data_ref = m_ref.group(2).strip() if m_ref else "Não encontrada"
    data_bel = m_bel.group(2).strip() if m_bel else "Não encontrada"

    secoes_faltantes, diferencas_conteudo, similaridades, diferencas_titulos, secoes_analisadas = verificar_secoes_e_conteudo(texto_ref, texto_belfar)
    erros = checar_ortografia_inteligente(texto_belfar, texto_ref)
    score = sum(similaridades)/len(similaridades) if similaridades else 100.0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Conformidade", f"{score:.0f}%")
    c2.metric("Erros Ortográficos", len(erros))
    c3.metric("Data ANVISA (Ref)", data_ref)
    c4.metric("Data ANVISA (Bel)", data_bel)

    st.divider()
    
    # ---------------- ABA DEBUG (NOVIDADE) ----------------
    with st.expander("🛠️ Debug: Ver Texto Extraído Puro (Diagnóstico)", expanded=False):
        c_dbg1, c_dbg2 = st.columns(2)
        with c_dbg1:
            st.markdown(f"**Ref: {nome_ref}**")
            st.text_area("Texto Ref", texto_ref, height=200, label_visibility="collapsed")
        with c_dbg2:
            st.markdown(f"**Bel: {nome_belfar}**")
            st.text_area("Texto Bel", texto_belfar, height=200, label_visibility="collapsed")

    st.subheader("Seções (clique para expandir)")
    
    prefixos_paciente = {
        "PARA QUE ESTE MEDICAMENTO É INDICADO": "1.", "COMO ESTE MEDICAMENTO FUNCIONA?": "2.",
        "QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?": "3.", "O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?": "4.",
        "ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?": "5.", "COMO DEVO USAR ESTE MEDICAMENTO?": "6.",
        "O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?": "7.", "QUAIS OS MALES QUE ESTE MEDICAMENTO PODE CAUSAR?": "8.",
        "O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?": "9."
    }
    prefixos_map = prefixos_paciente

    html_ref = construir_html_secoes(secoes_analisadas, [], True)
    html_bel = construir_html_secoes(secoes_analisadas, erros, False)

    for diff in secoes_analisadas:
        sec = diff['secao']
        pref = prefixos_map.get(sec, "")
        tit = f"{pref} {sec}" if pref else sec
        status = "✅ Idêntico"
        if diff.get('faltante'): status = "🚨 FALTANTE"
        elif diff.get('ignorada'): status = "⚠️ Ignorada"
        elif diff.get('tem_diferenca'): status = "❌ Divergente"

        with st.expander(f"{tit} — {status}", expanded=(diff.get('tem_diferenca') or diff.get('faltante'))):
            c1, c2 = st.columns([1,1], gap="large")
            with c1:
                st.markdown(f"**Ref: {nome_ref}**", unsafe_allow_html=True)
                st.markdown(f"<div class='bula-box'>{html_ref.get(sec, '<i>N/A</i>')}</div>", unsafe_allow_html=True)
            with c2:
                st.markdown(f"**Bel: {nome_belfar}**", unsafe_allow_html=True)
                st.markdown(f"<div class='bula-box'>{html_bel.get(sec, '<i>N/A</i>')}</div>", unsafe_allow_html=True)

    st.divider()
    st.subheader("🎨 Visualização Completa")
    full_order = [s['secao'] for s in secoes_analisadas]
    h_r = "".join([html_ref.get(s, "") for s in full_order])
    h_b = "".join([html_bel.get(s, "") for s in full_order])
    
    cr, cb = st.columns(2, gap="large")
    with cr: st.markdown(f"**📄 {nome_ref}**<div class='bula-box'>{h_r}</div>", unsafe_allow_html=True)
    with cb: st.markdown(f"**📄 {nome_belfar}**<div class='bula-box'>{h_b}</div>", unsafe_allow_html=True)

# ----------------- MAIN -----------------
st.title("🔬 Inteligência Artificial para Auditoria de Bulas (v79)")
st.markdown("Sistema com Reconstrução de Títulos e Seletor de Layout.")

st.divider()

col1, col2 = st.columns(2)
with col1:
    st.subheader("📄 Arquivo ANVISA")
    pdf_ref = st.file_uploader("PDF/DOCX Referência", type=["pdf", "docx"], key="ref")
with col2:
    st.subheader("📄 Arquivo MKT")
    pdf_belfar = st.file_uploader("PDF/DOCX Belfar", type=["pdf", "docx"], key="belfar")
    # NOVIDADE: OPÇÃO DE LAYOUT
    modo_leitura = st.radio("Modo de Leitura (Belfar)", ["Automático (Recomendado)", "Forçar 2 Colunas"], horizontal=True, index=0)

if st.button("🔍 Iniciar Auditoria Completa", use_container_width=True, type="primary"):
    if not (pdf_ref and pdf_belfar):
        st.warning("⚠️ Envie ambos os arquivos.")
    else:
        with st.spinner("Processando arquivos..."):
            modo_bel_code = "2col" if modo_leitura == "Forçar 2 Colunas" else "auto"
            
            # Extração
            texto_ref_raw, erro_ref = extrair_texto(pdf_ref, 'docx' if pdf_ref.name.endswith('.docx') else 'pdf', False, "auto")
            texto_belfar_raw, erro_belfar = extrair_texto(pdf_belfar, 'docx' if pdf_belfar.name.endswith('.docx') else 'pdf', True, modo_bel_code)

            if erro_ref or erro_belfar:
                st.error(f"Erro de leitura: {erro_ref or erro_belfar}")
            else:
                # Reconstrução
                t_ref = reconstruir_paragrafos(texto_ref_raw)
                t_ref = truncar_apos_anvisa(t_ref)
                
                t_bel = reconstruir_paragrafos(texto_belfar_raw)
                t_bel = truncar_apos_anvisa(t_bel)
                
                gerar_relatorio_final(t_ref, t_bel, pdf_ref.name, pdf_belfar.name)

st.divider()
st.caption("Sistema de Auditoria de Bulas v79 | v77 Base + Reconstrução de Títulos + Seletor de Colunas.")
