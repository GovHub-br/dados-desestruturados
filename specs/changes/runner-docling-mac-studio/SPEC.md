# Especificação da mudança — Runner Docling sempre ativo no Mac Studio

## Comportamento esperado

- O runner Docling roda no Mac Studio como **serviço do sistema**
  (LaunchDaemon). Ele sobe no boot sem login, volta sozinho se morrer e não
  depende de nenhuma sessão de terminal ou SSH.
- O comportamento das extrações é **idêntico ao de hoje**: mesmo código, mesmas
  versões de bibliotecas, mesmos patches e mesma configuração do pipeline.
- Atualizar o runner é um único script, que só troca o código quando não há
  extração em andamento e desfaz a troca se o runner não voltar saudável.

Nenhum código Python muda nesta entrega, e a VM de produção não é alterada.

## Requisitos funcionais

- **RF1 Sempre ativo.** LaunchDaemon `com.ocr-cidades.docling-runner`, sob o
  usuário `lablivre`, com `RunAtLoad` e `KeepAlive`. O runner responde em
  `:8081/healthz` em até 5 min após o boot, sem login, e em até 30 s após o
  processo morrer.
- **RF2 Independente de sessão.** Fechar qualquer sessão SSH ou terminal não
  afeta o runner.
- **RF3 Código fora do Desktop.** O serviço usa um clone completo e dedicado
  em `~/docling-runner/repo`, branch `main`, atualizado por `git pull`. O
  clone do Desktop não é usado pelo serviço.
- **RF4 Ambiente equivalente.** O venv em `~/docling-runner/venv` (fora do
  clone) é criado com o mesmo Python 3.14, as **mesmas versões** do venv atual
  (via `pip freeze`) e os patches de GPU aplicados.
- **RF5 Configuração explícita.** `~/docling-runner/runner.env` contém as
  variáveis do runner (`DOCLING_RUNNER_HOST/PORT`, `PIPELINE_TMP_DIR`,
  `HF_HOME`) e **somente** as linhas `DOCLING_LLM_*` e
  `DOCLING_TEXT_CANDIDATE_*` copiadas do `.env` atual, sem alterar valores.
  `PIPELINE_TMP_DIR` e `HF_HOME` continuam apontando para `~/ocr-data`.
- **RF6 Subprocesso correto.** O launcher coloca `~/docling-runner/venv/bin` no
  início do `PATH` e o clone no `PYTHONPATH`, de modo que o `python3` chamado
  pelo runner é o do venv.
- **RF7 Atualização segura.** `atualizar-runner.sh`:
  1. aborta se o clone tiver alterações locais;
  2. espera não haver `docling_pipeline` rodando;
  3. atualiza o clone para `origin/<branch>`, padrão `main` (equivale a
     `git pull` e permite testar outro branch);
  4. se o `requirements.txt` mudou, reinstala as dependências e reaplica os
     patches;
  5. valida que `docling_pipeline` importa no ambiente do serviço;
  6. reinicia o runner;
  7. espera o `/healthz`.

  Se a validação ou o `/healthz` falharem, volta ao commit anterior
  (reinstalando as dependências, se elas tinham mudado), reinicia e termina
  com erro.

## Requisitos não funcionais

- **RNF1 Simplicidade.** Quatro arquivos versionados no repositório (plist,
  launcher, script de atualização e exemplo de configuração) e um runbook. Nenhuma dependência nova.
  Os scripts rodam no `/bin/bash` 3.2 do macOS e passam no `shellcheck`.
- **RNF2 Sem regressão.** O contrato HTTP, o Docker local e a VM não mudam.
- **RNF3 Sem throttling.** `ProcessType=Interactive` no plist, porque o padrão
  do launchd aplica limites leves de CPU e I/O.
- **RNF4 Rollback trivial.** Remover o serviço e voltar ao comando manual pelo
  clone do Desktop, que é mantido até o aceite.

## Critérios de aceite

Detalhados em [ACCEPTANCE.md](ACCEPTANCE.md). Em resumo:

1. após reboot do Mac **sem login**, a VM recebe uma extração válida;
2. fechar a sessão SSH ou matar o processo não derruba o serviço;
3. a DAG de extração roda de ponta a ponta;
4. a atualização funciona, inclusive desfazendo uma troca com falha.
