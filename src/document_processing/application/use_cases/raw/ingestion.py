"""Ingestao deterministica de resolucoes aprovadas no destino raw."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections import defaultdict
from datetime import datetime, timezone

from document_processing.domain.raw.tabular import (
    abecip_competence,
    abecip_rows,
    construtoras_rows,
    merge_company_rows,
    normalize_quarter,
)
from document_processing.infrastructure.storage.raw_repository import rows_fingerprint


class SourceRejected(ValueError):
    """Artefato sem aprovacao ou com linhagem inconsistente."""


class RawIngestionUseCase:
    def __init__(self, source, target):
        self.source = source
        self.target = target

    def _read(self, key):
        from minio.error import S3Error

        try:
            return self.source.get_json(object_key=key)
        except S3Error as exc:
            if exc.code in ("NoSuchKey", "NoSuchObject"):
                raise SourceRejected(f"Artefato obrigatorio ausente: {key}") from exc
            raise

    def _describe(self, key, manifests):
        match = re.fullmatch(
            r"(?:execucoes/(abecip|construtoras)/resolucao|fallback/(abecip|construtoras))"
            r"/([a-z0-9-]+)/document_id=([^/]+)/execution_id=([^/]+)/"
            r"(resolution|revalidation)/schema_saida_resolvido.json", key,
        )
        if not match:
            raise SourceRejected(f"Caminho de resolucao nao reconhecido: {key}")
        canonical_domain, fallback_domain, entity, doc, path_execution, folder = match.groups()
        domain = canonical_domain or fallback_domain
        if (canonical_domain and folder != "resolution") or (fallback_domain and folder != "revalidation"):
            raise SourceRejected("Pasta de resolucao inconsistente.")
        root = key.rsplit("/", 1)[0]
        audit_key = root + "/auditoria_resolucao.json"
        validation_key = root + "/validacao_layout_signature.json"
        audit = self._read(audit_key)
        validation = self._read(validation_key)
        summary = audit.get("summary", {})
        if (audit.get("status") != "concluida"
                or summary.get("validation_status") != "compativel"
                or summary.get("campos_mapeamento_com_falha") != 0
                or validation.get("status_compatibilidade", {}).get("status") != "compativel"
                or any(row.get("obrigatorio") and row.get("status_resolucao") != "resolvido"
                       for row in audit.get("auditoria_resolucao", []))):
            raise SourceRejected(f"Resolucao bloqueada ou parcial: {key}")
        execution = audit.get("execution_id")
        if audit.get("document_id") != doc or not execution:
            raise SourceRejected("Auditoria com identidade divergente.")
        if canonical_domain and execution != path_execution:
            raise SourceRejected("Execucao da auditoria diverge do caminho canonico.")
        published = {}
        layout = {}
        if fallback_domain:
            publication_key = root.rsplit("/", 1)[0] + "/publicacao_layout_signature.json"
            published = self._read(publication_key)
            if published.get("status") != "publicado" or published.get("validation_object_key") != validation_key:
                raise SourceRejected("Fallback sem publicacao aprovada da mesma revalidacao.")
            candidate_key = published.get("candidate_layout_object_key", "")
            if candidate_key != root.rsplit("/", 1)[0] + "/layout_signature_candidato.json":
                raise SourceRejected("Candidato publicado pertence a outro fallback.")
            candidate = self._read(candidate_key)
            if candidate.get("document_id") != doc or candidate.get("execution_id_origem") != execution:
                raise SourceRejected("Candidato com identidade divergente da auditoria.")
            layout = self._read(published.get("published_layout_object_key", ""))
            origin = layout.get("documento_origem", {})
            lineage = layout.get("lineage_fallback", {})
            if (origin.get("document_id") != doc or origin.get("execution_id") != execution
                    or lineage.get("validation_object_key") != validation_key
                    or lineage.get("candidate_layout_object_key") != candidate_key):
                raise SourceRejected("Layout publicado diverge da origem revalidada.")
        candidates = manifests.get((domain, entity, doc, execution), [])
        if len(candidates) != 1:
            raise SourceRejected(f"Manifesto de extracao ausente ou ambiguo para {key}.")
        manifest_key = candidates[0]
        manifest = self._read(manifest_key)
        if manifest.get("document_id") != doc or manifest.get("execution_id") != execution:
            raise SourceRejected("Identidade do manifesto de extracao divergente.")
        candidate = manifest.get("candidate", {})
        if (candidate.get("domain", domain) != domain
                or (candidate.get("entity_slug") or candidate.get("company_slug") or entity) != entity):
            raise SourceRejected("Dominio ou entidade do manifesto divergente.")
        if not manifest.get("input_pdf_uri") or not (manifest.get("contrato_semantico_uri") or layout.get("referencia_contrato_semantico")):
            raise SourceRejected("Manifesto sem origem PDF ou contrato semantico.")
        schema = self._read(key)
        if domain == "abecip":
            period = abecip_competence(schema, manifest)
            expected = candidate.get("period_label")
        else:
            period = normalize_quarter(schema.get("periodo_referencia") or candidate.get("period_label"))
            expected = normalize_quarter(candidate.get("period_label"))
        if expected != period:
            raise SourceRejected("Competencia do schema diverge do manifesto.")
        timestamp = published.get("publicado_em") or audit.get("executado_em")
        try:
            approved_at = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            if approved_at.tzinfo is None:
                raise ValueError("Data sem fuso horario")
        except (AttributeError, TypeError, ValueError) as exc:
            raise SourceRejected("Data de aprovacao invalida.") from exc
        return {
            "domain": domain, "entity": entity, "period": period,
            "schema_key": key, "manifest_key": manifest_key, "audit_key": audit_key,
            "validation_key": validation_key, "document_id": doc, "execution_id": execution,
            "contract_uri": manifest.get("contrato_semantico_uri"),
            "contract_reference": layout.get("referencia_contrato_semantico"),
            "layout_key": published.get("published_layout_object_key"),
            "layout_version": published.get("versao_publicada"),
            "approved_at": approved_at.isoformat(),
            "source_fingerprint": hashlib.sha256(json.dumps([schema, manifest, audit, validation, published, layout], sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
        }

    def discover(self, params):
        domain = params.get("dominio", "ambos")
        if domain not in ("abecip", "construtoras", "ambos"):
            raise ValueError("Dominio invalido.")
        for name in ("entidades", "periodos", "schema_object_keys"):
            value = params.get(name, [])
            if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
                raise ValueError(f"{name} deve ser uma lista de strings.")
        domains = ("abecip", "construtoras") if domain == "ambos" else (domain,)
        manifests = defaultdict(list)
        for d in domains:
            for key in self.source.list_object_keys(prefix=f"execucoes/{d}/extracao/", suffix="/manifesto_execucao.json"):
                m = re.fullmatch(r"execucoes/([^/]+)/extracao/([^/]+)/(?:[^/]+/)*document_id=([^/]+)/execution_id=([^/]+)/extraction/manifesto_execucao.json", key)
                if m:
                    manifests[m.groups()].append(key)
        explicit = params.get("schema_object_keys", [])
        keys = explicit or [
            key for d in domains for prefix in (f"execucoes/{d}/resolucao/", f"fallback/{d}/")
            for key in self.source.list_object_keys(prefix=prefix, suffix="/schema_saida_resolvido.json")
        ]
        latest = {}
        for key in sorted(set(keys)):
            try:
                source = self._describe(key, manifests)
            except (SourceRejected, ValueError) as exc:
                if explicit:
                    raise
                logging.warning("Raw: origem ignorada: %s", exc)
                continue
            if source["domain"] not in domains:
                raise ValueError("Schema explicito fora do dominio selecionado.")
            if params.get("entidades") and source["entity"] not in params["entidades"]:
                continue
            if params.get("periodos") and source["period"] not in params["periodos"]:
                continue
            partition = (source["domain"], source["entity"], source["period"])
            rank = (datetime.fromisoformat(source["approved_at"]), key)
            if partition not in latest or rank > latest[partition][0]:
                latest[partition] = (rank, source)
        groups = defaultdict(list)
        for _, source in latest.values():
            groups[(source["domain"], source["entity"])].append(source)
        return [{"domain": d, "entity": e, "sources": sorted(sources, key=lambda s: s["period"])}
                for (d, e), sources in sorted(groups.items())]

    def ingest(self, group, *, execution_id, simulate=True):
        if not isinstance(simulate, bool):
            raise ValueError("simular deve ser booleano.")
        now = datetime.now(timezone.utc).isoformat()
        outputs = defaultdict(list)
        for item in group["sources"]:
            # Reconfere a aprovacao na execucao da task, nao apenas durante a descoberta.
            index = {(item["domain"], item["entity"], item["document_id"], item["execution_id"]): [item["manifest_key"]]}
            verified = self._describe(item["schema_key"], index)
            if verified != item:
                raise SourceRejected("Origem mudou apos a descoberta; execute nova descoberta.")
            schema = self._read(item["schema_key"])
            manifest = self._read(item["manifest_key"])
            base = {"document_id": item["document_id"], "execution_id": item["execution_id"], "exportado_em": now}
            if item["domain"] == "abecip":
                base.update(competencia_referencia=item["period"], entidade="ABECIP", source_object_key=item["schema_key"])
                tables = abecip_rows(schema, base)
                prefix = f"abecip/{item['period']}"
            else:
                base.update(periodo_referencia=schema.get("periodo_referencia") or item["period"],
                            source_pdf_uri=manifest["input_pdf_uri"], source_schema_object_key=item["schema_key"])
                tables = construtoras_rows(schema, base)
                prefix = f"construtoras/{item['entity']}"
            for table, rows in tables.items():
                outputs[f"{self.target.config.prefix}/{prefix}/{table}.json"].extend(rows)
        receipt = {
            "status": "simulado" if simulate else "em_andamento", "execution_id": execution_id,
            "iniciado_em": now, "sources": group["sources"], "objects": [],
            "target_bucket": self.target.config.bucket,
        }
        safe_id = re.sub(r"[^A-Za-z0-9_.-]", "_", execution_id)
        receipt_key = f"ingestoes/raw/{group['domain']}/{group['entity']}/execution_id={safe_id}/manifesto_ingestao_raw.json"

        def persist():
            if not simulate:
                self.source.put_json(object_key=receipt_key, payload=receipt)

        persist()
        try:
            for key, incoming in sorted(outputs.items()):
                existing, etag = self.target.read_rows(key)
                merged = merge_company_rows(existing, incoming) if group["domain"] == "construtoras" else incoming
                unchanged = etag is not None and rows_fingerprint(existing) == rows_fingerprint(merged)
                status = "sem_alteracao" if unchanged else "previsto" if simulate else "gravado"
                if not unchanged and not simulate:
                    self.target.write_rows(key, merged, etag)
                receipt["objects"].append({"key": key, "rows": len(merged), "incoming_rows": len(incoming),
                                           "fingerprint": rows_fingerprint(merged), "status": status})
                persist()
            receipt["status"] = "simulado" if simulate else "concluido"
            receipt["finalizado_em"] = datetime.now(timezone.utc).isoformat()
            persist()
        except Exception as exc:
            receipt.update(status="falhou", error_type=type(exc).__name__)
            persist()
            raise
        return receipt
