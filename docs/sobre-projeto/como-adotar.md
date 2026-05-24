# Como Adotar o Projeto

O uso mais simples do projeto é como pipeline local para exploração de PDFs:

```bash
python3 -m docling_pipeline docling_pipeline/dados.pdf --output-dir ./saida
```

## Quando ele é útil

- exploração inicial de relatórios institucionais;
- preparação de datasets para análise posterior;
- indexação de blocos narrativos com contexto;
- reaproveitamento de tabelas e gráficos em fluxos analíticos;
- criação de insumos para extração semântica com LLM.

## Formas de adoção

### Uso manual

Rodar um PDF por vez e inspecionar a pasta `saida/`.

### Uso em lote

Encapsular a CLI em scripts externos ou orquestração futura.

### Uso como camada intermediária

Consumir `sections`, `blocks`, `cases`, `tables` ou `text_structures` em outra aplicação.

## Estratégias de consumo por maturidade

### 1. Exploração inicial

Se o objetivo é entender um documento novo, normalmente os melhores pontos de entrada são:

- `metadata.json`
- `sections/sections.jsonl`
- `blocks/blocks.jsonl`

Esse trio dá uma boa visão do esqueleto do documento antes de mergulhar em saídas mais específicas.

### 2. Extração de indicadores

Se o objetivo é capturar KPIs e estruturas quantitativas:

- comece por `metrics/metrics.jsonl`;
- depois verifique `tables/` e `charts/`;
- por fim use `normalized_rows` quando quiser um consumo mais uniforme.

### 3. Leitura semiestruturada por capítulo

Se o documento é mais narrativo ou muito variável, `cases/cases.jsonl` costuma ser a melhor camada intermediária,
porque já consolida blocos por seção e tenta mapear pares `campo: valor`.

### 4. Extração semântica assistida

Se o foco é encontrar fatos em prosa:

- habilite `--enable-llm-text-extraction`;
- audite `text_candidates` para entender o que foi enviado ao modelo;
- consuma `text_structures` como a camada estruturada final.

## Como pensar evoluções

O projeto é especialmente adequado quando você quer evoluir em pequenas camadas:

- primeiro melhorar a árvore de seções;
- depois melhorar a classificação de blocos;
- depois especializar a extração por domínio;
- depois adicionar pós-processamentos ou exportações extras.

Essa progressão funciona bem porque o pipeline foi desenhado para reaproveitar contexto entre etapas.
