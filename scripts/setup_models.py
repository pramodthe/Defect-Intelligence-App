"""Explicit local model-cache setup. Does not read company documents."""
import argparse
import json
from pathlib import Path
from huggingface_hub import HfApi, snapshot_download

parser = argparse.ArgumentParser()
parser.add_argument("--download", action="store_true", required=True)
parser.add_argument("--tokenizer-only", action="store_true")
parser.add_argument("--revision", default=None)
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
repo = "BAAI/bge-base-en-v1.5"
revision = args.revision or HfApi().model_info(repo).sha
target = root / ".cache/models/bge-base-en-v1.5" / revision
patterns = ["*.json", "vocab.txt", "tokenizer*", "special_tokens_map.json"] if args.tokenizer_only else ["*.json", "*.safetensors", "vocab.txt", "tokenizer*", "1_Pooling/*"]
snapshot_download(repo, revision=revision, local_dir=target, allow_patterns=patterns)
manifest = {"model": repo, "revision": revision, "dimension": 768, "max_tokens": 512,
            "chunk_hard_limit": 480, "cache_path": str(target), "weights_present": not args.tokenizer_only}
(root / "data").mkdir(exist_ok=True)
(root / "data/model-profile.json").write_text(json.dumps(manifest, indent=2), "utf-8")
print(json.dumps(manifest, indent=2))
