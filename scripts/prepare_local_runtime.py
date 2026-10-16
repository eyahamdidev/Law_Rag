"""Download pinned, verifiable CPU LLM and OCR resources into ignored data/."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

def read_json(url):
    with urllib.request.urlopen(url, timeout=60) as response:
        return json.load(response)

def download(url, target, expected=None):
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and expected and hashlib.sha256(target.read_bytes()).hexdigest() == expected:
        return target
    partial = target.with_suffix(target.suffix + ".partial")
    for attempt in range(5):
        offset = partial.stat().st_size if partial.exists() else 0
        request = urllib.request.Request(url, headers={"Range": f"bytes={offset}-"} if offset else {})
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                mode = "ab" if offset and response.status == 206 else "wb"
                with partial.open(mode) as output:
                    size = offset if mode == "ab" else 0
                    last = size // (64 * 1024 * 1024)
                    for block in iter(lambda: response.read(1024 * 1024), b""):
                        output.write(block)
                        size += len(block)
                        if size // (64 * 1024 * 1024) != last:
                            last = size // (64 * 1024 * 1024)
                            print(f"{target.name}: {size // (1024 * 1024)} MiB", flush=True)
            if expected:
                digest = hashlib.sha256()
                with partial.open("rb") as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(block)
                if digest.hexdigest() != expected:
                    raise ValueError("SHA-256 mismatch")
            partial.replace(target)
            print(f"Ready: {target.name}", flush=True)
            return target
        except Exception as error:
            print(f"Retry {attempt + 1}/5: {target.name} ({type(error).__name__})", flush=True)
            if attempt == 4:
                raise

def prepare_llm():
    tag = "b11669"
    release = read_json(f"https://api.github.com/repos/ggml-org/llama.cpp/releases/tags/{tag}")
    asset = next(a for a in release["assets"] if a["name"] == f"llama-{tag}-bin-win-cpu-x64.zip")
    digest = asset.get("digest", "").removeprefix("sha256:") or None
    archive = download(asset["browser_download_url"], DATA / "downloads" / asset["name"], digest)
    runtime = DATA / "runtime" / "llama"
    runtime.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as package:
        for member in package.infolist():
            if not (runtime / member.filename).resolve().is_relative_to(runtime.resolve()):
                raise ValueError("Unsafe runtime archive path")
        package.extractall(runtime)
    repository = "ggml-org/Qwen3-1.7B-GGUF"
    revision = "daeb8e2d528a760970442092f6bf1e55c3b659eb"
    metadata = read_json(f"https://huggingface.co/api/models/{repository}/revision/{revision}?blobs=true")
    name = "Qwen3-1.7B-Q4_K_M.gguf"
    model = next(x for x in metadata["siblings"] if x["rfilename"] == name)
    expected = model.get("lfs", {}).get("sha256")
    if not expected:
        raise ValueError("Model metadata does not provide a SHA-256")
    download(f"https://huggingface.co/{repository}/resolve/{metadata['sha']}/{name}", DATA / "models" / name, expected)
    (DATA / "runtime" / "llm-provenance.json").write_text(json.dumps({
        "runtime_release": tag, "runtime_asset": asset["name"], "runtime_sha256": digest,
        "model_repository": repository, "model_revision": metadata["sha"], "model_file": name, "model_sha256": expected,
    }, indent=2), encoding="utf-8")

def prepare_ocr():
    release = read_json("https://api.github.com/repos/simonflueckiger/tesserocr-windows_build/releases/tags/tesserocr-v2.11.0-tesseract-5.5.3")
    asset = next(a for a in release["assets"] if a["name"] == "tesserocr-2.11.0-cp312-cp312-win_amd64.whl")
    download(asset["browser_download_url"], DATA / "downloads" / asset["name"], asset.get("digest", "").removeprefix("sha256:") or None)
    revision = read_json("https://api.github.com/repos/tesseract-ocr/tessdata_fast/commits/main")["sha"]
    for language in ("ara", "fra", "eng"):
        download(f"https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/{revision}/{language}.traineddata", DATA / "tessdata" / f"{language}.traineddata")
    (DATA / "tessdata" / "provenance.json").write_text(json.dumps({"repository": "tesseract-ocr/tessdata_fast", "revision": revision}, indent=2), encoding="utf-8")

if __name__ == "__main__":
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(prepare_llm), executor.submit(prepare_ocr)]
        for future in futures:
            future.result()
    print("Local runtime resources prepared.", flush=True)
