# pages/2_Conferencia_MKT.py
#
# Versão v26.58 (Ajustes solicitados)
# - Mantido backend v26.58 (extração, mapeamento, comparação, ortografia).
# - Alterações pedidas:
#   * Só realocar para APRESENTAÇÕES a linha com "USO NASAL" + "ADULTO" (ex.: "USO NASAL USO ADULTO").
#   * Se o título do MKT for diferente do título canônico, destacar o título do MKT em amarelo.
#   * Quando o título ocupar mais de 1 linha, mapear todas as linhas do título (manter cor/fonte ao renderizar).
#   * Removida a seção "INFORMAÇÕES AO PACIENTE" da configuração (não processar).
#
# Cole este arquivo substituindo o anterior em pages/2_Conferencia_MKT.py e reinicie o Streamlit.

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
    try:
        return spacy.load("pt_core_news_lg")
    except OSError:
        st.warning("Modelo 'pt_core_news_lg' não encontrado. NER ficará reduzido.")
        return None

nlp = carregar_modelo_spacy()

# ----------------- UTILITÁRIOS -----------------
def normalizar_texto(texto):
    if not isinstance(texto, str):
        return ""
    texto = ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')
    texto = re.sub(r'[^\w\s]', '', texto)
    texto = ' '.join(texto.split())
    return texto.lower()

def normalizar_titulo_para_comparacao(texto):
    t = normalizar_texto(texto or "")
    t = re.sub(r'^\d+\s*[\.\-)]*\s*', '', t).strip()
    return t

# ----------------- CONFIGURAÇÃO DE SEÇÕES (INFORMAÇÕES AO PACIENTE REMOVIDA) -----------------
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
        "PARA QUE ESTE MEDICAMENTO É INDICADO?": "1.PARA QUE ESTE MEDICAMENTO É INDICADO?",
        "COMO ESTE MEDICAMENTO FUNCIONA?": "2.COMO ESTE MEDICAMENTO FUNCIONA?",
        "QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?": "3.QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?",
        "O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?": "4.O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?",
        "ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?": "5.ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?",
        "COMO DEVO USAR ESTE MEDICAMENTO?": "6.COMO DEVO USAR ESTE MEDICAMENTO?",
        "O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?": "7.O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?",
        "QUAIS OS MALES QUE ESTE MEDICAMENTO PODE ME CAUSAR?": "8.QUAIS OS MALES QUE ESTE MEDICAMENTO PODE ME CAUSAR?",
        "O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?": "9.O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?"
    }

def obter_secoes_ignorar_comparacao():
    return ["APRESENTAÇÕES", "COMPOSIÇÃO", "DIZERES LEGAIS"]

def obter_secoes_ignorar_ortografia():
    return ["APRESENTAÇÕES", "COMPOSIÇÃO", "DIZERES LEGAIS"]

# ----------------- EXTRAÇÃO (mantida v26.58) -----------------
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
                        left = fitz.Rect(0, 0, rect.width / 2, rect.height)
                        right = fitz.Rect(rect.width / 2, 0, rect.width, rect.height)
                        texto_left = page.get_text("text", clip=left, sort=True)
                        texto_right = page.get_text("text", clip=right, sort=True)
                        full_text_list.append(texto_left)
                        full_text_list.append(texto_right)
                else:
                    for page in doc:
                        full_text_list.append(page.get_text("text", sort=True))
            texto = "\n\n".join(full_text_list)
        elif tipo_arquivo == 'docx':
            doc = docx.Document(arquivo)
            texto = "\n".join([p.text for p in doc.paragraphs])

        if texto:
            invis = ['\u00AD', '\u200B', '\u200C', '\u200D', '\uFEFF']
            for c in invis:
                texto = texto.replace(c, '')
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
            texto = re.sub(r'__KEEPBUL_(BUL_CLORIDRATO_DE_NAFAZOLINA)_(\d{2,4})__', lambda m: f"{m.group(1).replace('_',' ')} {m.group(2)}", texto, flags=re.IGNORECASE)

            if is_marketing_pdf:
                texto = re.sub(r'(?m)^\s*\d{1,2}\.\s*', '', texto)
                texto = re.sub(r'(?<=\s)\d{1,2}\.(?=\s)', ' ', texto)

            linhas = texto.split('\n')
            linhas_filtradas = []
            for ln in linhas:
                ln_strip = ln.strip()
                if padrao_ruido_linha.search(ln_strip):
                    continue
                ln_limpa = re.sub(r'\s{2,}', ' ', ln_strip).strip()
                if is_marketing_pdf and not re.search(r'[A-Za-zÁÉÍÓÚÂÊÔÃÕÇáéíóúâêôãõç]', ln_limpa):
                    continue
                if ln_limpa:
                    linhas_filtradas.append(ln_limpa)
                elif not linhas_filtradas or linhas_filtradas[-1] != "":
                    linhas_filtradas.append("")
            texto = "\n".join(linhas_filtradas)
            texto = re.sub(r'\n{3,}', '\n\n', texto)
            texto = re.sub(r'[ \t]+', ' ', texto)
            texto = texto.strip()

            return texto, None
    except Exception as e:
        return "", f"Erro ao ler o arquivo {tipo_arquivo}: {e}"

# ----------------- CORRIGE QUEBRAS EM TÍTULOS -----------------
def corrigir_quebras_em_titulos(texto):
    linhas = texto.split("\n")
    linhas_corrigidas = []
    buffer = ""
    for linha in linhas:
        linha_strip = linha.strip()
        if not linha_strip:
            if buffer:
                linhas_corrigidas.append(buffer)
                buffer = ""
            linhas_corrigidas.append("")
            continue
        is_potential_title = (linha_strip.isupper() and len(linha_strip) < 70) or re.match(r'^\d+\.', linha_strip)
        if is_potential_title:
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

# ----------------- DETECÇÃO DE TÍTULOS (COM SUPORTE A MULTILINE) -----------------
def is_titulo_secao(linha):
    ln = (linha or "").strip()
    if len(ln) < 4:
        return False
    if re.match(r'^\d+\.\s+[A-Z]', ln):
        return True
    if len(ln.split()) > 20:
        return False
    if ln.endswith('.') or ln.endswith(':'):
        return False
    if len(ln) > 120:
        return False
    if ln.isupper():
        return True
    upper_chars = sum(1 for c in ln if c.isupper())
    lower_chars = sum(1 for c in ln if c.islower())
    if upper_chars > lower_chars and lower_chars < 10:
        return True
    return False

def mapear_secoes(texto_completo, secoes_esperadas):
    """
    Agora detecta títulos que ocupam múltiplas linhas (considers contiguous uppercase lines as part
    of the same title). Stores 'num_linhas_titulo' > 1 and 'titulo_encontrado' as the joined lines.
    """
    mapa = []
    texto_normalizado = re.sub(r'\n{2,}', '\n', texto_completo or "")
    linhas = texto_normalizado.split('\n')
    aliases = obter_aliases_secao()

    titulos_possiveis = {}
    for sec in secoes_esperadas:
        titulos_possiveis[sec] = sec
    for alias, canon in aliases.items():
        if canon in secoes_esperadas:
            titulos_possiveis[alias] = canon

    titulos_norm_lookup = {normalizar_titulo_para_comparacao(t): c for t, c in titulos_possiveis.items()}
    limiar_score = 85

    idx = 0
    while idx < len(linhas):
        linha = linhas[idx].strip()
        if not linha:
            idx += 1
            continue
        if not is_titulo_secao(linha):
            idx += 1
            continue

        # collect possible multi-line title (lookahead)
        collected = [linha]
        j = idx + 1
        while j < len(linhas):
            next_ln = linhas[j].strip()
            if not next_ln:
                break
            # consider as continuation if uppercase and short
            if is_titulo_secao(next_ln) and len(next_ln) < 100:
                collected.append(next_ln)
                j += 1
                continue
            break

        titulo_candidato = " ".join(collected).strip()
        norm_linha = normalizar_titulo_para_comparacao(titulo_candidato)

        best_score = 0
        best_canonico = None
        for t_norm, canonico in titulos_norm_lookup.items():
            score = fuzz.token_set_ratio(t_norm, norm_linha)
            if score > best_score:
                best_score = score
                best_canonico = canonico

        if best_score < limiar_score:
            # contains fallback
            for t_norm, canonico in titulos_norm_lookup.items():
                if t_norm and t_norm in norm_linha:
                    best_score = 90
                    best_canonico = canonico
                    break

        if best_score >= limiar_score and best_canonico:
            num_lines = len(collected)
            titulo_encontrado = " ".join(collected)
            if not mapa or mapa[-1]['canonico'] != best_canonico:
                mapa.append({
                    'canonico': best_canonico,
                    'titulo_encontrado': titulo_encontrado,
                    'linha_inicio': idx,
                    'score': best_score,
                    'num_linhas_titulo': num_lines
                })
            idx = idx + num_lines
        else:
            idx += 1

    mapa.sort(key=lambda x: x['linha_inicio'])
    return mapa

# ----------------- OBTER DADOS DE SEÇÃO (INJEÇÃO DO TÍTULO MULTILINHA) -----------------
def obter_dados_secao(secao_canonico, mapa_secoes, linhas_texto_split):
    idx_secao_atual = -1
    for i, secao_mapa in enumerate(mapa_secoes):
        if secao_mapa['canonico'] == secao_canonico:
            idx_secao_atual = i
            break
    if idx_secao_atual == -1:
        return False, None, ""
    info = mapa_secoes[idx_secao_atual]
    titulo_encontrado = info['titulo_encontrado']
    linha_inicio = info['linha_inicio']
    num_linhas_titulo = info.get('num_linhas_titulo', 1)
    linha_inicio_conteudo = linha_inicio + num_linhas_titulo
    linha_fim = len(linhas_texto_split)
    if (idx_secao_atual + 1) < len(mapa_secoes):
        linha_fim = mapa_secoes[idx_secao_atual + 1]['linha_inicio']
    conteudo_lines = [linhas_texto_split[i] for i in range(linha_inicio_conteudo, linha_fim)]
    conteudo_sem_titulo = "\n".join(conteudo_lines).strip()
    # Injeta o título (multi-line já foi juntado em titulo_encontrado)
    if conteudo_sem_titulo:
        conteudo_final = f"{titulo_encontrado}\n\n{conteudo_sem_titulo}"
    else:
        conteudo_final = titulo_encontrado
    return True, titulo_encontrado, conteudo_final

# ----------------- EXTRAI QUALIFIERS INICIAIS (AGORA SÓ MOVEMOS "USO NASAL" + "ADULTO") -----------------
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
        # Conservative: only capture lines that contain both 'USO NASAL' and 'ADULTO' (in any order)
        ln_up = ln.upper()
        if 'USO NASAL' in ln_up and 'ADULTO' in ln_up:
            qualifiers.append(ln)
            i += 1
            continue
        # also accept if 'USO NASAL' and next line 'USO ADULTO' (split across lines)
        if 'USO NASAL' in ln_up and i+1 < len(linhas) and 'ADULTO' in linhas[i+1].upper():
            qualifiers.append(ln)
            qualifiers.append(linhas[i+1].strip())
            i += 2
            continue
        break
    restante = '\n'.join(linhas[i:]).strip()
    return qualifiers, restante

# ----------------- REALOCAR QUALIFIERS (MUITO RESTRITO: APENAS "USO NASAL ... ADULTO") -----------------
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

    # Move only if destination exists in MKT (safe)
    if not dst.get('encontrou_bel', False):
        return

    # Build qual text
    qual_text = ' '.join(q for q in qualifiers_bel if q.strip())
    if not qual_text:
        return

    # Avoid moving if qual_text looks like composition (contains 'contém', 'mg', etc.)
    if re.search(r'\b(?:cont[eé]m|mg\b|ml\b|equivalente|q\.s\.p|qsp)\b', qual_text, flags=re.IGNORECASE):
        return

    # Do not empty the source (safety)
    if len(restante_bel.strip()) < 30:
        return

    # Avoid duplicates
    dst_norm = normalizar_texto(dst.get('conteudo_bel', ""))
    if normalizar_texto(qual_text) in dst_norm:
        src['conteudo_bel'] = restante_bel
        return

    # Prepend qualifiers after destination title (destination title is first line of dst['conteudo_bel'])
    lines_dst = dst.get('conteudo_bel', "").split('\n')
    title_dst = lines_dst[0] if lines_dst and lines_dst[0].strip() else dst_section
    rest_dst = '\n'.join(lines_dst[1:]).strip() if len(lines_dst) > 1 else ""
    combined = f"{title_dst}\n\n{qual_text}\n\n{rest_dst}".strip()
    dst['conteudo_bel'] = combined
    src['conteudo_bel'] = restante_bel

# ----------------- VERIFICAÇÃO DE SEÇÕES E CONTEÚDO (APLICA REALOCAÇÃO RESTRITA) -----------------
def verificar_secoes_e_conteudo(texto_ref, texto_belfar, tipo_bula):
    secoes_esperadas = obter_secoes_por_tipo(tipo_bula)
    secoes_faltantes = []
    diferencas_titulos = []
    relatorio_comparacao_completo = []
    similaridade_geral = []
    secoes_ignorar_upper = [s.upper() for s in obter_secoes_ignorar_comparacao()]

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

    # Realocação restrita (apenas USO NASAL ... ADULTO)
    realocar_qualifiers_inplace(conteudos, src_section='COMPOSIÇÃO', dst_section='APRESENTAÇÕES')

    # Ao construir relatorio_comparacao_completo, se título encontrado no MKT for diferente do referência,
    # marcaremos o título do MKT com destaque amarelo (somente o título injetado, mantendo a fonte e cor).
    for sec in secoes_esperadas:
        item = conteudos[sec]
        encontrou_ref = item['encontrou_ref']
        encontrou_bel = item['encontrou_bel']
        conteudo_ref = item['conteudo_ref']
        conteudo_bel = item['conteudo_bel']
        titulo_ref = item.get('titulo_ref') or ""
        titulo_bel = item.get('titulo_bel') or ""

        # If titles differ, wrap the belfar injected title (first line) with a yellow mark while preserving style.
        if titulo_bel and titulo_ref and normalizar_titulo_para_comparacao(titulo_bel) != normalizar_titulo_para_comparacao(titulo_ref):
            # Only modify conteudo_bel if it starts with the injected title
            # We assume injected title is the first line (we injected it in obter_dados_secao)
            # Build styled title div (green for MKT)
            estilo_titulo_inline = "font-family: 'Georgia', 'Times New Roman', serif; font-weight:700; color: #0b8a3e; font-size:15px; margin-bottom:8px;"
            # preserve multiline title text
            titulo_html = f'<div style="{estilo_titulo_inline}"><mark style="background-color:#ffff99; padding:2px;">{titulo_bel}</mark></div>'
            # replace first occurrence of titulo_bel in conteudo_bel with titulo_html
            conteudo_bel = re.sub(re.escape(titulo_bel), titulo_html, conteudo_bel, count=1)
            item['conteudo_bel'] = conteudo_bel

        if not encontrou_bel:
            relatorio_comparacao_completo.append({
                'secao': sec,
                'status': 'faltante',
                'conteudo_ref': conteudo_ref,
                'conteudo_belfar': ""
            })
            continue

        if encontrou_ref and encontrou_bel:
            if sec.upper() in secoes_ignorar_upper:
                relatorio_comparacao_completo.append({
                    'secao': sec,
                    'status': 'identica',
                    'conteudo_ref': conteudo_ref,
                    'conteudo_belfar': conteudo_bel
                })
                similaridade_geral.append(100)
            else:
                if normalizar_texto(conteudo_ref) != normalizar_texto(conteudo_bel):
                    relatorio_comparacao_completo.append({
                        'secao': sec,
                        'status': 'diferente',
                        'conteudo_ref': conteudo_ref,
                        'conteudo_belfar': conteudo_bel
                    })
                    similaridade_geral.append(0)
                else:
                    relatorio_comparacao_completo.append({
                        'secao': sec,
                        'status': 'identica',
                        'conteudo_ref': conteudo_ref,
                        'conteudo_belfar': conteudo_bel
                    })
                    similaridade_geral.append(100)

    # Titles differences detection for reporting
    titulos_ref_encontrados = {m['canonico']: m['titulo_encontrado'] for m in mapa_ref}
    titulos_belfar_encontrados = {m['canonico']: m['titulo_encontrado'] for m in mapa_belfar}
    diferencas_titulos = []
    for secao_canonico, titulo_ref in titulos_ref_encontrados.items():
        if secao_canonico in titulos_belfar_encontrados:
            titulo_bel = titulos_belfar_encontrados[secao_canonico]
            if normalizar_titulo_para_comparacao(titulo_ref) != normalizar_titulo_para_comparacao(titulo_bel):
                diferencas_titulos.append({'secao_esperada': secao_canonico, 'titulo_encontrado': titulo_bel})

    return secoes_faltantes, relatorio_comparacao_completo, similaridade_geral, diferencas_titulos

# ----------------- MARCAÇÃO, ORTOGRAFIA E DIFERENÇAS (mantidas) -----------------
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
        vocab_referencia = set(re.findall(r'\b[a-záéíóúâêôãõçü]+\b', (texto_referencia or "").lower()))
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

# ----------------- FORMATAÇÃO PARA EXIBIÇÃO (mantida, usa títulos inline) -----------------
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
        "APRESENTAÇÕES", "APRESENTACOES", "APRESENTAÇÃO", "APRESENTACAO",
        "COMPOSIÇÃO", "COMPOSICAO", "DIZERES LEGAIS"
    ]
    def render_title(match):
        titulo_raw = match.group(0)
        titulo_limpo = re.sub(r'</?(?:mark|strong)[^>]*>', '', titulo_raw, flags=re.IGNORECASE)
        titulo_sem_num = re.sub(r'^\d+\.\s*', '', titulo_limpo).strip()
        return f'[[PARAGRAPH]]<div style="{estilo_titulo_inline}">{titulo_sem_num}</div>'
    for t in titulos_lista:
        html_content = re.sub(t, render_title, html_content, flags=re.IGNORECASE)
    html_content = re.sub(r'(\n)(\s*[-–•*])', r'[[LIST_ITEM]]\2', html_content)
    html_content = html_content.replace('\n', ' ')
    html_content = html_content.replace('[[PARAGRAPH]]', '<br><br>')
    html_content = html_content.replace('[[LIST_ITEM]]', '<br>')
    html_content = re.sub(r'(<br\s*/?>\s*){3,}', '<br><br>', html_content)
    html_content = re.sub(r'\s{2,}', ' ', html_content)
    return html_content

# ----------------- GERAÇÃO DE RELATÓRIO E UI (mantida com comportamento ajustado) -----------------
def gerar_relatorio_final(texto_ref, texto_belfar, nome_ref, nome_belfar, tipo_bula):
    st.header("Relatório de Auditoria Inteligente")
    secoes_faltantes, relatorio_comparacao_completo, similaridades, diferencas_titulos = verificar_secoes_e_conteudo(texto_ref, texto_belfar, tipo_bula)
    erros_ortograficos = checar_ortografia_inteligente(texto_belfar, texto_ref, tipo_bula)
    score = sum(similaridades) / len(similaridades) if similaridades else 100.0

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Conformidade de Conteúdo", f"{score:.0f}%")
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
    )

    for item in relatorio_comparacao_completo:
        sec = item['secao']
        status = item['status']
        conteudo_ref = item.get('conteudo_ref') or ""
        conteudo_bel = item.get('conteudo_belfar') or ""

        if status == 'diferente':
            with st.expander(f"📄 {sec} - ❌ CONTEÚDO DIVERGENTE"):
                c1, c2 = st.columns(2)
                with c1:
                    st.markdown("**Arquivo ANVISA:**")
                    st.markdown(f"<div style='{expander_caixa_style}'>{formatar_html_para_leitura(conteudo_ref, aplicar_numeracao=True)}</div>", unsafe_allow_html=True)
                with c2:
                    st.markdown("**Arquivo MKT:**")
                    st.markdown(f"<div style='{expander_caixa_style}'>{formatar_html_para_leitura(conteudo_bel, aplicar_numeracao=False)}</div>", unsafe_allow_html=True)
        else:
            with st.expander(f"📄 {sec} - ✅ CONTEÚDO IDÊNTICO" if status=='identica' else f"📄 {sec} - 🚨 FALTANTE"):
                c1, c2 = st.columns(2)
                with c1:
                    st.markdown("**Arquivo ANVISA:**")
                    st.markdown(f"<div style='{expander_caixa_style}'>{formatar_html_para_leitura(conteudo_ref, aplicar_numeracao=True)}</div>", unsafe_allow_html=True)
                with c2:
                    st.markdown("**Arquivo MKT:**")
                    st.markdown(f"<div style='{expander_caixa_style}'>{formatar_html_para_leitura(conteudo_bel, aplicar_numeracao=False)}</div>", unsafe_allow_html=True)

    st.divider()
    st.subheader("Visualização Lado a Lado")
    html_ref_bruto = marcar_divergencias_html(texto_ref or "", relatorio_comparacao_completo, [], tipo_bula, eh_referencia=True)
    html_bel_bruto = marcar_divergencias_html(texto_belfar or "", relatorio_comparacao_completo, erros_ortograficos, tipo_bula, eh_referencia=False)
    html_ref_marcado = formatar_html_para_leitura(html_ref_bruto, aplicar_numeracao=True)
    html_bel_marcado = formatar_html_para_leitura(html_bel_bruto, aplicar_numeracao=False)

    c1, c2 = st.columns(2, gap="large")
    with c1:
        st.markdown(f"**{nome_ref}**")
        st.markdown(f"<div style='max-height:700px; overflow-y:auto; border:1px solid #e8e8e8; padding:18px; font-family: Georgia, serif;'>{html_ref_marcado}</div>", unsafe_allow_html=True)
    with c2:
        st.markdown(f"**{nome_belfar}**")
        st.markdown(f"<div style='max-height:700px; overflow-y:auto; border:1px solid #e8e8e8; padding:18px; font-family: Georgia, serif;'>{html_bel_marcado}</div>", unsafe_allow_html=True)

    if erros_ortograficos:
        st.info("📝 Possíveis erros ortográficos: " + ", ".join(erros_ortograficos))

# ----------------- UI -----------------
st.set_page_config(layout="wide", page_title="Conferência MKT", page_icon="🔬")
st.title("🔬 Inteligência Artificial para Auditoria de Bulas")
st.markdown("Envie Arquivo ANVISA (.docx ou .pdf) e Arquivo MKT (.pdf).")

tipo = st.radio("Tipo de Bula:", ("Paciente","Profissional"), horizontal=True)
colA, colB = st.columns(2)
with colA:
    ref = st.file_uploader("Arquivo ANVISA (.docx ou .pdf)", type=["docx","pdf"], key="ref")
with colB:
    mkt = st.file_uploader("Arquivo MKT (.pdf)", type=["pdf"], key="mkt")

if st.button("🔍 Iniciar Auditoria"):
    if not (ref and mkt):
        st.warning("Envie ambos os arquivos.")
    else:
        with st.spinner("Processando..."):
            tipo_ref = 'docx' if ref.name.lower().endswith('.docx') else 'pdf'
            texto_ref, err_ref = extrair_texto(ref, tipo_ref, is_marketing_pdf=False)
            texto_mkt, err_mkt = extrair_texto(mkt, 'pdf', is_marketing_pdf=True)
            if err_ref or err_mkt:
                st.error(f"Erro leitura: {err_ref or err_mkt}")
            else:
                texto_ref = corrigir_quebras_em_titulos(texto_ref)
                texto_mkt = corrigir_quebras_em_titulos(texto_mkt)
                gerar_relatorio_final(texto_ref, texto_mkt, ref.name, mkt.name, tipo)

st.caption("Alterações: realocação restrita (USO NASAL + ADULTO) + destaque de títulos diferentes + suporte a títulos multi-linha. 'INFORMAÇÕES AO PACIENTE' foi removido das seções.")
