#!/usr/bin/env bash

# Instala somente skills autorais versionadas neste repositório.
set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source_dir="${repository_root}/skills"
target_root="${CODEX_HOME:-${HOME}/.codex}/skills"

if [[ ! -d "${source_dir}" ]]; then
  echo "Pasta de skills não encontrada: ${source_dir}" >&2
  exit 1
fi

mkdir -p "${target_root}"

installed=0
for skill_dir in "${source_dir}"/*; do
  [[ -d "${skill_dir}" ]] || continue
  [[ -f "${skill_dir}/SKILL.md" ]] || continue

  skill_name="$(basename "${skill_dir}")"
  rsync -a --delete "${skill_dir}/" "${target_root}/${skill_name}/"
  echo "Skill instalada: ${skill_name}"
  installed=$((installed + 1))
done

echo "${installed} skill(s) do projeto sincronizada(s) em ${target_root}."
