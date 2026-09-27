from django.db import models

from . import temas


class Laudo(models.Model):
    paciente = models.CharField(max_length=200)
    anamnese = models.TextField(help_text="Texto das anotações de anamnese enviadas pela psicóloga.")
    arquivo_nome = models.CharField(max_length=255, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-criado_em"]

    def __str__(self):
        return self.paciente

    def paragrafos_atuais(self):
        """Parágrafos ativos, na ordem dos temas, cada um com a versão atual."""
        ativos = [p for p in self.paragrafos.filter(ativo=True).prefetch_related("versoes")]
        ativos.sort(key=lambda p: (temas.ORDEM.get(p.tema, 99), p.posicao, p.id))
        return ativos

    def texto_42(self):
        return "\n\n".join(p.versao_atual().texto for p in self.paragrafos_atuais() if p.versao_atual())


class Mensagem(models.Model):
    USUARIA, IA = "usuaria", "ia"
    laudo = models.ForeignKey(Laudo, on_delete=models.CASCADE, related_name="mensagens")
    papel = models.CharField(max_length=10, choices=[(USUARIA, "Usuária"), (IA, "IA")])
    texto = models.TextField(blank=True)
    erro = models.TextField(blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["criado_em", "id"]


class Paragrafo(models.Model):
    laudo = models.ForeignKey(Laudo, on_delete=models.CASCADE, related_name="paragrafos")
    tema = models.CharField(max_length=40, choices=temas.TEMAS)
    posicao = models.PositiveIntegerField(default=0, help_text="Ordem entre parágrafos do mesmo tema.")
    ativo = models.BooleanField(default=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    @property
    def rotulo(self):
        return temas.ROTULOS.get(self.tema, self.tema)

    def versao_atual(self):
        versoes = list(self.versoes.all())
        return max(versoes, key=lambda v: v.numero) if versoes else None


class Versao(models.Model):
    GERACAO, AJUSTE, REVISAO, EDICAO = "geracao", "ajuste", "revisao", "edicao_usuaria"
    ORIGENS = [
        (GERACAO, "Gerado pela IA"),
        (AJUSTE, "Ajuste pedido na conversa"),
        (REVISAO, "Revisão de texto da usuária"),
        (EDICAO, "Editado pela usuária"),
    ]
    paragrafo = models.ForeignKey(Paragrafo, on_delete=models.CASCADE, related_name="versoes")
    numero = models.PositiveIntegerField()
    texto = models.TextField()
    trechos_origem = models.JSONField(default=list, blank=True)
    origem = models.CharField(max_length=20, choices=ORIGENS)
    faltou = models.JSONField(default=list, blank=True)
    sem_apoio = models.JSONField(default=list, blank=True)
    mensagem = models.ForeignKey(Mensagem, null=True, blank=True, on_delete=models.SET_NULL, related_name="versoes")
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["paragrafo_id", "numero"]
        unique_together = [("paragrafo", "numero")]

    @property
    def palavras(self):
        return len(self.texto.split())

    @property
    def curto_demais(self):
        return self.paragrafo.tema not in temas.LINHAS_DE_DADOS and self.palavras < temas.MINIMO_PALAVRAS

    def avaliacao(self):
        return self.avaliacoes.order_by("-criado_em").first()


class Avaliacao(models.Model):
    LIKE, DESLIKE = "like", "deslike"
    MOTIVOS = [
        ("curto", "Ficou curto"),
        ("faltou", "Faltou informação"),
        ("inventou", "Inventou coisa"),
        ("sem_ligacao", "Sem ligação entre as frases"),
        ("rebuscado", "Rebuscado"),
        ("fora_de_ordem", "Fora de ordem"),
        ("mudou_meu_texto", "Mudou o meu texto"),
    ]
    versao = models.ForeignKey(Versao, on_delete=models.CASCADE, related_name="avaliacoes")
    tipo = models.CharField(max_length=10, choices=[(LIKE, "Like"), (DESLIKE, "Deslike")])
    motivos = models.JSONField(default=list, blank=True)
    comentario = models.TextField(blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)


class Exemplo(models.Model):
    """Exemplo que entra no prompt.

    Os pares vêm dos likes: o trecho das anotações e o parágrafo aprovado.
    Os exemplos de estilo vêm dos laudos base e não têm trecho de origem.
    """

    LAUDO_BASE, LIKE = "laudo_base", "like"
    tema = models.CharField(max_length=40, choices=temas.TEMAS)
    trecho_origem = models.TextField(blank=True)
    texto = models.TextField()
    fonte = models.CharField(max_length=20, choices=[(LAUDO_BASE, "Laudo base"), (LIKE, "Like")])
    grupo = models.CharField(max_length=100, blank=True, help_text="Laudo base de onde veio o exemplo.")
    posicao = models.PositiveIntegerField(default=0)
    versao = models.OneToOneField(Versao, null=True, blank=True, on_delete=models.SET_NULL, related_name="exemplo")
    ativo = models.BooleanField(default=True)
    criado_em = models.DateTimeField(auto_now_add=True)
