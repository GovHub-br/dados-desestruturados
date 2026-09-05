# Runner Docling como Servico Persistente no Mac Studio (launchd)

## Objetivo

Este documento descreve como transformar a execucao manual do runner Docling
(`python -m docling_runtime.server`) em um servico persistente no Mac Studio,
usando `launchd`, o gerenciador de servicos nativo do macOS.

Hoje, o fluxo depende de entrar na maquina e rodar o comando manualmente a
cada vez:

```bash
cd ~/Desktop/ocr-cidades/dados-desestruturados/
source .venv-chart/bin/activate

export PYTHONPATH=$PWD
export PROJECT_ROOT=$PWD
export DOCLING_RUNNER_HOST=0.0.0.0
export DOCLING_RUNNER_PORT=8081
export PIPELINE_TMP_DIR="$HOME/ocr-data/pipeline-tmp"
export HF_HOME="$HOME/ocr-data/huggingface-cache"

python -m docling_runtime.server
```

O problema desse modelo: o processo fica preso a sessao de terminal (ou SSH)
que o iniciou. Se a sessao cai, a VPN reconecta, ou a maquina reinicia, o
processo morre e a porta 8081 para de escutar ate alguem entrar de novo e
rodar o comando. "Maquina sempre ligada" nao implica "processo sempre
rodando" — sao coisas independentes.

Com `launchd`, o processo sobe sozinho no boot/login da Mac Studio, reinicia
automaticamente se cair, e nao depende de nenhum terminal aberto.

## Pre-requisitos

- Repositorio clonado no Mac Studio (mesmo caminho usado no fluxo manual).
- Ambiente virtual `.venv-chart` ja criado e com as dependencias instaladas.
- Confirmar o caminho absoluto do usuario no Mac Studio, por exemplo:
  `/Users/<usuario-mac-studio>/Desktop/ocr-cidades/dados-desestruturados`.

Importante: `launchd` **nao** executa `.zshrc`, `.zprofile` nem
`source .venv-chart/bin/activate`. Ele nao tem shell interativo por tras.
Por isso o `.plist` precisa apontar diretamente para o interpretador Python
dentro do venv, usando caminho absoluto, e declarar as variaveis de ambiente
explicitamente.

## LaunchAgent vs LaunchDaemon

`launchd` tem dois tipos de servico relevantes aqui:

- **LaunchAgent**: roda no contexto de um usuario logado. So inicia depois
  que esse usuario faz login na sessao grafica (ou a sessao ja esta ativa).
  Fica em `~/Library/LaunchAgents/`.
- **LaunchDaemon**: roda em nivel de sistema, antes mesmo de qualquer login
  de usuario, e continua rodando mesmo sem sessao grafica ativa. Fica em
  `/Library/LaunchDaemons/` e exige `sudo` para instalar.

Recomendacao para este caso: se o Mac Studio fica normalmente com o usuario
logado (sessao aberta, sem logout), um **LaunchAgent** e suficiente e mais
simples de manter. Se a maquina pode reiniciar e ficar na tela de login sem
ninguem logar, use **LaunchDaemon** para garantir que o runner suba de
qualquer forma.

Este guia usa LaunchAgent como caminho principal, com uma nota sobre a
adaptacao para LaunchDaemon no final.

## Passo a passo

### 1. Confirmar o caminho do Python do venv

```bash
cd ~/Desktop/ocr-cidades/dados-desestruturados
source .venv-chart/bin/activate
which python
```

Anote o caminho absoluto retornado (algo como
`/Users/<usuario-mac-studio>/Desktop/ocr-cidades/dados-desestruturados/.venv-chart/bin/python`).
Ele sera usado diretamente no `.plist`, sem precisar ativar o venv.

### 2. Criar as pastas de dados, se ainda nao existirem

```bash
mkdir -p "$HOME/ocr-data/pipeline-tmp" "$HOME/ocr-data/huggingface-cache" "$HOME/ocr-data/logs"
```

### 3. Criar o arquivo `.plist`

Criar o arquivo em:

```text
~/Library/LaunchAgents/com.ocr-cidades.docling-runner.plist
```

Conteudo (substitua `<usuario-mac-studio>` pelo usuario real da maquina em
todos os caminhos):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.ocr-cidades.docling-runner</string>

  <key>ProgramArguments</key>
  <array>
    <string>/Users/&lt;usuario-mac-studio&gt;/Desktop/ocr-cidades/dados-desestruturados/.venv-chart/bin/python</string>
    <string>-m</string>
    <string>docling_runtime.server</string>
  </array>

  <key>WorkingDirectory</key>
  <string>/Users/&lt;usuario-mac-studio&gt;/Desktop/ocr-cidades/dados-desestruturados</string>

  <key>EnvironmentVariables</key>
  <dict>
    <key>PYTHONPATH</key>
    <string>/Users/&lt;usuario-mac-studio&gt;/Desktop/ocr-cidades/dados-desestruturados</string>
    <key>PROJECT_ROOT</key>
    <string>/Users/&lt;usuario-mac-studio&gt;/Desktop/ocr-cidades/dados-desestruturados</string>
    <key>DOCLING_RUNNER_HOST</key>
    <string>0.0.0.0</string>
    <key>DOCLING_RUNNER_PORT</key>
    <string>8081</string>
    <key>PIPELINE_TMP_DIR</key>
    <string>/Users/&lt;usuario-mac-studio&gt;/ocr-data/pipeline-tmp</string>
    <key>HF_HOME</key>
    <string>/Users/&lt;usuario-mac-studio&gt;/ocr-data/huggingface-cache</string>
  </dict>

  <key>RunAtLoad</key>
  <true/>

  <key>KeepAlive</key>
  <true/>

  <key>StandardOutPath</key>
  <string>/Users/&lt;usuario-mac-studio&gt;/ocr-data/logs/docling-runner.out.log</string>

  <key>StandardErrorPath</key>
  <string>/Users/&lt;usuario-mac-studio&gt;/ocr-data/logs/docling-runner.err.log</string>
</dict>
</plist>
```

Funcao de cada chave:

- `ProgramArguments`: comando executado, equivalente a
  `python -m docling_runtime.server`, mas com o Python do venv referenciado
  por caminho absoluto (substitui a necessidade de `source .venv-chart/bin/activate`).
- `WorkingDirectory`: equivalente ao `cd` feito manualmente antes de rodar o
  comando.
- `EnvironmentVariables`: substitui os `export` feitos manualmente no
  terminal.
- `RunAtLoad`: inicia o servico assim que o `launchd` carrega o `.plist`
  (no login do usuario, para LaunchAgent).
- `KeepAlive`: reinicia o processo automaticamente se ele cair ou crashar.
- `StandardOutPath` / `StandardErrorPath`: para onde vao os `print()` do
  runner (equivalente ao que hoje aparece no terminal).

### 4. Carregar o servico

```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.ocr-cidades.docling-runner.plist
```

Em versoes mais antigas do macOS, o equivalente e:

```bash
launchctl load ~/Library/LaunchAgents/com.ocr-cidades.docling-runner.plist
```

### 5. Verificar se esta rodando

```bash
launchctl list | grep docling-runner
curl http://localhost:8081/healthz
```

Resposta esperada do `curl`:

```json
{"status": "ok", "service": "docling-runner", "checked_at": "..."}
```

Tambem vale testar pela VPN, a partir do notebook local, com o IP do Mac
Studio na VPN:

```bash
curl http://<IP_DO_MAC_STUDIO_NA_VPN>:8081/healthz
```

### 6. Acompanhar logs

```bash
tail -f "$HOME/ocr-data/logs/docling-runner.out.log"
tail -f "$HOME/ocr-data/logs/docling-runner.err.log"
```

### 7. Reiniciar apos alterar o codigo do runner

Sempre que `docling_runtime/` ou `docling_pipeline/` mudar no Mac Studio
(por exemplo, apos um `git pull`), reinicie o servico para carregar o codigo
novo:

```bash
launchctl kickstart -k gui/$(id -u)/com.ocr-cidades.docling-runner
```

### 8. Parar ou remover o servico

Parar temporariamente:

```bash
launchctl kill SIGTERM gui/$(id -u)/com.ocr-cidades.docling-runner
```

Remover definitivamente (o `launchd` para de gerenciar o processo):

```bash
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.ocr-cidades.docling-runner.plist
```

## Cuidados operacionais

- **Sono do sistema**: se o Mac Studio entrar em modo de suspensao, a porta
  para de responder mesmo com o `launchd` configurado. Em
  `Ajustes do Sistema > Energia`, desative o sono automatico para essa
  maquina (ou use `sudo pmset -a sleep 0` e `sudo pmset -a disksleep 0`),
  já que ela atua como servidor.
- **Firewall do macOS**: em `Ajustes do Sistema > Rede > Firewall`, garanta
  que o Python do `.venv-chart` (ou conexoes de entrada em geral) nao esteja
  bloqueado. Do contrario, o processo escuta em `0.0.0.0:8081` mas o SO
  descarta os pacotes antes de chegar nele.
- **Caminhos absolutos**: `launchd` nao expande `$HOME` nem `~` dentro do
  `.plist`. Todos os caminhos precisam estar escritos por extenso.
- **Usuario logado**: como este e um LaunchAgent, ele so inicia quando o
  usuario `<usuario-mac-studio>` estiver logado na sessao. Se o Mac Studio
  reiniciar e ficar parado na tela de login, o runner nao sobe sozinho nesse
  modelo — ver secao abaixo para o caso de LaunchDaemon.

## Adaptando para LaunchDaemon (roda sem login)

Se for necessario que o runner suba mesmo sem nenhum usuario logado (por
exemplo, apos um reboot remoto), use um LaunchDaemon em vez de LaunchAgent:

1. Copiar o mesmo `.plist` para `/Library/LaunchDaemons/com.ocr-cidades.docling-runner.plist`
   (requer `sudo`).
2. Adicionar a chave `UserName` no `.plist` apontando para o usuario dono do
   repositorio e do venv, para que o processo nao rode como `root`:

   ```xml
   <key>UserName</key>
   <string>&lt;usuario-mac-studio&gt;</string>
   ```

3. Carregar com `sudo`:

   ```bash
   sudo launchctl bootstrap system /Library/LaunchDaemons/com.ocr-cidades.docling-runner.plist
   ```

O restante (verificacao, logs, reinicio) segue igual, trocando
`gui/$(id -u)` por `system` nos comandos `launchctl`.

## Relacao com o fluxo upload/download

Este documento cobre apenas a persistencia do processo do runner. O
contrato HTTP (`/extract-file`, headers, formato de resposta) e a logica de
rede entre notebook local e Mac Studio estao descritos em
[docling-remote-mac-studio.md](docling-remote-mac-studio.md). Depois que o
`launchd` estiver configurado, o restante do fluxo (chamada da DAG 1,
upload do PDF, download do `.tar.gz`) continua exatamente igual.
