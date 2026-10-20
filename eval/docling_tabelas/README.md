# Validação do `docling_pipeline`: título por tabela e fusão de tabelas

Ferramentas, linhas de base e variantes da mudança descrita em
[specs/changes/docling-titulo-tabela-e-fusao/](../../specs/changes/docling-titulo-tabela-e-fusao/CONTEXT.md).

Os scripts **reexecutam o código real** de `docling_pipeline/extractors/` sobre extrações já
gravadas (replay). Não precisam do Docling, só de `pandas` e `pydantic`. Os dados em que se
apoiam (`resultados_construtoras/`, `airflow/state/resolution_inputs/`) são locais e estão no
`.gitignore`; por isso as linhas de base estão versionadas em `dados/`.

## Como repetir

```bash
python -m venv /tmp/venv-diag && /tmp/venv-diag/bin/pip install pandas pydantic
PY=/tmp/venv-diag/bin/python

# código antigo (main antes da correção) exportado do git, sem tocar na árvore de trabalho
mkdir -p /tmp/codigo_antigo && git archive c017c16 docling_pipeline | tar -x -C /tmp/codigo_antigo

# cada script recebe a pasta que CONTÉM docling_pipeline/: antigo = /tmp/codigo_antigo, novo = .
$PY eval/docling_tabelas/scripts/abecip_meses.py /tmp/codigo_antigo   # reproduz as 7 fusões
$PY eval/docling_tabelas/scripts/abecip_meses.py .                    # 3 tabelas por mês
$PY eval/docling_tabelas/scripts/gerdau_vale.py /tmp/codigo_antigo
$PY eval/docling_tabelas/scripts/gerdau_vale.py .
```

Regra de leitura: o código **antigo** precisa reproduzir o defeito gravado (é o que valida o
método). Só então a saída do código novo vale como evidência.

## Pastas

| Pasta | Conteúdo |
| --- | --- |
| `scripts/` | Validações ativas. `harness_abecip_pag8.py` (página 8, jun/2026), `abecip_meses.py` (todos os meses fundidos), `gerdau_vale.py` (cabeçalho trocado fora da ABECIP), `replay_corpus_secoes.py <código> <saída.json>` (título de todas as tabelas de item único do corpus), `replay_propagacao_cabecalho.py <código> <saída.json>` (cabeçalhos trocados no corpus), `prova_composicao_table_id.py` (prova que a tabela fundida é a soma dos itens 97, 99 e 101) |
| `dados/baseline/` | Saída do código antigo (`c017c16`) sobre o corpus: `secoes_*` e `propagacao_*`. Comparar a saída nova com estes arquivos |
| `dados/variantes/` | Saída de cada protótipo testado, inclusive os descartados (nome termina em `_descartada`) |
| `patches/` | Diffs dos protótipos sobre `c017c16`. O código definitivo é o da branch; os patches registram como as variantes diferiam |
| `historico/` | Scripts do diagnóstico, só para registro. `dependencia_largura_inconclusivo.py` não distingue propagação legítima de coincidência e **não** sustenta nenhuma conclusão |

## Comparar saídas de `replay_*`

```bash
$PY eval/docling_tabelas/scripts/replay_corpus_secoes.py . /tmp/secoes_novo.json
# comparar /tmp/secoes_novo.json com dados/baseline/secoes_codigo_c017c16.json:
# campo "replay" = título atribuído; "idx" nulo = tabela fundida (fora da comparação)
```

## Reextração real no Mac Studio (etapas 5 e 6)

Rodam no contêiner `ocr_airflow_scheduler`, que tem o cliente do MinIO, o `PYTHONPATH` do
projeto e a rota até o runner; o repositório é montado nele, então a saída cai em
`eval/docling_tabelas/extracoes/` (no `.gitignore`: é grande e se reproduz com os scripts).
Nada é gravado no MinIO e o Airflow não é acionado, então DAG 2 e DAG 3 não rodam.

```bash
S=/opt/project/dados-desestruturados/eval/docling_tabelas/scripts

# extração antiga mais recente de cada PDF (só leitura no MinIO) -> extracoes/antigo/
docker exec ocr_airflow_scheduler python $S/baixar_extracoes_antigas.py

# envia os PDFs de documentos-origem/ ao runner (mesmo POST /extract-file e mesmas flags da DAG)
# --dry-run só lista e testa o /healthz; --filtro abecip limita; é retomável
docker exec ocr_airflow_scheduler python $S/extrair_lote_runner.py --rotulo novo --dry-run
docker exec -d ocr_airflow_scheduler sh -c "python $S/extrair_lote_runner.py --rotulo novo > /opt/project/dados-desestruturados/eval/docling_tabelas/extracoes/novo.log 2>&1"
```

`--rotulo` é o nome da pasta de saída: `novo` (runner na branch), `controle` (runner no `main`).

```bash
# compara extracoes/antigo × extracoes/novo e escreve comparacao_extracoes.md (só biblioteca padrão)
python3 eval/docling_tabelas/scripts/comparar_extracoes.py
```

O comparador pareia as tabelas pelo conteúdo e inclui uma prova de que nenhuma linha de dados
foi perdida ou inventada; se a mudança é melhor ou pior se decide abrindo o PDF. O resultado da
reextração de 2026-10-20 está em [RESULTADO_REEXTRACAO.md](RESULTADO_REEXTRACAO.md).

## Resultados da validação offline (2026-10-19)

- ABECIP: 7 de 7 meses fundidos viram 3 tabelas com título e cabeçalho certos.
- Gerdau (1) e Vale (4): cabeçalho verdadeiro mantido; o código antigo reproduz o defeito.
- Corpus: 0 de 322 cabeçalhos trocados. Título muda em 92 de 291 tabelas de item único
  (50 fora da ABECIP); 30 dessas 50 foram inspecionadas pelo conteúdo: 24 melhores, 5
  neutras, 0 piores.
- A reextração real no Mac Studio e a comparação com o MinIO estão no
  [ACCEPTANCE.md](../../specs/changes/docling-titulo-tabela-e-fusao/ACCEPTANCE.md).
