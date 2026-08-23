# Análise da `estrutura_schema_saida` nos payloads da DAG 3

## Objetivo

Avaliar quais partes de `estrutura_schema_saida` precisam ser enviadas para a
LLM em cada chamada da DAG 3, sem remover as informações que continuam
necessárias às validações determinísticas.

A distinção central é:

- **contexto interno de validação:** dados mantidos pela DAG para validar o
  candidato e a seleção;
- **projeção para a LLM:** somente as instruções necessárias para escolher
  artefatos ou escrever o `mapeamento_canonico`.

Não é necessário enviar à LLM tudo aquilo que o código consegue derivar,
preencher ou validar sozinho.

## Como a estrutura é montada hoje

`FallbackProblemContextBuilder._relevant_contract_context(...)` lê o
`schema_saida` do contrato semântico e o percorre recursivamente. O resultado
é incluído em `contrato_semantico_relevante.estrutura_schema_saida`:

```json
{
  "campos_raiz": ["..."],
  "paths_permitidos": ["..."],
  "arrays_que_exigem_seletor": ["..."]
}
```

As listas são uma projeção estrutural do contrato. Elas não indicam, por si só,
que todos os campos devem ser extraídos de um artefato nem que todos precisam
de mapeamento pela LLM.

| Elemento | Como é derivado | Uso atual no código |
| --- | --- | --- |
| `campos_raiz` | Chaves do primeiro nível de `schema_saida`. | `candidate_validation.py` confirma que um path de mapeamento começa em uma raiz válida. |
| `paths_permitidos` | Todos os nós e folhas do schema; para listas, percorre o primeiro item-modelo sem gerar índices numéricos. | Na seleção, rejeita `campo_saida` fora do contrato. No candidato, rejeita chaves de `mapeamento_canonico` fora do schema. |
| `arrays_que_exigem_seletor` | Caminhos cujo valor no template é uma lista. | `candidate_validation.py` exige filtro como `[empresa=...]` ou `[papel_periodo=...]` em cada array atravessado pelo path. |

Portanto, as três listas são importantes para a **DAG**, inclusive quando não
forem exibidas integralmente à LLM.

## Chamada 1 — seleção de artefatos

Nesta etapa a LLM não cria paths de resolução. Ela apenas escolhe arquivos do
inventário e declara quais valores brutos aqueles arquivos comprovam.

Hoje ela recebe o contrato relevante completo, inclusive a estrutura inteira.
No caso Plano&Plano, isso a expôs a paths como
`balancos_das_empresas.lancamentos.dados.empresa`; a LLM tentou provar esse
campo com um JSONL textual, apesar de `empresa` já ser conhecido pelo manifesto
e pelo esqueleto determinístico.

### Avaliação por elemento

| Elemento | Enviar na seleção? | Importância para a LLM nessa etapa | Recomendação |
| --- | --- | --- | --- |
| `campos_raiz` | Não. | Não ajuda a escolher tabelas, gráficos ou blocos. | Manter apenas no contexto interno de validação. |
| `paths_permitidos` completo | Não. | Inclui objetos, metadados e campos derivados; induz a LLM a tentar cobrir campos que não são valores extraíveis. | Não enviar a lista completa. Mantê-la internamente para validar `campo_saida`. |
| `arrays_que_exigem_seletor` | Não. | Seleção de artefatos não cria seletores nem `mapeamento_canonico`. | Manter apenas internamente. |

### Projeção recomendada para a seleção

Em vez de enviar a estrutura, a DAG deve derivar e enviar uma lista pequena de
campos que realmente exigem evidência. Hoje a regra determinística já faz isso:
na ausência de configuração específica, exige paths que terminam em
`.dados.valores.valor`.

Exemplo conceitual:

```json
{
  "campos_cobertura_minima": [
    "balancos_das_empresas.lancamentos.dados.valores.valor",
    "balancos_das_empresas.vendas.dados.valores.valor"
  ],
  "campos_deterministicos_nao_cobrir": [
    "empresa",
    "indicador",
    "tipo_operacao",
    "unidade",
    "periodos",
    "metadados"
  ]
}
```

Isso não altera a validação: `paths_permitidos` continua no servidor para
rejeitar um `campo_saida` inexistente. Apenas evita que a LLM veja opções que
não deve escolher.

### Observação sobre âncoras de JSONL

O resumo atual do inventário mostra, para `blocks`, `sections` e
`text_structures`, o path, a contagem e o schema, mas não amostras textuais.
Assim, a LLM não tem como garantir que uma âncora literal como
`"APRESENTAÇÃO"` existe no JSONL. Ela só consegue fazer essa comprovação bem
para tabelas, pois o inventário contém cabeçalhos e amostras de rótulos.

Enquanto não houver amostras, a seleção deve priorizar tabelas e declarar
cobertura somente para os valores mínimos. Artefatos textuais podem ser
selecionados por necessidade de contexto, mas não devem receber alegações de
âncoras literais que a LLM não consegue verificar.

## Chamada 2 — geração do `layout_signature_candidato`

Nesta etapa a LLM precisa construir o `mapeamento_canonico`. Aqui uma parte da
estrutura é útil, pois ela limita os paths e informa onde há arrays que exigem
seletores.

O payload atual também já possui `alvos_mapeaveis`, derivado deterministicamente
dos paths que terminam em `.dados.valores.valor`. Ele é mais próximo da tarefa
real da LLM que a lista estrutural completa.

### Avaliação por elemento

| Elemento | Enviar no candidato? | Importância para a LLM nessa etapa | Recomendação |
| --- | --- | --- | --- |
| `campos_raiz` | Em geral, não. | É necessário ao validador, mas a LLM já recebe um exemplo de cabeçalho e não deve mapear raízes isoladas. | Retirar da projeção LLM; manter no contexto interno. |
| `paths_permitidos` completo | Temporariamente, sim. | Hoje é a única lista completa que permite à LLM saber quais paths podem aparecer no mapeamento. Porém inclui caminhos intermediários e campos determinísticos. | Manter até existir uma lista específica de paths mapeáveis; depois substituir pela lista reduzida. |
| `arrays_que_exigem_seletor` | Sim. | É essencial para a LLM escrever paths com os seletores obrigatórios de arrays. | Manter, mas apenas para arrays atravessados pelos alvos mapeáveis. |
| `alvos_mapeaveis` | Sim, prioritário. | Diz quais valores brutos devem ser recuperados e quais papéis de período existem. | Manter e tornar a referência principal da instrução. |

## Projeção futura recomendada para a segunda chamada

Criar, de modo determinístico, uma estrutura específica para a LLM, distinta do
contexto de validação:

```json
{
  "alvos_mapeaveis": [
    {
      "grupo": "lancamentos",
      "valor_path": "balancos_das_empresas.lancamentos.dados.valores.valor",
      "papeis_periodo_disponiveis": [
        "periodo_referencia",
        "periodo_comparativo_anterior",
        "mesmo_periodo_ano_anterior"
      ],
      "arrays": [
        "balancos_das_empresas.lancamentos.dados.valores"
      ]
    }
  ],
  "paths_mapeaveis_adicionais": [
    "... apenas os paths não preenchidos pelo esqueleto determinístico ..."
  ],
  "arrays_com_seletor_obrigatorio": [
    "... apenas arrays usados pelos paths acima ..."
  ],
  "campos_preenchidos_pela_dag": [
    "empresa",
    "documento_origem",
    "contrato_semantico_ref",
    "regras_execucao",
    "metadados de execução"
  ]
}
```

Essa mudança só deve ser aplicada depois de classificar explicitamente, no
gerador de esqueleto, quais campos são preenchidos deterministicamente e quais
realmente precisam de uma regra de origem. Não é seguro simplesmente remover
`paths_permitidos` hoje: o validador aceita mapeamentos para qualquer path do
contrato, e alguns layouts podem usar paths auxiliares além de `valor`.

## Decisão recomendada

1. **Seleção de artefatos:** não enviar `estrutura_schema_saida`; enviar apenas
   `campos_cobertura_minima` e uma instrução inequívoca de não cobrir campos
   determinísticos.
2. **Geração do candidato:** manter `alvos_mapeaveis` e os arrays relevantes;
   preservar temporariamente `paths_permitidos` até existir
   `paths_mapeaveis_adicionais` derivado do esqueleto.
3. **Validações:** manter sempre as três listas completas no contexto interno.
   A limpeza do payload não deve enfraquecer as barreiras determinísticas.
4. **Prompts de retry:** repetir o contrato JSON completo e permitir remover
   uma cobertura estrutural inválida, em vez de obrigar a busca de outro
   artefato.

## Implementação da primeira chamada

Implementado no payload de seleção de artefatos:

- `estrutura_schema_saida` não é mais enviado à LLM;
- `contrato_semantico.metricas` não é mais enviado à LLM;
- a DAG envia `campos_cobertura_minima_layout`, derivado somente dos paths que
  terminam em `.dados.valores.valor`;
- a validação usa essa lista como whitelist: a LLM não pode alegar cobertura
  para `empresa`, períodos, metadados ou qualquer outro campo estrutural;
- o prompt de retry repete o objeto JSON obrigatório e instrui remover uma
  cobertura indevida, em vez de buscar outro artefato para prová-la.

O contrato completo e a estrutura completa continuam no contexto interno para
validação da DAG e para a segunda chamada de geração do candidato.

## Impacto esperado

- Menos contexto irrelevante e menos tentativas de mapear metadados.
- Seleção focada nos artefatos que realmente contêm valores brutos.
- Segunda chamada guiada por alvos concretos, sem perder a segurança de paths e
  seletores imposta pelo código.
- Validação determinística preservada integralmente fora do contexto da LLM.
