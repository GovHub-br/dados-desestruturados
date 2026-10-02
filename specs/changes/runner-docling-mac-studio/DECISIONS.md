# Decisões — Runner Docling sempre ativo no Mac Studio

Princípio: **escopo mínimo e implementação simples**. O objetivo é o runner do
Mac voltar sozinho. Melhorias de segurança, rastreabilidade e LLM ficam
registradas em [CONTEXT.md](CONTEXT.md) como fora de escopo.

## D1 — LaunchDaemon sob `lablivre`

- **Decisão:** `/Library/LaunchDaemons/com.ocr-cidades.docling-runner.plist` com
  `UserName=lablivre`.
- **Por quê:**
  - O Mac não tem auto-login. Um LaunchAgent (serviço de usuário) só sobe
    quando alguém faz login, como aconteceu com o Ollama em 29–30/09.
  - Com FileVault desligado, um LaunchDaemon sobe no boot sem login.
  - Rodar como `lablivre` mantém o dono de `~/ocr-data` e do cache de modelos.

## D2 — Clone completo e dedicado, por HTTPS anônimo

- **Decisão:** `~/docling-runner/repo`, clone completo no branch `main`, por
  `https://github.com/GovHub-br/dados-desestruturados.git`.
- **Por que HTTPS:**
  - O repositório é público.
  - A chave SSH que já existe no Mac (`id_rsa`) tem senha guardada no
    Keychain (`UseKeychain yes`). O Keychain só destrava com login, então a
    atualização automática falharia depois de um reboot sem login.
  - Testado em 2026-10-02: HTTPS anônimo funciona num ambiente zerado
    (`env -i`), igual ao do launchd.
- **Por quê:**
  - Simplicidade, decidida em 2026-10-02.
  - Fora do Desktop, para evitar o bloqueio de privacidade do macOS a
    serviços.
  - Separado do clone de desenvolvimento, para o serviço nunca rodar código
    de branch ou edição local.
- **Regra:** o clone é espelho, não bancada de trabalho. O script de
  atualização recusa rodar se houver alteração local.

## D3 — Venv equivalente ao atual, fora do clone

- **Decisão:**
  1. criar `~/docling-runner/venv` com `/opt/homebrew/bin/python3.14`;
  2. instalar exatamente o `pip freeze` do `.venv-chart` atual (129 pacotes);
  3. aplicar `infra/airflow/scripts/apply_docling_vlm_patches.py`;
  4. rodar `pip check`.
- **Por quê:**
  - Reproduz o ambiente que já funciona em produção, incluindo os patches de
    GPU.
  - Fora do clone, nenhuma operação do git o afeta.
  - O freeze é guardado em `~/docling-runner/pip-freeze-base.txt` como linha
    de base.

## D4 — Configuração em `runner.env`, só com o necessário

- **Decisão:** um arquivo `~/docling-runner/runner.env`, carregado pelo
  launcher, com as variáveis do runner e as linhas `DOCLING_LLM_*` e
  `DOCLING_TEXT_CANDIDATE_*` copiadas do `.env` atual, sem alterar valores.
- **Por quê:**
  - Mantém as extrações idênticas às de hoje.
  - Não copiar o `.env` inteiro, porque ele tem `HF_HOME` e
    `PIPELINE_TMP_DIR` de Docker (`/opt/...`) e senhas da stack da VM.
  - O clone dedicado nunca tem `.env`.

## D5 — Nenhuma mudança em código Python

- **Decisão:** a armadilha do `python3` é resolvida pelo launcher, que coloca
  o `bin/` do venv no início do `PATH`.
- **Por quê:**
  - Entrega menor, sem PR de código nem release da VM.
  - A troca para `sys.executable` no `command_builder.py` fica como melhoria
    futura.

## D6 — Reinício sem `sudo` na atualização

- **Decisão:**
  - o script de atualização encerra o processo do runner com `SIGTERM` (o
    processo é do próprio `lablivre`), e o `KeepAlive` religa com o código
    novo;
  - o launchd encerra junto os processos filhos, então nenhum Docling fica
    órfão;
  - `sudo` só na instalação.

## D7 — Atualização automática a cada 15 min, acompanhando o branch em uso

- **Decisão:** um segundo LaunchDaemon
  (`com.ocr-cidades.docling-runner-atualizacao`, `StartInterval=900`,
  `ProcessType=Background`) executa `atualizar-runner.sh`, decidido em
  2026-10-02. Sem argumento, o script segue o branch em uso. Assim, testar
  um branch não é desfeito pelo agendamento, e voltar é
  `atualizar-runner.sh main`.
- **Consequência:** todo merge no `main` chega à produção em até 15 min. O
  `main` precisa estar sempre em condição de rodar.
- **Proteções para rodar sem supervisão:**
  - trava com PID, que remove a trava órfã de uma execução interrompida;
  - o commit revertido não é tentado de novo, para um `main` quebrado não
    reiniciar o runner a cada 15 min;
  - no revert, o runner só reinicia se já tiver sido reiniciado;
  - histórico em `~/docling-runner/atualizacoes.log`.

## D8 — VM fora desta entrega

- **Decisão:** a VM de produção não é alterada agora (decidido em 2026-10-02).
- **Consequência conhecida:** após um reboot da VM, a stack precisa ser
  religada manualmente com
  `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d`, como
  em 2026-10-02.
- **Melhoria futura:** `restart: unless-stopped` nos serviços de longa duração
  do `docker-compose.prod.yml`.
