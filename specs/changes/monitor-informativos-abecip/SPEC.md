# Especificação — Monitor dos informativos mensais da ABECIP

## Comportamento esperado

`dag_detecta_e_baixa_pdfs_abecip` roda todos os dias entre os dias 20 e 7 de cada mês.
Em cada execução lê a página de informativos, baixa os PDFs listados, grava no MinIO os
que ainda não existem e dispara `dag_extrai_documentos_origem` somente para os que ainda
não foram extraídos. Sem novidades, termina sem disparar nada.

```text
dag_detecta_e_baixa_pdfs_abecip
  detectar_informativos → baixar_e_persistir_informativos
    → preparar_disparo_extracao → disparar_extracao_documentos_origem
                                    → dag_extrai_documentos_origem → dag_resolve_schema_saida → …
```

## Requisitos funcionais

- **RF1 — Detecção.** Cada informativo com link de PDF vira um candidato de origem com
  `domain=abecip`, `entity_slug=abecip`, `period_label=AAAA-MM`, `reference_year`,
  `reference_quarter=0`, `published_at`, `url` e `should_trigger_dag2=true`. O período vem
  da descrição ("Em <mês> de <ano>") e, na falta dela, do nome do arquivo; sufixos de
  republicação (`032`, `051`, `-novo`) não mudam o mês. Havendo conflito, a descrição vence
  e o conflito fica em `metadata.conflito_periodo_arquivo`.
- **RF2 — Falha visível.** Se nenhum informativo for reconhecido, a detecção falha. Item
  sem link de PDF ou sem período reconhecível é ignorado com aviso.
- **RF3 — Identidade por checksum.** O `document_id` vem do SHA-256 do conteúdo. Resposta
  que não começa por `%PDF` falha a execução e não grava nada.
- **RF4 — Persistência.** PDF novo vai para
  `documentos-origem/abecip/abecip/ano=<A>/periodo=<A-MM>/document_id=<id>/<sha16>_<arquivo>.pdf`,
  com `documento_detectado.json` ao lado. O manifesto traz o contrato semântico mais novo
  do domínio (`contratos/abecip/`), `should_trigger_dag2=true` e o candidato completo. Se um
  PDF do monitor estiver sem manifesto (execução interrompida), o manifesto é refeito.
- **RF5 — Idempotência.** O PDF é procurado por checksum em todo
  `documentos-origem/abecip/abecip/`, em qualquer layout (`document_id=<id>/` no caminho ou
  nome iniciado por `<sha16>_`). Achado, não é regravado. Status: `novo`, `duplicado`
  (já do monitor) ou `duplicado_externo` (outro layout).
- **RF6 — O que segue para extração.** `novo` e `duplicado` sem manifesto de extração no
  período. `duplicado_externo` nunca segue. `FORCE_EXTRACT` é ignorado.
- **RF7 — Disparo.** Uma execução de `dag_extrai_documentos_origem` com
  `origin_manifest_keys` e `trigger_origin_dag=dag_detecta_e_baixa_pdfs_abecip`. A cadeia
  até a DAG 2 e a DAG 3 é a existente, sem alteração.
- **RF8 — Agenda.** Cron `0 18 1-7,20-31 * *` (UTC, 15h em Brasília), `catchup=false`,
  `max_active_runs=1`, 2 novas tentativas com 10 minutos de intervalo.

## Requisitos não funcionais

- **RNF1 — Sem estado fora do MinIO.** Nenhum arquivo de controle, variável do Airflow
  ou tabela nova: "já visto" é "já existe no MinIO".
- **RNF2 — Núcleo agnóstico.** Nada de ABECIP em `domain/` nem em `application/`. O que é
  específico da ABECIP fica em `infrastructure/abecip/`, na DAG e na fábrica de dependências.
- **RNF3 — Fluxo existente intocado.** `download_and_persist_pdfs`, a DAG de RI e a DAG de
  extração não mudam.
- **RNF4 — Custo.** Cada execução baixa os PDFs da primeira página (8 hoje, ~1,2 MB cada)
  e lê só metadados do MinIO.

## Critérios de aceite

Ver [ACCEPTANCE.md](ACCEPTANCE.md).
