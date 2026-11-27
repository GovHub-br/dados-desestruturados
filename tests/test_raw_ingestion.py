from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest

from document_processing.application.use_cases.raw.ingestion import (
    RawIngestionUseCase,
    SourceRejected,
)
from document_processing.domain.raw.tabular import abecip_rows, merge_company_rows, numeric_value
from document_processing.infrastructure.storage.raw_repository import (
    RawRepository,
    rows_fingerprint,
)
from document_processing.shared.config.raw import RawStorageConfig, load_raw_storage_config


class Source:
    def __init__(self):
        self.data = {}
        self.writes = []

    def get_json(self, *, object_key):
        from minio.error import S3Error
        if object_key not in self.data:
            raise S3Error('NoSuchKey', 'missing', object_key, 'request', 'host', None)
        return copy.deepcopy(self.data[object_key])

    def list_object_keys(self, *, prefix, suffix):
        return sorted(k for k in self.data if k.startswith(prefix) and k.endswith(suffix))

    def put_json(self, *, object_key, payload):
        self.writes.append((object_key, copy.deepcopy(payload)))
        self.data[object_key] = copy.deepcopy(payload)


class Target:
    def __init__(self):
        self.config = SimpleNamespace(prefix='raw', bucket='test')
        self.data = {}
        self.writes = []
        self.fail_key = None

    def read_rows(self, key):
        return copy.deepcopy(self.data.get(key, [])), 'etag' if key in self.data else None

    def write_rows(self, key, rows, etag):
        if key == self.fail_key:
            raise RuntimeError('conflict')
        self.writes.append(key)
        self.data[key] = copy.deepcopy(rows)


def company_schema(period='2T26'):
    return {
        'periodo_referencia': period, 'fonte': None,
        'balancos_das_empresas': {
            op: {'indicador': 'numero_de_unidades', 'tipo': 'valor_bruto', 'unidade': 'unidades',
                 'tipo_operacao': kind,
                 'dados': [{'empresa': 'Cury', 'valores': [{'periodo': period, 'escopo_periodo': 'trimestre', 'valor': 123}]}]}
            for op, kind in [('lancamentos', 'lancamento'), ('vendas', 'venda')]
        },
    }


def add_source(source, *, fallback=False, execution='extract', period='2T26', date='2026-11-24T12:00:00+00:00'):
    doc = 'document'
    manifest_key = f'execucoes/construtoras/extracao/cury/ano=2026/periodo={period}/document_id={doc}/execution_id={execution}/extraction/manifesto_execucao.json'
    source.data[manifest_key] = {
        'document_id': doc, 'execution_id': execution, 'input_pdf_uri': 'minio://source/document.pdf',
        'contrato_semantico_uri': 'minio://source/contracts/v1.json',
        'candidate': {'company_slug': 'cury', 'period_label': period},
    }
    root = (f'fallback/construtoras/cury/document_id={doc}/execution_id=fallback-{execution}/revalidation' if fallback
            else f'execucoes/construtoras/resolucao/cury/document_id={doc}/execution_id={execution}/resolution')
    key = root + '/schema_saida_resolvido.json'
    source.data[key] = company_schema(period)
    source.data[root+'/auditoria_resolucao.json'] = {
        'document_id': doc, 'execution_id': execution, 'status': 'concluida', 'executado_em': date,
        'summary': {'validation_status': 'compativel', 'campos_mapeamento_com_falha': 0},
    }
    source.data[root+'/validacao_layout_signature.json'] = {'status_compatibilidade': {'status': 'compativel'}}
    if fallback:
        parent = root.rsplit('/', 1)[0]
        candidate_key = parent+'/layout_signature_candidato.json'
        layout_key = f'layouts/construtoras/cury/{execution}/layout.json'
        source.data[parent+'/publicacao_layout_signature.json'] = {
            'status': 'publicado', 'publicado_em': date, 'validation_object_key': root+'/validacao_layout_signature.json',
            'candidate_layout_object_key': candidate_key, 'published_layout_object_key': layout_key, 'versao_publicada': 'v1',
        }
        source.data[candidate_key] = {'document_id': doc, 'execution_id_origem': execution}
        source.data[layout_key] = {
            'documento_origem': {'document_id': doc, 'execution_id': execution},
            'referencia_contrato_semantico': {'arquivo': 'contract.json', 'versao': '1'},
            'lineage_fallback': {'validation_object_key': root+'/validacao_layout_signature.json', 'candidate_layout_object_key': candidate_key},
        }
    return key


def test_company_idempotent_preserves_history_and_extraction_identity():
    source, target = Source(), Target()
    add_source(source, period='1T26', execution='old')
    add_source(source, fallback=True)
    use = RawIngestionUseCase(source, target)
    group = use.discover({'periodos': ['1T26']})[0]
    use.ingest(group, execution_id='raw1', simulate=False)
    group = use.discover({'periodos': ['2T26']})[0]
    use.ingest(group, execution_id='raw2', simulate=False)
    assert {r['periodo_referencia'] for r in target.data['raw/construtoras/cury/vendas.json']} == {'1T26', '2T26'}
    assert target.data['raw/construtoras/cury/vendas.json'][-1]['execution_id'] == 'extract'
    previous = copy.deepcopy(target.data)
    result = use.ingest(group, execution_id='raw3', simulate=False)
    assert target.data == previous
    assert all(o['status'] == 'sem_alteracao' for o in result['objects'])
    assert len(target.writes) == 4
    assert source.writes[-1][1]['sources'][0]['layout_version'] == 'v1'


def test_simulation_performs_no_writes():
    source, target = Source(), Target()
    add_source(source)
    use = RawIngestionUseCase(source, target)
    result = use.ingest(use.discover({})[0], execution_id='raw')
    assert result['status'] == 'simulado'
    assert not source.writes and not target.writes


@pytest.mark.parametrize('mutation', ['validation', 'partial', 'identity', 'missing', 'no_publication', 'wrong_candidate', 'wrong_layout', 'manifest_identity', 'period'])
def test_unapproved_or_inconsistent_sources_blocked(mutation):
    source = Source()
    key = add_source(source, fallback=True)
    root = key.rsplit('/', 1)[0]
    parent = root.rsplit('/', 1)[0]
    if mutation == 'validation':
        source.data[root+'/validacao_layout_signature.json']['status_compatibilidade']['status'] = 'incompativel'
    elif mutation == 'partial':
        source.data[root+'/auditoria_resolucao.json']['summary']['campos_mapeamento_com_falha'] = 1
    elif mutation == 'identity':
        source.data[root+'/auditoria_resolucao.json']['document_id'] = 'other'
    elif mutation == 'missing':
        del source.data[root+'/auditoria_resolucao.json']
    elif mutation == 'no_publication':
        del source.data[parent+'/publicacao_layout_signature.json']
    elif mutation == 'wrong_candidate':
        source.data[parent+'/layout_signature_candidato.json']['execution_id_origem'] = 'other'
    elif mutation == 'wrong_layout':
        source.data['layouts/construtoras/cury/extract/layout.json']['documento_origem']['document_id'] = 'other'
    elif mutation == 'manifest_identity':
        source.data[next(k for k in source.data if k.endswith('manifesto_execucao.json'))]['execution_id'] = 'other'
    else:
        source.data[key]['periodo_referencia'] = '1T26'
    use = RawIngestionUseCase(source, Target())
    assert use.discover({}) == []
    with pytest.raises((SourceRejected, ValueError)):
        use.discover({'schema_object_keys': [key]})


def test_selects_latest_approved_not_latest_failed():
    source = Source()
    key = add_source(source, fallback=True, execution='first')
    newer = add_source(source, fallback=True, execution='new', date='2026-11-25T12:00:00+00:00')
    bad = add_source(source, execution='bad', date='2026-11-26T12:00:00+00:00')
    source.data[bad.replace('schema_saida_resolvido', 'auditoria_resolucao')]['summary']['campos_mapeamento_com_falha'] = 1
    use = RawIngestionUseCase(source, Target())
    assert use.discover({})[0]['sources'][0]['schema_key'] == newer
    assert use.discover({'schema_object_keys': [key]})[0]['sources'][0]['schema_key'] == key
    assert use.discover({'entidades': ['tenda']}) == []


def test_legacy_contract_from_published_layout():
    source = Source()
    add_source(source, fallback=True)
    source.data[next(k for k in source.data if k.endswith('manifesto_execucao.json'))].pop('contrato_semantico_uri')
    item = RawIngestionUseCase(source, Target()).discover({})[0]['sources'][0]
    assert item['contract_uri'] is None
    assert item['contract_reference']['versao'] == '1'


def test_changed_source_between_tasks_rejected():
    source, target = Source(), Target()
    key = add_source(source)
    use = RawIngestionUseCase(source, target)
    group = use.discover({})[0]
    source.data[key]['fonte'] = 'changed'
    with pytest.raises(SourceRejected):
        use.ingest(group, execution_id='raw', simulate=False)
    assert not source.writes and not target.writes


def test_partial_failure_records_receipt_and_retry_completes():
    source, target = Source(), Target()
    add_source(source)
    use = RawIngestionUseCase(source, target)
    group = use.discover({})[0]
    target.fail_key = 'raw/construtoras/cury/vendas.json'
    with pytest.raises(RuntimeError):
        use.ingest(group, execution_id='raw', simulate=False)
    assert source.writes[-1][1]['status'] == 'falhou'
    assert len(target.writes) == 1
    target.fail_key = None
    result = use.ingest(group, execution_id='raw', simulate=False)
    assert result['status'] == 'concluido' and len(target.writes) == 2


def test_abecip_current_and_old_shapes():
    schema = {
        'financiamentos_imobiliarios': {
            'serie_mensal_sbpe': [{'periodo': {'rotulo_publicado': 'Jan'}, 'unidades_financiadas': {'valor': 12}, 'volume_financiado_milhoes': 34}],
            'serie_historica_anual': [{'periodo': {'rotulo_publicado': '2025'}, 'unidades_financiadas': 56}],
            'por_modalidade_e_instituicao': [{'periodo': {'rotulo_publicado': None}, 'modalidade': 'aquisicao', 'instituicao_financeira': 'CAIXA', 'volume_mensal_milhoes': 78}],
        },
        'poupanca_sbpe': {'saldos_mensais': [{'ano': 2025, 'mes': 'Dez', 'saldo_milhoes': 90}], 'captacoes_liquidas_mensais': []},
    }
    result = abecip_rows(schema, {'competencia_referencia': '2026-09', 'document_id': 'd'})
    assert len(result) == 6 and result['recursos_livres'] == []
    assert result['financiamentos_sbpe_mensal'][0]['ano'] == 2026
    assert result['financiamentos_sbpe_mensal'][0]['unidades_financiadas'] == 12
    assert result['financiamentos_historico_anual'][0]['ano'] == 2025
    assert result['poupanca_saldos_mensais'][0]['ano'] == 2025
    assert result['financiamentos_por_instituicao'][0]['volume_mensal_milhoes'] == 78
    assert all(not isinstance(v, (dict, list)) for rows in result.values() for row in rows for v in row.values())


@pytest.mark.parametrize('value', [True, '1.234', float('inf'), float('nan')])
def test_rejects_unresolved_numeric_values(value):
    with pytest.raises(ValueError):
        numeric_value(value)


def test_quarter_notes_replaced_as_same_partition():
    assert merge_company_rows([{'periodo_referencia': '2T26 (a)'}], [{'periodo_referencia': '2T26'}]) == [{'periodo_referencia': '2T26'}]
    assert rows_fingerprint([{'valor': 1, 'exportado_em': 'a'}]) == rows_fingerprint([{'valor': 1, 'exportado_em': 'b'}])


def test_target_conditional_headers_and_conflict_propagation():
    class Client:
        def _execute(self, *args, **kwargs):
            self.headers = kwargs['headers']
            if self.headers.get('If-Match') == 'outdated':
                raise RuntimeError('PreconditionFailed')
            return SimpleNamespace(release_conn=lambda: None)
    client = Client()
    repo = RawRepository(RawStorageConfig('localhost:9000', 'test', 'test'), client=client)
    repo.write_rows('raw/test.json', [], None)
    assert client.headers['If-None-Match'] == '*'
    repo.write_rows('raw/test.json', [], 'etag')
    assert client.headers['If-Match'] == 'etag'
    with pytest.raises(RuntimeError):
        repo.write_rows('raw/test.json', [], 'outdated')
    with pytest.raises(ValueError):
        repo.write_rows('stage/test.json', [], None)


def test_target_config_endpoint_override_and_secrets_hidden(monkeypatch):
    monkeypatch.setenv('UI_HOST', 'https://prod.example')
    monkeypatch.setenv('UI_PORT', '9001')
    monkeypatch.setenv('UI_ACCESS_USER', 'username')
    monkeypatch.setenv('UI_SECRET_KEY', 'supersecret')
    monkeypatch.setenv('RAW_TARGET_SECURE', '')
    config = load_raw_storage_config()
    assert config.secure
    assert 'supersecret' not in repr(config) and 'username' not in repr(config)
    monkeypatch.setenv('RAW_TARGET_ENDPOINT', 'minio:9000')
    assert load_raw_storage_config().endpoint == 'minio:9000'
    assert not load_raw_storage_config().secure


def test_rejects_missing_required_abecip_collections():
    with pytest.raises(ValueError, match="colecao obrigatoria"):
        abecip_rows({}, {"competencia_referencia": "2026-09"})


def test_rejects_derived_company_metrics():
    source, target = Source(), Target()
    key = add_source(source)
    source.data[key]["balancos_das_empresas"]["vendas"]["tipo"] = "percentual"
    use = RawIngestionUseCase(source, target)
    with pytest.raises(ValueError, match="valores brutos"):
        use.ingest(use.discover({})[0], execution_id="raw", simulate=False)
    assert not source.writes and not target.writes


def test_required_failure_cannot_be_hidden_by_summary():
    source = Source()
    key = add_source(source)
    source.data[key.replace("schema_saida_resolvido", "auditoria_resolucao")]["auditoria_resolucao"] = [
        {"obrigatorio": True, "status_resolucao": "nao_resolvido"},
    ]
    assert RawIngestionUseCase(source, Target()).discover({}) == []
