# Plano de Correções: Arrays, Tabelas e Fragmentos da DAG 3

## Objetivo

Permitir que a DAG 3 gere layout signatures escaláveis para qualquer tipo de
PDF que possua tabelas com séries, listas ou registros repetidos. A solução
deve manter a LLM responsável por reconhecer a evidência e propor o
mapeamento, enquanto a DAG 2 continua responsável pela extração e montagem
determinística do schema de saída.

Este plano surgiu da execução ABECIP de 16/08/2026, mas não deve introduzir
regras específicas de financiamento, ABECIP, mês ou banco.

## Diagnóstico da execução de referência

Na unidade `financiamentos_imobiliarios`, a LLM selecionou corretamente três
tabelas e retornou JSON válido. Porém gerou 121 mapeamentos individuais para
meses, anos e instituições, em vez de três mapeamentos por coleção.

O primeiro erro de validação foi:

```text
Resposta da LLM tentou criar candidato com mapeamento para campo fora do
schema_saida do contrato:
financiamentos_imobiliarios.serie_mensal_sbpe
[periodo.rotulo_publicado=Jan].periodo.rotulo_publicado.
```

O path é semanticamente compreensível: ele identifica um item de uma lista
pelo campo aninhado `periodo.rotulo_publicado`. A falha ocorreu porque o
código divide paths por ponto sem considerar se o ponto está dentro de
colchetes.

O mesmo resultado foi devolvido nas quatro tentativas. O retry reenviou a
resposta inteira inválida, mas a mensagem de erro não explica a limitação do
parser; portanto não há informação prática para a LLM mudar a estratégia.

## Comparação com o layout de referência

O arquivo `layout_signature_abecip_deterministico.json` representa o resultado
esperado para a unidade `financiamentos_imobiliarios`. Ele não contém centenas
de células isoladas: contém três mapeamentos de coleções por
`linhas_de_tabela`:

| Coleção | Arquivo | Estrutura do layout de referência |
|---|---|---|
| `serie_mensal_sbpe` | `tables/table004.json` | dois segmentos: 2025 e 2026, com colunas distintas para cada ano |
| `serie_historica_anual` | `tables/table005.json` | uma faixa que lê a série anual inteira |
| `por_modalidade_e_instituicao` | `tables/table006.json` | três segmentos: construção, aquisição e total |

Em contraste, a resposta da LLM criou 121 mapeamentos de `celula_de_tabela`,
um por mês, ano ou instituição. O modelo identificou corretamente os três
arquivos e várias colunas, mas não recebeu nem foi instruído a produzir a
forma compacta do layout de referência.

Essa comparação altera a prioridade do plano: o caminho principal para
tabelas repetitivas não é ampliar o suporte a seletores por registro. É fazer
com que a LLM gere `linhas_de_tabela` no path da coleção e que a DAG 2 resolva
essa instrução diretamente para itens do schema.

## Estado atual

### Implementado nesta etapa

- A DAG 2 aceita `linhas_de_tabela`.
- `linhas_de_tabela` aceita `segmentos` ou `faixas_linhas`, com
  `linha_inicial`, `linha_final` e `indices_colunas`.
- A DAG 3 divide a geração em unidades de mapeamento e persiste entrada,
  resposta e erro por unidade/tentativa.
- A LLM pode selecionar os artefatos antes de receber a evidência da unidade.
- O parser compartilhado preserva pontos dentro de seletores de arrays e a
  DAG 2 aplica seletores aninhados sem conhecer nomes de domínio.
- Um `linhas_de_tabela` pode mapear a própria coleção do contrato sem filtro
  de item, desde que declare campos nomeados ou o formato posicional legado.
- `campos.caminho_saida` preenche objetos aninhados do item de saída, e é
  validado contra o schema de destino quando informado.
- Tabelas pequenas são enviadas integralmente à LLM; tabelas grandes usam
  janelas determinísticas de início, meio e fim.
- Os exemplos enviados à LLM agora usam as mesmas chaves consumidas pela DAG
  2, inclusive seletores de tabela e `valor_fixo`.
- Respostas LLM aceitas também persistem `api_response_metadata`; retries de
  fragmento reenviam apenas o trecho relevante da resposta inválida.

### Adiado por decisão atual

- A melhoria 6, divisão de uma unidade em subunidades e novas chamadas LLM,
  foi explicitamente adiada. A unidade continua sendo resolvida em uma única
  chamada de geração após a seleção de artefatos.

## Princípios de implementação

1. Não criar regras por domínio, empresa, período ou nome de campo.
2. O contrato semântico define o schema; o layout signature define onde cada
   campo está; o resolvedor apenas interpreta essas instruções.
3. Uma tabela repetitiva deve normalmente ser descrita uma vez, por faixa de
   linhas, e não uma vez por observação.
4. Paths, seletores e formatos ensinados à LLM devem ser exatamente os que a
   validação e a DAG 2 suportam.
5. A exceção para coleções deve ser explícita e limitada: somente um
   mapeamento `linhas_de_tabela` que aponta para a própria coleção pode omitir
   um seletor de item.

## Melhoria 1 — Parser seguro de paths de mapeamento

### Problema

Os parsers atuais usam `path.split(".")`. Isso quebra seletores aninhados:

```text
serie[periodo.rotulo_publicado=Jan].valor
```

é interpretado como partes inválidas porque o ponto entre `periodo` e
`rotulo_publicado` está dentro de `[...]`.

### Comportamento esperado

O path acima deve ser dividido em apenas dois segmentos:

```text
serie[periodo.rotulo_publicado=Jan]
valor
```

### Implementação

Criar um utilitário compartilhado, por exemplo em um módulo de paths de
layout, que percorra os caracteres e separe por ponto somente quando a
profundidade de colchetes for zero. Esse utilitário deve ser usado por:

- validação de paths do candidato;
- normalização de path para comparação com `paths_permitidos`;
- verificação de arrays que exigem seletor;
- leitura de seletores em requisitos de mapeamento;
- `_parse_mapping_path` da DAG 2.

Não manter implementações locais com `split(".")`, pois elas voltarão a divergir.

### Testes mínimos

- path simples: `grupo.valor`;
- array com seletor simples: `grupo.itens[codigo=A].valor`;
- array com seletor aninhado:
  `grupo.itens[periodo.rotulo=Jan].valor`;
- dois arrays no mesmo path;
- path inválido com colchete não fechado deve gerar erro claro.

## Melhoria 2 — Aplicação genérica de seletores aninhados

### Problema

Mesmo que o parser reconheça:

```text
itens[periodo.rotulo_publicado=Jan]
```

a DAG 2 ainda precisa localizar ou criar o item correto no array. Hoje a
busca funciona apenas com campos diretos do item, como `empresa=Cury`.

### Comportamento esperado

Para um item como:

```json
{
  "periodo": {"rotulo_publicado": "Jan"}
}
```

o seletor `periodo.rotulo_publicado=Jan` deve localizar esse item.

Quando ele não existe, a DAG deve criar o objeto aninhado correspondente e
registrar o seletor interno usado para manter idempotência durante a mesma
resolução.

### Implementação

Adicionar helpers genéricos para:

- ler valor aninhado por path (`get_nested_value`);
- escrever valor aninhado por path (`set_nested_value`);
- comparar os valores com o seletor;
- preservar o mecanismo interno de seletores usado para reencontrar itens.

Esses helpers não devem conhecer `periodo`, `rotulo_publicado`, datas ou
qualquer campo de domínio.

### Testes mínimos

- localizar item por campo direto;
- localizar item por campo aninhado;
- criar item por campo aninhado;
- preservar dois itens que tenham o mesmo valor em um campo, mas seletor
  distinto em outro.

## Melhoria 3 — Alinhar prompt, schema de resposta e resolvedor

### Problema

O exemplo enviado à LLM ensina formatos que a DAG 2 não consome diretamente.

Exemplo ensinado para célula:

```json
{
  "indice_linha": 2,
  "indice_coluna": 4
}
```

Formato atualmente lido pelo resolvedor:

```json
{
  "seletor_linha": {"indice_linha_esperado": 2},
  "seletor_coluna": {"indice_coluna_esperado": 4}
}
```

Também é necessário padronizar `valor_fixo`: o resolvedor lê a chave
`valor_fixo`, e não a chave `valor`.

### Decisão necessária

Escolher um único formato canônico. Há duas opções válidas:

1. Manter o formato atual da DAG 2 e corrigir os exemplos/prompts.
2. Simplificar a DAG 2 para aceitar índices diretos e atualizar validação e
   documentação.

A opção 1 altera menos código e é a recomendada para curto prazo.

### Implementação

- Atualizar todos os exemplos de `celula_de_tabela`, `cabecalho_de_tabela` e
  `valor_fixo` enviados à LLM.
- Atualizar o schema JSON de `CanonicalMappingEntry` para descrever as chaves
  efetivamente aceitas. Hoje `extra="allow"` deixa respostas estruturalmente
  válidas passarem até uma falha posterior.
- Incluir validação Pydantic específica por `tipo_origem`, ou uma validação
  determinística equivalente antes da validação semântica.
- Nos retries, informar o formato esperado e enviar só o trecho inválido, não
  a resposta inteira.

### Testes mínimos

- candidato com formato documentado passa à resolução;
- `valor` em vez de `valor_fixo` falha com mensagem específica;
- célula sem `seletor_coluna.indice_coluna_esperado` falha antes de chamar a
  DAG 2.

## Melhoria 4 — Mapeamento estrutural de tabela para coleção

### Problema

`linhas_de_tabela` já lê várias linhas, mas o formato genérico atual retorna
uma estrutura posicional:

```json
{
  "indice_linha": 0,
  "valores": [
    {"indice_coluna": 0, "valor": "Jan"},
    {"indice_coluna": 7, "valor": "35.701"}
  ]
}
```

Isso não informa como montar o item exigido pelo contrato, por exemplo:

```json
{
  "periodo": {"rotulo_publicado": "Jan"},
  "unidades_financiadas": 35701
}
```

Apenas indicar índices de colunas não é suficiente: o resolvedor não tem como
saber, de forma determinística, qual coluna alimenta qual campo de saída.

### Formato proposto

Permitir que `linhas_de_tabela` declare os campos do item com paths relativos
ao item da coleção:

```json
{
  "tipo_origem": "linhas_de_tabela",
  "arquivo_origem": "tables/table004.json",
  "faixas_linhas": [
    {
      "linha_inicial": 0,
      "linha_final": 4
    }
  ],
  "campos": [
    {
      "caminho_saida": "periodo.rotulo_publicado",
      "indice_coluna": 0,
      "tipo": "texto"
    },
    {
      "caminho_saida": "unidades_financiadas",
      "indice_coluna": 7,
      "tipo": "numero"
    },
    {
      "caminho_saida": "volume_financiado_milhoes",
      "indice_coluna": 10,
      "tipo": "numero"
    }
  ],
  "obrigatorio": true
}
```

`caminho_saida` não é hardcode de domínio: é relativo ao item declarado no
contrato. A mesma capacidade serve para qualquer tabela e qualquer schema.

### Mudança de validação para arrays

Quando `tipo_origem` for `linhas_de_tabela` e o `mapping_path` for exatamente
um path de array permitido no contrato, a ausência de `[seletor=valor]` deve
ser aceita. A entrada representa a coleção inteira, e não apenas um item.

Para mapeamentos de campo individual dentro de array, o seletor continua
obrigatório.

Essa exceção é indispensável para reproduzir o layout de referência. Os paths
de coleção, por exemplo `grupo.serie_mensal`, não representam um único item e
portanto não devem exigir a forma `grupo.serie_mensal[chave=valor]` quando a
origem é `linhas_de_tabela`.

### Implementação na DAG 2

- Validar que cada `caminho_saida` existe no schema do item da coleção.
- Para cada linha selecionada, criar um item e preencher os paths relativos
  declarados em `campos`.
- Aplicar conversão numérica somente quando `tipo` for `numero`.
- Manter o formato posicional atual como compatibilidade legada quando
  `campos` não estiver presente.
- Registrar na auditoria faixa, colunas, valor bruto e valor normalizado.

### Testes mínimos

- tabela simples para uma lista de objetos;
- campo aninhado no item (`periodo.rotulo_publicado`);
- duas faixas com colunas distintas;
- preservação do formato legado sem `campos`;
- rejeição de `caminho_saida` que não pertença ao item do array.

## Melhoria 5 — Evidência tabular suficiente para o mapeamento

### Problema

O carregador de artefatos entrega somente uma amostra inicial de tabelas. Na
execução de referência, a LLM recebeu cinco linhas da tabela mensal e oito
linhas da tabela histórica. Porém o layout esperado depende de faixas que não
aparecem na amostra, como meses posteriores ou blocos de linhas mais abaixo na
tabela por instituição.

Uma LLM não deve ser cobrada por declarar uma faixa, seção ou coluna que não
estava presente na evidência recebida.

### Comportamento esperado

Para uma tabela selecionada, o payload deve conter evidência suficiente para
que a LLM determine sua estrutura completa:

- quantidade total de linhas e colunas;
- schema/cabeçalhos completos;
- todas as linhas, quando a tabela for pequena;
- para tabelas grandes, janelas determinísticas distribuídas pela tabela,
  preservando índice absoluto de cada linha;
- metadados auxiliares da extração, quando identificarem blocos ou seções.

Exemplo de formato para uma tabela grande:

```json
{
  "quantidade_linhas": 36,
  "schema": ["..."],
  "janelas": [
    {"linha_inicial": 0, "linha_final": 7, "rows": []},
    {"linha_inicial": 8, "linha_final": 15, "rows": []},
    {"linha_inicial": 16, "linha_final": 23, "rows": []},
    {"linha_inicial": 24, "linha_final": 35, "rows": []}
  ]
}
```

### Implementação

- Definir um limite de tamanho em caracteres/tokens para tabelas completas.
- Quando a tabela couber nesse limite, enviar todas as linhas.
- Acima do limite, montar janelas por posição de forma determinística, em vez
  de enviar sempre apenas as primeiras linhas.
- Manter o `indice_linha` original em cada janela.
- Se houver cabeçalhos internos, divisores ou rótulos de seção, priorizar sua
  inclusão nas janelas.

Essa regra depende apenas da estrutura do artefato, não do domínio do PDF.

### Testes mínimos

- tabela pequena chega completa ao payload;
- tabela grande contém janelas de início, meio e fim;
- índices das linhas permanecem iguais aos do arquivo de origem;
- um bloco localizado depois da primeira amostra é visível à LLM.

## Melhoria 6 — Granularidade adaptativa das unidades LLM

### Problema

`financiamentos_imobiliarios` foi tratada como uma única unidade, embora
contenha três coleções independentes e três tabelas diferentes. Mesmo com o
contexto menor que o candidato completo, a LLM recebeu uma tarefa que exigia
mapear meses, anos e instituições de uma vez.

### Regra genérica proposta

Antes de chamar a LLM, a DAG deve observar os paths obrigatórios do contrato:

- cada coleção obrigatória independente pode se tornar uma subunidade;
- campos escalares próximos podem permanecer agrupados;
- o limite pode ser guiado por quantidade de paths, quantidade de coleções ou
  tamanho estimado da evidência.

Exemplo estrutural:

```text
grupo
├── serie_mensal        -> subunidade 1
├── serie_historica     -> subunidade 2
└── registros_por_entidade -> subunidade 3
```

Não há referência a nomes de domínio: a divisão depende do tipo estrutural do
schema e dos requisitos obrigatórios.

### Benefícios

- Menos contexto por chamada.
- Respostas menores.
- Retry localizado: uma falha na série histórica não invalida a série mensal.
- Melhor observabilidade por coleção.
- Possibilidade futura de dynamic task mapping no Airflow, com uma task por
  subunidade.

### Testes mínimos

- contrato só com escalares gera uma unidade;
- contrato com três arrays independentes gera três subunidades;
- consolidação final preserva todos os fragmentos;
- falha de uma subunidade não descarta respostas válidas das demais.

## Melhoria 7 — Retry útil e observabilidade de chamadas bem-sucedidas

### Problema

Quando uma chamada retorna JSON válido, mas a validação local a rejeita,
`api_response_metadata` foi persistido como `null`. Isso esconde consumo,
latência e `finish_reason` justamente nos casos de maior interesse.

Além disso, o retry reenvia a resposta inválida completa. Em respostas grandes
isso aumenta muito o prompt e tende a reproduzir a mesma saída.

### Implementação

- Carregar os metadados retornados pelo cliente LLM junto com a resposta
  parseada e propagá-los até os artefatos de erro de validação.
- Persistir por tentativa: modelo, provider, `finish_reason`, `usage`, tamanho
  de `content`, tamanho de `reasoning_content`, duração e modo thinking.
- Para erro de formato, enviar no retry apenas:
  - erro determinístico;
  - path ou entrada inválida;
  - formato correto esperado;
  - trecho de resposta que precisa ser alterado.
- Não reenviar o candidato inteiro quando o erro puder ser corrigido em uma
  entrada específica.

## Ordem recomendada de execução

### Caminho prioritário: coleções originadas em tabelas

Este é o caminho que reproduz o layout de referência e deve ser priorizado:

1. Alinhar o schema de resposta, os exemplos e a validação por tipo de origem.
   O prompt deve ensinar explicitamente `linhas_de_tabela`, `segmentos`,
   `campos` e `valores_por_segmento`, no formato já aceito pelo resolvedor.
2. Implementar projeção estruturada de `linhas_de_tabela` para itens de array,
   preservando o formato legado com `campos.nome` como compatibilidade.
3. Liberar `linhas_de_tabela` no path raiz de uma coleção, sem seletor de item.
4. Melhorar o carregamento de evidência tabular completa ou por janelas
   determinísticas.
5. Implementar divisão adaptativa por coleções obrigatórias.
6. Melhorar retry e observabilidade.

### Caminho complementar: correções pontuais em itens de array

O suporte a filtros aninhados permanece importante, mas é complementar. Ele é
necessário quando uma correção deve atingir um item já conhecido dentro de uma
coleção, e não quando uma tabela inteira está sendo criada pela primeira vez.

7. Implementar e testar o parser compartilhado de paths.
8. Implementar suporte da DAG 2 a seletores aninhados.

Essa ordem evita investir primeiro em centenas de paths de célula individual.
Ela permite que a DAG 3 gere layouts curtos, auditáveis e escaláveis para
tabelas repetitivas, mantendo a capacidade futura de corrigir um registro
específico.
