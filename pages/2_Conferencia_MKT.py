# pages/2_Conferencia_MKT.py
#
# Versão v94 - "Canonical Anchor Slicing" + Fix NameError
# - CORREÇÃO: Restauradas as funções 'obter_secoes_ignorar_comparacao' e 'obter_secoes_ignorar_ortografia' que faltavam.
# - LÓGICA: Mantém a estratégia v93 de usar APENAS a lista de 13 títulos para fatiar o texto.
# - RESULTADO: O erro de NameError sumirá e a separação será rígida pelos títulos oficiais.

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
  height: 350px;
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
  margin: 12px 0 8px;
  padding-top: 8px;
  border-top: 1px solid #eee;
}

.ref-title { color: #0b5686; }
.bel-title { color: #0b8a3e; }

mark.diff { background-color: #ffff99; padding: 0 2px; color: black; }
mark.ort { background-color: #ffdfd9; padding: 0 2px; color: black; border-bottom: 1px dashed red; }
mark.anvisa { background-color: #DDEEFF; padding: 0 2px; color: black; border: 1px solid #0000FF; }
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

# ----------------- LISTA MESTRA DE SEÇÕES (HARDCODED) -----------------
def get_canonical_sections():
    """
    Retorna a lista exata de títulos que o sistema deve respeitar.
    Qualquer coisa fora disso é conteúdo.
    """
    return [
        "APRESENTAÇÕES",
        "COMPOSIÇÃO",
        "1.PARA QUE ESTE MEDICAMENTO É INDICADO?",
        "2.COMO ESTE MEDICAMENTO FUNCIONA?",
        "3.QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?",
        "4.O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?",
        "5.ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?",
        "6.COMO DEVO USAR ESTE MEDICAMENTO?",
        "7.O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?",
        "8.QUAIS OS MALES QUE ESTE MEDICAMENTO PODE CAUSAR?",
        "9.O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?",
        "DIZERES LEGAIS"
    ]

# --- FUNÇÕES RESTAURADAS (FIX NAME ERROR) ---
def obter_secoes_ignorar_comparacao(): 
    return ["APRESENTAÇÕES", "COMPOSIÇÃO", "DIZERES LEGAIS"]

def obter_secoes_ignorar_ortografia(): 
    return ["COMPOSIÇÃO", "DIZERES LEGAIS"]

# ----------------- UTILITÁRIOS -----------------
def normalizar_texto(texto):
    if not isinstance(texto, str): return ""
    texto = texto.replace('\n', ' ')
    texto = ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')
    texto = re.sub(r'[^\w\s]', '', texto)
    texto = ' '.join(texto.split())
    return texto.lower()

def normalizar_titulo_para_comparacao(texto):
    # Remove tudo que não é letra ou número para comparação bruta
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

# ----------------- FILTRO DE LIXO -----------------
def limpar_lixo_grafico(texto):
    padroes_lixo = [
        r'\b\d{1,3}\s*[,.]\s*\d{0,2}\s*cm\b', 
        r'\b\d{1,3}\s*[,.]\s*\d{0,2}\s*mm\b',
        r'Merlidu\s*sa.*', r'Fuenteerso', r'Tipologia\s*da\s*bula.*', 
        r'ALTEFAR', r'Impressão:.*', r'Cor:\s*Phats.*',
        r'.*31\s*2105.*', r'.*w\s*Roman.*', r'.*Negrito\.\s*Corpo\s*14.*',
        r'AZOLINA:', r'contato:', r'artes\s*@\s*belfar\.com\.br',
        r'^\s*VERSO\s*$', r'^\s*FRENTE\s*$', r'.*Frente\s*/\s*Verso.*',
        r'.*-\s*\.\s*Cor.*', r'.*Cor:\s*Preta.*', r'.*Papel:.*', r'.*Ap\s*\d+gr.*', 
        r'.*da bula:.*', r'.*AFAZOLINA_BUL.*', r'bula do paciente', 
        r'página \d+\s*de\s*\d+', r'^\s*\d+\s*$',
        r'Tipologia', r'Dimensão', r'Dimensões', r'Formato',
        r'Times New Roman', r'Myriad Pro', r'Arial', r'Helvética',
        r'Cores?:', r'Preto', r'Black', r'Cyan', r'Magenta', r'Yellow', r'Pantone',
        r'^\s*\d+[,.]?\d*\s*mm\s*$', r'\b\d{2,4}\s*x\s*\d{2,4}\s*mm\b',
        r'^\s*BELFAR\s*$', r'^\s*PHARMA\s*$',
        r'CNPJ:?', r'SAC:?', r'Farm\. Resp\.?:?', r'CRF-?MG',
        r'Cód\.?:?', r'Ref\.?:?', r'Laetus', r'Pharmacode',
        r'.*AZOLINA:\s*Tim.*', r'.*NAFAZOLINA:\s*Times.*', 
        r'\b\d{6,}\s*-\s*\d{2}/\d{2}\b', r'^\s*[\w_]*BUL\d+V\d+[\w_]*\s*$',
        r'.*New\s*Roman.*', r'.*r?po\s*10.*', r'.*BUL_CLORIDRATO.*', 
        r'.*Impress[ãa]o.*', r'.*Normal\s*e\s*Negrito.*'
    ]
    texto_limpo = texto
    for p in padroes_lixo:
        texto_limpo = re.sub(p, ' ', texto_limpo, flags=re.IGNORECASE | re.MULTILINE)
    return texto_limpo

def forcar_titulos_bula(texto):
    """
    Força a padronização EXATA dos títulos para bater com a lista canônica.
    """
    substituicoes = [
        (r"(?:1\.?\s*)?PARA\s*QUE\s*ESTE\s*MEDICAMENTO\s*[\s\S]{0,100}?INDICADO\??",
         r"\n1.PARA QUE ESTE MEDICAMENTO É INDICADO?\n"),

        (r"(?:2\.?\s*)?COMO\s*ESTE\s*MEDICAMENTO\s*[\s\S]{0,100}?FUNCIONA\??",
         r"\n2.COMO ESTE MEDICAMENTO FUNCIONA?\n"),

        (r"(?:3\.?\s*)?QUANDO\s*N[ÃA]O\s*DEVO\s*USAR\s*[\s\S]{0,100}?MEDICAMENTO\??",
         r"\n3.QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?\n"),

        (r"(?:4\.?\s*)?O\s*QUE\s*DEVO\s*SABER[\s\S]{1,100}?USAR[\s\S]{1,100}?MEDICAMENTO\??",
         r"\n4.O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?\n"),

        (r"(?:5\.?\s*)?ONDE\s*,?\s*COMO\s*E\s*POR\s*QUANTO[\s\S]{1,100}?GUARDAR[\s\S]{1,100}?MEDICAMENTO\??",
         r"\n5.ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?\n"),
          
        (r"(?:6\.?\s*)?COMO\s*DEVO\s*USAR\s*ESTE\s*[\s\S]{0,100}?MEDICAMENTO\??",
         r"\n6.COMO DEVO USAR ESTE MEDICAMENTO?\n"),

        (r"(?:7\.?\s*)?O\s*QUE\s*DEVO\s*FAZER[\s\S]{0,200}?MEDICAMENTO\??", 
         r"\n7.O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?\n"),
          
        (r"(?:8\.?\s*)?QUAIS\s*OS\s*MALES[\s\S]{0,200}?CAUSAR\??", 
         r"\n8.QUAIS OS MALES QUE ESTE MEDICAMENTO PODE CAUSAR?\n"),
          
        (r"(?:9\.?\s*)?O\s*QUE\s*FAZER\s*SE\s*ALGU[EÉ]M\s*USAR[\s\S]{0,400}?MEDICAMENTO\??", 
         r"\n9.O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?\n"),
         
        (r"(?:DIZERES\s*LEGAIS)", r"\nDIZERES LEGAIS\n")
    ]
    
    texto_arrumado = texto
    for padrao, substituto in substituicoes:
        texto_arrumado = re.sub(padrao, substituto, texto_arrumado, flags=re.IGNORECASE | re.DOTALL)
    return texto_arrumado

# ----------------- EXTRAÇÃO 3 COLUNAS AJUSTADA -----------------
def detectar_num_colunas(page):
    """Detecta se a página tem 2 ou 3 colunas analisando a distribuição horizontal dos blocos."""
    rect = page.rect
    blocks = page.get_text("blocks")
    
    if not blocks:
        return 2  # Default para 2 colunas
    
    # Coleta as posições horizontais dos centros dos blocos
    posicoes_x = []
    for b in blocks:
        if b[6] == 0:  # Apenas texto
            center_x = (b[0] + b[2]) / 2
            posicoes_x.append(center_x)
    
    if not posicoes_x:
        return 2
    
    # Divide a largura em 3 terços e conta quantos blocos tem em cada
    largura = rect.width
    terco1 = largura / 3
    terco2 = 2 * largura / 3
    
    col1 = sum(1 for x in posicoes_x if x < terco1)
    col2 = sum(1 for x in posicoes_x if terco1 <= x < terco2)
    col3 = sum(1 for x in posicoes_x if x >= terco2)
    
    # Se temos blocos substanciais nas 3 regiões, é 3 colunas
    total = len(posicoes_x)
    if col1 > total * 0.15 and col2 > total * 0.15 and col3 > total * 0.15:
        return 3
    
    return 2
def extrair_texto(arquivo, tipo_arquivo, is_marketing_pdf=False):
    if arquivo is None: return "", f"Arquivo {tipo_arquivo} não enviado."
    try:
        arquivo.seek(0)
        texto_completo = ""

        if tipo_arquivo == 'pdf':
            with fitz.open(stream=arquivo.read(), filetype="pdf") as doc:
                for page in doc:
                    rect = page.rect
                    width = rect.width
                    margem_y = rect.height * 0.01 
                    
                    if is_marketing_pdf:
                 # Detecta número de colunas automaticamente
                 num_colunas = detectar_num_colunas(page)
              blocks = page.get_text("blocks")
    
    if num_colunas == 3:
        # Layout de 3 colunas com suporte a blocos multi-coluna
        largura = rect.width
        terco1 = largura / 3
        terco2 = 2 * largura / 3
        
        # Lista única para blocos largos (títulos que ocupam 2-3 colunas)
        blocos_ordenados = []
        
        for b in blocks:
            if b[6] == 0:  # Apenas texto
                if b[1] >= margem_y and b[3] <= (rect.height - margem_y):
                    largura_bloco = b[2] - b[0]
                    b_center_x = (b[0] + b[2]) / 2
                    
                    # Classifica o bloco:
                    # - Blocos muito largos (>60% da página) = títulos de seção que ocupam múltiplas colunas
                    # - Blocos largos (>40%) = podem ser sub-títulos ou parágrafos que cruzam 2 colunas
                    # - Blocos normais = texto de coluna única
                    
                    if largura_bloco > largura * 0.6:
                        # Título principal - ocupa 2-3 colunas
                        tipo = 'titulo_largo'
                        coluna = 0  # Primeira posição na ordenação
                    elif largura_bloco > largura * 0.4:
                        # Bloco médio - pode ocupar 2 colunas
                        tipo = 'bloco_medio'
                        # Define coluna pelo centro
                        if b_center_x < terco1:
                            coluna = 1
                        elif b_center_x < terco2:
                            coluna = 2
                        else:
                            coluna = 3
                    else:
                        # Bloco normal - 1 coluna
                        tipo = 'normal'
                        if b_center_x < terco1:
                            coluna = 1
                        elif b_center_x < terco2:
                            coluna = 2
                        else:
                            coluna = 3
                    
                    # Adiciona: (posição_Y, coluna, tipo, bloco)
                    blocos_ordenados.append((b[1], coluna, tipo, b))
        
        # Ordena por: 1) Posição Y (linha), 2) Coluna (esquerda para direita)
        # Isso garante que na mesma "linha" visual, lemos col1 -> col2 -> col3
        blocos_ordenados.sort(key=lambda x: (x[0], x[1]))
        
        # Reconstrói o texto
        for _, _, _, b in blocos_ordenados:
            texto_completo += b[4] + "\n"
    
    else:
        # Layout de 2 colunas (código original)
        meio_x = rect.width / 2
        col_esq = []
        col_dir = []
        
        for b in blocks:
            if b[6] == 0:
                if b[1] >= margem_y and b[3] <= (rect.height - margem_y):
                    b_center_x = (b[0] + b[2]) / 2
                    if b_center_x < meio_x:
                        col_esq.append(b)
                    else:
                        col_dir.append(b)
        
        col_esq.sort(key=lambda x: x[1])
        col_dir.sort(key=lambda x: x[1])
        
        for b in col_esq: texto_completo += b[4] + "\n"
        for b in col_dir: texto_completo += b[4] + "\n"

        elif tipo_arquivo == 'docx':
            doc = docx.Document(arquivo)
            texto_completo = "\n".join([p.text for p in doc.paragraphs])

        if texto_completo:
            invis = ['\u00AD', '\u200B', '\u200C', '\u200D', '\uFEFF']
            for c in invis: texto_completo = texto_completo.replace(c, '')
            texto_completo = texto_completo.replace('\r\n', '\n').replace('\r', '\n').replace('\u00A0', ' ')

            texto_completo = limpar_lixo_grafico(texto_completo)
            
c

# ----------------- PARSER BASEADO EM ÂNCORAS CANÔNICAS -----------------
def identificar_ancoras_secoes(texto):
    """
    Varre o texto e retorna um dicionário {Nome_Seção: Indice_Linha}.
    SÓ aceita matches que batem com a lista canônica.
    """
    linhas = texto.split('\n')
    secoes_esperadas = get_canonical_sections()
    ancoras = {}
    
    # Normalização prévia das seções esperadas para busca
    secoes_norm = {normalizar_titulo_para_comparacao(s): s for s in secoes_esperadas}
    
    for i, linha in enumerate(linhas):
        linha_limpa = linha.strip()
        if len(linha_limpa) < 5: continue
        
        norm_linha = normalizar_titulo_para_comparacao(linha_limpa)
        
        # 1. Match Exato ou Muito Próximo
        matched_canon = None
        for s_norm, s_canon in secoes_norm.items():
            # Verifica se a linha NORMALIZADA é igual ao título NORMALIZADO
            # Ou se a linha começa com o título (ex: "3. QUANDO..." e lixo depois)
            if s_norm == norm_linha or (len(s_norm) > 10 and norm_linha.startswith(s_norm)):
                matched_canon = s_canon
                break
            # Fuzzy ratio alto (>95)
            if fuzz.ratio(s_norm, norm_linha) > 95:
                matched_canon = s_canon
                break
                
        if matched_canon:
            # Só registra se for a primeira vez que encontra (evita duplicatas falsas)
            if matched_canon not in ancoras:
                ancoras[matched_canon] = i
                
    return ancoras, linhas

def fatiar_texto_por_ancoras(ancoras, linhas):
    """
    Usa os índices das âncoras para fatiar o texto.
    Seção X = Texto entre (Linha da Seção X) e (Linha da Próxima Seção Encontrada).
    """
    secoes_esperadas = get_canonical_sections()
    resultado = {}
    
    # Ordena as âncoras encontradas por linha
    ancoras_ordenadas = sorted(ancoras.items(), key=lambda x: x[1])
    
    for i in range(len(ancoras_ordenadas)):
        nome_secao, linha_inicio = ancoras_ordenadas[i]
        
        # Define o fim: é a linha da próxima seção ou o fim do arquivo
        if i < len(ancoras_ordenadas) - 1:
            linha_fim = ancoras_ordenadas[i+1][1]
        else:
            linha_fim = len(linhas)
            
        # Extrai conteúdo (pula a linha do título)
        conteudo_bruto = linhas[linha_inicio+1 : linha_fim]
        resultado[nome_secao] = "\n".join(conteudo_bruto).strip()
        
    return resultado

# ----------------- VERIFICAÇÃO -----------------
def verificar_secoes_e_conteudo(texto_ref, texto_belfar):
    secoes_esperadas = get_canonical_sections()
    ignore_comparison = [s.upper() for s in obter_secoes_ignorar_comparacao()]
    
    # 1. Identificar Âncoras
    ancoras_ref, linhas_ref = identificar_ancoras_secoes(texto_ref)
    ancoras_bel, linhas_bel = identificar_ancoras_secoes(texto_belfar)
    
    # 2. Fatiar Conteúdo
    conteudo_ref_map = fatiar_texto_por_ancoras(ancoras_ref, linhas_ref)
    conteudo_bel_map = fatiar_texto_por_ancoras(ancoras_bel, linhas_bel)
    
    secoes_faltantes = []
    diferencas_conteudo = []
    similaridades_secoes = []
    secoes_analisadas = []

    for sec in secoes_esperadas:
        cont_ref = conteudo_ref_map.get(sec)
        cont_bel = conteudo_bel_map.get(sec)
        
        # Status de Encontrado
        encontrou_ref = (cont_ref is not None)
        encontrou_bel = (cont_bel is not None)
        
        if not encontrou_bel:
            secoes_faltantes.append(sec)
            secoes_analisadas.append({
                'secao': sec, 'conteudo_ref': cont_ref or "Seção não encontrada",
                'conteudo_belfar': "SEÇÃO NÃO ENCONTRADA (Verifique se o título está exato)",
                'tem_diferenca': True, 'ignorada': False, 'faltante': True
            })
            continue
            
        if not encontrou_ref:
             secoes_analisadas.append({
                'secao': sec, 'conteudo_ref': "Seção não encontrada na Referência",
                'conteudo_belfar': cont_bel,
                'tem_diferenca': True, 'ignorada': False, 'faltante': True
            })
             continue

        if sec.upper() in ignore_comparison:
            secoes_analisadas.append({
                'secao': sec, 'conteudo_ref': cont_ref, 'conteudo_belfar': cont_bel,
                'tem_diferenca': False, 'ignorada': True, 'faltante': False
            })
            continue

        # Comparação
        norm_ref = re.sub(r'([.,;?!()\[\]])', r' \1 ', cont_ref or "")
        norm_bel = re.sub(r'([.,;?!()\[\]])', r' \1 ', cont_bel or "")
        norm_ref = normalizar_texto(norm_ref)
        norm_bel = normalizar_texto(norm_bel)

        tem_diferenca = False
        if norm_ref != norm_bel:
            tem_diferenca = True
            diferencas_conteudo.append({'secao': sec, 'conteudo_ref': cont_ref, 'conteudo_belfar': cont_bel})
            similaridades_secoes.append(0)
        else:
            similaridades_secoes.append(100)

        secoes_analisadas.append({
            'secao': sec, 'conteudo_ref': cont_ref, 'conteudo_belfar': cont_bel,
            'tem_diferenca': tem_diferenca, 'ignorada': False, 'faltante': False
        })
        
    return secoes_faltantes, diferencas_conteudo, similaridades_secoes, [], secoes_analisadas

# ----------------- ORTOGRAFIA & DIFF -----------------
def checar_ortografia_inteligente(texto_para_checar, texto_referencia):
    if not texto_para_checar: return []
    try:
        spell = SpellChecker(language='pt')
        palavras_ignorar = {"alair", "belfar", "peticionamento", "urotrobel", "nebacetin", "neomicina", "bacitracina", "sac"}
        vocab_ref_raw = set(re.findall(r'\b[a-zA-ZÀ-ÖØ-öø-ÿ0-9\-]+\b', (texto_referencia or "").lower()))
        spell.word_frequency.load_words(vocab_ref_raw.union(palavras_ignorar))
        palavras = re.findall(r'\b[a-zA-ZÀ-ÖØ-öø-ÿ]+\b', texto_para_checar)
        palavras = [p for p in palavras if len(p) > 2]
        possiveis_erros = set(spell.unknown([p.lower() for p in palavras]))
        erros_filtrados = []
        vocab_norm = set(normalizar_texto(w) for w in vocab_ref_raw)
        for e in possiveis_erros:
            e_raw = e.lower()
            e_norm = normalizar_texto(e_raw)
            if e_raw in vocab_ref_raw or e_norm in vocab_norm: continue
            if e_raw in palavras_ignorar: continue
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

# ----------------- CONSTRUÇÃO HTML -----------------
def construir_html_secoes(secoes_analisadas, erros_ortograficos, eh_referencia=False):
    html_map = {}
    mapa_erros = {}
    if erros_ortograficos and not eh_referencia:
        for erro in erros_ortograficos:
            pattern = r'(?<![<>a-zA-Z])(?<!mark>)(?<!;>)\b(' + re.escape(erro) + r')\b(?![<>])'
            mapa_erros[pattern] = r"<mark class='ort'>\1</mark>"
    regex_anvisa = r"((?:aprovad[ao]\s+pela\s+anvisa\s+em|data\s+de\s+aprovação\s+na\s+anvisa:)\s*[\d]{1,2}/[\d]{1,2}/[\d]{2,4})"
    anvisa_pattern = re.compile(regex_anvisa, re.IGNORECASE)
    
    for diff in secoes_analisadas:
        secao_canonico = diff['secao']
        if eh_referencia:
            title_html = f"<div class='section-title ref-title'>{secao_canonico}</div>"
            conteudo = diff['conteudo_ref'] or ""
        else:
            title_html = f"<div class='section-title bel-title'>{secao_canonico}</div>"
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

def gerar_relatorio_final(texto_ref, texto_belfar, nome_ref, nome_belfar, tipo_bula):
    st.header("Relatório de Auditoria Inteligente")
    rx_anvisa = r"(aprovad[ao]\s+pela\s+anvisa\s+em|data\s+de\s+aprovação\s+na\s+anvisa:)\s*([\d]{1,2}/[\d]{1,2}/[\d]{2,4})"
    m_ref = re.search(rx_anvisa, texto_ref or "", re.IGNORECASE)
    m_bel = re.search(rx_anvisa, texto_belfar or "", re.IGNORECASE)
    data_ref = m_ref.group(2).strip() if m_ref else "Não encontrada"
    data_bel = m_bel.group(2).strip() if m_bel else "Não encontrada"

    secoes_faltantes, diferencas_conteudo, similaridades, _, secoes_analisadas = verificar_secoes_e_conteudo(texto_ref, texto_belfar)
    erros = checar_ortografia_inteligente(texto_belfar, texto_ref)
    score = sum(similaridades)/len(similaridades) if similaridades else 100.0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Conformidade", f"{score:.0f}%")
    c2.metric("Erros Ortográficos", len(erros))
    c3.metric("Data ANVISA (Ref)", data_ref)
    c4.metric("Data ANVISA (Bel)", data_bel)

    st.divider()
    st.subheader("Seções (clique para expandir)")
    
    html_ref = construir_html_secoes(secoes_analisadas, [], True)
    html_bel = construir_html_secoes(secoes_analisadas, erros, False)

    for diff in secoes_analisadas:
        sec = diff['secao']
        status = "✅ Idêntico"
        if diff.get('faltante'): status = "🚨 FALTANTE"
        elif diff.get('ignorada'): status = "⚠️ Ignorada"
        elif diff.get('tem_diferenca'): status = "❌ Divergente"

        with st.expander(f"{sec} — {status}", expanded=(diff.get('tem_diferenca') or diff.get('faltante'))):
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
    with cr: st.markdown(f"**📄 {nome_ref}**<div class='bula-box-full'>{h_r}</div>", unsafe_allow_html=True)
    with cb: st.markdown(f"**📄 {nome_belfar}**<div class='bula-box-full'>{h_b}</div>", unsafe_allow_html=True)

# ----------------- VALIDAÇÃO DE TIPO -----------------
def detectar_tipo_arquivo_por_score(texto):
    if not texto: return "Indeterminado"
    titulos_paciente = ["como este medicamento funciona", "o que devo saber antes de usar"]
    titulos_profissional = ["resultados de eficacia", "caracteristicas farmacologicas"]
    t_norm = normalizar_texto(texto)
    score_pac = sum(1 for t in titulos_paciente if t in t_norm)
    score_prof = sum(1 for t in titulos_profissional if t in t_norm)
    if score_pac > score_prof: return "Paciente"
    elif score_prof > score_pac: return "Profissional"
    return "Indeterminado"

# ----------------- MAIN -----------------
st.title("🔬 Inteligência Artificial para Auditoria de Bulas (v94)")
st.markdown("Sistema com Fatiamento por Âncoras Canônicas (Ignora subtítulos).")

st.divider()
tipo_bula_selecionado = "Paciente" # Fixo

col1, col2 = st.columns(2)
with col1:
    st.subheader("📄 Arquivo ANVISA")
    pdf_ref = st.file_uploader("PDF/DOCX Referência", type=["pdf", "docx"], key="ref")
with col2:
    st.subheader("📄 Arquivo MKT")
    pdf_belfar = st.file_uploader("PDF/DOCX Belfar", type=["pdf", "docx"], key="belfar")

if st.button("🔍 Iniciar Auditoria Completa", use_container_width=True, type="primary"):
    if not (pdf_ref and pdf_belfar):
        st.warning("⚠️ Envie ambos os arquivos.")
    else:
        with st.spinner("Lendo arquivos, removendo lixo gráfico e validando estrutura..."):
            # Extração MKT (Split-Column) e Anvisa (Padrão)
            texto_ref_raw, erro_ref = extrair_texto(pdf_ref, 'docx' if pdf_ref.name.endswith('.docx') else 'pdf', is_marketing_pdf=False)
            texto_belfar_raw, erro_belfar = extrair_texto(pdf_belfar, 'docx' if pdf_belfar.name.endswith('.docx') else 'pdf', is_marketing_pdf=True)

            if erro_ref or erro_belfar:
                st.error(f"Erro de leitura: {erro_ref or erro_belfar}")
            else:
                detectado_ref = detectar_tipo_arquivo_por_score(texto_ref_raw)
                detectado_bel = detectar_tipo_arquivo_por_score(texto_belfar_raw)
                
                erro = False
                if detectado_ref == "Profissional": 
                    st.error(f"🚨 Arquivo ANVISA parece Bula Profissional. Use Paciente."); erro=True
                if detectado_bel == "Profissional":
                    st.error(f"🚨 Arquivo MKT parece Bula Profissional. Use Paciente."); erro=True
                
                if not erro:
                    # Não precisamos mais de reconstruir_paragrafos agressivo aqui,
                    # pois o fatiador de ancoras cuida disso.
                    # Apenas limpamos ANVISA
                    t_ref = truncar_apos_anvisa(texto_ref_raw)
                    t_bel = truncar_apos_anvisa(texto_belfar_raw)
                    
                    gerar_relatorio_final(t_ref, t_bel, pdf_ref.name, pdf_belfar.name, tipo_bula_selecionado)

st.divider()
st.caption("Sistema de Auditoria de Bulas v94 | Base v93 + Fix NameError.")
