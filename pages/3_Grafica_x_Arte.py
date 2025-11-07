# --- IMPORTS ---
import re
import difflib
import unicodedata
import io
import os

import streamlit as st
import fitz  # PyMuPDF
import docx
import spacy
from thefuzz import fuzz
from spellchecker import SpellChecker
import pytesseract
from PIL import Image

# --- CONFIG STREAMLIT (mantive o seu CSS) ---
hide_streamlit_UI = """
            <style>
            [data-testid="stHeader"] { display: none !important; visibility: hidden !important; }
            [data-testid="main-menu-button"] { display: none !important; }
            footer { display: none !important; visibility: hidden !important; }
            [data-testid="stStatusWidget"] { display: none !important; visibility: hidden !important; }
            [data-testid="stCreatedBy"] { display: none !important; visibility: hidden !important; }
            [data-testid="stHostedBy"] { display: none !important; visibility: hidden !important; }
            </style>
            """
st.markdown(hide_streamlit_UI, unsafe_allow_html=True)

# ----------------- MODELO NLP -----------------
@st.cache_resource
def carregar_modelo_spacy():
    try:
        return spacy.load("pt_core_news_lg")
    except OSError:
        st.error("Modelo 'pt_core_news_lg' não encontrado. Execute: python -m spacy download pt_core_news_lg")
        return None

nlp = carregar_modelo_spacy()

# ----------------- PADRÕES PARA FILTRAR BLOCOS GRÁFICOS (Ajuste se quiser) -----------------
GRAFICOS_PATTERNS = [
    r'\bmedida da bula\b', r'\bfrente\b', r'\bverso\b', r'\btipologia\b', r'\btimes new roman\b',
    r'\bap\s*\d+gr\b', r'\bpapel\b', r'\bcor\b', r'\bimpressão\b', r'\bmm\b', r'\bcm\b',
    r'\bBELFAR\b', r'\bBUL_[A-Z0-9_]+\b', r'\bcontato\b', r'\bartes?@', r'\bregistro\b', r'\bimpressa[oã]\b',
    r'\bmedida\b', r'\bcep\b', r'\bSAC\b', r'\bbarcode\b'
]
GRAFICOS_RE = re.compile("|".join(GRAFICOS_PATTERNS), flags=re.IGNORECASE)

def filtrar_bloco_grafico(texto):
    """
    Remove linhas / blocos que tipicamente correspondem a áreas de diagramação,
    medidas, contato da gráfica, rodapés técnicos que você marcou nas imagens.
    """
    linhas = [l.rstrip() for l in texto.splitlines()]
    linhas_filtradas = []
    # Se houver blocos repetitivos curtos (ex: caixa azul com 3-6 linhas), removemos por heurística
    i = 0
    while i < len(linhas):
        linha = linhas[i].strip()
        if not linha:
            linhas_filtradas.append(linhas[i])
            i += 1
            continue

        # Se a linha contém um padrão gráfico, pule uma "região" possível (heurística: até 8 linhas)
        if GRAFICOS_RE.search(linha):
            # pula bloco de até 8 linhas que contenham muitas palavras curtas/técnicas
            skip_count = 1
            for j in range(i+1, min(i+8, len(linhas))):
                # se a próxima linha também tem pattern ou é curta com números, aumente skip
                if GRAFICOS_RE.search(linhas[j]) or re.search(r'\b\d{2,3}\s*mm\b|\b\d+\s*mm\b|\b\d{1,3}\s*x\s*\d{1,3}\b', linhas[j], re.IGNORECASE):
                    skip_count += 1
                else:
                    break
            i += skip_count
            continue

        # Caso contrário, se a linha for curta e conter muitas siglas/maiusculas e números, considere descartá-la
        if len(linha) < 40 and re.search(r'[A-Z]{2,}|[\d]{2,}', linha):
            # mas só descarta se tiver ao menos um token que pareça técnico
            if re.search(r'\bAp\b|\bBUL\b|\bBELFAR\b|mm|cm|Impress', linha, re.IGNORECASE):
                i += 1
                continue

        linhas_filtradas.append(linhas[i])
        i += 1

    resultado = "\n".join([l for l in linhas_filtradas if l.strip() != ''])
    # Remover regiões duplicadas e linhas curtas soltas
    resultado = re.sub(r'\n{3,}', '\n\n', resultado)
    return resultado

# ----------------- OCR FORÇADO EM TODAS AS PÁGINAS -----------------
def extrair_texto_pdf_com_ocr(arquivo_bytes):
    """
    Faz OCR forçado em todas as páginas do PDF usando PyMuPDF + pytesseract.
    Retorna o texto inteiro extraído por OCR (mais confiável para bulas vetoriais).
    """
    texto_total = []
    with fitz.open(stream=io.BytesIO(arquivo_bytes), filetype="pdf") as doc:
        for i, page in enumerate(doc):
            try:
                # Renderiza com dpi relativamente alto para aumentar acurácia do OCR
                pix = page.get_pixmap(dpi=300)
                img_bytes = pix.tobytes("png")
                imagem = Image.open(io.BytesIO(img_bytes)).convert("RGB")
                # Config do tesseract: psm 6 (blocos de texto) + oem 3
                config = "--psm 6 --oem 3"
                texto_pagina = pytesseract.image_to_string(imagem, lang='por', config=config)
                # Aplica limpeza básica na página
                texto_pagina = texto_pagina.replace('\r\n', '\n').replace('\r', '\n')
                texto_total.append(texto_pagina.strip())
            except Exception as e:
                # Em erro, tenta extração direta como fallback para essa página
                try:
                    texto_total.append(page.get_text("text"))
                except:
                    texto_total.append('')
    texto_completo = "\n\n".join([t for t in texto_total if t])
    # Filtra blocos gráficos conhecidos
    texto_completo = filtrar_bloco_grafico(texto_completo)
    return texto_completo

# ----------------- FUNÇÃO DE EXTRAÇÃO PRINCIPAL -----------------
def extrair_texto(arquivo, tipo_arquivo):
    if arquivo is None:
        return "", f"Arquivo {tipo_arquivo} não enviado."
    try:
        arquivo.seek(0)
        texto = ""
        if tipo_arquivo == 'pdf':
            texto = extrair_texto_pdf_com_ocr(arquivo.read())
        elif tipo_arquivo == 'docx':
            doc = docx.Document(arquivo)
            texto = "\n".join([p.text for p in doc.paragraphs])

        if texto:
            caracteres_invisiveis = ['\u00AD', '\u200B', '\u200C', '\u200D', '\uFEFF']
            for char in caracteres_invisiveis:
                texto = texto.replace(char, '')
            texto = texto.replace('\u00A0', ' ')
            texto = re.sub(r'(\w+)-\n(\w+)', r'\1\2', texto, flags=re.IGNORECASE)
            texto = texto.replace('\r\n', '\n').replace('\r', '\n')
            # Retira rodapés comuns
            padrao_rodape = re.compile(r'bula do paciente|página \d+\s*de\s*\d+|Siga corretamente o modo de usar', re.IGNORECASE)
            linhas = texto.split('\n')
            linhas = [l for l in linhas if not padrao_rodape.search(l.strip())]
            texto = "\n".join(linhas)
            texto = re.sub(r'\n{3,}', '\n\n', texto)
            texto = re.sub(r'[ \t]+', ' ', texto)
            texto = texto.strip()
        return texto, None
    except Exception as e:
        return "", f"Erro ao ler o arquivo {tipo_arquivo}: {e}"

# ----------------- SEÇÕES NUMERADAS (conforme pedido) -----------------
def obter_secoes_por_tipo(tipo_bula):
    secoes = {
        "Paciente": [
            "APRESENTAÇÕES", "COMPOSIÇÃO", "1. PARA QUE ESTE MEDICAMENTO É INDICADO?",
            "2. COMO ESTE MEDICAMENTO FUNCIONA?", "3. QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?",
            "4. O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?",
            "5. ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?",
            "6. COMO DEVO USAR ESTE MEDICAMENTO?",
            "7. O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?",
            "8. QUAIS OS MALES QUE ESTE MEDICAMENTO PODE ME CAUSAR?",
            "9. O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?",
            "DIZERES LEGAIS"
        ],
        "Profissional": [
            "APRESENTAÇÕES", "COMPOSIÇÃO", "1. INDICAÇÕES", "2. RESULTADOS DE EFICÁCIA",
            "3. CARACTERÍSTICAS FARMACOLÓGICAS", "4. CONTRAINDICAÇÕES",
            "5. ADVERTÊNCIAS E PRECAUÇÕES", "6. INTERAÇÕES MEDICAMENTOSAS",
            "7. CUIDADOS DE ARMAZENAMENTO DO MEDICAMENTO", "8. POSOLOGIA E MODO DE USAR",
            "9. REAÇÕES ADVERSAS", "10. SUPERDOSE", "DIZERES LEGAIS"
        ]
    }
    return secoes.get(tipo_bula, [])

def obter_aliases_secao():
    return {
        "INDICAÇÕES": "1. INDICAÇÕES",
        "CONTRAINDICAÇÕES": "4. CONTRAINDICAÇÕES",
        "POSOLOGIA E MODO DE USAR": "8. POSOLOGIA E MODO DE USAR",
        "REAÇÕES ADVERSAS": "9. REAÇÕES ADVERSAS",
        "SUPERDOSE": "10. SUPERDOSE",
        "CUIDADOS DE ARMAZENAMENTO DO MEDICAMENTO": "7. CUIDADOS DE ARMAZENAMENTO DO MEDICAMENTO"
    }

def obter_secoes_ignorar_ortografia():
    return ["COMPOSIÇÃO", "DIZERES LEGAIS"]

def obter_secoes_ignorar_comparacao():
    return ["COMPOSIÇÃO", "DIZERES LEGAIS", "APRESENTAÇÕES", "ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?"]

# ----------------- NORMALIZAÇÃO -----------------
def normalizar_texto(texto):
    texto = ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')
    texto = re.sub(r'[^\w\s]', '', texto)
    texto = ' '.join(texto.split())
    return texto.lower()

def normalizar_titulo_para_comparacao(texto):
    texto_norm = normalizar_texto(texto)
    texto_norm = re.sub(r'^\d+\s*[\.\-)]*\s*', '', texto_norm).strip()
    return texto_norm

def _create_anchor_id(secao_nome, prefix):
    norm = normalizar_texto(secao_nome)
    norm_safe = re.sub(r'[^a-z0-9\-]', '-', norm)
    return f"anchor-{prefix}-{norm_safe}"

def is_titulo_secao(linha):
    linha = linha.strip()
    if len(linha) < 4:
        return False
    if len(linha.split()) > 20:
        return False
    if linha.endswith('.') and len(linha) > 6:
        # permitir títulos terminados em ponto apenas se curtos
        return False
    if re.search(r'\>\s*\<', linha):
        return False
    if len(linha) > 120:
        return False
    return True

def mapear_secoes(texto_completo, secoes_esperadas):
    mapa = []
    linhas = texto_completo.split('\n')
    aliases = obter_aliases_secao()

    titulos_possiveis = {}
    for secao in secoes_esperadas:
        titulos_possiveis[secao] = secao
        # também adicione a versão sem numeração para matching
        titulos_possiveis[re.sub(r'^\d+\.\s*', '', secao)] = secao
    for alias, canonico in aliases.items():
        if canonico in secoes_esperadas:
            titulos_possiveis[alias] = canonico

    for idx, linha in enumerate(linhas):
        linha_limpa = linha.strip()
        if not is_titulo_secao(linha_limpa):
            continue

        linha_norm = normalizar_texto(linha_limpa)
        if not linha_norm:
            continue

        best_match_score = 0
        best_match_canonico = None

        for titulo_possivel, titulo_canonico in titulos_possiveis.items():
            score = fuzz.token_set_ratio(normalizar_titulo_para_comparacao(titulo_possivel), normalizar_titulo_para_comparacao(linha_limpa))
            if score > best_match_score:
                best_match_score = score
                best_match_canonico = titulo_canonico

        if best_match_score >= 90:  # ser um pouco mais permissivo
            if not mapa or mapa[-1]['canonico'] != best_match_canonico:
                mapa.append({
                    'canonico': best_match_canonico,
                    'titulo_encontrado': linha_limpa,
                    'linha_inicio': idx,
                    'score': best_match_score
                })

    mapa.sort(key=lambda x: x['linha_inicio'])
    return mapa

def obter_dados_secao(secao_canonico, mapa_secoes, linhas_texto, tipo_bula):
    TITULOS_OFICIAIS = {
        "Paciente": [
            "APRESENTAÇÕES", "COMPOSIÇÃO", "1. PARA QUE ESTE MEDICAMENTO É INDICADO?",
            "2. COMO ESTE MEDICAMENTO FUNCIONA?", "3. QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?",
            "4. O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?",
            "5. ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?",
            "6. COMO DEVO USAR ESTE MEDICAMENTO?",
            "7. O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?",
            "8. QUAIS OS MALES QUE ESTE MEDICAMENTO PODE ME CAUSAR?",
            "9. O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?",
            "DIZERES LEGAIS"
        ],
        "Profissional": [
            "APRESENTAÇÕES", "COMPOSIÇÃO", "1. INDICAÇÕES", "2. RESULTADOS DE EFICÁCIA",
            "3. CARACTERÍSTICAS FARMACOLÓGICAS", "4. CONTRAINDICAÇÕES",
            "5. ADVERTÊNCIAS E PRECAUÇÕES", "6. INTERAÇÕES MEDICAMENTOSAS",
            "7. CUIDADOS DE ARMAZENAMENTO DO MEDICAMENTO", "8. POSOLOGIA E MODO DE USAR",
            "9. REAÇÕES ADVERSAS", "10. SUPERDOSE", "DIZERES LEGAIS"
        ]
    }

    titulos_lista = TITULOS_OFICIAIS.get(tipo_bula, [])
    titulos_norm_set = {normalizar_titulo_para_comparacao(t) for t in titulos_lista}

    for i, secao_mapa in enumerate(mapa_secoes):
        if secao_mapa['canonico'] != secao_canonico:
            continue

        titulo_encontrado = secao_mapa['titulo_encontrado']
        linha_inicio = secao_mapa['linha_inicio']
        linha_inicio_conteudo = linha_inicio + 1

        prox_idx = None
        for j in range(linha_inicio_conteudo, len(linhas_texto)):
            linha_atual = linhas_texto[j].strip()
            linha_atual_norm = normalizar_titulo_para_comparacao(linha_atual)

            encontrou_titulo_1_linha = False
            for titulo_oficial_norm in titulos_norm_set:
                if titulo_oficial_norm and titulo_oficial_norm in linha_atual_norm:
                    encontrou_titulo_1_linha = True
                    break

            if encontrou_titulo_1_linha:
                prox_idx = j
                break

            if (j + 1) < len(linhas_texto):
                linha_seguinte = linhas_texto[j + 1].strip()
                titulo_duas_linhas = f"{linha_atual} {linha_seguinte}"
                titulo_duas_linhas_norm = normalizar_titulo_para_comparacao(titulo_duas_linhas)

                encontrou_titulo_2_linhas = False
                for titulo_oficial_norm in titulos_norm_set:
                    if titulo_oficial_norm and titulo_oficial_norm in titulo_duas_linhas_norm:
                        encontrou_titulo_2_linhas = True
                        break

                if encontrou_titulo_2_linhas:
                    prox_idx = j
                    break

        linha_fim = prox_idx if prox_idx is not None else len(linhas_texto)
        conteudo = [linhas_texto[idx] for idx in range(linha_inicio_conteudo, linha_fim)]
        conteudo_final = "\n".join(conteudo).strip()
        return True, titulo_encontrado, conteudo_final

    return False, None, ""

# ----------------- VERIFICAÇÃO E RELATÓRIO (MOSTRA TODAS AS SEÇÕES) -----------------
def verificar_secoes_e_conteudo(texto_ref, texto_belfar, tipo_bula):
    secoes_esperadas = obter_secoes_por_tipo(tipo_bula)
    secoes_faltantes, diferencas_conteudo, similaridades_secoes, diferencas_titulos = [], [], [], []
    secoes_ignorar_upper = [s.upper() for s in obter_secoes_ignorar_comparacao()]

    linhas_ref = texto_ref.split('\n')
    linhas_belfar = texto_belfar.split('\n')
    mapa_ref = mapear_secoes(texto_ref, secoes_esperadas)
    mapa_belfar = mapear_secoes(texto_belfar, secoes_esperadas)

    for secao in secoes_esperadas:
        melhor_titulo = None
        encontrou_ref, _, conteudo_ref = obter_dados_secao(secao, mapa_ref, linhas_ref, tipo_bula)
        encontrou_belfar, titulo_belfar, conteudo_belfar = obter_dados_secao(secao, mapa_belfar, linhas_belfar, tipo_bula)

        if not encontrou_belfar:
            # tenta fuzzy para achar título parecido
            melhor_score = 0
            melhor_titulo = None
            for m in mapa_belfar:
                score = fuzz.token_set_ratio(normalizar_titulo_para_comparacao(secao), normalizar_titulo_para_comparacao(m['titulo_encontrado']))
                if score > melhor_score:
                    melhor_score = score
                    melhor_titulo = m['titulo_encontrado']
            if melhor_score >= 85:
                for m in mapa_belfar:
                    if m['titulo_encontrado'] == melhor_titulo:
                        next_section_start = len(linhas_belfar)
                        current_index = mapa_belfar.index(m)
                        if current_index + 1 < len(mapa_belfar):
                            next_section_start = mapa_belfar[current_index + 1]['linha_inicio']
                        conteudo_belfar = "\n".join(linhas_belfar[m['linha_inicio']+1:next_section_start])
                        break
                encontrou_belfar = True

        if not encontrou_belfar:
            secoes_faltantes.append(secao)

        # mesmo que idênticos, guardamos os conteúdos (você pediu todas as seções separadas)
        if encontrou_ref and encontrou_belfar:
            if normalizar_texto(conteudo_ref) != normalizar_texto(conteudo_belfar):
                diferencas_conteudo.append({
                    'secao': secao,
                    'conteudo_ref': conteudo_ref,
                    'conteudo_belfar': conteudo_belfar,
                    'titulo_encontrado': titulo_belfar or melhor_titulo
                })
                similaridades_secoes.append(0)
            else:
                similaridades_secoes.append(100)
        else:
            similaridades_secoes.append(0)

    return secoes_faltantes, diferencas_conteudo, similaridades_secoes, []

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
            encontrou, _, conteudo = obter_dados_secao(secao_nome, mapa_secoes, linhas_texto, tipo_bula)
            if encontrou and conteudo:
                linhas_conteudo = conteudo.split('\n')
                if len(linhas_conteudo) > 1:
                    texto_filtrado_para_checar.append('\n'.join(linhas_conteudo[1:]))

        texto_final_para_checar = '\n'.join(texto_filtrado_para_checar)
        if not texto_final_para_checar:
            return []

        spell = SpellChecker(language='pt')
        palavras_a_ignorar = {"alair", "belfar", "peticionamento", "urotrobel"}
        vocab_referencia = set(re.findall(r'\b[a-záéíóúâêôãõçü]+\b', texto_referencia.lower()))
        doc = nlp(texto_para_checar)
        entidades = {ent.text.lower() for ent in doc.ents}

        spell.word_frequency.load_words(vocab_referencia.union(entidades).union(palavras_a_ignorar))

        palavras = re.findall(r'\b[a-záéíóúâêôãõçü]+\b', texto_final_para_checar.lower())
        erros = spell.unknown(palavras)
        return list(sorted(set([e for e in erros if len(e) > 3])))[:20]
    except Exception as e:
        return []

def tokenizar_para_marcacao(txt):
    return re.findall(r'\n|[A-Za-zÀ-ÖØ-öø-ÿ0-9_]+|[^\w\s]', txt, re.UNICODE)

def marcar_diferencas_palavra_por_palavra(texto_ref, texto_belfar, eh_referencia):
    def tokenizar(txt):
        return tokenizar_para_marcacao(txt)

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
        raw_tok = re.sub(r'^<mark[^>]*>|</mark>$', '', tok)
        if re.match(r'^[^\w\s]$', raw_tok) or raw_tok == '\n':
            resultado += tok
        else:
            resultado += " " + tok
    resultado = re.sub(r'\s+([.,;:!?)])', r'\1', resultado)
    resultado = re.sub(r'(\()\s+', r'\1', resultado)
    resultado = re.sub(r"(</mark>)\s+(<mark[^>]*>)", " ", resultado)
    return resultado

def marcar_divergencias_html(texto_original, secoes_problema, erros_ortograficos, tipo_bula, eh_referencia=False):
    texto_trabalho = texto_original
    if secoes_problema:
        for diff in secoes_problema:
            conteudo_ref = diff['conteudo_ref']
            conteudo_belfar = diff['conteudo_belfar']
            conteudo_a_marcar = conteudo_ref if eh_referencia else conteudo_belfar
            conteudo_marcado = marcar_diferencas_palavra_por_palavra(conteudo_ref, conteudo_belfar, eh_referencia)
            secao_canonico = diff['secao']
            anchor_id = _create_anchor_id(secao_canonico, "ref" if eh_referencia else "bel")
            conteudo_com_ancora = f"<div id='{anchor_id}' style='scroll-margin-top: 20px;'>{conteudo_marcado}</div>"
            if conteudo_a_marcar in texto_trabalho:
                texto_trabalho = texto_trabalho.replace(conteudo_a_marcar, conteudo_com_ancora)

    if erros_ortograficos and not eh_referencia:
        for erro in erros_ortograficos:
            pattern = r'(?<![<>a-zA-Z])(?<!mark>)(?<!;>)\b(' + re.escape(erro) + r')\b(?![<>])'
            texto_trabalho = re.sub(pattern, r"<mark style='background-color: #FFDDC1; padding: 2px;'>\1</mark>", texto_trabalho, flags=re.IGNORECASE)

    regex_anvisa = r"((?:aprovad[ao]\s+pela\s+anvisa\s+em|data\s+de\s+aprovação\s+na\s+anvisa:)\s*[\d]{1,2}/[\d]{1,2}/[\d]{2,4})"
    match = re.search(regex_anvisa, texto_original, re.IGNORECASE)
    if match:
        frase_anvisa = match.group(1)
        if frase_anvisa in texto_trabalho:
            texto_trabalho = texto_trabalho.replace(frase_anvisa, f"<mark style='background-color: #cce5ff; padding: 2px; font-weight: 500;'>{frase_anvisa}</mark>", 1)
    return texto_trabalho

# ----------------- RELATÓRIO FINAL (MOSTRA TODAS AS SEÇÕES SEPARADAS) -----------------
def gerar_relatorio_final(texto_ref, texto_belfar, nome_ref, nome_belfar, tipo_bula):
    st.header("Relatório de Auditoria Inteligente (v19.0)")
    secoes_faltantes, diferencas_conteudo, similaridades, diferencas_titulos = verificar_secoes_e_conteudo(texto_ref, texto_belfar, tipo_bula)
    erros_ortograficos = checar_ortografia_inteligente(texto_belfar, texto_ref, tipo_bula)
    score_similaridade_conteudo = sum(similaridades) / len(similaridades) if similaridades else 100.0

    st.subheader("Dashboard de Veredito")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Conformidade de Conteúdo", f"{score_similaridade_conteudo:.0f}%")
    col2.metric("Erros Ortográficos", len(erros_ortograficos))
    col3.metric("Data ANVISA (BELFAR)", "Ver detalhe abaixo")
    col4.metric("Seções Faltantes", f"{len(secoes_faltantes)}")

    st.divider()
    st.subheader("Seções (todas separadas e numeradas)")
    secoes_esperadas = obter_secoes_por_tipo(tipo_bula)
    linhas_ref = texto_ref.split('\n')
    linhas_belfar = texto_belfar.split('\n')
    mapa_ref = mapear_secoes(texto_ref, secoes_esperadas)
    mapa_belfar = mapear_secoes(texto_belfar, secoes_esperadas)

    for secao in secoes_esperadas:
        encontrou_ref, titulo_ref, conteudo_ref = obter_dados_secao(secao, mapa_ref, linhas_ref, tipo_bula)
        encontrou_bel, titulo_bel, conteudo_bel = obter_dados_secao(secao, mapa_belfar, linhas_belfar, tipo_bula)

        display_titulo = titulo_bel or titulo_ref or secao
        with st.expander(f"📂 {display_titulo}"):
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**Referência (Referência/Arte Vigente):**")
                st.text(conteudo_ref or "[Não encontrada]")
            with c2:
                st.markdown("**BELFAR (PDF da Gráfica):**")
                st.text(conteudo_bel or "[Não encontrada]")

            # Se houver diferença, mostre side-by-side marcação
            if conteudo_ref and conteudo_bel and normalizar_texto(conteudo_ref) != normalizar_texto(conteudo_bel):
                st.markdown("**Divergências destacadas (palavra a palavra):**")
                html_ref = marcar_diferencas_palavra_por_palavra(conteudo_ref, conteudo_bel, True).replace('\n', '<br>')
                html_bel = marcar_diferencas_palavra_por_palavra(conteudo_ref, conteudo_bel, False).replace('\n', '<br>')
                st.markdown("**Referência (marcada):**", unsafe_allow_html=True)
                st.markdown(html_ref, unsafe_allow_html=True)
                st.markdown("**BELFAR (marcada):**", unsafe_allow_html=True)
                st.markdown(html_bel, unsafe_allow_html=True)
            else:
                st.success("Seção idêntica (ou conteúdo não encontrado em uma das versões).")

    if erros_ortograficos:
        st.info(f"📝 Possíveis erros ortográficos ({len(erros_ortograficos)}): " + ", ".join(erros_ortograficos))

# ----------------- INTERFACE -----------------
st.set_page_config(layout="wide", page_title="Auditoria de Bulas (v19.0)", page_icon="🔬")
st.title("🔬 Inteligência Artificial para Auditoria de Bulas — v19.0")
st.markdown("OCR forçado em todas as páginas + seções numeradas e filtragem de blocos gráficos")
st.divider()

tipo_bula_selecionado = st.radio("Tipo de Bula:", ("Paciente", "Profissional"), horizontal=True)
col1, col2 = st.columns(2)
with col1:
    st.subheader("📄 Arte Vigente")
    pdf_ref = st.file_uploader("Envie o PDF de referência", type=["pdf","docx"], key="ref")
with col2:
    st.subheader("📄 PDF da Gráfica")
    pdf_belfar = st.file_uploader("Envie o PDF BELFAR", type="pdf", key="belfar")

if st.button("🔍 Iniciar Auditoria Completa (OCR em todas as páginas)", use_container_width=True, type="primary"):
    if pdf_ref and pdf_belfar:
        with st.spinner("🔄 Processando (OCR em todas as páginas) — isto pode demorar..."):
            tipo_arquivo_ref = 'docx' if pdf_ref.name.lower().endswith('.docx') else 'pdf'
            texto_ref, erro_ref = extrair_texto(pdf_ref, tipo_arquivo_ref)
            texto_belfar, erro_belfar = extrair_texto(pdf_belfar, 'pdf')

            if not erro_ref:
                texto_ref = texto_ref
            if not erro_belfar:
                texto_belfar = texto_belfar

            if erro_ref or erro_belfar:
                st.error(f"Erro ao processar arquivos: {erro_ref or erro_belfar}")
            else:
                gerar_relatorio_final(texto_ref, texto_belfar, "Arte Vigente (Referência)", "PDF da Gráfica", tipo_bula_selecionado)
    else:
        st.warning("⚠️ Por favor, envie ambos os arquivos (referência e BELFAR) para iniciar a auditoria.")

st.divider()
st.caption("Sistema de Auditoria de Bulas v19.0 | OCR forçado em todas as páginas | Filtragem automática de blocos gráficos")
