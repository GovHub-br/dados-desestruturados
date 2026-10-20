# Plano de implementação — Título por tabela e fim da fusão de tabelas

## Etapas

1. **Diagnóstico e protótipo** (feito em 2026-10-19). Replay do código real sobre as
   extrações gravadas, sem reprocessar PDFs. Resultados em
   [eval/docling_tabelas/](../../../eval/docling_tabelas/README.md).
2. **Código e testes** (feito). `common.py` e `tables.py`; testes em
   `tests/unit/docling_pipeline/test_docling_tabelas_titulo_e_fusao.py`.
3. **Persistir as ferramentas** (feito). Scripts, linhas de base e variantes em
   `eval/docling_tabelas/`, para repetir a comparação depois.
4. **Trocar o runner do Mac Studio para esta branch.** Push da branch e, no Mac,
   `~/docling-runner/repo/infra/docling-runner/macos/atualizar-runner.sh fix/docling-titulo-tabela-e-fusao`.
   Não fazer `git checkout` à mão e não mexer no clone `~/Desktop/…`. Enquanto o
   runner estiver na branch de teste, **não dar push nela**: cada push chega ao
   runner em até 15 min.
5. **Reextrair os mesmos PDFs pela DAG de extração** (envio por `POST /extract-file`),
   com o runner nesta branch. Em seguida, repetir os mesmos PDFs com o runner no
   `main` (`atualizar-runner.sh main`), como **controle** nas mesmas condições
   (mesmo Mac, mesmas bibliotecas, mesmo limite de tokens dos gráficos do PR #17).
   Cada reprocessamento cria um `execution_id` novo; nada é sobrescrito no MinIO.
6. **Comparar** a extração nova com (a) o controle em `main` e (b) as extrações
   antigas do MinIO. Registrar o resultado em `eval/docling_tabelas/`.
7. **Decidir** pelo critério do [ACCEPTANCE.md](ACCEPTANCE.md). Se a nova versão
   ganhar, merge no `main` e `atualizar-runner.sh main` (ou deixar a atualização
   automática trazer). Se não, voltar o runner para o `main` e arquivar a branch.

## Estratégia de teste

- Unidade: 9 testes novos, cada correção coberta por pelo menos um teste. Foi feito
  teste de mutação: reintroduzir cada defeito faz falhar o teste correspondente.
- Replay offline: ABECIP (7 meses fundidos → 3 tabelas cada), Gerdau e Vale (cabeçalho
  verdadeiro mantido nas 5 tabelas), corpus (0 de 322 cabeçalhos trocados).
- Reextração real no Mac Studio (etapas 5 e 6): é a única que valida o que o replay
  não alcança, como propagação legítima de cabeçalho e o efeito sobre `charts/`,
  `cases/` e `text_candidates/`.

## Compatibilidade e rollback

- Rollback do runner: `atualizar-runner.sh main`. O script volta sozinho ao commit
  anterior se a validação ou o `/healthz` falharem.
- Rollback do código: `git revert` do commit; não há migração de dados.
- O runner **não volta sozinho** ao `main`: a atualização automática acompanha a branch
  em uso. Ao terminar o teste, voltar explicitamente.
- O layout signature da ABECIP deve ser regenerado depois de adotar esta mudança. Até
  lá, uma extração nova da ABECIP não casa com o signature atual (`table005.json`).
