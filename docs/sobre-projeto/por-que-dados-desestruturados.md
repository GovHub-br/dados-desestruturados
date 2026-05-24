# Por Que o Projeto Existe

Relatórios em PDF normalmente misturam:

- títulos hierárquicos;
- texto narrativo;
- valores numéricos espalhados;
- tabelas formais;
- gráficos que às vezes não aparecem como objetos nativos fáceis de consumir.

Sem uma camada intermediária, esse conteúdo continua difícil de usar em automações, análise ou indexação semântica.

## O problema que o projeto ataca

O objetivo não é apenas "ler texto do PDF". O objetivo é recuperar **estrutura utilizável**:

- que seção fala de qual assunto;
- quais blocos formam o contexto de uma métrica;
- quais tabelas pertencem a qual capítulo;
- quais comparativos podem virar séries ou pontos estruturados;
- quais trechos narrativos justificam os números encontrados.

## Estratégia adotada

O projeto usa um caminho progressivo:

1. converter o PDF com Docling;
2. detectar seções e blocos;
3. reagrupar contexto por árvore e ordem de leitura;
4. extrair entidades específicas;
5. persistir resultados em formatos amigáveis para pessoas e scripts.

## Por que usar o Docling como base

O projeto assume que o Docling oferece mais do que OCR e mais do que detecção de caixas.
Ele oferece uma estrutura documental com itens, níveis e referências entre nós.

Isso permite que a pipeline trabalhe com perguntas mais ricas:

- este bloco é filho de qual item;
- esta seção contém quais nós;
- esta tabela está presa a qual parte do documento;
- esta legenda ou referência pertence a qual artefato.

## Por que ainda existem heurísticas

Mesmo com uma boa estrutura de entrada, PDFs continuam sendo documentos difíceis.
Nem todo gráfico aparece como gráfico nativo.
Nem todo valor textual aparece em um schema limpo.
Nem toda seção vem rotulada de forma perfeita.

Por isso o projeto combina:

- sinais fortes do Docling quando existem;
- heurísticas explícitas quando faltam sinais;
- resolução por fallback quando o documento é ambíguo.

## Resultado prático

O projeto vira uma ponte entre o PDF bruto e usos posteriores, como:

- exploração humana;
- automação analítica;
- indexação semântica;
- criação de datasets;
- apoio a pipelines futuras de QA, RAG ou BI.
