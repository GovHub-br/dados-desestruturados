# Fluxo da Pipeline

## Ponto de entrada

O ponto de entrada público é:

```bash
python3 -m docling_pipeline ...
```

Internamente isso chama `docling_pipeline.__main__`, que delega para `cli.main()`.

## O que `main()` realmente faz

O fluxo é propositalmente curto:

1. ler argumentos e ambiente;
2. executar `run_pipeline(config)`;
3. persistir tudo com `persist_bundle(bundle, output_dir)`.

Esse ponto de entrada é enxuto porque toda a inteligência foi empurrada para módulos especializados.

## Bundle final

Toda a execução converge para um `PipelineBundle`, que reúne:

- `document`
- `sections`
- `metrics`
- `tables`
- `charts`
- `normalized_rows`
- `blocks`
- `cases`
- `text_candidates`
- `text_structures`
- `semantic_markdown`

Na prática, o bundle funciona como um snapshot completo da interpretação do documento.
Se fosse necessário trocar a persistência por outro backend, o bundle já seria uma boa fronteira de integração.

## Conversão base e assistências opcionais

### Conversão padrão

Usa o conversor estruturado principal do Docling.

É essa conversão que alimenta quase toda a pipeline.

### VLM remoto opcional

Se `enable_remote_vlm_assist` estiver ativo, a pipeline roda uma segunda conversão remota
e tenta salvar `semantic_markdown.md`.

### LLM textual opcional

Se `enable_llm_text_extraction` estiver ativo, a pipeline monta trechos candidatos e pede ao modelo
uma resposta JSON com fatos e resumo narrativo.

## Sequenciamento das etapas

### `extract_sections`

Cria a árvore leve das seções.

### `extract_blocks`

Cria a malha textual e já começa a associar contexto.

### `extract_cases`

Consolida o material textual por seção.

### `extract_metrics`

Busca indicadores curtos diretamente no texto.

### `extract_tables`

Extrai tabelas e já gera linhas normalizadas.

### `extract_charts`

Tenta extrair gráficos nativos.

### `extract_table_derived_charts`

Entra em ação quando os gráficos nativos não aparecem ou não são suficientes.

### `extract_text_candidates`

Seleciona trechos textuais promissores.

### `extract_text_structures`

Transforma esses trechos em fatos estruturados com a LLM.

## Critério de fallback importante

O fallback para gráficos derivados de tabela é uma decisão arquitetural forte:
ele reconhece que, em muitos relatórios, a informação do gráfico existe no documento,
mas não está exposta pelo parser como um gráfico nativo consumível.
