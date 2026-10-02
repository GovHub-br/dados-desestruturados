# Contexto da mudança — Runner Docling sempre ativo no Mac Studio

- Status: proposto (escopo mínimo, definido em 2026-10-02)
- Origem: rascunho `mac-studio-runner-isolado.md` + inspeção somente leitura da
  VM de produção (`10.0.0.86`) e do Mac Studio (`10.0.0.10`) em 2026-10-01/02.

## Como funciona hoje

```text
VM de produção (Airflow)  ── envia o PDF ──▶  Mac Studio, porta 8081
                          ◀── devolve a extração (.tar.gz) ──
```

- A VM orquestra.
- O Mac executa o Docling, porque precisa da GPU da Apple, e o Docker no macOS
  não tem acesso a ela.
- O "runner" é uma API HTTP (`python -m docling_runtime.server`) que alguém
  inicia à mão num terminal do Mac.

## Problema

O runner só vive enquanto durar a sessão SSH de quem o iniciou:

- O histórico de logins mostra sessões de minutos a 4h45. A sessão que rodou
  as extrações de 21/09 fechou às 17h15, e o runner morreu junto.
- Não há timer de 1 hora: o processo cai quando o notebook dorme, a rede cai ou
  o terminal fecha.
- Depois de um reboot, ninguém religa o runner.

Em 2026-09-29 houve uma queda de energia e as duas máquinas reiniciaram:

- **Mac:** a máquina voltou, mas a porta 8081 ficou recusando conexão.
- **VM:** só o `nginx` voltou, porque os demais containers têm
  `restart: "no"`. O `atlas.gov-hub.io` ficou com erro 502 até 2026-10-02,
  quando a stack foi religada manualmente.

## Objetivo

Quando o Mac reiniciar ou o runner cair, o serviço volta sozinho e fica pronto
para extrair, sem ninguém entrar na máquina. Atualizar o runner passa a ser um
comando simples e seguro.

## Estado observado que importa para a implementação

| Item | Valor |
| --- | --- |
| Mac | macOS 26.5, M3 Ultra, 256 GB, usuário `lablivre` (admin), **sem auto-login**, **FileVault desligado**, energia já configurada para não dormir |
| Clone atual | `~/Desktop/ocr-cidades/dados-desestruturados`, branch `feat/dag-resolve`, sem alterações locais; código do Docling idêntico ao `main` |
| Python | venv `.venv-chart` com Python 3.14 do Homebrew; versões batem com o `requirements.txt`; 4 patches de GPU (MPS) aplicados à mão |
| Configuração | `.env` do clone fornece `DOCLING_LLM_*` e `DOCLING_TEXT_CANDIDATE_*`, mas tem `PIPELINE_TMP_DIR` e `HF_HOME` com caminhos de Docker (`/opt/...`) e senhas da stack da VM; funciona hoje só porque os `export` do terminal têm prioridade |
| Dados | `~/ocr-data`: cache de modelos 8 GB, `pipeline-tmp` 110 MB |
| Acesso ao GitHub | já funciona no Mac (chave SSH existente) |
| VM | Debian 12, `main` @ 107f3e9, `DOCLING_RUNNER_BASE_URL=http://10.0.0.10:8081`, timeouts 1800/1500 s |

## Armadilhas que a implementação precisa evitar

1. **`python3` pelo `PATH`.** O runner inicia o Docling com o comando literal
   `python3`. Um serviço do macOS não ativa o venv, então, sem o `bin/` do
   venv no `PATH`, a porta responde mas toda extração falha com
   `ModuleNotFoundError`.
2. **Configuração do LLM.** A VM pede a etapa de LLM, e quem lê
   `DOCLING_LLM_*` é o Mac. Sem essas chaves, **toda** extração aborta (exit
   2). Elas precisam ir para a configuração nova, sem mudar os valores.
3. **Copiar o `.env` inteiro.** Levaria `HF_HOME=/opt/...` e
   `PIPELINE_TMP_DIR=/opt/...`, que não existem no Mac.
4. **Patches de GPU.** Um venv novo instalado só com o `requirements.txt` não
   tem os 4 patches de MPS. O script que aplica está em
   `infra/airflow/scripts/apply_docling_vlm_patches.py`.
5. **Desktop.** O macOS pode bloquear um serviço de sistema que lê
   `~/Desktop`, por proteção de privacidade (TCC). O código do serviço fica
   fora do Desktop.

## Fora de escopo (registrado para depois)

- Restart automático da stack da VM. Hoje ela tem `restart: "no"` e exige
  `docker compose … up -d` manual após reboot (ver D7).
- Token de acesso na porta 8081 (hoje qualquer máquina da rede pode enviar
  PDFs).
- Chave do GitHub dedicada e somente leitura. Por ora usa-se o acesso
  existente.
- **Etapa de LLM da extração textual quebrada:** `gpt-oss:120b` não existe no
  Ollama. Em 21/09 foram 322 chamadas com 404 e `text_structures` vazio nos 7
  PDFs. O DeepSeek configurado na VM é outro uso (DAG 3).
- Ollama como serviço de sistema (hoje só sobe com login).
- `/readyz`, versão do runner no manifesto, limpeza automática de jobs
  antigos, rotação de logs.
- Bug de permissão em `/opt/airflow/logs` que derrubou o `dag-processor` em
  25/09.
- Clone `~/Desktop/ocr-cidades/docling` com trabalho não commitado (fica como
  está).

## Riscos

| Risco | Mitigação |
| --- | --- |
| GPU (MPS) indisponível para um serviço de sistema sem login | Baixo: o PyTorch enumera as GPUs sem depender de sessão gráfica. Verificado no aceite (reboot sem login + duração de uma extração real) |
| `brew upgrade` trocar o Python por baixo do venv | Atualizações de patch (3.14.x) são compatíveis; uma troca de versão menor exige recriar o venv (runbook) |
| Atualização no meio de uma extração | O script de atualização espera não haver extração rodando |
