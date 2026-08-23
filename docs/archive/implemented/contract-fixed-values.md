# Plano: Valores Fixos do Contrato Fora da LLM

## Objetivo

Garantir que a LLM da DAG 3 mapeie somente informacoes cuja origem depende do
PDF. Valores semanticos estaveis, ja declarados no `schema_saida` do contrato,
devem ser aplicados deterministicamente pela DAG 2.

O plano vale para qualquer familia documental. O contrato declara os valores
fixos; o codigo nao conhece nomes de metricas, empresas ou unidades especificas.

## Problema Atual

O contrato de construtoras ja declara, por exemplo:

```json
{
  "tipo": "valor_bruto",
  "tipo_operacao": "lancamento",
  "indicador": "numero_de_unidades",
  "unidade": "unidades"
}
```

Esses valores nao precisam ser encontrados em tabelas, blocos ou outros
artefatos. Ainda assim, candidatos da DAG 3 podem inclui-los no
`mapeamento_canonico` com `tipo_origem: valor_fixo`. Isso e redundante e permite
que a LLM proponha um valor divergente do contrato.

O ajuste inicial da versao `1.7.0` corrigiu a base: a DAG 2 preserva literais do
contrato ao montar o `schema_saida`, enquanto descritores como `string`,
`number` e `string | null` continuam como `null` ate serem resolvidos.

Ainda falta impedir que o candidato os trate como alvos de mapeamento e
sobrescreva esses valores.

## Decisao de Modelagem

No `schema_saida`:

- descritores de tipo indicam um campo que pode precisar de resolucao, como
  `string`, `number` e `string | null`;
- qualquer literal e um valor fixo do contrato, como `unidades`, `venda`,
  `valor_bruto` ou uma classificacao de fonte;
- listas continuam descrevendo colecoes repetiveis.

Um literal nao e um dado extraido. Ele deve estar presente no resultado mesmo
quando nao houver layout signature, candidato ou artefato de origem para ele.

Titulos foram removidos do contrato de construtoras porque eram redundantes com
a propria estrutura (`lancamentos` e `vendas`). Caso outra familia precise
preservar um titulo efetivamente publicado, ele deve ser modelado como campo
dinamico e ter origem declarada no layout.

## Novo Fluxo Desejado

```text
contrato semantico
  ├─ literais estaveis ────────────────> DAG 2 preenche deterministicamente
  └─ campos dinamicos/requisitos ─────> DAG 3 pede origem a LLM
                                             └─ layout candidato
                                                  └─ DAG 2 resolve artefatos
```

A LLM deve receber somente a projecao de campos dinamicos permitidos. Ela nao
deve ver nem devolver paths de valores fixos.

## Implementacao Concluida

### 1. Classificar os paths do schema na construcao do contexto

Arquivo: `airflow/plugins/services/fallback/context_builder.py`.

Foi criada uma classificacao generica a partir do `schema_saida`:

- `paths_dinamicos_permitidos`: folhas descritas por tipo;
- `paths_fixos_do_contrato`: folhas cujo valor e literal;
- arrays que exigem seletor, como ja ocorre hoje.

`estrutura_schema_saida.paths_permitidos`, entregue a LLM, contem somente
os paths dinamicos. Os paths fixos podem existir em uma secao interna do
contexto operacional, mas nunca no payload enviado ao modelo.

Essa classificacao deve reutilizar a mesma regra de descritores usada pela DAG
2, para nao haver interpretacoes diferentes entre os dois componentes.

### 2. Restringir alvos e exemplos da segunda chamada

Arquivos: `context_builder.py` e `prompts.py`.

- `alvos_mapeaveis` e construido apenas de
  `requisitos_mapeamento.campos_obrigatorios` e de paths dinamicos relevantes;
- exemplos de `valor_fixo` podem continuar existindo para campos dinamicos que
  realmente sejam constantes do documento, mas devem declarar explicitamente
  que nao servem para literais ja definidos no contrato;
- o prompt deve dizer que a ausencia de um path fixo no candidato e esperada.

O contrato continua sendo a fonte da verdade; a LLM nao pode redefinir sua
semantica.

### 3. Bloquear sobrescrita de literais pela DAG 2

Arquivo: `airflow/plugins/services/schema_resolution_service.py`.

Antes de executar cada entrada de `mapeamento_canonico`, a DAG 2 deve verificar
se o path final corresponde a um literal do `schema_saida`.

Para esse caso:

- nao ler artefato;
- nao executar `valor_fixo` fornecido pelo layout;
- manter o valor originado no contrato;
- registrar na auditoria que o mapeamento foi ignorado por ser um valor fixo do
  contrato.

O ideal e que um layout novo nunca chegue a esse ponto; a protecao existe para
layouts antigos e para defesa em profundidade.

### 4. Rejeitar candidatos incorretos na DAG 3

Arquivo: `airflow/plugins/services/fallback/candidate_validation.py`.

Foi adicionada validacao que rejeita qualquer entrada em `mapeamento_canonico` cujo
path pertença a `paths_fixos_do_contrato`. A mensagem deve identificar o path e
orientar que o valor ja e preenchido pelo contrato.

Essa validacao deve ocorrer antes da persistencia do candidato e antes da
revalidacao pela DAG 2.

### 5. Ajustar o esquema Pydantic apenas se necessario

Arquivo: `airflow/plugins/services/fallback/models.py`.

Nao foi necessario remover `valor_fixo` dos tipos de origem aceitos: ele continua
valido para um campo dinamico quando a assinatura precisa representar uma
constante documental. A restricao e por path fixado pelo contrato, nao pelo
tipo de origem em si.

## Compatibilidade e Migracao

- O contrato de construtoras esta publicado como `v1.7.0`.
- Layouts existentes que tenham mapeamentos redundantes devem continuar sendo
  resolvidos: a DAG 2 preserva o contrato e registra que ignorou o mapeamento.
- Novos candidatos nao poderao conter esses paths.
- Nao ha necessidade de reescrever layouts publicados apenas para remover as
  entradas redundantes; eles podem ser renovados quando houver uma alteracao
  real de layout.

## Testes de Aceite

1. Um contrato com `"unidade": "unidades"` produz `unidade: "unidades"` sem
   qualquer layout.
2. Um campo `"valor": "number | null"` continua `null` antes da resolucao.
3. O payload da LLM nao contem paths fixos do contrato.
4. Um candidato que inclua `unidade` ou `tipo_operacao` como mapeamento e
   rejeitado pela DAG 3 com mensagem clara.
5. Um layout legado com tal mapeamento nao sobrescreve o literal na DAG 2 e
   deixa evidencia na auditoria.
6. Uma execucao das cinco construtoras continua produzindo os valores e
   periodos hoje aprovados, com os metadados fixos identicos entre empresas.

## Fora de Escopo

- Calculos de variacao e outros indicadores derivados;
- criar titulos artificiais para secoes;
- transformar literais do contrato em dados extraidos;
- tornar regras exclusivas de construtoras globais para outros PDFs.
