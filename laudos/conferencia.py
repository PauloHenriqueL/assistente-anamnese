"""Conferências feitas no código, sem depender do prompt.

O prompt pede, mas o modelo nem sempre obedece. Aqui ficam as regras que dá
para checar de forma determinística: o que falhar vira pedido de reescrita e,
se ainda sobrar depois dela, aviso no bloco para a psicóloga ver.
"""

import re
from collections import Counter

VERBOS_DE_RELATO = [
    "relata", "informa", "refere", "menciona", "descreve", "destaca", "afirma", "cita", "explica", "recorda",
    "ressalta", "reconhece", "pontua", "acrescenta", "conta", "observa", "aponta", "declara", "esclarece", "enfatiza",
]

# Palavras que ela já rejeitou: informais, rebuscadas ou vagas. Nunca entram.
PROIBIDAS = {
    r"paix(ão|ões)|apaixonad[oa]s?": "paixão",
    r"genitor(a|es|as)?|progenitor(a|es|as)?": "genitor",
    r"descendente": "descendente",
    r"respons[áa]vel familiar": "responsável familiar",
    r"estado an[íi]mico": "estado anímico",
    r"comportamentos? at[íi]picos?|condutas? at[íi]picas?": "comportamentos atípicos",
    r"perfeitamente": "perfeitamente",
    r"total aus[êe]ncia": "total ausência",
    r"de forma alguma": "de forma alguma",
    r"imprescind[íi]ve(l|is)": "imprescindível",
    r"in[úu]mer[oa]s": "inúmeros",
}

# Intensificadores que só podem aparecer se as anotações também trazem a ideia.
INTENSIFICADORES = {
    r"significativ[oa]s?|significativamente": "signific",
    r"sever[oa]s?|severamente": "sever",
    r"extrem[oa]s?|extremamente": "extrem",
    r"expressiv[oa]s?|expressivamente": "expressiv",
}

# Na anamnese só entra o relato do paciente ou do informante, nunca a voz da avaliadora.
VOZ_DA_AVALIADORA = [
    r"o que sugere", r"o que evidencia", r"o que reflete", r"o que indica", r"a investiga[çc][ãa]o",
    r"observa-se", r"nota-se", r"evidencia-se", r"percebe-se",
]

ASPAS = re.compile(r"[\"“”]")
MAXIMO_PALAVRAS_TEMA = 230


def _achar(padrao, texto):
    return re.search(rf"\b(?:{padrao})\b", texto, re.IGNORECASE)


def problemas_de_estilo(secao, paragrafos, material):
    """{id do bloco: [pedidos de correção]} para os blocos que a IA escreveu (revisões dela ficam de fora)."""
    material = (material or "").lower()
    resultado = {}
    reconhece_visto = False
    for p in paragrafos:
        if p.modo.value == "revisao":
            continue
        texto, pedidos = p.texto, []
        if ASPAS.search(texto):
            pedidos.append("Tire as aspas e passe a fala para discurso indireto.")
        for padrao, nome in PROIBIDAS.items():
            if _achar(padrao, texto):
                pedidos.append(f"Não use {nome}; troque por uma palavra simples do dia a dia.")
        for padrao, raiz in INTENSIFICADORES.items():
            achado = _achar(padrao, texto)
            if achado and raiz not in material:
                pedidos.append(f"Tire {achado.group(0)}: as anotações não trazem essa intensidade.")
        if secao.ordem_livre:
            for padrao in VOZ_DA_AVALIADORA:
                achado = _achar(padrao, texto)
                if achado:
                    pedidos.append(f"Tire {achado.group(0)}: a anamnese é só o relato do paciente ou do informante, sem interpretação.")
        contagem = Counter(m.group(0).lower() for m in re.finditer(rf"\b({'|'.join(VERBOS_DE_RELATO)})\b", texto, re.IGNORECASE))
        repetidos = [v for v, n in contagem.items() if n >= 2]
        if repetidos:
            pedidos.append(f"Não repita {', '.join(repetidos)} no mesmo parágrafo: reorganize a frase ou omita o sujeito.")
        if contagem.get("reconhece"):
            if reconhece_visto:
                pedidos.append("Reconhece já foi usado na seção; use outro verbo de relato.")
            reconhece_visto = True
        tema_grande = secao.ordem_livre and p.tema not in secao.tipos_finais | secao.tipos_abertura
        if tema_grande and len(texto.split()) > MAXIMO_PALAVRAS_TEMA:
            pedidos.append("Parágrafo longo demais: condense para até 200 palavras cortando palavras e repetições, nunca fatos.")
        if pedidos:
            resultado[p.id] = pedidos
    return resultado


def tirar_aspas(texto):
    """Último recurso, quando a reescrita ainda deixou aspas."""
    return re.sub(r"\s{2,}", " ", ASPAS.sub("", texto)).strip()


def juntar_temas_repetidos(secao, resposta, existentes):
    """Garante um parágrafo por tema nas seções de ordem livre. Devolve os ids dos blocos que receberam junção.

    - Dois blocos da resposta com o mesmo tema viram um só (o primeiro), e os ids existentes dos outros saem.
    - Um bloco novo de um tema que já existe na seção é juntado ao parágrafo existente.
    `existentes` = {tema: (id "P12", texto atual)} dos parágrafos ativos que não vieram na resposta.
    """
    from .gemini import Modo

    if not secao.ordem_livre:
        return []
    juntados, primeiro = [], {}
    for p in list(resposta.paragrafos):
        if p.tema == "outro" or p.modo.value == "revisao":
            continue
        if p.tema in primeiro:
            alvo = primeiro[p.tema]
            alvo.texto = f"{alvo.texto.strip()} {p.texto.strip()}"
            alvo.trechos_origem = alvo.trechos_origem + p.trechos_origem
            resposta.paragrafos.remove(p)
            if p.id.startswith("P"):
                resposta.remover.append(p.id)
            if alvo.id not in juntados:
                juntados.append(alvo.id)
            continue
        primeiro[p.tema] = p
        if not p.id.startswith("P") and p.tema in existentes:
            id_existente, texto_existente = existentes[p.tema]
            if id_existente not in {q.id for q in resposta.paragrafos} and id_existente not in resposta.remover:
                p.id = id_existente
                p.texto = f"{texto_existente.strip()} {p.texto.strip()}"
                p.modo = Modo.ajuste
                juntados.append(p.id)
    return juntados
