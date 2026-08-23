# ADR 0007 — Portal como fronteira autenticada

- Status: Aceito
- Data: 2026-08-16
- Fonte de verdade: `docs/architecture/portal-experimentacao-documentos.md`

## Responsáveis

Mateus de Castro

## Contexto

Usuários precisam enviar PDFs e publicar contratos sem depender de acesso direto
a MinIO, Airflow ou detalhes internos da infraestrutura.

## Drivers da decisão

- Segurança de credenciais;
- experiência para usuários não técnicos;
- validação centralizada;
- rastreabilidade operacional.

## Alternativas consideradas

### Portal com backend autenticado

**Vantagens**

- Credenciais permanecem no servidor;
- validação e autorização são centralizadas;
- interface não depende de detalhes internos.

**Desvantagens**

- Introduz serviço e contrato de API adicionais.

### Navegador acessar MinIO e Airflow diretamente

**Vantagens**

- Menos backend no início.

**Desvantagens**

- Expõe credenciais e contratos internos;
- dificulta política única de autorização.

### Upload manual por operadores

**Vantagens**

- Menor superfície de produto.

**Desvantagens**

- Não atende experimentação por usuários nem rastreabilidade guiada.

## Decisão

O portal valida domínio, versão, entidade e arquivos; o backend autenticado
persiste os artefatos e dispara os fluxos permitidos. O navegador não recebe
credenciais de MinIO nem de Airflow.

## Consequências

- A interface é uma superfície de produto, não um atalho administrativo.
- Autorização e validação ficam centralizadas no backend.
- A rastreabilidade apresentada ao usuário usa identificadores operacionais.

## Riscos

- Estados exibidos podem divergir do Airflow se a consulta for desatualizada;
- autorização insuficiente pode permitir publicar contratos indevidos.

## Implementação

- Backend valida domínio, versão, entidade e arquivo;
- backend persiste artefatos e dispara somente fluxos autorizados;
- navegador recebe IDs operacionais, nunca credenciais de MinIO/Airflow;
- status deve ser derivado de fonte operacional identificável.

## Critérios para reconsideração

Revisitar se houver SSO/RBAC corporativo obrigatório, múltiplos tenants ou
necessidade de execução assíncrona desacoplada da API atual.

## Referências

- `docs/architecture/portal-experimentacao-documentos.md`;
- ADR 0003 e ADR 0006.
