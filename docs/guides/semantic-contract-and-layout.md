# Contrato Semântico e Layout Signature

## Objetivo

O contrato semântico define a saída estável de uma família de documentos. O
layout signature declara como obter essa saída na extração de um PDF concreto.
Ambos são versionados, mas possuem responsabilidades diferentes:

| Artefato | Responde | Contém |
| --- | --- | --- |
| Contrato semântico | O que o dado significa e como será entregue? | conceitos, granularidade, unidades, períodos, schema de saída e limites da extração |
| Layout signature | Onde e como o dado é obtido? | arquivos de extração, seletores, caminhos JSON, índices, regras de validação e mapeamento canônico |

Essa separação permite que a aparência de um PDF mude sem que o significado do
dado mude. Nesse caso, ajusta-se somente o layout.

## Fluxo

```text
Documento de origem
        ↓
Artefatos de extração (tabelas, gráficos, blocos e manifesto)
        ↓
Contrato semântico ── define a estrutura esperada ──┐
Layout signature ── localiza cada campo ────────────┤
                                                    ↓
                                     DAG 2: resolução determinística
                                                    ↓
                              schema_saida_resolvido + auditoria
                                                    ↓
                         transformação analítica e camada bronze
```

## Como criar um contrato

### 1. Definir o que é fato bruto

Comece pelo dado que precisa sobreviver à extração: valores monetários,
quantidades, dimensões, período e unidade. Percentuais comparativos, rankings,
participações e variações devem ficar fora quando puderem ser calculados depois
a partir das séries brutas.

### 2. Definir a granularidade

Cada lista no `schema_saida` deve ter uma granularidade única. Exemplos que não
devem ser misturados:

- série mensal;
- acumulado publicado no ano;
- histórico anual;
- observação por modalidade e instituição.

O contrato não deve substituir uma série mensal por um acumulado, nem assumir
que um ranking visual é uma dimensão permanente.

### 3. Modelar período, unidade e escala

Cada observação deve carregar o período publicado e seu tipo quando aplicável.
Quando a origem fornecer datas de início e fim, elas podem ser preservadas. A
DAG 2 não deve deduzir datas a partir de uma convenção específica de empresa ou
de um rótulo textual.

A unidade e a escala precisam ser inequívocas. Se o gráfico publica R$ bilhões
e milhares de unidades, use nomes que expressem isso, por exemplo
`volume_financiado_bilhoes` e `unidades_financiadas_mil`. Converter para outra
unidade é transformação posterior, explícita e rastreável.

### 4. Separar semântica da aparência

Não inclua no contrato nomes de tabela, páginas, colunas, índices ou títulos do
PDF. Esses detalhes pertencem ao layout signature. O contrato deve continuar
válido se uma tabela mudar de página ou se um cabeçalho for renomeado sem mudar
o conceito medido.

## Como o contrato influencia o layout signature

O `schema_saida` é o limite do `mapeamento_canonico`: a DAG 2 só deve resolver
campos que o contrato prometeu entregar. Portanto, antes de criar o layout,
cada campo final precisa ter uma fonte de evidência na extração.

| Forma definida pelo contrato | Estratégia correspondente no layout |
| --- | --- |
| Campo único do documento | `campo_json`, `bloco_textual`, `valor_fixo` ou outra origem simples |
| Lista proveniente de tabela | `linhas_de_tabela` com seletores e campos declarados |
| Observação formada por dois artefatos | `juncao_de_registros_json` por chave declarada |
| Dado de contexto que muda por segmento | `valores_por_segmento` ou `valores_por_chave` no layout |

O resolvedor permanece genérico: ele executa tipos e caminhos declarados no
layout, sem conhecer “ABECIP”, “construtoras”, meses ou conceitos específicos.

## Exemplo: recursos livres da ABECIP

O contrato define uma observação de recursos livres por período com volume e
unidades. A extração, porém, publica os valores em dois gráficos:

- `chart007`: valor financiado, com a chave `attributes.date`;
- `chart008`: unidades financiadas, com a chave `attributes.month`.

Os dois usam os mesmos rótulos, como `May-26` e `Jan-Mai-26`. Como o contrato
exige as duas medidas no mesmo objeto final, o layout declara uma
`juncao_de_registros_json` pelas chaves publicadas. A DAG 2 apenas associa
registros de mesma chave; ela não interpreta o período nem calcula valores.

Se o contrato tivesse definido duas listas independentes, a junção não seria
necessária. A escolha é semântica: manter medidas correlatas na mesma
observação por período ou preservá-las como séries independentes.

## Evolução e versionamento

Altere a versão do contrato quando mudar algum destes pontos:

- significado de um campo;
- estrutura do `schema_saida`;
- granularidade;
- unidade ou escala;
- obrigatoriedade de um campo.

Altere somente o layout quando mudar a localização física, o seletor, o índice,
o arquivo de extração, um título ou uma regra de validação, sem alterar o que o
dado significa. Depois de qualquer nova versão, revalide o layout com uma
extração real e consulte a auditoria da DAG 2.

## Checklist

- O contrato descreve dados de negócio, não detalhes visuais do PDF?
- Cada fato bruto possui período, unidade, escala e granularidade claros?
- Valores derivados estão fora da extração quando puderem ser calculados depois?
- Cada campo obrigatório tem uma fonte viável na extração ou no manifesto?
- O layout pode mudar por ruptura visual sem mudar o contrato?
- O `schema_saida_resolvido` pode ser consumido sem inferir contexto ausente?
