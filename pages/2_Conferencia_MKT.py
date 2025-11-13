# pages/2_Conferencia_MKT.py
#
# Versão v26.58 (Correção Definitiva: Lógica de Extração)
# Ajustes: refinamento da realocação de qualificadores (USO NASAL / USO ADULTO / EMBALAGENS)
# e prevenção de duplicações no destino. Títulos continuam sendo injetados dentro da seção.
# - Tornada a realocação mais conservadora e segura
# - Se APRESENTAÇÕES não existir no MKT, criaremos título+qualifiers apenas quando for seguro
# - Evita mover linhas que claramente parecem fórmula/composição

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

# ----------------- FORMATAÇÃO HTML (mantida) -----------------
def formatar_html_para_leitura(html_content, aplicar_numeracao=False):
    if html_content is None:
        return ""
    cor_titulo = "#0b5686" if aplicar_numeracao else "#0b8a3e"
    estilo_titulo_inline = f"font-family: 'Georgia', 'Times New Roman', serif; font-weight:700; color: {cor_titulo}; font-size:15px; margin-bottom:8px;"
    if not aplicar_numeracao:
        html_content = re.sub(r'(?:[\n\r]+)\s*\d+\.\s*(?:[\n\r]+)', '\n\n', html_content, flags=re.IGNORECASE)
        html_content = re.sub(r'^\s*\d+\.\s*(?:[\n\r]+)', '', html_content, flags=re.IGNORECASE)
        html_content = re.sub(r'(?:[\n\r]+)\s*\d+\.\s*$', '', html_content, flags=re.IGNORECASE)
    html_content = re.sub(r'\n{2,}', '[[PARAGRAPH]]', html_content)
    titulos_lista = [
        "APRESENTAÇÕES", "APRESENTACOES", "COMPOSIÇÃO", "COMPOSICAO", "DIZERES LEGAIS", "INFORMAÇÕES AO PACIENTE", "INFORMACOES AO PACIENTE",
        "IDENTIFICAÇÃO DO MEDICAMENTO", "INFORMAÇÕES AO PACIENTE",
        r"(9\.?\s*O\s+QUE\s+FAZER\s+SE\s+ALGU[EÉ]M\s+USAR\s+UMA\s+QUANTIDADE\s+MAIOR\s+DO\s+QUE\s+A\s+INDICADA[\s\S]{0,10}?DESTE\s+MEDICAMENTO\??)",
        r"(O\s+QUE\s+FAZER\s+SE\s+ALGU[EÉ]M\s+USAR\s+UMA\s+QUANTIDADE\s+MAIOR\s+DO\s+QUE\s+A\s+INDICADA[\s\S]{0,10}?DESTE\s+MEDICAMENTO\??)",
        r"(8\.?\s*QUAIS\s+OS\s+MALES\s+QUE\s+ESTE\s+MEDICAMENTO\s+PODE\s+ME\s+CAUSAR\??)",
        r"(QUAIS\s+OS\s+MALES\s+QUE\s+ESTE\s+MEDICAMENTO\s+PODE\s+ME\s+CAUSAR\??)",
        r"(7\.?\s*O\s+QUE\s+DEVO\s+FAZER\s+QUANDO\s+EU\s+ME\s+ESQUECER\s+DE\s+USAR\s+ESTE\s+MEDICAMENTO\??)",
        r"(O\s+QUE\s+DEVO\s+FAZER\s+QUANDO\s+EU\s+ME\s+ESQUECER\s+DE\s+USAR\s+ESTE\s+MEDICAMENTO\??)",
        r"(6\.?\s*COMO\s+DEVO\s+USAR\s+ESTE\s+MEDICamento\??)",
        r"(COMO\s+DEVO\s+USAR\s+ESTE\s+MEDICAMENTO\??)",
        r"(5\.?\s*ONDE,?\s+COMO\s+E\s+POR\s+QUANTO\s+TEMPO\s+POSSO\s+GUARDAR\s+ESTE\s+MEDICAMENTO\??)",
        r"(ONDE,?\s+COMO\s+E\s+POR\s+QUANTO\s+TEMPO\s+POSSO\s+GUARDAR\s+ESTE\s+MEDICAMENTO\??)",
        r"(4\.?\s*O\s+QUE\s+DEVO\s+SABER\s+ANTES\s+DE\s+USAR\s+ESTE\s+MEDICAMENTO\??)",
        r"(O\s+QUE\s+DEVO\s+SABER\s+ANTES\s+DE\s+USAR\s+ESTE\s+MEDICAMENTO\??)",
        r"(3\.?\s*QUANDO\s+N[AÃ]O\s+DEVO\s+USAR\s+ESTE\s+MEDICAMENTO\??)",
        r"(QUANDO\s+N[AÃ]O\s+DEVO\s+USAR\s+ESTE\s+MEDICAMENTO\??)",
        r"(2\.?\s*COMO\s+ESTE\s+MEDICAMENTO\s+FUNCIONA\??)",
        r"(COMO\s+ESTE\s+MEDICAMENTO\s+FUNCIONA\??)",
        r"(1\.?\s*PARA\s+QUE\s+ESTE\s+MEDICAMENTO\s+[EÉ]\s+INDICADO\??)",
        r"(PARA\s+QUE\s+ESTE\s+MEDICAMENTO\s+[EÉ]\s+INDICADO\??)"
    ]
    def limpar_e_numerar_titulo(match):
        titulo = match.group(0)
        titulo_limpo = re.sub(r'</?(?:mark|strong)[^>]*>', '', titulo, flags=re.IGNORECASE)
        titulo_limpo = re.sub(r'\s+', ' ', titulo_limpo).strip()
        titulo_sem_numero = re.sub(r'^\d+\.\s*', '', titulo_limpo)
        titulo_upper = titulo_limpo.upper()
        numero_prefix = ""
        if 'PARA QUE' in titulo_upper and 'INDICADO' in titulo_upper:
            numero_prefix = "1. "
        elif 'COMO ESTE MEDICAMENTO FUNCIONA' in titulo_upper:
            numero_prefix = "2. "
        elif 'QUANDO NÃO DEVO' in titulo_upper or 'QUANDO NAO DEVO' in titulo_upper:
            numero_prefix = "3. "
        elif 'O QUE DEVO SABER ANTES' in titulo_upper:
            numero_prefix = "4. "
        elif 'ONDE' in titulo_upper and 'GUARDAR' in titulo_upper:
            numero_prefix = "5. "
        elif 'COMO DEVO USAR' in titulo_upper:
            numero_prefix = "6. "
        elif 'ESQUECER' in titulo_upper:
            numero_prefix = "7. "
        elif 'QUAIS OS MALES' in titulo_upper:
            numero_prefix = "8. "
        elif 'QUANTIDADE MAIOR' in titulo_upper:
            numero_prefix = "9. "
        if any(k in titulo_upper for k in ['APRESENTAÇÕES', 'APRESENTACOES', 'COMPOSIÇÃO', 'COMPOSICAO', 'DIZERES LEGAIS', 'INFORMAÇÕES AO PACIENTE']):
            numero_prefix = ""
        estilo_titulo_inline = f"font-family: 'Georgia', 'Times New Roman', serif; font-weight:700; color: {'#0b5686' if aplicar_numeracao else '#0b8a3e'}; font-size:15px; margin-bottom:8px;"
        return f'[[PARAGRAPH]]<div style="{estilo_titulo_inline}">{numero_prefix}{titulo_sem_numero}</div>'
    for titulo_pattern in titulos_lista:
        html_content = re.sub(titulo_pattern, limpar_e_numerar_titulo, html_content, flags=re.IGNORECASE)
    html_content = re.sub(r'(\n)(\s*[-–•*])', r'[[LIST_ITEM]]\2', html_content)
    html_content = html_content.replace('\n', ' ')
    html_content = html_content.replace('[[PARAGRAPH]]', '<br><br>')
    html_content = html_content.replace('[[LIST_ITEM]]', '<br>')
    html_content = re.sub(r'(<br\s*/?>\s*){3,}', '<br><br>', html_content)
    html_content = html_content.replace('<br><br> <br><br>', '<br><br>')
    html_content = re.sub(r'(<br\s*/?>\s*){3,}', '<br><br>', html_content)
    html_content = re.sub(r'\s{2,}', ' ', html_content)
    return html_content

# ----------------- MARCAÇÃO DE DIVERGÊNCIAS (mantida) -----------------
def marcar_divergencias_html(texto_original, secoes_problema_lista_dicionarios, erros_ortograficos, tipo_bula, eh_referencia=False):
    texto_trabalho = texto_original
    if secoes_problema_lista_dicionarios:
        for diff in secoes_problema_lista_dicionarios:
            if diff['status'] != 'diferente':
                continue
            conteudo_ref = diff['conteudo_ref']
            conteudo_belfar = diff['conteudo_belfar']
            conteudo_a_marcar = conteudo_ref if eh_referencia else conteudo_belfar
            if conteudo_a_marcar and conteudo_a_marcar in texto_trabalho:
                conteudo_marcado = marcar_diferencas_palavra_por_palavra(conteudo_ref, conteudo_belfar, eh_referencia)
                texto_trabalho = texto_trabalho.replace(conteudo_a_marcar, conteudo_marcado, 1)
    if erros_ortograficos and not eh_referencia:
        for erro in erros_ortograficos:
            pattern = r'\b(' + re.escape(erro) + r')\b(?![^<]*?>)'
            texto_trabalho = re.sub(pattern, r"<mark style='background-color: #FFDDC1; padding: 2px;'>\1</mark>", texto_trabalho, flags=re.IGNORECASE)
    regex_anvisa = r"((?:aprovad[ao]\s+pela\s+anvisa\s+em|data\s+de\s+aprova\w+\s+na\s+anvisa:)\s*([\d]{1,2}\s*/\s*[\d]{1,2}\s*/\s*[\d]{2,4}))"
    def remove_marks_da_data(match):
        frase_anvisa = match.group(1)
        frase_limpa = re.sub(r'<mark.*?>|</mark>', '', frase_anvisa)
        return f"<mark style='background-color: #cce5ff; padding: 2px; font-weight: 500;'>{frase_limpa}</mark>"
    texto_trabalho = re.sub(regex_anvisa, remove_marks_da_data, texto_trabalho, count=1, flags=re.IGNORECASE)
    return texto_trabalho

# ----------------- MODELO NLP -----------------
@st.cache_resource
def carregar_modelo_spacy():
    try:
        return spacy.load("pt_core_news_lg")
    except OSError:
        st.error("Modelo 'pt_core_news_lg' não encontrado. Execute: python -m spacy download pt_core_news_lg")
        return None
nlp = carregar_modelo_spacy()

# ----------------- EXTRAÇÃO (mantida) -----------------
def extrair_texto(arquivo, tipo_arquivo, is_marketing_pdf=False):
    if arquivo is None:
        return "", f"Erro ao ler o arquivo {tipo_arquivo}: arquivo não enviado."
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
            caracteres_invisiveis = ['\u00AD', '\u200B', '\u200C', '\u200D', '\uFEFF']
            for char in caracteres_invisiveis:
                texto = texto.replace(char, '')
            texto = texto.replace('\r\n', '\n').replace('\r', '\n')
            texto = texto.replace('\u00A0', ' ')
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
            texto = re.sub(r'__KEEPBUL_(BUL_CLORIDRATO_DE_NAFAZOLINA)_(\d{2,4})__', lambda m: f"{m.group(1).replace('_', ' ')} {m.group(2)}", texto, flags=re.IGNORECASE)
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

# ----------------- FUNÇÕES AUXILIARES e MAPEAMENTO (mantidas) -----------------
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

# Substitua/cole estas funções no seu pages/2_Conferencia_MKT.py
# (apenas as funções presentes aqui precisam ser aplicadas; o resto do arquivo fica igual)

def obter_secoes_por_tipo(tipo_bula):
    secoes = {
        "Paciente": [
            "APRESENTAÇÕES",
            "APRESENTACOES",
            "APRESENTAÇÃO",
            "APRESENTACAO",
            "COMPOSIÇÃO",
            "COMPOSICAO",
            "INFORMAÇÕES AO PACIENTE",
            "INFORMACOES AO PACIENTE",
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
        ],
        "Profissional": [
            "APRESENTAÇÕES",
            "APRESENTACOES",
            "APRESENTAÇÃO",
            "APRESENTACAO",
            "COMPOSIÇÃO",
            "COMPOSICAO",
            "INFORMAÇÕES AO PACIENTE",
            "INFORMACOES AO PACIENTE",
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
        "PARA QUE ESTE MEDICAMENTO É INDICADO?": "1.PARA QUE ESTE MEDICAMENTO É INDICADO?",
        "COMO ESTE MEDICAMENTO FUNCIONA?": "2.COMO ESTE MEDICAMENTO FUNCIONA?",
        "QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?": "3.QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?",
        "O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?": "4.O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?",
        "ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?": "5.ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?",
        "COMO DEVO USAR ESTE MEDICAMENTO?": "6.COMO DEVO USAR ESTE MEDICAMENTO?",
        "O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?": "7.O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?",
        "QUAIS OS MALES QUE ESTE MEDICAMENTO PODE ME CAUSAR?": "8.QUAIS OS MALES QUE ESTE MEDICAMENTO PODE ME CAUSAR?",
        "O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?": "9.O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?",
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

def mapear_secoes(texto_completo, secoes_esperadas):
    """
    Versão ajustada: tenta captar variantes (singular/plural/sem acento) e, se não
    encontra um título por fuzzy, faz uma verificação local (próximas linhas) para
    detectar títulos que possam ter sido quebrados pela extração.
    """
    mapa = []
    texto_normalizado = re.sub(r'\n{2,}', '\n', texto_completo)
    linhas = texto_normalizado.split('\n')
    aliases = obter_aliases_secao()

    titulos_possiveis = {}
    for secao in secoes_esperadas:
        titulos_possiveis[secao] = secao
    for alias, canonico in aliases.items():
        if canonico in secoes_esperadas:
            titulos_possiveis[alias] = canonico

    titulos_norm_lookup = {normalizar_titulo_para_comparacao(t): c for t, c in titulos_possiveis.items()}
    limiar_score = 82  # ligeiramente mais permissivo

    for idx, linha_raw in enumerate(linhas):
        linha_limpa = linha_raw.strip()
        if not linha_limpa:
            continue
        if not is_titulo_secao(linha_limpa):
            continue
        norm_linha = normalizar_titulo_para_comparacao(linha_limpa)
        best_score = 0
        best_canonico = None
        for titulo_norm, canonico in titulos_norm_lookup.items():
            score = fuzz.token_set_ratio(titulo_norm, norm_linha)
            if score > best_score:
                best_score = score
                best_canonico = canonico
        # se não bateu o limiar, checa variantes simples (contains)
        if best_score < limiar_score:
            for titulo_norm, canonico in titulos_norm_lookup.items():
                if titulo_norm and titulo_norm in norm_linha:
                    best_score = 90
                    best_canonico = canonico
                    break
        # fallback local: se a linha seguinte (ou a própria) tem palavra-chave 'APRESENT' e não foi mapeada
        if best_score < limiar_score:
            # lookahead até 2 linhas por causa de quebras
            look_text = (linha_limpa + " " + (linhas[idx+1].strip() if idx+1 < len(linhas) else "")).upper()
            for k in ["APRESENTA", "COMPOSI", "DIZERES", "INFORMAÇ", "INFORMAC"]:
                if k in look_text:
                    # mapear para o canonico mais próximo por contains
                    for titulo_norm, canonico in titulos_norm_lookup.items():
                        if k.lower() in titulo_norm:
                            best_canonico = canonico
                            best_score = 85
                            break
                    if best_canonico:
                        break

        if best_score >= limiar_score and best_canonico:
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

def _extrair_linhas_qualificadoras_iniciais(texto, max_lines=4):
    """
    Versão conservadora: extrai QUALIFIERS apenas se:
      - linha curta (<=12 palavras)
      - contém chaves de apresentação (USO, NASAL, FRASCOS, EMBALAGENS, GOTAS, ML) OR
      - é MAIÚSCULA curta
    Evita mover linhas que claramente são fórmulas (contém 'contém', 'mg', 'ml', 'q.s.p').
    """
    if not texto:
        return [], texto
    linhas = texto.split('\n')
    qualifiers = []
    keys = {'USO', 'NASAL', 'ADULTO', 'EMBALAGENS', 'EMBALAGEM', 'FRASCOS', 'APRESENTA', 'APRESENTACAO', 'GOTAS', 'ML', 'MG'}
    i = 0
    while i < min(len(linhas), max_lines):
        ln = linhas[i].strip()
        if not ln:
            i += 1
            continue
        ln_upper = ln.upper()
        # não capture títulos exatos
        if ln_upper in {'APRESENTAÇÃO','APRESENTACAO','APRESENTAÇÕES','APRESENTACOES','COMPOSIÇÃO','COMPOSICAO','DIZERES LEGAIS','INFORMAÇÕES AO PACIENTE','INFORMACOES AO PACIENTE'}:
            break
        words = ln.split()
        word_count = len(words)
        uppercase_letters = sum(1 for ch in ln if ch.isalpha() and ch.isupper())
        alpha_letters = sum(1 for ch in ln if ch.isalpha())
        uppercase_ratio = (uppercase_letters / alpha_letters) if alpha_letters > 0 else 0
        contains_key = any(k in ln_upper for k in keys)
        is_short = word_count <= 12 and len(ln) < 140
        is_upper = uppercase_ratio > 0.6 and is_short
        looks_like_composition_line = bool(re.search(r'\b(?:cont[eé]m|equivalente|mg\b|ml\b|ve[ií]culo|veiculo|q\.s\.p|qsp|\d+mg|\d+ ml)\b', ln_upper))
        if (contains_key and is_short) or is_upper:
            if looks_like_composition_line and not contains_key:
                break
            qualifiers.append(ln)
            i += 1
            continue
        break
    restante = '\n'.join(linhas[i:]).strip()
    return qualifiers, restante

# Realocação: versão estrita — NÃO cria APRESENTAÇÕES novo e só move se destino detectado no MKT.
def realocar_qualifiers_inplace(map_conteudos, src_section='COMPOSIÇÃO', dst_section='APRESENTAÇÕES'):
    src = map_conteudos.get(src_section)
    dst = map_conteudos.get(dst_section)
    if not src or not dst:
        return
    if not src['conteudo_bel'].strip():
        return
    qualifiers_bel, restante_bel = _extrair_linhas_qualificadoras_iniciais(src['conteudo_bel'], max_lines=4)
    if not qualifiers_bel:
        return
    # se o destino NÃO foi detectado no MKT, NÃO mover — evita criar vazamento
    if not dst.get('encontrou_bel', False):
        return
    # evitar mover se qualifiers parecem ser composição
    looks_like_comp = any(re.search(r'\b(?:cont[eé]m|equivalente|mg\b|ml\b|ve[ií]culo|q\.s\.p|qsp)\b', q.upper()) for q in qualifiers_bel)
    if looks_like_comp:
        return
    # não mover se remover qualifiers deixar src vazio ou muito curto (proteção)
    if len(restante_bel.strip()) < 40:
        # se restante fica muito curto provavelmente qualifiers faziam parte da composição -> aborta
        return
    # evita duplicação
    def _contains_similar(dst_text, qualifiers):
        dst_norm = normalizar_texto(dst_text or "")
        for q in qualifiers:
            if normalizar_texto(q) in dst_norm:
                return True
        return False
    if _contains_similar(dst['conteudo_bel'], qualifiers_bel):
        # já presente no destino
        src['conteudo_bel'] = restante_bel
        return
    # safe prepend qualifiers after dst title (titulo is first line)
    qual_text = '\n'.join(q for q in qualifiers_bel if q.strip())
    lines_dst = dst['conteudo_bel'].split('\n')
    title_dst = lines_dst[0] if lines_dst else dst_section
    rest_dst = '\n'.join(lines_dst[1:]).strip() if len(lines_dst) > 1 else ""
    combined = f"{title_dst}\n\n{qual_text}\n\n{rest_dst}".strip()
    dst['conteudo_bel'] = combined
    src['conteudo_bel'] = restante_bel
        if not src:
            return
        if not src['conteudo_bel'].strip():
            return
        qualifiers_bel, restante_bel = _extrair_linhas_qualificadoras_iniciais(src['conteudo_bel'], max_lines=4)
        if qualifiers_bel:
            qual_text = '\n'.join([q for q in qualifiers_bel if q.strip() != ""]).strip()
            # Se qual_text parece claramente composição (tem 'contém', 'mg', 'ml' como parte da fórmula), não mover
            looks_like_comp = any(re.search(r'\b(?:cont[eé]m|mg\b|ml\b|equivalente|ve[ií]culo|q\.s\.p|qsp)\b', q.upper()) for q in qualifiers_bel)
            if looks_like_comp and len(qualifiers_bel) <= 2:
                # muito provável que seja parte da composição — não mover
                return
            # se destino existe no MKT, anexar após título; se não, criar destino (mas faça isso apenas se não duplicar)
            if dst and dst.get('encontrou_bel', False):
                if not _contains_similar(dst['conteudo_bel'], qualifiers_bel):
                    lines_dst = dst['conteudo_bel'].split('\n')
                    title_dst = lines_dst[0] if lines_dst else dst_section
                    rest_dst = '\n'.join(lines_dst[1:]).strip() if len(lines_dst) > 1 else ""
                    combined = f"{title_dst}\n\n{qual_text}\n\n{rest_dst}".strip()
                    dst['conteudo_bel'] = combined
                    src['conteudo_bel'] = restante_bel
            else:
                # destino não detectado no MKT: criar APRESENTAÇÕES no MKT somente se
                # - qual_text contiver chaves muito fortes (EX: 'USO NASAL', 'FRASCOS', 'EMBALAGENS') AND
                # - não parece composição
                strong_keys = any(k in q.upper() for q in qualifiers_bel for k in ['USO NASAL', 'USO ADULTO', 'EMBALAGENS', 'FRASCOS', 'APRESENTAÇ', 'APRESENTAC'])
                if strong_keys and not looks_like_comp:
                    # criar destino content (injetando título)
                    created = f"APRESENTAÇÕES\n\n{qual_text}"
                    # only create if not already contained elsewhere
                    if not _contains_similar(map_conteudos.get(dst_section, {}).get('conteudo_bel', ""), qualifiers_bel):
                        if dst:
                            dst['conteudo_bel'] = created + ("\n\n" + dst['conteudo_bel'] if dst['conteudo_bel'] else "")
                            dst['encontrou_bel'] = True
                        else:
                            map_conteudos[dst_section] = {'encontrou_ref': False, 'conteudo_ref': "", 'encontrou_bel': True, 'conteudo_bel': created}
                        src['conteudo_bel'] = restante_bel
        # processar referêncial (ANVISA) com mesma lógica (mais permissiva)
        qualifiers_ref, restante_ref = _extrair_linhas_qualificadoras_iniciais(src['conteudo_ref'], max_lines=4)
        if qualifiers_ref:
            qual_text_ref = '\n'.join([q for q in qualifiers_ref if q.strip() != ""]).strip()
            if dst and dst.get('encontrou_ref', False):
                if not _contains_similar(dst['conteudo_ref'], qualifiers_ref):
                    lines_dst = dst['conteudo_ref'].split('\n')
                    title_dst = lines_dst[0] if lines_dst else dst_section
                    rest_dst = '\n'.join(lines_dst[1:]).strip() if len(lines_dst) > 1 else ""
                    combined_ref = f"{title_dst}\n\n{qual_text_ref}\n\n{rest_dst}".strip()
                    dst['conteudo_ref'] = combined_ref
                    src['conteudo_ref'] = restante_ref
            else:
                strong_keys_ref = any(k in q.upper() for q in qualifiers_ref for k in ['USO NASAL', 'USO ADULTO', 'EMBALAGENS', 'FRASCOS', 'APRESENTAÇ', 'APRESENTAC'])
                looks_like_comp_ref = any(re.search(r'\b(?:cont[eé]m|mg\b|ml\b|equivalente|ve[ií]culo|q\.s\.p|qsp)\b', q.upper()) for q in qualifiers_ref)
                if strong_keys_ref and not looks_like_comp_ref:
                    if dst:
                        dst['conteudo_ref'] = f"{dst.get('conteudo_ref','').strip()}"
                        dst['encontrou_ref'] = True
                        # prepend in safe manner
                        lines_dst = dst['conteudo_ref'].split('\n') if dst.get('conteudo_ref') else []
                        title_dst = lines_dst[0] if lines_dst else dst_section
                        rest_dst = '\n'.join(lines_dst[1:]).strip() if len(lines_dst) > 1 else ""
                        combined_ref = f"{title_dst}\n\n{qual_text_ref}\n\n{rest_dst}".strip()
                        dst['conteudo_ref'] = combined_ref
                        src['conteudo_ref'] = restante_ref
    realocar_qualifiers_inplace(conteudos, src_section='COMPOSIÇÃO', dst_section='APRESENTAÇÕES')
    for sec in secoes_esperadas:
        item = conteudos[sec]
        encontrou_ref = item['encontrou_ref']
        encontrou_bel = item['encontrou_bel']
        conteudo_ref = item['conteudo_ref']
        conteudo_bel = item['conteudo_bel']
        if not encontrou_bel:
            relatorio.append({'secao': sec, 'status': 'faltante', 'conteudo_ref': conteudo_ref, 'conteudo_belfar': ""})
            continue
        if encontrou_ref and encontrou_bel:
            if sec.upper() in secoes_ignorar_upper:
                relatorio.append({'secao': sec, 'status': 'identica', 'conteudo_ref': conteudo_ref, 'conteudo_belfar': conteudo_bel})
                similaridade_geral.append(100)
                continue
            if normalizar_texto(conteudo_ref) != normalizar_texto(conteudo_bel):
                relatorio.append({'secao': sec, 'status': 'diferente', 'conteudo_ref': conteudo_ref, 'conteudo_belfar': conteudo_bel})
                similaridade_geral.append(0)
            else:
                relatorio.append({'secao': sec, 'status': 'identica', 'conteudo_ref': conteudo_ref, 'conteudo_belfar': conteudo_bel})
                similaridade_geral.append(100)
    titulos_ref_encontrados = {m['canonico']: m['titulo_encontrado'] for m in mapa_ref}
    titulos_belfar_encontrados = {m['canonico']: m['titulo_encontrado'] for m in mapa_belfar}
    diferencas_titulos = []
    for secao_canonico, titulo_ref in titulos_ref_encontrados.items():
        if secao_canonico in titulos_belfar_encontrados:
            titulo_belfar = titulos_belfar_encontrados[secao_canonico]
            if normalizar_titulo_para_comparacao(titulo_ref) != normalizar_titulo_para_comparacao(titulo_belfar):
                diferencas_titulos.append({'secao_esperada': secao_canonico, 'titulo_encontrado': titulo_belfar})
    return secoes_faltantes, relatorio, similaridade_geral, diferencas_titulos

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
        if not re.match(r'^[.,;:!?)\\]$', raw_tok) and raw_tok != '\n' and tok_anterior_raw != '\n' and not re.match(r'^[(\\[]$', tok_anterior_raw):
            resultado += " " + tok
        else:
            resultado += tok
    resultado = re.sub(r"(</mark>)\s+(<mark[^>]*>)", " ", resultado)
    return resultado

# ----------------- GERAÇÃO DE RELATÓRIO (v26.57 - MANTIDO) -----------------
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
                html_ref_bruto_expander = marcar_diferencas_palavra_por_palavra(conteudo_ref_str, conteudo_belfar_str, eh_referencia=True)
                html_belfar_bruto_expander = marcar_diferencas_palavra_por_palavra(conteudo_ref_str, conteudo_belfar_str, eh_referencia=False)
                expander_html_ref = formatar_html_para_leitura(html_ref_bruto_expander, aplicar_numeracao=True)
                expander_html_belfar = formatar_html_para_leitura(html_belfar_bruto_expander, aplicar_numeracao=False)
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
                expander_html_ref = formatar_html_para_leitura(conteudo_ref_str, aplicar_numeracao=True)
                expander_html_belfar = formatar_html_para_leitura(conteudo_belfar_str, aplicar_numeracao=False)
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
    st.subheader("🎨 Visualização Lado a Lado com Destaques")
    legend_style = ("font-size: 14px; background-color: #f0f2f6; padding: 10px 15px; border-radius: 8px; margin-bottom: 15px;")
    st.markdown(f"<div style='{legend_style}'><strong>Legenda:</strong> <mark style='background-color: #ffff99; padding: 2px; margin: 0 2px;'>Amarelo</mark> = Divergências | <mark style='background-color: #FFDDC1; padding: 2px; margin: 0 2px;'>Rosa</mark> = Erros ortográficos | <mark style='background-color: #cce5ff; padding: 2px; margin: 0 2px;'>Azul</mark> = Data ANVISA</div>", unsafe_allow_html=True)
    html_ref_bruto = marcar_divergencias_html(texto_original=texto_ref_safe, secoes_problema_lista_dicionarios=relatorio_comparacao_completo, erros_ortograficos=[], tipo_bula=tipo_bula, eh_referencia=True)
    html_belfar_marcado_bruto = marcar_divergencias_html(texto_original=texto_belfar_safe, secoes_problema_lista_dicionarios=relatorio_comparacao_completo, erros_ortograficos=erros_ortograficos, tipo_bula=tipo_bula, eh_referencia=False)
    html_ref_marcado = formatar_html_para_leitura(html_ref_bruto, aplicar_numeracao=True)
    html_belfar_marcado = formatar_html_para_leitura(html_belfar_marcado_bruto, aplicar_numeracao=False)
    caixa_style = ("max-height: 700px; overflow-y: auto; border: 1px solid #e0e0e0; border-radius: 8px; padding: 20px 24px; background-color: #ffffff; font-size: 15px; line-height: 1.7; box-shadow: 0 4px 12px rgba(0,0,0,0.08); text-align: left; overflow-wrap: break-word; word-break: break-word;")
    title_style = ("font-size: 1.25rem; font-weight: 600; margin-bottom: 8px; color: #31333F;")
    col1, col2 = st.columns(2, gap="large")
    with col1:
        st.markdown(f"<div style='{title_style}'>{nome_ref}</div>", unsafe_allow_html=True)
        st.markdown(f"<div style='{caixa_style}'>{html_ref_marcado}</div>", unsafe_allow_html=True)
    with col2:
        st.markdown(f"<div style='{title_style}'>{nome_belfar}</div>", unsafe_allow_html=True)
        st.markdown(f"<div style='{caixa_style}'>{html_belfar_marcado}</div>", unsafe_allow_html=True)

# ----------------- LAYOUT -----------------
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
st.caption("Sistema de Auditoria de Bulas v26.58 | Correção Extração MKT | Realocação de qualifiers para APRESENTAÇÕES")
