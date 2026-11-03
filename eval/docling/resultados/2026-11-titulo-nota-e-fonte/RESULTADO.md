# Resultado da reextração no Mac Studio: título de tabela não vem de nota de rodapé nem de outro bloco

- Data: 2026-11-02
- Código testado: branch `fix/docling-titulo-nota-e-fonte`, commit `0592726`, runner do Mac Studio nesse commit
  (atualizado com `atualizar-runner.sh fix/docling-titulo-nota-e-fonte`; `/healthz` ok).
- Referência: as extrações feitas com o código da `main` (PR #18): os 10 meses da ABECIP reextraídos em 21/10 (MinIO) e a
  amostra padrão em `extracoes/novo/` (20/10).
- Escopo: amostra padrão (15 PDFs) + os 11 PDFs da ABECIP no MinIO; 25 extrações (maio está nas duas listas), 25 de 25 sem
  falha. 24 comparadas (o `abecip_maio`, PDF antigo, não tem extração de referência com o código da `main`).
- Detalhe PDF a PDF: [comparacao_extracoes.md](comparacao_extracoes.md).

## Veredito

**Aprovado, sem efeito colateral.** De 289 tabelas comparadas, muda **1**, e só o título: ABECIP 2025-10, `table004`,
`**(Depositos-Retiradas)` -> `Table 4`. Linhas, cabeçalhos, seções, blocos, métricas e gráficos idênticos em todos os 24 PDFs,
inclusive o controle de cobertura (Gerdau) e o caso das três tabelas empilhadas (ABECIP maio, p. 8).

## O problema (ABECIP out/2025, página 5)

A página é imagem lida por OCR. O título "2 - SBPE: FINANCIAMENTOS IMOBILIÁRIOS - NÚMERO DE UNIDADES E VALORES CONTRATADOS" está
na página, mas o modelo de layout do Docling não o detectou: não virou seção, bloco nem texto em nenhum artefato. Acima da tabela 2
ficaram a nota da tabela 1 ("**(Depositos-Retiradas)") e a linha "Fontes: Abecip e Banco Central", e a regra do título mais próximo
acima (PR #18) deu a nota como título. Nos outros 9 meses o título foi detectado; na amostra padrão nenhuma tabela tinha nota como
título. Efeito no fallback: a seleção de artefatos leu o nome, descartou a tabela de financiamentos e a série mensal saiu da tabela
de poupança (lote 16 do registro de releases).

## O que mudou (só a regra `closest_above` de título de tabela)

- texto que começa como nota ou fonte (`*`, `(*`, sobrescrito, `Fonte:`, `Nota:`, `Obs.:`) não é título de tabela;
- uma linha `Fonte(s): ...` entre o título candidato e a tabela fecha o bloco da tabela de cima, e o título de cima não é herdado;
- se tudo o que havia acima foi descartado por isso, a tabela fica sem título (`Table N`).

Antes de ir ao runner, a regra foi simulada sobre as extrações existentes (301 tabelas): só barrar a nota fazia a tabela 2 herdar o
título da tabela 1, e barrar "título acima de outra tabela" tirava o título de 6 tabelas boas da amostra (ex.: balanço dividido em
duas tabelas sob um só título). A combinação nota + linha de fonte mudou só a tabela de 2025-10, o que o runner confirmou.

## Limite

O título verdadeiro não é recuperado: a tabela fica sem título, com os cabeçalhos das colunas ("Numero de Unidades",
"R$ Milhoes Contratados") como sinal. Recuperar o título exigiria ler por OCR a faixa entre as duas tabelas. Se isso basta para a
seleção de artefatos do fallback escolher a tabela certa é medido no pipeline (DAG 1 + DAG 3), não aqui.
