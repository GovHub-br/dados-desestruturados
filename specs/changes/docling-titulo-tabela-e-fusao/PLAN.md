# Plano de implementação — Título por tabela e fim da fusão de tabelas

## Etapas

1. **Diagnóstico e protótipo** (2026-10-19). Replay do código real sobre extrações gravadas, sem
   reprocessar PDFs. A evidência (protótipos, linhas de base, scripts) está na tag
   `arquivo/docling-titulo-evidencias`.
2. **Código e testes** (2026-10-19). `docling_pipeline/extractors/common.py` e `tables.py`; testes em
   `tests/unit/docling_pipeline/test_docling_tabelas_titulo_e_fusao.py`. Teste de mutação: reintroduzir
   cada defeito faz falhar o teste correspondente.
3. **Reextração no Mac Studio** (2026-10-20). 15 PDFs, um por empresa, com o runner na branch, comparados
   com as extrações antigas do MinIO. Segue o protocolo de [eval/docling/README.md](../../../eval/docling/README.md);
   resultado em [eval/docling/resultados/2026-10-titulo-tabela-fusao/](../../../eval/docling/resultados/2026-10-titulo-tabela-fusao/RESULTADO.md).
4. **Decisão.** Escopo ABECIP e construtoras, resolvido; pendências das demais empresas registradas. Ver D6 em
   [DECISIONS.md](DECISIONS.md) e [ACCEPTANCE.md](ACCEPTANCE.md).
5. **Merge no `main` e runner de volta ao `main`** (A12). Falta fazer.

## Compatibilidade e rollback

- Rollback do runner: `atualizar-runner.sh main`. O script volta sozinho ao commit anterior se a
  validação ou o `/healthz` falharem.
- Rollback do código: `git revert` do commit; não há migração de dados.
- O runner **não volta sozinho** ao `main`: a atualização automática acompanha a branch em uso.
  Depois do merge, rodar `atualizar-runner.sh main` explicitamente e conferir branch, hash e `/healthz`.
- O layout signature atual da ABECIP (`table005.json`, a tabela fundida) não casa com a extração nova.
  Isso **não é critério de aceite nem regressão**: o signature foi escrito sobre a extração pior. Mas,
  com o runner no código novo, uma extração nova da ABECIP sai com 3 tabelas na página das modalidades;
  o signature precisa ser reescrito antes de processar o próximo mês, tarefa própria.
