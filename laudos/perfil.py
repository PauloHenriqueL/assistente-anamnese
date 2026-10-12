"""Perfil de um caso: faixa etária e queixas, para escolher exemplos de casos parecidos.

É uma heurística por palavras-chave, de propósito simples: serve só para ordenar
os exemplos, e um erro aqui troca um exemplo por outro, sem afetar o laudo.
"""

import re

QUEIXAS = {
    "tea": r"\bTEA\b|autis|espectro autista",
    "tdah": r"\bTDAH\b|d[ée]ficit de aten[çc][ãa]o|hiperativ",
    "ansiedade": r"ansiedade|ansios",
    "humor": r"depress|bipolar|humor|idea[çc][ãa]o suicida",
    "aprendizagem": r"dislexia|aprendizagem|discalculia|alfabetiza",
    "altas_habilidades": r"altas habilidades|superdota",
}

_IDADE = re.compile(r"\bidade\s*[:\-]?\s*(\d{1,2})\s*anos", re.IGNORECASE)
_CRIANCA = re.compile(r"\b(s[ée]rie|ano escolar|professora|ber[çc]ário|creche|maternal|brincadeira|birra)", re.IGNORECASE)
_ADULTO = re.compile(r"\b(faculdade|gradua[çc][ãa]o|emprego|trabalho|esposa|marido|namorad[oa]|concurso|salário)", re.IGNORECASE)


def faixa(texto):
    """adulto, crianca ou vazio quando não dá para saber."""
    idade = _IDADE.search(texto or "")
    if idade:
        return "adulto" if int(idade.group(1)) >= 18 else "crianca"
    criancas, adultos = len(_CRIANCA.findall(texto or "")), len(_ADULTO.findall(texto or ""))
    if criancas == adultos:
        return ""
    return "crianca" if criancas > adultos else "adulto"


def queixas(texto):
    return sorted(chave for chave, padrao in QUEIXAS.items() if re.search(padrao, texto or "", re.IGNORECASE))


def do_texto(texto):
    return {"faixa": faixa(texto), "queixas": queixas(texto)}


def semelhanca(a, b):
    """Quanto dois perfis se parecem: a mesma faixa pesa mais que cada queixa em comum."""
    pontos = 2 if a.get("faixa") and a.get("faixa") == b.get("faixa") else 0
    return pontos + len(set(a.get("queixas", [])) & set(b.get("queixas", [])))
