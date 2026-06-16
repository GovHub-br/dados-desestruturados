# Patches hardcoded da `.venv-chart` para `do_chart_extraction`

Este documento registra as alteracoes manuais encontradas dentro do ambiente virtual:

```text
dados-desestruturados/.venv-chart
```

Essas alteracoes explicam por que a extracao com `--do-chart-extraction` funcionou nesse ambiente, mas pode falhar em outra maquina mesmo usando os mesmos `requirements`.

## Resumo

Foram encontrados patches diretos em dois pacotes instalados:

```text
transformers
docling
```

No `transformers`, os arquivos alterados foram detectados por divergencia de hash no `RECORD` do pacote:

```text
transformers/masking_utils.py
transformers/models/rt_detr_v2/modeling_rt_detr_v2.py
```

No `docling`, o pacote instalado nao registra todos os arquivos no `RECORD`, entao a deteccao por hash nao denuncia as mudancas. Mesmo assim, a comparacao com o clone local mostrou alteracoes em:

```text
docling/models/stages/chart_extraction/granite_vision.py
docling/models/stages/table_structure/table_structure_model_granite_vision.py
```

## Por que os requirements nao bastam

O `requirements.txt` fixa as versoes principais:

```text
docling[vlm]==2.95.0
docling-ibm-models==3.13.2
docling-core==2.77.0
transformers==5.9.0
peft==0.19.1
accelerate==1.13.0
torch==2.12.0
torchvision==0.27.0
```

Isso instala as mesmas versoes, mas nao reaplica os patches manuais feitos dentro da `.venv-chart`.

Em outra maquina, depois de instalar as dependencias, ainda sera necessario aplicar os ajustes abaixo ou usar uma versao empacotada/local do Docling ja corrigida.

## Patch 1: RT-DETR v2 no MPS

Arquivo no ambiente virtual:

```text
<venv>/lib/pythonX.Y/site-packages/transformers/models/rt_detr_v2/modeling_rt_detr_v2.py
```

Funcao:

```python
build_2d_sinusoidal_position_embedding(...)
```

Problema:

O RT-DETR v2 cria tensores `float64` diretamente no device. Em Apple Silicon, quando o device e `mps`, o PyTorch falha porque MPS nao suporta `float64`.

Erro relacionado:

```text
TypeError: Cannot convert a MPS Tensor to float64 dtype as the MPS framework doesn't support float64.
```

Alteracao encontrada:

```python
device_type = torch.device(device).type if device is not None else None
arange_dtype = torch.float32 if device_type == "mps" else torch.float64

omega = torch.arange(pos_dim, dtype=arange_dtype, device=device) / pos_dim
omega = 1.0 / temperature**omega

grid_h = torch.arange(height, dtype=arange_dtype, device=device)
grid_w = torch.arange(width, dtype=arange_dtype, device=device)
grid_h, grid_w = torch.meshgrid(grid_h, grid_w, indexing="ij")
```

Recomendacao ao reproduzir:

Tambem trocar o dtype do `cls_token` para `arange_dtype`, para evitar outro ponto de `float64` caso esse caminho seja usado:

```python
if cls_token:
    pos_embed = torch.cat(
        [
            torch.zeros(
                1,
                embed_dim,
                dtype=arange_dtype,
                device=device,
            ),
            pos_embed,
        ],
        dim=0,
    )
```

Na `.venv-chart`, o trecho principal dos `arange` ja estava corrigido. A linha do `cls_token` ainda aparecia com `torch.float64`, mas provavelmente esse caminho nao foi acionado durante a validacao local.

## Patch 2: `cache_position` em `transformers.masking_utils`

Arquivo no ambiente virtual:

```text
<venv>/lib/pythonX.Y/site-packages/transformers/masking_utils.py
```

Funcao:

```python
create_causal_mask(...)
```

Problema:

O modelo Granite Vision pode chamar `create_causal_mask` passando o argumento `cache_position`. Na versao instalada do `transformers`, a documentacao interna mencionava esse argumento como depreciado e nao usado, mas a assinatura da funcao nao aceitava o parametro. Isso causava erro durante a geracao.

Erro relacionado:

```text
TypeError: create_causal_mask() got an unexpected keyword argument 'cache_position'
```

Alteracao encontrada:

```python
def create_causal_mask(
    config: PreTrainedConfig,
    inputs_embeds: torch.Tensor,
    attention_mask: torch.Tensor | None,
    past_key_values: Cache | None,
    cache_position: torch.Tensor | None = None,
    position_ids: torch.Tensor | None = None,
    or_mask_function: Callable | None = None,
    and_mask_function: Callable | None = None,
    block_sequence_ids: torch.Tensor | None = None,
) -> torch.Tensor | BlockMask | None:
```

O ponto central e aceitar `cache_position` e nao usa-lo. Isso mantem compatibilidade com chamadas de modelos que enviam esse argumento.

## Patch 3: MPS no chart extraction Granite Vision

Arquivo no ambiente virtual:

```text
<venv>/lib/pythonX.Y/site-packages/docling/models/stages/chart_extraction/granite_vision.py
```

Problemas tratados:

- permitir que o chart extraction use `mps`;
- reduzir o batch size em `mps`;
- limitar valores sentinela muito altos de `tokenizer.model_max_length`;
- adicionar diagnosticos opcionais para depuracao.

### 3.1. Permitir MPS

Na chamada de `decide_device`, a lista de devices suportados deve incluir `AcceleratorDevice.MPS`:

```python
self.device = decide_device(
    accelerator_options.device,
    supported_devices=[
        AcceleratorDevice.CPU,
        AcceleratorDevice.CUDA,
        AcceleratorDevice.MPS,
    ],
)
```

### 3.2. Reduzir batch no MPS

Alteracao encontrada:

```python
if self.device == "mps":
    self.elements_batch_size = 1
```

Isso torna a execucao mais conservadora no backend MPS.

### 3.3. Limitar `model_max_length`

Funcao adicionada:

```python
def _safe_model_max_length(raw_value: Any, default: int = 1024) -> int:
    """Clamp tokenizer sentinel values before using them as generation limits."""
    try:
        value = int(raw_value)
    except (TypeError, ValueError, OverflowError):
        return default
    if value <= 0 or value > default:
        return default
    return value
```

Uso:

```python
self._model_max_length = _safe_model_max_length(
    self._processor.tokenizer.model_max_length
)
```

Motivo:

Alguns tokenizers retornam valores sentinela enormes em `model_max_length`. Usar esse valor diretamente em `max_new_tokens` pode quebrar a geracao ou tornar a execucao impraticavel.

### 3.4. Diagnosticos opcionais

A `.venv-chart` tambem tinha prints condicionados por:

```text
DOCLING_INTERNAL_DIAGNOSTICS=1
```

Eles ajudam a ver quando o processor e o generate comecam e terminam. Esses diagnosticos nao sao essenciais para corrigir a falha, mas ajudam a depurar travamentos.

## Patch 4: MPS no table structure Granite Vision

Arquivo no ambiente virtual:

```text
<venv>/lib/pythonX.Y/site-packages/docling/models/stages/table_structure/table_structure_model_granite_vision.py
```

Problemas tratados:

- permitir `mps` no modelo de estrutura de tabela com Granite Vision;
- limitar valores sentinela muito altos de `tokenizer.model_max_length`;
- adicionar diagnosticos opcionais.

### 4.1. Permitir MPS

Na chamada de `decide_device`, incluir `AcceleratorDevice.MPS`:

```python
self.device = decide_device(
    accelerator_options.device,
    supported_devices=[
        AcceleratorDevice.CPU,
        AcceleratorDevice.CUDA,
        AcceleratorDevice.MPS,
    ],
)
```

### 4.2. Limitar `model_max_length`

Funcao adicionada:

```python
def _safe_model_max_length(raw_value: Any, default: int = 4096) -> int:
    """Clamp tokenizer sentinel values before using them as generation limits."""
    try:
        value = int(raw_value)
    except (TypeError, ValueError, OverflowError):
        return default
    if value <= 0 or value > default:
        return default
    return value
```

Uso:

```python
self._model_max_length = _safe_model_max_length(
    self._processor.tokenizer.model_max_length
)
```

## Como verificar se a nova maquina esta com os patches

Depois de aplicar os ajustes, rode estes comandos apontando para o novo ambiente virtual.

### Verificar RT-DETR

```bash
rg -n "arange_dtype|device_type == \"mps\"|torch.float64" \
  <venv>/lib/pythonX.Y/site-packages/transformers/models/rt_detr_v2/modeling_rt_detr_v2.py
```

O arquivo deve conter:

```python
arange_dtype = torch.float32 if device_type == "mps" else torch.float64
```

### Verificar `cache_position`

```bash
rg -n "cache_position" \
  <venv>/lib/pythonX.Y/site-packages/transformers/masking_utils.py
```

A assinatura de `create_causal_mask` deve aceitar:

```python
cache_position: torch.Tensor | None = None
```

### Verificar MPS no Granite Vision

```bash
rg -n "AcceleratorDevice.MPS|elements_batch_size|_safe_model_max_length" \
  <venv>/lib/pythonX.Y/site-packages/docling/models/stages/chart_extraction/granite_vision.py \
  <venv>/lib/pythonX.Y/site-packages/docling/models/stages/table_structure/table_structure_model_granite_vision.py
```

O chart extraction deve conter:

```python
AcceleratorDevice.MPS
if self.device == "mps":
    self.elements_batch_size = 1
```

Os dois arquivos Granite devem conter `_safe_model_max_length`.

## Ordem recomendada para reproduzir em outra maquina

1. Criar e ativar o ambiente virtual.
2. Instalar as dependencias do `requirements.txt`.
3. Confirmar as versoes instaladas de `docling`, `transformers`, `torch`, `peft` e `accelerate`.
4. Aplicar os patches acima nos arquivos dentro de `site-packages`.
5. Rodar um teste pequeno com `DOCLING_DEVICE=mps` e `--do-chart-extraction`.
6. Se ainda falhar, rodar com `DOCLING_INTERNAL_DIAGNOSTICS=1` para ver em qual etapa o pipeline parou.

## Observacao sobre a solucao elegante

No clone local do Docling em:

```text
docling/
```

ha uma solucao mais elegante documentada em:

```text
docling/ISSUE_3483_EXPLICACAO_SOLUCAO_PT_BR.md
docling/ISSUE_3483_MPS_RT_DETR_FLOAT64_FIX.md
```

Essa solucao cria um patch no lado do Docling para evitar mexer diretamente no `transformers`. Ja a `.venv-chart` funcionou porque recebeu patches hardcoded diretamente nos arquivos instalados.

Para reproducao rapida em outra maquina, os patches hardcoded acima sao o caminho mais direto. Para manter o projeto no longo prazo, o ideal e transformar essas mudancas em pacote, fork ou patch automatizado versionado, evitando edicao manual invisivel dentro de ambiente virtual.
