# --- IMPORTS ---
import streamlit as st
from style_utils import hide_streamlit_toolbar

hide_streamlit_toolbar()
import fitz  # PyMuPDF
import docx
import re
import spacy
from thefuzz import fuzz
from spellchecker import SpellChecker
import difflib
import unicodedata

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

# ----------------- EXTRAÇÃO (COM CORREÇÃO DE FORMATAÇÃO) -----------------
def extrair_texto(caminho_pdf):
    import fitz
    import re

    texto_extraido = ""

    with fitz.open(caminho_pdf) as pdf:
        for pagina in pdf:
            blocos = pagina.get_text("blocks")  # lê blocos em vez de texto corrido
            blocos_ordenados = sorted(blocos, key=lambda b: (b[1], b[0]))  # ordena por posição Y, depois X

            for bloco in blocos_ordenados:
                texto = bloco[4].strip()
                if texto:
                    texto_extraido += texto + "\n\n"  # adiciona espaçamento entre blocos

    # Remove espaços múltiplos e limpa quebras extras
    texto_extraido = re.sub(r"[ \t]+", " ", texto_extraido)
    texto_extraido = re.sub(r"\n{3,}", "\n\n", texto_extraido).strip()

    return texto_extraido


# ----------------- CONFIGURAÇÃO DE SEÇÕES -----------------
# (Funções obter_secoes_por_tipo, obter_aliases_secao, etc. - Sem alterações)
def obter_secoes_por_tipo(tipo_bula):
    secoes = {
        "Paciente": [
            "APRESENTAÇÕES", "COMPOSIÇÃO", "PARA QUE ESTE MEDICAMENTO É INDICADO",
            "COMO ESTE MEDICAMENTO FUNCIONA?", "QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?",
            "O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?",
            "ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?",
            "COMO DEVO USAR ESTE MEDICAMENTO?",
            "O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?",
            "QUAIS OS MALES QUE ESTE MEDICAMENTO PODE CAUSAR?",
            "O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?",
            "DIZERES LEGAIS"
        ],
        "Profissional": [
            "APRESENTAÇÕES", "COMPOSIÇÃO", "INDICAÇÕES", "RESULTADOS DE EFICÁCIA",
            "CARACTERÍSTICAS FARMACOLÓGICAS", "CONTRAINDICAÇÕES",
            "ADVERTÊNCIAS E PRECAUÇÕES", "INTERAÇÕES MEDICAMENTOSAS",
            "CUIDADOS DE ARMAZENAMENTO DO MEDICAMENTO", "POSOLOGIA E MODO DE USAR",
            "REAÇÕES ADVERSAS", "SUPERDOSE", "DIZERES LEGAIS"
        ]
    }
    return secoes.get(tipo_bula, [])

def obter_aliases_secao():
    return {
        "INDICAÇÕES": "PARA QUE ESTE MEDICAMENTO É INDICADO?",
        "CONTRAINDICAÇÕES": "QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?",
        "POSOLOGIA E MODO DE USAR": "COMO DEVO USAR ESTE MEDICAMENTO?",
        "REAÇÕES ADVERSAS": "QUAIS OS MALES QUE ESTE MEDICAMENTO PODE CAUSAR?",
        "SUPERDOSE": "O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?",
        "CUIDADOS DE ARMAZENAMENTO DO MEDICAMENTO": "ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?"
    }

def obter_secoes_ignorar_ortografia():
    return ["COMPOSIÇÃO", "DIZERES LEGAIS"]

def obter_secoes_ignorar_comparacao():
    return ["COMPOSIÇÃO", "DIZERES LEGAIS"]


# ----------------- NORMALIZAÇÃO -----------------
# (Funções normalizar_texto, normalizar_titulo_para_comparacao - Sem alterações)
def normalizar_texto(texto):
    texto = ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')
    texto = re.sub(r'[^\w\s]', '', texto)
    texto = ' '.join(texto.split())
    return texto.lower()

def normalizar_titulo_para_comparacao(texto):
    """Normalização robusta para títulos, removendo acentos, pontuação e numeração inicial."""
    texto_norm = normalizar_texto(texto)
    texto_norm = re.sub(r'^\d+\s*[\.\-)]*\s*', '', texto_norm).strip()
    return texto_norm


# ----------------- ARQUITETURA DE MAPEAMENTO DE SEÇÕES -----------------
# (Funções is_titulo_secao, mapear_secoes, obter_dados_secao - Sem alterações significativas na lógica principal, apenas usando a versão mais recente que lida com títulos de 1 ou 2 linhas)
def is_titulo_secao(linha):
    """Retorna True se a linha for um possível título de seção puro."""
    linha = linha.strip()
    if len(linha) < 4 or len(linha.split()) > 12: # Títulos muito curtos ou longos demais
        return False
    if linha.endswith('.') or linha.endswith(':'): # Títulos geralmente não terminam com . ou :
        return False
    # Evita linhas que parecem ser parte de tabelas ou formatação estranha
    if re.search(r'\s{3,}', linha): # Mais de 2 espaços seguidos
         return False
    if len(linha) > 100: # Limite de caracteres para segurança
        return False
    # Verifica se a linha está toda em maiúsculas (forte indicativo de título)
    # ou se tem capitalização de título (maioria das palavras começa com maiúscula)
    if linha.isupper():
         return True
    # Heurística mais complexa pode ser necessária aqui se os títulos não forem consistentes
    # Por exemplo, verificar se poucas palavras são minúsculas (exceto artigos, preposições)
    return False # Default mais conservador se não for claramente um título


def mapear_secoes(texto_completo, secoes_esperadas):
    mapa = []
    linhas = texto_completo.split('\n')
    aliases = obter_aliases_secao()
    
    titulos_possiveis = {}
    for secao in secoes_esperadas:
        titulos_possiveis[secao] = secao
    for alias, canonico in aliases.items():
        if canonico in secoes_esperadas:
            titulos_possiveis[alias] = canonico

    idx = 0
    while idx < len(linhas):
        linha_limpa = linhas[idx].strip()

        # Pula linhas vazias
        if not linha_limpa:
            idx += 1
            continue

        # --- LÓGICA DE DETECÇÃO DE TÍTULO DE 1 OU 2 LINHAS ---
        best_match_score_1_linha = 0
        best_match_canonico_1_linha = None
        # Verifica apenas se a linha atual parece um título
        if is_titulo_secao(linha_limpa):
            for titulo_possivel, titulo_canonico in titulos_possiveis.items():
                score = fuzz.token_set_ratio(normalizar_titulo_para_comparacao(titulo_possivel), normalizar_titulo_para_comparacao(linha_limpa))
                if score > best_match_score_1_linha:
                    best_match_score_1_linha = score
                    best_match_canonico_1_linha = titulo_canonico

        best_match_score_2_linhas = 0
        best_match_canonico_2_linhas = None
        titulo_combinado = ""
        # Verifica a combinação com a próxima linha APENAS se a linha atual parece título e a próxima também (ou é curta)
        if is_titulo_secao(linha_limpa) and (idx + 1) < len(linhas):
            linha_seguinte = linhas[idx + 1].strip()
            # Condição para considerar a próxima linha como parte do título: ser curta ou parecer título também
            if linha_seguinte and (len(linha_seguinte.split()) < 5 or is_titulo_secao(linha_seguinte)):
                titulo_combinado = f"{linha_limpa} {linha_seguinte}"
                for titulo_possivel, titulo_canonico in titulos_possiveis.items():
                    score = fuzz.token_set_ratio(normalizar_titulo_para_comparacao(titulo_possivel), normalizar_titulo_para_comparacao(titulo_combinado))
                    if score > best_match_score_2_linhas:
                        best_match_score_2_linhas = score
                        best_match_canonico_2_linhas = titulo_canonico
        
        limiar_score = 90 # Reduzido ligeiramente para mais flexibilidade
        
        # Prioriza match de 2 linhas se for significativamente melhor E acima do limiar
        if best_match_score_2_linhas > best_match_score_1_linha + 5 and best_match_score_2_linhas >= limiar_score:
            if not mapa or mapa[-1]['canonico'] != best_match_canonico_2_linhas: # Evita duplicatas
                mapa.append({
                    'canonico': best_match_canonico_2_linhas,
                    'titulo_encontrado': titulo_combinado,
                    'linha_inicio': idx,
                    'score': best_match_score_2_linhas,
                    'num_linhas_titulo': 2
                })
            idx += 2 # Pula as duas linhas do título
        # Senão, usa o match de 1 linha se for bom o suficiente
        elif best_match_score_1_linha >= limiar_score:
             if not mapa or mapa[-1]['canonico'] != best_match_canonico_1_linha: # Evita duplicatas
                mapa.append({
                    'canonico': best_match_canonico_1_linha,
                    'titulo_encontrado': linha_limpa,
                    'linha_inicio': idx,
                    'score': best_match_score_1_linha,
                    'num_linhas_titulo': 1
                })
             idx += 1 # Pula a linha do título
        # Se nenhum match for bom, apenas avança
        else:
            idx += 1 
            
    mapa.sort(key=lambda x: x['linha_inicio'])
    return mapa


def obter_dados_secao(secao_canonico, mapa_secoes, linhas_texto, tipo_bula):
    """
    Extrai o conteúdo de uma seção baseado no mapa, indo até o início da próxima seção mapeada.
    """
    conteudo_final = ""
    titulo_encontrado = None
    encontrou = False

    for i, secao_mapa in enumerate(mapa_secoes):
        if secao_mapa['canonico'] == secao_canonico:
            encontrou = True
            titulo_encontrado = secao_mapa['titulo_encontrado']
            # Linha onde o conteúdo começa (logo após o título, que pode ter 1 ou 2 linhas)
            linha_inicio_conteudo = secao_mapa['linha_inicio'] + secao_mapa.get('num_linhas_titulo', 1) 

            # Determina a linha final (início da próxima seção mapeada ou fim do texto)
            linha_fim = len(linhas_texto) # Padrão é ir até o fim do documento
            if i + 1 < len(mapa_secoes):
                # A próxima seção começa na linha 'linha_inicio' dela
                linha_fim = mapa_secoes[i+1]['linha_inicio']

            # Extrai as linhas de conteúdo entre o fim do título e o início da próxima seção
            # Remove linhas que são apenas espaços em branco
            conteudo_linhas = [linhas_texto[idx] for idx in range(linha_inicio_conteudo, linha_fim) if linhas_texto[idx].strip()]
            conteudo_final = "\n".join(conteudo_linhas).strip() # Usa \n simples e strip no final
            break # Encontrou a seção desejada, pode parar o loop

    return encontrou, titulo_encontrado, conteudo_final


# ----------------- COMPARAÇÃO DE CONTEÚDO -----------------
# (Função verificar_secoes_e_conteudo - Lógica principal mantida)
def verificar_secoes_e_conteudo(texto_ref, texto_belfar, tipo_bula):
    secoes_esperadas = obter_secoes_por_tipo(tipo_bula)
    secoes_faltantes, diferencas_conteudo, similaridades_secoes, diferencas_titulos = [], [], [], []
    secoes_ignorar_upper = [s.upper() for s in obter_secoes_ignorar_comparacao()]

    linhas_ref = texto_ref.split('\n')
    linhas_belfar = texto_belfar.split('\n')
    mapa_ref = mapear_secoes(texto_ref, secoes_esperadas)
    mapa_belfar = mapear_secoes(texto_belfar, secoes_esperadas)

    for secao in secoes_esperadas:
        encontrou_ref, _, conteudo_ref = obter_dados_secao(secao, mapa_ref, linhas_ref, tipo_bula)
        encontrou_belfar, titulo_belfar_encontrado, conteudo_belfar = obter_dados_secao(secao, mapa_belfar, linhas_belfar, tipo_bula)

        if not encontrou_belfar:
            secoes_faltantes.append(secao)
            continue # Se não encontrou no Belfar, não há o que comparar

        # Compara títulos apenas se ambos foram encontrados
        # Procura o título correspondente na referência para comparação
        titulo_ref_encontrado = None
        for item_mapa_ref in mapa_ref:
            if item_mapa_ref['canonico'] == secao:
                titulo_ref_encontrado = item_mapa_ref['titulo_encontrado']
                break
        
        if titulo_ref_encontrado and titulo_belfar_encontrado:
             if normalizar_titulo_para_comparacao(titulo_ref_encontrado) != normalizar_titulo_para_comparacao(titulo_belfar_encontrado):
                 # Adiciona apenas se ainda não foi adicionado por outra lógica
                 if not any(d['secao_esperada'] == secao for d in diferencas_titulos):
                      diferencas_titulos.append({'secao_esperada': secao, 'titulo_encontrado': titulo_belfar_encontrado})


        # Compara conteúdo se ambos foram encontrados e a seção não deve ser ignorada
        if encontrou_ref and secao.upper() not in secoes_ignorar_upper:
            # Normalização antes da comparação para ignorar espaços extras e maiúsculas/minúsculas
            norm_ref = ' '.join(normalizar_texto(conteudo_ref).split())
            norm_belfar = ' '.join(normalizar_texto(conteudo_belfar).split())
            if norm_ref != norm_belfar:
                diferencas_conteudo.append({'secao': secao, 'conteudo_ref': conteudo_ref, 'conteudo_belfar': conteudo_belfar})
                similaridades_secoes.append(0)
            else:
                similaridades_secoes.append(100)
        # Se encontrou na ref mas seção é ignorada OU não encontrou na ref, considera 100% (pois não há comparação a fazer)
        elif encontrou_belfar: 
             similaridades_secoes.append(100)


    return secoes_faltantes, diferencas_conteudo, similaridades_secoes, diferencas_titulos


# ----------------- ORTOGRAFIA (COM "CONTATO" IGNORADO) -----------------
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
                texto_filtrado_para_checar.append(conteudo) # Adiciona todo o conteúdo da seção

        texto_final_para_checar = '\n\n'.join(texto_filtrado_para_checar) # Usa join com \n\n para separar seções
        
        if not texto_final_para_checar:
            return []

        spell = SpellChecker(language='pt')
        
        # Palavra "contato" adicionada aqui
        palavras_a_ignorar = {"alair", "belfar", "peticionamento", "urotrobel", "contato"}
        
        # Adiciona palavras do texto de referência ao dicionário
        vocab_referencia = set(re.findall(r'\b[a-záéíóúâêôãõçü]+\b', texto_referencia.lower()))
        # Adiciona entidades nomeadas (como nomes de remédios, locais) ao dicionário
        doc = nlp(texto_para_checar) 
        entidades = {ent.text.lower() for ent in doc.ents}

        # Carrega palavras customizadas no verificador
        spell.word_frequency.load_words(
            vocab_referencia.union(entidades).union(palavras_a_ignorar)
        )

        # Encontra palavras no texto a checar
        palavras = re.findall(r'\b[a-záéíóúâêôãõçü]+\b', texto_final_para_checar.lower())
        # Identifica as desconhecidas (possíveis erros)
        erros = spell.unknown(palavras)
        # Filtra erros curtos e retorna uma lista limitada e ordenada
        return list(sorted(set([e for e in erros if len(e) > 3])))[:20]

    except Exception as e:
        # Em caso de erro na verificação, retorna lista vazia para não travar
        print(f"Erro na checagem de ortografia: {e}") # Log do erro (opcional)
        return []


# ----------------- DIFERENÇAS PALAVRA A PALAVRA -----------------
# (Função marcar_diferencas_palavra_por_palavra - Sem alterações)
def marcar_diferencas_palavra_por_palavra(texto_ref, texto_belfar, eh_referencia):
    def tokenizar(txt):
        # Captura quebras de linha ou sequências de não-espaços ou um único caractere não alfanumérico
        return re.findall(r'\n|\S+|[^\w\s]', txt, re.UNICODE)

    def norm(tok):
        # Normaliza apenas se for uma palavra (contém letra ou número)
        if re.search(r'\w', tok):
            # Remove acentos, pontuação interna e converte para minúsculas
            normalized = ''.join(c for c in unicodedata.normalize('NFD', tok) if unicodedata.category(c) != 'Mn')
            normalized = re.sub(r'[^\w]', '', normalized) # Remove qualquer coisa que não seja letra/número
            return normalized.lower()
        return tok # Mantém pontuação e quebras de linha como estão para comparação

    ref_tokens = tokenizar(texto_ref)
    bel_tokens = tokenizar(texto_belfar)
    ref_norm = [norm(t) for t in ref_tokens]
    bel_norm = [norm(t) for t in bel_tokens]

    matcher = difflib.SequenceMatcher(None, ref_norm, bel_norm, autojunk=False)
    indices = set()
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != 'equal':
            # Marca os índices correspondentes no texto original (ref ou bel)
            indices_para_marcar = range(i1, i2) if eh_referencia else range(j1, j2)
            # Adiciona apenas índices de tokens que não são apenas espaços em branco
            tokens_originais = ref_tokens if eh_referencia else bel_tokens
            indices.update(idx for idx in indices_para_marcar if tokens_originais[idx].strip())


    tokens = ref_tokens if eh_referencia else bel_tokens
    marcado = []
    for idx, tok in enumerate(tokens):
        # Marca apenas se o índice estiver no set e o token não for só espaço
        if idx in indices and tok.strip():
            marcado.append(f"<mark style='background-color: #ffff99; padding: 2px;'>{tok}</mark>")
        else:
            marcado.append(tok)

    # Reconstrução cuidadosa do texto
    resultado = ""
    for i, tok in enumerate(marcado):
        raw_tok_atual = re.sub(r'<[^>]+>', '', tok) # Token sem tags HTML

        # Se for o primeiro token, apenas adiciona
        if i == 0:
            resultado += tok
            continue

        raw_tok_anterior = re.sub(r'<[^>]+>', '', marcado[i-1]) # Token anterior sem tags

        # Não adiciona espaço antes se:
        # 1. O token atual é pontuação (e não é uma palavra entre <mark>)
        # 2. O token anterior foi uma quebra de linha
        # 3. O token atual é uma quebra de linha
        # 4. O token anterior foi um parêntese de abertura
        if (re.match(r'^[^\w\s]$', raw_tok_atual) and not raw_tok_atual.isalnum()) or \
           raw_tok_anterior == '\n' or raw_tok_atual == '\n' or raw_tok_anterior == '(':
            resultado += tok
        else:
            resultado += " " + tok # Adiciona espaço na maioria dos casos

    # Remove espaço antes de pontuações específicas (pós-processamento)
    resultado = re.sub(r'\s+([.,;:!?)])', r'\1', resultado)
    # Remove espaço depois de abrir parênteses
    resultado = re.sub(r'(\()\s+', r'\1', resultado)
    # Garante um único espaço entre tags de marcação adjacentes
    resultado = re.sub(r'(</mark>)\s+(<mark)', r'\1 \2', resultado)
    # Remove espaços duplos que possam ter surgido
    resultado = re.sub(r' {2,}', ' ', resultado)

    return resultado.strip()


# ----------------- MARCAÇÃO GERAL HTML (DIVERGÊNCIAS, ORTOGRAFIA, ANVISA) -----------------
# (Função marcar_divergencias_html - Sem alterações)
def marcar_divergencias_html(texto_original, secoes_problema, erros_ortograficos, tipo_bula, eh_referencia=False):
    texto_trabalho = texto_original
    
    # Marca divergências de conteúdo (Amarelo)
    if secoes_problema:
        # Ordena por posição de início para evitar sobreposição incorreta
        secoes_problema.sort(key=lambda x: texto_original.find(x['conteudo_ref'] if eh_referencia else x['conteudo_belfar']) if (x['conteudo_ref'] if eh_referencia else x['conteudo_belfar']) in texto_original else float('inf'))

        offset = 0 # Ajuste de offset para lidar com mudanças no tamanho do texto devido às tags HTML
        texto_processado_temp = list(texto_trabalho) # Converte para lista para inserção de tags

        for diff in secoes_problema:
            conteudo_ref = diff['conteudo_ref']
            conteudo_belfar = diff['conteudo_belfar']
            conteudo_a_buscar = conteudo_ref if eh_referencia else conteudo_belfar

            # Busca o conteúdo original no texto atual (que pode já ter tags)
            # A busca precisa ser feita no texto original para obter os índices corretos
            start_index = texto_original.find(conteudo_a_buscar)

            if start_index != -1 and conteudo_a_buscar: # Procede apenas se encontrar e não for vazio
                end_index = start_index + len(conteudo_a_buscar)

                # Gera o conteúdo com as marcações internas de palavra a palavra
                conteudo_marcado_interno = marcar_diferencas_palavra_por_palavra(
                    conteudo_ref, 
                    conteudo_belfar, 
                    eh_referencia
                )

                # Substitui no texto original usando os índices + offset
                # Esta parte é complexa devido à modificação da string. Uma abordagem mais segura seria
                # reconstruir a string com as marcações. Vamos simplificar por enquanto.
                # A substituição simples pode falhar se o mesmo texto aparecer múltiplas vezes.
                # Tenta substituir apenas a primeira ocorrência para mitigar.
                try:
                     # A substituição direta é arriscada se o conteúdo já foi alterado.
                     # Vamos usar replace com contagem 1 por enquanto.
                     if conteudo_a_buscar in texto_trabalho:
                          texto_trabalho = texto_trabalho.replace(conteudo_a_buscar, conteudo_marcado_interno, 1)
                except Exception as e:
                     print(f"Erro ao substituir conteúdo divergente: {e}") # Log para debug


    # Marca erros ortográficos (Rosa) - Apenas no texto Belfar
    if erros_ortograficos and not eh_referencia:
        # Ordena erros do maior para o menor para evitar substituições parciais (ex: marcar "casa" antes de "casamento")
        erros_ortograficos_sorted = sorted(erros_ortograficos, key=len, reverse=True)
        for erro in erros_ortograficos_sorted:
            # Regex para encontrar a palavra inteira, ignorando case, e evitando marcar dentro de tags HTML ou palavras já marcadas
            # (?<!...) são lookbehinds negativos para garantir que não estamos dentro de uma tag ou outra marcação
            pattern = r'(?<![<>a-zA-Z])(?<!mark style=\'background-color: #FFDDC1; padding: 2px;\'>)(?<!;>)\b(' + re.escape(erro) + r')\b(?![<>])(?!\s*</mark>)'
            
            # Função de substituição para preservar a capitalização original
            def replace_case_insensitive(match):
                original_word = match.group(1)
                return f"<mark style='background-color: #FFDDC1; padding: 2px;'>{original_word}</mark>"

            try:
                texto_trabalho = re.sub(
                    pattern,
                    replace_case_insensitive, # Usa a função para manter capitalização
                    texto_trabalho,
                    flags=re.IGNORECASE 
                )
            except Exception as e:
                print(f"Erro ao marcar erro ortográfico '{erro}': {e}") # Log para debug

    # Marca data ANVISA (Azul)
    regex_anvisa = r"((?:aprovad[ao]\s+pela\s+anvisa\s+em|data\s+de\s+aprovação\s+na\s+anvisa:)\s*[\d]{1,2}/[\d]{1,2}/[\d]{2,4})"
    
    # Função para aplicar a marcação na data ANVISA, evitando remarcar se já estiver dentro de outra tag
    def replace_anvisa(match):
        full_match_text = match.group(0)
        # Verifica se o texto já contém alguma tag <mark> - simples verificação
        if "<mark" in full_match_text:
             return full_match_text # Retorna o original se já parece marcado
        else:
             frase_anvisa = match.group(1)
             return full_match_text.replace(frase_anvisa, f"<mark style='background-color: #cce5ff; padding: 2px; font-weight: 500;'>{frase_anvisa}</mark>")

    try:
        # Usa re.sub com uma função para aplicar a lógica de verificação
        texto_trabalho = re.sub(regex_anvisa, replace_anvisa, texto_trabalho, count=1, flags=re.IGNORECASE)
    except Exception as e:
        print(f"Erro ao marcar data ANVISA: {e}") # Log para debug

    return texto_trabalho


# ----------------- RELATÓRIO (COM VISUALIZAÇÃO LADO A LADO MELHORADA) -----------------
def gerar_relatorio_final(texto_ref, texto_belfar, nome_ref, nome_belfar, tipo_bula):
    st.header("Relatório de Auditoria Inteligente")
    regex_anvisa = r"(aprovad[ao]\s+pela\s+anvisa\s+em|data\s+de\s+aprovação\s+na\s+anvisa:)\s*([\d]{1,2}/[\d]{1,2}/[\d]{2,4})"
    match_ref = re.search(regex_anvisa, texto_ref.lower())
    match_belfar = re.search(regex_anvisa, texto_belfar.lower())
    data_ref = match_ref.group(2).strip() if match_ref else "Não encontrada"
    data_belfar = match_belfar.group(2).strip() if match_belfar else "Não encontrada"

    secoes_faltantes, diferencas_conteudo, similaridades, diferencas_titulos = verificar_secoes_e_conteudo(texto_ref, texto_belfar, tipo_bula)
    erros_ortograficos = checar_ortografia_inteligente(texto_belfar, texto_ref, tipo_bula) 
    score_similaridade_conteudo = sum(similaridades) / len(similaridades) if similaridades else 100.0

    st.subheader("Dashboard de Veredito")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Conformidade de Conteúdo", f"{score_similaridade_conteudo:.0f}%")
    col2.metric("Erros Ortográficos", len(erros_ortograficos))
    col3.metric("Data ANVISA (Belfar)", data_belfar)
    col4.metric("Seções Faltantes", f"{len(secoes_faltantes)}")

    st.divider()
    st.subheader("Detalhes dos Problemas Encontrados")
    st.info(f"ℹ️ **Datas de Aprovação ANVISA:**\n    - Referência: {data_ref}\n    - Belfar: {data_belfar}") # Removido backticks para consistência

    if secoes_faltantes:
        st.error(f"🚨 **Seções faltantes na bula Belfar ({len(secoes_faltantes)})**:\n" + "\n".join([f"    - {s}" for s in secoes_faltantes]))
    else:
        st.success("✅ Todas as seções obrigatórias estão presentes")
    
    # Exibe diferenças de títulos encontradas
    if diferencas_titulos:
         st.warning(f"⚠️ **Títulos de seção divergentes ou remapeados ({len(diferencas_titulos)}):**")
         for dt in diferencas_titulos:
              st.markdown(f"   - Seção Esperada: **{dt['secao_esperada']}** | Título Encontrado: _{dt['titulo_encontrado']}_")

    if diferencas_conteudo:
        st.warning(f"⚠️ **Diferenças de conteúdo encontradas ({len(diferencas_conteudo)} seções):**")
        
        # Estilo para os expanders de diferença de conteúdo
        expander_caixa_style = (
            "max-height: 400px; overflow-y: auto; border: 1px solid #ddd; border-radius: 6px; " # max-height em vez de height
            "padding: 12px; background-color: #fafafa; font-size: 14px; line-height: 1.7; "
            "font-family: sans-serif; text-align: left;" # Alinhamento à esquerda
        )

        for diff in diferencas_conteudo:
            # Usa o título canônico (esperado) no expander para consistência
            with st.expander(f"📄 {diff['secao']} - Conteúdo Divergente"):
                # Marca as palavras diferentes dentro do expander também
                expander_html_ref = marcar_diferencas_palavra_por_palavra(
                    diff['conteudo_ref'], diff['conteudo_belfar'], eh_referencia=True
                ).replace('\n', '<br>')
                
                expander_html_belfar = marcar_diferencas_palavra_por_palavra(
                    diff['conteudo_ref'], diff['conteudo_belfar'], eh_referencia=False
                ).replace('\n', '<br>')

                c1, c2 = st.columns(2)
                with c1:
                    st.markdown("**Referência:**")
                    st.markdown(f"<div style='{expander_caixa_style}'>{expander_html_ref}</div>", unsafe_allow_html=True)
                with c2:
                    st.markdown("**Belfar:**")
                    st.markdown(f"<div style='{expander_caixa_style}'>{expander_html_belfar}</div>", unsafe_allow_html=True)
    elif not secoes_faltantes: # Só mostra sucesso se não houver seções faltantes também
        st.success("✅ Conteúdo das seções está idêntico")

    if erros_ortograficos:
        st.info(f"📝 **Possíveis erros ortográficos ({len(erros_ortograficos)} palavras):**\n" + ", ".join(erros_ortograficos))

    # Mensagem de aprovação final
    if not any([secoes_faltantes, diferencas_conteudo, diferencas_titulos]) and len(erros_ortograficos) < 5: # Condição ajustada
        st.success("🎉 **Bula aprovada!** Nenhum problema crítico encontrado.")

    # --- INÍCIO DA VISUALIZAÇÃO LADO A LADO MELHORADA ---
    st.divider()
    st.subheader("Visualização Lado a Lado com Destaques")
    
    legend_style = (
        "font-size: 14px; "
        "background-color: #f0f2f6; "  # Cor de fundo suave
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

    # Prepara o HTML com todas as marcações para a visualização final
    html_ref_marcado = marcar_divergencias_html(texto_original=texto_ref, secoes_problema=diferencas_conteudo, erros_ortograficos=[], tipo_bula=tipo_bula, eh_referencia=True).replace('\n', '<br>')
    html_belfar_marcado = marcar_divergencias_html(texto_original=texto_belfar, secoes_problema=diferencas_conteudo, erros_ortograficos=erros_ortograficos, tipo_bula=tipo_bula, eh_referencia=False).replace('\n', '<br>')

    caixa_style = (
        "max-height: 700px; "  # Altura máxima
        "overflow-y: auto; "
        "border: 1px solid #e0e0e0; "  # Borda suave
        "border-radius: 8px; "  # Cantos arredondados
        "padding: 20px 24px; "  # Padding
        "background-color: #ffffff; "
        "font-size: 15px; "  # Fonte maior
        "line-height: 1.7; "  # Espaçamento
        "box-shadow: 0 4px 12px rgba(0,0,0,0.08); "  # Sombra suave
        "text-align: left; "  # Alinhamento à esquerda
    )
    
    col1, col2 = st.columns(2, gap="medium")
    with col1:
        st.markdown(f"#### {nome_ref}") # Título H4
        st.markdown(f"<div style='{caixa_style}'>{html_ref_marcado}</div>", unsafe_allow_html=True)
    with col2:
        st.markdown(f"#### {nome_belfar}") # Título H4
        st.markdown(f"<div style='{caixa_style}'>{html_belfar_marcado}</div>", unsafe_allow_html=True)
    
    # --- FIM DA VISUALIZAÇÃO LADO A LADO MELHORADA ---

# ----------------- INTERFACE -----------------
st.set_page_config(layout="wide", page_title="Auditoria de Bulas", page_icon="🔬")
st.title("🔬 Inteligência Artificial para Auditoria de Bulas")
st.markdown("Sistema avançado de comparação literal e validação de bulas farmacêuticas")
st.divider()

st.header("📋 Configuração da Auditoria")
tipo_bula_selecionado = st.radio("Tipo de Bula:", ("Paciente", "Profissional"), horizontal=True)
col1, col2 = st.columns(2)
with col1:
    st.subheader("📄 Arquivo da Anvisa") # Mantido do seu último código
    pdf_ref = st.file_uploader("Envie o arquivo da Anvisa (.docx ou .pdf)", type=["docx", "pdf"], key="ref") # Mantido
with col2:
    st.subheader("📄 Arquivo Marketing") # Mantido
    pdf_belfar = st.file_uploader("Envie o PDF do Marketing", type="pdf", key="belfar") # Mantido

if st.button("🔍 Iniciar Auditoria Completa", use_container_width=True, type="primary"):
    if pdf_ref and pdf_belfar:
        with st.spinner("🔄 Processando e analisando as bulas..."):
            
            # Determina dinamicamente o tipo de arquivo da Anvisa
            tipo_arquivo_ref = 'docx' if pdf_ref.name.lower().endswith('.docx') else 'pdf'
            texto_ref, erro_ref = extrair_texto(pdf_ref, tipo_arquivo_ref)
            
            texto_belfar, erro_belfar = extrair_texto(pdf_belfar, 'pdf')

            if not erro_ref:
                texto_ref = truncar_apos_anvisa(texto_ref)
            if not erro_belfar:
                texto_belfar = truncar_apos_anvisa(texto_belfar)

            if erro_ref or erro_belfar:
                st.error(f"Erro ao processar arquivos: {erro_ref or erro_belfar}") # Corrigido erro de variável
            else:
                gerar_relatorio_final(texto_ref, texto_belfar, "Arquivo da Anvisa", "Arquivo Marketing", tipo_bula_selecionado) # Mantido
    else:
        st.warning("⚠️ Por favor, envie ambos os arquivos para iniciar a auditoria.")

st.divider()
st.caption("Sistema de Auditoria de Bulas v18.0 | Arquitetura de Mapeamento Final")
