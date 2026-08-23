# Plano: Portal com Rastreabilidade Visual do Dado no PDF

## Objetivo

Permitir que uma pessoa abra o resultado final de uma execução no portal,
consulte o `schema_saida_resolvido.json` e, ao selecionar um valor, veja no PDF
original a evidência que originou aquele dado. A interface deve abrir a página
correta e desenhar uma marcação vermelha sobre a área efetivamente usada na
resolução.

O objetivo não é apenas exibir o PDF: é conectar, de forma auditável, o valor
resolvido, o mapeamento da layout signature, o artefato de extração e a região
visual do documento de origem.

## Diagnóstico técnico do portal atual

### Pontos positivos

- O portal já é uma aplicação FastAPI simples e tem o MinIO como fonte dos
  artefatos, em vez de duplicar PDFs e resultados em outro banco.
- O envio de documentos preserva o original em um caminho estável no MinIO e
  dispara o Airflow pelo backend, sem expor a credencial do Airflow ao navegador.
- Já há uma tela de rastreabilidade e uma API de acompanhamento da execução,
  baseada no manifesto e nos artefatos persistidos.
- O contrato é tratado como uma entidade versionada, e o fluxo já carrega
  domínio, entidade, `document_id` e `execution_id`: são os identificadores
  necessários para abrir o resultado correto.

### Limitações atuais

- O portal está concentrado em um único arquivo, `portal/app.py`: rotas FastAPI,
  acesso ao MinIO e Airflow, HTML, CSS e JavaScript convivem no mesmo módulo.
  Isso é adequado para o protótipo, mas torna arriscado acrescentar uma tela de
  resultado complexa e um visualizador de PDF.
- A rota de detalhe da execução devolve somente o manifesto e uma lista plana de
  chaves de artefatos. Ela ainda não identifica e entrega explicitamente o
  schema resolvido, a auditoria, a validação e o PDF original.
- O HTML contém JavaScript grande em linha. Há inclusive mais de uma atribuição
  a `form.onsubmit`, o que torna a ordem de comportamento difícil de manter.
- Não há testes próprios do portal nem modelos tipados para as respostas das
  APIs de execução.
- O cache do rastreamento é local ao processo. Isso é aceitável no Docker local,
  mas em produção com mais de uma réplica deverá ser substituído por cache
  compartilhado ou eliminado em favor de consultas idempotentes ao MinIO.
- A autenticação atual é um token Bearer opcional. Em produção será necessário
  SSO/proxy corporativo e autorização por domínio, entidade ou execução.

### Recomendação de organização

Não é necessário reescrever o portal como uma SPA agora. A evolução mínima e
segura é manter FastAPI, mas separar responsabilidades:

```text
portal/
  app.py                         # criação da aplicação e inclusão de rotas
  routers/
    documents.py                 # upload e disparo
    contracts.py                 # contratos e domínios
    executions.py                # status, resultado e PDF
  services/
    execution_locator.py         # localiza os artefatos corretos da execução
    provenance_service.py        # normaliza evidência visual
    airflow_gateway.py
  repositories/
    minio_repository.py
  models/
    api.py                       # modelos Pydantic das respostas
  static/
    portal.css
    portal.js
    result-viewer.js
```

Essa estrutura permite evoluir o visualizador isoladamente, sem mudar o fluxo
de upload já estabilizado. A tela deve manter controles nativos acessíveis,
foco visível, navegação por teclado e foco que não fique oculto pelo painel de
PDF ou por modais.

## O que já existe para produzir a evidência

O pipeline já preserva parte importante da proveniência:

1. O `manifesto_execucao.json` guarda o `input_pdf_uri` do PDF original.
2. A `layout_signature` indica o artefato e o seletor usados, por exemplo
   `tables/table002.json`, linha e coluna.
3. O `auditoria_resolucao.json` registra, para cada mapeamento, o
   `campo_saida`, status, valor bruto, valor normalizado e evidências como
   arquivo de origem, página, índices de linha/coluna e metadados da tabela.
4. Os artefatos de blocos, métricas, seções e tabelas já possuem `bbox` em
   vários casos. A origem de coordenadas normalmente é preservada como
   `coord_origin`, por exemplo `BOTTOMLEFT`.

Contudo, hoje o `TableCellRecord` armazena somente `row_index`, `column_index`
e `value_raw`. A tabela inteira possui bbox, mas a célula individual não.
Logo, a aplicação pode destacar com precisão um bloco textual ou uma tabela
inteira, mas ainda não pode afirmar que um retângulo corresponde exatamente à
célula selecionada.

Não devemos estimar uma célula dividindo proporcionalmente a área da tabela:
tabelas podem ter células mescladas, cabeçalhos em múltiplas linhas, larguras
variáveis e quebra entre páginas. Isso produziria uma visualização bonita, mas
enganosa.

## Princípios de implementação

- A evidência visual é derivada de artefatos persistidos; não é inferida pelo
  navegador a partir do texto ou do valor exibido.
- O portal jamais associa uma ocorrência pelo texto do valor sozinho. Valores
  repetidos são comuns; a associação precisa usar um identificador estrutural
  persistido na auditoria.
- A UI deve declarar o nível de precisão: `célula`, `bloco`, `tabela`,
  `intervalo lógico` ou `sem localização visual`.
- Um campo sem bbox não é erro. Valores fixos, derivados e metadados de
  manifesto não têm, necessariamente, uma posição no PDF.
- Nenhuma URL assinada permanente, credencial MinIO ou caminho interno sensível
  deve ir para o navegador. O PDF é entregue por endpoint autenticado do portal.
- A solução deve ser genérica para documentos de qualquer domínio, sem nomes ou
  regras de construtoras, ABECIP ou outro conjunto de PDFs.

## Contrato de proveniência visual proposto

### 1. Localizador inequívoco do campo resolvido

O `campo_saida` da auditoria representa o caminho semântico da layout
signature e pode conter filtros. O JSON final, por sua vez, contém arrays em
posições concretas. Fazer a união por valor ou por heurística é inseguro.

A DAG 2 deve persistir, em cada item da auditoria, um ponteiro para a posição
real escrita no `schema_saida_resolvido.json`, preferencialmente em JSON Pointer
(RFC 6901):

```json
{
  "campo_saida": "balancos.metricas.dados[empresa=Exemplo].valores[papel_periodo=referencia].valor",
  "output_pointer": "/balancos/metricas/dados/0/valores/1/valor"
}
```

O portal usará esse ponteiro para vincular o nó clicado à evidência. Ele não
deve tentar deduzir o vínculo a partir de `valor_resolvido`.

### 2. Forma normalizada de evidência

Durante a resolução, a auditoria deve ganhar uma representação estável, sem
substituir a evidência detalhada já existente:

```json
{
  "evidencia_visual": {
    "versao": "1.0",
    "tipo": "pdf_bbox",
    "precisao": "celula",
    "origem": {
      "arquivo_origem": "tables/table002.json",
      "registro_id": "table002",
      "seletor": {
        "row_index": 4,
        "column_index": 2
      }
    },
    "pagina": 2,
    "bbox": {
      "left": 120.4,
      "top": 410.0,
      "right": 188.9,
      "bottom": 390.2,
      "coord_origin": "BOTTOMLEFT"
    }
  }
}
```

Quando não houver marcação possível:

```json
{
  "evidencia_visual": {
    "versao": "1.0",
    "tipo": "sem_localizacao_visual",
    "precisao": "indisponivel",
    "motivo": "valor_fixo_definido_no_contrato"
  }
}
```

Para uma fonte em bloco textual, `precisao` será `bloco`; para tabela antiga sem
geometria de célula, será `tabela` ou `intervalo_logico`. O portal deve mostrar
isso explicitamente.

### 3. Casos de origem

| Tipo de origem | Evidência visual esperada | Comportamento no portal |
| --- | --- | --- |
| `bloco_textual` | bbox do bloco | marcação exata do bloco |
| `celula_de_tabela` | bbox da célula | marcação exata da célula |
| `linhas_de_tabela` | bbox das linhas, quando disponível | destaca intervalo; senão tabela e rótulo de escopo |
| `cabecalho_de_tabela` | bbox da célula/cabeçalho | marcação do cabeçalho |
| `campo_json` | não é necessariamente PDF | apresenta JSON/origem, sem simular marcação |
| `valor_fixo` | definido no contrato | exibe proveniência contratual, sem PDF |
| `campo_derivado` | depende de outros campos | exibe dependências navegáveis |
| `juncao_de_registros_json` | múltiplas evidências | permite escolher cada origem |
| gráfico | bbox do gráfico ou do ponto, se existir | destaca gráfico; ponto exato só com bbox do ponto |

## Evolução necessária na extração

### Bboxes por célula de tabela

Para cumprir a promessa de destacar o dado específico, a extração precisa
persistir bbox por célula lógica. A mudança deve ampliar `TableCellRecord` com
campos opcionais, sem quebrar artefatos existentes:

```json
{
  "row_index": 4,
  "column_index": 2,
  "value_raw": "2.022",
  "page_number": 2,
  "bbox": { "left": 120.4, "top": 410.0, "right": 188.9, "bottom": 390.2,
            "coord_origin": "BOTTOMLEFT" },
  "row_span": 1,
  "column_span": 1
}
```

Implementação:

1. Investigar o objeto de tabela do Docling na versão instalada para obter a
   proveniência de suas células lógicas, incluindo células de cabeçalho e spans.
2. Converter somente coordenadas fornecidas pelo Docling; não gerar coordenadas
   aproximadas a partir de `DataFrame`.
3. Persistir a informação tanto no registro de células como no artefato de
   tabela correspondente.
4. Fazer a DAG 2 recuperar o bbox da célula por `row_index` e `column_index`
   ao criar a auditoria.
5. Para PDFs já extraídos sem esse dado, manter fallback em nível de tabela,
   claramente sinalizado. Não reescrever artefatos imutáveis: reextrair apenas
   os documentos que precisarem de precisão por célula.

Gráficos devem entrar em fase posterior. Hoje os pontos de gráfico não possuem
bbox; inicialmente o portal poderá destacar o gráfico inteiro quando houver
essa geometria, sem alegar apontar o ponto numérico exato.

## APIs a implementar no portal

### Localização de artefatos de resultado

Criar um serviço que receba `domain`, `entity_slug`, `document_id` e
`execution_id` e localize de forma determinística:

- manifesto de extração;
- PDF de origem;
- contrato e layout usados;
- `schema_saida_resolvido.json`;
- `auditoria_resolucao.json`;
- `validacao_layout_signature.json`;
- revalidação da DAG 3, quando a publicação tiver ocorrido por fallback.

Ele não deve escolher "o arquivo mais recente" de forma silenciosa. A resposta
deve informar de qual prefixo de resolução/revalidação veio cada artefato.

### Endpoints propostos

```text
GET /api/executions/{domain}/{entity_slug}/{document_id}/{execution_id}/result
GET /api/executions/{domain}/{entity_slug}/{document_id}/{execution_id}/provenance?pointer=...
GET /api/executions/{domain}/{entity_slug}/{document_id}/{execution_id}/source-pdf
```

`/result` devolve o schema, resumo de auditoria, validação e referências de
artefatos. `/provenance` devolve a evidência normalizada de um ou mais campos
associados ao JSON Pointer. `/source-pdf` atua como proxy autenticado e deve
suportar requisições HTTP `Range`, necessárias para o PDF.js abrir documentos
grandes sem baixar tudo antecipadamente.

As respostas devem usar modelos Pydantic e não retornar objeto MinIO bruto ou
segredos de infraestrutura.

## Experiência de uso proposta

### Página de resultado

Ao fim de uma execução terminal, a rastreabilidade atual exibirá o botão
**Abrir resultado auditável**. Ele abre uma página com dois painéis:

```text
+--------------------------------+--------------------------------------+
| Schema de saída resolvido      | PDF de origem                        |
| - árvore JSON expansível       | - página atual                       |
| - valores e tipo de evidência  | - zoom e navegação                   |
| - status de resolução          | - retângulo vermelho de evidência    |
+--------------------------------+--------------------------------------+
| Auditoria: bruto, normalizado, artefato, seletor, layout e contrato       |
+-------------------------------------------------------------------------+
```

### Interação

1. A pessoa expande a árvore do schema e seleciona um valor resolvido.
2. O portal consulta a proveniência pelo `output_pointer`.
3. Se houver bbox, o PDF abre na página indicada, aplica a transformação de
   coordenadas e desenha o contorno vermelho.
4. O painel de auditoria mostra valor bruto, valor normalizado, artefato,
   seletor, página, tipo de origem e nível de precisão.
5. Se houver mais de uma evidência, a pessoa escolhe qual delas visualizar.
6. Se não houver posição visual, a UI explica por que: valor fixo, derivado,
   origem JSON, bbox indisponível ou artefato legado.

Valores da árvore devem ser botões acessíveis, não `div`s clicáveis. A seleção
precisa ter foco visível; o usuário deve conseguir navegar entre evidências por
teclado. Em telas pequenas, os painéis ficam empilhados, com o PDF abaixo da
árvore.

### Renderização do PDF

Usar PDF.js para renderizar a página em canvas e sobrepor um SVG/HTML absoluto
para a marcação. O visualizador nativo do navegador não oferece uma forma
confiável de desenhar a camada de evidência sobre o documento.

Para a origem `BOTTOMLEFT`, com altura da página `H` e escala `s`, a conversão
para a superfície de PDF.js, cuja origem é superior esquerda, é:

```text
x      = left * s
y      = (H - top) * s
largura = (right - left) * s
altura  = (top - bottom) * s
```

A transformação deve ficar isolada e coberta por testes para cada
`coord_origin` suportada. Bbox incompleto, página ausente ou origem desconhecida
deve desabilitar a sobreposição, não desenhar em local possivelmente errado.

## Fases de execução

### Fase 0 — Contrato e amostras de aceitação

1. Escolher documentos de referência com bloco textual, célula de tabela,
   valor fixo, campo derivado e, se possível, um gráfico.
2. Definir quais casos exigem precisão de célula e quais aceitam escopo de
   tabela/bloco.
3. Formalizar `output_pointer` e `evidencia_visual` como parte da auditoria.

**Saída:** exemplos versionados de auditoria e critérios de aceitação.

### Fase 1 — Resultado auditável sem visualizador

1. Refatorar o acesso a MinIO para um repositório/serviço de execução.
2. Criar a rota `/result` com schema, auditoria e validação.
3. Criar a página de resultado com árvore JSON e painel de auditoria textual.
4. Persistir `output_pointer` na DAG 2 para cada valor resolvido.

**Saída:** a pessoa já consegue clicar no valor e ler sua evidência, mesmo sem
marcação no PDF.

### Fase 2 — Geometria confiável da extração

1. Ampliar o modelo/persistência de células para bbox, página e spans.
2. Adaptar o extrator Docling com detecção compatível com a versão instalada.
3. Adaptar a DAG 2 para transportar o bbox certo até a auditoria normalizada.
4. Reextrair apenas amostras necessárias e testar tabelas com cabeçalho,
   larguras variáveis e células mescladas.

**Saída:** bboxes de célula são produzidos onde o Docling oferece geometria.

### Fase 3 — Preview do PDF e sobreposição

1. Adicionar endpoint autenticado e compatível com `Range` para o PDF.
2. Integrar PDF.js com carregamento preguiçoso da página selecionada.
3. Implementar conversão de coordenadas e retângulo vermelho.
4. Implementar estados `célula`, `bloco`, `tabela`, `indisponível` e múltiplas
   evidências.

**Saída:** clique em dado abre a página e evidencia corretamente a origem.

### Fase 4 — Robustez, segurança e operação

1. Substituir token global por autenticação corporativa e autorização por
   domínio/owner.
2. Criar testes unitários, de API e ponta a ponta.
3. Monitorar tempo de carregamento, falhas de PDF e percentual de campos com
   evidência visual disponível.
4. Acrescentar suporte a gráfico quando houver bbox confiável do gráfico/ponto.

## Critérios de aceite

- Um campo resolvido com bbox de célula abre a página correta e o retângulo
  cobre a célula correspondente, sem deslocamento de origem.
- Um bloco textual é destacado como bloco, não como célula.
- Uma tabela legada sem bbox de célula mostra destaque de tabela e a UI informa
  que a precisão é ampla.
- `valor_fixo`, `campo_derivado` e `campo_json` não recebem um retângulo falso;
  recebem explicação e dependências/origem apropriadas.
- Campos de mesmo valor em pontos diferentes do schema não se cruzam: o vínculo
  é feito por `output_pointer` persistido na auditoria.
- Nenhuma credencial ou URL MinIO pública aparece no navegador.
- O navegador carrega prioritariamente a página consultada, não renderiza todo
  o PDF de uma vez.
- A tela mantém operação por teclado, foco visível e um texto alternativo para
  casos em que a evidência visual não está disponível.

## Riscos e decisões a evitar

- Não desenhar células por interpolação geométrica da tabela.
- Não localizar a evidência comparando texto ou valor bruto.
- Não fazer o frontend abrir diretamente o MinIO.
- Não misturar a implementação no HTML em linha atual; o visualizador exige
  JavaScript isolado, testável e com ciclo de vida explícito.
- Não tratar ausência de bbox como falha da resolução. A resolução pode ser
  válida e auditável mesmo sem preview visual preciso.

## Resultado esperado

O portal deixa de ser somente uma porta de entrada e monitor de estágio. Ele
passa a ser a camada de auditoria humana do pipeline: qualquer usuário consegue
sair de um valor do schema final, ver o seletor e a transformação aplicados e
chegar visualmente ao ponto correspondente do PDF, com transparência sobre a
precisão real dessa evidência.
