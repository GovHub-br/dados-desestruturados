# Docling Remoto com Upload do PDF e Retorno da Pasta de Extracao

## Objetivo

Este documento descreve uma alternativa de arquitetura para executar o
processamento pesado do Docling em um Mac Studio remoto, sem exigir que o Mac
Studio acesse o notebook local.

Neste modelo, apenas o notebook inicia conexoes de rede:

```text
Notebook local
  -> envia PDF para o Mac Studio via HTTP
  -> Mac Studio processa o PDF localmente
  -> Mac Studio devolve a pasta de extracao compactada
  -> notebook extrai a pasta localmente
  -> notebook faz a ingestao/persistencia local
```

Essa abordagem evita a necessidade de:

- expor o MinIO local para o Mac Studio
- permitir conexoes do Mac Studio para o notebook
- usar filesystem compartilhado entre as maquinas
- instalar Docker no Mac Studio

## Contexto

O fluxo anterior assumia que o Mac Studio conseguiria acessar o MinIO local no
notebook. Isso exigiria conectividade no sentido:

```text
Mac Studio -> notebook:9000
```

No seu caso, a premissa e diferente: o notebook consegue acessar o Mac Studio,
mas o Mac Studio nao deve acessar o notebook.

Entao, a fronteira entre as maquinas deve ser invertida:

```text
Notebook -> Mac Studio
```

O notebook envia todos os dados necessarios para a execucao, e o Mac Studio
devolve todos os artefatos gerados.

## Arquitetura alvo

Fluxo detalhado:

```text
Airflow local em Docker
  -> baixa o PDF
  -> salva o PDF no MinIO local, como ja acontece hoje
  -> chama o runner HTTP no Mac Studio
      -> envia o PDF no corpo da requisicao
      -> envia metadados da execucao em headers ou query params
      -> Mac Studio salva o PDF em pasta temporaria
      -> Mac Studio roda python -m docling_pipeline
      -> Mac Studio gera uma pasta parecida com extraction_cury
      -> Mac Studio compacta a pasta em extraction.tar.gz
      -> Mac Studio devolve o archive para o notebook
  -> Airflow extrai o archive em output_dir local
  -> Airflow usa a ingestao local existente
  -> Airflow sobe artefatos no MinIO local
```

Exemplo da pasta gerada:

```text
extraction/
  metadata.json
  diagnostics.log
  blocks/
  cases/
  charts/
  metrics/
  sections/
  tables/
  text_candidates/
  text_structures/
```

Essa pasta e equivalente conceitual ao exemplo local:

```text
dados-desestruturados/extraction_cury/
```

## Contrato HTTP recomendado

Para manter a implementacao simples, a recomendacao e criar um endpoint novo no
runner:

```text
POST /extract-file
```

### Entrada

O corpo da requisicao deve ser o PDF bruto:

```http
Content-Type: application/pdf
```

Os metadados podem ir em headers HTTP:

```http
X-Execution-Id: cury-2025-3t
X-Input-Filename: relatorio.pdf
X-Do-Ocr: true
X-Do-Chart-Extraction: true
X-Enable-Llm-Text-Extraction: false
X-Timeout-Seconds: 1500
```

Por que usar PDF bruto em vez de JSON/base64:

- evita aumentar o tamanho do arquivo com base64
- simplifica o upload
- funciona bem com PDFs grandes
- e facil de salvar no disco no runner

### Saida

Se a execucao der certo, o runner devolve um arquivo compactado:

```http
Content-Type: application/gzip
Content-Disposition: attachment; filename="extraction.tar.gz"
```

O conteudo do `.tar.gz` deve conter a pasta `extraction/` ou diretamente os
arquivos internos da extracao. A recomendacao e incluir a pasta `extraction/`
para manter o retorno previsivel.

### Erro

Se a execucao falhar, o runner devolve JSON:

```json
{
  "status": "failed",
  "return_code": 1,
  "log_tail": "...",
  "error": "Falha na execucao remota do pipeline Docling."
}
```

## Diretorios temporarios no Mac Studio

No Mac Studio, use uma raiz dedicada:

```bash
mkdir -p "$HOME/ocr-data/pipeline-tmp" "$HOME/ocr-data/huggingface-cache" "$HOME/ocr-data/logs"
```

Para cada execucao:

```text
$PIPELINE_TMP_DIR/
  jobs/
    <execution_id>/
      input/
        documento.pdf
      extraction/
        metadata.json
        blocks/
        tables/
        charts/
        ...
      extraction.tar.gz
      runner.log
```

Funcao de cada pasta:

- `input/`: guarda o PDF recebido do notebook.
- `extraction/`: guarda a saida do `docling_pipeline`.
- `extraction.tar.gz`: archive enviado de volta ao notebook.
- `runner.log`: log da execucao do processo Docling.

## Variaveis no Mac Studio

Para teste manual:

```bash
export PYTHONPATH=$PWD
export PROJECT_ROOT=$PWD
export DOCLING_RUNNER_HOST=0.0.0.0
export DOCLING_RUNNER_PORT=8081
export PIPELINE_TMP_DIR="$HOME/ocr-data/pipeline-tmp"
export HF_HOME="$HOME/ocr-data/huggingface-cache"
```

Funcao das variaveis:

- `PYTHONPATH`: permite que o Python encontre `docling_runtime` e
  `docling_pipeline`.
- `PROJECT_ROOT`: preserva o mesmo contrato usado no ambiente Docker.
- `DOCLING_RUNNER_HOST`: com `0.0.0.0`, o runner escuta na interface da VPN.
- `DOCLING_RUNNER_PORT`: define a porta HTTP do runner.
- `PIPELINE_TMP_DIR`: define onde o Mac Studio guarda PDF recebido, saidas e
  archives.
- `HF_HOME`: define onde modelos/cache do Hugging Face ficam persistidos.

Neste modelo, o Mac Studio nao precisa de variaveis `MINIO_*`, porque ele nao
acessa o MinIO local.

## Mudancas no runner remoto

Arquivo principal:

```text
dados-desestruturados/docling_runtime/server.py
```

Hoje o runner aceita:

```json
{
  "input_path": "...",
  "output_dir": "..."
}
```

Esse contrato assume filesystem compartilhado. Para o novo fluxo, adicione um
endpoint separado:

```text
POST /extract-file
```

Responsabilidades desse endpoint:

1. ler o PDF bruto do corpo da requisicao
2. criar `job_dir` em `$PIPELINE_TMP_DIR/jobs/<execution_id>`
3. salvar o PDF em `job_dir/input/documento.pdf`
4. criar `job_dir/extraction`
5. chamar o comando existente do `DoclingCommandBuilder`
6. compactar `job_dir/extraction` em `job_dir/extraction.tar.gz`
7. devolver o `.tar.gz` para o notebook

Pseudocodigo:

```python
execution_id = sanitize(headers["X-Execution-Id"])
job_dir = Path(os.environ["PIPELINE_TMP_DIR"]) / "jobs" / execution_id
input_dir = job_dir / "input"
output_dir = job_dir / "extraction"
archive_path = job_dir / "extraction.tar.gz"

input_dir.mkdir(parents=True, exist_ok=True)
output_dir.mkdir(parents=True, exist_ok=True)

pdf_path = input_dir / safe_filename
pdf_path.write_bytes(request_body)

run_docling(input_path=pdf_path, output_dir=output_dir)
create_tar_gz(archive_path, output_dir)
return_file(archive_path)
```

Para criar o `.tar.gz`, use a biblioteca padrao:

```python
import tarfile

with tarfile.open(archive_path, "w:gz") as tar:
    tar.add(output_dir, arcname="extraction")
```

## Mudancas no client do Airflow

Arquivo principal:

```text
dados-desestruturados/airflow/plugins/clients/docling_pipeline_client.py
```

Hoje o metodo `run_extract_command` envia JSON para `/extract`.

O `HttpClient` atual do projeto e voltado principalmente para JSON/NDJSON. Para
esse fluxo, sera necessario criar um metodo novo para transferencia binaria:

```text
PDF local -> corpo HTTP application/pdf -> resposta application/gzip
```

Para o novo fluxo, crie um metodo novo, por exemplo:

```python
def run_extract_file_command(
    self,
    *,
    input_path: str,
    output_dir: str,
    execution_id: str,
    do_ocr: bool = True,
    do_chart_extraction: bool = False,
    enable_llm_text_extraction: bool = False,
) -> dict[str, object]:
    ...
```

Responsabilidades desse metodo:

1. abrir o PDF local (`input_path`)
2. fazer `POST` para `/extract-file`
3. enviar o PDF como `application/pdf`
4. receber `extraction.tar.gz`
5. extrair o archive dentro de `output_dir`
6. retornar metadados da execucao para o manifesto

Exemplo de chamada HTTP:

```text
POST http://<IP_DO_MAC_STUDIO_NA_VPN>:8081/extract-file
Content-Type: application/pdf
X-Execution-Id: <execution_id>
X-Input-Filename: <nome_do_pdf>
X-Do-Ocr: true
X-Do-Chart-Extraction: true
X-Enable-Llm-Text-Extraction: false
```

Para extrair o `.tar.gz` localmente:

```python
import tarfile

with tarfile.open(downloaded_archive, "r:gz") as tar:
    tar.extractall(output_dir.parent)
```

Observacao importante: ao extrair archives recebidos por rede, valide os paths
dos membros do tar para evitar path traversal. O archive e gerado pelo nosso
runner, mas ainda vale manter essa protecao.

## Mudancas no service da DAG

Arquivo principal:

```text
dados-desestruturados/airflow/plugins/services/detecta_pdf_extrai_service.py
```

Hoje o service cria `output_dir`, chama o runner e depois faz:

```python
artifact_uris = self.minio_client.upload_directory(directory=output_dir, object_prefix=object_prefix)
```

Esse trecho pode continuar existindo.

A diferenca e que, antes, o runner escrevia diretamente em `output_dir` por
volume compartilhado. No novo fluxo, o runner devolve `extraction.tar.gz`, e o
client do Airflow extrai esse archive em `output_dir`.

Depois disso, a ingestao local permanece igual:

```text
output_dir local preenchido
  -> upload_directory(output_dir)
  -> manifesto_execucao.json
  -> artifact_uris no MinIO local
```

Na pratica, depois que o client extrair o `extraction.tar.gz`, a DAG deve voltar
a enxergar a pasta local como se o Docling tivesse rodado no proprio ambiente
local.

## Observacao sobre logs em tempo real

O endpoint atual `/extract` usa NDJSON para enviar logs conforme o processamento
avanca. No endpoint proposto `/extract-file`, a resposta principal e o arquivo
`.tar.gz`, entao a implementacao simples perde o streaming de logs em tempo
real.

Para a primeira versao, isso e aceitavel se o runner devolver um JSON de erro
com `log_tail` quando falhar.

Se logs em tempo real forem necessarios depois, ha duas evolucoes possiveis:

- criar um fluxo em duas etapas, com `POST /jobs` e `GET /jobs/<id>/archive`
- manter `/extract-file` simples e adicionar `GET /jobs/<id>/logs`

## Mudancas no Docker Compose local

Como o runner pesado nao roda mais localmente, o `docling-runner` do Compose deve
ser opcional.

No `docker-compose.yml`, adicione profile ao servico:

```yaml
  docling-runner:
    profiles:
      - local-docling
    <<: *docling-image
```

Remova a dependencia obrigatoria do `docling-runner` nos servicos do Airflow:

```yaml
      docling-runner:
        condition: service_healthy
```

No `.env` local:

```env
DOCLING_RUNNER_BASE_URL=http://<IP_DO_MAC_STUDIO_NA_VPN>:8081
```

Subida local:

```bash
docker compose up -d
```

## Runner persistente no Mac Studio

O Mac Studio pode rodar o runner manualmente para testes:

```bash
cd ~/ocr-cidades/dados-desestruturados
source .venv/bin/activate
python -m docling_runtime.server
```

Para operacao, use `launchd` com um `LaunchAgent`, como descrito no documento:

```text
dados-desestruturados/documentacao/DOCLING_REMOTO_VM_SEM_DOCKER.md
```

O importante e que o `launchd` injete estas variaveis:

```text
PYTHONPATH
PROJECT_ROOT
DOCLING_RUNNER_HOST
DOCLING_RUNNER_PORT
PIPELINE_TMP_DIR
HF_HOME
```

Neste modelo, nao inclua `MINIO_*` no `launchd`, porque o Mac Studio nao precisa
acessar o MinIO.

## Ordem de implementacao recomendada

1. Criar o endpoint `/extract-file` no `docling_runtime/server.py`.
2. Fazer o endpoint salvar o PDF recebido em `$PIPELINE_TMP_DIR/jobs/<execution_id>/input`.
3. Reaproveitar `DoclingCommandBuilder` para rodar o pipeline.
4. Compactar a pasta `extraction/` em `extraction.tar.gz`.
5. Devolver o archive como resposta HTTP.
6. Criar metodo novo no `DoclingPipelineClient` para enviar PDF e receber archive.
7. Extrair o archive em `output_dir` local.
8. Ajustar `detecta_pdf_extrai_service.py` para usar o novo metodo.
9. Manter `upload_directory(output_dir)` local como esta.
10. Tornar `docling-runner` opcional no Docker Compose local.
11. Testar com um PDF pequeno antes de rodar a DAG completa.

## Implementacao realizada

Esta implementacao foi aplicada mantendo o endpoint antigo `/extract` para
compatibilidade e adicionando o novo fluxo upload/download para a DAG.

### Runner remoto

Arquivo alterado:

```text
dados-desestruturados/docling_runtime/server.py
```

Foi adicionado o endpoint:

```text
POST /extract-file
```

Comportamento implementado:

- le o PDF bruto do corpo HTTP;
- valida tamanho maximo pelo ambiente `DOCLING_RUNNER_MAX_UPLOAD_BYTES`
  (padrao: 500 MiB);
- sanitiza `X-Execution-Id` e `X-Input-Filename`;
- salva o PDF em `$PIPELINE_TMP_DIR/jobs/<execution_id>/input/`;
- executa o `docling_pipeline` usando o `DoclingCommandBuilder` existente;
- gera `$PIPELINE_TMP_DIR/jobs/<execution_id>/extraction.tar.gz`;
- devolve o archive como `application/gzip`.

Em caso de falha do pipeline, o runner devolve JSON com `status`,
`return_code`, `log_tail` e `error`.

### Client do Airflow

Arquivos alterados:

```text
dados-desestruturados/airflow/plugins/clients/http_client.py
dados-desestruturados/airflow/plugins/clients/docling_pipeline_client.py
```

Foi criado suporte a POST binario no `HttpClient` e o metodo:

```python
run_extract_file_command(...)
```

Esse metodo:

- abre o PDF local;
- envia o PDF para `/extract-file` como `application/pdf`;
- envia os flags de OCR, chart extraction e LLM por headers;
- salva o retorno em `extraction.tar.gz`;
- extrai o archive no `output_dir` local;
- valida os paths internos do `.tar.gz` antes de extrair.

### DAG 1

Arquivo alterado:

```text
dados-desestruturados/airflow/plugins/services/detecta_pdf_extrai_service.py
```

A DAG `dag_detecta_pdf_e_extrai` passou a chamar
`run_extract_file_command(...)`.

Depois que o archive e extraido em `output_dir`, o fluxo local continua igual:

```text
output_dir local preenchido
  -> upload_directory(output_dir)
  -> manifesto_execucao.json
  -> artifact_uris no MinIO local
```

### Docker Compose local

Arquivo alterado:

```text
dados-desestruturados/docker-compose.yml
```

O servico `docling-runner` agora usa o profile:

```yaml
profiles:
  - local-docling
```

As dependencias obrigatorias dos servicos do Airflow para `docling-runner`
foram removidas. Assim, o ambiente local pode subir sem executar o runtime
pesado do Docling.

Para usar o runner remoto, ajuste no `.env` local:

```env
DOCLING_RUNNER_BASE_URL=http://<IP_DO_MAC_STUDIO_NA_VPN>:8081
```

Para usar o runner local antigo, suba explicitamente o profile:

```bash
docker compose --profile local-docling up -d
```

## Teste manual do endpoint

Depois de implementar `/extract-file`, um teste manual poderia ser:

```bash
curl -X POST "http://<IP_DO_MAC_STUDIO_NA_VPN>:8081/extract-file" \
  -H "Content-Type: application/pdf" \
  -H "X-Execution-Id: teste-docling" \
  -H "X-Input-Filename: documento.pdf" \
  -H "X-Do-Ocr: true" \
  -H "X-Do-Chart-Extraction: true" \
  --data-binary "@dados-desestruturados/pdfs_testes/dados.pdf" \
  --output /tmp/extraction.tar.gz
```

Extrair localmente:

```bash
mkdir -p /tmp/extraction-test
tar -xzf /tmp/extraction.tar.gz -C /tmp/extraction-test
find /tmp/extraction-test -maxdepth 2 -type f | sort | head
```

Resultado esperado:

```text
/tmp/extraction-test/extraction/metadata.json
/tmp/extraction-test/extraction/blocks/blocks.jsonl
/tmp/extraction-test/extraction/tables/...
```

## Cuidados importantes

- Configure timeouts altos, porque Docling pode demorar muitos minutos.
- Limite tamanho maximo do PDF aceito pelo runner.
- Sanitize `execution_id` e nome do arquivo antes de criar paths.
- Nao extraia `.tar.gz` sem validar os caminhos internos.
- Limpe jobs antigos no Mac Studio periodicamente.
- Restrinja a porta `8081` para a VPN.
- Considere adicionar um token HTTP simples, por exemplo `X-Runner-Token`.

## Comparacao com a abordagem MinIO remoto

Abordagem MinIO remoto:

```text
Mac Studio acessa MinIO local
```

Vantagem:

- menos trafego direto no retorno HTTP

Desvantagem:

- exige que o Mac Studio acesse o notebook

Abordagem upload/download:

```text
Notebook envia PDF e recebe extraction.tar.gz
```

Vantagem:

- respeita a direcao de rede disponivel
- nao expoe MinIO para o Mac Studio
- deixa o notebook no controle do fluxo

Desvantagem:

- trafega o PDF e o archive pela chamada HTTP
- exige endpoint novo para upload e download de arquivo

Para o seu caso, a abordagem upload/download e a mais alinhada com a restricao:
o Mac Studio processa, mas nao inicia conexoes para o notebook.
