# Runner Docling como serviço no Mac Studio (launchd)

- Status: vigente
- Responsável: Davi de Aguiar Vieira
- Última revisão: 2026-10-02
- Mudança de origem: [`specs/changes/runner-docling-mac-studio/`](../../specs/changes/runner-docling-mac-studio/PLAN.md)

O runner Docling (`python -m docling_runtime.server`, porta 8081) recebe PDFs
da VM de produção e devolve a extração. No Mac Studio ele roda como
**LaunchDaemon** do launchd, o gerenciador de serviços do macOS:

- sobe no boot, sem ninguém fazer login;
- volta sozinho se o processo morrer;
- não depende de terminal ou sessão SSH;
- se atualiza sozinho: a cada 15 min, um segundo LaunchDaemon verifica se há
  commit novo e, se houver, troca o código e reinicia o runner com segurança.

O contrato HTTP está em [docling-remote-mac-studio.md](docling-remote-mac-studio.md).

## Onde fica cada coisa

| Caminho | Conteúdo |
| --- | --- |
| `/Library/LaunchDaemons/com.ocr-cidades.docling-runner.plist` | Serviço do runner (cópia de `infra/docling-runner/macos/`) |
| `/Library/LaunchDaemons/com.ocr-cidades.docling-runner-atualizacao.plist` | Atualização automática a cada 15 min |
| `~/docling-runner/repo/` | Clone dedicado do repositório por HTTPS, branch `main`. É espelho: não edite código aqui |
| `~/docling-runner/venv/` | Python 3.14 com as dependências e os patches de GPU (MPS) |
| `~/docling-runner/runner.env` | Configuração do runner e do pipeline (modelo: `runner.env.example`) |
| `~/docling-runner/atualizacoes.log` | Histórico das atualizações aplicadas ou revertidas |
| `~/ocr-data/pipeline-tmp/jobs/` | PDFs recebidos e extrações, por `execution_id` |
| `~/ocr-data/huggingface-cache/` | Modelos baixados (~8 GB) |
| `~/ocr-data/logs/docling-runner.{out,err}.log` | Saída do runner |
| `~/ocr-data/logs/docling-runner-atualizacao.log` | Saída de cada verificação de atualização |

Arquivos versionados em `infra/docling-runner/macos/`:

- os dois plists;
- `run-runner.sh`, que o serviço executa e que monta o ambiente;
- `atualizar-runner.sh`, usado pela atualização automática e pela manual;
- `runner.env.example`, o modelo da configuração.

O código fica fora do Desktop porque o macOS bloqueia o acesso de serviços às
pastas Desktop, Documentos e Downloads (TCC).

## Operação diária

```bash
# Está rodando? (state = running, pid, last exit code)
launchctl print system/com.ocr-cidades.docling-runner | grep -E 'state|pid|last exit'
curl -fsS http://localhost:8081/healthz

# Logs do serviço e de um job
tail -f ~/ocr-data/logs/docling-runner.out.log ~/ocr-data/logs/docling-runner.err.log
tail -n 50 ~/ocr-data/pipeline-tmp/jobs/<execution_id>/extraction/runner.log

# Reiniciar (o launchd religa sozinho em segundos)
pkill -TERM -f '[-]m docling_runtime[.]server'
```

### Atualização do código (automática)

A cada 15 min, o LaunchDaemon `com.ocr-cidades.docling-runner-atualizacao`
roda `atualizar-runner.sh`. Um merge no `main` chega à produção em até 15 min,
sem ninguém entrar na máquina. A cada execução, o script:

1. sai sem fazer nada se não houver commit novo, registrando uma linha no log;
2. espera terminar a extração em andamento;
3. troca o código;
4. reinstala as dependências se o `requirements.txt` mudou;
5. valida o pipeline no ambiente do serviço;
6. reinicia o runner e confere o `/healthz`.

Se algo falhar, volta sozinho ao commit anterior. O commit com falha fica
registrado em `~/docling-runner/.commit-com-falha` e **não é tentado de novo**
até chegar um commit mais novo. Assim, um `main` quebrado não fica
reiniciando o runner a cada 15 min. Para forçar nova tentativa do mesmo
commit, apague esse arquivo.

Uma extração que chegue no instante do reinício é interrompida, e o Airflow a
repete (`retries=1`).

```bash
# O que aconteceu? (aplicadas e revertidas)
cat ~/docling-runner/atualizacoes.log
tail -n 20 ~/ocr-data/logs/docling-runner-atualizacao.log

# Aplicar agora, sem esperar os 15 min
~/docling-runner/repo/infra/docling-runner/macos/atualizar-runner.sh

# Pausar e retomar a atualização automática (o runner continua no ar)
sudo launchctl bootout system/com.ocr-cidades.docling-runner-atualizacao
sudo launchctl bootstrap system /Library/LaunchDaemons/com.ocr-cidades.docling-runner-atualizacao.plist
```

### Testar um branch antes do `main`

A atualização automática **acompanha o branch em uso** no clone:

```bash
~/docling-runner/repo/infra/docling-runner/macos/atualizar-runner.sh <branch>  # passa a rodar o branch
~/docling-runner/repo/infra/docling-runner/macos/atualizar-runner.sh main      # volta para o main
```

Enquanto o clone estiver no branch de teste, cada push nesse branch chega ao
runner em até 15 min. **Não esqueça de voltar para o `main`**: o branch em uso
aparece em cada linha de `atualizacoes.log`.

### Alterar configuração

Edite `~/docling-runner/runner.env` e reinicie. O launchd não lê `.env`; o
clone dedicado nunca deve ter um.

## Instalação (uma vez)

Pelo SSH, como `lablivre`. Antes, confira que nenhum runner manual está
rodando: `lsof -nP -iTCP:8081 -sTCP:LISTEN` deve voltar vazio.

**1. Clone e pastas:**

```bash
mkdir -p ~/docling-runner ~/ocr-data/logs
git clone https://github.com/GovHub-br/dados-desestruturados.git ~/docling-runner/repo
```

Use HTTPS, não SSH. O repositório é público e a atualização automática roda
sem ninguém logado. Nessa situação, uma chave SSH protegida por senha (cuja
senha o macOS guarda no Keychain) não funciona, porque o Keychain só destrava
com login.

**2. Ambiente Python, com as mesmas versões do ambiente em uso:**

```bash
LEGADO=~/Desktop/ocr-cidades/dados-desestruturados
"$LEGADO/.venv-chart/bin/python" -m pip freeze > ~/docling-runner/pip-freeze-base.txt
/opt/homebrew/bin/python3.14 -m venv ~/docling-runner/venv
~/docling-runner/venv/bin/python -m pip install -r ~/docling-runner/pip-freeze-base.txt
~/docling-runner/venv/bin/python ~/docling-runner/repo/infra/airflow/scripts/apply_docling_vlm_patches.py
~/docling-runner/venv/bin/python -m pip check
```

Os patches ajustam `transformers` e `docling` para a GPU da Apple (MPS). Sem
eles, a extração de gráficos falha.

**3. Configuração.** Copiar **só** as linhas do pipeline do `.env` antigo. O
arquivo inteiro traz caminhos de Docker (`/opt/...`) e credenciais da VM.

```bash
cp ~/docling-runner/repo/infra/docling-runner/macos/runner.env.example ~/docling-runner/runner.env
grep -E '^DOCLING_(LLM|TEXT_CANDIDATE)_' "$LEGADO/.env" >> ~/docling-runner/runner.env
chmod 600 ~/docling-runner/runner.env
```

**4. Validar no ambiente do serviço**, sem o `PATH` do terminal, como o
launchd fará:

```bash
cd ~/docling-runner/repo && env -i HOME="$HOME" PATH="$HOME/docling-runner/venv/bin:/usr/bin:/bin" \
  PYTHONPATH="$HOME/docling-runner/repo" python3 -m docling_pipeline --help >/dev/null && echo ok
```

**5. Registrar o runner e, depois, a atualização automática:**

```bash
for NOME in com.ocr-cidades.docling-runner com.ocr-cidades.docling-runner-atualizacao; do
  P="/Library/LaunchDaemons/$NOME.plist"
  sudo cp ~/docling-runner/repo/infra/docling-runner/macos/"$NOME".plist "$P"
  sudo chown root:wheel "$P" && sudo chmod 644 "$P" && plutil -lint "$P"
  sudo launchctl bootstrap system "$P"
done
```

**6. Conferir:**

- `curl -fsS http://localhost:8081/healthz` no Mac;
- `curl -fsS http://10.0.0.10:8081/healthz` a partir da VM;
- depois de até 15 min, uma linha "Nada novo" em
  `~/ocr-data/logs/docling-runner-atualizacao.log`.

Se um plist mudar no repositório, repita o passo 5 para ele, precedido de
`sudo launchctl bootout system/<nome>`. A atualização automática troca o
código, mas não reinstala plists.

## Diagnóstico

| Sintoma | Causa provável | O que fazer |
| --- | --- | --- |
| `/healthz` não responde e `launchctl print` mostra `last exit code` ≠ 0 | o launcher falhou: `runner.env` ou venv ausente, porta ocupada | ler `docling-runner.err.log`; `lsof -nP -iTCP:8081` |
| `/healthz` ok, mas toda extração volta JSON com `ModuleNotFoundError` | o subprocesso não está usando o Python do venv | conferir se o venv existe e rodar o passo 4 da instalação |
| Extração volta erro citando `--llm-api-url` | `DOCLING_LLM_*` faltando no `runner.env` (a VM pediu LLM) | refazer o passo 3 da instalação |
| Extração muito mais lenta que o normal | GPU (MPS) indisponível, rodando em CPU | ver `runner.log` do job; `~/docling-runner/venv/bin/python -c "import torch; print(torch.backends.mps.is_available())"` |
| Porta não responde da VM, mas responde no Mac | rede ou firewall do macOS | `nc -vz 10.0.0.10 8081` a partir da VM |
| `atualizar-runner.sh` recusa por alterações locais | alguém editou o clone dedicado | `git -C ~/docling-runner/repo status`; descartar ou levar a mudança para o GitHub |
| Merge no `main` não chegou ao runner | atualização pausada, commit marcado com falha ou extração longa em andamento | `tail ~/ocr-data/logs/docling-runner-atualizacao.log`; `launchctl print system/com.ocr-cidades.docling-runner-atualizacao` |
| Log de atualização diz "commit … já falhou" | o commit não passou na validação e foi revertido | ver o motivo em `atualizacoes.log`; corrigir no GitHub ou apagar `~/docling-runner/.commit-com-falha` para tentar de novo |

## Recriar o ambiente Python

Necessário se o Homebrew trocar a versão menor do Python (por exemplo,
3.14 → 3.15) ou se o venv corromper. Pare o serviço com
`sudo launchctl bootout system/com.ocr-cidades.docling-runner` e mova o venv
antigo para o lado. Depois:

1. refaça o passo 2 da instalação usando
   `~/docling-runner/pip-freeze-base.txt`;
2. reinstale `~/docling-runner/repo/requirements.txt` por cima, caso ele tenha
   mudado desde a instalação;
3. refaça o passo 5.

## Remover o serviço

```bash
for NOME in com.ocr-cidades.docling-runner-atualizacao com.ocr-cidades.docling-runner; do
  sudo launchctl bootout "system/$NOME"
  sudo rm "/Library/LaunchDaemons/$NOME.plist"
done
```

Para voltar ao modo manual, em último caso:

```bash
cd ~/Desktop/ocr-cidades/dados-desestruturados && source .venv-chart/bin/activate
export PYTHONPATH=$PWD DOCLING_RUNNER_HOST=0.0.0.0 DOCLING_RUNNER_PORT=8081 \
  PIPELINE_TMP_DIR="$HOME/ocr-data/pipeline-tmp" HF_HOME="$HOME/ocr-data/huggingface-cache"
python -m docling_runtime.server
```

Nesse modo o runner só vive enquanto o terminal estiver aberto.
