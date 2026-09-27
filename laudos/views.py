import json

from django.contrib import messages
from django.db.models import Count
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from . import exemplos, servico, temas
from .extracao import ArquivoInvalido, texto_do_arquivo
from .models import Avaliacao, Exemplo, Laudo, Versao


def lista(request):
    return render(
        request,
        "laudos/lista.html",
        {"laudos": Laudo.objects.all(), "sem_exemplos": not Exemplo.objects.filter(fonte=Exemplo.LAUDO_BASE).exists()},
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
    laudo = Laudo.objects.create(paciente=paciente, anamnese=texto, arquivo_nome=nome_arquivo)
    return redirect("laudo", laudo.id)


def laudo(request, laudo_id):
    laudo = get_object_or_404(Laudo, id=laudo_id)
    mensagens = laudo.mensagens.prefetch_related("versoes__paragrafo", "versoes__avaliacoes")
    paragrafos = [(p, p.versao_atual()) for p in laudo.paragrafos_atuais()]
    return render(
        request,
        "laudos/laudo.html",
        {
            "laudo": laudo,
            "mensagens": mensagens,
            "paragrafos": paragrafos,
            "motivos": Avaliacao.MOTIVOS,
            "pedido_inicial": servico.PEDIDO_INICIAL,
            "minimo": temas.MINIMO_PALAVRAS,
        },
    )


def _json(request):
    try:
        return json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return {}


@require_POST
def mensagem(request, laudo_id):
    laudo = get_object_or_404(Laudo, id=laudo_id)
    resposta = servico.processar_mensagem(laudo, _json(request).get("texto", ""))
    if resposta.erro:
        return JsonResponse({"ok": False, "erro": resposta.erro}, status=502)
    return JsonResponse({"ok": True})


@require_POST
def avaliar(request, versao_id):
    versao = get_object_or_404(Versao, id=versao_id)
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
                "trecho_origem": "\n".join(versao.trechos_origem),
                "texto": versao.texto,
                "fonte": Exemplo.LIKE,
                "ativo": True,
            },
        )
    else:
        Exemplo.objects.filter(versao=versao).update(ativo=False)
    return JsonResponse({"ok": True})


@require_POST
def editar(request, versao_id):
    versao = get_object_or_404(Versao, id=versao_id)
    texto = _json(request).get("texto", "").strip()
    if not texto:
        return JsonResponse({"ok": False, "erro": "O texto não pode ficar vazio."}, status=400)
    servico.editar_versao(versao, texto)
    return JsonResponse({"ok": True})


def texto_42(request, laudo_id):
    laudo = get_object_or_404(Laudo, id=laudo_id)
    return HttpResponse("4.2 DADOS DA ENTREVISTA DE ANAMNESE\n\n" + laudo.texto_42(), content_type="text/plain; charset=utf-8")


def estatisticas(request):
    contagem, total = exemplos.contagem_motivos()
    rotulos = dict(Avaliacao.MOTIVOS)
    motivos = [(rotulos.get(m, m), n, round(100 * n / total) if total else 0) for m, n in contagem.most_common()]
    likes_por_tema = (
        Exemplo.objects.filter(fonte=Exemplo.LIKE, ativo=True).values("tema").annotate(n=Count("id")).order_by("-n")
    )
    return render(
        request,
        "laudos/estatisticas.html",
        {
            "motivos": motivos,
            "total_deslikes": total,
            "total_likes": Avaliacao.objects.filter(tipo=Avaliacao.LIKE).count(),
            "likes_por_tema": [(temas.ROTULOS.get(x["tema"], x["tema"]), x["n"]) for x in likes_por_tema],
            "reforcos": exemplos.reforcos(),
        },
    )
