# --------------------------------------------------------------
#  Auditoria de Bulas – v25+ (Layout Lado a Lado + Marcações)
# --------------------------------------------------------------
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
import pytesseract
from PIL import Image

# ====================== CONFIGURAÇÃO DA PÁGINA ======================
st.set_page_config(layout="wide", page_title="Auditoria de Bulas", page_icon="🔬")
hide_streamlit_UI = """
<style>
    [data-testid="stHeader"], [data-testid="main-menu-button"], footer,
    [data-testid="stStatusWidget"], [data-testid="stCreatedBy"], [data-testid="stHostedBy"] {
        display: none !important; visibility: hidden !important;
    }
</style>
"""
st.markdown(hide_streamlit_UI, unsafe_allow_html=True)

# ====================== ESTILO GLOBAL (CSS) ======================
CSS = """
<style>
    .container-scroll {
        height: 720px;
        overflow-y: auto;
        border: 2px solid #bbb;
        border-radius: 12px;
        padding: 24px 32px;
        background: #fafafa;
        font-family: 'Georgia', serif;
        font-size: 15px;
        line-height: 1.8;
        box-shadow: 0 4px 16px rgba(0,0,0,0.12);
        text-align: justify;
        margin-bottom: 20px;
    }
    .container-scroll::-webkit-scrollbar { width: 10px; }
    .container-scroll::-webkit-scrollbar-thumb { background: #999; border-radius: 5px; }

    mark.diff   { background:#ffff99; padding:2px 4px; border-radius:3px; }
    mark.spell  { background:#ffddcc; padding:2px 4px; border-radius:3px; }
    mark.anvisa { background:#cce5ff; padding:2px 4px; border-radius:3px; font-weight:600; }

    .expander-box {
        height: 360px; overflow-y:auto; border:2px solid #d0d0d0; border-radius:6px;
        padding:14px; background:#fff; font-size:14px; line-height:1.7;
    }
    .clickable { cursor:pointer; transition:background 0.3s; }
    .clickable:hover { background:#f0f8ff !important; }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

# ====================== MODELO NLP ======================
@st.cache_resource
def carregar_modelo_spacy():
    try:
        return spacy.load("pt_core_news_lg")
    except OSError:
        st.error("Modelo 'pt_core_news_lg' não encontrado. `python -m spacy download pt_core_news_lg`")
        return None
nlp = carregar_modelo_spacy()

# ====================== CORRETOR OCR ======================
def corrigir_erros_ocr_comuns(texto):
    if not texto: return ""
    correcoes = {
        r"(?i)\b(3|1)lfar\b": "Belfar",
        r"(?i)\bBeifar\b": "Belfar",
        r"(?i)\b3elspan\b": "Belspan",
        r"(?i)USO\s+ADULTO": "USO ADULTO",
        r"(?i)USO\s+ORAL": "USO ORAL",
        r"(?i)\bNAO\b": "NÃO",
        r"(?i)\bCOMPOSIÇAO\b": "COMPOSIÇÃO",
        r"(?i)\bMEDICAMENT0\b": "MEDICAMENTO",
        r"(?i)\bJevido\b": "Devido",
        r"(?i)\"ertilidade\b": "Fertilidade",
        r"(?i)\bjperar\b": "operar",
        r"(?i)\'ombinação\b": "combinação",
        r"(?i)\bjue\b": "que",
        r"(?i)\brereditários\b": "hereditários",
        r"(?i)\bralactosemia\b": "galactosemia",
    }
    for padrao, correcao in correcoes.items():
        texto = re.sub(padrao, correcao, texto)
    return texto

# ====================== EXTRAÇÃO HÍBRIDA ======================
def extrair_pdf_hibrido_colunas(arquivo_bytes):
    texto_total = ""
    with fitz.open(stream=io.BytesIO(arquivo_bytes), filetype="pdf") as doc:
        for i, page in enumerate(doc):
            rect = page.rect
            margin_y = 20
            col1 = fitz.Rect(0, margin_y, rect.width*0.5, rect.height-margin_y)
            col2 = fitz.Rect(rect.width*0.5, margin_y, rect.width, rect.height-margin_y)

            # ---- tentativa direta (texto) ----
            try:
                txt1 = page.get_text("text", clip=col1, sort=True)
                txt2 = page.get_text("text", clip=col2, sort=True)
                pagina = txt1 + "\n" + txt2
            except Exception:
                pagina = ""

            if len(pagina.strip()) > 200:
                texto_total += pagina + "\n"
                continue

            # ---- OCR (imagem) ----
            try:
                cfg = r'--psm 6'
                pix1 = page.get_pixmap(clip=col1, dpi=300)
                img1 = Image.open(io.BytesIO(pix1.tobytes("png")))
                ocr1 = pytesseract.image_to_string(img1, lang='por', config=cfg)

                pix2 = page.get_pixmap(clip=col2, dpi=300)
                img2 = Image.open(io.BytesIO(pix2.tobytes("png")))
                ocr2 = pytesseract.image_to_string(img2, lang='por', config=cfg)

                texto_total += ocr1 + "\n" + ocr2 + "\n"
            except Exception as e:
                st.error(f"OCR falhou pág.{i+1}: {e}")
    return texto_total

def extrair_texto(arquivo, tipo):
    if not arquivo: return "", "Arquivo não enviado"
    arquivo.seek(0)
    bytes_ = arquivo.read()
    if tipo == "pdf":
        texto = extrair_pdf_hibrido_colunas(bytes_)
    else:  # pdf
        doc = pdf.Document(io.BytesIO(bytes_))
        texto = "\n".join(p.text for p in doc.paragraphs)

    # ---- limpeza ----
    lixo = [
        r"(?i)BELFAR", r"(?i)Papel", r"(?i)Times New Roman", r"(?i)Cor[: ]",
        r"(?i)Frente/?Verso", r"(?i)Medida da bula", r"(?i)Contato[: ]",
        r"(?i)Impressão[: ]", r"(?i)Tipologia da bula", r"BUL\s*BELSPAN\s*COMPRIMIDO",
        r"BUL\d+V\d+", r"FRENTE:", r"VERSO:", r"artes@belfat\.com\.br",
    ]
    linhas = [ln for ln in texto.split('\n') if not any(re.search(p, ln, re.I) for p in lixo)]
    texto = "\n".join(linhas)

    # normalização
    invis = ['\u00AD','\u200B','\u200C','\u200D','\uFEFF']
    for c in invis: texto = texto.replace(c,'')
    texto = texto.replace('\r\n','\n').replace('\r','\n')
    texto = texto.replace('\u00A0',' ')
    texto = re.sub(r'(\w+)-\n(\w+)', r'\1\2', texto)
    texto = re.sub(r'\n{3,}', '\n\n', texto)
    texto = re.sub(r'[ \t]+', ' ', texto)
    texto = texto.strip()

    texto = corrigir_erros_ocr_comuns(texto)
    return texto, None

# ====================== TRUNCAR APÓS ANVISA ======================
def truncar_apos_anvisa(texto):
    m = re.search(r"(aprovad[ao]\s+pela\s+anvisa\s+em|data\s+de\s+aprovação\s+na\s+anvisa:)\s*([\d]{1,2}/[\d]{1,2}/[\d]{2,4})", texto, re.I)
    if m:
        fim = texto.find('\n', m.end())
        return texto[:fim] if fim != -1 else texto
    return texto

# ====================== SEÇÕES ======================
def obter_secoes_por_tipo(tipo):
    pac = ["APRESENTAÇÕES","COMPOSIÇÃO","1. PARA QUE ESTE MEDICAMENTO É INDICADO?","2. COMO ESTE MEDICAMENTO FUNCIONA?","3. QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?","4. O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?","5. ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?","6. COMO DEVO USAR ESTE MEDICAMENTO?","7. O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?","8. QUAIS OS MALES QUE ESTE MEDICAMENTO PODE ME CAUSAR?","9. O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?","DIZERES LEGAIS"]
    prof = ["APRESENTAÇÕES","COMPOSIÇÃO","1. INDICAÇÕES","2. RESULTADOS DE EFICÁCIA","3. CARACTERÍSTICAS FARMACOLÓGICAS","4. CONTRAINDICAÇÕES","5. ADVERTÊNCIAS E PRECAUÇÕES","6. INTERAÇÕES MEDICAMENTOSAS","7. CUIDADOS DE ARMAZENAMENTO DO MEDICAMENTO","8. POSOLOGIA E MODO DE USAR","9. REAÇÕES ADVERSAS","10. SUPERDOSE","DIZERES LEGAIS"]
    return pac if tipo=="Paciente" else prof

def obter_aliases_secao():
    return {
        "INDICAÇÕES":"1. PARA QUE ESTE MEDICAMENTO É INDICADO?",
        "CONTRAINDICAÇÕES":"3. QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?",
        "POSOLOGIA E MODO DE USAR":"6. COMO DEVO USAR ESTE MEDICAMENTO?",
        "REAÇÕES ADVERSAS":"8. QUAIS OS MALES QUE ESTE MEDICAMENTO PODE ME CAUSAR?",
        "SUPERDOSE":"9. O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?",
        "CUIDADOS DE ARMAZENAMENTO DO MEDICAMENTO":"5. ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?",
    }

def obter_secoes_ignorar_ortografia(): return ["COMPOSIÇÃO","DIZERES LEGAIS"]
def obter_secoes_ignorar_comparacao(): return ["COMPOSIÇÃO","DIZERES LEGAIS","APRESENTAÇÕES","ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?","CUIDADOS DE ARMAZENAMENTO DO MEDICAMENTO"]

# ====================== NORMALIZAÇÃO ======================
def normalizar_para_comparacao_literal(t):
    if not t: return ""
    t = re.sub(r'[\n\r\t]+',' ',t)
    t = re.sub(r' +',' ',t).strip()
    return t.lower()

def normalizar_texto(t):
    t = ''.join(c for c in unicodedata.normalize('NFD',t) if unicodedata.category(c)!='Mn')
    t = re.sub(r'[^\w\s]','',t)
    return ' '.join(t.split()).lower()

def normalizar_titulo_para_comparacao(t):
    return re.sub(r'^\d+\s*[\.\-)]*\s*','',normalizar_texto(t)).strip()

def _create_anchor_id(secao, prefix):
    safe = re.sub(r'[^a-z0-9\-]','-',normalizar_texto(secao))
    return f"anchor-{prefix}-{safe}"

# ====================== MAPEAMENTO DE SEÇÕES ======================
def is_titulo_secao(l):
    l = l.strip()
    if len(l)<4 or len(l.split())>20 or l.endswith(('.',':')) or len(l)>120: return False
    return True

def mapear_secoes(texto, esperadas):
    linhas = texto.split('\n')
    aliases = obter_aliases_secao()
    possiveis = {s:s for s in esperadas}
    for a,c in aliases.items():
        if c in esperadas and a not in possiveis: possiveis[a]=c
    mapa = []
    for idx,ln in enumerate(linhas):
        if not is_titulo_secao(ln): continue
        norm = normalizar_titulo_para_comparacao(ln)
        best, best_c = 0, None
        for tit,c in possiveis.items():
            sc = fuzz.token_set_ratio(normalizar_titulo_para_comparacao(tit),norm)
            if sc>best: best,best_c=sc,c
        if best>=98 and (not mapa or mapa[-1]['canonico']!=best_c):
            mapa.append({'canonico':best_c,'titulo_encontrado':ln.strip(),'linha_inicio':idx,'score':best})
    mapa.sort(key=lambda x:x['linha_inicio'])
    return mapa

def obter_dados_secao(canonico, mapa, linhas, tipo):
    titulos = obter_secoes_por_tipo(tipo)
    tit_norm = {normalizar_titulo_para_comparacao(t) for t in titulos}
    for m in mapa:
        if m['canonico']!=canonico: continue
        inicio = m['linha_inicio']+1
        fim = len(linhas)
        for j in range(inicio,len(linhas)):
            linha = linhas[j].strip()
            if not linha: continue
            n = normalizar_titulo_para_comparacao(linha)
            if any(fuzz.token_set_ratio(tn,n)>=98 for tn in tit_norm):
                fim = j; break
            if j+1<len(linhas):
                duas = f"{linha} {linhas[j+1].strip()}"
                if any(fuzz.token_set_ratio(tn,normalizar_titulo_para_comparacao(duas))>=98 for tn in tit_norm):
                    fim = j; break
        conteudo = '\n'.join(linhas[inicio:fim]).strip()
        return True, m['titulo_encontrado'], conteudo
    return False, None, ""

# ====================== COMPARAÇÃO ======================
def verificar_secoes_e_conteudo(ref, bel, tipo):
    esperadas = obter_secoes_por_tipo(tipo)
    faltantes, diffs, sims, tit_diffs = [], [], [], []
    lref, lbel = ref.split('\n'), bel.split('\n')
    mref, mbel = mapear_secoes(ref,esperadas), mapear_secoes(bel,esperadas)

    for s in esperadas:
        ok_ref, _, cref = obter_dados_secao(s,mref,lref,tipo)
        ok_bel, tbel, cbel = obter_dados_secao(s,mbel,lbel,tipo)

        if not ok_bel:
            # tentativa fuzzy
            best, best_t = 0, None
            for mm in mbel:
                sc = fuzz.token_set_ratio(normalizar_titulo_para_comparacao(s),normalizar_titulo_para_comparacao(mm['titulo_encontrado']))
                if sc>best: best,best_t=sc,mm['titulo_encontrado']
            if best>=95:
                tit_diffs.append({'secao_esperada':s,'titulo_encontrado':best_t})
                idx = next(i for i,m in enumerate(mbel) if m['titulo_encontrado']==best_t)
                nxt = mbel[idx+1]['linha_inicio'] if idx+1<len(mbel) else len(lbel)
                cbel = '\n'.join(lbel[mbel[idx]['linha_inicio']+1:nxt])
                ok_bel = True
            else:
                faltantes.append(s); continue

        if ok_ref and ok_bel:
            if normalizar_titulo_para_comparacao(s)!=normalizar_titulo_para_comparacao(tbel if tbel else best_t):
                if not any(d['secao_esperada']==s for d in tit_diffs):
                    tit_diffs.append({'secao_esperada':s,'titulo_encontrado':tbel or best_t})

            if normalizar_titulo_para_comparacao(s) in [normalizar_titulo_para_comparacao(i) for i in obter_secoes_ignorar_comparacao()]:
                sims.append(100); continue

            if normalizar_para_comparacao_literal(cref)!=normalizar_para_comparacao_literal(cbel):
                diffs.append({'secao':s,'conteudo_ref':cref,'conteudo_belfar':cbel,'titulo_encontrado':tbel or best_t})
                sims.append(0)
            else:
                sims.append(100)
    return faltantes, diffs, sims, tit_diffs

# ====================== ORTOGRAFIA ======================
def checar_ortografia_inteligente(bel, ref, tipo):
    if not nlp or not bel: return []
    try:
        ignorar = obter_secoes_ignorar_ortografia()
        todas = obter_secoes_por_tipo(tipo)
        mapa = mapear_secoes(bel,todas)
        linhas = bel.split('\n')
        texto = []
        for sec in todas:
            if normalizar_titulo_para_comparacao(sec) in [normalizar_titulo_para_comparacao(i) for i in ignorar]: continue
            ok,_,c = obter_dados_secao(sec,mapa,linhas,tipo)
            if ok and c: texto.append('\n'.join(c.split('\n')[1:]))
        texto = '\n'.join(texto)
        if not texto: return []

        spell = SpellChecker(language='pt')
        vocab = set(re.findall(r'\b[a-záéíóúâêôãõçü]+\b',ref.lower()))
        doc = nlp(bel)
        ents = {e.text.lower() for e in doc.ents}
        spell.word_frequency.load_words(vocab|ents|{"alair","belfar","peticionamento","urotrobel","escopolamina","dipirona","butilbrometo","nafazolina","cloreto"})
        palavras = re.findall(r'\b[a-záéíóúâêôãõçü]+\b',texto.lower())
        erros = spell.unknown(palavras)
        return sorted({e for e in erros if len(e)>3})[:20]
    except Exception as e:
        st.error(f"Ortografia: {e}")
        return []

# ====================== MARCAÇÃO PALAVRA A PALAVRA ======================
def marcar_diferencas_palavra_por_palavra(ref, bel, eh_ref):
    def tok(t): return re.findall(r'\n|[A-Za-zÀ-ÖØ-öø-ÿ0-9_]+|[^\w\s]', t, re.UNICODE)
    def norm(t): return t.lower() if re.match(r'[A-Za-zÀ-ÖØ-öø-ÿ0-9_]+$',t) else t
    r_tok, b_tok = tok(ref), tok(bel)
    r_norm, b_norm = [norm(t) for t in r_tok], [norm(t) for t in b_tok]
    matcher = difflib.SequenceMatcher(None, r_norm, b_norm, autojunk=False)
    diff = set()
    for tag,i1,i2,j1,j2 in matcher.get_opcodes():
        if tag!='equal': diff.update(range(i1,i2) if eh_ref else range(j1,j2))
    tokens = r_tok if eh_ref else b_tok
    res = []
    for i,t in enumerate(tokens):
        if i in diff and t.strip(): res.append(f'<mark class="diff">{t}</mark>')
        else: res.append(t)
    txt = ''
    for i,t in enumerate(res):
        raw = re.sub(r'^<mark[^>]*>|</mark>$','',t)
        if i==0: txt+=t; continue
        if re.match(r'^[^\w\s]$',raw) or raw=='\n': txt+=t
        else: txt+=f' {t}'
    txt = re.sub(r'\s+([.,;:!?)])',r'\1',txt)
    txt = re.sub(r'(\()\s+',r'\1',txt)
    txt = re.sub(r"(</mark>)\s+(<mark[^>]*>)",r"\1 \2",txt)
    return txt

# ====================== MARCAÇÃO FINAL (HTML) ======================
def marcar_divergencias_html(texto, diffs, erros_orto, tipo, eh_ref):
    # 1 – divergências por seção
    for d in diffs:
        src = d['conteudo_ref'] if eh_ref else d['conteudo_belfar']
        marked = marcar_diferencas_palavra_por_palavra(d['conteudo_ref'], d['conteudo_belfar'], eh_ref)
        anchor = _create_anchor_id(d['secao'], "ref" if eh_ref else "bel")
        marked = f'<div id="{anchor}" style="scroll-margin-top:20px;">{marked}</div>'
        texto = texto.replace(src, marked, 1) if src in texto else texto.replace(marked.split('>',1)[1].rsplit('<',1)[0], marked, 1)

    # 2 – erros ortográficos (apenas BELFAR)
    if not eh_ref and erros_orto:
        for e in erros_orto:
            pat = rf'(?<![\w<>-])({re.escape(e)})(?![\w<>-])'
            texto = re.sub(pat, r'<mark class="spell">\1</mark>', texto, flags=re.I)

    # 3 – data ANVISA
    m = re.search(r"((?:aprovad[ao]\s+pela\s+anvisa\s+em|data\s+de\s+aprovação\s+na\s+anvisa:)\s*[\d]{1,2}/[\d]{1,2}/[\d]{2,4})", texto, re.I)
    if m:
        frase = m.group(1)
        texto = texto.replace(frase, f'<mark class="anvisa">{frase}</mark>', 1)
    return texto

# ====================== RELATÓRIO ======================
def gerar_relatorio_final(tref, tbel, nref, nbel, tipo):
    # JS de rolagem sincronizada
    js = """
    <script>
    if (!window.syncScroll) {
        window.syncScroll = function(refId, belId) {
            const r = document.getElementById(refId);
            const b = document.getElementById(belId);
            if (!r || !b) return;
            const scroll = (e) => {
                const other = e.target===r ? b : r;
                other.scrollTop = e.target.scrollTop;
            };
            r.onscroll = scroll; b.onscroll = scroll;
        };
        console.log("syncScroll carregado");
    }
    </script>
    """
    st.markdown(js, unsafe_allow_html=True)

    st.header("Relatório de Auditoria")
    # --- métricas ---
    falt, diffs, sims, titdiff = verificar_secoes_e_conteudo(tref, tbel, tipo)
    orto = checar_ortografia_inteligente(tbel, tref, tipo)
    score = sum(sims)/len(sims) if sims else 100

    c1,c2,c3,c4 = st.columns(4)
    c1.metric("Conformidade", f"{score:.0f}%")
    c2.metric("Erros Ortográficos", len(orto))
    c3.metric("Data ANVISA (BELFAR)", re.search(r"[\d]{1,2}/[\d]{1,2}/[\d]{2,4}", tbel, re.I).group() if re.search(r"[\d]{1,2}/[\d]{1,2}/[\d]{2,4}", tbel, re.I) else "N/D")
    c4.metric("Seções Faltantes", len(falt))

    # --- problemas ---
    if falt: st.error("Seções faltantes: " + ", ".join(falt))
    else: st.success("Todas as seções presentes")

    if diffs:
        st.warning("Seções com divergência de conteúdo:")
        for d in diffs:
            with st.expander(f"{d.get('titulo_encontrado') or d['secao']} – DIVERGENTE"):
                colA, colB = st.columns(2)
                with colA:
                    st.markdown("**Referência**")
                    st.markdown(f'<div class="expander-box clickable" onclick="window.syncScroll(\'container-ref-scroll\',\'container-bel-scroll\')">{marcar_diferencas_palavra_por_palavra(d["conteudo_ref"],d["conteudo_belfar"],True).replace(chr(10),"<br>")}</div>', unsafe_allow_html=True)
                with colB:
                    st.markdown("**BELFAR**")
                    st.markdown(f'<div class="expander-box clickable" onclick="window.syncScroll(\'container-ref-scroll\',\'container-bel-scroll\')">{marcar_diferencas_palavra_por_palavra(d["conteudo_ref"],d["conteudo_belfar"],False).replace(chr(10),"<br>")}</div>', unsafe_allow_html=True)

    if orto:
        st.info("Possíveis erros ortográficos: " + ", ".join(orto))

    # --- visualização lado a lado ---
    st.subheader("Visualização Lado a Lado com Destaques")
    st.markdown('**Legenda:** <mark class="diff">Amarelo</mark> = divergência | <mark class="spell">Rosa</mark> = erro ortográfico | <mark class="anvisa">Azul</mark> = data ANVISA', unsafe_allow_html=True)

    html_ref = marcar_divergencias_html(tref, diffs, [], tipo, True).replace('\n','<br>')
    html_bel = marcar_divergencias_html(tbel, diffs, orto, tipo, False).replace('\n','<br>')

    colL, colR = st.columns(2, gap="medium")
    with colL:
        st.markdown(f"**{nref}**")
        st.markdown(f'<div id="container-ref-scroll" class="container-scroll">{html_ref}</div>', unsafe_allow_html=True)
    with colR:
        st.markdown(f"**{nbel}**")
        st.markdown(f'<div id="container-bel-scroll" class="container-scroll">{html_bel}</div>', unsafe_allow_html=True)

    # ativar sincronização
    st.markdown('<script>window.syncScroll("container-ref-scroll","container-bel-scroll")</script>', unsafe_allow_html=True)

# ====================== INTERFACE ======================
st.title("Inteligência Artificial para Auditoria de Bulas")
st.markdown("Comparação **literal** + OCR + correção automática")
st.divider()

tipo_bula = st.radio("Tipo de Bula", ("Paciente","Profissional"), horizontal=True)
c1,c2 = st.columns(2)
with c1:
    st.subheader("Arte Vigente (Referência)")
    arq_ref = st.file_uploader("PDF ou DOCX", type=["pdf","docx"], key="ref")
with c2:
    st.subheader("PDF da Gráfica (BELFAR)")
    arq_bel = st.file_uploader("PDF", type="pdf", key="bel")

if st.button("Iniciar Auditoria Completa", use_container_width=True, type="primary"):
    if arq_ref and arq_bel:
        with st.spinner("Processando..."):
            tipo_ref = "docx" if arq_ref.name.lower().endswith(".docx") else "pdf"
            txt_ref, err_ref = extrair_texto(arq_ref, tipo_ref)
            txt_bel, err_bel = extrair_texto(arq_bel, "pdf")
            if err_ref or err_bel:
                st.error(err_ref or err_bel)
            else:
                txt_ref = truncar_apos_anvisa(txt_ref)
                txt_bel = truncar_apos_anvisa(txt_bel)
                gerar_relatorio_final(txt_ref, txt_bel, "Referência", "BELFAR", tipo_bula)
    else:
        st.warning("Envie **os dois arquivos** para começar.")
st.divider()
st.caption("Auditoria de Bulas v25+ – Layout Lado a Lado + Marcações Corretas")
