# Modelo e Checklist de Contrato Semântico

## Estrutura mínima

```json
{
  "nome": "família documental",
  "dominio": "identificador-estavel-do-dominio",
  "entidade": "identificador-da-entidade-ou-fonte",
  "fonte": "nome da fonte",
  "tipo_documento": "familia_documental",
  "versao": "1.0.0",
  "descricao": "Escopo do contrato e limite da extração.",
  "contrato_semantico": {
    "principios": {},
    "entidades": {},
    "requisitos_mapeamento": {
      "papeis": {},
      "campos_obrigatorios": []
    },
    "chaves_de_item": {},
    "derivacoes": []
  },
  "schema_saida": {}
}
```

`requisitos_mapeamento.papeis`, `chaves_de_item` e `derivacoes` são opcionais
— um contrato sem eles segue o caminho legado de resolução, sem erro (ADR
0011) — mas devem ser declarados sempre que o fato de negócio permitir; é o
que faz a DAG 2 resolver e a DAG 3 gerar layout por código em vez de pedir
à LLM a cada documento. Ver a seção "Modo genérico" abaixo.

`contrato_semantico` explica linguagem e regras. `schema_saida` é o molde que
a DAG 2 preencherá. Não use o primeiro como substituto do segundo.

`dominio` deve ser o mesmo usado nos documentos de origem e no caminho de
publicação do contrato. A seleção automática escolhe a maior versão semântica
publicada para esse domínio.

## Semântica das folhas do schema

Uma folha descrita por `string`, `number`, `integer`, `boolean`, `object`,
`array`, `null` ou uma união desses tipos (por exemplo, `number | null`) é
dinâmica. Todo outro valor é literal e será reaplicado pela DAG 2 em cada
ocorrência do template.

```json
{
  "periodo": {"rotulo": "string", "tipo": "mensal"},
  "unidade": "unidades",
  "valor": "number | null"
}
```

No exemplo, `rotulo` e `valor` são dinâmicos; `tipo` e `unidade` são
determinísticos. Para um domínio de valores variável, use `string` no schema e
documente o vocabulário em `entidades`; não use `"a | b"`, pois isso seria
interpretado como literal.

## Requisitos mínimos para a DAG 3

`contrato_semantico.requisitos_mapeamento.campos_obrigatorios` é obrigatório
em contratos que podem acionar criação ou correção de layout pela DAG 3. Cada
item declara um `path` dinâmico presente no `schema_saida`:

```json
{
  "requisitos_mapeamento": {
    "campos_obrigatorios": [
      {"path": "observacoes"},
      {
        "path": "indicadores.itens.valor",
        "observacoes_obrigatorias": [
          {
            "seletores": {"categoria": "principal"},
            "campos_contexto_obrigatorios": ["periodo", "unidade"]
          }
        ]
      }
    ]
  }
}
```

Declare uma coleção quando uma origem produz o registro completo. Use uma folha
e seletores apenas quando o contrato exige uma observação identificável antes
de conhecer o próximo documento. Não inclua valores fixos, metadados
operacionais ou campos opcionais apenas por completude.

## Modo genérico: `chaves_de_item`, `papeis` e `derivacoes`

Exemplo completo, reduzido do contrato real `construtoras v1.9.1`
(`infra/minio-bootstrap/contracts/construtoras/v1.9.1/`), com os quatro
blocos que tiram trabalho da LLM na DAG 3 (ver `SKILL.md` para a explicação
de cada um):

```json
{
  "contrato_semantico": {
    "requisitos_mapeamento": {
      "papeis": {
        "papel_periodo": {
          "periodo_referencia": {
            "descricao": "Periodo a que o documento se refere.",
            "derivacao": {"origem": "identidade_documento.periodo"}
          },
          "periodo_comparativo_anterior": {
            "descricao": "Periodo imediatamente anterior, no mesmo escopo.",
            "derivacao": {"relacao": "anterior", "passo": 1}
          },
          "mesmo_periodo_ano_anterior": {
            "descricao": "Mesmo periodo do ano anterior.",
            "derivacao": {"relacao": "mesmo_periodo_ano_anterior"}
          }
        }
      },
      "campos_obrigatorios": [
        {
          "path": "balancos_das_empresas.lancamentos.dados.valores.valor",
          "evidencia_esperada": {
            "valor": "celula_de_tabela",
            "periodo": "cabecalho_de_tabela"
          },
          "observacoes_obrigatorias": [
            {
              "seletores": {"papel_periodo": "periodo_referencia"},
              "campos_contexto_obrigatorios": ["periodo", "escopo_periodo"]
            },
            {
              "seletores": {"papel_periodo": "periodo_comparativo_anterior"},
              "campos_contexto_obrigatorios": ["periodo", "escopo_periodo"],
              "obrigatorio": false
            }
          ]
        }
      ]
    },
    "chaves_de_item": {
      "balancos_das_empresas.lancamentos.dados": {
        "chave": "empresa",
        "origem_valor": "identidade_documento"
      },
      "balancos_das_empresas.lancamentos.dados.valores": {
        "chave": "papel_periodo",
        "origem_valor": "seletor_observacao"
      }
    },
    "derivacoes": [
      {"destino": "fonte", "origem": {"tipo": "contrato", "campo": "fonte"}},
      {
        "destino": "periodos_disponiveis.periodo_referencia",
        "origem": {
          "tipo": "observacao", "campo": "periodo",
          "seletor": {"papel_periodo": "periodo_referencia"}
        }
      }
    ]
  }
}
```

Leitura de cima para baixo, para quem está montando um contrato novo:

1. **`papeis`** nomeia os valores que o seletor `papel_periodo` (usado dentro
   de `observacoes_obrigatorias`) pode assumir, e diz como calcular dois deles
   sem LLM (`anterior`, `mesmo_periodo_ano_anterior`) a partir do terceiro
   (`periodo_referencia`, derivado da identidade do documento). Todo seletor
   citado em `observacoes_obrigatorias[].seletores` tem que aparecer aqui —
   a validação (`role_specs_from_context`) recusa o contrato se sobrar um dos
   dois lados.
2. **`campos_obrigatorios[].evidencia_esperada`** diz que o valor sempre vem
   de célula de tabela e o período do cabeçalho da mesma tabela — a LLM não
   precisa decidir o `tipo_origem`.
3. **`chaves_de_item`** diz que o array de empresas é indexado por `empresa`
   (valor vem da identidade do documento, o código copia) e o array de
   valores é indexado por `papel_periodo` (valor é um dos seletores já
   declarados acima, o código enumera) — nenhum dos dois fica com a LLM para
   inventar.
4. **`derivacoes`** preenche `fonte` (do próprio contrato) e cada
   `periodos_disponiveis.<papel>` (do valor de `periodo` na observação que
   casa aquele papel) sem pedir mapeamento nenhum para esses campos.

O ganho de declarar tudo isso, medido nas releases do plano de assinatura de
layout (`docs/guides/registro-de-releases.md`): a Fase 1 zerou
`assinatura_f1_chaves_fora_das_esperadas` (a LLM parou de inventar filtro de
array) justamente porque `chaves_de_item`+`papeis` já diziam a chave certa; o
item 3.2 fechou a variância de ancoragem de linha do Plano&Plano por
`chaves_de_item`/sinônimo, não por sorte de LLM; a Fase 2 usa `derivacao` para
resolver a coluna de cada papel de período por código. Um contrato que
declare esses blocos de forma completa tende a custar menos tokens e ter
menos variância entre execuções do mesmo documento — não é só documentação,
é o que o código lê para decidir o que ele resolve sozinho.

## Roteiro de modelagem

### 1. Inventário de fatos

Para cada item desejado, responda:

- Qual é a medida bruta?
- Qual é sua unidade e escala tal como publicada?
- Quais dimensões a identificam?
- Qual período ela representa?
- É uma série mensal, observação anual, acumulado publicado, detalhe por
  entidade ou outro grão?
- É observação do documento ou cálculo posterior?

Se duas respostas tiverem grãos diferentes, crie coleções distintas no schema.

### 2. Períodos

Represente o período dentro da observação quando ele variar por linha. Preserve
ao menos o rótulo publicado e, quando a origem fornecer, limites de início/fim
e tipo de período. A DAG 2 lê metadados disponíveis; ela não deve transformar
`2026-05` em datas por uma regra específica da família documental.

### 3. Unidades e escalas

Escolha nomes que impedem ambiguidade. Exemplos:

```json
{
  "valor_financiado_bilhoes": "number | null",
  "unidades_financiadas_mil": "number | null"
}
```

Não nomeie `valor_milhoes` se a origem publica bilhões. Converter unidade é uma
transformação explícita, posterior e rastreável; não é uma consequência oculta
da resolução.

### 4. Dados brutos versus derivados

Inclua como bruto: valor publicado, quantidade publicada, período, dimensão,
unidade e contexto declarados pela fonte.

Exclua ou marque para transformação posterior: percentuais comparativos,
participação, ranking calculado, médias, acumulados reconstruíveis e variações
entre períodos, salvo se forem o fato solicitado e não puderem ser
reconstruídos.

### 5. Obrigatoriedade

Use campos obrigatórios no sentido operacional: a ausência impede o caso de
uso. Não torne obrigatório um enriquecimento que o PDF pode deixar de publicar
regularmente. Registre ausência na auditoria em vez de inventar valor.

## Relação contrato e layout

| Decisão no contrato | Consequência no layout |
| --- | --- |
| Uma medida escalar | Uma origem simples pode bastar. |
| Uma lista de observações | O layout precisa selecionar várias linhas ou registros. |
| Medidas com grãos diferentes | Mapeamentos e coleções independentes. |
| Uma observação com campos em fontes diferentes | Junção declarada por chave, ou revisão do contrato para listas separadas. |
| Unidade/escala preservada | O layout lê a medida publicada sem conversão implícita. |
| Campo obrigatório | O layout deve ter evidência e regra de validação apropriadas. |
| `chaves_de_item` declarado | A DAG 3 enumera a chave do filtro por código; a LLM só resolve o que `origem_valor=evidencia` deixar para ela. |
| `papeis.*.derivacao` declarado | A DAG 3 resolve a coluna/observação do papel por código (quando o rótulo é reconhecível); sem isso, é decisão livre da LLM a cada documento. |

## Exemplo: duas fontes para uma observação

Quando o contrato requer uma única observação por período com `valor` e
`quantidade`, mas cada medida está em um gráfico separado, o layout pode fazer
uma junção interna pela chave bruta de período:

```json
{
  "tipo_origem": "juncao_de_registros_json",
  "fontes": [
    {
      "arquivo_origem": "charts/valor/normalized_rows.json",
      "caminho_chave": "attributes.periodo",
      "campos": [
        {"campo_saida": "periodo.rotulo_publicado", "caminho_json": "attributes.periodo"},
        {"campo_saida": "valor_bilhoes", "caminho_json": "measures.valor", "tipo": "numero"}
      ]
    },
    {
      "arquivo_origem": "charts/quantidade/normalized_rows.json",
      "caminho_chave": "attributes.periodo",
      "campos": [
        {"campo_saida": "quantidade_mil", "caminho_json": "measures.quantidade", "tipo": "numero"}
      ]
    }
  ]
}
```

Isso não interpreta datas nem calcula valores: apenas associa registros que já
publicam a mesma chave. Se a relação não for natural ou segura, prefira duas
listas independentes no contrato.

## Checklist de aprovação

- [ ] A família documental e o caso de uso estão explícitos.
- [ ] Todos os campos do schema têm propósito de negócio.
- [ ] Chaves não carregam mês, ano, empresa ou posição visual.
- [ ] Grão e período estão claros em cada lista.
- [ ] Unidade e escala são preservadas ou declaradas explicitamente.
- [ ] Métricas derivadas estão fora da extração bruta.
- [ ] A estrutura não depende de página, tabela ou título atual.
- [ ] Cada campo obrigatório tem uma origem viável na extração ou no manifesto.
- [ ] `campos_obrigatorios` é não vazio, contém apenas paths dinâmicos do
      `schema_saida` e representa o mínimo necessário para o caso de uso.
- [ ] Literais do schema representam somente valores invariáveis; valores
      possíveis ou variáveis foram descritos como tipos dinâmicos.
- [ ] Cada array do `schema_saida` que tem item identificável declara
      `chaves_de_item` com `origem_valor` (`identidade_documento` ou
      `seletor_observacao` sempre que possível; `evidencia` só quando o valor
      realmente varia sem regra fixa por documento).
- [ ] Cada seletor usado em `observacoes_obrigatorias` tem todos os seus
      papéis descritos em `papeis`, e os papéis deriváveis (a partir da
      identidade do documento ou de outro papel) declaram `derivacao`.
- [ ] `campos_obrigatorios[].evidencia_esperada` declara o `tipo_origem`
      esperado quando ele é previsível pelo próprio fato de negócio.
- [ ] Campos de raiz que só espelham o contrato, o manifesto ou uma
      observação resolvida estão em `derivacoes`, não pedidos à LLM.
- [ ] O layout poderá mudar sem alterar o contrato para uma simples mudança
      visual.
- [ ] Uma mudança de significado ou estrutura implicará nova versão do contrato.
