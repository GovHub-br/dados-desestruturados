import sys, types, importlib, json, glob
from pathlib import Path
root = Path(sys.argv[1])
pkg = types.ModuleType("docling_pipeline"); pkg.__path__ = [str(root / "docling_pipeline")]; sys.modules["docling_pipeline"] = pkg
ext = types.ModuleType("docling_pipeline.extractors"); ext.__path__ = [str(root / "docling_pipeline" / "extractors")]; sys.modules["docling_pipeline.extractors"] = ext
T = importlib.import_module("docling_pipeline.extractors.tables")
B = Path(__file__).resolve().parents[3] / "airflow/state/resolution_inputs"
d = glob.glob(str(B / "dag_detecta_pdf_e_extrai__santander__*/extraction"))[0]
items = json.load(open(f"{d}/tables/metadata.json"))["items"]
print(f"== {root.name}")
for i, it in enumerate(items[:5], 1):
    s = json.load(open(f"{d}/{it['path']}"))["schema"]
    cells = [(c[:26], T._value_is_data_like(T.normalize_space(c))) for c in s]
    print(f" tab#{i} p{it['page_number']} width={len(s)} usable={T._header_is_usable(s)} looks_data={T._schema_looks_like_data(s)} generic={T._columns_are_generic(s)}")
    print("      celulas data-like:", [(c, f) for c, f in cells if f] or "nenhuma", "| n_celulas=", len(s))
