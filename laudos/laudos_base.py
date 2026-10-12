"""Extração dos laudos finais da psicóloga (PDF) para exemplos de estilo.

Usado pelo comando extrair_laudos, só na máquina local. Os passos:
1. Lê o PDF mantendo o recuo das linhas, que marca o início dos parágrafos.
2. Acha as seções pelo TÍTULO, nunca pelo número: nos laudos dela a anamnese é
   "4.1 HISTÓRIA CLÍNICA", enquanto no sistema é a seção 4.2.
3. Divide a CONCLUSÃO em 5.1 e 5.2 no primeiro parágrafo que trata do diagnóstico.
4. Anonimiza: o paciente vira um pseudônimo, familiares viram o parentesco,
   profissionais perdem o nome e o registro, datas saem.
5. Lista as palavras com cara de nome próprio que sobraram, para revisão humana.
"""

import re
import unicodedata

INVISIVEIS = dict.fromkeys(map(ord, "​‌‍﻿­"), None)

PSEUDONIMOS = {
    "F": ["Helena", "Lívia", "Marina", "Cecília", "Débora", "Renata", "Sílvia", "Olívia", "Teresa"],
    "M": ["Bruno", "Otávio", "Rafael", "Gustavo", "Leandro", "Murilo", "Vinícius", "Rodrigo", "Sérgio"],
}

PARENTESCOS = {
    "mãe": "a mãe", "pai": "o pai", "avó": "a avó", "avô": "o avô", "irmã": "a irmã", "irmão": "o irmão",
    "esposa": "a esposa", "marido": "o marido", "companheira": "a companheira", "companheiro": "o companheiro",
    "namorada": "a namorada", "namorado": "o namorado", "tia": "a tia", "tio": "o tio", "madrasta": "a madrasta",
    "padrasto": "o padrasto", "filha": "a filha", "filho": "o filho",
}

PROFISSOES = (
    r"[Pp]siquiatra|[Pp]sic[óo]log[oa]|[Nn]eurologista|[Nn]europediatra|[Pp]ediatra|[Ff]onoaudi[óo]log[oa]|"
    r"[Tt]erapeuta [Oo]cupacional|[Pp]sicopedagog[oa]|[Mm][ée]dic[oa]|[Nn]europsic[óo]log[oa]|[Pp]rofessor[a]?|Dra?\."
)

# Palavras com inicial maiúscula que aparecem no meio das frases e não são nomes de pessoa.
TERMOS_CONHECIDOS = {
    "Transtorno", "Espectro", "Autista", "Déficit", "Atenção", "Hiperatividade", "Ansiedade", "Generalizada",
    "Depressivo", "Maior", "Terapia", "Cognitivo", "Comportamental", "Manual", "Diagnóstico", "Estatístico",
    "Transtornos", "Mentais", "Classificação", "Internacional", "Doenças", "Psiquiatria", "Psicologia", "Escola",
    "Queixas", "Saúde", "Uso", "Medicação", "Histórico", "Familiar", "Profissional", "Gestação", "Parto", "Marcos",
    "Desenvolvimento", "Percurso", "Escolar", "Sugestões", "Observação", "Legislação", "Brasileira", "Brasil",
    "Lei", "Política", "Nacional", "Educação", "Inclusiva", "Especial", "Diretrizes", "Bases", "Atendimento",
    "Acessibilidade", "Pessoa", "Deficiência", "Proteção", "Direitos", "Inclusão", "Português", "Matemática",
    "Ensino", "Médio", "Fundamental", "Superior", "Direito", "Psicopedagogia", "Fonoaudiologia", "Ocupacional",
    "Neuropediatria", "Neurologia", "Por", "Além", "Apesar", "Durante", "Segundo", "Conforme", "Quanto", "No",
    "Na", "Em", "De", "Do", "Da", "Sobre", "Acerca", "Atualmente", "Adicionalmente", "Ademais", "Somado",
    "Contudo", "Entretanto", "Todavia", "Embora", "Ainda", "Também", "Esta", "Este", "Esse", "Essa", "Os", "As",
    "O", "A", "Com", "Para", "Diante", "Concomitantemente", "Descarta", "Sugere", "Recomenda", "Considera",
}

_TITULO = re.compile(r"^\s*(?:\d+(?:\.\d+)*\.?)\s*([A-ZÁÉÍÓÚÂÊÔÃÕÇ][A-ZÁÉÍÓÚÂÊÔÃÕÇ ,:–-]{3,})\s*$")
_RODAPE = re.compile(r"^\s*\d+\s+de\s+\d+\s*$")
_NOTA = re.compile(r"^\s*\d{1,2}\s*$")
# Nota de rodapé que começa na mesma linha do número: "3de Paula, J.J. (2018)..." ou "12AMERICAN PSYCHIATRIC...".
# No corpo do laudo, uma linha quase nunca começa com número seguido de letra.
_NOTA_COM_TEXTO = re.compile(r"^\s*\d{1,2}\s?[A-Za-zÁÉÍÓÚ]")
_REFERENCIA = re.compile(r"\(\d{4}\)|\b(19|20)\d{2}\b|Editora|Vetor|Journal|Press|Association|Psychological|\bed\.", re.IGNORECASE)
_MARCADOR = re.compile(r"^\s*[▪•●■◦−–-]\s*")
_ASSINATURA = re.compile(r"^\s*(_{5,}|[A-ZÁ-Úa-zá-ú ]+,\s*\d{1,2}\s+de\s+\w+\s+de\s+\d{4})")
_CHAMADA_DE_NOTA = re.compile(r"(?<=[a-zá-ú\)])\d{1,2}(?=[\s,.;:])")
_DIAGNOSTICO = re.compile(r"crit[ée]rios diagn[óo]sticos|DSM-5|hip[óo]teses? diagn[óo]stica|fica estabelecido o diagn", re.IGNORECASE)


def sem_acento(texto):
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn").upper()


def secao_do_titulo(titulo):
    """Chave da seção do sistema para um título de laudo, ou None se não for seção que o sistema escreve."""
    t = sem_acento(titulo)
    if "DESCRICAO DA DEMANDA" in t:
        return "2"
    if "HISTORIA CLINICA" in t or "ANAMNESE" in t:
        return "4.2"
    if "RELACAO ENTRE" in t:
        return "5.1"
    if "HIPOTESES" in t:
        return "5.2"
    if "CONCLUSAO" in t:
        return "5"
    if "RECOMENDACOES" in t or "ENCAMINHAMENTOS" in t:
        return "6"
    return None


def ler_pdf(caminho):
    """Páginas do PDF como listas de linhas, já sem rodapé de página e sem notas de rodapé."""
    from pypdf import PdfReader

    paginas = []
    for pagina in PdfReader(str(caminho)).pages:
        linhas = (pagina.extract_text(extraction_mode="layout") or "").translate(INVISIVEIS).splitlines()
        limpas = []
        for i, linha in enumerate(linhas):
            if _RODAPE.match(linha):
                continue
            seguinte = " ".join(linhas[i + 1:i + 3])
            if (_NOTA.match(linha) and _REFERENCIA.search(seguinte)) or (
                _NOTA_COM_TEXTO.match(linha) and _REFERENCIA.search(linha + seguinte)
            ):
                break  # daqui para baixo são as notas de rodapé da página
            limpas.append(linha.rstrip())
        paginas.append(limpas)
    return paginas


def identificacao(linhas):
    """Nome, sexo (F/M) e idade do quadro de identificação."""
    texto = "\n".join(linhas[:80])
    nome = re.search(r"Nome\s{2,}(.+?)(?:\s{2,}|$)", texto, re.MULTILINE)
    sexo = re.search(r"Sexo\s+(Feminino|Masculino)", texto)
    idade = re.search(r"Idade\s+(\d{1,2})\s+anos", texto)
    return {
        "nome": nome.group(1).strip() if nome else "",
        "sexo": "F" if sexo and sexo.group(1) == "Feminino" else "M",
        "idade": int(idade.group(1)) if idade else None,
    }


def paragrafos(linhas):
    """Junta as linhas de layout em parágrafos. Recuo, marcador ou fim de frase em linha curta abrem um novo."""
    largura = max((len(l.strip()) for l in linhas if l.strip()), default=80)
    blocos, atual, anterior = [], [], ""
    for linha in linhas:
        if not linha.strip():
            continue
        recuo = len(linha) - len(linha.lstrip(" "))
        marcador = bool(_MARCADOR.match(linha))
        fim_de_frase = anterior.rstrip().endswith((".", ":", ";")) and len(anterior.strip()) < 0.8 * largura
        if atual and (marcador or recuo >= 4 or fim_de_frase):
            blocos.append(atual)
            atual = []
        texto = _MARCADOR.sub("- ", linha) if marcador else linha.strip()
        atual.append(texto.strip())
        anterior = linha
    if atual:
        blocos.append(atual)
    return [_CHAMADA_DE_NOTA.sub("", re.sub(r"\s+", " ", " ".join(b))).strip() for b in blocos]


def secoes(paginas):
    """{chave: [parágrafos]} das seções que o sistema escreve, localizadas pelo título."""
    linhas = [l for pagina in paginas for l in pagina]
    encontradas, atual = {}, None
    for linha in linhas:
        titulo = _TITULO.match(linha)
        if titulo:
            atual = secao_do_titulo(titulo.group(1))
            if atual:
                encontradas.setdefault(atual, [])
            continue
        if atual == "6" and _ASSINATURA.match(linha):
            atual = None
            continue
        if atual:
            encontradas[atual].append(linha)
    resultado = {chave: paragrafos(ls) for chave, ls in encontradas.items()}
    conclusao = resultado.pop("5", None)
    if conclusao:
        corte = next((i for i, p in enumerate(conclusao) if _DIAGNOSTICO.search(p)), len(conclusao))
        if conclusao[:corte]:
            resultado.setdefault("5.1", conclusao[:corte])
        if conclusao[corte:]:
            resultado.setdefault("5.2", conclusao[corte:])
    return {chave: ps for chave, ps in resultado.items() if ps}


def _trocar(texto, alvo, substituto):
    """Troca alvo por substituto, com maiúscula quando a troca abre uma frase."""
    padrao = re.compile(r"(^|[.!?:]\s+|- )?\b" + re.escape(alvo) + r"\b")

    def troca(m):
        inicio = m.group(1)
        if inicio is not None:
            return inicio + substituto[0].upper() + substituto[1:]
        return substituto

    return padrao.sub(troca, texto)


def anonimizar(textos, ident, pseudonimo, substituicoes=None):
    """Devolve (textos anonimizados, trocas feitas). `substituicoes` vem da revisão humana."""
    trocas = {}
    junto = "\n\n".join(textos)

    # Familiares: "Rosa Maria, mãe de Joana" vira "a mãe" em todo o texto.
    nome_proprio = r"[A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-záéíóúâêôãõç]+(?: (?:de |da |do |dos |das )?[A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-záéíóúâêôãõç]+)*"
    for m in re.finditer(rf"({nome_proprio}),\s+(?:sua |seu )?({'|'.join(PARENTESCOS)})\b", junto):
        trocas.setdefault(m.group(1), PARENTESCOS[m.group(2)])
    for m in re.finditer(rf"\b(?:sua |seu |a |o )?({'|'.join(PARENTESCOS)}),\s+({nome_proprio})\b", junto):
        trocas.setdefault(m.group(2), PARENTESCOS[m.group(1)])

    # O paciente: nome completo, nome e sobrenome, e o primeiro nome. Vale sobre qualquer
    # parentesco achado acima ("seu irmão, Fulano" fala do irmão, não faz do paciente o irmão).
    partes = [p for p in ident["nome"].split() if len(p) > 2 and p.lower() not in {"de", "da", "do", "dos", "das"}]
    for n in range(len(partes), 0, -1):
        trocas[" ".join(partes[:n])] = pseudonimo
    trocas.update(substituicoes or {})

    resultado = []
    for texto in textos:
        # "Rosa Maria, mãe de X, relata" vira "a mãe relata", sem o aposto repetido.
        for alvo in sorted(trocas, key=len, reverse=True):
            texto = _trocar(texto, alvo, trocas[alvo])
        for parente in PARENTESCOS:
            texto = re.sub(rf"\b([Aa]|[Oo]) {parente},\s+{parente} d[eao] \w+,?", rf"\1 {parente}", texto)
        texto = re.sub(rf"\b({PROFISSOES})\s+(?:{nome_proprio})(?:\s+Junior|\s+Júnior|\s+Filho|\s+Neto)?", r"\1", texto)
        texto = re.sub(r"\s*[–-]?\s*(?:CR[MP]|RQE)\s*:?\s*[\d/.-]+(?:\s*/?\s*[A-Z]{2}\b)?", "", texto)
        texto = re.sub(r"\s*/\s*(?=[\s)(])", "", texto)  # barra que sobra entre registros removidos
        texto = re.sub(r"\s*\(\s*(?:[A-Z]{2})?\s*\)", "", texto)  # "()" ou "(SP)" que sobram do registro
        texto = re.sub(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b", "", texto)
        # Contrações que a troca de nome por parentesco desfaz: "por a mãe" vira "pela mãe".
        papeis = "|".join(p.split(" ", 1)[1] for p in PARENTESCOS.values())
        for antes, artigo, depois in (("por", "a", "pela"), ("por", "o", "pelo"), ("de", "a", "da"), ("de", "o", "do"),
                                      ("em", "a", "na"), ("em", "o", "no")):
            texto = re.sub(rf"\b{antes} {artigo} (?=({papeis})\b)", f"{depois} ", texto)
        texto = re.sub(r"[ \t]{2,}", " ", texto)  # só espaços: as quebras de parágrafo ficam
        resultado.append(texto.strip())
    return resultado, trocas


def suspeitos(textos):
    """Palavras com inicial maiúscula no meio da frase que podem ser nomes que sobraram."""
    achados = {}
    for texto in textos:
        for m in re.finditer(r"(?<![.!?:]\s)(?<!^)(?<!- )\b([A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-záéíóúâêôãõç]{2,})\b", texto):
            palavra = m.group(1)
            if palavra in TERMOS_CONHECIDOS or palavra in sum(PSEUDONIMOS.values(), []):
                continue
            inicio = max(0, m.start() - 40)
            achados.setdefault(palavra, texto[inicio:m.end() + 40].replace("\n", " "))
    return achados
