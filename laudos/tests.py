import io
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings

from . import exemplos, gemini, prompt, secoes, servico
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


def usuaria(nome="ana", admin=False):
    User = get_user_model()
    if admin:
        return User.objects.create_superuser(username=nome, password="Senha-forte-123")
    return User.objects.create_user(username=nome, password="Senha-forte-123")


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
        self.dona = usuaria()
        self.laudo = Laudo.objects.create(dono=self.dona, paciente="Ana", anamnese="Sono: insônia. Social: poucos amigos.")

    def test_primeira_geracao_cria_paragrafos_ordenados(self):
        # Os temas seguem a ordem da resposta (a das anotações); abertura antes e linhas de dados depois.
        blocos = resposta(par("novo", "sono"), par("novo", "saude"), par("novo", "gestacao"), par("novo", "social"))
        with mock.patch.object(gemini, "gerar", return_value=blocos), \
             mock.patch.object(gemini, "verificar", return_value=verificacao()):
            msg = servico.processar_mensagem(self.laudo, "")
        self.assertEqual(msg.erro, "")
        self.assertEqual([p.tema for p in self.laudo.paragrafos_atuais()], ["gestacao", "sono", "social", "saude"])
        self.assertEqual(Versao.objects.count(), 4)
        self.assertEqual(self.laudo.mensagens.first().texto, servico.PEDIDO_INICIAL)
        self.assertFalse(self.laudo.mensagens.first().pendente)

    def test_bloco_novo_num_ajuste_vai_para_o_fim_dos_temas(self):
        with mock.patch.object(gemini, "gerar", return_value=resposta(par("novo", "sono"), par("novo", "social"), par("novo", "saude"))), \
             mock.patch.object(gemini, "verificar", return_value=verificacao()):
            servico.processar_mensagem(self.laudo, "")
        with mock.patch.object(gemini, "gerar", return_value=resposta(par("novo", "ansiedade", modo="ajuste"))), \
             mock.patch.object(gemini, "verificar", return_value=verificacao()):
            servico.processar_mensagem(self.laudo, "inclua a ansiedade")
        self.assertEqual([p.tema for p in self.laudo.paragrafos_atuais()], ["sono", "social", "ansiedade", "saude"])

    def test_resposta_com_todos_os_blocos_reorganiza_a_secao(self):
        with mock.patch.object(gemini, "gerar", return_value=resposta(par("novo", "sono"), par("novo", "social"))), \
             mock.patch.object(gemini, "verificar", return_value=verificacao()):
            servico.processar_mensagem(self.laudo, "")
        sono, social = (Paragrafo.objects.get(tema=t) for t in ("sono", "social"))
        # Um ajuste que toca todos os blocos não mexe na ordem.
        invertida = resposta(par(f"P{social.id}", "social", modo="ajuste"), par(f"P{sono.id}", "sono", modo="ajuste"))
        with mock.patch.object(gemini, "gerar", return_value=invertida), \
             mock.patch.object(gemini, "verificar", return_value=verificacao()):
            servico.processar_mensagem(self.laudo, "corrija a gramática de tudo")
        self.assertEqual([p.tema for p in self.laudo.paragrafos_atuais()], ["sono", "social"])
        # Reescrever a seção inteira em modo geracao define a ordem de novo.
        regerada = resposta(par(f"P{social.id}", "social"), par(f"P{sono.id}", "sono"))
        with mock.patch.object(gemini, "gerar", return_value=regerada), \
             mock.patch.object(gemini, "verificar", return_value=verificacao()):
            servico.processar_mensagem(self.laudo, "refaça começando pelo social")
        self.assertEqual([p.tema for p in self.laudo.paragrafos_atuais()], ["social", "sono"])

    def test_falha_inesperada_vira_mensagem_de_erro_e_libera_a_secao(self):
        with mock.patch.object(gemini, "gerar", side_effect=RuntimeError("quebrou")):
            msg = servico.processar_mensagem(self.laudo, "")
        self.assertIn("Algo deu errado", msg.erro)
        self.assertIsNone(servico.em_andamento(self.laudo, "4.2"))

    def test_secao_fixa_continua_na_ordem_dos_tipos(self):
        with mock.patch.object(gemini, "gerar", return_value=resposta(par("novo", "fechamento"), par("novo", "abertura"))), \
             mock.patch.object(gemini, "verificar", return_value=verificacao()):
            servico.processar_mensagem(self.laudo, "", "5.2")
        self.assertEqual([p.tema for p in self.laudo.paragrafos_atuais("5.2")], ["abertura", "fechamento"])

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
        self.dona = usuaria()
        self.client.force_login(self.dona)
        laudo = Laudo.objects.create(dono=self.dona, paciente="Ana", anamnese="notas")
        p = Paragrafo.objects.create(laudo=laudo, tema="sono")
        self.versao = Versao.objects.create(paragrafo=p, numero=1, texto="texto aprovado", trechos_origem=["insônia"], origem=Versao.GERACAO)

    def test_like_vira_par_de_exemplo(self):
        r = self.client.post(f"/versoes/{self.versao.id}/avaliar/", {"tipo": "like"}, content_type="application/json")
        self.assertEqual(r.status_code, 200)
        ex = Exemplo.objects.get()
        self.assertEqual((ex.fonte, ex.tema, ex.trecho_origem, ex.texto), (Exemplo.LIKE, "sono", "insônia", "texto aprovado"))
        self.assertEqual(exemplos.pares(self.dona, "4.2", ["sono"])[0]["texto"], "texto aprovado")

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
        self.assertIn("curtos", exemplos.reforcos(self.dona))
        self.assertIn("curtos", prompt.instrucao_sistema(secoes.ANAMNESE, {}, [], exemplos.reforcos(self.dona)))

    def test_edicao_da_usuaria_vira_nova_versao(self):
        self.client.post(f"/versoes/{self.versao.id}/editar/", {"texto": "minha versão"}, content_type="application/json")
        atual = self.versao.paragrafo.versao_atual()
        self.assertEqual((atual.numero, atual.origem, atual.texto), (2, Versao.EDICAO, "minha versão"))


class TelasEExemplosTestes(TestCase):
    def setUp(self):
        self.dona = usuaria("paulo", admin=True)
        self.client.force_login(self.dona)

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
        call_command("criar_demo", usuario="paulo", stdout=io.StringIO())
        laudo = Laudo.objects.get()
        self.assertEqual(len(laudo.paragrafos_atuais()), 9)
        self.assertEqual(self.client.get(f"/laudos/{laudo.id}/").status_code, 200)

    def test_telas_abrem(self):
        laudo = Laudo.objects.create(dono=self.dona, paciente="Ana", anamnese="notas")
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


@override_settings(
    IA_PROVEDOR="openai", OPENAI_API_KEY="teste", OPENAI_MODEL="gpt-teste", OPENAI_MODEL_VERIFICACAO="gpt-confere",
    OPENAI_RACIOCINIO="medium", OPENAI_RACIOCINIO_VERIFICACAO="low",
)
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
        self.assertEqual(kwargs["model"], "gpt-confere")
        self.assertEqual(kwargs["reasoning_effort"], "low")
        self.assertNotIn("temperature", kwargs)
        self.assertIs(kwargs["response_format"], gemini.RespostaVerificacao)
        self.assertEqual(kwargs["messages"][0], {"role": "system", "content": "sistema"})

    def test_geracao_usa_o_modelo_principal_pensando(self):
        cliente = mock.MagicMock()
        cliente.chat.completions.parse.return_value = self._resposta('{"mensagem": "", "paragrafos": [], "remover": []}')
        with mock.patch("openai.OpenAI", return_value=cliente):
            gemini.gerar("sistema", "conteúdo", "4.2")
        kwargs = cliente.chat.completions.parse.call_args.kwargs
        self.assertEqual((kwargs["model"], kwargs["reasoning_effort"]), ("gpt-teste", "medium"))
        self.assertNotIn("temperature", kwargs)

    @override_settings(OPENAI_RACIOCINIO="")
    def test_sem_raciocinio_manda_temperatura(self):
        cliente = mock.MagicMock()
        cliente.chat.completions.parse.return_value = self._resposta('{"mensagem": "", "paragrafos": [], "remover": []}')
        with mock.patch("openai.OpenAI", return_value=cliente):
            gemini.gerar("sistema", "conteúdo", "4.2")
        kwargs = cliente.chat.completions.parse.call_args.kwargs
        self.assertIn("temperature", kwargs)
        self.assertNotIn("reasoning_effort", kwargs)

    @override_settings(OPENAI_RACIOCINIO_VERIFICACAO="")
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



class AcessoTestes(TestCase):
    def setUp(self):
        self.ana = usuaria("ana")
        self.bia = usuaria("bia")
        self.laudo_ana = Laudo.objects.create(dono=self.ana, paciente="Paciente da Ana", anamnese="notas")
        p = Paragrafo.objects.create(laudo=self.laudo_ana, tema="sono")
        self.versao_ana = Versao.objects.create(paragrafo=p, numero=1, texto="texto", origem=Versao.GERACAO)

    def test_sem_login_toda_pagina_manda_para_a_entrada(self):
        for url in ["/", f"/laudos/{self.laudo_ana.id}/", "/estatisticas/", f"/laudos/{self.laudo_ana.id}/texto/", "/senha/"]:
            r = self.client.get(url)
            self.assertEqual(r.status_code, 302, url)
            self.assertTrue(r["Location"].startswith("/entrar/"), url)
        r = self.client.post(f"/laudos/{self.laudo_ana.id}/secao/4.2/mensagem/", {"texto": "x"}, content_type="application/json")
        self.assertEqual(r.status_code, 302)

    def test_tela_de_entrada_e_admin_sao_publicos(self):
        self.assertEqual(self.client.get("/entrar/").status_code, 200)
        self.assertEqual(self.client.get("/admin/login/").status_code, 200)

    def test_login_certo_entra_e_sair_encerra(self):
        r = self.client.post("/entrar/", {"username": "ana", "password": "Senha-forte-123"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.client.get("/").status_code, 200)
        self.client.post("/sair/")
        self.assertEqual(self.client.get("/").status_code, 302)

    def test_bloqueia_depois_de_cinco_senhas_erradas(self):
        for _ in range(5):
            r = self.client.post("/entrar/", {"username": "ana", "password": "errada"})
            self.assertContains(r, "incorretos")
        r = self.client.post("/entrar/", {"username": "ana", "password": "Senha-forte-123"})
        self.assertContains(r, "Muitas tentativas")
        self.assertEqual(self.client.get("/").status_code, 302)

    def test_uma_usuaria_nao_ve_os_laudos_da_outra(self):
        self.client.force_login(self.bia)
        self.assertNotContains(self.client.get("/"), "Paciente da Ana")
        self.assertEqual(self.client.get(f"/laudos/{self.laudo_ana.id}/").status_code, 404)
        self.assertEqual(self.client.get(f"/laudos/{self.laudo_ana.id}/texto/").status_code, 404)
        r = self.client.post(f"/versoes/{self.versao_ana.id}/avaliar/", {"tipo": "like"}, content_type="application/json")
        self.assertEqual(r.status_code, 404)
        r = self.client.post(f"/versoes/{self.versao_ana.id}/editar/", {"texto": "invasão"}, content_type="application/json")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(self.versao_ana.paragrafo.versoes.count(), 1)

    def test_exemplo_aprovado_so_entra_no_prompt_de_quem_aprovou(self):
        self.client.force_login(self.ana)
        self.versao_ana.trechos_origem = ["insônia"]
        self.versao_ana.save()
        self.client.post(f"/versoes/{self.versao_ana.id}/avaliar/", {"tipo": "like"}, content_type="application/json")
        self.assertEqual(len(exemplos.pares(self.ana)), 1)
        self.assertEqual(exemplos.pares(self.bia), [])

    def test_novo_laudo_pertence_a_quem_criou(self):
        self.client.force_login(self.bia)
        self.client.post("/laudos/novo/", {"paciente": "Paciente da Bia", "anamnese": "notas"})
        self.assertEqual(Laudo.objects.get(paciente="Paciente da Bia").dono, self.bia)


class AdminTestes(TestCase):
    def _rodar(self, senha="DYw90088!x", **kw):
        with mock.patch.dict("os.environ", {"ADMIN_USUARIO": "Paulo", "ADMIN_SENHA": senha}):
            call_command("garantir_admin", stdout=io.StringIO(), **kw)

    def test_cria_superusuario_e_e_idempotente(self):
        Laudo.objects.create(paciente="sem dono", anamnese="x")
        self._rodar()
        self._rodar()
        User = get_user_model()
        admin = User.objects.get(username="Paulo")
        self.assertTrue(admin.is_superuser and admin.is_staff)
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(Laudo.objects.get().dono, admin)

    def test_nao_troca_senha_sem_pedir(self):
        self._rodar()
        self._rodar(senha="Outra-senha-forte-9")
        self.assertTrue(get_user_model().objects.get(username="Paulo").check_password("DYw90088!x"))
        self._rodar(senha="Outra-senha-forte-9", redefinir_senha=True)
        self.assertTrue(get_user_model().objects.get(username="Paulo").check_password("Outra-senha-forte-9"))

    def test_recusa_senha_fraca(self):
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            self._rodar(senha="123")



class SecoesTestes(TestCase):
    def setUp(self):
        self.dona = usuaria()
        self.client.force_login(self.dona)
        self.laudo = Laudo.objects.create(dono=self.dona, paciente="Ligia", anamnese="Queixa: esquece tudo. Sono: dorme mal.")

    def _gerar(self, chave, *blocos, mensagem=""):
        with mock.patch.object(gemini, "gerar", return_value=resposta(*blocos, mensagem=mensagem)) as gerar, \
             mock.patch.object(gemini, "verificar", return_value=verificacao()):
            servico.processar_mensagem(self.laudo, "", chave)
        return gerar

    def test_visao_geral_lista_as_secoes_em_ordem(self):
        r = self.client.get(f"/laudos/{self.laudo.id}/")
        conteudo = r.content.decode()
        posicoes = [conteudo.index(s.titulo) for s in secoes.SECOES]
        self.assertEqual(posicoes, sorted(posicoes))

    def test_cada_secao_abre_e_secao_inexistente_da_404(self):
        for s in secoes.SECOES:
            self.assertEqual(self.client.get(f"/laudos/{self.laudo.id}/secao/{s.chave}/").status_code, 200, s.chave)
        self.assertEqual(self.client.get(f"/laudos/{self.laudo.id}/secao/9/").status_code, 404)

    def test_blocos_e_conversas_ficam_separados_por_secao(self):
        self._gerar("2", par("novo", "demanda"))
        self._gerar("4.2", par("novo", "sono"))
        self.assertEqual([p.tema for p in self.laudo.paragrafos_atuais("2")], ["demanda"])
        self.assertEqual([p.tema for p in self.laudo.paragrafos_atuais("4.2")], ["sono"])
        self.assertEqual(self.laudo.mensagens.filter(secao="2").count(), 2)

    def test_secao_recebe_as_anteriores_como_contexto(self):
        self._gerar("2", par("novo", "demanda", texto="Demanda aprovada sobre esquecimentos."))
        self._gerar("4.2", par("novo", "sono", texto="Sono aprovado, dorme mal."))
        gerar = self._gerar("5.1", par("novo", "abertura"))
        sistema, conteudo = gerar.call_args.args[0], gerar.call_args.args[1]
        self.assertIn("Demanda aprovada sobre esquecimentos.", conteudo)
        self.assertIn("Sono aprovado, dorme mal.", conteudo)
        self.assertIn(secoes.RELACAO.titulo, sistema)
        self.assertEqual(gerar.call_args.args[2], "5.1")

    def test_exemplos_de_estilo_sao_da_secao_certa(self):
        Exemplo.objects.create(fonte=Exemplo.LAUDO_BASE, secao="5.2", tema="diagnostico", texto="EXEMPLO DE HIPOTESE", grupo="g")
        Exemplo.objects.create(fonte=Exemplo.LAUDO_BASE, secao="4.2", tema="sono", texto="EXEMPLO DE ANAMNESE", grupo="g")
        gerar = self._gerar("5.2", par("novo", "diagnostico"))
        sistema = gerar.call_args.args[0]
        self.assertIn("EXEMPLO DE HIPOTESE", sistema)
        self.assertNotIn("EXEMPLO DE ANAMNESE", sistema)

    def test_like_numa_secao_so_ensina_aquela_secao(self):
        self._gerar("2", par("novo", "demanda", trechos=["queixa"]))
        versao = Versao.objects.get()
        self.client.post(f"/versoes/{versao.id}/avaliar/", {"tipo": "like"}, content_type="application/json")
        self.assertEqual(len(exemplos.pares(self.dona, "2")), 1)
        self.assertEqual(exemplos.pares(self.dona, "4.2"), [])

    def test_tipo_de_bloco_de_outra_secao_vira_tipo_valido(self):
        self._gerar("5.1", par("novo", "sono"))
        self.assertEqual(Paragrafo.objects.get().tema, "outro")

    def test_esquema_de_cada_secao_so_aceita_os_tipos_dela(self):
        from pydantic import ValidationError

        Esquema = gemini.esquema_resposta("5.2")
        base = {"mensagem": "", "remover": [], "paragrafos": [{"id": "novo", "tema": "diagnostico", "texto": "t",
                "trechos_origem": [], "modo": "geracao", "texto_base_usuaria": "", "pediu_acrescimo": False}]}
        Esquema.model_validate(base)
        base["paragrafos"][0]["tema"] = "sono"
        with self.assertRaises(ValidationError):
            Esquema.model_validate(base)

    def test_copiar_laudo_junta_as_secoes_em_ordem(self):
        self._gerar("5.1", par("novo", "abertura", texto="Texto da 5.1."))
        self._gerar("2", par("novo", "demanda", texto="Texto da 2."))
        texto = self.client.get(f"/laudos/{self.laudo.id}/texto/").content.decode()
        self.assertLess(texto.index("2. DESCRIÇÃO DA DEMANDA"), texto.index("5.1 CONCLUSÃO"))
        self.assertLess(texto.index("Texto da 2."), texto.index("Texto da 5.1."))

    def test_aviso_quando_falta_a_secao_de_base(self):
        r = self.client.get(f"/laudos/{self.laudo.id}/secao/6/")
        self.assertContains(r, "ainda não foi escrita")
        self._gerar("5.2", par("novo", "diagnostico"))
        self._gerar("4.2", par("novo", "sono"))
        self._gerar("5.1", par("novo", "abertura"))
        self.assertNotContains(self.client.get(f"/laudos/{self.laudo.id}/secao/6/"), "ainda não foi escrita")

    def test_dados_antigos_ficam_na_4_2(self):
        p = Paragrafo.objects.create(laudo=self.laudo, tema="sono")
        self.assertEqual(p.secao, "4.2")

    def test_esquemas_das_secoes_sao_aceitos_no_modo_estrito(self):
        from openai.lib._pydantic import to_strict_json_schema

        for s in secoes.SECOES:
            esquema = to_strict_json_schema(gemini.esquema_resposta(s.chave))
            self.assertEqual(set(esquema["properties"]), {"mensagem", "paragrafos", "remover"})


class SegundoPlanoTestes(TestCase):
    def setUp(self):
        self.dona = usuaria()
        self.client.force_login(self.dona)
        self.laudo = Laudo.objects.create(dono=self.dona, paciente="Ana", anamnese="Sono: insônia.")
        self.url = f"/laudos/{self.laudo.id}/secao/4.2/"

    @override_settings(IA_EM_SEGUNDO_PLANO=True)
    def test_envio_responde_na_hora_e_roda_numa_thread(self):
        with mock.patch("threading.Thread") as Thread:
            r = self.client.post(self.url + "mensagem/", {"texto": ""}, content_type="application/json")
        self.assertEqual(r.status_code, 200)
        msg = self.laudo.mensagens.get()
        self.assertTrue(msg.pendente)
        self.assertEqual(Thread.call_args.kwargs["args"], (msg.id,))
        Thread.return_value.start.assert_called_once()
        self.assertEqual(self.client.get(self.url + "andamento/").json()["pendente"], True)
        self.assertContains(self.client.get(self.url), 'data-pendente="1"')

    @override_settings(IA_EM_SEGUNDO_PLANO=True)
    def test_segundo_envio_durante_a_geracao_e_recusado(self):
        Mensagem.objects.create(laudo=self.laudo, secao="4.2", papel=Mensagem.USUARIA, texto="gere", pendente=True)
        with mock.patch("threading.Thread") as Thread:
            r = self.client.post(self.url + "mensagem/", {"texto": "de novo"}, content_type="application/json")
        self.assertEqual(r.status_code, 409)
        Thread.assert_not_called()
        self.assertEqual(self.laudo.mensagens.count(), 1)

    def test_geracao_interrompida_vira_erro_depois_do_prazo(self):
        from django.utils import timezone

        velha = Mensagem.objects.create(laudo=self.laudo, secao="4.2", papel=Mensagem.USUARIA, texto="gere", pendente=True)
        Mensagem.objects.filter(id=velha.id).update(criado_em=timezone.now() - servico.PRAZO_DA_GERACAO * 2)
        self.assertEqual(self.client.get(self.url + "andamento/").json()["pendente"], False)
        self.assertEqual(self.laudo.mensagens.get(papel=Mensagem.IA).erro, servico.ERRO_INTERROMPIDA)

    @override_settings(IA_EM_SEGUNDO_PLANO=True)
    def test_thread_responde_e_libera_a_mensagem(self):
        msg = Mensagem.objects.create(laudo=self.laudo, secao="4.2", papel=Mensagem.USUARIA, texto="gere", pendente=True)
        with mock.patch.object(gemini, "gerar", return_value=resposta(par("novo", "sono"))), \
             mock.patch.object(gemini, "verificar", return_value=verificacao()), \
             mock.patch("django.db.connections.close_all"):
            servico._responder_em_thread(msg.id)
        msg.refresh_from_db()
        self.assertFalse(msg.pendente)
        self.assertEqual([p.tema for p in self.laudo.paragrafos_atuais()], ["sono"])


class RetomadaTestes(TestCase):
    """Geração que parou de dar sinal de vida (servidor reiniciou no meio) é retomada pela consulta da tela."""

    def setUp(self):
        self.dona = usuaria()
        self.client.force_login(self.dona)
        self.laudo = Laudo.objects.create(dono=self.dona, paciente="Ana", anamnese="Sono: insônia.")
        self.url = f"/laudos/{self.laudo.id}/secao/4.2/andamento/"

    def pendente(self, sem_sinal_ha, tentativas=1):
        from django.utils import timezone

        msg = Mensagem.objects.create(laudo=self.laudo, secao="4.2", papel=Mensagem.USUARIA, texto="gere", pendente=True)
        Mensagem.objects.filter(id=msg.id).update(vivo_em=timezone.now() - sem_sinal_ha, tentativas=tentativas)
        return msg

    @override_settings(IA_EM_SEGUNDO_PLANO=True)
    def test_geracao_parada_e_retomada(self):
        msg = self.pendente(servico.SEM_SINAL * 2)
        with mock.patch("threading.Thread") as Thread:
            self.assertEqual(self.client.get(self.url).json()["pendente"], True)
            self.client.get(self.url)  # a segunda consulta vê o sinal novo e não dispara de novo
        Thread.assert_called_once()
        self.assertEqual(Thread.call_args.kwargs["args"], (msg.id,))
        msg.refresh_from_db()
        self.assertEqual(msg.tentativas, 2)
        self.assertTrue(msg.pendente)

    @override_settings(IA_EM_SEGUNDO_PLANO=True)
    def test_geracao_com_sinal_recente_nao_e_retomada(self):
        self.pendente(servico.BATIMENTO)
        with mock.patch("threading.Thread") as Thread:
            self.assertEqual(self.client.get(self.url).json()["pendente"], True)
        Thread.assert_not_called()

    @override_settings(IA_EM_SEGUNDO_PLANO=True)
    def test_depois_das_tentativas_vira_erro(self):
        self.pendente(servico.SEM_SINAL * 2, tentativas=servico.TENTATIVAS_MAXIMAS)
        with mock.patch("threading.Thread") as Thread:
            self.assertEqual(self.client.get(self.url).json()["pendente"], False)
        Thread.assert_not_called()
        self.assertEqual(self.laudo.mensagens.get(papel=Mensagem.IA).erro, servico.ERRO_INTERROMPIDA)

    @override_settings(IA_EM_SEGUNDO_PLANO=True)
    def test_mensagem_nova_ja_nasce_com_sinal_de_vida(self):
        with mock.patch("threading.Thread"):
            self.client.post(f"/laudos/{self.laudo.id}/secao/4.2/mensagem/", {"texto": ""}, content_type="application/json")
        msg = self.laudo.mensagens.get()
        self.assertIsNotNone(msg.vivo_em)
        self.assertEqual(msg.tentativas, 1)


class ResistenciaTestes(TestCase):
    def setUp(self):
        self.dona = usuaria()
        self.client.force_login(self.dona)
        self.laudo = Laudo.objects.create(dono=self.dona, paciente="Ana", anamnese="Sono: insônia.")
        p = Paragrafo.objects.create(laudo=self.laudo, secao="4.2", tema="sono")
        self.versao = Versao.objects.create(paragrafo=p, numero=1, texto="Texto.", origem=Versao.GERACAO)

    @override_settings(DEBUG=False, SECURE_SSL_REDIRECT=True, ALLOWED_HOSTS=["site.exemplo"])
    def test_saude_responde_sem_login_https_nem_host(self):
        self.client.logout()
        r = self.client.get("/saude/", HTTP_HOST="10.0.0.5:10000")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"ok": True, "banco": True})

    def test_edicao_reenviada_nao_cria_outra_versao(self):
        for _ in range(2):
            r = self.client.post(f"/versoes/{self.versao.id}/editar/", {"texto": "Novo."}, content_type="application/json")
            self.assertEqual(r.status_code, 200)
        self.assertEqual(self.versao.paragrafo.versoes.count(), 2)

    def test_avaliacao_reenviada_conta_uma_vez(self):
        for _ in range(2):
            self.client.post(
                f"/versoes/{self.versao.id}/avaliar/", {"tipo": "deslike", "motivos": ["curto"]}, content_type="application/json"
            )
        self.assertEqual(Avaliacao.objects.count(), 1)

    def test_queda_de_conexao_com_a_ia_e_passageira(self):
        class APIConnectionError(Exception):
            pass

        class APITimeoutError(APIConnectionError):
            pass

        self.assertEqual(gemini._classificar(APIConnectionError("Connection error.")), (False, True))
        self.assertEqual(gemini._classificar(APITimeoutError("Request timed out.")), (False, False))


class PerfilEExemplosTestes(TestCase):
    def test_faixa_e_queixas(self):
        from . import perfil

        self.assertEqual(perfil.faixa("Idade: 9 anos. A professora relata..."), "crianca")
        self.assertEqual(perfil.faixa("Trabalha e faz faculdade; a esposa conta..."), "adulto")
        self.assertEqual(perfil.queixas("Suspeita de TEA e sintomas ansiosos"), ["ansiedade", "tea"])

    def test_estilo_escolhe_seccoes_inteiras_dos_casos_mais_parecidos(self):
        perfis = {
            "Criança TDAH": {"faixa": "crianca", "queixas": ["tdah"]},
            "Adulto TEA": {"faixa": "adulto", "queixas": ["tea"]},
            "Adulto TEA e ansiedade": {"faixa": "adulto", "queixas": ["ansiedade", "tea"]},
            "Adulto humor": {"faixa": "adulto", "queixas": ["humor"]},
            "Criança aprendizagem": {"faixa": "crianca", "queixas": ["aprendizagem"]},
        }
        for grupo, p in perfis.items():
            Exemplo.objects.create(fonte=Exemplo.LAUDO_BASE, secao="4.2", tema="", texto=f"texto {grupo}", grupo=grupo, perfil=p)
        escolhidos = exemplos.estilo("4.2", {"faixa": "adulto", "queixas": ["tea", "ansiedade"]})
        self.assertEqual(len(escolhidos), exemplos.MAXIMO_LAUDOS_BASE)
        self.assertEqual(list(escolhidos)[:2], ["Adulto TEA e ansiedade", "Adulto TEA"])
        self.assertNotIn("Criança aprendizagem", escolhidos)

    def test_pares_do_gemini_entram_e_a_mesma_faixa_vem_primeiro(self):
        dona = usuaria()
        Exemplo.objects.create(fonte=Exemplo.GEMINI, dono=dona, secao="4.2", tema="sono", trecho_origem="n",
                               texto="adulto", perfil={"faixa": "adulto"})
        Exemplo.objects.create(fonte=Exemplo.GEMINI, dono=dona, secao="4.2", tema="sono", trecho_origem="n",
                               texto="criança", perfil={"faixa": "crianca"})
        Exemplo.objects.create(fonte=Exemplo.GEMINI, dono=dona, secao="4.2", tema="sono", trecho_origem="n",
                               texto="criança 2", perfil={"faixa": "crianca"})
        textos = [p["texto"] for p in exemplos.pares(dona, "4.2", ["sono"], "adulto")]
        self.assertEqual(textos[0], "adulto")
        self.assertEqual(len(textos), exemplos.POR_TEMA)
        self.assertEqual(exemplos.pares(usuaria("bia"), "4.2"), [])

    def test_carregar_exemplos_no_formato_novo(self):
        import json
        import tempfile
        from pathlib import Path
        from laudos.management.commands import carregar_exemplos

        dados = {"laudo_01": {"nome": "Laudo 1 (adulto)", "perfil": {"faixa": "adulto", "queixas": ["tea"]},
                              "secoes": {"4.2": [{"tema": "", "texto": "seção inteira"}], "2": [{"texto": "demanda"}]}}}
        with tempfile.TemporaryDirectory() as pasta:
            arquivo = Path(pasta) / "laudos_base.json"
            arquivo.write_text(json.dumps(dados), encoding="utf-8")
            with mock.patch.object(carregar_exemplos, "ARQUIVO_REAL", arquivo):
                call_command("carregar_exemplos", stdout=io.StringIO())
        ex = Exemplo.objects.get(secao="4.2")
        self.assertEqual((ex.grupo, ex.texto, ex.perfil["faixa"]), ("Laudo 1 (adulto)", "seção inteira", "adulto"))
        self.assertEqual(Exemplo.objects.count(), 2)


class LaudosBaseTestes(TestCase):
    def test_secao_e_achada_pelo_titulo_e_nao_pelo_numero(self):
        from . import laudos_base

        self.assertEqual(laudos_base.secao_do_titulo("4.1 HISTÓRIA CLÍNICA"), "4.2")
        self.assertIsNone(laudos_base.secao_do_titulo("4.2 OBSERVAÇÕES DO COMPORTAMENTO"))
        self.assertEqual(laudos_base.secao_do_titulo("2. DESCRIÇÃO DA DEMANDA"), "2")
        self.assertEqual(laudos_base.secao_do_titulo("6. RECOMENDAÇÕES E ENCAMINHAMENTOS"), "6")

    def test_secoes_divide_a_conclusao_e_ignora_rodape(self):
        from . import laudos_base

        paginas = [[
            "2. DESCRIÇÃO DA DEMANDA",
            "A avaliação foi solicitada pela mãe.",
            "4.1 HISTÓRIA CLÍNICA",
            "▪ Gestação/Parto: sem intercorrências.",
            "▪ Queixas principais: No que se refere ao sono, relata",
            " insônia desde a infância.",
            "      Quanto à rotina, menciona atrasos.",
            "4.2 OBSERVAÇÕES DO COMPORTAMENTO",
            "Colaborou bem.",
            "5. CONCLUSÃO",
            "Com base nos testes, a atenção ficou preservada.",
            "      Levando-se em conta os critérios diagnósticos do DSM-5-TR, fica estabelecido.",
            "3 de 18",
        ]]
        secoes_ = laudos_base.secoes(paginas)
        self.assertEqual(secoes_["2"], ["A avaliação foi solicitada pela mãe."])
        self.assertEqual(secoes_["4.2"], [
            "- Gestação/Parto: sem intercorrências.",
            "- Queixas principais: No que se refere ao sono, relata insônia desde a infância.",
            "Quanto à rotina, menciona atrasos.",
        ])
        self.assertEqual(secoes_["5.1"], ["Com base nos testes, a atenção ficou preservada."])
        self.assertIn("DSM-5-TR", secoes_["5.2"][0])
        self.assertNotIn("Colaborou", " ".join(sum(secoes_.values(), [])))

    def test_anonimizacao_troca_paciente_familiar_e_profissional(self):
        from . import laudos_base

        ident = {"nome": "Joana Pereira da Costa", "sexo": "F", "idade": 30}
        textos = [
            "Rosa Maria, mãe de Joana, relata que Joana Pereira dorme mal. A adaptação foi considerada boa por Rosa Maria.",
            "- Profissional que acompanha: Psiquiatra Carlos Alberto Souza – CRM 12345 (cerca de 2 anos).",
        ]
        anonimos, trocas = laudos_base.anonimizar(textos, ident, "Helena")
        self.assertEqual(anonimos[0], "A mãe relata que Helena dorme mal. A adaptação foi considerada boa pela mãe.")
        self.assertEqual(anonimos[1], "- Profissional que acompanha: Psiquiatra (cerca de 2 anos).")
        for nome in ("Joana", "Rosa", "Carlos", "12345"):
            self.assertNotIn(nome, " ".join(anonimos))

    def test_paciente_nao_vira_parente_por_aposto(self):
        from . import laudos_base

        ident = {"nome": "Pedro Alves", "sexo": "M", "idade": 30}
        anonimos, _ = laudos_base.anonimizar(["Segundo o irmão, Pedro dorme mal. Pedro estuda."], ident, "Bruno")
        self.assertEqual(anonimos[0], "Segundo o irmão, Bruno dorme mal. Bruno estuda.")


class ImportarGeminiTestes(TestCase):
    def test_importa_so_os_aprovados_na_revisao_e_e_idempotente(self):
        import json
        import tempfile
        from pathlib import Path

        dona = usuaria()
        linhas = [
            {"id": "c1", "secao": "4.2", "tema": "sono", "faixa": "adulto", "texto": "Texto bom.", "trecho_origem": "nota", "decisao": "manter"},
            {"id": "c2", "secao": "6", "tema": "psicologia", "faixa": "crianca", "texto": "Outro.", "trecho_origem": "", "decisao": "corrigir"},
            {"id": "c3", "secao": "4.2", "tema": "sono", "faixa": "adulto", "texto": "Ruim.", "trecho_origem": "x", "decisao": "descartar"},
        ]
        with tempfile.TemporaryDirectory() as pasta:
            arquivo = Path(pasta) / "revisados.jsonl"
            arquivo.write_text("\n".join(json.dumps(l) for l in linhas), encoding="utf-8")
            for _ in range(2):
                call_command("importar_gemini", str(arquivo), usuario="ana", stdout=io.StringIO())
        self.assertEqual(sorted(Exemplo.objects.values_list("grupo", flat=True)), ["c1", "c2"])
        self.assertEqual(exemplos.pares(dona, "4.2", ["sono"], "adulto")[0]["texto"], "Texto bom.")


class EscolhaDoModeloTestes(TestCase):
    def setUp(self):
        self.dona = usuaria()
        self.client.force_login(self.dona)
        self.laudo = Laudo.objects.create(dono=self.dona, paciente="Ana", anamnese="Sono: insônia.")
        self.url = f"/laudos/{self.laudo.id}/secao/4.2/"

    @override_settings(IA_MODELOS=[("gpt-6-sol", "Melhor"), ("gpt-6-luna", "Barato")], OPENAI_RACIOCINIO="medium")
    def test_tela_mostra_os_modelos_e_a_escolha_chega_na_ia(self):
        self.assertContains(self.client.get(self.url), '<option value="gpt-6-luna">')
        with mock.patch.object(gemini, "gerar", return_value=resposta(par("novo", "sono"))) as gerar, \
             mock.patch.object(gemini, "verificar", return_value=verificacao()):
            r = self.client.post(self.url + "mensagem/", {"texto": "", "modelo": "gpt-6-luna", "pensar": False},
                                 content_type="application/json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(gerar.call_args.args[3], ("gpt-6-luna", "none"))
        ia = self.laudo.mensagens.get(papel=Mensagem.IA)
        self.assertEqual(ia.modelo, "gpt-6-luna, sem pensar")
        self.assertContains(self.client.get(self.url), "Escrito com gpt-6-luna, sem pensar")

    @override_settings(IA_MODELOS=[("gpt-6-sol", "Melhor")], OPENAI_RACIOCINIO="high")
    def test_modelo_fora_da_lista_cai_no_padrao(self):
        self.assertEqual(gemini.escolha_valida("gpt-qualquer", True), ("", "high"))
        self.assertEqual(gemini.escolha_valida("gpt-6-sol", False), ("gpt-6-sol", "none"))

    @override_settings(IA_PROVEDOR="openai", OPENAI_API_KEY="teste", OPENAI_MODEL="gpt-4o-mini", OPENAI_RACIOCINIO="medium")
    def test_modelo_sem_raciocinio_tenta_de_novo_com_temperatura(self):
        import httpx
        from openai import BadRequestError

        erro = BadRequestError("Unsupported parameter: 'reasoning_effort'",
                               response=httpx.Response(400, request=httpx.Request("POST", "http://x")), body=None)
        ok = mock.MagicMock(choices=[mock.MagicMock(message=mock.MagicMock(
            content='{"mensagem": "", "paragrafos": [], "remover": []}', refusal=None))])
        cliente = mock.MagicMock()
        cliente.chat.completions.parse.side_effect = [erro, ok]
        with mock.patch("openai.OpenAI", return_value=cliente):
            gemini.gerar("s", "c", "4.2")
        kwargs = cliente.chat.completions.parse.call_args.kwargs
        self.assertIn("temperature", kwargs)
        self.assertNotIn("reasoning_effort", kwargs)

    def test_resposta_que_chega_depois_do_prazo_e_descartada(self):
        msg = Mensagem.objects.create(laudo=self.laudo, secao="4.2", papel=Mensagem.USUARIA, texto="gere", pendente=True)
        Mensagem.objects.filter(id=msg.id).update(pendente=False)  # o prazo venceu e a tela já mostrou o erro
        with mock.patch.object(gemini, "gerar", return_value=resposta(par("novo", "sono"))), \
             mock.patch.object(gemini, "verificar", return_value=verificacao()):
            self.assertIsNone(servico.responder(msg))
        self.assertEqual(Paragrafo.objects.count(), 0)

    def test_pendencia_vencida_gera_um_erro_so(self):
        from django.utils import timezone

        velha = Mensagem.objects.create(laudo=self.laudo, secao="4.2", papel=Mensagem.USUARIA, texto="gere", pendente=True)
        Mensagem.objects.filter(id=velha.id).update(criado_em=timezone.now() - servico.PRAZO_DA_GERACAO * 2)
        servico.em_andamento(self.laudo, "4.2")
        servico.em_andamento(self.laudo, "4.2")
        self.assertEqual(self.laudo.mensagens.filter(erro=servico.ERRO_INTERROMPIDA).count(), 1)


class ConferenciaNoCodigoTestes(TestCase):
    def setUp(self):
        self.dona = usuaria()
        self.laudo = Laudo.objects.create(dono=self.dona, paciente="Ana", anamnese="Social: poucos amigos. Sono: dorme mal.")

    def _rodar(self, *respostas, texto=""):
        with mock.patch.object(gemini, "gerar", side_effect=list(respostas)) as gerar, \
             mock.patch.object(gemini, "verificar", return_value=verificacao()):
            servico.processar_mensagem(self.laudo, texto)
        return gerar

    def test_tema_repetido_na_resposta_vira_um_paragrafo_e_e_costurado(self):
        primeira = resposta(par("novo", "social", texto="Ana tem poucos amigos."), par("novo", "sono"),
                            par("novo", "social", texto="Prefere ficar em casa."))
        costurada = resposta(par("N1", "social", texto="Ana tem poucos amigos e prefere ficar em casa."))
        gerar = self._rodar(primeira, costurada)
        self.assertEqual([p.tema for p in self.laudo.paragrafos_atuais()], ["social", "sono"])
        self.assertIn("juntou parágrafos do mesmo tema", gerar.call_args_list[1].args[1])
        self.assertIn("Ana tem poucos amigos. Prefere ficar em casa.", gerar.call_args_list[1].args[1])
        self.assertEqual(Paragrafo.objects.get(tema="social").versao_atual().texto, "Ana tem poucos amigos e prefere ficar em casa.")

    def test_bloco_novo_de_tema_existente_entra_no_paragrafo_que_ja_existe(self):
        self._rodar(resposta(par("novo", "social", texto="Ana tem poucos amigos."), par("novo", "sono")))
        social = Paragrafo.objects.get(tema="social")
        costurada = resposta(par(f"P{social.id}", "social", texto="Ana tem poucos amigos e evita festas.", modo="ajuste"))
        self._rodar(resposta(par("novo", "social", texto="Evita festas.", modo="ajuste")), costurada, texto="inclua as festas")
        self.assertEqual(Paragrafo.objects.filter(tema="social", ativo=True).count(), 1)
        self.assertEqual(social.versao_atual().texto, "Ana tem poucos amigos e evita festas.")

    def test_palavra_proibida_pede_reescrita_e_o_que_sobra_vira_aviso(self):
        ruim = resposta(par("novo", "sono", texto="Ana tem paixão por dormir tarde. " + TEXTO_LONGO))
        gerar = self._rodar(ruim, ruim)
        self.assertIn("Não use paixão", gerar.call_args_list[1].args[1])
        self.assertTrue(any("paixão" in e for e in Versao.objects.get().estilo))

    def test_aspas_que_sobram_saem_pelo_codigo(self):
        com_aspas = resposta(par("novo", "sono", texto='Ana diz "durmo mal" desde sempre. ' + TEXTO_LONGO))
        self._rodar(com_aspas, com_aspas)
        versao = Versao.objects.get()
        self.assertNotIn('"', versao.texto)
        self.assertFalse(any("aspas" in e for e in versao.estilo))

    def test_verbo_repetido_e_voz_da_avaliadora_sao_apontados(self):
        from . import conferencia

        bloco = par("N1", "social", texto="Ana relata poucos amigos. Relata também timidez, o que sugere ansiedade.")
        pedidos = conferencia.problemas_de_estilo(secoes.ANAMNESE, [bloco], "")["N1"]
        self.assertTrue(any("relata" in p for p in pedidos))
        self.assertTrue(any("o que sugere" in p for p in pedidos))

    def test_intensificador_so_passa_se_estiver_nas_anotacoes(self):
        from . import conferencia

        bloco = par("N1", "sono", texto="Ana tem insônia severa.")
        self.assertIn("N1", conferencia.problemas_de_estilo(secoes.ANAMNESE, [bloco], "dorme mal"))
        self.assertEqual(conferencia.problemas_de_estilo(secoes.ANAMNESE, [bloco], "insônia severa"), {})

    def test_texto_que_ela_mandou_revisar_nao_passa_pelas_regras(self):
        from . import conferencia

        dela = par("N1", "sono", texto="Ana tem paixão por dormir.", modo="revisao", base="Ana tem paixão por dormir.")
        self.assertEqual(conferencia.problemas_de_estilo(secoes.ANAMNESE, [dela], ""), {})
