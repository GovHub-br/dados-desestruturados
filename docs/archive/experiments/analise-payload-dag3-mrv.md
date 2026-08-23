# Análise da Entrada LLM para Gerar Layout Signature — MRV, 16/07

## Objetivo

Este documento analisa exclusivamente a **segunda etapa da DAG 3**: a chamada
que recebe os artefatos já selecionados e gera ou corrige o
`layout_signature_candidato`.

A seleção de artefatos da execução `dia16_8h` foi suficiente para o objetivo:

- `tables/table002.json` cobre lançamentos;
- `tables/table003.json` cobre vendas.

Portanto, ela é uma pré-condição já satisfeita. O foco agora é reduzir e tornar
mais didático o contexto enviado para a geração do layout **na primeira
tentativa**. O desenho do retry será decidido depois.

## Diagnóstico do candidato aceito

O candidato passou formalmente, mas o resultado resolvido mostra que a chamada
não entendeu por completo a estrutura de saída:

- mapeou somente a coluna `1T26`; deixou de fora `4T25` e `1T25`, que estão nas
  mesmas tabelas e são necessários para comparações posteriores;
- usou `valores[escopo_periodo=trimestre]` como seletor do array. Esse seletor
  não é único: todas as observações trimestrais compartilham o mesmo valor;
- como consequência, o `schema_saida_resolvido` materializou um objeto dentro
  de `valor`, em vez de uma observação com `periodo` e `valor` no mesmo nível;
- mapeou `periodo_referencia` a partir de `blocks/blocks.jsonl`, embora esse
  arquivo não estivesse entre os artefatos carregados para a segunda chamada;
- `fonte`, `metricas_calculadas` e `periodos_disponiveis` permaneceram nulos.

Além disso, a revalidação ficou `compativel` com `regras_total: 0`. Ela não
comprovou a qualidade semântica do resultado; apenas não possuía uma regra que
o reprovasse.

## O que a segunda chamada recebe hoje

O `user_payload` inicial de
`entrada_llm_layout_signature_candidato.json` tem aproximadamente 16,7 KB. A
tentativa de correção adiciona `correcao_candidato` (~4,2 KB), chegando a mais
de 20 KB de JSON parcialmente repetido.

| Chave | Tamanho aprox. | Decisão | Utilidade real e recomendação |
| --- | ---: | --- | --- |
| `tipo_payload` | pequeno | Manter | Informa que o caso é criação inicial, correção parcial ou remapeamento. |
| `escopo_permitido` | pequeno | Manter | É a decisão dinâmica que delimita o que pode ser criado ou alterado. O seu significado deve estar explicado no prompt. |
| `layout_candidate_lineage` | ~0,2 KB | Retirar | É linhagem operacional. `document_id` e `execution_id_origem` devem vir no cabeçalho do exemplo/estrutura exigida, sem expor uma chave de lineage à LLM. |
| `artefatos_contexto_llm` | ~1,9 KB | Manter | É a evidência da chamada. Deve conter apenas os artefatos selecionados, com tabelas, cabeçalhos e linhas que serão usadas. |
| `selecao_artefatos_llm` | ~0,6 KB | Retirar | Os mesmos paths já estão em `artefatos_contexto_llm`; a proveniência continua persistida no MinIO, mas não precisa ser reenviada à LLM. |
| `contrato_semantico_relevante` | ~5,3 KB | Manter e reorganizar | A semântica do contrato é necessária. A estrutura do schema deve ser apresentada de forma mais legível e explicada por instruções textuais antes de a LLM recebê-la. Os trechos artificiais `<truncado>` devem sair. |
| `contrato_saida_candidato` | ~2,6 KB | Renomear e simplificar | O novo nome será `exemplo_estrutura_layout_signature`. Ele deve mostrar a forma esperada do layout, sem acumular regras operacionais repetidas. |
| `llm_constraints` | ~0,7 KB | Retirar do payload | As regras serão explicadas em textos específicos por escopo: criação inicial, correção parcial e regeneração completa. Regras internas como chunking não pertencem ao contexto da LLM. |
| `regras_de_saida` | ~0,2 KB | Retirar | Duplica escopo, constraints e instruções do prompt. |
| `estado_chunking` | ~0,1 KB | Retirar | Chunking é controle lógico da DAG. A LLM deve apenas receber o conteúdo de evidência que a DAG decidiu enviar. |
| `correcao_candidato` | ~4,2 KB, apenas no retry | Fora do escopo agora | A análise e o desenho do retry serão feitos depois da primeira tentativa estar bem definida. |

## Como `contrato_semantico_relevante` é montado hoje

Essa chave não vem pronta do JSON do contrato. O builder monta um recorte com
seis partes:

| Parte atual | Como o código a cria | Utilidade para a primeira geração |
| --- | --- | --- |
| `identificacao` | Copia nome, versão e domínio do contrato. | Contexto leve; pode permanecer dentro do contrato. |
| `schema_saida_campos_raiz` | Lista e ordena as chaves do primeiro nível de `schema_saida`. | Útil para entender os blocos principais, mas não basta para montar arrays. |
| `schema_saida_paths` | Percorre recursivamente todo objeto do `schema_saida` e registra cada objeto e folha navegável. | Importante: limita os paths que a LLM pode mapear. Deve ser explicado em texto como “paths permitidos de saída”. |
| `schema_saida_array_paths` | Faz outra travessia recursiva, registrando os paths que são listas. | Importante: mostra onde a assinatura precisa de seletor entre colchetes. Deve ser explicado com exemplo. |
| `schema_saida_trechos_relevantes` | Copia fragmentos do schema, usando profundidade limitada. Quando não há campos quebrados, copia o schema inteiro com profundidade 2. | Deve ser retirado desta primeira chamada: repete as informações dos paths e é a principal fonte de `<truncado>`. |
| `entidades` e `metricas` | Copia essas seções do contrato semântico com profundidade limitada. | Manter a semântica, mas sem substituir níveis profundos por texto artificial. Se for grande, criar um resumo semântico determinístico e legível. |

### Por que aparece `<truncado>`

`<truncado>` não existe no contrato e não vem da extração. Ele é inserido pela
função `_truncate_json` para evitar payloads muito profundos:

- em `schema_saida_trechos_relevantes`, a profundidade máxima é 2 na criação
  inicial e 4 em correções com campos quebrados;
- em `entidades` e `metricas`, a profundidade máxima padrão é 5;
- listas também são limitadas aos primeiros 8 itens e objetos aos primeiros 20
  campos.

Esse mecanismo reduz tokens, mas cria um falso valor textual no contexto. Para
a LLM, `<truncado>` parece conteúdo de um contrato, embora seja apenas uma
lacuna. A primeira geração não deve receber esses fragmentos incompletos.

O desenho recomendado é manter o contrato semântico em duas partes explícitas:

```json
{
  "contrato_semantico": {
    "entidades": "definições semânticas necessárias",
    "metricas": "grupos e medidas brutas a extrair"
  },
  "estrutura_schema_saida": {
    "campos_raiz": ["..."],
    "paths_permitidos": ["..."],
    "arrays_que_exigem_seletor": ["..."]
  }
}
```

Antes desse bloco, uma instrução textual deve explicar que `paths_permitidos`
limitam as chaves do `mapeamento_canonico` e que cada path listado em
`arrays_que_exigem_seletor` precisa de um identificador único como
`[papel_periodo=periodo_referencia]`.

## Payload mínimo recomendado

O payload deve conter apenas fatos que variam por execução. Um formato
conceitual para criação inicial seria:

```json
{
  "contexto_execucao": {
    "escopo": "criacao_inicial_layout",
    "document_id": "...",
    "execution_id_origem": "..."
  },
  "contrato_semantico": {
    "metricas": "definições necessárias do contrato"
  },
  "estrutura_schema_saida": {
    "paths_permitidos": ["..."],
    "arrays_que_exigem_seletor": ["..."]
  },
  "alvos_mapeaveis": [
    {
      "grupo": "lancamentos",
      "valor_path": "balancos_das_empresas.lancamentos.dados.valores.valor",
      "papeis_periodo": [
        "periodo_referencia",
        "periodo_comparativo_anterior",
        "mesmo_periodo_ano_anterior"
      ],
      "estrutura_array": {
        "empresa": "MRV",
        "seletor_valores": "papel_periodo"
      }
    },
    {
      "grupo": "vendas",
      "valor_path": "balancos_das_empresas.vendas.dados.valores.valor",
      "papeis_periodo": [
        "periodo_referencia",
        "periodo_comparativo_anterior",
        "mesmo_periodo_ano_anterior"
      ],
      "estrutura_array": {
        "empresa": "MRV",
        "seletor_valores": "papel_periodo"
      }
    }
  ],
  "exemplo_estrutura_layout_signature": {
    "mapeamento_canonico": "exemplo compacto de seletor de tabela e período"
  },
  "artefatos": {
    "tables/table002.json": "conteúdo selecionado pela etapa 1",
    "tables/table003.json": "conteúdo selecionado pela etapa 1"
  }
}
```

`alvos_mapeaveis` deve ser derivado deterministicamente do contrato semântico.
Assim, não há hardcode de MRV no código: outro contrato produzirá outros
grupos, paths e papéis de período.

## Instruções textuais distribuídas antes de cada contexto

Não deve existir apenas um parágrafo genérico para o documento todo. A chamada
de geração deve aceitar uma sequência ordenada de mensagens: textos de
instrução e blocos JSON, alternados conforme a responsabilidade de cada bloco.

Isso requer que o cliente deixe de receber somente `system_prompt: str` e
`user_payload: dict`. A interface deve aceitar uma lista ordenada de mensagens,
preservando o mesmo mecanismo de resposta JSON. Exemplo conceitual:

```text
system: instrução específica do escopo atual
user:   contexto_execucao
system: como ler o contrato semântico e a estrutura do schema
user:   contrato_semantico + estrutura_schema_saida + alvos_mapeaveis
system: como usar o exemplo de layout e como montar seletores
user:   exemplo_estrutura_layout_signature
system: como usar somente evidências carregadas e resumo final da tarefa
user:   artefatos_contexto_llm
```

Cada texto deve explicar apenas o bloco que o sucede, e o texto final deve
recapitular a tarefa inteira antes da resposta.

Cada uma dessas instruções deve ser escrita em **texto corrido e didático**.
Não basta listar comandos como “use paths permitidos” ou “use seletor único”.
O texto precisa explicar o que aquele bloco representa, por que ele existe,
como a LLM deve utilizá-lo e o que não deve concluir a partir dele. Listas e
exemplos JSON podem complementar a explicação, mas não substituí-la.

### Instrução 1: escopo da execução

Deve haver um texto diferente para cada caso:

- **criação inicial:** não existe layout ativo; criar apenas o mapeamento novo a
  partir do contrato e dos artefatos selecionados;
- **correção parcial:** existe layout base; alterar somente os paths afetados
  pela falha recebida;
- **regeneração completa:** o layout anterior não é confiável; reconstruir os
  mapeamentos permitidos a partir das evidências atuais.

Esse texto substitui `llm_constraints`. Não deve mencionar `chamar_llm`,
chunking, layouts versionados ou outras decisões internas da DAG.

### Instrução 2: como ler o contrato semântico

Explicar, antes do bloco do contrato, que:

- as métricas descrevem quais valores brutos devem ser localizados;
- `paths_permitidos` são as únicas chaves aceitas no
  `mapeamento_canonico`;
- paths de arrays exigem seletor único;
- a LLM não cria campos, contratos, regras de execução ou valores de negócio.

### Instrução 3: como usar o exemplo de estrutura

O bloco agora chamado `exemplo_estrutura_layout_signature` deve vir precedido
por um texto que diga que ele é um modelo de sintaxe, não uma fonte de dados.
Explicar que uma entrada válida precisa de:

- um path presente em `alvos_mapeaveis`;
- um `tipo_origem` permitido;
- `arquivo_origem` presente em `artefatos` quando houver leitura de arquivo;
- seletor de linha e coluna quando a origem for tabela;
- seletor único de array;
- papel de período para cada coluna comparativa.

O texto deve afirmar explicitamente que `escopo_periodo` não identifica uma
observação sozinho. Para valores trimestrais, o identificador do array deve ser
o papel semântico: `periodo_referencia`,
`periodo_comparativo_anterior` ou `mesmo_periodo_ano_anterior`.

### Instrução 4: como usar os artefatos

Antes de `artefatos_contexto_llm`, explicar que eles são a única evidência de
origem disponível. Todo `arquivo_origem` do candidato deve aparecer nesse
bloco. Se uma tabela contém as três colunas de período exigidas em
`alvos_mapeaveis`, a LLM deve produzir três mapeamentos: um para cada papel.
Não deve escolher somente a primeira coluna por ser a referência atual.

### Instrução 5: resumo final antes da resposta

O último texto deve resumir, sem acrescentar novas regras:

- não usar artefato não carregado;
- não criar paths fora de `alvos_mapeaveis`;
- não produzir valores finais de negócio;
- não criar metadados, publicação, contrato ou regras de execução;
- não explicar a resposta fora do JSON.

## Ordem recomendada de implementação

1. Retirar `layout_candidate_lineage`, `selecao_artefatos_llm`,
   `llm_constraints`, `regras_de_saida` e `estado_chunking` da primeira
   chamada de geração.
2. Reorganizar `contrato_semantico_relevante`, sem retirar sua semântica, e
   eliminar os fragmentos com `<truncado>`.
3. Renomear `contrato_saida_candidato` para
   `exemplo_estrutura_layout_signature`.
4. Criar mensagens de instrução distribuídas por escopo, contrato, exemplo,
   artefatos e resumo final.
5. Criar um adaptador de payload que derive `alvos_mapeaveis` e a estrutura de
   arrays a partir do contrato.
6. Adicionar regras de revalidação para períodos obrigatórios, unicidade dos
   seletores de array, tipo numérico em `valor` e origem limitada a artefatos
   carregados.

Esse desenho preserva a seleção de artefatos já aprovada e concentra a melhoria
onde ela é necessária: transformar evidências corretas em um layout signature
que a DAG 2 resolve sem ambiguidade.
