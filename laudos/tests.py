import io
from unittest import mock

from django.core.management import call_command
from django.test import TestCase, override_settings

from . import exemplos, gemini, prompt, servico
from .extracao import ArquivoInvalido, texto_do_arquivo
from .models import Avaliacao, Exemplo, Laudo, Mensagem, Paragrafo, Versao

class _SemRede:
    def __init__(self, *a, **k):
        raise AssertionError("Um teste tentou chamar a IA de verdade.")


def setUpModule():
    global _travas
    _travas = [mock.patch("openai.OpenAI", _SemRede), mock.patch("google.genai.Client", _SemRede)]
    for trava in _travas:
        trava.start()


def tearDownModule():
    for trava in _travas:
        trava.stop()


TEXTO_LONGO = " ".join(["palavra"] * 100)


def par(id_, tema, texto=TEXTO_LONGO, modo="geracao", base="", acrescimo=False, trechos=None):
    return gemini.ParagrafoIA(
        id=id_, tema=tema, texto=texto, trechos_origem=trechos or ["nota"], modo=modo,
        texto_base_usuaria=base, pediu_acrescimo=acrescimo,
    )


def resposta(*paragrafos, mensagem="", remover=None):
    return gemini.RespostaIA(mensagem=mensagem, paragrafos=list(paragrafos), remover=remover or [])


def verificacao(*itens):
    return gemini.RespostaVerificacao(itens=[gemini.ItemVerificacao(id=i, faltou=f, sem_apoio=s) for i, f, s in itens])


class FluxoTestes(TestCase):
    def setUp(self):
        self.laudo = Laudo.objects.create(paciente="Ana", anamnese="Sono: insônia. Social: poucos amigos.")

    def test_primeira_geracao_cria_paragrafos_ordenados(self):
        with mock.patch.object(gemini, "gerar", return_value=resposta(par("novo", "sono"), par("novo", "social"))), \
             mock.patch.object(gemini, "verificar", return_value=verificacao()):
            msg = servico.processar_mensagem(self.laudo, "")
        self.assertEqual(msg.erro, "")
        self.assertEqual([p.tema for p in self.laudo.paragrafos_atuais()], ["social", "sono"])
        self.assertEqual(Versao.objects.count(), 2)
        self.assertEqual(self.laudo.mensagens.first().texto, servico.PEDIDO_INICIAL)

    def test_problema_da_verificacao_gera_uma_reescrita(self):
        primeira = resposta(par("novo", "sono", texto="curto"))
        reescrita = resposta(par("N1", "sono", texto=TEXTO_LONGO + " insônia"))
        with mock.patch.object(gemini, "gerar", side_effect=[primeira, reescrita]) as gerar, \
             mock.patch.object(gemini, "verificar", side_effect=[verificacao(("N1", ["insônia"], [])), verificacao()]):
            servico.processar_mensagem(self.laudo, "")
        self.assertEqual(gerar.call_count, 2)
        versao = Versao.objects.get()
        self.assertIn("insônia", versao.texto)
        self.assertEqual(versao.faltou, [])

    def test_problema_que_sobra_vira_aviso(self):
        primeira = resposta(par("novo", "sono"))
        with mock.patch.object(gemini, "gerar", side_effect=[primeira, primeira]), \
             mock.patch.object(gemini, "verificar", side_effect=[
                 verificacao(("N1", [], ["dorme 3 horas"])), verificacao(("N1", [], ["dorme 3 horas"]))]):
            servico.processar_mensagem(self.laudo, "")
        self.assertEqual(Versao.objects.get().sem_apoio, ["dorme 3 horas"])

    def test_ajuste_cria_nova_versao_so_do_paragrafo_pedido(self):
        with mock.patch.object(gemini, "gerar", return_value=resposta(par("novo", "sono"), par("novo", "social"))), \
             mock.patch.object(gemini, "verificar", return_value=verificacao()):
            servico.processar_mensagem(self.laudo, "")
        sono = Paragrafo.objects.get(tema="sono")
        with mock.patch.object(gemini, "gerar", return_value=resposta(par(f"P{sono.id}", "sono", texto="novo texto", modo="ajuste"))), \
             mock.patch.object(gemini, "verificar", return_value=verificacao()):
            servico.processar_mensagem(self.laudo, "suaviza o sono")
        self.assertEqual(sono.versao_atual().numero, 2)
        self.assertEqual(sono.versao_atual().origem, Versao.AJUSTE)
        self.assertEqual(Paragrafo.objects.get(tema="social").versoes.count(), 1)

    def test_revisao_que_muda_demais_o_texto_dela_e_refeita(self):
        base = "Ana relata que dorme mal desde a adolescência e acorda cedo."
        mudou = resposta(par("novo", "sono", texto="A avaliada evidencia severa perturbação do repouso noturno.", modo="revisao", base=base))
        refeito = resposta(par("N1", "sono", texto=base, modo="revisao", base=base))
        with mock.patch.object(gemini, "gerar", side_effect=[mudou, refeito]) as gerar, \
             mock.patch.object(gemini, "verificar", return_value=verificacao()):
            servico.processar_mensagem(self.laudo, "arruma a escrita: " + base)
        self.assertEqual(gerar.call_count, 2)
        self.assertIn("mudou demais", gerar.call_args_list[1].args[1])
        self.assertEqual(Versao.objects.get().texto, base)

    def test_remover_desativa_paragrafo(self):
        with mock.patch.object(gemini, "gerar", return_value=resposta(par("novo", "sono"), par("novo", "social"))), \
             mock.patch.object(gemini, "verificar", return_value=verificacao()):
            servico.processar_mensagem(self.laudo, "")
        social = Paragrafo.objects.get(tema="social")
        with mock.patch.object(gemini, "gerar", return_value=resposta(remover=[f"P{social.id}"])):
            servico.processar_mensagem(self.laudo, "tira o social")
        self.assertEqual([p.tema for p in self.laudo.paragrafos_atuais()], ["sono"])

    def test_erro_do_gemini_vira_mensagem_de_erro(self):
        with mock.patch.object(gemini, "gerar", side_effect=gemini.ErroGemini("sem chave")):
            msg = servico.processar_mensagem(self.laudo, "")
        self.assertEqual(msg.erro, "sem chave")
        self.assertEqual(Paragrafo.objects.count(), 0)

    @override_settings(IA_PROVEDOR="openai", OPENAI_API_KEY="")
    def test_sem_chave_explica_como_configurar(self):
        msg = servico.processar_mensagem(self.laudo, "")
        self.assertIn("OPENAI_API_KEY", msg.erro)
        self.assertNotIn("OpenAI", msg.erro)


class AvaliacaoTestes(TestCase):
    def setUp(self):
        laudo = Laudo.objects.create(paciente="Ana", anamnese="notas")
        p = Paragrafo.objects.create(laudo=laudo, tema="sono")
        self.versao = Versao.objects.create(paragrafo=p, numero=1, texto="texto aprovado", trechos_origem=["insônia"], origem=Versao.GERACAO)

    def test_like_vira_par_de_exemplo(self):
        r = self.client.post(f"/versoes/{self.versao.id}/avaliar/", {"tipo": "like"}, content_type="application/json")
        self.assertEqual(r.status_code, 200)
        ex = Exemplo.objects.get()
        self.assertEqual((ex.fonte, ex.tema, ex.trecho_origem, ex.texto), (Exemplo.LIKE, "sono", "insônia", "texto aprovado"))
        self.assertEqual(exemplos.pares(["sono"])[0]["texto"], "texto aprovado")

    def test_deslike_guarda_motivos_e_desativa_exemplo(self):
        self.client.post(f"/versoes/{self.versao.id}/avaliar/", {"tipo": "like"}, content_type="application/json")
        self.client.post(
            f"/versoes/{self.versao.id}/avaliar/",
            {"tipo": "deslike", "motivos": ["curto", "inexistente"], "comentario": "faltou coisa"},
            content_type="application/json",
        )
        av = Avaliacao.objects.filter(tipo="deslike").get()
        self.assertEqual(av.motivos, ["curto"])
        self.assertFalse(Exemplo.objects.get().ativo)

    def test_reforco_aparece_quando_motivo_se_repete(self):
        for _ in range(3):
            Avaliacao.objects.create(versao=self.versao, tipo="deslike", motivos=["curto"])
        self.assertIn("curtos", exemplos.reforcos())
        self.assertIn("curtos", prompt.instrucao_sistema({}, [], exemplos.reforcos()))

    def test_edicao_da_usuaria_vira_nova_versao(self):
        self.client.post(f"/versoes/{self.versao.id}/editar/", {"texto": "minha versão"}, content_type="application/json")
        atual = self.versao.paragrafo.versao_atual()
        self.assertEqual((atual.numero, atual.origem, atual.texto), (2, Versao.EDICAO, "minha versão"))


class TelasEExemplosTestes(TestCase):
    def test_carregar_exemplos_sem_arquivo_real_usa_o_ficticio(self):
        from pathlib import Path
        from laudos.management.commands import carregar_exemplos

        with mock.patch.object(carregar_exemplos, "ARQUIVO_REAL", Path("/nao/existe.json")):
            call_command("carregar_exemplos", stdout=io.StringIO())
            call_command("carregar_exemplos", stdout=io.StringIO())
        estilo = exemplos.estilo()
        self.assertEqual(set(estilo), {"Laudo fictício de demonstração"})
        self.assertIn("Bruno", estilo["Laudo fictício de demonstração"][0])

    def test_criar_demo_monta_laudo_sem_chamar_a_ia(self):
        call_command("criar_demo", stdout=io.StringIO())
        laudo = Laudo.objects.get()
        self.assertEqual(len(laudo.paragrafos_atuais()), 9)
        self.assertEqual(self.client.get(f"/laudos/{laudo.id}/").status_code, 200)

    def test_telas_abrem(self):
        laudo = Laudo.objects.create(paciente="Ana", anamnese="notas")
        for url in ["/", f"/laudos/{laudo.id}/", "/estatisticas/", f"/laudos/{laudo.id}/texto/"]:
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_novo_laudo_com_texto_colado(self):
        r = self.client.post("/laudos/novo/", {"paciente": "Ana", "anamnese": "notas da anamnese"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Laudo.objects.get().anamnese, "notas da anamnese")

    def test_arquivo_de_formato_errado(self):
        arquivo = io.BytesIO(b"x")
        arquivo.name = "foto.png"
        with self.assertRaises(ArquivoInvalido):
            texto_do_arquivo(arquivo)

    def test_esquema_do_gemini_aceita_todos_os_temas(self):
        from . import temas
        for chave in temas.CHAVES:
            gemini.ParagrafoIA(id="novo", tema=chave, texto="t", trechos_origem=[], modo="geracao", texto_base_usuaria="", pediu_acrescimo=False)


@override_settings(IA_PROVEDOR="gemini", GEMINI_API_KEY="teste")
class TentativasTestes(TestCase):
    def _cliente(self, efeitos):
        cliente = mock.MagicMock()
        cliente.models.generate_content.side_effect = efeitos
        return mock.patch("google.genai.Client", return_value=cliente), cliente

    def test_sobrecarga_passageira_tenta_de_novo(self):
        ok = mock.MagicMock(text='{"itens": []}')
        patch, cliente = self._cliente([Exception("503 UNAVAILABLE"), ok])
        with patch, mock.patch("time.sleep") as dormir:
            r = gemini.verificar("s", "c")
        self.assertEqual(r.itens, [])
        self.assertEqual(cliente.models.generate_content.call_count, 2)
        dormir.assert_called_once_with(5)

    def test_sobrecarga_persistente_desiste_com_mensagem_clara(self):
        patch, cliente = self._cliente([Exception("503 UNAVAILABLE")] * 4)
        with patch, mock.patch("time.sleep"), self.assertRaises(gemini.ErroGemini) as ctx:
            gemini.verificar("s", "c")
        self.assertEqual(cliente.models.generate_content.call_count, 4)
        self.assertIn("sobrecarregada", str(ctx.exception))

    def test_sem_cota_nao_tenta_de_novo(self):
        patch, cliente = self._cliente([Exception("429 RESOURCE_EXHAUSTED limit: 0")])
        with patch, mock.patch("time.sleep"), self.assertRaises(gemini.ErroGemini) as ctx:
            gemini.verificar("s", "c")
        self.assertEqual(cliente.models.generate_content.call_count, 1)
        self.assertIn("crédito ou de cota", str(ctx.exception))
        self.assertNotIn("Gemini", str(ctx.exception))


@override_settings(IA_PROVEDOR="openai", OPENAI_API_KEY="teste", OPENAI_MODEL="gpt-teste")
class OpenAITestes(TestCase):
    def _resposta(self, conteudo):
        mensagem = mock.MagicMock(content=conteudo, refusal=None)
        return mock.MagicMock(choices=[mock.MagicMock(message=mensagem)])

    def test_openai_devolve_resposta_no_formato(self):
        cliente = mock.MagicMock()
        cliente.chat.completions.parse.return_value = self._resposta('{"itens": []}')
        with mock.patch("openai.OpenAI", return_value=cliente):
            r = gemini.verificar("sistema", "conteúdo")
        self.assertEqual(r.itens, [])
        kwargs = cliente.chat.completions.parse.call_args.kwargs
        self.assertEqual(kwargs["model"], "gpt-teste")
        self.assertIs(kwargs["response_format"], gemini.RespostaVerificacao)
        self.assertEqual(kwargs["messages"][0], {"role": "system", "content": "sistema"})

    def test_modelo_sem_temperatura_tenta_sem_ela(self):
        import httpx
        from openai import BadRequestError

        erro = BadRequestError("temperature not supported", response=httpx.Response(400, request=httpx.Request("POST", "http://x")), body=None)
        cliente = mock.MagicMock()
        cliente.chat.completions.parse.side_effect = [erro, self._resposta('{"itens": []}')]
        with mock.patch("openai.OpenAI", return_value=cliente):
            gemini.verificar("s", "c")
        self.assertNotIn("temperature", cliente.chat.completions.parse.call_args.kwargs)

    @override_settings(OPENAI_API_KEY="")
    def test_sem_chave_da_openai(self):
        with self.assertRaises(gemini.ErroGemini) as ctx:
            gemini.verificar("s", "c")
        self.assertIn("OPENAI_API_KEY", str(ctx.exception))
