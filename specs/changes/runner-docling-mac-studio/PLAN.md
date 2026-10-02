# Plano de implementação — Runner Docling sempre ativo no Mac Studio

Escopo mínimo. Leia antes [CONTEXT.md](CONTEXT.md) (problema e armadilhas),
[SPEC.md](SPEC.md) (requisitos) e [DECISIONS.md](DECISIONS.md).

## Visão geral

| Etapa | Onde | Entrega | Esforço |
| --- | --- | --- | --- |
| 1 | Repositório (2 PRs: serviço e atualização automática) | 5 arquivos em `infra/docling-runner/macos/` + runbook | P |
| 2 | Mac Studio | Runner instalado como serviço do sistema (launchd) | P |
| 3 | Mac + VM | Validação (reboot sem login, kill, SSH, atualização, DAG real) | P |
| 4 | Mac | Remoção do clone legado do Desktop (opcional, após o aceite) | P |

A VM não é alterada (D8).

Resultado no Mac Studio:

```text
/Users/lablivre/docling-runner/
  repo/                  clone completo e dedicado (branch main)
  venv/                  Python 3.14 + mesmas versões do venv atual + patches de GPU
  runner.env             configuração do serviço (chmod 600)
  pip-freeze-base.txt    versões do venv atual (linha de base)
/Users/lablivre/ocr-data/          sem mudança: pipeline-tmp/, huggingface-cache/
/Users/lablivre/ocr-data/logs/     logs do serviço (novo)
/Library/LaunchDaemons/com.ocr-cidades.docling-runner.plist
```

## Etapa 1 — Repositório (dois PRs pequenos)

### 1.1 `infra/docling-runner/macos/com.ocr-cidades.docling-runner.plist`

| Chave | Valor | Por quê |
| --- | --- | --- |
| `Label` | `com.ocr-cidades.docling-runner` | nome usado no `launchctl` |
| `UserName` | `lablivre` | não rodar como root (D1) |
| `ProgramArguments` | `/bin/bash`, `/Users/lablivre/docling-runner/repo/infra/docling-runner/macos/run-runner.sh` | launcher versionado |
| `EnvironmentVariables` | `RUNNER_HOME=/Users/lablivre/docling-runner`, `HOME=/Users/lablivre` | o launchd não expande `~` nem `$HOME` |
| `RunAtLoad` / `KeepAlive` | `true` / `true` | sobe no boot e religa se morrer |
| `ThrottleInterval` | `10` | evita laço apertado se a subida falhar |
| `ProcessType` | `Interactive` | sem throttling de CPU e I/O (RNF3) |
| `StandardOutPath` / `StandardErrorPath` | `/Users/lablivre/ocr-data/logs/docling-runner.{out,err}.log` | substitui o que aparecia no terminal |

### 1.2 `infra/docling-runner/macos/run-runner.sh` e `runner.env.example`

O launcher é o que o launchd executa. Ele:

1. carrega `$RUNNER_HOME/runner.env`;
2. coloca `venv/bin` no início do `PATH`, para que o `python3` chamado pelo
   runner seja o do venv;
3. define `PYTHONPATH` e `PYTHONUNBUFFERED`;
4. entra no clone e faz `exec` do Python do venv. Assim o launchd acompanha o
   processo Python diretamente.

O `runner.env.example` documenta as variáveis do servidor e como acrescentar
as linhas `DOCLING_LLM_*` e `DOCLING_TEXT_CANDIDATE_*` do `.env` atual.

### 1.3 `atualizar-runner.sh` e `com.ocr-cidades.docling-runner-atualizacao.plist`

O plist executa o script a cada 15 min (D7). O script também pode ser rodado à
mão, e o próprio arquivo documenta os passos. Em resumo:

1. trava contra execuções simultâneas;
2. busca o branch em uso (ou o informado) e sai se não houver commit novo, ou
   se o commit novo já falhou antes;
3. espera não haver extração em andamento;
4. faz o checkout;
5. reinstala as dependências e os patches se o `requirements.txt` ou o script
   de patches mudaram;
6. valida com `python3 -m docling_pipeline --help` em ambiente limpo, que
   carrega a mesma cadeia de imports de um job;
7. reinicia via `pkill` e espera o `/healthz`;
8. em falha, volta ao commit anterior e registra em `atualizacoes.log`.

O corpo do script fica numa função `main` chamada na última linha. Ele vive no
clone que atualiza, e assim o bash já leu tudo antes de o git reescrever o
arquivo.

Uma extração que chegue entre a espera (3) e o reinício (7) é interrompida.
O Airflow repete a task (`retries=1`).

### 1.4 Runbook

Reescrever `docs/operations/docling-runner-launchd.md`, que hoje descreve um
LaunchAgent no Desktop, com:

- a instalação (Etapa 2);
- operação diária: status, logs, reiniciar e atualizar;
- diagnóstico: porta responde mas a extração falha, o que normalmente é
  `PATH` ou configuração;
- recriação do venv após troca de versão do Python;
- remoção do serviço.

Em `docs/operations/docling-remote-mac-studio.md`, trocar as instruções
manuais por um link para o runbook.

**Verificação do PR:**

```bash
plutil -lint infra/docling-runner/macos/com.ocr-cidades.docling-runner.plist
bash -n infra/docling-runner/macos/*.sh
shellcheck infra/docling-runner/macos/*.sh
```

O CI atual não é afetado: não há mudança em Python.

## Etapa 2 — Instalação no Mac Studio

Depois do merge, seguir a seção **Instalação** do runbook
[`docs/operations/docling-runner-launchd.md`](../../../docs/operations/docling-runner-launchd.md),
que é a fonte única dos comandos. Em resumo:

1. clone dedicado em `~/docling-runner/repo`, por HTTPS (D2);
2. venv recriado com o `pip freeze` do `.venv-chart` + patches de GPU +
   `pip check` (D3);
3. `runner.env` a partir do exemplo, com as linhas `DOCLING_LLM_*` e
   `DOCLING_TEXT_CANDIDATE_*` do `.env` atual (D4);
4. validação do pipeline em ambiente limpo (`env -i`);
5. os dois plists em `/Library/LaunchDaemons` (`root:wheel`, 644) + `launchctl bootstrap system`;
6. `/healthz` no Mac e a partir da VM.

**Rollback:** `sudo launchctl bootout system/com.ocr-cidades.docling-runner`
e voltar a usar o comando manual no clone do Desktop, que não foi tocado.

## Etapa 3 — Validação

Executar e registrar cada item do [ACCEPTANCE.md](ACCEPTANCE.md), nesta ordem:

1. `/healthz` e extração pela VM;
2. DAG real;
3. fechar o SSH;
4. `kill -9`;
5. reboot do Mac sem login;
6. atualização (sem novidade, com commit novo, com falha).

## Etapa 4 — Limpeza (opcional)

Depois do aceite e de alguns dias de operação, remover
`~/Desktop/ocr-cidades/dados-desestruturados` (1,7 GB, inclui `.venv-chart`).
Até lá, ele é o rollback. O clone `~/Desktop/ocr-cidades/docling` fica como
está.

## Estratégia de teste

- **Estático (no PR):** `plutil -lint`, `bash -n` e `shellcheck`.
- **Funcional:** os itens do ACCEPTANCE, executados nas máquinas reais.
  Launchd, GPU e reboot não são testáveis em CI.
- Sem testes unitários novos: nenhuma linha de Python muda.

## Compatibilidade e rollback

- **Contrato HTTP, VM, DAGs e Docker local:** sem mudança.
- **Mac:** desfazer o serviço é um comando (`bootout`). O fluxo manual antigo
  continua disponível até a Etapa 4.
