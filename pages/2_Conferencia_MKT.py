# pages/2_Conferencia_MKT.py
#
# Versão v26.26 (Títulos Enumerados + Filtro Aprimorado)
# 1. (v26.26) Títulos da ANVISA agora enumerados como no MKT
# 2. (v26.26) Filtro aprimorado para "New Roman" e "BUL_CLORIDRATO_DE_NA 190"
# 3. (v26.24) Filtro de ruído "hiper-específico" para "BUL_..." e "New Roman..."
# 4. (v26.23) Lógica de extração correta (filtra ANTES de splitar).
# 5. (v26.23) Layout robusto (formatar_html_para_leitura) que acha títulos "grudados".

# --- IMPORTS ---
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

# ----------------- MODELO NLP -----------------
@st.cache_resource
def carregar_modelo_spacy():
    """Carrega o modelo de linguagem SpaCy de forma otimizada."""
    try:
        return spacy.load("pt_core_news_lg")
    except OSError:
        st.error("Modelo 'pt_core_news_lg' não encontrado. Execute: python -m spacy download pt_core_news_lg")
        return None

nlp = carregar_modelo_spacy()

# ----------------- EXTRAÇÃO (v26.26 - Filtro Aprimorado) -----------------
def extrair_texto(arquivo, tipo_arquivo, is_marketing_pdf=False):
    """
    Extrai texto de arquivos.
    Usa sort=True DENTRO de cada coluna,
    para fluir o texto e deixar o layout "bonitinho".
    """
    if arquivo is None:
        return "", f"Arquivo {tipo_arquivo} não enviado."
    try:
        arquivo.seek(0)
        texto = ""
        full_text_list = []
        
        if tipo_arquivo == 'pdf':
            with fitz.open(stream=arquivo.read(), filetype="pdf") as doc:
                if is_marketing_pdf:
                    # Lógica de 2 colunas SÓ para o PDF do Marketing
                    for page in doc:
                        rect = page.rect
                        clip_esquerda = fitz.Rect(0, 0, rect.width / 2, rect.height)
                        clip_direita = fitz.Rect(rect.width / 2, 0, rect.width, rect.height)
                        
                        texto_esquerda = page.get_text("text", clip=clip_esquerda, sort=True)
                        texto_direita = page.get_text("text", clip=clip_direita, sort=True)
                        
                        full_text_list.append(texto_esquerda)
                        full_text_list.append(texto_direita)
                else:
                    # Lógica de 1 coluna (padrão) para o PDF da Anvisa
                    for page in doc:
                        full_text_list.append(page.get_text("text", sort=True))
            
            texto = "\n\n".join(full_text_list)
        
        elif tipo_arquivo == 'docx':
            doc = docx.Document(arquivo)
            texto = "\n".join([p.text for p in doc.paragraphs])
        
        if texto:
            caracteres_invisiveis = ['\u00AD', '\u200B', '\u200C', '\u200D', '\uFEFF']
            for char in caracteres_invisiveis:
                texto = texto.replace(char, '')
            texto = texto.replace('\r\n', '\n').replace('\r', '\n')
            texto = texto.replace('\u00A0', ' ')
            
            # --- FILTRO DE RUÍDO (v26.26 - APRIMORADO) ---
            
            # Padrão 1: Remove LINHAS INTEIRAS que são ruído
            padrao_ruido_linha = re.compile(
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
                r'|AZOLINA: Tim mm'  # <-- MUDANÇA AQUI
            , re.IGNORECASE)

            # Padrão 2: Remove FRAGMENTOS de ruído (v26.26 - APRIMORADO)
            padrao_ruido_inline = re.compile(
                # (v26.26) Regra MAIS ABRANGENTE para "BUL_CLORIDRATO_DE_NA" seguido de números
                r'BUL_CLORIDRATO_DE_NA[\s\S]{0,20}?\d+'  
                
                # (v26.26) Regra MAIS ABRANGENTE para "New Roman" com variações
                r'|New[\s\S]{0,10}?Roman[\s\S]{0,50}?(?:mm|\d+)'
                
                # Outras regras existentes:
                r'|AFAZOLINA_BUL\d+V\d+.*?'  
                r'|BUL_CLORIDRATO_DE_NAFAZOLINA_BUL\d+V\d+'
                r'|AMBROXOL_BUL\d+V\d+'
                r'|es New Roman.*?'  
                r'|rpo \d+.*?'  
                r'|olL: Times New Roman.*?'
            , re.IGNORECASE)
            
            # ***** LÓGICA CORRETA (v26.23) *****
            # 1. Aplicar o filtro INLINE no texto COMPLETO (antes de splitar)
            texto = padrao_ruido_inline.sub(' ', texto)
            
            # 2. AGORA, splitar o texto limpo em linhas
            linhas = texto.split('\n')
            
            # 3. Aplicar o filtro de LINHA INTEIRA
            linhas_filtradas = []
            for linha in linhas:
                linha_strip = linha.strip()
                
                if padrao_ruido_linha.search(linha_strip):
                    continue

                linha_limpa = re.sub(r'\s{2,}', ' ', linha_strip).strip()
                
                if len(linha_limpa) > 1 or (len(linha_limpa) == 1 and linha_limpa.isdigit()):
                    linhas_filtradas.append(linha_limpa)
                elif linha_limpa.isupper() and len(linha_limpa) > 0:
                    linhas_filtradas.append(linha_limpa)
            
            # 4. Juntar o texto final
            texto = "\n".join(linhas_filtradas)
            
            texto = re.sub(r'\n{3,}', '\n\n', texto)  
            texto = re.sub(r'[ \t]+', ' ', texto)
            texto = texto.strip()

        return texto, None
    except Exception as e:
        return "", f"Erro ao ler o arquivo {tipo_arquivo}: {e}"
def truncar_apos_anvisa(texto):
    if not isinstance(texto, str):
        return texto
    
    regex_anvisa = r"((?:aprovad[ao]\s+pela\s+anvisa\s+em|data\s+de\s+aprova\w+\s+na\s+anvisa:)\s*([\d]{1,2}\s*/\s*[\d]{1,2}\s*/\s*[\d]{2,4}))"
    
    match = re.search(regex_anvisa, texto, re.IGNORECASE)
    
    if not match:
        return texto

    cut_off_position = match.end(1) 
    pos_match = re.search(r'^\s*\.', texto[cut_off_position:], re.IGNORECASE)
    
    if pos_match: 
        cut_off_position += pos_match.end()

    return texto[:cut_off_position]

# ----------------- CONFIGURAÇÃO DE SEÇÕES (v26.26 - TÍTULOS ENUMERADOS) -----------------
def obter_secoes_por_tipo(tipo_bula):
    
    secoes = {
        "Paciente": [
            "APRESENTAÇÕES", 
            "COMPOSIÇÃO", 
            "1.PARA QUE ESTE MEDICAMENTO É INDICADO?",
            "2.COMO ESTE MEDICAMENTO FUNCIONA?",
            "3.QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?",
            "4.O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?",
            "5. ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?",
            "6. COMO DEVO USAR ESTE MEDICAMENTO?",
            "7.O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?",
            "8. QUAIS OS MALES QUE ESTE MEDICAMENTO PODE ME CAUSAR?",
            "9. O QUE FAZER SE ALGUÉM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?",
            "DIZERES LEGAIS"
        ],
        "Profissional": [
            "APRESENTAÇÕES", 
            "COMPOSIÇÃO", 
            "1. INDICAÇÕES", 
            "2. RESULTADOS DE EFICÁCIA",
            "3. CARACTERÍSTICAS FARMACOLÓGICAS", 
            "4. CONTRAINDICAÇÕES",
            "5. ADVERTÊNCIAS E PRECAUÇÕES", 
            "6. INTERAÇÕES MEDICAMENTOSAS",
            "7. CUIDADOS DE ARMAZENAMENTO DO MEDICAMENTO", 
            "8. POSOLOGIA E MODO DE USAR",
            "9. REAÇÕES ADVERSAS", 
            "10. SUPERDOSE", 
            "DIZERES LEGAIS"
        ]
    }
    
    return secoes.get(tipo_bula, [])

def obter_aliases_secao():
    return {
        # Aliases Paciente (com e sem número)
        "PARA QUE ESTE MEDICAMENTO É INDICADO?": "1.PARA QUE ESTE MEDICAMENTO É INDICADO?",
        "COMO ESTE MEDICAMENTO FUNCIONA?": "2.COMO ESTE MEDICAMENTO FUNCIONA?",
        "QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?": "3.QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?",
        "O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?": "4.O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?",
        "ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?": "5. ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?",
        "COMO DEVO USAR ESTE MEDICAMENTO?": "6. COMO DEVO USAR ESTE MEDICAMENTO?",
        "O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?": "7.O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?",
        "QUAIS OS MALES QUE ESTE MEDICAMENTO PODE ME CAUSAR?": "8. QUAIS OS MALES QUE ESTE MEDICAMENTO PODE ME CAUSAR?",
        
        # Variações da Seção 9
        "O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?": "9. O QUE FAZER SE ALGUÉM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?",
        "O QUE FAZER SE ALGUÉM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?": "9. O QUE FAZER SE ALGUÉM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?",

        # Aliases Profissional (com e sem número)
        "INDICAÇÕES": "1. INDICAÇÕES",
        "RESULTADOS DE EFICÁCIA": "2. RESULTADOS DE EFICÁCIA",
        "CARACTERÍSTICAS FARMACOLÓGICAS": "3. CARACTERÍSTICAS FARMACOLÓGICAS",
        "CONTRAINDICAÇÕES": "4. CONTRAINDICAÇÕES",
        "ADVERTÊNCIAS E PRECAUÇÕES": "5. ADVERTÊNCIAS E PRECAUÇÕES",
        "INTERAÇÕES MEDICAMENTOSAS": "6. INTERAÇÕES MEDICAMENTOSAS",
        "CUIDADOS DE ARMAZENAMENTO DO MEDICAMENTO": "7. CUIDADOS DE ARMAZENAMENTO DO MEDICAMENTO",
        "POSOLOGIA E MODO DE USAR": "8. POSOLOGIA E MODO DE USAR",
        "REAÇÕES ADVERSAS": "9. REAÇÕES ADVERSAS",
        "SUPERDOSE": "10. SUPERDOSE"
    }

def obter_secoes_ignorar_comparacao():
    return ["APRESENTAÇÕES", "COMPOSIÇÃO", "DIZERES LEGAIS"]

def obter_secoes_ignorar_ortografia():
    return ["APRESENTAÇÕES", "COMPOSIÇÃO", "DIZERES LEGAIS"]

# ----------------- NORMALIZAÇÃO -----------------
def normalizar_texto(texto):
    if not isinstance(texto, str):
        return ""
    texto = ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')
    texto = re.sub(r'[^\w\s]', '', texto)
    texto = ' '.join(texto.split())
    return texto.lower()

def normalizar_titulo_para_comparacao(texto):
    texto_norm = normalizar_texto(texto)
    texto_norm = re.sub(r'^\d+\s*[\.\-)]*\s*', '', texto_norm).strip()
    return texto_norm

# ----------------- CORREÇÃO DE TÍTULOS BELFAR -----------------
def corrigir_quebras_em_titulos(texto):
    """
    Une linhas maiúsculas consecutivas (títulos quebrados em várias linhas)
    para corrigir erros de reconhecimento no PDF da BELFAR.
    """
    linhas = texto.split("\n")
    linhas_corrigidas = []
    buffer = ""

    for linha in linhas:
        linha_strip = linha.strip()
        if not linha_strip:
            continue

        if linha_strip.isupper() and len(linha_strip) < 60:
            if buffer:
                buffer += " " + linha_strip
            else:
                buffer = linha_strip
        else:
            if buffer:
                linhas_corrigidas.append(buffer)
                buffer = ""
            linhas_corrigidas.append(linha_strip)

    if buffer:
        linhas_corrigidas.append(buffer)

    return "\n".join(linhas_corrigidas)

# ----------------- ARQUITETURA DE MAPEAMENTO DE SEÇÕES (v23.0) -----------------
def is_titulo_secao(linha):
    """Retorna True se a linha for um possível título de seção puro."""
    linha = linha.strip()
    
    if len(linha) < 4:  
        return False
    
    if re.match(r'^\d+\.\s+[A-Z]', linha):
        return True
        
    if len(linha.split()) > 20:  
        return False
        
    if linha.endswith('.') or linha.endswith(':'):
        return False
        
    if re.search(r'>\s*<', linha):
        return False
        
    if len(linha) > 100:
        return False
        
    if linha.isupper():
        return True
        
    return False
            
def mapear_secoes(texto_completo, secoes_esperadas):
    """Mapeador simplificado (v23) para funcionar com o texto "bonito" (fluído)"""
    mapa = []
    linhas = texto_completo.split('\n')
    aliases = obter_aliases_secao()
    
    titulos_possiveis = {}
    for secao in secoes_esperadas:
        titulos_possiveis[secao] = secao
    for alias, canonico in aliases.items():
        if canonico in secoes_esperadas:
            titulos_possiveis[alias] = canonico
            
    titulos_norm_lookup = {normalizar_titulo_para_comparacao(t): c for t, c in titulos_possiveis.items()}

    limiar_score = 85

    for idx, linha_limpa in enumerate(linhas):
        linha_limpa = linha_limpa.strip()
        
        if not is_titulo_secao(linha_limpa):
            continue
        
        norm_linha_1 = normalizar_titulo_para_comparacao(linha_limpa)
        best_score = 0
        best_canonico = None

        for titulo_norm, canonico in titulos_norm_lookup.items():
            score = fuzz.token_set_ratio(titulo_norm, norm_linha_1)
            if score > best_score:
                best_score = score
                best_canonico = canonico
        
        if best_score >= limiar_score:
            if not mapa or mapa[-1]['canonico'] != best_canonico:
                mapa.append({
                    'canonico': best_canonico,
                    'titulo_encontrado': linha_limpa,
                    'linha_inicio': idx,
                    'score': best_score,
                    'num_linhas_titulo': 1
                })
            
    mapa.sort(key=lambda x: x['linha_inicio'])
    return mapa


def obter_dados_secao(secao_canonico, mapa_secoes, linhas_texto):
    """
    Extrai o conteúdo de uma seção com base no mapa pré-processado.
    """
    
    idx_secao_atual = -1
    for i, secao_mapa in enumerate(mapa_secoes):
        if secao_mapa['canonico'] == secao_canonico:
            idx_secao_atual = i
            break
    
    if idx_secao_atual == -1:
        return False, None, ""

    secao_atual_info = mapa_secoes[idx_secao_atual]
    titulo_encontrado = secao_atual_info['titulo_encontrado']
    linha_inicio = secao_atual_info['linha_inicio']
    num_linhas_titulo = secao_atual_info.get('num_linhas_titulo', 1)
    
    linha_inicio_conteudo = linha_inicio + num_linhas_titulo

    linha_fim = len(linhas_texto) 
    
    if (idx_secao_atual + 1) < len(mapa_secoes):
        secao_seguinte_info = mapa_secoes[idx_secao_atual + 1]
        linha_fim = secao_seguinte_info['linha_inicio']

    conteudo = [linhas_texto[idx] for idx in range(linha_inicio_conteudo, linha_fim)]
    conteudo_final = "\n".join(conteudo).strip()
    
    return True, titulo_encontrado, conteudo_final

# ----------------- COMPARAÇÃO DE CONTEÚDO -----------------
def verificar_secoes_e_conteudo(texto_ref, texto_belfar, tipo_bula):
    secoes_esperadas = obter_secoes_por_tipo(tipo_bula)
    secoes_faltantes = []
    diferencas_titulos = []
    
    relatorio_comparacao_completo = []
    similaridade_geral = []
    
    secoes_ignorar_upper = [s.upper() for s in obter_secoes_ignorar_comparacao()] 

    linhas_ref = texto_ref.split('\n')
    linhas_belfar = texto_belfar.split('\n')
    mapa_ref = mapear_secoes(texto_ref, secoes_esperadas)
    mapa_belfar = mapear_secoes(texto_belfar, secoes_esperadas)

    for secao in secoes_esperadas:
        encontrou_ref, _, conteudo_ref = obter_dados_secao(secao, mapa_ref, linhas_ref)
        encontrou_belfar, titulo_belfar, conteudo_belfar = obter_dados_secao(secao, mapa_belfar, linhas_belfar)
        
        if not encontrou_belfar:
            secoes_faltantes.append(secao)
            relatorio_comparacao_completo.append({
                'secao': secao, 
                'status': 'faltante', 
                'conteudo_ref': conteudo_ref, 
                'conteudo_belfar': ""
            })
            continue

        if encontrou_ref and encontrou_belfar:
            if secao.upper() in secoes_ignorar_upper: 
                relatorio_comparacao_completo.append({
                    'secao': secao, 
                    'status': 'identica', 
                    'conteudo_ref': conteudo_ref, 
                    'conteudo_belfar': conteudo_belfar
                })
                similaridade_geral.append(100)
                continue

            if normalizar_texto(conteudo_ref) != normalizar_texto(conteudo_belfar):
                relatorio_comparacao_completo.append({
                    'secao': secao, 
                    'status': 'diferente', 
                    'conteudo_ref': conteudo_ref, 
                    'conteudo_belfar': conteudo_belfar
                })
                similaridade_geral.append(0)
            else:
                relatorio_comparacao_completo.append({
                    'secao': secao, 
                    'status': 'identica', 
                    'conteudo_ref': conteudo_ref, 
                    'conteudo_belfar': conteudo_belfar
                })
                similaridade_geral.append(100)

    titulos_ref_encontrados = {m['canonico']: m['titulo_encontrado'] for m in mapa_ref}
    titulos_belfar_encontrados = {m['canonico']: m['titulo_encontrado'] for m in mapa_belfar}

    for secao_canonico, titulo_ref in titulos_ref_encontrados.items():
        if secao_canonico in titulos_belfar_encontrados:
            titulo_belfar = titulos_belfar_encontrados[secao_canonico]
            if normalizar_titulo_para_comparacao(titulo_ref) != normalizar_titulo_para_comparacao(titulo_belfar):
                diferencas_titulos.append({'secao_esperada': secao_canonico, 'titulo_encontrado': titulo_belfar})

    return secoes_faltantes, relatorio_comparacao_completo, similaridade_geral, diferencas_titulos


# ----------------- ORTOGRAFIA -----------------
def checar_ortografia_inteligente(texto_para_checar, texto_referencia, tipo_bula):
    if not nlp or not texto_para_checar:
        return []

    try:
        secoes_ignorar = obter_secoes_ignorar_ortografia()
        secoes_todas = obter_secoes_por_tipo(tipo_bula)
        texto_filtrado_para_checar = []

        mapa_secoes = mapear_secoes(texto_para_checar, secoes_todas)
        linhas_texto = texto_para_checar.split('\n')

        for secao_nome in secoes_todas:
            if secao_nome.upper() in [s.upper() for s in secoes_ignorar]:
                continue
            
            encontrou, _, conteudo = obter_dados_secao(secao_nome, mapa_secoes, linhas_texto)
            if encontrou and conteudo:
                texto_filtrado_para_checar.append(conteudo)

        texto_final_para_checar = '\n'.join(texto_filtrado_para_checar)
        
        if not texto_final_para_checar:
            return []

        spell = SpellChecker(language='pt')
        palavras_a_ignorar = {"alair", "belfar", "peticionamento", "urotrobel", "contato"}
        vocab_referencia = set(re.findall(r'\b[a-záéíóúâêôãõçü]+\b', texto_referencia.lower()))
        doc = nlp(texto_para_checar)
        entidades = {ent.text.lower() for ent in doc.ents}

        spell.word_frequency.load_words(
            vocab_referencia.union(entidades).union(palavras_a_ignorar)
        )

        palavras = re.findall(r'\b[a-záéíóúâêôãõçü]+\b', texto_final_para_checar.lower())
        erros = spell.unknown(palavras)
        return list(sorted(set([e for e in erros if len(e) > 3])))[:20]

    except Exception:
        return []


# ----------------- DIFERENÇAS PALAVRA A PALAVRA -----------------
def marcar_diferencas_palavra_por_palavra(texto_ref, texto_belfar, eh_referencia):
    if texto_ref is None:
        texto_ref = ""
    if texto_belfar is None:
        texto_belfar = ""

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

        if not re.match(r'^[.,;:!?)\\]$', raw_tok) and \
           raw_tok != '\n' and \
           tok_anterior_raw != '\n' and \
           not re.match(r'^[(\\[]$', tok_anterior_raw):
            resultado += " " + tok
        else:
            resultado += tok
            
    resultado = re.sub(r"(</mark>)\s+(<mark[^>]*>)", " ", resultado)
    return resultado


# ----------------- MARCAÇÃO POR SEÇÃO COM ÍNDICES -----------------
def marcar_divergencias_html(texto_original, secoes_problema_lista_dicionarios, erros_ortograficos, tipo_bula, eh_referencia=False):
    texto_trabalho = texto_original
    
    # 1. Marca Amarelo (Divergências)
    if secoes_problema_lista_dicionarios:
        for diff in secoes_problema_lista_dicionarios:
            if diff['status'] != 'diferente':
                continue
                
            conteudo_ref = diff['conteudo_ref']
            conteudo_belfar = diff['conteudo_belfar']
            conteudo_a_marcar = conteudo_ref if eh_referencia else conteudo_belfar
            
            if conteudo_a_marcar and conteudo_a_marcar in texto_trabalho:
                conteudo_marcado = marcar_diferencas_palavra_por_palavra(
                    conteudo_ref, conteudo_belfar, eh_referencia
                )
                texto_trabalho = texto_trabalho.replace(conteudo_a_marcar, conteudo_marcado, 1)

    # 2. Marca Rosa (Ortografia)
    if erros_ortograficos and not eh_referencia:
        for erro in erros_ortograficos:
            pattern = r'\b(' + re.escape(erro) + r')\b(?![^<]*?>)'
            texto_trabalho = re.sub(
                pattern,
                r"<mark style='background-color: #FFDDC1; padding: 2px;'>\1</mark>",
                texto_trabalho,
                flags=re.IGNORECASE
            )
            
    # 3. Marca Azul (ANVISA) POR ÚLTIMO
    regex_anvisa = r"((?:aprovad[ao]\s+pela\s+anvisa\s+em|data\s+de\s+aprova\w+\s+na\s+anvisa:)\s*([\d]{1,2}\s*/\s*[\d]{1,2}\s*/\s*[\d]{2,4}))"
    
    def remove_marks_da_data(match):
        frase_anvisa = match.group(1)
        frase_limpa = re.sub(r'<mark.*?>|</mark>', '', frase_anvisa)
        return f"<mark style='background-color: #cce5ff; padding: 2px; font-weight: 500;'>{frase_limpa}</mark>"

    texto_trabalho = re.sub(
        regex_anvisa,
        remove_marks_da_data,
        texto_trabalho,
        count=1,
        flags=re.IGNORECASE
    )
            
    return texto_trabalho


# ----------------- RELATÓRIO -----------------
def gerar_relatorio_final(texto_ref, texto_belfar, nome_ref, nome_belfar, tipo_bula):
    st.header("Relatório de Auditoria Inteligente")
    
    regex_anvisa = r"((?:aprovad[ao]\s+pela\s+anvisa\s+em|data\s+de\s+aprova\w+\s+na\s+anvisa:)\s*([\d]{1,2}\s*/\s*[\d]{1,2}\s*/\s*[\d]{2,4}))"
    
    match_ref = re.search(regex_anvisa, texto_ref.lower()) if texto_ref else None
    match_belfar = re.search(regex_anvisa, texto_belfar.lower()) if texto_belfar else None
    
    data_ref = match_ref.group(2).strip() if match_ref else "Não encontrada"
    data_belfar = match_belfar.group(2).strip() if match_belfar else "Não encontrada"

    texto_ref_safe = texto_ref or ""
    texto_belfar_safe = texto_belfar or ""

    secoes_faltantes, relatorio_comparacao_completo, similaridades, diferencas_titulos = verificar_secoes_e_conteudo(texto_ref_safe, texto_belfar_safe, tipo_bula)
    
    erros_ortograficos = checar_ortografia_inteligente(texto_belfar_safe, texto_ref_safe, tipo_bula)
    score_similaridade_conteudo = sum(similaridades) / len(similaridades) if similaridades else 100.0

    st.subheader("Dashboard de Veredito")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Conformidade de Conteúdo", f"{score_similaridade_conteudo:.0f}%")
    col2.metric("Erros Ortográficos", len(erros_ortograficos))
    col3.metric("Data ANVISA (Arquivo ANVISA)", data_ref)
    col4.metric("Seções Faltantes", f"{len(secoes_faltantes)}")

    st.divider()
    st.subheader("Detalhes dos Problemas Encontrados")
    
    st.info(f"ℹ️ **Datas de Aprovação ANVISA:**\n  - Arquivo ANVISA: {data_ref}\n  - Arquivo MKT: {data_belfar}")
    
def formatar_html_para_leitura(html_content):
    """
    Formata o texto "fluído" (sort=True) para um HTML "bonito".
    (v26.23) - Regras de regex quebram em partes menores e usam [\s\S]
    para formatar títulos, mesmo se houver ruído ou quebras de linha.
    """
    if html_content is None:
        return ""
    
    html_content = re.sub(r'\n{2,}', '[[PARAGRAPH]]', html_content)
    
    titulos_lista = [
        "APRESENTAÇÕES", "COMPOSIÇÃO", "DIZERES LEGAIS",
        "IDENTIFICAÇÃO DO MEDICAMENTO", "INFORMAÇÕES AO PACIENTE",
        
        # --- MUDANÇAS ABAIXO (para bater com os títulos exatos) ---
        
        # Seção 9 (permite ruído como 'mm')
        r"(9\.\s*O QUE FAZER SE ALGUÉM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA[\s\S]*?DESTE MEDICAMENTO\?)",
        r"(O QUE FAZER SE ALGUÉM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA[\s\S]*?DESTE MEDICAMENTO\?)",
        
        # Seção 8 (com espaço)
        r"(8\.\s*QUAIS OS MALES QUE ESTE MEDICAMENTO PODE ME CAUSAR\?)",
        r"(QUAIS OS MALES QUE ESTE MEDICAMENTO PODE ME CAUSAR\?)",

        # Seção 7 (sem espaço)
        r"(7\.O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO\?)",
        r"(O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO\?)",

        # Seção 6 (com espaço)
        r"(6\.\s*COMO DEVO USAR ESTE MEDICAMENTO\?)",
        r"(COMO DEVO USAR ESTE MEDICAMENTO\?)",

        # Seção 5 (com espaço)
        r"(5\.\s*ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO\?)",
        r"(ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO\?)",

        # Seção 4 (sem espaço)
        r"(4\.O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO\?)",
        r"(O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO\?)",

        # Seção 3 (sem espaço)
        r"(3\.QUANDO NÃO DEVO USAR ESTE MEDICAMENTO\?)",
        r"(QUANDO NÃO DEVO USAR ESTE MEDICAMENTO\?)",
        
        # Seção 2 (sem espaço)
        r"(2\.COMO ESTE MEDICAMENTO FUNCIONA\?)",
        r"(COMO ESTE MEDICAMENTO FUNCIONA\?)",

        # Seção 1 (sem espaço)
        r"(1\.PARA QUE ESTE MEDICAMENTO É INDICADO\?)",
        r"(PARA QUE ESTE MEDICAMENTO É INDICADO\?)"
    ]
    
    regex_titulos = r'(' + '|'.join(titulos_lista) + r')'

    html_content = re.sub(
        regex_titulos,
        r'[[PARAGRAPH]]<strong>\1</strong>', 
        html_content,
        flags=re.IGNORECASE
    )

    html_content = re.sub(
        r'(\n)(\s*[-–•*])',
        r'[[LIST_ITEM]]\2',
        html_content
    )

    html_content = html_content.replace('\n', ' ')

    html_content = html_content.replace('[[PARAGRAPH]]', '<br><br>')
    html_content = html_content.replace('[[LIST_ITEM]]', '<br>')
    
    html_content = re.sub(r'(<br\s*/?>\s*){3,}', '<br><br>', html_content)
    html_content = html_content.replace('<br><br> <br><br>', '<br><br>')
    
    return html_content

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
    st.subheader("Análise Detalhada Seção por Seção")

    for item in relatorio_comparacao_completo:
        secao_nome = item['secao']
        status = item['status']
        conteudo_ref_str = item.get('conteudo_ref') or ""
        conteudo_belfar_str = item.get('conteudo_belfar') or ""
        
        is_ignored_section = secao_nome.upper() in [s.upper() for s in obter_secoes_ignorar_comparacao()]

        if status == 'diferente':
            with st.expander(f"📄 {secao_nome} - ❌ CONTEÚDO DIVERGENTE"):
                html_ref_bruto_expander = marcar_diferencas_palavra_por_palavra(
                    conteudo_ref_str, conteudo_belfar_str, eh_referencia=True
                )
                html_belfar_bruto_expander = marcar_diferencas_palavra_por_palavra(
                    conteudo_ref_str, conteudo_belfar_str, eh_referencia=False
                )
                
                expander_html_ref = formatar_html_para_leitura(html_ref_bruto_expander)
                expander_html_belfar = formatar_html_para_leitura(html_belfar_bruto_expander)

                c1, c2 = st.columns(2)
                with c1:
                    st.markdown("**Arquivo ANVISA:**")
                    st.markdown(f"<div style='{expander_caixa_style}'>{expander_html_ref}</div>", unsafe_allow_html=True)
                with c2:
                    st.markdown("**Arquivo MKT:**")
                    st.markdown(f"<div style='{expander_caixa_style}'>{expander_html_belfar}</div>", unsafe_allow_html=True)
        
        elif status == 'identica':
            expander_title = f"📄 {secao_nome} - ✅ CONTEÚDO IDÊNTICO"
            if is_ignored_section:
                expander_title = f"📄 {secao_nome} - ✔️ NÃO CONFERIDO (Regra de Negócio)"

            with st.expander(expander_title):
                expander_html_ref = formatar_html_para_leitura(conteudo_ref_str)
                expander_html_belfar = formatar_html_para_leitura(conteudo_belfar_str)

                c1, c2 = st.columns(2)
                with c1:
                    st.markdown("**Arquivo ANVISA:**")
                    st.markdown(f"<div style='{expander_caixa_style}'>{expander_html_ref}</div>", unsafe_allow_html=True)
                with c2:
                    st.markdown("**Arquivo MKT:**")
                    st.markdown(f"<div style='{expander_caixa_style}'>{expander_html_belfar}</div>", unsafe_allow_html=True)

    if erros_ortograficos:
        st.info(f"📝 **Possíveis erros ortográficos ({len(erros_ortograficos)} palavras):**\n" + ", ".join(erros_ortograficos))

    diferencas_conteudo_count = sum(1 for item in relatorio_comparacao_completo if item['status'] == 'diferente')

    if not any([secoes_faltantes, diferencas_conteudo_count > 0, diferencas_titulos]) and len(erros_ortograficos) < 5:
        st.success("🎉 **Bula aprovada!** Nenhum problema crítico encontrado.")

    st.divider()
    st.subheader("Visualização Lado a Lado com Destaques")

    legend_style = (
        "font-size: 14px; "
        "background-color: #f0f2f6; "
        "padding: 10px 15px; "
        "border-radius: 8px; "
        "margin-bottom: 15px;"
    )
    
    st.markdown(
        f"<div style='{legend_style}'>"
        "<strong>Legenda:</strong> "
        "<mark style='background-color: #ffff99; padding: 2px; margin: 0 2px;'>Amarelo</mark> = Divergências | "
        "<mark style='background-color: #FFDDC1; padding: 2px; margin: 0 2px;'>Rosa</mark> = Erros ortográficos | "
        "<mark style='background-color: #cce5ff; padding: 2px; margin: 0 2px;'>Azul</mark> = Data ANVISA"
        "</div>",
        unsafe_allow_html=True
    )

    html_ref_bruto = marcar_divergencias_html(texto_original=texto_ref_safe, secoes_problema_lista_dicionarios=relatorio_comparacao_completo, erros_ortograficos=[], tipo_bula=tipo_bula, eh_referencia=True)
    html_belfar_marcado_bruto = marcar_divergencias_html(texto_original=texto_belfar_safe, secoes_problema_lista_dicionarios=relatorio_comparacao_completo, erros_ortograficos=erros_ortograficos, tipo_bula=tipo_bula, eh_referencia=False)

    html_ref_marcado = formatar_html_para_leitura(html_ref_bruto)
    html_belfar_marcado = formatar_html_para_leitura(html_belfar_marcado_bruto)


    caixa_style = (
        "max-height: 700px; "
        "overflow-y: auto; "
        "border: 1px solid #e0e0e0; "
        "border-radius: 8px; "
        "padding: 20px 24px; "
        "background-color: #ffffff; "
        "font-size: 15px; "
        "line-height: 1.7; "
        "box-shadow: 0 4px 12px rgba(0,0,0,0.08); "
        "text-align: left; "
        "overflow-wrap: break-word; "
        "word-break: break-word; "
    )
    
    title_style = (
        "font-size: 1.25rem; "
        "font-weight: 600; "
        "margin-bottom: 8px; "
        "color: #31333F;"
    )
    
    col1, col2 = st.columns(2, gap="large")
    with col1:
        st.markdown(f"<div style='{title_style}'>{nome_ref}</div>", unsafe_allow_html=True)
        st.markdown(f"<div style='{caixa_style}'>{html_ref_marcado}</div>", unsafe_allow_html=True)
    with col2:
        st.markdown(f"<div style='{title_style}'>{nome_belfar}</div>", unsafe_allow_html=True)
        st.markdown(f"<div style='{caixa_style}'>{html_belfar_marcado}</div>", unsafe_allow_html=True)
    

# ----------------- INTERFACE -----------------
st.title("🔬 Inteligência Artificial para Auditoria de Bulas")
st.markdown("Sistema avançado de comparação literal e validação de bulas farmacêuticas")
st.divider()

st.header("📋 Configuração da Auditoria")
tipo_bula_selecionado = st.radio("Tipo de Bula:", ("Paciente"), horizontal=True)
col1, col2 = st.columns(2)
with col1:
    st.subheader("📄 Arquivo ANVISA")
    pdf_ref = st.file_uploader("Envie o arquivo da Anvisa (.docx ou .pdf)", type=["docx", "pdf"], key="ref")
with col2:
    st.subheader("📄 Arquivo MKT")
    pdf_belfar = st.file_uploader("Envie o PDF do Marketing", type="pdf", key="belfar")

if st.button("🔍 Iniciar Auditoria Completa", use_container_width=True, type="primary"):
    if pdf_ref and pdf_belfar:
        with st.spinner("🔄 Processando e analisando as bulas..."):
            
            tipo_arquivo_ref = 'docx' if pdf_ref.name.lower().endswith('.docx') else 'pdf'
            
            texto_ref, erro_ref = extrair_texto(pdf_ref, tipo_arquivo_ref, is_marketing_pdf=False)
            
            if not erro_ref:
                texto_ref = corrigir_quebras_em_titulos(texto_ref) 
                texto_ref = truncar_apos_anvisa(texto_ref)
            
            texto_belfar, erro_belfar = extrair_texto(pdf_belfar, 'pdf', is_marketing_pdf=True)
            
            if not erro_belfar:
                texto_belfar = corrigir_quebras_em_titulos(texto_belfar)
                texto_belfar = truncar_apos_anvisa(texto_belfar)

            if erro_ref or erro_belfar:
                st.error(f"Erro ao processar arquivos: {erro_ref or erro_belfar}") 
            elif not texto_ref or not texto_belfar:
                 st.error("Erro: Um dos arquivos está vazio ou não pôde ser lido corretamente.")
            else:
                gerar_relatorio_final(texto_ref, texto_belfar, "Arquivo ANVISA", "Arquivo MKT", tipo_bula_selecionado)
    else:
        st.warning("⚠️ Por favor, envie ambos os arquivos para iniciar a auditoria.")

st.divider()
st.caption("Sistema de Auditoria de Bulas v26.26 | Títulos Enumerados + Filtro Aprimorado")
