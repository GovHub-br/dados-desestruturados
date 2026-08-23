# Resolução Determinística do Schema de Saída na DAG 2

## Objetivo

Registrar as extensões determinísticas da DAG 2 para reutilizar contratos e
layouts entre famílias de PDFs, sem codificar regras de uma empresa específica
no resolvedor.

## Contrato por execução

`dag_resolve_schema_saida` aceita `contrato_semantico_uri` na configuração da
execução. Quando informado, esse URI substitui o contrato padrão das
construtoras somente naquela execução. Assim, o mesmo resolvedor pode validar,
por exemplo, contratos de construtoras e da ABECIP.

## `campo_json`

O tipo de origem `campo_json` lê um valor literal de um arquivo JSON da
extração:

```json
{
  "tipo_origem": "campo_json",
  "arquivo_origem": "manifesto_execucao.json",
  "caminho_json": "candidate.period_label"
}
```

Ele não transforma o valor. Não há conversão de mês, rótulo em português ou
cálculo de início/fim de período na DAG 2.

Se o contrato exigir datas normalizadas, a origem deve publicar explicitamente
os campos necessários, por exemplo:

```json
{
  "candidate": {
    "periodo_referencia": {
      "data_inicio": "2026-05-01",
      "data_fim": "2026-05-31"
    }
  }
}
```

## `linhas_de_tabela`

O formato semântico é apropriado quando a assinatura precisa ligar colunas a
nomes de campos do schema:

```json
{
  "linha_inicial": 1,
  "linha_final": 9,
  "campos": [{"nome": "campo_do_contrato", "indice_coluna": 0}]
}
```

O formato estrutural é uma alternativa quando a intenção for selecionar apenas
linhas e colunas:

```json
{
  "tipo_origem": "linhas_de_tabela",
  "arquivo_origem": "tables/table003.json",
  "segmentos": [
    {"linha_inicial": 0, "linha_final": 11, "indices_colunas": [0, 5]},
    {"linha_inicial": 0, "linha_final": 4, "indices_colunas": [0, 11]}
  ]
}
```

Também são aceitos `faixas_linhas` e uma faixa simples com
`linha_inicial`/`linha_final` e `indices_colunas`.

O resultado estrutural preserva a origem sem inferência:

```json
{
  "indice_linha": 0,
  "valores": [
    {"indice_coluna": 0, "valor": "Jan"},
    {"indice_coluna": 5, "valor": "-128,6"}
  ]
}
```

Esse formato é uma leitura bruta. Para preencher objetos semânticos finais, o
contrato e um mapeador semântico posterior precisam estabelecer o significado
dos valores selecionados. No formato semântico, `valores_fixos` acrescenta
contexto igual a todas as linhas do mapeamento. Quando o contexto muda entre
segmentos ou faixas, use `valores_por_segmento` no seletor correspondente.

## `juncao_de_registros_json`

Use esse tipo quando uma observação final precisa combinar campos publicados em
duas ou mais listas JSON distintas, como linhas normalizadas de gráficos. Cada
fonte declara seu arquivo, o caminho da chave e os caminhos dos campos que ela
fornece; a DAG 2 faz uma junção interna somente pelas chaves presentes em todas
as fontes.

```json
{
  "tipo_origem": "juncao_de_registros_json",
  "fontes": [
    {
      "arquivo_origem": "charts/grafico_valor/normalized_rows.json",
      "caminho_chave": "attributes.periodo",
      "campos": [
        {"campo_saida": "valor", "caminho_json": "measures.valor", "tipo": "numero"}
      ]
    },
    {
      "arquivo_origem": "charts/grafico_quantidade/normalized_rows.json",
      "caminho_chave": "attributes.periodo",
      "campos": [
        {"campo_saida": "quantidade", "caminho_json": "measures.quantidade", "tipo": "numero"}
      ]
    }
  ]
}
```

`valores_fixos` pode acrescentar contexto comum aos registros. Para contexto
dependente do rótulo, `valores_por_chave` declara um `padrao_chave` e os valores
aplicáveis. O resolvedor não interpreta o período, não converte unidade e não
atribui significado aos campos: essas decisões permanecem no contrato e na
assinatura de layout.

## Seleção de linha em validações

Regras de validação tabular podem declarar `indice_linha_esperado`. O resolvedor
testa primeiro essa posição e só depois procura a mesma linha na tabela inteira.
Isso reduz ambiguidades quando um rótulo é repetido.

## Situação ABECIP

O layout ABECIP usa campos semânticos declarados no próprio layout, com
segmentos e faixas para as tabelas mensais e por bloco. O manifesto atual
fornece `candidate.period_label`; ele ainda precisa passar a
publicar `candidate.periodo_referencia.data_inicio` e `data_fim` para que a
DAG 2 resolva esses limites sem regras específicas.
