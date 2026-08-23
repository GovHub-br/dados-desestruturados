# Skills do projeto

Esta pasta é a fonte de verdade das skills autorais da plataforma. Ela contém
instruções operacionais, critérios de validação e referências para os fluxos
mais sensíveis; não contém skills do sistema nem de terceiros.

## Instalação local

```bash
bash scripts/install_project_skills.sh
```

O instalador copia apenas as skills deste repositório para
`${CODEX_HOME:-~/.codex}/skills` e não remove skills externas já existentes.

## Manutenção

- Atualize uma skill no repositório junto da mudança de arquitetura que ela
  descreve.
- Prefira links para `docs/` e `specs/` canônicos; não referencie artefatos de
  execução temporários como fonte de verdade.
- Cada skill deve manter escopo, pré-condições, passos de validação e limites
  explícitos.
