# ----------------- EXTRAÇÃO -----------------
def extrair_texto(arquivo, tipo_arquivo):
    if arquivo is None:
        return "", f"Arquivo {tipo_arquivo} não enviado."
    try:
        arquivo.seek(0)
        texto = ""
        if tipo_arquivo == 'pdf':
            full_text_list = []
            
            # --- MUDANÇA 4: CORRIGIDO O "MEIO" DA PÁGINA ---
            # O corte agora é feito exatamente em 50% (ao "meio")
            # como você indicou.
            with fitz.open(stream=arquivo.read(), filetype="pdf") as doc:
                for page in doc:
                    rect = page.rect
                    
                    # Define a coluna da esquerda (do início até o meio)
                    clip_esquerda = fitz.Rect(0, 0, rect.width / 2, rect.height)
                    
                    # Define a coluna da direita (do meio até o fim)
                    clip_direita = fitz.Rect(rect.width / 2, 0, rect.width, rect.height)

                    # 1. Extrai o texto da coluna da ESQUERDA primeiro
                    texto_esquerda = page.get_text("text", clip=clip_esquerda, sort=True)
                    
                    # 2. Extrai o texto da coluna da DIREITA depois
                    texto_direita = page.get_text("text", clip=clip_direita, sort=True)
                    
                    # 3. Junta as duas colunas na ordem correta
                    full_text_list.append(texto_esquerda)
                    full_text_list.append(texto_direita)
                    
            texto = "\n\n".join(full_text_list) # \n\n para separar colunas/páginas
        
        elif tipo_arquivo == 'docx':
            doc = docx.Document(arquivo)
            texto = "\n".join([p.text for p in doc.paragraphs])
        
        if texto:
            caracteres_invisiveis = ['\u00AD', '\u200B', '\u200C', '\u200D', '\uFEFF']
            for char in caracteres_invisiveis:
                texto = texto.replace(char, '')
            texto = texto.replace('\r\n', '\n').replace('\r', '\n')
            texto = texto.replace('\u00A0', ' ')
            texto = re.sub(r'(\w+)-\n(\w+)', r'\1\2', texto, flags=re.IGNORECASE)
            
            linhas = texto.split('\n')
            
            # --- FILTRO DE RUÍDO APRIMORADO ---
            # Adiciona os novos ruídos (REZA, GEM) e melhora a detecção
            # de "Medida da bula" etc., mesmo com erros de digitação.
            padrao_ruido_linha = re.compile(
                r'bula do paciente|página \d+\s*de\s*\d+'  # Rodapé padrão
                r'|(Tipologie|Tipologia) da bula:.*|(Merida|Medida) da (bula|trúa):?.*' # Ruído do MKT (com erros)
                r'|(Impressãe|Impressão):? Frente/Verso|Papel[\.:]? Ap \d+gr' # Ruído do MKT (com erros)
                r'|Cor:? Preta|contato:?|artes@belfar\.com\.br' # Ruído do MKT
                r'|BUL_CLORIDRATO_DE_NAFAZOLINA_BUL\d+V\d+' # Nome do arquivo
                r'|CLORIDRATO DE NAFAZOLINA: Times New Roman' # Ruído do MKT
                r'|^\s*FRENTE\s*$|^\s*VERSO\s*$' # Indicador de página
                r'|^\s*\d+\s*mm\s*$' # Medidas (ex: 190 mm, 300 mm)
                r'|^\s*-\s*Normal e Negrito\. Corpo \d+\s*$' # Linha de formatação
                r'|^\s*BELFAR\s*$|^\s*REZA\s*$|^\s*GEM\s*$|^\s*ALTEFAR\s*$|^\s*RECICLAVEL\s*$|^\s*BUL\d+\s*$' # Ruído do rodapé
            , re.IGNORECASE)
            
            linhas_filtradas = []
            for linha in linhas:
                linha_strip = linha.strip()
                # Remove linhas de ruído E linhas muito curtas (lixo de extração)
                # Mantém a exceção para títulos curtos (ex: USO NASAL)
                if not padrao_ruido_linha.search(linha_strip):
                    if len(linha_strip) > 1 or (len(linha_strip) == 1 and linha_strip.isdigit()):
                        # --- [AQUI ESTÁ A CORREÇÃO] ---
                        # Salvamos a 'linha' original (com espaços)
                        # e não a 'linha_strip' (sem espaços)
                        linhas_filtradas.append(linha) 
                    elif linha_strip.isupper() and len(linha_strip) > 0: # Salva "USO NASAL" etc.
                        linhas_filtradas.append(linha_strip)
            
            texto = "\n".join(linhas_filtradas)
            
            texto = re.sub(r'\n{3,}', '\n\n', texto) 
            # Removemos o sub(r'[ \t]+', ' ', texto) que também podia estar quebrando o layout
            texto = texto.strip()

        return texto, None
    except Exception as e:
        return "", f"Erro ao ler o arquivo {tipo_arquivo}: {e}"
