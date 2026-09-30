import json

from django.contrib import messages
from django.db.models import Count
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from . import exemplos, secoes, servico
from .extracao import ArquivoInvalido, texto_do_arquivo
from .models import Avaliacao, Exemplo, Laudo, Versao


def _laudo_da_usuaria(request, laudo_id):
    # Laudo de outra pessoa responde 404, para não revelar nem que ele existe.
    return get_object_or_404(Laudo, id=laudo_id, dono=request.user)


def _versao_da_usuaria(request, versao_id):
    return get_object_or_404(Versao, id=versao_id, paragrafo__laudo__dono=request.user)


def lista(request):
    return render(
        request,
        "laudos/lista.html",
        {
            "laudos": Laudo.objects.filter(dono=request.user),
            "sem_exemplos": not Exemplo.objects.filter(fonte=Exemplo.LAUDO_BASE).exists(),
        },
    )


@require_POST
def novo(request):
    paciente = request.POST.get("paciente", "").strip()
    texto = request.POST.get("anamnese", "").strip()
    arquivo = request.FILES.get("arquivo")
    nome_arquivo = ""
    if arquivo:
        try:
            texto = texto_do_arquivo(arquivo)
            nome_arquivo = arquivo.name
        except ArquivoInvalido as erro:
            messages.error(request, str(erro))
            return redirect("lista")
    if not paciente or not texto:
        messages.error(request, "Preencha o nome do paciente e envie a anamnese, em arquivo ou colada no campo.")
        return redirect("lista")
    laudo = Laudo.objects.create(dono=request.user, paciente=paciente, anamnese=texto, arquivo_nome=nome_arquivo)
    return redirect("laudo", laudo.id)


def _secao(chave):
    try:
        return secoes.secao(chave)
    except KeyError:
        raise Http404("Seção inexistente.")


def laudo(request, laudo_id):
    """Visão geral do laudo: a lista de seções para ela escolher onde entrar."""
    laudo = _laudo_da_usuaria(request, laudo_id)
    return render(
        request,
        "laudos/laudo.html",
        {"laudo": laudo, "situacao": servico.situacao_das_secoes(laudo), "secoes": secoes.SECOES},
    )


def secao(request, laudo_id, chave):
    laudo = _laudo_da_usuaria(request, laudo_id)
    s = _secao(chave)
    mensagens = laudo.mensagens.filter(secao=s.chave).prefetch_related("versoes__paragrafo", "versoes__avaliacoes")
    paragrafos = [(p, p.versao_atual()) for p in laudo.paragrafos_atuais(s.chave)]
    situacao = {item["secao"].chave: item for item in servico.situacao_das_secoes(laudo)}
    return render(
        request,
        "laudos/secao.html",
        {
            "laudo": laudo,
            "secao": s,
            "secoes": secoes.SECOES,
            "situacao": situacao,
            "faltando": situacao[s.chave]["faltando"],
            "mensagens": mensagens,
            "paragrafos": paragrafos,
            "motivos": Avaliacao.MOTIVOS,
        },
    )


def _json(request):
    try:
        return json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return {}


@require_POST
def mensagem(request, laudo_id, chave):
    laudo = _laudo_da_usuaria(request, laudo_id)
    s = _secao(chave)
    resposta = servico.processar_mensagem(laudo, _json(request).get("texto", ""), s.chave)
    if resposta.erro:
        return JsonResponse({"ok": False, "erro": resposta.erro}, status=502)
    return JsonResponse({"ok": True})


@require_POST
def avaliar(request, versao_id):
    versao = _versao_da_usuaria(request, versao_id)
    dados = _json(request)
    tipo = dados.get("tipo")
    if tipo not in (Avaliacao.LIKE, Avaliacao.DESLIKE):
        return JsonResponse({"ok": False, "erro": "Tipo de avaliação inválido."}, status=400)
    validos = {chave for chave, _ in Avaliacao.MOTIVOS}
    motivos = [m for m in dados.get("motivos", []) if m in validos] if tipo == Avaliacao.DESLIKE else []
    Avaliacao.objects.create(versao=versao, tipo=tipo, motivos=motivos, comentario=dados.get("comentario", "").strip())
    if tipo == Avaliacao.LIKE:
        Exemplo.objects.update_or_create(
            versao=versao,
            defaults={
                "tema": versao.paragrafo.tema,
                "secao": versao.paragrafo.secao,
                "trecho_origem": "\n".join(versao.trechos_origem),
                "texto": versao.texto,
                "fonte": Exemplo.LIKE,
                "dono": request.user,
                "ativo": True,
            },
        )
    else:
        Exemplo.objects.filter(versao=versao).update(ativo=False)
    return JsonResponse({"ok": True})


@require_POST
def editar(request, versao_id):
    versao = _versao_da_usuaria(request, versao_id)
    texto = _json(request).get("texto", "").strip()
    if not texto:
        return JsonResponse({"ok": False, "erro": "O texto não pode ficar vazio."}, status=400)
    servico.editar_versao(versao, texto)
    return JsonResponse({"ok": True})


def texto_secao(request, laudo_id, chave):
    laudo = _laudo_da_usuaria(request, laudo_id)
    s = _secao(chave)
    return HttpResponse(f"{s.titulo}\n\n{laudo.texto_secao(s.chave)}", content_type="text/plain; charset=utf-8")


def texto_completo(request, laudo_id):
    laudo = _laudo_da_usuaria(request, laudo_id)
    return HttpResponse(laudo.texto_completo(), content_type="text/plain; charset=utf-8")


def estatisticas(request):
    contagem, total = exemplos.contagem_motivos(request.user)
    rotulos = dict(Avaliacao.MOTIVOS)
    motivos = [(rotulos.get(m, m), n, round(100 * n / total) if total else 0) for m, n in contagem.most_common()]
    likes_por_tema = (
        Exemplo.objects.filter(fonte=Exemplo.LIKE, ativo=True, dono=request.user)
        .values("secao", "tema")
        .annotate(n=Count("id"))
        .order_by("-n")
    )
    return render(
        request,
        "laudos/estatisticas.html",
        {
            "motivos": motivos,
            "total_deslikes": total,
            "total_likes": Avaliacao.objects.filter(tipo=Avaliacao.LIKE, versao__paragrafo__laudo__dono=request.user).count(),
            "likes_por_tema": [
                (secoes.secao(x["secao"]).titulo, secoes.secao(x["secao"]).rotulo_tipo(x["tema"]), x["n"]) for x in likes_por_tema
            ],
            "reforcos": [(s.titulo, exemplos.reforcos(request.user, s.chave)) for s in secoes.SECOES if exemplos.reforcos(request.user, s.chave)],
        },
    )
