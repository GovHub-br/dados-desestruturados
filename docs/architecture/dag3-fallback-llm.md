# Plano de Implementacao da DAG 3: `dag_valida_e_fallback_llm`

## Objetivo

Implementar a DAG 3 como fallback assistido por LLM para casos em que a DAG 2
detecta incompatibilidade no `validacao_layout_signature.json`.

A DAG 3 deve:

- ler a falha produzida pela DAG 2;
- classificar o tipo de problema;
- gerar diretamente um layout signature candidato;
- validar o candidato antes de qualquer persistencia ou publicacao;
- permitir revalidacao pela DAG 2;
- publicar automaticamente uma nova versao versionada quando o candidato for aprovado;
- nunca modificar um layout signature existente.

## Principio Central

A DAG 3 nao corrige o dado final e nao gera uma proposta intermediaria como
artefato principal.

Ela usa a LLM para gerar diretamente um `layout_signature` candidato, limitado
ao contexto estruturado montado pelas etapas anteriores. Esse candidato pode
alterar `fontes_relevantes`, `regras_deteccao_mudanca`, `mapeamento_canonico` e
metadados estruturais de evidencia. A DAG 2 continua sendo a etapa que prova
deterministicamente se o candidato funciona.

Fluxo simples esperado:

```text
Falha da DAG 2
  -> DAG 3 classifica a falha
  -> DAG 3 monta contexto focado
  -> LLM gera layout signature candidato
  -> DAG 3 valida o candidato
  -> DAG 2 revalida com layout candidato
  -> DAG 3 publica nova versao somente se a revalidacao passar
```

Quando o problema exigir redescoberta de origem, a DAG 3 pode incluir uma etapa
previa de selecao de artefatos usando `inventory.json`. Mesmo nesse caso, a LLM
continua tendo uma unica responsabilidade final: gerar um `layout_signature`
candidato, nunca gerar `schema_saida_resolvido`.

## Etapa 1: Contrato Operacional da DAG 3

### Objetivo

Definir claramente o payload de entrada da DAG 3.

### Implementacoes

- Ajustar `dag_valida_e_fallback_llm.py` para receber `dag_run.conf` vindo da DAG 2.
- Validar campos minimos:
  - `company_slug`;
  - `document_id`;
  - `execution_id`, sempre entendido como a execucao de origem da DAG 1/DAG 2;
  - `manifest_key`;
  - `trigger_origin_dag`.
- Gerar um `fallback_execution_id` proprio da DAG 3 a partir do `run_id` atual
  da DAG 3, para que cada nova tentativa de fallback grave artefatos em uma
  pasta propria e nao sobrescreva evidencias de execucoes anteriores.

### Criterio de Aceite

- Se `dag_run.conf` estiver incompleto, a DAG falha com erro claro.
- Se estiver completo, segue para a proxima etapa.
- Nenhum artefato e escrito ainda.
- Uma nova execucao manual da DAG 3 cria um novo prefixo de fallback, mesmo que
  esteja analisando o mesmo `document_id` e o mesmo `execution_id` de origem.

## Etapa 2: Leitura dos Artefatos da DAG 2

### Objetivo

Carregar os artefatos da execucao incompativel.

### Implementacoes

Criar um service novo:

- `FallbackLlmService`

Metodos iniciais:

- `load_fallback_context(conf)`;
- `load_validation_artifact(...)`;
- `load_audit_artifact(...)`;
- `load_base_layout_signature(...)`;
- `load_semantic_contract(...)`;
- `load_extraction_manifest(...)`.

### Artefatos Lidos

- `validacao_layout_signature.json`;
- `auditoria_resolucao.json`;
- layout signature base ou versao vigente;
- contrato semantico;
- manifesto da extracao;
- artefatos de extracao necessarios.

### Criterio de Aceite

- DAG 3 abre os artefatos corretos no MinIO.
- Se `status_compatibilidade.status = compativel`, a DAG recusa fallback.
- Se o relatorio estiver ausente ou malformado, a DAG falha antes de chamar LLM.

## Etapa 3: Classificacao Deterministica da Falha

### Objetivo

Antes de chamar LLM, decidir se o problema e correcao parcial ou ruptura
estrutural ampla.

### Implementacoes

Criar metodo:

- `classify_fallback_scope(validation, audit)`

Classificacoes:

- `correcao_parcial_mapeamento`;
- `regeneracao_total_mapeamento`;
- `falha_nao_suportada_para_fallback_automatico`.

### Regras Iniciais

Correção parcial quando houver:

- linha critica ausente;
- coluna critica ausente;
- valor nao normalizavel;
- poucos campos obrigatorios nao resolvidos;
- campo obrigatorio com seletor quebrado.

Regeneracao total quando houver:

- tabela critica ausente;
- secao critica ausente;
- multiplas falhas criticas simultaneas;
- perfil critico declarado no layout nao resolvido.

### Criterio de Aceite

- A classificacao e feita sem LLM.
- A LLM recebe a classificacao como limite de atuacao.
- Validacao compativel nao aciona fallback.

## Etapa 4: Geracao do Contexto de Problema

### Objetivo

Montar um pacote estruturado com o problema antes da LLM.

### Implementacoes

Criar payload:

- `fallback_problem_context`

Conteudo:

- campos quebrados;
- regras reprovadas;
- codigos de falha;
- trechos relevantes do layout signature;
- trechos relevantes do contrato;
- amostras dos artefatos de extracao;
- escopo permitido da correcao.

### Criterio de Aceite

- O payload nao contem o PDF inteiro.
- O payload nao pede valores finais de negocio.
- O payload limita a LLM a gerar somente um layout signature candidato dentro
  das secoes permitidas.
- Metadados operacionais uteis apenas para debug, como `tipo_artefato`,
  `status`, contadores do manifesto e flags internas, podem ser persistidos no
  MinIO, mas nao devem ser enviados para a LLM quando nao ajudarem a escolher
  artefatos ou gerar o candidato.
- O payload deixa claro que contrato semantico, schema resolvido, regras de
  governanca e versoes ja publicadas nao podem ser alterados pela LLM.

## Etapa 5: Cliente LLM e Prompt Controlado

### Objetivo

Adicionar chamada LLM isolada, testavel e substituivel.

### Implementacoes

Criar client:

- `airflow/plugins/clients/llm_client.py`

Criar contrato tipado da resposta:

- `airflow/plugins/services/fallback/models.py`;
- modelo Pydantic para `layout_signature_candidato`;
- modelos auxiliares para validar secoes alteraveis do layout.

Organizacao dos services de fallback:

- `airflow/plugins/services/fallback/orchestrator.py`: coordena o fluxo da DAG 3;
- `airflow/plugins/services/fallback/classification.py`: classifica o escopo do fallback;
- `airflow/plugins/services/fallback/context_builder.py`: monta o `fallback_problem_context`;
- `airflow/plugins/services/fallback/inventory.py`: le inventario, artefatos e chunks;
- `airflow/plugins/services/fallback/prompts.py`: centraliza prompts da LLM;
- `airflow/plugins/services/fallback/candidate_validation.py`: valida o candidato;
- `airflow/plugins/services/fallback/models.py`: contratos Pydantic.

Configuracoes por ambiente:

- `FALLBACK_LLM_PROVIDER`;
- `FALLBACK_LLM_API_URL`;
- `FALLBACK_LLM_API_KEY`;
- `FALLBACK_LLM_MODEL`;
- `FALLBACK_LLM_TIMEOUT_SECONDS`;
- `FALLBACK_LLM_MAX_TOKENS`.

Providers suportados:

- `openai`: usa endpoint compativel com Chat Completions. Por padrao,
  `FALLBACK_LLM_API_URL=https://api.openai.com/v1`. Exige
  `FALLBACK_LLM_API_KEY` e `FALLBACK_LLM_MODEL`. Se `FALLBACK_LLM_API_KEY`
  estiver vazio, a DAG 3 tambem aceita `OPENAI_API_KEY`.
- `ollama`: usa `/api/chat`. Por padrao, `FALLBACK_LLM_API_URL=http://ollama:11434`,
  mas em ambiente local com Ollama rodando no host Mac pode ser usado
  `http://host.docker.internal:11434`. Exige `FALLBACK_LLM_MODEL` e nao exige
  chave de API.

O prompt deve instruir rigidamente:

- quando a politica de inventario exigir ou recomendar busca de artefatos,
  fazer uma primeira chamada para escolher artefatos relevantes usando contrato
  semantico, falhas e `inventory.json`;
- nessa primeira chamada, nao gerar layout, valores finais ou mapeamento
  canonico;
- nessa primeira chamada, devolver somente caminhos existentes no inventario;
- na chamada de geracao do candidato, gerar diretamente o
  `layout_signature_candidato`; quando houver selecao previa, usar os artefatos
  selecionados como contexto adicional;
- nao gerar matriz de cobertura como etapa intermediaria obrigatoria;
- nao gerar `schema_saida_resolvido`;
- nao inventar campos fora do contrato;
- nao alterar layout base nem versoes ja publicadas;
- nao alterar `referencia_contrato_semantico`;
- nao alterar `regras_execucao` de governanca;
- nao definir `versao_artefato` final;
- retornar diretamente um `layout_signature_candidato`;
- permitir, conforme a falha, alteracoes apenas em `fontes_relevantes`,
  `regras_deteccao_mudanca`, `mapeamento_canonico` e metadados estruturais de
  evidencia;
- retornar JSON estrito.

### Criterio de Aceite

- Se LLM nao estiver configurada, a DAG falha ou pula com status explicito.
- Resposta nao JSON e rejeitada.
- Resposta JSON fora dos contratos Pydantic de selecao de artefatos ou de layout
  candidato e rejeitada.
- Quando houver selecao de artefatos, a primeira chamada e rejeitada se apontar
  para arquivos fora do inventario.
- Campos fora do contrato sao rejeitados.
- A DAG 3 consegue usar tanto API OpenAI/compativel quanto Ollama local/remoto
  apenas alterando variaveis de ambiente.
- A resposta da LLM ainda nao e publicada como layout ativo nesta etapa.
- A LLM nao gera artefatos intermediarios de analise semantica ou proposta de
  atualizacao; ela gera o candidato que sera validado pelas proximas etapas.

### Retry Corretivo da LLM

Quando a LLM entender a tarefa, mas falhar em detalhes corrigiveis, a DAG 3 deve
tentar corrigir a resposta antes de desistir.

Politica inicial:

- chamada inicial + ate 3 tentativas corretivas;
- retry corretivo apenas para erros de JSON, contrato Pydantic ou pequenas
  violacoes de formato que possam ser explicadas objetivamente;
- erro de transporte, timeout ou indisponibilidade do provider deve ser tratado
  como retry tecnico separado, nao como retry semantico;
- cada tentativa corretiva deve receber a resposta anterior, o erro
  deterministico encontrado e uma instrucao objetiva de correcao;
- se todas as tentativas falharem, a DAG 3 persiste o erro e falha sem publicar
  candidato.

## Etapa 6: Gerar Layout Signature Candidato

### Objetivo

Gerar diretamente um `layout_signature_candidato` a partir do contexto de
problema, do contrato semantico, do layout base e dos artefatos de extracao
relevantes.

Para `correcao_parcial_mapeamento`, o candidato pode funcionar como um patch
controlado das secoes editaveis do layout existente.

Para `regeneracao_total_mapeamento` profunda ou `criacao_inicial_layout`, o
candidato deve representar um layout signature completo em estado candidato,
pois a LLM precisa reconstruir todas as partes necessarias para que a DAG 2
consiga validar e resolver o schema de saida.

### Formato Esperado

```json
{
  "tipo_artefato": "layout_signature_candidato",
  "status_layout": "candidato",
  "escopo_correcao": "correcao_parcial_mapeamento",
  "document_id": "...",
  "execution_id_origem": "...",
  "base_layout_signature": {
    "versao": "4.0.0",
    "object_key": "layouts/construtoras/cury/v4.0.0/layout_signature_deterministico.json"
  },
  "fontes_relevantes": {},
  "regras_deteccao_mudanca": [],
  "mapeamento_canonico": {},
  "metadados_estruturais_evidencia": {},
  "publicacao_automatica_habilitada": true
}
```

### Criterio de Aceite

- O candidato e gerado em memoria ou XCom, ainda sem alterar MinIO `layouts/...`.
- O candidato nao contem valores finais do `schema_saida_resolvido`.
- O candidato respeita o escopo permitido pela classificacao deterministica.
- O candidato nao altera contrato semantico, regras de governanca, versao final
  nem objetos ja publicados.

## Etapa 7: Decidir entre Chamada Unica ou Selecao Previa de Artefatos

### Objetivo

Decidir se a DAG 3 consegue gerar o candidato com contexto focado em uma unica
chamada LLM ou se precisa primeiro pedir para a LLM escolher artefatos do
`inventory.json`.

### Decisao de Design

A DAG 3 pode seguir por dois caminhos.

#### Caminho A: Chamada Unica

Usado quando o inventario for `opcional` ou quando a correcao puder ser feita
com contexto focado.

Fluxo:

1. DAG 3 monta o `fallback_problem_context` com contrato, falhas, layout
   relevante e restricoes.
2. DAG 3 chama a LLM uma vez.
3. LLM retorna `layout_signature_candidato`.
4. DAG 3 valida o candidato com Pydantic e regras deterministicas.

Esse caminho e adequado para correcoes parciais simples, por exemplo:

- ajustar um seletor;
- corrigir um path de `mapeamento_canonico`;
- trocar um cabecalho esperado;
- corrigir uma regra pequena sem precisar abrir novos artefatos da extracao.

#### Caminho B: Selecao Previa por Inventario

Usado quando o uso do inventario for `obrigatorio`, ou quando for
`recomendado` e houver inventario disponivel.

Esse caminho existe para evitar mandar todo o documento para a LLM. Primeiro a
LLM escolhe quais arquivos quer olhar; depois a DAG carrega somente esses
arquivos e faz a chamada de geracao do candidato.

Fluxo:

1. DAG 3 envia contrato, falhas, layout relevante e `inventory.json` para a LLM.
2. LLM retorna `selecao_artefatos_layout`.
3. DAG 3 valida se os arquivos pedidos existem no inventario.
4. DAG 3 carrega os arquivos selecionados.
5. DAG 3 chama a LLM novamente com o contexto enriquecido.
6. LLM retorna `layout_signature_candidato`.
7. DAG 3 valida o candidato com Pydantic e regras deterministicas.

Esse caminho e adequado para:

- regeneracao total;
- criacao inicial de layout signature;
- correcao parcial em que a origem antiga pode nao ser mais suficiente;
- casos em que a tabela, secao, grafico ou bloco textual esperado mudou de
  lugar.

Observacao importante: este plano nao inclui mais uma chamada intermediaria para
`matriz_cobertura_layout`. A cobertura dos campos deve ser verificada por
validacao deterministica do candidato contra o contrato e pela revalidacao da
DAG 2.

### Selecao de Artefatos por LLM usando Inventario

O inventario passa a ser o catalogo consultado pela LLM antes de abrir conteudo
pesado da extracao, mas somente quando a politica de fallback indicar que isso
e necessario. O fluxo simples continua com uma chamada de LLM para gerar o
candidato a partir do contexto focado. O fluxo com inventario tem duas chamadas
LLM:

1. **Selecao de artefatos:** a DAG 3 envia contrato semantico, contexto da falha,
   layout base quando existir e resumo do `inventory.json`. A LLM responde quais
   arquivos quer explorar.
2. **Geracao do candidato:** a DAG 3 valida os caminhos escolhidos contra o
   inventario, carrega os arquivos selecionados e chama a LLM novamente para
   gerar o `layout_signature_candidato`.

Quando a primeira chamada for acionada, a DAG 3 envia para a LLM:

- contrato semantico;
- `inventory.json` da extracao;
- contexto da falha, quando houver fallback sobre layout existente;
- layout signature base, quando existir, apenas como pista e referencia de
  lineage.

A selecao nao deve ser feita por regra deterministica baseada em ranking de
termos. A LLM escolhe os artefatos e a DAG 3 atua como validadora: aceita apenas
caminhos existentes no inventario e rejeita qualquer arquivo inventado,
object key completo ou URI MinIO.

Formato esperado da primeira chamada:

```json
{
  "tipo_artefato": "selecao_artefatos_layout",
  "artifact_paths": [
    {
      "path": "tables/table001.json",
      "motivo": "Tabela contem os campos de lancamentos exigidos pelo contrato.",
      "campos_saida": ["balancos_das_empresas.lancamentos"]
    }
  ]
}
```

Depois disso, a DAG 3 abre somente os artefatos selecionados, por exemplo uma
tabela, um grafico, uma secao ou um subconjunto de blocos textuais. Quando a
politica de inventario for `opcional` e a falha puder ser corrigida com o
contexto focado, essa primeira chamada nao acontece.

### Quando Usar o Inventario no Fallback

O inventario deve ser sempre usado em `criacao_inicial_layout` e
`regeneracao_total_mapeamento`, porque nesses cenarios a DAG 3 precisa descobrir
ou reconstruir todas as origens relevantes do layout.

Em `criacao_inicial_layout`, o inventario enviado para a primeira chamada da LLM
deve ser completo. Como nao existe layout signature base confiavel, a LLM precisa
ver todo o catalogo da extracao junto com o contrato semantico para decidir quais
artefatos devem ser explorados.

Em `correcao_parcial_mapeamento`, o inventario nao precisa ser usado sempre. Ele
entra como uma ajuda de roteamento quando a falha indicar que a origem antiga
pode nao ser suficiente para localizar o novo dado. O objetivo e economizar
contexto: em vez de enviar todos os artefatos da extracao, a DAG 3 usa o
`inventory.json` para escolher uma tabela, grafico, secao ou arquivo textual
provavel e abre apenas esse artefato.

Com base nas falhas classificadas hoje em `classify_fallback_scope`, o uso do
inventario deve seguir esta politica inicial:

| Falha detectada | Escopo atual | Uso do inventario | Motivo |
| --- | --- | --- | --- |
| `arquivo_existe` reprovado | regeneracao total | obrigatorio | O arquivo, tabela ou artefato critico esperado nao foi encontrado; e preciso procurar substitutos no catalogo da extracao. |
| `secao_existe` reprovado | regeneracao total | obrigatorio | A secao esperada mudou, sumiu ou foi renomeada; o inventario ajuda a localizar secoes candidatas por titulo, pagina e estrutura. |
| `perfil_colunas_periodo_existe_em_tabela` com perfil critico nao resolvido | regeneracao total | obrigatorio | A tabela pode ter mudado de estrutura; o inventario ajuda a encontrar tabelas com schemas similares antes de abrir arquivos completos. |
| tres ou mais regras deterministicas reprovadas | regeneracao total | obrigatorio | Multiplas falhas indicam ruptura estrutural ampla; o inventario vira o mapa de redescoberta do layout. |
| multiplos campos obrigatorios nao resolvidos | regeneracao total | obrigatorio | Muitos campos quebrados indicam que as fontes antigas nao bastam; a busca deve partir do catalogo da extracao. |
| `linha_existe_em_tabela` reprovado | correcao parcial | recomendado | A tabela pode ser a mesma, mas o rotulo da linha mudou; o inventario pode confirmar a tabela provavel e evitar abrir artefatos irrelevantes. |
| `perfil_colunas_periodo_existe_em_tabela` com coluna critica ausente | correcao parcial | recomendado | A coluna ou cabecalho mudou; o inventario ajuda a encontrar outra tabela com schema parecido ou confirmar que basta ajustar seletor. |
| `valor_normalizavel` reprovado | correcao parcial | opcional | Normalmente o problema e normalizacao, nao localizacao; usar inventario apenas se a evidencia apontar que o valor veio da fonte errada. |
| poucos campos obrigatorios nao resolvidos | correcao parcial | recomendado | O inventario ajuda a procurar rapidamente origens alternativas para esses campos sem carregar todo o documento. |
| campo obrigatorio com `status_resolucao = erro` | correcao parcial | recomendado | Erro de seletor pode indicar que a origem mudou; o inventario ajuda a escolher novo artefato ou confirmar que basta corrigir caminho interno. |
| regra reprovada sem classificador automatico | nao suportado | nao usar automaticamente | A DAG deve falhar antes da LLM ate existir politica explicita para esse tipo de falha. |

Essa politica pode evoluir quando novos `tipo_teste` forem adicionados na DAG 2.
Todo novo tipo de falha deve declarar se o inventario e obrigatorio,
recomendado, opcional ou proibido no fallback automatico.

### Tipos de Candidato

Para `correcao_parcial_mapeamento`, a LLM deve gerar um candidato restrito as
secoes editaveis do layout existente:

- `fontes_relevantes`;
- `regras_deteccao_mudanca`;
- `mapeamento_canonico`;
- metadados estruturais de evidencia.

Para `regeneracao_total_mapeamento` profunda ou `criacao_inicial_layout`, a LLM
deve gerar um layout signature candidato completo, nao apenas esses tres blocos.
Nesse caso, ela pode preencher todas as partes estruturais necessarias do layout
signature candidato, desde que respeite as fronteiras de governanca.

### Pode Ser Gerado pela LLM no Candidato Completo

- estrutura completa do layout signature candidato;
- `fontes_relevantes`;
- `regras_deteccao_mudanca`;
- `mapeamento_canonico`;
- descricoes operacionais do layout, quando existirem no padrao;
- criterios de compatibilidade do layout;
- metadados estruturais de evidencia;
- referencias ao contrato e a execucao apenas quando recebidas no contexto.

### Nao Pode Ser Gerado Livremente pela LLM

- `schema_saida`;
- entidades e metricas do contrato semantico;
- valores finais resolvidos;
- `versao_artefato` oficial;
- regras de governanca do pipeline;
- object key oficial em `layouts/...`;
- qualquer alteracao em layout versionado ja publicado.

### Uso de Chunks

Chunks ficam como mecanismo de contingencia, nao como fluxo padrao. Eles devem
ser usados quando o artefato escolhido pelo inventario for grande demais para
ser enviado inteiro, especialmente em:

- `blocks/blocks.jsonl`;
- `text_candidates/text_candidates.jsonl`;
- `text_structures/text_structures.jsonl`;
- documentos longos com muitas paginas;
- colecoes textuais geradas por OCR muito verboso.

Para tabelas, graficos e metadados pequenos, a DAG 3 deve preferir carregar o
artefato completo selecionado pelo inventario.

### Estado Acumulado Entre Chunks

Quando chunks forem necessarios, a DAG 3 nao deve depender de memoria implicita
da LLM entre chamadas. Cada chamada de LLM e isolada; portanto, quem preserva o
contexto global deve ser a propria DAG 3 por meio de um estado intermediario
estruturado.

Fluxo esperado:

1. A DAG 3 cria um estado inicial por campo ou grupo de campos do contrato.
2. Cada chunk e enviado para a LLM junto com o objetivo, o trecho relevante do
   contrato, o inventario e um resumo curto do estado acumulado ate aquele
   momento.
3. A LLM retorna apenas evidencias encontradas naquele chunk, nao o layout
   signature final.
4. A DAG 3 valida e acumula essas evidencias em uma estrutura propria.
5. Ao final dos chunks, a DAG 3 consolida as evidencias e so entao chama a LLM
   para gerar o `layout_signature_candidato`.

Exemplo de estado acumulado:

```json
{
  "campo_saida": "periodos_disponiveis.periodo_referencia",
  "evidencias_candidatas": [
    {
      "chunk_id": "blocks_page_4",
      "arquivo_origem": "blocks/blocks.jsonl",
      "record_id": "block_123",
      "page_number": 4,
      "section_title": "Lançamentos",
      "valor_exemplo": "1T26",
      "confianca": 0.86
    }
  ],
  "chunks_analisados": ["blocks_page_4"],
  "conflitos": []
}
```

Na chamada seguinte, a LLM nao recebe todos os chunks anteriores. Ela recebe
apenas o chunk atual e um resumo do estado acumulado, por exemplo a melhor
evidencia encontrada ate agora para cada campo. Isso reduz consumo de contexto e
evita que cada chunk seja analisado como um problema solto.

Se chunks diferentes sugerirem origens conflitantes para o mesmo campo, a DAG 3
deve registrar o conflito no estado acumulado e resolver por uma chamada final
de consolidacao antes de gerar o layout candidato.

### Criterio de Aceite

- A DAG 3 consegue carregar `inventory.json` a partir do manifesto da extracao.
- Quando a politica de inventario for `obrigatorio`, a primeira chamada LLM
  escolhe artefatos usando contrato, falhas e inventario, sem receber o conteudo
  completo desses artefatos.
- Quando a politica for `recomendado` e houver inventario disponivel, a primeira
  chamada tambem pode ser usada para economizar contexto em falhas parciais.
- Quando a politica for `opcional`, a DAG 3 pode seguir com uma chamada unica
  usando apenas o contexto focado.
- Toda resposta de selecao passa por Pydantic e por validacao de caminhos contra
  o inventario.
- Para remapeamento amplo ou criacao inicial, a segunda chamada so recebe os
  artefatos escolhidos e validados.
- A LLM nao recebe o documento inteiro em uma unica chamada por padrao.
- Quando um artefato selecionado for pequeno, ele e enviado completo.
- Quando um artefato selecionado for grande, a DAG aplica chunking ou paginacao.
- O candidato gerado respeita o escopo: patch para correcao parcial, layout
  completo para criacao inicial ou regeneracao profunda.

## Etapa 8: Observabilidade dos Requests LLM

### Objetivo

Persistir informacoes suficientes para entender o que cada chamada da LLM
recebeu, respondeu e por que foi aceita ou rejeitada.

### Artefatos Esperados

No prefixo de fallback da execucao da DAG 3:

```text
fallback/<dominio>/<entidade>/document_id=.../execution_id=<fallback_execution_id>/
```

Persistir, quando aplicavel:

- `entrada_llm_selecao_artefatos.json`;
- `resposta_llm_selecao_artefatos.json`;
- `selecao_artefatos_layout.json`, somente apos validacao;
- `erro_llm_selecao_artefatos.json`, quando falhar;
- `entrada_llm_layout_signature_candidato.json`;
- `resposta_llm_layout_signature_candidato.json`;
- `layout_signature_candidato.json`, somente apos validacao;
- `erro_llm_layout_signature_candidato.json`, quando falhar.

Cada artefato de erro deve conter:

- etapa;
- tentativa;
- tipo de erro;
- mensagem deterministica;
- trecho ou resposta bruta da LLM, quando disponivel;
- instrucao corretiva enviada no retry, quando houver.

### Criterio de Aceite

- Toda chamada LLM relevante deixa rastreabilidade minima no MinIO.
- O payload persistido para debug pode conter metadados operacionais, mas o
  payload enviado efetivamente para a LLM deve permanecer enxuto.
- Uma nova execucao da DAG 3 nao sobrescreve artefatos de execucoes anteriores.
- Resposta bruta invalida tambem e persistida para permitir diagnostico de
  prompt, modelo ou provider.

## Etapa 9: Validacao do Layout Signature Candidato

### Objetivo

Antes de gravar ou revalidar o layout candidato, validar deterministicamente se
ele respeita as fronteiras do contrato, do layout base e da classificacao de
fallback.

### Implementacoes

Criar metodo:

- `validate_candidate_layout(candidate_layout, contract, base_layout, classification)`

Na implementacao inicial, esta validacao roda na mesma task que chama a LLM e
gera o candidato. Assim, a DAG 3 so devolve `layout_signature_candidato` quando
ele ja passou pelo contrato Pydantic e pelas regras deterministicas abaixo.

Validacoes:

- todo path em `mapeamento_canonico` existe no `schema_saida` do contrato;
- nenhuma alteracao escreve valores finais;
- alteracoes so podem atingir secoes permitidas do layout signature:
  `fontes_relevantes`, `regras_deteccao_mudanca`, `mapeamento_canonico` e
  metadados estruturais de evidencia;
- nenhum path de `mapeamento_canonico` pode apontar para campo fora do
  `schema_saida` do contrato;
- `referencia_contrato_semantico`, `regras_execucao` e `versao_artefato` final
  nao podem ser definidos ou alterados pelo candidato;
- candidato parcial nao remove mapeamentos nao relacionados;
- candidato total so e permitido em ruptura estrutural ampla.

### Criterio de Aceite

- Candidato invalido e rejeitado com motivo claro.
- Nenhum layout existente no MinIO e modificado.

## Etapa 10: Materializar Layout Signature Candidato

### Objetivo

Gravar o layout signature candidato validado em area separada, sem publica-lo
como versao oficial e sem sobrescrever qualquer layout existente.

### Implementacoes

Criar metodo:

- `persist_candidate_layout(candidate_layout, fallback_context)`

Implementacao inicial:

- `FallbackLlmService.persist_candidate_layout(...)` grava o candidato validado
  em `fallback/.../layout_signature_candidato.json`;
- o objeto persistido recebe `candidate_layout_object_key`, `persistido_em` e
  `secoes_atualizadas`;
- a DAG 3 usa a task `persistir_layout_candidato` logo apos a geracao e
  validacao Pydantic/deterministica do candidato.

### Caminho no MinIO

```text
fallback/<dominio>/<entidade>/document_id=.../execution_id=<fallback_execution_id>/layout_signature_candidato.json
```

### Metadados no Candidato

```json
{
  "status_layout": "candidato",
  "base_layout_signature": "...",
  "secoes_atualizadas": [
    "fontes_relevantes",
    "regras_deteccao_mudanca",
    "mapeamento_canonico"
  ],
  "publicacao_automatica_habilitada": true
}
```

### Criterio de Aceite

- O layout base em `layouts/.../layout_signature_deterministico.json` nao muda.
- O candidato fica separado em `fallback/...`.
- O candidato aponta para layout base, document_id, execution_id de origem e
  escopo de fallback.

## Etapa 11: Revalidacao pela DAG 2

### Objetivo

Permitir que a DAG 2 rode usando o layout candidato.

### Possiveis Abordagens

1. DAG 3 dispara DAG 2 com `dag_run.conf` apontando para o layout candidato.
2. DAG 2 passa a aceitar override de layout em runtime.
3. DAG 2 registra que esta validando layout candidato, nao a versao vigente.

### Implementacoes Necessarias

Na DAG 2:

- aceitar `layout_signature_uri` opcional no runtime/conf;
- se presente, carregar esse layout em vez da versao vigente;
- persistir artefatos de resolucao com referencia ao layout candidato.

Implementacao inicial:

- a DAG 3 monta `dag_run.conf` com:
  - `modo_execucao = revalidacao_layout_candidato`;
  - `manifest_key` da execucao original;
  - `layout_signature_uri` e `layout_signature_object_key` do candidato;
  - `fallback_revalidation_prefix`;
- a DAG 3 dispara `dag_resolve_schema_saida` com `wait_for_completion=True`;
- a DAG 2, quando recebe `manifest_key`, processa apenas esse manifesto;
- a DAG 2, quando recebe `layout_signature_uri/object_key`, carrega esse layout
  candidato no lugar do layout vigente;
- a DAG 2 grava os artefatos da revalidacao em
  `fallback/.../revalidation/`, sem sobrescrever a resolucao original;
- a DAG 2 nao dispara novo fallback quando roda em
  `modo_execucao = revalidacao_layout_candidato`.

### Criterio de Aceite

- DAG 2 consegue validar candidato sem publicar nova versao.
- Se passar, status do candidato vira `validado_para_publicacao_automatica`.
- Se falhar, status vira `reprovado_na_revalidacao`.

## Etapa 12: Publicacao Automatizada de Nova Versao

### Objetivo

Garantir que candidato aprovado nao altere nenhuma versao existente. Quando a
revalidacao pela DAG 2 passar, a DAG 3 deve publicar automaticamente uma nova
versao versionada do layout signature no MinIO.

### Implementacao Inicial

Registrar:

- `publicacao_automatica_habilitada: true`;
- `status_candidato: validado_para_publicacao_automatica`;
- `proxima_versao_sugerida`, quando aplicavel.

Implementacao inicial:

- `FallbackLlmService.evaluate_revalidation_result(...)` le
  `fallback/.../revalidation/validacao_layout_signature.json`;
- se a revalidacao nao estiver `compativel`, a DAG 3 falha e nao publica nada;
- `FallbackLlmService.publish_validated_layout_version(...)` calcula a proxima
  versao minor disponivel em `layouts/.../vX.Y.Z/`;
- a nova versao e montada aplicando o candidato sobre o layout base e removendo
  metadados exclusivos de candidato;
- o layout publicado recebe `versao_artefato`, `publicado_em` e
  `lineage_fallback`;
- a publicacao falha se o object key versionado ja existir.

A publicacao automatica deve criar um novo caminho versionado, por exemplo:

```text
layouts/construtoras/cury/v4.1.0/layout_signature_deterministico.json
```

O caminho anterior continua existindo para rastreabilidade e reproducibilidade.
A definicao de qual versao e a vigente deve ser feita por catalogo/metadata ou
ponteiro operacional, nunca por sobrescrita do arquivo antigo.

Implementacao do ponteiro vigente:

- a DAG 2 resolve o layout vigente por
  `layouts/<dominio>/<entidade>/current.json`;
- `current.json` aponta para o `object_key` versionado atualmente vigente;
- quando a DAG 3 publica uma nova versao aprovada, ela cria o novo objeto em
  `layouts/.../vX.Y.Z/layout_signature_deterministico.json` e atualiza
  `current.json`;
- se `current.json` nao existir, a DAG 2 entende que ainda nao ha layout
  signature vigente e aciona a DAG 3 em modo `criacao_inicial_layout`.

### Criterio de Aceite

- Nenhum codigo da DAG 3 sobrescreve objetos ja existentes em `layouts/...`.
- A DAG 3 cria uma nova versao em `layouts/.../vX.Y.Z/...` somente depois de
  revalidacao deterministica bem-sucedida pela DAG 2.
- A versao anterior permanece disponivel para rastreabilidade e reprocessamento.
- Se a revalidacao falhar, nenhuma nova versao e publicada.

## Etapa 13: Testes e Smokes

### Testes Minimos

- validacao compativel recusa fallback;
- validacao ausente falha antes da LLM;
- falha de linha gera correcao parcial;
- tabela critica ausente gera regeneracao total;
- candidato com campo fora do contrato e rejeitado;
- candidato com `schema_saida_resolvido` e rejeitado;
- candidato que altera `referencia_contrato_semantico`, `regras_execucao` ou
  `versao_artefato` final e rejeitada;
- resposta LLM com JSON invalido aciona retry corretivo e persiste erro bruto;
- selecao de artefatos com path fora do inventario e rejeitada;
- nova execucao da DAG 3 gera novo `fallback_execution_id` e nao sobrescreve
  artefatos anteriores;
- layout candidato nao altera versoes existentes;
- DAG 2 consegue revalidar candidato.

### Smoke Manual

1. Rodar DAG 2 com layout quebrado propositalmente.
2. Confirmar `validacao_layout_signature = incompativel`.
3. Rodar DAG 3.
4. Verificar `layout_signature_candidato.json`.
5. Rodar DAG 2 com candidato.
6. Confirmar que nenhuma versao existente em `layouts/...` foi alterada.
7. Confirmar que foi criada uma nova versao versionada somente se a revalidacao
   do candidato passou.

## Etapa 14: Postgres Operacional

### Objetivo

Registrar estado operacional do fallback.

### Implementacao Posterior

Tabela esperada:

- `operacional.fallback_execucoes`

Campos principais:

- `execution_id`;
- `document_id`;
- `execution_id_origem`;
- `status_fallback`;
- `escopo_correcao`;
- `codigos_falha`;
- `candidate_layout_object_key`;
- `published_layout_object_key`;
- `publicacao_automatica_habilitada`.

### Criterio de Aceite

Enquanto Postgres nao estiver integrado, deixar essa lacuna explicita na
auditoria e documentacao.

## Ordem Recomendada de Implementacao

1. Criar `FallbackLlmService` sem LLM, so carregando contexto.
2. Fazer DAG 3 validar `dag_run.conf` e ler artefatos da DAG 2.
3. Implementar classificacao deterministica da falha.
4. Gerar layout signature candidato mockado/deterministico para testes.
5. Validar e persistir layout candidato em `fallback/...`.
6. Adaptar DAG 2 para aceitar layout candidato por `dag_run.conf`.
7. Plugar LLM real para gerar candidato diretamente.
8. Adicionar validacao rigida da resposta LLM/candidato.
9. Criar smokes e testes negativos.
10. Documentar o fluxo de publicacao automatica e versionamento de layout.

## Fora do Escopo da DAG 3

- Corrigir diretamente `schema_saida_resolvido.json`;
- escrever na bronze;
- modificar versoes existentes de layout signature;
- usar LLM como mecanismo padrao de resolucao.

## Etapas Futuras Ainda em Analise

### Revisao Humana de Layout Candidato

Por enquanto, a correcao do layout signature fica automatizada: a LLM gera o
layout signature candidato, a DAG 3 valida e materializa esse candidato, a DAG 2
revalida deterministicamente e, se passar, a DAG 3 publica uma nova versao
versionada no MinIO.

A revisao humana pode ser adicionada depois como uma trava opcional antes da
publicacao da nova versao. Essa decisao ainda precisa definir:

- quando a revisao humana sera obrigatoria;
- quais campos um revisor podera aprovar ou rejeitar;
- onde o estado de aprovacao sera persistido;
- como a versao aprovada sera marcada como vigente;
- quais perfis ou papeis poderao homologar um layout candidato.
