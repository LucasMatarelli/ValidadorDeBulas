# pages/2_Conferencia_MKT.py
#
# Versão v40 - Correção Definitiva do Mapeamento
# - CORRIGIDA a função 'corrigir_quebras_em_titulos' (v40).
#   Ela agora ignora linhas vazias e junta corretamente os
#   títulos de MKT separados por '\n\n'.
# - Isso corrige o bug "4 não ta puxando" e o "6 engolindo 7".
# - Mantém o foco 100% em Paciente e o layout "achatado" do MKT.
# - Mantém a correção do '\n' em 'normalizar_texto' (v32).
# - Mantém a correção do 'is_titulo_secao' (v34).

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

# ----------------- MODELO NLP (carregado apenas uma vez) -----------------
@st.cache_resource
def carregar_modelo_spacy():
    try:
        return spacy.load("pt_core_news_lg")
    except OSError:
        st.warning("Modelo 'pt_core_news_lg' não encontrado. Algumas funções ficam reduzidas.")
        return None

nlp = carregar_modelo_spacy()

# ----------------- UTILITÁRIOS DE NORMALIZAÇÃO (v32) -----------------
def normalizar_texto(texto):
    if not isinstance(texto, str):
        return ""
    texto = texto.replace('\n', ' ') # <-- [CORREÇÃO V32] Essencial para comparar títulos MKT
    texto = ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')
    texto = re.sub(r'[^\w\s]', '', texto)
    texto = ' '.join(texto.split())
    return texto.lower()

def normalizar_titulo_para_comparacao(texto):
    texto_norm = normalizar_texto(texto or "")
    texto_norm = re.sub(r'^\d+\s*[\.\-)]*\s*', '', texto_norm).strip()
    return texto_norm

# ----------------- FUNÇÃO MISSING: truncar_apos_anvisa -----------------
def truncar_apos_anvisa(texto):
    """
    Corta o texto após a menção de aprovação na ANVISA (mantém até a data).
    Retorna o texto truncado ou o texto original se não encontrar a expressão.
    """
    if not isinstance(texto, str):
        return texto
    regex_anvisa = r"((?:aprovad[ao]\s+pela\s+anvisa\s+em|data\s+de\s+aprova\w+\s+na\s+anvisa:)\s*([\d]{1,2}\s*/\s*[\d]{1,2}\s*/\s*[\d]{2,4}))"
    match = re.search(regex_anvisa, texto, re.IGNORECASE)
    if not match:
        return texto
    cut_off_position = match.end(1)
    # mantem um possível ponto logo após
    pos_match = re.search(r'^\s*\.', texto[cut_off_position:], re.IGNORECASE)
    if pos_match:
        cut_off_position += pos_match.end()
    return texto[:cut_off_position]

# ----------------- EXTRAÇÃO (PDF/DOCX) -----------------
def extrair_texto(arquivo, tipo_arquivo, is_marketing_pdf=False):
    if arquivo is None:
        return "", f"Arquivo {tipo_arquivo} não enviado."
    try:
        arquivo.seek(0)
        texto = ""
        full_text_list = []

        if tipo_arquivo == 'pdf':
            with fitz.open(stream=arquivo.read(), filetype="pdf") as doc:
                if is_marketing_pdf:
                    for page in doc:
                        rect = page.rect
                        clip_esquerda = fitz.Rect(0, 0, rect.width / 2, rect.height)
                        clip_direita = fitz.Rect(rect.width / 2, 0, rect.width, rect.height)
                        texto_esquerda = page.get_text("text", clip=clip_esquerda, sort=True)
                        texto_direita = page.get_text("text", clip=clip_direita, sort=True)
                        full_text_list.append(texto_esquerda)
                        full_text_list.append(texto_direita)
                else:
                    for page in doc:
                        full_text_list.append(page.get_text("text", sort=True))
            texto = "\n\n".join(full_text_list)
        elif tipo_arquivo == 'docx':
            doc = docx.Document(arquivo)
            texto = "\n".join([p.text for p in doc.paragraphs])

        if texto:
            # remove caracteres invisíveis e normaliza quebras
            caracteres_invisiveis = ['\u00AD', '\u200B', '\u200C', '\u200D', '\uFEFF']
            for c in caracteres_invisiveis:
                texto = texto.replace(c, '')
            texto = texto.replace('\r\n', '\n').replace('\r', '\n')
            texto = texto.replace('\u00A0', ' ')

            # padrões de ruído (mantidos da v26.58)
            padrao_ruido_linha_regex = (
                r'bula do paciente|página \d+\s*de\s*\d+'
                r'|(Tipologie|Tipologia) da bula:.*|(Merida|Medida) da (bula|trúa):?.*'
                r'|(Impressãe|Impressão):? Frente/Verso|Papel[\.:]? Ap \d+gr'
                r'|Cor:? Preta|contato:?|artes@belfar\.com\.br'
                r'|CLORIDRATO DE NAFAZOLINA: Times New Roman'
                r'|^\s*FRENTE\s*$|^\s*VERSO\s*$'
                r'|^\s*\d+\s*mm\s*$'
                r'|^\s*BELFAR\s*$|^\s*REZA\s*$|^\s*GEM\s*$|^\s*ALTEFAR\s*$|^\s*RECICLAVEL\s*$|^\s*BUL\d+\s*$'
                r'|BUL_CLORIDRATO_DE_[A-Z].*'
                r'|\d{2}\s\d{4}\s\d{4}.*'
                r'|cloridrato de ambroxo\s*$'
                r'|Normal e Negrito\. Co\s*$'
                r'|cloridrato de ambroxol Belfar Ltda\. Xarope \d+ mg/mL'
                r'|^\s*\d+\s+CLORIDRATO\s+DE\s+NAFAZOLINA.*'
            )
            padrao_ruido_linha = re.compile(padrao_ruido_linha_regex, re.IGNORECASE)

            padrao_ruido_inline_regex = (
                r'BUL_CLORIDRATO_DE_NA[\s\S]{0,20}?\d+'
                r'|New[\s\S]{0,10}?Roman[\s\S]{0,50}?(?:mm|\d+)'
                r'|AFAZOLINA_BUL\d+V\d+.*?'
                r'|BUL_CLORIDRATO_DE_NAFAZOLINA_BUL\d+V\d+'
                r'|AMBROXOL_BUL\d+V\d+'
                r'|es New Roman.*?'
                r'|rpo \d+.*?'
                r'|olL: Times New Roman.*?'
                r'|(?<=\s)\d{3}(?=\s[a-zA-Z])'
                r'|(?<=\s)mm(?=\s)'
            )
            padrao_ruido_inline = re.compile(padrao_ruido_inline_regex, re.IGNORECASE)

            texto = re.sub(r'(BUL_CLORIDRATO_DE_NAFAZOLINA)\s*(\d{2,4})', r'__KEEPBUL_\1_\2__', texto, flags=re.IGNORECASE)
            texto = padrao_ruido_inline.sub(' ', texto)
            texto = re.sub(
                r'__KEEPBUL_(BUL_CLORIDRATO_DE_NAFAZOLINA)_(\d{2,4})__',
                lambda m: f"{m.group(1).replace('_', ' ')} {m.group(2)}",
                texto,
                flags=re.IGNORECASE
            )

            # remover numeracao solta no MKT
            if is_marketing_pdf:
                texto = re.sub(r'(?m)^\s*\d{1,2}\.\s*', '', texto)
                texto = re.sub(r'(?<=\s)\d{1,2}\.(?=\s)', ' ', texto)

            linhas = texto.split('\n')
            linhas_filtradas = []
            for linha in linhas:
                linha_strip = linha.strip()
                if padrao_ruido_linha.search(linha_strip):
                    continue
                linha_limpa = re.sub(r'\s{2,}', ' ', linha_strip).strip()
                if is_marketing_pdf and not re.search(r'[A-Za-zÁÉÍÓÚÂÊÔÃÕÇáéíóúâêôãõç]', linha_limpa):
                    continue
                if linha_limpa:
                    linhas_filtradas.append(linha_limpa)
                elif not linhas_filtradas or linhas_filtradas[-1] != "":
                    linhas_filtradas.append("")
            texto = "\n".join(linhas_filtradas)
            texto = re.sub(r'\n{3,}', '\n\n', texto)
            texto = re.sub(r'[ \t]+', ' ', texto)
            texto = texto.strip()
            return texto, None

    except Exception as e:
        return "", f"Erro ao ler o arquivo {tipo_arquivo}: {e}"

# ----------------- DETECÇÃO DE TÍTULOS (v34 - Corrigida) -----------------
def is_titulo_secao(linha):
    if not linha:
        return False
    ln = linha.strip()
    if len(ln) < 4:
        return False
    if len(ln.split('\n')) > 3: # Se tiver mais de 3 linhas juntas, não é um título
        return False
        
    ln_primeira_linha = ln.split('\n')[0] # Checa só a primeira linha
    
    if len(ln_primeira_linha.split()) > 20: # Um título não deve ser tão longo
        return False

    # Regra 1: Começa com número (Ex: "1. ... INDICADO?")
    if re.match(r'^\d+\s*[\.\-)]*\s+[A-ZÁÉÍÓÚÂÊÔÃÕÇ]', ln_primeira_linha):
        return True
    
    # Regra 2: É TUDO MAIÚSCULO (Ex: "APRESENTAÇÕES")
    if ln_primeira_linha.isupper():
        # [CORREÇÃO V34] - A exceção agora é se terminar com PONTO.
        # Isso filtra "TODO MEDICAMENTO..." mas permite títulos
        # que contenham a palavra "medicamento".
        if ln_primeira_linha.endswith('.'):
             return False
        return True # É maiúsculo e não termina com ponto.
        
    return False

# ----------------- CORREÇÃO DE QUEBRAS EM TÍTULOS (v41 - Corrigida) -----------------
# Esta função é ESSENCIAL para juntar os títulos do MKT
def corrigir_quebras_em_titulos(texto):
    if not texto:
        return texto
    linhas = texto.split("\n")
    linhas_corrigidas = []
    buffer = ""
    linhas_vazias_consecutivas = 0
    
    for linha in linhas:
        linha_strip = linha.strip()
        
        if not linha_strip: # É uma linha vazia
            linhas_vazias_consecutivas += 1
            # Se temos mais de 1 linha vazia, força o flush do buffer
            if linhas_vazias_consecutivas > 1 and buffer:
                linhas_corrigidas.append(buffer)
                buffer = ""
            # Se não há buffer, adiciona a linha vazia
            if not buffer:
                linhas_corrigidas.append("")
            continue
        
        # Reset do contador de linhas vazias
        linhas_vazias_consecutivas = 0
        
        is_potential_title = is_titulo_secao(linha_strip)
        
        if is_potential_title and len(linha_strip.split()) < 20: # Se for um título potencial
            if buffer:
                # Junta com a linha anterior usando espaço ao invés de \n
                buffer += " " + linha_strip
            else:
                buffer = linha_strip # Começa um novo título
        else: # É uma linha de conteúdo
            if buffer:
                linhas_corrigidas.append(buffer) # Salva o título anterior
                buffer = ""
            linhas_corrigidas.append(linha_strip) # Salva a linha de conteúdo
            
    if buffer: # Salva o último título
        linhas_corrigidas.append(buffer)
    
    # Limpa quebras de linha duplas mas mantém uma quebra entre seções
    resultado = "\n".join(linhas_corrigidas)
    return re.sub(r'\n{3,}', '\n\n', resultado)

# ----------------- CONFIGURAÇÃO DE SEÇÕES (v30 - Paciente Apenas) -----------------
def obter_secoes_por_tipo(tipo_bula):
    secoes = {
        "Paciente": [
            "APRESENTAÇÕES",
            "COMPOSIÇÃO",
            "1.PARA QUE ESTE MEDICAMENTO É INDICADO?",
            "2.COMO ESTE MEDICAMENTO FUNCIONA?",
            "3.QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?",
            "4.O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?",
            "5.ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?",
            "6.COMO DEVO USAR ESTE MEDICAMENTO?",
            "7.O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?",
            "8.QUAIS OS MALES QUE ESTE MEDICAMENTO PODE ME CAUSAR?",
            "9.O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?",
            "DIZERES LEGAIS"
        ]
        # "Profissional" key removida
    }
    # Retorna as seções do Paciente se tipo_bula="Paciente", ou lista vazia
    return secoes.get(tipo_bula, [])

def obter_aliases_secao():
    # v30 - Apenas Aliases de Paciente
    return {
        "PARA QUE ESTE MEDICAMENTO É INDICADO?": "1.PARA QUE ESTE MEDICAMENTO É INDICADO?",
        "COMO ESTE MEDICAMENTO FUNCIONA?": "2.COMO ESTE MEDICAMENTO FUNCIONA?",
        "QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?": "3.QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?",
        "O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?": "4.O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?",
        "ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?": "5.ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?",
        "COMO DEVO USAR ESTE MEDICAMENTO?": "6.COMO DEVO USAR ESTE MEDICAMENTO?",
        "O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?": "7.O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?",
        "QUAIS OS MALES QUE ESTE MEDICAMENTO PODE ME CAUSAR?": "8.QUAIS OS MALES QUE ESTE MEDICAMENTO PODE ME CAUSAR?",
        "O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?": "9.O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?",
    }

def obter_secoes_ignorar_comparacao():
    return ["APRESENTAÇÕES", "COMPOSIÇÃO", "DIZERES LEGAIS"]

def obter_secoes_ignorar_ortografia():
    return ["APRESENTAÇÕES", "COMPOSIÇÃO", "DIZERES LEGAIS"]

# ----------------- FUNÇÃO 'CORE' (v31 - Simplificada) -----------------
# Lógica simples que depende do 'corrigir_quebras_em_titulos'
def mapear_secoes(texto_completo, secoes_esperadas):
    mapa = []
    texto_normalizado = re.sub(r'\n{2,}', '\n', texto_completo or "")
    # As linhas agora vêm pré-juntadas por 'corrigir_quebras_em_titulos'
    linhas = texto_normalizado.split('\n') 
    aliases = obter_aliases_secao()

    # 1. Criar lookup de todos os títulos possíveis
    titulos_possiveis = {}
    for secao in secoes_esperadas:
        titulos_possiveis[secao] = secao
    for alias, canon in aliases.items():
        if canon in secoes_esperadas:
            titulos_possiveis[alias] = canon

    titulos_norm_lookup = {normalizar_titulo_para_comparacao(t): c for t, c in titulos_possiveis.items()}
    limiar_score = 85

    for idx, linha in enumerate(linhas):
        linha_strip = linha.strip()
        
        # 2. Checa se a linha (que pode ser multi-linha, ex: "TITULO\nPARTE 2") é um título
        if not linha_strip or not is_titulo_secao(linha_strip):
            continue
        
        # [Correção v32] A normalização agora trata o '\n'
        norm_linha = normalizar_titulo_para_comparacao(linha_strip)
        
        best_score = 0
        best_canonico = None
        for titulo_norm, canonico in titulos_norm_lookup.items():
            score = fuzz.token_set_ratio(titulo_norm, norm_linha)
            if score > best_score:
                best_score = score
                best_canonico = canonico
        
        if best_score < limiar_score:
             for titulo_norm, canonico in titulos_norm_lookup.items():
                if titulo_norm and titulo_norm in norm_linha:
                    best_score = 90
                    best_canonico = canonico
                    break

        # 3. Avalia o match
        if best_score >= limiar_score and best_canonico:
            num_lines = len(linha_strip.split('\n')) # Conta as linhas que foram "coladas"
            
            if not mapa or mapa[-1]['canonico'] != best_canonico:
                mapa.append({
                    'canonico': best_canonico,
                    'titulo_encontrado': linha_strip,
                    'linha_inicio': idx,
                    'score': best_score,
                    'num_linhas_titulo': num_lines
                })
    
    mapa.sort(key=lambda x: x['linha_inicio'])
    return mapa


# ----------------- OBTER DADOS DE SEÇÃO (v35 - Lógica v31 Restaurada) -----------------
def obter_dados_secao(secao_canonico, mapa_secoes, linhas_texto_split):
    idx_secao_atual = -1
    for i, secao_mapa in enumerate(mapa_secoes):
        if secao_mapa['canonico'] == secao_canonico:
            idx_secao_atual = i
            break
    if idx_secao_atual == -1:
        return False, None, ""
    secao_atual_info = mapa_secoes[idx_secao_atual]
    
    # O 'titulo_encontrado' é a linha "colada" (ex: "TITULO\nPARTE 2")
    titulo_encontrado = secao_atual_info['titulo_encontrado']
    
    # 'linha_inicio' é o índice (em linhas_texto_split) onde esse título colado está
    linha_inicio = secao_atual_info['linha_inicio']
    
    # O conteúdo começa na linha SEGUINTE do 'linhas_texto_split'
    linha_inicio_conteudo = linha_inicio + 1 
    
    linha_fim = len(linhas_texto_split)
    if (idx_secao_atual + 1) < len(mapa_secoes):
        # O fim é o início da próxima seção mapeada
        linha_fim = mapa_secoes[idx_secao_atual + 1]['linha_inicio']
    
    # Pega o conteúdo, ignorando o próprio título
    # (range(start, end) exclui 'end', então ele para exatamente antes da próxima seção)
    conteudo = [linhas_texto_split[idx] for idx in range(linha_inicio_conteudo, linha_fim)]
    
    conteudo_final_sem_titulo = "\n".join(conteudo).strip()
    
    if conteudo_final_sem_titulo:
        conteudo_final = f"{titulo_encontrado}\n\n{conteudo_final_sem_titulo}"
    else:
        conteudo_final = f"{titulo_encontrado}"
        
    return True, titulo_encontrado, conteudo_final

# ----------------- EXTRAI QUALIFIERS INICIAIS (RESTRITO) -----------------
def _extrair_linhas_qualificadoras_iniciais(texto, max_lines=4):
    if not texto:
        return [], texto
    linhas = texto.split('\n')
    qualifiers = []
    i = 0
    while i < min(len(linhas), max_lines):
        ln = linhas[i].strip()
        if not ln:
            i += 1
            continue
        ln_up = ln.upper()
        if 'USO NASAL' in ln_up and 'ADULTO' in ln_up:
            qualifiers.append(ln)
            i += 1
            continue
        if 'USO NASAL' in ln_up and i+1 < len(linhas) and 'ADULTO' in linhas[i+1].upper():
            qualifiers.append(ln)
            qualifiers.append(linhas[i+1].strip())
            i += 2
            continue
        break
    restante = '\n'.join(linhas[i:]).strip()
    return qualifiers, restante

# ----------------- REALOCAR QUALIFIERS (RESTRITO) -----------------
def realocar_qualifiers_inplace(conteudos, src_section='COMPOSIÇÃO', dst_section='APRESENTAÇÕES'):
    src = conteudos.get(src_section)
    dst = conteudos.get(dst_section)
    if not src or not dst:
        return
    if not src.get('conteudo_bel', "").strip():
        return
    qualifiers_bel, restante_bel = _extrair_linhas_qualificadoras_iniciais(src['conteudo_bel'], max_lines=4)
    if not qualifiers_bel:
        return
    if not dst.get('encontrou_bel', False):
        return
    qual_text = ' '.join(q for q in qualifiers_bel if q.strip())
    if not qual_text:
        return
    if re.search(r'\b(?:cont[eé]m|mg\b|ml\b|equivalente|q\.s\.p|qsp)\b', qual_text, flags=re.IGNORECASE):
        return
    if len(restante_bel.strip()) < 30:
        return
    dst_norm = normalizar_texto(dst.get('conteudo_bel', ""))
    if normalizar_texto(qual_text) in dst_norm:
        src['conteudo_bel'] = restante_bel
        return
    lines_dst = dst.get('conteudo_bel', "").split('\n')
    title_dst = lines_dst[0] if lines_dst and lines_dst[0].strip() else dst_section
    rest_dst = '\n'.join(lines_dst[1:]).strip() if len(lines_dst) > 1 else ""
    combined = f"{title_dst}\n\n{qual_text}\n\n{rest_dst}".strip()
    dst['conteudo_bel'] = combined
    src['conteudo_bel'] = restante_bel

# ----------------- VERIFICAÇÃO E COMPARAÇÃO -----------------
def verificar_secoes_e_conteudo(texto_ref, texto_belfar, tipo_bula):
    secoes_esperadas = obter_secoes_por_tipo(tipo_bula)
    secoes_faltantes = []
    diferencas_titulos = []
    relatorio_comparacao_completo = []
    similaridade_geral = []
    secoes_ignorar_upper = [s.upper() for s in obter_secoes_ignorar_comparacao()]

    # Importante: As linhas aqui já estão "coladas" pelo 'corrigir_quebras_em_titulos'
    linhas_ref = re.sub(r'\n{2,}', '\n', texto_ref or "").split('\n')
    linhas_belfar = re.sub(r'\n{2,}', '\n', texto_belfar or "").split('\n')

    mapa_ref = mapear_secoes(texto_ref or "", secoes_esperadas)
    mapa_belfar = mapear_secoes(texto_belfar or "", secoes_esperadas)

    conteudos = {}
    for sec in secoes_esperadas:
        encontrou_ref, titulo_ref, conteudo_ref = obter_dados_secao(sec, mapa_ref, linhas_ref)
        encontrou_bel, titulo_bel, conteudo_bel = obter_dados_secao(sec, mapa_belfar, linhas_belfar)
        conteudos[sec] = {
            'encontrou_ref': encontrou_ref,
            'titulo_ref': titulo_ref or "",
            'conteudo_ref': conteudo_ref or "",
            'encontrou_bel': encontrou_bel,
            'titulo_bel': titulo_bel or "",
            'conteudo_bel': conteudo_bel or ""
        }
        if not encontrou_bel:
            secoes_faltantes.append(sec)

    realocar_qualifiers_inplace(conteudos, src_section='COMPOSIÇÃO', dst_section='APRESENTAÇÕES')

    for sec in secoes_esperadas:
        item = conteudos[sec]
        encontrou_ref = item['encontrou_ref']
        encontrou_bel = item['encontrou_bel']
        conteudo_ref = item['conteudo_ref']
        conteudo_bel = item['conteudo_bel']
        titulo_ref = item.get('titulo_ref') or ""
        titulo_bel = item.get('titulo_bel') or ""

        # [CORREÇÃO v28] - Bloco desativado
        # if titulo_bel and titulo_ref and normalizar_titulo_para_comparacao(titulo_bel) != normalizar_titulo_para_comparacao(titulo_ref):
        #     estilo_titulo_inline = "font-family: 'Georgia', 'Times New Roman', serif; font-weight:700; color: #0b8a3e; font-size:15px; margin-bottom:8px;"
        #     titulo_html = titulo_bel.replace('\n', '<br>')
        #     marcado = f'<div style="{estilo_titulo_inline}"><mark style="background-color:#ffff99; padding:2px;">{titulo_html}</mark></div>'
        #     conteudo_bel = re.sub(re.escape(titulo_bel), marcado, conteudo_bel, count=1)

        if not encontrou_bel:
            relatorio_comparacao_completo.append({'secao': sec, 'status': 'faltante', 'conteudo_ref': conteudo_ref, 'conteudo_belfar': ""})
            continue

        if encontrou_ref and encontrou_bel:
            if sec.upper() in secoes_ignorar_upper:
                relatorio_comparacao_completo.append({'secao': sec, 'status': 'identica', 'conteudo_ref': conteudo_ref, 'conteudo_belfar': conteudo_bel})
                similaridade_geral.append(100)
            else:
                if normalizar_texto(conteudo_ref) != normalizar_texto(conteudo_bel):
                    relatorio_comparacao_completo.append({'secao': sec, 'status': 'diferente', 'conteudo_ref': conteudo_ref, 'conteudo_belfar': conteudo_bel})
                    similaridade_geral.append(0)
                else:
                    relatorio_comparacao_completo.append({'secao': sec, 'status': 'identica', 'conteudo_ref': conteudo_ref, 'conteudo_belfar': conteudo_bel})
                    similaridade_geral.append(100)

    titulos_ref_encontrados = {m['canonico']: m['titulo_encontrado'] for m in mapa_ref}
    titulos_belfar_encontrados = {m['canonico']: m['titulo_encontrado'] for m in mapa_belfar}
    for secao_canonico, titulo_ref in titulos_ref_encontrados.items():
        if secao_canonico in titulos_belfar_encontrados:
            titulo_bel = titulos_belfar_encontrados[secao_canonico]
            if normalizar_titulo_para_comparacao(titulo_ref) != normalizar_titulo_para_comparacao(titulo_bel):
                diferencas_titulos.append({'secao_esperada': secao_canonico, 'titulo_encontrado': titulo_bel})

    return secoes_faltantes, relatorio_comparacao_completo, similaridade_geral, diferencas_titulos

# ----------------- ORTOGRAFIA, MARCAÇÃO, DIFERENÇAS (mantidos) -----------------
def checar_ortografia_inteligente(texto_para_checar, texto_referencia, tipo_bula):
    if not nlp or not texto_para_checar:
        return []
    try:
        secoes_ignorar = obter_secoes_ignorar_ortografia()
        secoes_todas = obter_secoes_por_tipo(tipo_bula)
        texto_filtrado_para_checar = []
        mapa_secoes = mapear_secoes(texto_para_checar, secoes_todas)
        linhas_texto = re.sub(r'\n{2,}', '\n', texto_para_checar).split('\n')
        for secao_nome in secoes_todas:
            if secao_nome.upper() in [s.upper() for s in secoes_ignorar]:
                continue
            encontrou, _, conteudo = obter_dados_secao(secao_nome, mapa_secoes, linhas_texto)
            if encontrou and conteudo:
                texto_filtrado_para_checar.append(conteudo)
        texto_final_para_checar = "\n".join(texto_filtrado_para_checar)
        if not texto_final_para_checar:
            return []
        spell = SpellChecker(language='pt')
        palavras_a_ignorar = {"alair", "belfar", "peticionamento", "urotrobel", "contato", "iobeguane"}
        vocab_referencia = set(re.findall(r'\b[a-záéíóúâêôãõçü]+\b', texto_referencia.lower()))
        doc = nlp(texto_para_checar)
        entidades = {ent.text.lower() for ent in doc.ents}
        spell.word_frequency.load_words(vocab_referencia.union(entidades).union(palavras_a_ignorar))
        palavras = re.findall(r'\b[a-záéíóúâêôãõçü]+\b', texto_final_para_checar.lower())
        erros = spell.unknown(palavras)
        return list(sorted(set([e for e in erros if len(e) > 3])))[:20]
    except Exception:
        return []

def marcar_diferencas_palavra_por_palavra(texto_ref, texto_belfar, eh_referencia):
    texto_ref = texto_ref or ""
    texto_belfar = texto_belfar or ""
    def tokenizar(txt):
        return re.findall(r'\n|[A-Za-zÀ-ÖØ-öø-ÿ0-9_]+|[^\w\s]', txt, re.UNICODE)
    def norm(tok):
        if re.match(r'[A-Za-zÀ-ÖØ-öø-ÿ0-9_]+$', tok):
            return normalizar_texto(tok)
        return tok
    ref_tokens = tokenizar(texto_ref)
    bel_tokens = tokenizar(texto_belfar)
    ref_norm = [norm(t) for t in ref_tokens]
    bel_norm = [norm(t) for t in bel_tokens]
    matcher = difflib.SequenceMatcher(None, ref_norm, bel_norm, autojunk=False)
    indices = set()
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != 'equal':
            indices.update(range(i1, i2) if eh_referencia else range(j1, j2))
    tokens = ref_tokens if eh_referencia else bel_tokens
    marcado = []
    for idx, tok in enumerate(tokens):
        if idx in indices and tok.strip() != '':
            marcado.append(f"<mark style='background-color: #ffff99; padding: 2px;'>{tok}</mark>")
        else:
            marcado.append(tok)
    resultado = ""
    for i, tok in enumerate(marcado):
        if i == 0:
            resultado += tok
            continue
        tok_anterior_raw = re.sub(r'^<mark[^>]*>|</mark>$', '', marcado[i-1])
        raw_tok = re.sub(r'^<mark[^>]*>|</mark>$', '', tok)
        if not re.match(r'^[.,;:!?)\\]$', raw_tok) and raw_tok != '\n' and tok_anterior_raw != '\n' and not re.match(r'^[(\\[]$', tok_anterior_raw):
            resultado += " " + tok
        else:
            resultado += tok
    resultado = re.sub(r"(</mark>)\s+(<mark[^>]*>)", " ", resultado)
    return resultado

# ----------------- FORMATAÇÃO PARA LEITURA (v42 - Layout Melhorado) -----------------
def formatar_html_para_leitura(html_content, aplicar_numeracao=False):
    if html_content is None:
        return ""
    
    # --- LÓGICA DE TÍTULO RESTRITA (v30 - Paciente Apenas) ---
    try:
        secoes_validas = obter_secoes_por_tipo("Paciente") 
        aliases = obter_aliases_secao()
        
        titulos_validos_norm = set(normalizar_titulo_para_comparacao(s) for s in secoes_validas)
        titulos_validos_norm.update(normalizar_titulo_para_comparacao(a) for a in aliases.keys())
    except NameError:
        titulos_validos_norm = set()
    # --- FIM DA LÓGICA DE TÍTULO ---

    cor_titulo = "#0b5686" if aplicar_numeracao else "#0b8a3e"
    # [v42] Melhorado: título com mais destaque visual e espaçamento
    estilo_titulo_inline = (
        f"font-family: 'Georgia', 'Times New Roman', serif; "
        f"font-weight: 700; "
        f"color: {cor_titulo}; "
        f"font-size: 16px; "
        f"margin-top: 16px; "
        f"margin-bottom: 12px; "
        f"line-height: 1.4; "
        f"display: block;"
    )

    linhas = html_content.split('\n')
    linhas_formatadas = []
    linha_anterior_foi_titulo = False

    for linha in linhas:
        linha_strip = linha.strip()
        
        if not linha_strip:
            # [v42] Melhor controle de espaçamento após títulos
            if not linha_anterior_foi_titulo:
                linhas_formatadas.append("") 
            linha_anterior_foi_titulo = False
            continue

        linha_strip_sem_tags = re.sub(r'</?(?:mark|strong)[^>]*>', '', linha_strip, flags=re.IGNORECASE).strip()
        
        is_title = False
        if linha_strip_sem_tags:
            linha_norm_sem_tags = normalizar_titulo_para_comparacao(linha_strip_sem_tags)
            if linha_norm_sem_tags in titulos_validos_norm:
                is_title = True

        if is_title:
            titulo_formatado = linha_strip
            
            # [v42] Melhorado: remove TODAS as quebras de linha internas e normaliza espaços
            titulo_formatado = titulo_formatado.replace("\n", " ")
            titulo_formatado = titulo_formatado.replace("<br>", " ")
            titulo_formatado = titulo_formatado.replace("<br/>", " ")
            titulo_formatado = re.sub(r'\s+', ' ', titulo_formatado)  # Normaliza múltiplos espaços

            if not aplicar_numeracao:
                # Remove numeração preservando tags <mark>
                titulo_formatado = re.sub(r'^\s*(<mark[^>]*>)?\s*\d+\s*[\.\-)]*\s*(</mark>)?', r'\1\2', titulo_formatado, flags=re.IGNORECASE)
                titulo_formatado = re.sub(r'^\s*\d+\s*[\.\-)]*\s*', '', titulo_formatado)
            
            # [v42] Adiciona margem superior para separar do conteúdo anterior
            if linhas_formatadas and linhas_formatadas[-1]:
                linhas_formatadas.append("")  # Espaço antes do título
            
            linhas_formatadas.append(f'<div style="{estilo_titulo_inline}">{titulo_formatado.strip()}</div>')
            linha_anterior_foi_titulo = True
        
        else:
            linhas_formatadas.append(linha_strip)
            linha_anterior_foi_titulo = False
    
    # [v42] Melhorado: junta com <br> e faz limpeza mais eficiente
    html_content_final = "<br>".join(linhas_formatadas)
    
    # Remove múltiplas quebras consecutivas (mantém no máximo 2)
    html_content_final = re.sub(r'(<br\s*/?>\s*){3,}', '<br><br>', html_content_final)
    # Remove quebras no início
    html_content_final = re.sub(r'^\s*(<br\s*/?>\s*)+', '', html_content_final)
    # Remove quebras no final
    html_content_final = re.sub(r'(<br\s*/?>\s*)+$', '', html_content_final)
    
    return html_content_final

# ----------------- MARCAÇÃO HTML (FUNÇÃO AUSENTE) -----------------
def marcar_divergencias_html(texto_original, secoes_problema_lista_dicionarios, erros_ortograficos, tipo_bula, eh_referencia):
    """
    Recria o texto HTML completo, marcando seções divergentes e erros ortográficos.
    Usa a função 'marcar_diferencas_palavra_por_palavra' para as seções com 'status' == 'diferente'.
    """
    if not texto_original:
        return ""

    secoes_esperadas = obter_secoes_por_tipo(tipo_bula)
    secoes_ignorar_comp = [s.upper() for s in obter_secoes_ignorar_comparacao()]
    
    # Mapear o texto que estamos processando (Ref ou Belfar)
    # v40 - Usando o texto PRÉ-PROCESSADO por 'corrigir_quebras_em_titulos'
    linhas_texto = re.sub(r'\n{2,}', '\n', texto_original).split('\n')
    mapa_secoes_texto = mapear_secoes(texto_original, secoes_esperadas)

    # Criar um lookup rápido para os problemas
    problemas_lookup = {item['secao']: item for item in secoes_problema_lista_dicionarios}

    texto_html_final_secoes = {}
    
    # 1. Processar todas as seções encontradas no texto original
    for i, secao_info in enumerate(mapa_secoes_texto):
        secao_canonico = secao_info['canonico']
        
        # Obter o conteúdo completo desta seção (com título)
        # v40 - Usando o 'obter_dados_secao' corrigido
        encontrou, titulo, conteudo_secao_atual = obter_dados_secao(secao_canonico, mapa_secoes_texto, linhas_texto)
        
        if not encontrou:
            continue

        item_problema = problemas_lookup.get(secao_canonico)

        # Se a seção é problemática (diferente) E NÃO é ignorada
        if item_problema and item_problema['status'] == 'diferente' and secao_canonico.upper() not in secoes_ignorar_comp:
            texto_ref_problema = item_problema.get('conteudo_ref', '')
            texto_bel_problema = item_problema.get('conteudo_belfar', '')
            
            # Usamos a função já existente para marcar as palavras
            html_marcado = marcar_diferencas_palavra_por_palavra(
                texto_ref_problema, 
                texto_bel_problema, 
                eh_referencia=eh_referencia
            )
            texto_html_final_secoes[secao_canonico] = html_marcado
        
        # Se não é problemática, ou é ignorada, apenas adiciona o conteúdo original
        # (O conteúdo 'belfar' já pode conter o título destacado, se for diferente)
        else:
            if eh_referencia:
                 texto_html_final_secoes[secao_canonico] = item_problema.get('conteudo_ref', conteudo_secao_atual) if item_problema else conteudo_secao_atual
            else:
                 texto_html_final_secoes[secao_canonico] = item_problema.get('conteudo_belfar', conteudo_secao_atual) if item_problema else conteudo_secao_atual


    # 2. Reconstruir o texto na ordem que foi encontrado no arquivo
    html_bruto = "\n\n".join(texto_html_final_secoes.get(m['canonico'], '') for m in mapa_secoes_texto if m['canonico'] in texto_html_final_secoes)

    # 3. Aplicar marcação de erros ortográficos (apenas no texto Belfar)
    if not eh_referencia and erros_ortograficos:
        import html
        # Regex para encontrar as palavras de erro, mas evitando estar dentro de tags HTML
        try:
            palavras_regex = r'\b(' + '|'.join(re.escape(e) for e in erros_ortograficos) + r')\b'
            
            partes = re.split(r'(<[^>]+>)', html_bruto) # Divide por tags HTML
            resultado_final = []
            for parte in partes:
                if parte.startswith('<'):
                    resultado_final.append(parte) # É uma tag, mantém
                else:
                    # Não é uma tag, aplicar regex de ortografia
                    parte_escapada = html.unescape(parte)
                    parte_marcada = re.sub(
                        palavras_regex, 
                        lambda m: f"<mark style='background-color: #ffcccb; padding: 2px; border: 1px dashed red;'>{m.group(1)}</mark>", 
                        parte_escapada, 
                        flags=re.IGNORECASE
                    )
                    resultado_final.append(parte_marcada)
            html_bruto = "".join(resultado_final)
        except re.error:
            # Evita que um regex mal formado (ex: palavra com caractere especial) quebre a app
            pass 

    return html_bruto

# ----------------- GERAÇÃO DE RELATÓRIO E UI (mantido layout original) -----------------
def gerar_relatorio_final(texto_ref, texto_belfar, nome_ref, nome_belfar, tipo_bula):
    st.header("Relatório de Auditoria Inteligente")
    secoes_faltantes, relatorio_comparacao_completo, similaridades, diferencas_titulos = verificar_secoes_e_conteudo(texto_ref, texto_belfar, tipo_bula)
    erros_ortograficos = checar_ortografia_inteligente(texto_belfar, texto_ref, tipo_bula)
    score_similaridade_conteudo = sum(similaridades) / len(similaridades) if similaridades else 100.0

    st.subheader("Dashboard de Veredito")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Conformidade de Conteúdo", f"{score_similaridade_conteudo:.0f}%")
    col2.metric("Erros Ortográficos", len(erros_ortograficos))
    rx = r"(aprovad[ao]\s+pela\s+anvisa\s+em|data\s+de\s+aprova\w+\s+na\s+anvisa:)\s*([\d]{1,2}/[\d]{1,2}/[\d]{2,4})"
    match_ref = re.search(rx, (texto_ref or "").lower())
    match_bel = re.search(rx, (texto_belfar or "").lower())
    data_ref = match_ref.group(2) if match_ref else "Não encontrada"
    data_bel = match_bel.group(2) if match_bel else "Não encontrada"
    col3.metric("Data ANVISA (Ref)", data_ref)
    col4.metric("Seções Faltantes", f"{len(secoes_faltantes)}")

    st.divider()
    st.subheader("Análise Detalhada Seção por Seção")

    expander_caixa_style = (
        "height: 350px; overflow-y: auto; border: 2px solid #d0d0d0; border-radius: 6px; "
        "padding: 16px; background-color: #ffffff; font-size: 14px; line-height: 1.8; "
        "font-family: 'Georgia', 'Times New Roman', serif; text-align: left;"
        "overflow-wrap: break-word; word-break: break-word;"
    )

    if secoes_faltantes:
        st.error(f"🚨 **Seções faltantes na bula Arquivo MKT ({len(secoes_faltantes)})**:\n" + "\n".join([f"  - {s}" for s in secoes_faltantes]))
    else:
        st.success("✅ Todas as seções obrigatórias estão presentes")

    st.markdown("---")

    for item in relatorio_comparacao_completo:
        secao_nome = item['secao']
        status = item['status']
        conteudo_ref_str = item.get('conteudo_ref') or ""
        conteudo_belfar_str = item.get('conteudo_belfar') or ""
        is_ignored_section = secao_nome.upper() in [s.upper() for s in obter_secoes_ignorar_comparacao()]

        if status == 'diferente':
            with st.expander(f"📄 {secao_nome} - ❌ CONTEÚDO DIVERGENTE"):
                c1, c2 = st.columns(2)
                with c1:
                    st.markdown("**Arquivo ANVISA:**")
                    # [CORREÇÃO v31] - Simplificado, sem tipo_bula
                    html_ref = formatar_html_para_leitura(conteudo_ref_str, aplicar_numeracao=True)
                    st.markdown(f"<div style='{expander_caixa_style}'>{html_ref}</div>", unsafe_allow_html=True)
                with c2:
                    st.markdown("**Arquivo MKT:**")
                    # [CORREÇÃO v31] - Simplificado, sem tipo_bula
                    html_bel = formatar_html_para_leitura(conteudo_belfar_str, aplicar_numeracao=False)
                    st.markdown(f"<div style='{expander_caixa_style}'>{html_bel}</div>", unsafe_allow_html=True)
        else:
            expander_title = f"📄 {secao_nome} - ✅ CONTEÚDO IDÊNTICO"
            if is_ignored_section:
                expander_title = f"📄 {secao_nome} - ✔️ NÃO CONFERIDO (Regra de Negócio)"
            with st.expander(expander_title):
                c1, c2 = st.columns(2)
                with c1:
                    st.markdown("**Arquivo ANVISA:**")
                    # [CORREÇÃO v31] - Simplificado, sem tipo_bula
                    html_ref = formatar_html_para_leitura(conteudo_ref_str, aplicar_numeracao=True)
                    st.markdown(f"<div style='{expander_caixa_style}'>{html_ref}</div>", unsafe_allow_html=True)
                with c2:
                    st.markdown("**Arquivo MKT:**")
                    # [CORREÇÃO v31] - Simplificado, sem tipo_bula
                    html_bel = formatar_html_para_leitura(conteudo_belfar_str, aplicar_numeracao=False)
                    st.markdown(f"<div style='{expander_caixa_style}'>{html_bel}</div>", unsafe_allow_html=True)

    if erros_ortograficos:
        st.info(f"📝 **Possíveis erros ortográficos ({len(erros_ortograficos)} palavras):**\n" + ", ".join(erros_ortograficos))

    st.divider()
    st.subheader("🎨 Visualização Lado a Lado com Destaques")

    html_ref_bruto = marcar_divergencias_html(texto_original=texto_ref or "", secoes_problema_lista_dicionarios=relatorio_comparacao_completo, erros_ortograficos=[], tipo_bula=tipo_bula, eh_referencia=True)
    html_belfar_marcado_bruto = marcar_divergencias_html(texto_original=texto_belfar or "", secoes_problema_lista_dicionarios=relatorio_comparacao_completo, erros_ortograficos=erros_ortograficos, tipo_bula=tipo_bula, eh_referencia=False)

    # [CORREÇÃO v31] - Simplificado, sem tipo_bula
    html_ref_marcado = formatar_html_para_leitura(html_ref_bruto, aplicar_numeracao=True)
    html_belfar_marcado = formatar_html_para_leitura(html_belfar_marcado_bruto, aplicar_numeracao=False)

    caixa_style = (
        "max-height: 700px; overflow-y: auto; border: 1px solid #e0e0e0; border-radius: 8px; padding: 20px 24px; "
        "background-color: #ffffff; font-size: 15px; line-height: 1.7; box-shadow: 0 4px 12px rgba(0,0,0,0.08);"
        "text-align: left; overflow-wrap: break-word; word-break: break-word;"
    )
    title_style = ("font-size: 1.25rem; font-weight: 600; margin-bottom: 8px; color: #31333F;")

    col1, col2 = st.columns(2, gap="large")
    with col1:
        st.markdown(f"<div style='{title_style}'>{nome_ref}</div>", unsafe_allow_html=True)
        st.markdown(f"<div style='{caixa_style}'>{html_ref_marcado}</div>", unsafe_allow_html=True)
    with col2:
        st.markdown(f"<div style='{title_style}'>{nome_belfar}</div>", unsafe_allow_html=True)
        st.markdown(f"<div style='{caixa_style}'>{html_belfar_marcado}</div>", unsafe_allow_html=True)

# ----------------- INTERFACE PRINCIPAL (UI) (v31 - Paciente Apenas) -----------------
st.set_page_config(layout="wide", page_title="Auditoria de Bulas", page_icon="🔬")
st.title("🔬 Inteligência Artificial para Auditoria de Bulas")
st.markdown("Envie o arquivo da ANVISA (pdf/docx) e o PDF Marketing (MKT).")

st.divider()
# [CORREÇÃO v30] - Removido st.radio, hardcoded para "Paciente"
tipo_bula_selecionado = "Paciente" 

col1, col2 = st.columns(2)
with col1:
    st.subheader("📄 Arquivo ANVISA")
    pdf_ref = st.file_uploader("Envie o arquivo da Anvisa (.docx ou .pdf)", type=["docx", "pdf"], key="ref")
with col2:
    st.subheader("📄 Arquivo MKT")
    pdf_belfar = st.file_uploader("Envie o PDF do Marketing", type="pdf", key="belfar")

if st.button("🔍 Iniciar Auditoria Completa", use_container_width=True, type="primary"):
    if not (pdf_ref and pdf_belfar):
        st.warning("⚠️ Por favor, envie ambos os arquivos para iniciar a auditoria.")
    else:
        with st.spinner("🔄 Processando e analisando as bulas..."):
            tipo_arquivo_ref = 'docx' if pdf_ref.name.lower().endswith('.docx') else 'pdf'
            
            # [v40] Texto RAW é extraído
            texto_ref_raw, erro_ref = extrair_texto(pdf_ref, tipo_arquivo_ref, is_marketing_pdf=False)
            texto_belfar_raw, erro_belfar = extrair_texto(pdf_belfar, 'pdf', is_marketing_pdf=True)
            
            texto_ref_processado = texto_ref_raw
            texto_belfar_processado = texto_belfar_raw

            if not erro_ref:
                # [CORREÇÃO v40] RE-ATIVADO para pré-processar
                texto_ref_processado = corrigir_quebras_em_titulos(texto_ref_raw)
                texto_ref_processado = truncar_apos_anvisa(texto_ref_processado)
            if not erro_belfar:
                # [CORREÇÃO v40] RE-ATIVADO para pré-processar
                texto_belfar_processado = corrigir_quebras_em_titulos(texto_belfar_raw)
                texto_belfar_processado = truncar_apos_anvisa(texto_belfar_processado)

            if erro_ref or erro_belfar:
                st.error(f"Erro ao processar arquivos: {erro_ref or erro_belfar}")
            elif not texto_ref_processado or not texto_belfar_processado:
                st.error("Erro: Um dos arquivos está vazio ou não pôde ser lido corretamente.")
            else:
                # [v40] Passa o texto PRÉ-PROCESSADO para o verificador
                gerar_relatorio_final(texto_ref_processado, texto_belfar_processado, pdf_ref.name, pdf_belfar.name, tipo_bula_selecionado)

st.divider()
st.caption("Sistema de Auditoria de Bulas v40 | Mapeamento Pré-processado (Corrigido).")
