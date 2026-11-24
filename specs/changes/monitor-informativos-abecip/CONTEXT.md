# Contexto da mudança — Monitor dos informativos mensais da ABECIP

- Status: implementada e testada; DAG criada **pausada**, ainda sem execução real (ver `ACCEPTANCE.md`).
- Base: [ADR 0003](../../../docs/adr/0003-separacao-descoberta-e-extracao.md) (descoberta e extração são fluxos separados).
- Fonte: <https://www.abecip.org.br/imprensa/informativos-mensais>.

## Problema

Os PDFs da ABECIP entram no pipeline por carga manual: alguém baixa o informativo do
mês, grava em `documentos-origem/abecip/` e dispara `dag_extrai_documentos_origem`. As
construtoras já têm uma DAG que consulta o site de RI e dispara a extração
(`dag_detecta_e_baixa_pdfs_construtoras`); a ABECIP não tem equivalente.

Dois fatos do site e do MinIO moldam o desenho:

1. **O site republica.** Os nomes de arquivo ganham sufixo quando o informativo é
   refeito (`data-abecip-2026-032.pdf`, `…-051.pdf`, `…-2025-12-novo.pdf`). O mês de
   maio, por exemplo, existe no MinIO com dois conteúdos diferentes. Mês e nome de
   arquivo, portanto, não identificam um documento; o checksum identifica.
2. **Os PDFs já carregados à mão têm três layouts de pasta** (`document_id=…/`,
   `ano=…/periodo=…/document_id=…/` e `ano=…/periodo=maio/<sha16>_….pdf`). O monitor
   precisa reconhecê-los pelo checksum, sem duplicá-los.

## Objetivo

Todo mês, quando a ABECIP publicar um informativo novo, o pipeline o processa sozinho:
detecta, baixa, grava em `documentos-origem/`, dispara a extração, que dispara a
resolução (DAG 2) e, se a validação falhar, o fallback (DAG 3), sem intervenção.

## Fora de escopo

- Histórico anterior à primeira página da listagem (o site tem 175 informativos; a
  página inicial traz só os mais recentes e o resto vem por um botão "carregar mais").
- Reprocessar documentos já extraídos: continua sendo `dag_extrai_documentos_origem`
  disparada à mão, com `FORCE_EXTRACT`.
- Qualquer mudança em `dag_extrai_documentos_origem`, DAG 2, DAG 3 ou na DAG de RI das
  construtoras.
- Outras fontes além da ABECIP (a porta `DocumentSource` deixa o caminho aberto).

## Vocabulário e invariantes

- **Informativo mensal**: PDF da ABECIP com os indicadores do SBPE de um mês.
- **Período de referência**: mês a que os dados se referem, `AAAA-MM`. Sai da frase
  "Em agosto de 2026, …" da descrição; na falta dela, do nome do arquivo. Não é a data
  de publicação (o informativo de agosto sai em setembro).
- **`document_id`**: 32 primeiros caracteres hexadecimais do SHA-256 do PDF.
- **`novo`**: o checksum não existe em `documentos-origem/abecip/abecip/`.
- **`duplicado`**: o PDF já foi gravado por este monitor (mesmo diretório).
- **`duplicado_externo`**: o PDF já existe em outro layout (carga manual, portal).
- Invariante: o monitor nunca altera nem apaga um objeto que já existe.

## Riscos e dependências

- **Mudança de HTML no site**: tratada como falha (nenhum informativo reconhecido), não
  como "sem novidades".
- **Publicação fora da janela da agenda** (dias 20 a 7): disparar a DAG à mão.
- **Republicação de um mês**: conteúdo diferente vira documento novo e é reprocessado,
  com `execution_id` novo (o histórico não é sobrescrito).
- **Primeira ativação**: o PDF de junho/2026 do site (`17120b85…`) não é o que está no
  MinIO (`d34c60cc…`, uma captura "Imprimir em PDF" do Safari feita em 25/08). O texto
  é idêntico (8 páginas, 1021 palavras, zero diferenças), mas os bytes não; o monitor o
  tratará como novo e reprocessará junho uma vez.
- Depende de rede para `www.abecip.org.br`, do MinIO e do runner do Docling (Mac Studio)
  ligados na hora da extração.
