# Aceite — Monitor dos informativos mensais da ABECIP

Preencha cada linha com data, evidência (comando + saída relevante) e resultado. Um item
só passa com evidência. Os itens A7 a A10 exigem a execução real da DAG, que depende de
despausá-la (decisão do dono do pipeline).

## Evidências de validação

| # | Verificação | Como verificar | Req. | Evidência | Resultado |
| --- | --- | --- | --- | --- | --- |
| A1 | Testes e lint | `pytest tests/unit` e `ruff check src tests/unit scripts/validate_repository_structure.py airflow/dags/abecip airflow/dags/_shared`; `python scripts/validate_repository_structure.py` | RF1–RF7 | 2026-10-21: 325 passed (302 antes + 23 novos), 1 skip preexistente (pandas), ruff limpo, validador ok | ✅ |
| A2 | Cada regra tem um teste que a pega | Quebrar a regra numa cópia e ver o teste falhar | RF5, RF6 | 2026-10-21, 2 mutantes detectados: `FORCE_EXTRACT` passando a valer (`test_force_extract_do_ambiente_nao_reextrai…`) e reconhecimento do layout de nome prefixado removido (`…carga_manual…[layout_prefixado]`) | ✅ |
| A3 | Parser na página real | `parse_page` sobre o HTML de 2026-10-21 | RF1 | 8 de 8 informativos, períodos 2026-01 a 2026-08 na ordem da página, `…-032` e `…-051` mapeados para 2026-03 e 2026-05, "março" acentuado ok, nenhum conflito descrição × arquivo | ✅ |
| A4 | `HttpClient` do projeto é aceito pelo site | `fetch` da listagem e de um PDF com o User-Agent padrão | RF3 | 2026-10-21: listagem 51 927 bytes `text/html`; PDF 1 174 792 bytes `application/pdf`, redirecionado para `/admin/assets/uploads/anexos/…`, começa por `%PDF-` | ✅ |
| A5 | DAG carrega no Airflow | `airflow dags details dag_detecta_e_baixa_pdfs_abecip`; log do dag-processor | RF8 | 2026-10-21: 1 DAG, 0 erros no parse; "At 18:00, on day 1 through 7 and 20 through 31 of the month"; `max_active_runs=1`; pausada | ✅ |
| A6 | Simulação contra o MinIO real, sem escrita | `docker exec -w /opt/project/dados-desestruturados ocr_airflow_scheduler python scripts/simular_monitor_abecip.py` | RF4–RF6 | 2026-10-21: 8 candidatos; **novo**: 2026-08 (esperado) e 2026-06; **duplicado_externo**: 2026-01 a 2026-05 e 2026-07, todos com extração. Zero escritas. Junho: o MinIO tem uma captura do Safari (25/08), o site tem o PDF original do Publisher (27/07); texto idêntico (`pdftotext`, zero diferenças) | ✅ |
| A7 | Primeira execução real | Despausar (ou `airflow dags trigger`) e conferir o MinIO | RF4, RF7 | | |
| A8 | Cadeia até a resolução | Uma execução de `dag_extrai_documentos_origem` por manifesto novo, seguida de `dag_resolve_schema_saida` com `execucoes/abecip/extracao/abecip/ano=2026/periodo=2026-08/…/manifesto_execucao.json` | RF7 | | |
| A9 | Segunda execução é um no-op | Disparar de novo logo depois: nenhum objeto novo, `disparar_extracao_documentos_origem` pulada | RF5, RF6 | | |
| A10 | Recuperação | Parar o runner, rodar (extração falha), religar, rodar de novo: o mês volta para a fila e é extraído | RF6 | | |

## Resultado

Implementação e testes aprovados (A1 a A6). Faltam as evidências da execução real
(A7 a A10), que dependem de despausar a DAG.
