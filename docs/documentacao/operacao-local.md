# Operação Local

## Servindo a documentação

Com as dependências instaladas:

```bash
mkdocs serve
```

Ou especificando host e porta:

```bash
mkdocs serve -a 127.0.0.1:8000
```

Se você estiver usando a `.venv` do projeto sem ativá-la:

```bash
.venv/bin/python -m mkdocs serve -a 127.0.0.1:8000
```

## Build estático

Para gerar o site estático:

```bash
mkdocs build
```

O resultado vai para a pasta `site/`.

Essa pasta é artefato gerado e por isso está ignorada no repositório.

## Publicação no GitHub Pages

Há dois caminhos comuns:

### Publicar o conteúdo gerado de `site/`

Via GitHub Actions ou branch dedicada.

### Publicar usando CI

Executar `mkdocs build` no pipeline e publicar o diretório final em Pages.

## Comandos úteis de manutenção

### Validar a documentação sem subir servidor

```bash
.venv/bin/python -m mkdocs build
```

### Reinstalar dependências da docs

```bash
.venv/bin/python -m pip install -r requirements-docs.txt
```

### Rodar a pipeline principal

```bash
python3 -m docling_pipeline docling_pipeline/dados.pdf --output-dir ./saida
```

## Quando editar a documentação

Você normalmente vai mexer em:

- `mkdocs.yml`
- arquivos Markdown dentro de `docs/`
- `docs/assets/custom-footer.css`

## Estratégia de edição recomendada

### Para conteúdo

Edite os arquivos Markdown em `docs/`.

### Para navegação

Edite `mkdocs.yml`.

### Para apresentação

Edite os assets em `docs/assets/`.

## Verificação mínima antes de commit

Uma boa rotina antes de versionar mudanças na documentação é:

1. rodar `mkdocs build`;
2. abrir `mkdocs serve`;
3. navegar pela home e por pelo menos uma página de cada grupo do `nav`.
