# Plano de Implementacao — MVP de Producao

## Criterio de pronto

Uma pessoa autorizada envia PDF, escolhe contrato publicado, acompanha a
execucao e consulta `schema_saida_resolvido.json`, validacao e auditoria.

## Fundacao de infraestrutura

- [ ] Provisionar MinIO, Airflow, Postgres operacional, OpenMetadata e Langfuse.
- [ ] Configurar segredos, rede, backup e politicas de acesso.
- [ ] Criar autenticacao e perfis: administrador, autor de contrato, operador e leitor.

## Bootstrap

- [ ] Publicar contrato e layouts homologados das construtoras.
- [ ] Registrar ativos, donos e linhagem no OpenMetadata.
- [ ] Carregar PDFs de demonstracao para testes.

## Entrada manual generica

- [x] API de upload manual de PDF.
- [x] Validacao de PDF, tamanho, checksum e identificadores de dominio/entidade.
- [x] Persistencia em `documentos-origem/<dominio>/<entidade>/document_id=<hash>/`.
- [x] Manifesto com URI do contrato e disparo de extracao independente de RI.
- [x] Publicacao imutavel de contrato pelo portal com validacao estrutural minima.
- [ ] Bloqueio de reprocessamento acidental com acao explicita de reprocessar.

## Portal minimo

- [x] Tela de upload e selecao de contrato publicado.
- [x] APIs para listar contratos, execucoes e artefatos de extracao.
- [ ] Tela de execucoes com estados Airflow e status final resumido.
- [ ] Tela de detalhe com validacao, auditoria e schema resolvido.
- [ ] Links temporarios e seguros para objetos MinIO.

## Governanca e observabilidade

- [ ] Integrar catalogo/linhagem ao OpenMetadata.
- [ ] Integrar DAG 3 ao Langfuse.
- [ ] Registrar prompt e resposta sanitizados, modelo, tokens, latencia, retries e finish reason.
- [ ] Vincular traces a `document_id`, `execution_id` e `fallback_execution_id`.

## Qualidade antes de abrir testes livres

- [ ] Testar upload de construtoras e de segunda familia documental.
- [ ] Testar fallback, retry, revalidacao e bloqueio de publicacao invalida.
- [ ] Testar autorizacao e isolamento por dominio.
- [ ] Definir limites de custo, timeout e concorrencia para Docling e LLM.
- [ ] Criar alertas para falha, fallback recorrente, erro de contrato e custo anormal.

## Decisoes mantidas

1. MinIO e a fonte operacional de arquivos e artefatos.
2. Git e o canal inicial de autoria e revisao de contratos.
3. OpenMetadata governa; Langfuse observa LLM.
4. Coleta automatica e upload manual sao entradas distintas da mesma DAG de extracao.
5. Layout candidato nao vira ativo sem revalidacao deterministica da DAG 2.
