# Estado atual e próximos passos da geração de Layout Signature com LLM

## 1. Propósito deste documento

Este documento registra até onde o projeto avançou na criação automática de
Layout Signatures, quais resultados já foram comprovados, quais falhas foram
encontradas durante os testes e quais problemas ainda precisam ser resolvidos.

O objetivo final não é apenas gerar um JSON estruturalmente válido. O objetivo
é gerar uma **assinatura de layout perfeita para a família documental em
análise**, isto é, uma assinatura que permita:

- encontrar novamente os mesmos conceitos em novas versões do documento;
- resolver deterministicamente o schema de saída;
- distinguir valores fixos de valores observados no PDF;
- preservar linhagem, evidência e auditabilidade;
- detectar mudanças reais de layout;
- impedir publicação quando houver cobertura apenas aparente;
- funcionar sem usar a LLM no caminho normal depois da homologação.

Embora os testes atuais usem o relatório trimestral da Cury como fixture, o
projeto **não é um extrator exclusivo de construtoras**. A arquitetura deve ser
capaz de receber contratos semânticos de diferentes domínios e extrair conteúdo
de qualquer família de PDFs.

---

## 2. Visão final do produto

Ao iniciar a extração de uma nova família documental, o único artefato que deve
ser criado manualmente é o **Contrato Semântico**.

Esse contrato define:

- entidades;
- métricas;
- conceitos canônicos;
- sinônimos;
- domínios de valores;
- obrigatoriedade;
- tipos;
- chaves estáveis;
- estrutura do `schema_saida`.

O contrato responde:

> O que esse tipo de documento deve entregar, independentemente de sua forma
> visual?

Todo o restante deve ser descoberto, validado e versionado pelo pipeline:

1. a DAG 1 transforma o PDF em artefatos estruturados;
2. a DAG 3 analisa contrato e artefatos para construir uma Layout Signature;
3. a DAG 2 revalida deterministicamente essa assinatura;
4. somente uma assinatura aprovada pode ser publicada como ativa;
5. execuções futuras usam a assinatura ativa sem depender da LLM;
6. a LLM retorna apenas quando ocorrer uma quebra comprovada.

Em termos simples:

```text
Contrato Semântico manual
  define O QUE deve sair
          |
          v
PDF -> artefatos de extração
  mostram O QUE existe e ONDE está
          |
          v
Layout Signature descoberta
  define ONDE e COMO buscar
          |
          v
DAG 2 determinística
  produz o Schema de Saída Resolvido
```

Essa separação é essencial para que a arquitetura seja generalizável. Não se
deve codificar no pipeline que toda empresa possui lançamentos e vendas, que
toda tabela usa `Número de Unidades`, ou que todo PDF é trimestral. Essas
características pertencem ao contrato e à assinatura daquele domínio, não ao
motor genérico.

---

## 3. Papel de cada artefato

### 3.1 Contrato Semântico

É a fonte de verdade manual e estática para uma família documental.

Deve declarar significado, estrutura e resultado esperado, mas não deve conter:

- números de página;
- nomes de arquivos `table001`, `table002` etc.;
- índices físicos de linha ou coluna;
- coordenadas visuais;
- seletores específicos do documento;
- valores de negócio extraídos de uma execução.

### 3.2 Artefatos de extração

São produzidos pela DAG 1 a partir do PDF e podem incluir:

- tabelas;
- células;
- linhas normalizadas;
- blocos textuais;
- seções;
- gráficos;
- métricas;
- casos estruturais;
- candidatos textuais;
- estruturas textuais extraídas.

Eles são evidências do documento, não o resultado final.

### 3.3 Layout Signature

É o mapa operacional que liga o contrato aos artefatos observados.

Deve conter:

- fontes relevantes;
- regras determinísticas de mudança;
- seletores de linha e coluna;
- papéis de período quando aplicável;
- normalizações;
- mapeamento canônico;
- evidências estruturais;
- referência ao contrato utilizado.

A Layout Signature não deve armazenar valores de negócio resolvidos. Por
exemplo, `8.001` não deve ser gravado como `valor_fixo` quando ele é uma célula
observada no PDF. A assinatura deve registrar o seletor capaz de encontrar esse
valor novamente.

### 3.4 Schema de Saída Resolvido

É a instância preenchida do `schema_saida` para uma execução específica.

Esse artefato contém os valores de negócio efetivamente extraídos e é o produto
que poderá seguir para a camada bronze quando autorizado pela validação.

---

## 4. Fluxo implementado atualmente

### 4.1 Comportamento sem Layout Signature ativa

Quando a DAG 2 não encontra `current.json`, ela:

- não tenta resolver o schema sem mapa de leitura;
- não cria artefatos oficiais de resolução vazios;
- retorna o motivo `layout_signature_ausente`;
- aciona a DAG 3 em modo `criacao_inicial_layout`.

Esse comportamento está alinhado à decisão do projeto: sem assinatura não há
base confiável para gerar os artefatos da resolução.

### 4.2 Geração em três passagens da LLM

A criação inicial e a regeneração ampla agora usam três etapas.

#### Passagem 1 — seleção de artefatos

A LLM recebe o inventário da extração e escolhe os artefatos necessários.

No teste da Cury, a seleção chegou corretamente a:

- `tables/table001.json`;
- `tables/table002.json`;
- `sections/sections.jsonl`.

A resposta é validada para impedir caminhos que não existam no inventário.

#### Passagem 2 — matriz de cobertura

A LLM recebe os campos-alvo derivados do `schema_saida` e deve declarar, para
cada campo:

- se foi localizado;
- a fonte observada;
- o tipo de origem proposto;
- os seletores necessários;
- a evidência estrutural;
- o motivo da ausência, quando não localizado.

A matriz existe para impedir que campos desapareçam silenciosamente durante a
geração do layout.

#### Passagem 3 — Layout Signature candidata

A LLM transforma a matriz em uma assinatura operacional. O candidato deve
conter diretamente todos os mappings autorizados, fontes e regras necessárias.

O candidato passa por modelos Pydantic estritos antes de ser persistido.

---

## 5. Melhorias já implementadas

### 5.1 Modelos Pydantic discriminados

Foram criados modelos específicos para:

- seletor de linha;
- seletor de coluna;
- evidência estrutural;
- `valor_fixo`;
- `campo_derivado`;
- `bloco_textual`;
- `cabecalho_de_tabela`;
- `celula_de_tabela`;
- regra `arquivo_existe`;
- regra `secao_existe`;
- regra `linha_existe_em_tabela`;
- regra `perfil_colunas_periodo_existe_em_tabela`;
- regra `valor_normalizavel`.

Cada tipo aceita apenas seus próprios parâmetros. Campos extras são rejeitados.
Isso eliminou o problema anterior em que mappings inteiros eram aninhados
dentro de outro mapping ou chaves corrompidas eram aceitas silenciosamente.

### 5.2 Contexto completo do contrato

Na criação inicial, a LLM recebe o contrato completo, incluindo:

- `schema_saida` completo;
- paths navegáveis;
- arrays;
- entidades;
- métricas;
- sinônimos;
- tipos;
- papéis de período;
- campos-alvo concretos para a execução.

Para a fixture atual da Cury, o contexto produz 32 campos-alvo concretos. Esse
número é uma característica do contrato atual, não uma constante do motor.

### 5.3 Validações contra falso positivo

O pipeline agora bloqueia:

- zero regras interpretado como compatibilidade;
- fontes vazias na criação inicial;
- mapping vazio;
- mappings fora do `schema_saida`;
- arrays sem seletores explícitos;
- caminhos inventados fora do inventário;
- schema vazio considerado publicável;
- campos obrigatórios não resolvidos;
- percentuais derivados no schema resolvido;
- divergência de perfis temporais entre fontes críticas;
- publicação sem período de referência;
- publicação sem dados críticos materializados.

### 5.4 Compatibilidade com o endpoint Ollama

O Ollama utilizado nos testes rejeitou alguns JSON Schemas discriminados
complexos. O cliente foi ajustado para:

- tentar primeiro o schema estruturado;
- detectar especificamente `invalid JSON schema in format`;
- repetir com `format=json`;
- manter obrigatoriamente a validação Pydantic local.

Também foi adicionada tolerância para JSON envolvido em bloco Markdown, sem
aceitar conteúdo que não forme um objeto JSON válido.

### 5.5 Reparos controlados

Matriz e candidato podem passar por até três tentativas de reparo.

Os erros Pydantic são compactados antes de voltar à LLM para evitar que dezenas
de mensagens repetidas consumam todo o contexto e causem respostas truncadas.

### 5.6 Publicação governada

Quando um candidato passa pela revalidação:

- o envelope governado é reconstruído deterministicamente;
- a LLM não define versão final;
- a LLM não define regras de governança;
- a referência do contrato é preservada;
- a versão é publicada em caminho imutável;
- os três artefatos da revalidação são promovidos para a resolução oficial;
- `current.json` é atualizado por último.

---

## 9. Critérios para considerar uma Layout Signature “perfeita”

Uma assinatura não precisa ser visualmente idêntica à fixture manual. Ela deve
ser funcionalmente equivalente e cumprir os critérios abaixo.

### 9.1 Fidelidade ao contrato

- todos os mappings apontam para paths válidos do `schema_saida`;
- entidades, métricas e chaves seguem o contrato;
- não existem campos inventados;
- campos opcionais ausentes são explicitamente justificados;
- campos obrigatórios estão integralmente cobertos.

### 9.2 Reutilização

- valores variáveis são encontrados por seletores;
- valores de negócio não são congelados como constantes;
- papéis semânticos são usados em vez de períodos codificados no nome da chave;
- a assinatura funciona em uma nova edição compatível do documento.

### 9.3 Determinismo

- a DAG 2 consegue executar sem LLM;
- cada mapping possui algoritmo fechado;
- cada regra produz aprovação ou reprovação explicável;
- a mesma entrada produz o mesmo resultado.

### 9.4 Cobertura

- fontes relevantes sustentam todos os mappings aplicáveis;
- mappings obrigatórios são resolvidos;
- dados críticos possuem valor, período e escopo;
- a cobertura é calculada contra o contrato, não contra o próprio candidato.

### 9.5 Evidência e auditoria

- cada valor pode ser rastreado ao artefato de origem;
- seletores aplicados aparecem na auditoria;
- valor bruto e valor normalizado são preservados;
- versão de contrato e assinatura são identificáveis;
- alterações e rejeições deixam histórico.

### 9.6 Segurança de publicação

- zero regras nunca significa compatibilidade;
- lista não vazia nunca substitui validação do conteúdo interno;
- candidato permanece isolado até revalidação;
- versões antigas não são sobrescritas;
- `current.json` só é atualizado ao final;
- falha em qualquer gate impede promoção.

---

## 10. Generalização para qualquer PDF

O motor deve ser neutro em relação ao domínio.

Para outro tipo de PDF, como contratos, notas fiscais, relatórios médicos,
editais, documentos jurídicos, demonstrativos financeiros ou relatórios
ambientais, o fluxo continua o mesmo:

1. uma pessoa modela o Contrato Semântico;
2. a DAG 1 extrai estruturas observáveis;
3. a LLM relaciona essas estruturas às entidades, métricas e chaves do contrato;
4. a matriz demonstra a cobertura;
5. a LLM produz seletores e regras;
6. a DAG 2 tenta resolver o schema sem interpretação livre;
7. somente a resolução comprovada permite publicação da assinatura.

O que muda entre domínios é o contrato. O que não deve mudar é o motor de:

- inventário;
- seleção de evidências;
- modelagem de mappings;
- validação de regras;
- resolução do schema;
- auditoria;
- fallback;
- versionamento.

Essa é a razão para o contrato semântico ser o centro da arquitetura. Sem ele,
a LLM tenderia a reproduzir exemplos conhecidos, inventar estruturas ou ficar
presa ao caso das construtoras. Com ele, o processo pode descobrir layouts
diferentes mantendo uma saída estável e governada.

---

## 11. Próxima sequência recomendada

1. Implementar retry de transporte no cliente da LLM.
2. Reexecutar criação inicial da Cury com o endpoint estável.
3. Inspecionar no MinIO seleção, matriz e candidato antes da revalidação.
4. Confirmar que os dez valores por período usam `celula_de_tabela`.
5. Confirmar os cinco papéis de período e seus cabeçalhos.
6. Confirmar regras de seção, arquivo, linha, perfil e normalização.
7. Revalidar pela DAG 2.
8. Inspecionar os três artefatos da revalidação.
9. Comparar automaticamente o candidato com a fixture manual.
10. Publicar somente se schema e auditoria comprovarem o resultado.
11. Repetir o teste com uma segunda família de PDF e outro contrato semântico.

O item 11 é essencial. Um resultado excelente somente para a Cury prova a
fixture; um resultado consistente em contratos e layouts diferentes começa a
provar a arquitetura genérica.

---

## 12. Conclusão

O projeto avançou de uma resposta de LLM estruturalmente quebrada para um fluxo
governado, com três passagens, modelos estritos, revalidação determinística,
versionamento e inspeção de artefatos.

A LLM já demonstrou capacidade de encontrar as fontes e os valores corretos.
O desafio atual é fazê-la representar esse conhecimento como uma assinatura
reutilizável, e não como uma fotografia dos valores da execução atual.

A “assinatura perfeita” será alcançada quando a LLM conseguir transformar o
Contrato Semântico e as evidências de qualquer PDF em regras e seletores que a
DAG 2 possa executar repetidamente, com cobertura real e sem conhecimento
hardcoded do domínio.

O Contrato Semântico continuará sendo o único artefato manual necessário ao
iniciar uma nova extração. Ele define o significado. Todo o restante deve ser
descoberto, provado, auditado e versionado pelo pipeline.
