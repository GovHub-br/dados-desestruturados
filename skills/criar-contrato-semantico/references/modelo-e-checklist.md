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
      "campos_obrigatorios": []
    }
  },
  "schema_saida": {}
}
```

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
- [ ] O layout poderá mudar sem alterar o contrato para uma simples mudança
      visual.
- [ ] Uma mudança de significado ou estrutura implicará nova versão do contrato.
