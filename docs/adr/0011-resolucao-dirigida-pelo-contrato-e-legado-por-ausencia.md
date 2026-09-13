# ADR 0011 — A resolução é dirigida pelo contrato; o legado vale por ausência de declaração

- Status: Aceito
- Data: 2026-09-13
- Fonte de verdade: `specs/platform/CONTEXT.md`, ADR 0005

## Responsáveis

Mateus de Castro

## Contexto

A ADR 0005 estabelece que o núcleo não codifica condições específicas de domínio.
Um inventário da DAG 2 em 2026-09-13 encontrou cinco pontos herdados do primeiro
domínio (construtoras) que violavam isso:

1. a célula de tabela era sempre projetada como `{periodo, escopo_periodo, valor}`
   e `valores[...]` recebia a observação inteira;
2. o contexto semântico procurava `tipo_operacao`, `indicador` e `unidade` em
   campos irmãos, partindo o path em `.dados[` e `.valores[`;
3. `periodos_disponiveis` era derivado por uma regex de `[empresa=…].valores[papel_periodo=…]`;
4. nenhuma declaração dizia qual chave identifica o item de cada array — a LLM
   emitiu `valores[indicador=…]` e passou;
5. `"construtoras"` era o default de domínio em três lugares.

O efeito para o domínio de bancos era concreto: campos de raiz todos `null`, um
gabarito que o construtor de saída nunca conseguiria materializar, e um validador
que aceitava seletores com a chave do array errado.

## Drivers da decisão

- Criar uma layout signature do zero para qualquer domínio, sem tocar no núcleo;
- não quebrar construtoras, que já está validado em produção;
- não introduzir `if dominio == "..."` no núcleo, que é a violação que se quer remover;
- dar a construtoras um caminho de migração, e não um privilégio permanente.

## Alternativas consideradas

### Gate pelo contrato (escolhida)

O modo genérico entra quando o contrato declara dois blocos opcionais em
`contrato_semantico`: `chaves_de_item` (qual chave identifica o item de cada
array) e `derivacoes` (campos preenchidos a partir do contrato, do manifesto ou
das observações resolvidas). Sem declaração, o caminho legado executa intacto.

**Vantagens**: nenhum nome de domínio no núcleo; construtoras v1.8.0 não muda um
byte; quando construtoras publicar um contrato que declare os blocos, o legado
vira código morto e pode ser apagado.
**Desvantagens**: exige publicar bancos v2.1.0 com as declarações; um domínio
novo que esqueça os blocos recebe o comportamento legado em silêncio — por isso
o registro de releases mede a diferença.

### Gate pelo nome do domínio

`if dominio == "construtoras"` escolhe o legado. Mais rápido, mas fixa um domínio
no núcleo e não oferece migração. Rejeitada.

### Reescrever construtoras agora

Migrar o contrato e os layouts curados para o modo genérico junto. Rejeitada por
escopo: construtoras já resolve bem e a prova de não-regressão precisa de uma
base estável para comparar.

## Decisão

- `domain/contracts/capabilities.py` lê e valida `chaves_de_item` e `derivacoes`
  contra o próprio `schema_saida`; `uses_generic_resolution(contract)` é o único
  gate, e é `bool(chaves_de_item)`.
- No modo genérico, `celula_de_tabela` devolve apenas o valor do campo terminal,
  tipado pelo descritor do contrato (`number` → número normalizado; senão texto);
  cabeçalho e constantes da observação são mapeados por `cabecalho_de_tabela` e
  `valor_fixo`. Um path que termina no array é recusado.
- No modo genérico, o contexto semântico são os seletores do próprio path; só os
  sinônimos do indicador selecionado passam a valer para casar o rótulo da linha.
- `derivacoes` preenche somente campos ainda nulos; três origens: `contrato`,
  `manifesto` e `observacao` (esta última é a forma declarada da regra de
  construtoras).
- O validador da DAG 3 exige que cada filtro `[k=v]` use a chave declarada para o
  seu array e recusa observação inteira quando há `chaves_de_item`.
- Defaults `"construtoras"` passam a `PIPELINE_DOMINIO`, com aviso quando o
  manifesto não declara domínio.

## Consequências

- Bancos resolve o `schema_saida` completo (raiz, `dados[].instituicao`, observações)
  a partir de um layout gerado do zero.
- Construtoras: sete entidades com layout vigente resolvem byte a byte igual ao
  código anterior (comparação em 2026-09-13).
- Um `&` literal em valor de seletor (`Plano&Plano`) é aceito; só `&` que introduz
  outra `chave=` é recusado — a regra vive no validador, não no parser.

## Riscos

- Um contrato novo sem os blocos cai no legado sem erro. Mitigação: o registro de
  releases e a auditoria `derivacoes` no artefato de resolução tornam isso visível.
- `derivacoes` de origem `manifesto` dependem de campos do manifesto de extração
  (`candidate.entity_name`, `candidate.period_label`).

## Critérios para reconsideração

Quando construtoras migrar para um contrato com os blocos, remover o caminho legado
(`_derive_construtoras_global_periods`, a projeção de observação inteira e o
contexto por campos irmãos) e esta ADR passa a descrever o único caminho.

## Referências

- ADR 0005; `docs/architecture/resolucao-deterministica-schema-saida-dag2.md`;
- `docs/guides/registro-de-releases.md` (rótulo `exp-contrato-dirige-resolucao`).
