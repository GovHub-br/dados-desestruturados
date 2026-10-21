# Medir mudanças no Docling (antes × depois)

Protocolo e ferramentas para decidir se uma mudança em `docling_pipeline/`, `docling_runtime/`,
na versão do Docling ou nos patches de GPU **melhora ou piora** as extrações. Foi criado na
mudança [docling-titulo-tabela-e-fusao](../../specs/changes/docling-titulo-tabela-e-fusao/CONTEXT.md);
o resultado dela está em [resultados/2026-10-titulo-tabela-fusao/](resultados/2026-10-titulo-tabela-fusao/RESULTADO.md).
Problemas conhecidos e ainda sem tratamento: [PENDENCIAS.md](PENDENCIAS.md).

Repita este protocolo a cada mudança no Docling, com a mesma amostra, para os resultados serem comparáveis.

## Protocolo

Os scripts rodam no contêiner do Airflow (`ocr_airflow_scheduler`, que tem o cliente do MinIO, o
`PYTHONPATH` do projeto e a rota até o runner). O repositório é montado nele, então a saída cai em
`eval/docling/extracoes/` (fora do git). **Nada é gravado no MinIO e o Airflow não é acionado**, então
a DAG de resolução e a de fallback não rodam.

```bash
S=/opt/project/dados-desestruturados/eval/docling/scripts
```

1. **Referência.** Baixe do MinIO a extração mais recente de cada PDF (só leitura):
   `docker exec ocr_airflow_scheduler python $S/baixar_extracoes_antigas.py` → `extracoes/antigo/`.
2. **Runner na versão a testar.** No Mac Studio:
   `~/docling-runner/repo/infra/docling-runner/macos/atualizar-runner.sh <branch>`. Confira
   `git -C ~/docling-runner/repo rev-parse --short HEAD` e `curl -s http://127.0.0.1:8081/healthz`
   (no zsh, sem comentário na mesma linha). Não dê push nessa branch durante o teste: cada push chega
   ao runner em até 15 min e o reinicia.
3. **Extrair a amostra padrão** ([amostra_padrao.txt](amostra_padrao.txt): 1 PDF por empresa, 15 PDFs, ~50 min):
   `docker exec -d ocr_airflow_scheduler sh -c "python $S/extrair_lote_runner.py --rotulo novo --amostra > /opt/project/dados-desestruturados/eval/docling/extracoes/novo.log 2>&1"`.
   Retomável; `--dry-run` só lista os PDFs e tenta o `/healthz` (se o runner estiver inacessível, avisa e segue; numa extração real, falha antes de enviar qualquer coisa); `--filtro` limita a PDFs específicos. Use
   `caffeinate` na máquina que dispara. Mesmas flags da DAG (OCR, gráficos, texto por LLM).
4. **Comparar** (só biblioteca padrão):
   `python3 eval/docling/scripts/comparar_extracoes.py` → `extracoes/comparacao_antigo_vs_novo.md`
   (tabelas pareadas pelo conteúdo, com a prova de que nenhuma linha de dados foi perdida ou inventada) e
   `python3 eval/docling/scripts/analisar_cobertura.py --rotulo novo --saida <arquivo>` (números do PDF × números extraídos, por página).
5. **Julgar abrindo o PDF.** Cada diferença é *melhor*, *neutra* ou *pior*. Os relatórios mostram onde olhar; não decidem.
6. **Registrar** em `resultados/<aaaa-mm>-<id>/` (RESULTADO.md e os relatórios que valham) e atualizar
   [PENDENCIAS.md](PENDENCIAS.md). Se algo for pior, a mudança é revista.
7. **Devolver o runner** com `atualizar-runner.sh main` e conferir branch, hash e `/healthz`. O runner não volta sozinho.

## Regras que valem sempre

- **O critério é o conteúdo extraído contra o PDF.** Layout signature e regras determinísticas existentes
  foram escritos sobre a extração antiga: se uma extração melhor não casa com eles, o defeito é do
  signature, não da extração. Nenhuma exigência de "igual à antiga" além da prova de dados.
- **Dados preservados:** toda linha de dados do antes existe no depois (como dado ou, se era o cabeçalho
  verdadeiro, como cabeçalho) e vice-versa. Artefatos fora de tabelas (`sections`, `blocks`, `metrics`,
  `cases`, `text_candidates`, nº de gráficos) devem ser iguais quando a mudança só mexe em tabelas.
- **Controle em `main`:** se houver diferença que o código não explique (artefatos fora de tabelas, ou
  dúvida de ambiente/bibliotecas), repita os PDFs com o runner no `main`, na mesma máquina.
- **Teste de controle do analisador:** a Gerdau (p. 21, 24 e 25) tem perdas conhecidas e precisa ser
  acusada. Se não for, o método quebrou.

## Armadilhas já encontradas

- Os gráficos guardam o valor como inteiro puro (`1072`, não `1.072`): compare por dígitos.
- Páginas de prosa numérica, capas, divisores e gráficos geram "ausentes" que não são tabela: confirme no PDF.
- O primeiro dado de uma tabela às vezes vira o `schema`; o analisador conta o cabeçalho.
- Ponto cego: tabela em imagem sem camada de texto não é medida por número (a CSN p. 3 foi coletada por OCR).
- O número de página guardado na tabela é o da página inicial; tabelas que atravessam páginas precisam de tolerância.

## Conteúdo

| Caminho | O que é |
| --- | --- |
| `scripts/` | `baixar_extracoes_antigas.py`, `extrair_lote_runner.py`, `comparar_extracoes.py`, `analisar_cobertura.py` e `_lote.py` (comum aos de lote) |
| `amostra_padrao.txt` | Os 15 PDFs da amostra padrão (um filtro por linha) |
| `PENDENCIAS.md` | Problemas conhecidos do `docling_pipeline`, com onde, evidência e hipótese |
| `resultados/` | Um registro por medição (`<aaaa-mm>-<id>/`) |
| `extracoes/` | Dados brutos (`antigo/`, `novo/`, `pdfs/`); **fora do git**, reproduzíveis pelos scripts |

Os scripts de reprodução offline e os protótipos da primeira medição foram arquivados na tag
`arquivo/docling-titulo-evidencias` (`git show arquivo/docling-titulo-evidencias:eval/docling_tabelas/README.md`).
