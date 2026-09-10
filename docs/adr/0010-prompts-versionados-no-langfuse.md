# ADR 0010 — Prompts do fallback versionados no Langfuse

- Status: Aceito
- Data: 2026-09-05
- Fonte de verdade: `docs/architecture/observabilidade-e-metricas-langfuse.md`

## Responsáveis

Mateus de Castro

## Contexto

Os prompts do fallback eram funções Python em
`application/use_cases/fallback/prompts.py`. Mudar uma instrução exigia editar
código, abrir PR e reimplantar, e o efeito da mudança sobre as métricas só era
visível cruzando o histórico do git com o histórico do Langfuse na mão.

Três etapas usam LLM, e a maior delas não é um prompt: `layout_signature_candidato`
envia nove mensagens, cinco delas instrucionais. Tratar isso como "o prompt da
etapa" esconde qual das cinco mudou.

A ADR 0009 já estabeleceu que a observabilidade não pode derrubar o pipeline.
Buscar prompt pela rede em tempo de execução cria exatamente esse risco.

Alternativas consideradas:

1. **Um prompt por etapa**, com as instruções concatenadas. Simples, mas perde a
   granularidade: qualquer ajuste move a versão do bloco inteiro.
2. **Catorze prompts soltos**, um por função de instrução. Preserva a
   granularidade e perde o agrupamento: a tela vira uma lista sem etapa visível.
3. **Blocos individuais compostos em conjuntos por etapa**, usando a composição
   de prompts do Langfuse.

## Decisão

Adotar a **terceira opção**: 18 blocos, cada um um text prompt com linha do tempo
própria, agrupados em 6 conjuntos (chat prompts) que os referenciam por
`@@@langfusePrompt:name=...|label=...@@@`.

O conteúdo passa a ser controlado pelo Langfuse. A estrutura da conversa — ordem
das mensagens e onde os dados da execução entram — permanece no repositório, em
`application/use_cases/fallback/prompt_sets.py`.

`prompts.py` continua existindo como **espelho**: é o texto usado quando o
Langfuse não responde, e é o que `scripts/sincronizar_prompts_langfuse.py`
publica e compara.

## Justificativa

**Contra o prompt único por etapa.** A pergunta que motiva a mudança é "qual
alteração melhorou o resultado". Um bloco por etapa responde "a etapa mudou",
que é justamente o que já se sabia.

**Contra os prompts soltos.** Foi a alternativa levantada e recusada na
especificação: sem agrupamento, quem abre a tela não vê que cinco blocos formam
uma chamada só.

**A favor da composição.** Ela é o único arranjo que dá as duas coisas ao mesmo
tempo, e é primitivo nativo do Langfuse 3.178 — verificado nesta instância antes
de adotar, com um prompt descartável, e não inferido da documentação.

**Resolução bloco a bloco em execução, não pelo conjunto composto.** O Langfuse
sabe entregar o conjunto já resolvido, o que seria uma requisição em vez de
cinco. Mesmo assim a execução resolve bloco a bloco, porque é isso que permite
registrar no artefato a versão exata de cada bloco usado. Com o conjunto
resolvido, o registro seria "conjunto v2", e como a composição é por rótulo,
esse número não se move quando um bloco muda.

**Composição por rótulo, não por versão fixa.** Editar um bloco pela interface
passa a valer na execução seguinte, sem republicar o conjunto. É o que "controlar
pelo Langfuse" significa na prática. O custo é a versão do conjunto ficar parada,
compensado pela métrica `prompt_conjunto_versao`.

## Consequências

### Positivas

- cada bloco tem histórico, diff e autor próprios na interface;
- a métrica de uma etapa pode ser cortada por versão de prompt, porque a
  `generation` recebe `promptName`/`promptVersion` e o artefato registra a
  combinação exata de versões;
- ajustar um prompt deixa de exigir reimplantação;
- nenhuma dependência nova entra na imagem do Airflow: o resolvedor usa
  `urllib`, como o cliente de ingestão;
- o espelho em código mantém o texto auditável por git mesmo com o controle no
  Langfuse.

### Negativas

- o texto em produção pode divergir do repositório entre uma edição na interface
  e a atualização do espelho;
- a estrutura da conversa e o conteúdo passam a viver em lugares diferentes, e
  reordenar mensagens continua sendo mudança de código;
- `scripts/sincronizar_prompts_langfuse.py --puxar` não reescreve o código: ele
  salva o texto publicado e mostra o diff. Reescrever literais Python com prosa
  por programa é a forma mais fácil de corromper em silêncio justamente o texto
  que a mudança existe para proteger.

### Mitigação

A flag `ATLAS_PROMPTS_LANGFUSE_ENABLED` nasce desligada. Com ela desligada, ou
com o Langfuse fora do ar, a execução usa o espelho e o artefato registra
`origem: codigo`. A equivalência entre os dois caminhos é fixada por teste em
`tests/unit/application/test_prompt_sets.py`, que compara a sequência de
mensagens montada com a sequência original.

## Referências

- `docs/architecture/observabilidade-e-metricas-langfuse.md`
- `docs/guides/desenvolvimento-orientado-a-metricas.md`
- `docs/guides/langfuse-guia-do-zero.md`
- ADR 0008 — núcleo independente; Airflow como adaptador
- ADR 0009 — observabilidade por projeção de artefatos
