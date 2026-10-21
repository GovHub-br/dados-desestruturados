# Decisões — Monitor dos informativos mensais da ABECIP

## D1 — Sem estado: "já visto" é "já existe no MinIO"

A alternativa era guardar um registro de URLs vistas (arquivo no MinIO ou variável do
Airflow) para evitar baixar de novo. Descartada: o registro não conheceria os PDFs
carregados à mão, a ABECIP republica sob o mesmo mês, e um registro dessincronizado
falharia em silêncio, perdendo um lançamento. Baixar tudo e comparar o checksum custa
~10 MB por execução, em até 19 execuções por mês (~190 MB), e nunca erra. Se o volume
passar a incomodar, o caminho é um `HEAD` com `Last-Modified`, não um registro.

## D2 — Um diretório por documento (`document_id=`)

A DAG de RI das construtoras grava `ano=/periodo=/<arquivo>.pdf` e um único
`documento_detectado.json` por período. Se o mês é republicado, o segundo manifesto
sobrescreve o primeiro e `dag_extrai_documentos_origem` enxerga os dois PDFs sob o mesmo
manifesto. Na ABECIP isso já aconteceu (maio tem duas versões). Com `document_id=` no
caminho cada versão tem seu manifesto e a extração recebe exatamente um PDF.

## D3 — `FORCE_EXTRACT` não vale para o monitor

O `.env` local tem `FORCE_EXTRACT=true`. A DAG de RI das construtoras o respeita porque
roda em poucos meses e ele serve para reextrair. Um monitor que roda até 19 vezes por mês
e o respeitasse reextrairia todos os informativos a cada execução, e cada extração
dispara a DAG 2 e, se falhar a validação, o fallback com LLM. Reprocessar continua
possível, de propósito, em `dag_extrai_documentos_origem`.

## D4 — Caso de uso novo em vez de mudar `download_and_persist_pdfs`

Ele fixa o domínio em `MINIO_DOCUMENT_PREFIX` (`documentos-origem/construtoras`), grava
um manifesto por período e sobrescreve o manifesto de duplicados. Corrigir os três
pontos mexeria no fluxo das construtoras, cujos experimentos dependem de comportamento
estável. O caso de uso novo reaproveita os auxiliares do mixin e deixa o existente como está.

## D5 — `duplicado_externo` não é extraído

Um PDF com o mesmo checksum de uma carga manual é o mesmo documento: reextraí-lo geraria
uma execução redundante, DAG 2 incluída. Se ele não tiver extração, o monitor só avisa
no log e indica `dag_extrai_documentos_origem`. Já o `duplicado` do próprio monitor sem
extração **volta para a fila** a cada execução, porque a causa provável é uma falha
transitória (runner desligado) e o mês não pode ficar sem processar.

## D6 — Só a primeira página da listagem

O site entrega os 8 mais recentes no HTML e o resto por um POST em
`livros_load_more_noticias`. Um lançamento novo sempre aparece no topo; paginar só serviria
para carga histórica, que é outro trabalho (e o parser já serve para as respostas dessa chamada).

## D7 — Agenda por janela de dias, não diária nem mensal

Datas de publicação observadas em 2026: 4/3, 31/3, 23/4, 28/5, 30/6, 28/7, 26/8 e 30/9. A
janela dos dias 20 a 7 cobre todas com folga e poupa ~12 execuções por mês em relação a
uma agenda diária. Uma execução mensal fixa perderia lançamentos fora do dia escolhido.

## D8 — Sem ADR novo

A decisão estrutural (descoberta separada da extração, idempotência pelo checksum do
documento de origem) já está no [ADR 0003](../../../docs/adr/0003-separacao-descoberta-e-extracao.md).
Esta mudança é uma segunda fonte de aquisição sobre a mesma fronteira.
