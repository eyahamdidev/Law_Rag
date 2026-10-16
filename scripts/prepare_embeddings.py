"""Prepare pinned multilingual ONNX weights using system TLS trust and file hashes."""
import json
from pathlib import Path
from prepare_local_runtime import download, read_json

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "intfloat/multilingual-e5-small"
REVISION = "614241f622f53c4eeff9890bdc4f31cfecc418b3"

if __name__ == "__main__":
    metadata = read_json(f"https://huggingface.co/api/models/{REPOSITORY}/revision/{REVISION}?blobs=true")
    files = {x["rfilename"]: x for x in metadata["siblings"]}
    folder = ROOT / "data" / "models" / "e5_small_int8"
    names = ["onnx/model_qint8_avx512_vnni.onnx", "config.json", "tokenizer.json", "tokenizer_config.json", "special_tokens_map.json"]
    for name in names:
        expected = files[name].get("lfs", {}).get("sha256")
        download(f"https://huggingface.co/{REPOSITORY}/resolve/{REVISION}/{name}", folder / name, expected)
    (folder / "provenance.json").write_text(json.dumps({"repository": REPOSITORY, "revision": REVISION,
        "variant": "quantized ONNX, tested locally before use", "files": names}, indent=2), encoding="utf-8")
    print("Multilingual embedding resources ready.", flush=True)
