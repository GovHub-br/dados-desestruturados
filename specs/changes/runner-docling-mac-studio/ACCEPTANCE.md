# Aceite — Runner Docling sempre ativo no Mac Studio

Preencha cada linha com data, evidência (comando + saída relevante) e
resultado. Um item só passa com evidência. "VM" indica que o comando roda em
`10.0.0.86`; os demais rodam no Mac Studio.

## Evidências de validação

| # | Verificação | Como verificar | Req. | Evidência | Resultado |
| --- | --- | --- | --- | --- | --- |
| A0 | Pré-condição: stack da VM no ar | `docker compose … up -d` sem conflito de portas; 14 containers ok; `curl 127.0.0.1/healthz` → `{"status":"ok"}` | — | 2026-10-02, religada manualmente na sessão de inspeção | ✅ |
| A1 | Porta respondendo | VM: `curl -fsS 10.0.0.10:8081/healthz` → `{"status": "ok", "service": "docling-runner", …}` | RF1 | | |
| A2 | Extração pela VM | VM: `curl -X POST 10.0.0.10:8081/extract-file -H "Content-Type: application/pdf" -H "X-Execution-Id: teste-servico" -H "X-Input-Filename: dados.pdf" --data-binary @pdfs_testes/dados.pdf -o /tmp/x.tar.gz` → `tar -tzf /tmp/x.tar.gz` lista `extraction/metadata.json`. Se vier JSON com `ModuleNotFoundError`, é o `PATH`; com `--llm-api-url`, é o `runner.env` | RF5, RF6 | | |
| A3 | DAG real | `dag_extrai_documentos_origem` conclui e sobe os artefatos ao MinIO, sem mudança na VM | — | | |
| A4 | Independente de sessão | Fechar todas as sessões SSH do Mac; repetir A1 pela VM | RF2 | | |
| A5 | Volta se morrer | `kill -9 $(pgrep -f docling_runtime.server)` → A1 volta em ≤ 30 s | RF1 | | |
| A6 | Volta após reboot sem login | `sudo reboot`; sem login nem SSH: A1 + A2 pela VM em ≤ 5 min. Duração de A2 na mesma ordem de antes, o que confirma a GPU | RF1 | | |
| A7 | Atualização sem novidade | `atualizar-runner.sh` → "nada novo"; o runner não reinicia | RF7 | | |
| A8 | Atualização com commit novo | Commit novo no `main` → o script troca, reinicia e mostra `ANTES → DEPOIS`; A1 ok | RF7 | | |
| A9 | Atualização com falha volta sozinha | `atualizar-runner.sh <branch de teste com erro de import>` → termina com erro; `git rev-parse HEAD` igual ao anterior; A1 ok. Depois, `atualizar-runner.sh main` | RF7 | | |
| A10 | Não interrompe extração | Rodar a atualização durante uma extração: o script espera o fim | RF7 | | |
| A11 | Configuração correta | `runner.env` em modo 600, com `HF_HOME` e `PIPELINE_TMP_DIR` em `~/ocr-data`; não existe `~/docling-runner/repo/.env` | RF5 | | |

## Resultado

_A preencher ao final da Etapa 4._
