"""Resolve o texto dos prompts do fallback a partir do Langfuse.

O Langfuse passa a ser o ponto de controle do *conteudo* dos prompts: cada bloco
e um prompt versionado, editavel pela interface, e a execucao seguinte ja usa a
nova versao. A *estrutura* da conversa continua no repositorio, em
`application/use_cases/fallback/prompt_sets.py`.

Duas propriedades sao inegociaveis aqui, pelas mesmas razoes da ADR 0009:

1. Nenhuma falha derruba o pipeline. Rede fora, credencial errada, prompt
   inexistente ou resposta malformada caem para o espelho em codigo e seguem.
2. Toda resolucao e registrada. O artefato do MinIO guarda qual bloco, em qual
   versao e de qual origem produziu cada chamada, senao a atribuicao de uma
   mudanca de metrica a uma mudanca de prompt seria adivinhacao.

Como o cliente de ingestao, usa apenas a biblioteca padrao: nenhuma dependencia
nova entra na imagem do Airflow por causa disto.
"""

from __future__ import annotations

import base64
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from document_processing.shared.config.runtime import RUNTIME_CONFIG_LOADER, RuntimeConfigLoader

LOGGER = logging.getLogger(__name__)

ORIGEM_LANGFUSE = "langfuse"
ORIGEM_CODIGO = "codigo"


@dataclass(frozen=True)
class ResolvedPrompt:
    """Um bloco de prompt resolvido, com a procedencia preservada."""

    nome: str
    texto: str
    origem: str
    versao: int | None = None
    label: str | None = None

    def como_registro(self) -> dict[str, Any]:
        """Forma persistida no artefato de entrada da LLM."""
        return {
            "nome": self.nome,
            "versao": self.versao,
            "label": self.label,
            "origem": self.origem,
        }


class LangfusePromptRegistry:
    """Busca prompts no Langfuse com cache por processo e queda para o codigo."""

    def __init__(self, *, config_loader: RuntimeConfigLoader | None = None) -> None:
        self.config_loader = config_loader or RUNTIME_CONFIG_LOADER
        self._cache: dict[tuple[str, str], ResolvedPrompt] = {}

    def limpar_cache(self) -> None:
        """Descarta o cache; usado em teste e entre execucoes longas."""
        self._cache.clear()

    def resolve(self, nome: str, *, espelho: str) -> ResolvedPrompt:
        """Devolve o texto publicado do bloco, ou o espelho de codigo.

        `espelho` e o texto que vive no repositorio. Ele nao e um valor de
        emergencia improvisado: e a mesma copia que o script de sincronizacao
        publica e traz de volta, entao cair para ele nao muda o comportamento
        enquanto ninguem editar o prompt pela interface.
        """
        config = self.config_loader.load_local_platform_config()
        if not getattr(config, "prompts_langfuse_enabled", False):
            return ResolvedPrompt(nome=nome, texto=espelho, origem=ORIGEM_CODIGO)

        label = getattr(config, "prompt_label", "production")
        chave = (nome, label)
        if chave in self._cache:
            return self._cache[chave]

        resolvido = self._buscar(nome, label=label, config=config)
        if resolvido is None:
            # Nao cacheia a falha: uma indisponibilidade momentanea nao deve
            # congelar o processo inteiro no espelho de codigo.
            return ResolvedPrompt(nome=nome, texto=espelho, origem=ORIGEM_CODIGO)

        self._cache[chave] = resolvido
        return resolvido

    def versao_publicada(self, nome: str) -> int | None:
        """Versao atual de um prompt, sem exigir que ele seja texto.

        Serve para os conjuntos, que sao chat prompts e existem para agrupar os
        blocos na interface e para dar a generation um alvo estavel. Devolve None
        quando o Langfuse nao responde, e nesse caso a generation simplesmente
        nao recebe o vinculo.
        """
        config = self.config_loader.load_local_platform_config()
        if not getattr(config, "prompts_langfuse_enabled", False):
            return None
        label = getattr(config, "prompt_label", "production")
        chave = (f"__versao__{nome}", label)
        if chave in self._cache:
            return self._cache[chave].versao
        payload = self._payload(nome, label=label, config=config)
        versao = payload.get("version") if isinstance(payload, dict) else None
        if not isinstance(versao, int):
            return None
        self._cache[chave] = ResolvedPrompt(
            nome=nome, texto="", origem=ORIGEM_LANGFUSE, versao=versao, label=label
        )
        return versao

    def _buscar(self, nome: str, *, label: str, config: Any) -> ResolvedPrompt | None:
        """Faz o GET do prompt; devolve None em qualquer falha."""
        payload = self._payload(nome, label=label, config=config)
        if payload is None:
            return None

        texto = payload.get("prompt")
        if not isinstance(texto, str) or not texto.strip():
            # Um bloco e sempre text prompt. Chat prompt aqui significa que o
            # nome foi trocado por um conjunto, e usar o espelho e mais seguro
            # do que serializar uma lista de mensagens como se fosse texto.
            LOGGER.warning("Prompt '%s' nao e texto utilizavel. Usando o codigo.", nome)
            return None

        versao = payload.get("version")
        return ResolvedPrompt(
            nome=nome,
            texto=texto,
            origem=ORIGEM_LANGFUSE,
            versao=int(versao) if isinstance(versao, int) else None,
            label=label,
        )


    def _payload(self, nome: str, *, label: str, config: Any) -> dict[str, Any] | None:
        """GET autenticado de um prompt; devolve None em qualquer falha."""
        base = str(getattr(config, "langfuse_base_url", "")).rstrip("/")
        public_key = getattr(config, "langfuse_public_key", "")
        secret_key = getattr(config, "langfuse_secret_key", "")
        if not (base and public_key and secret_key):
            return None
        url = (
            f"{base}/api/public/v2/prompts/{urllib.parse.quote(nome, safe='')}"
            f"?label={urllib.parse.quote(label)}"
        )
        auth = base64.b64encode(f"{public_key}:{secret_key}".encode()).decode()
        request = urllib.request.Request(url, headers={"Authorization": f"Basic {auth}"})
        try:
            timeout = int(getattr(config, "langfuse_timeout_seconds", 10))
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode() or "{}")
        except (
            urllib.error.HTTPError,
            urllib.error.URLError,
            TimeoutError,
            ValueError,
            OSError,
        ) as exc:
            LOGGER.warning(
                "Prompt '%s' nao resolvido pelo Langfuse (%s). Usando o codigo.", nome, exc
            )
            return None


LANGFUSE_PROMPT_REGISTRY = LangfusePromptRegistry()
