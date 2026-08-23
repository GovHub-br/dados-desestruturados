# ADR 0005 — O contrato declara requisitos de mapeamento e literais

- Status: Aceito
- Data: 2026-08-03
- Fonte de verdade: `specs/platform/CONTEXT.md`

## Responsáveis

Mateus de Castro

## Contexto

Campos fixos e requisitos implícitos obrigavam a LLM e a resolução a inferir
informações que já pertencem à semântica do domínio.

## Drivers da decisão

- Menor ambiguidade para LLM e resolução;
- generalidade entre domínios;
- validação explícita de completude;
- redução de custo e contexto.

## Alternativas consideradas

### Declarar requisitos e literais no contrato

**Vantagens**

- O contrato contém a semântica necessária para validar e materializar;
- evita solicitar à LLM valores que já são conhecidos;
- não exige condições específicas por domínio no código.

**Desvantagens**

- Autores de contrato precisam modelar requisitos com precisão.

### Inferir todos os campos de artefatos ou LLM

**Vantagens**

- Contrato inicial aparentemente menor.

**Desvantagens**

- Aumenta ambiguidade, custo e inconsistência.

### Codificar literais por domínio na DAG

**Vantagens**

- Correção rápida em um caso conhecido.

**Desvantagens**

- Quebra a generalidade do núcleo.

## Decisão

O contrato declara `campos_obrigatorios`, observações e contextos obrigatórios.
Folhas literais do `schema_saida` são materializadas deterministicamente e não
devem ser buscadas nos artefatos ou mapeadas pela LLM.

## Consequências

- Menos contexto e menos trabalho para a LLM.
- Requisitos verificáveis sem codificar nomes específicos de domínios.
- Layout signatures representam somente campos observáveis e dinâmicos.

## Riscos

- Contratos vagos transferem decisão excessiva à LLM;
- requisitos incorretos podem reprovar uma extração válida.

## Implementação

- `campos_obrigatorios` declara paths, seletores e contexto exigido;
- folhas literais de `schema_saida` são materializadas deterministicamente;
- a LLM recebe somente campos observáveis relevantes ao mapeamento.

## Critérios para reconsideração

Revisitar se o contrato não conseguir representar um domínio sem extensões
especiais, ou se literais passarem a depender de evidência do documento.

## Referências

- `specs/platform/SPEC.md`;
- ADR 0004.
