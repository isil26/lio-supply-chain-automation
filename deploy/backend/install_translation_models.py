"""Install the Argos English translation models used by the supplier mail interpreter."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
from urllib.request import urlretrieve
import zipfile

# Official packages published in argosopentech/argospm-index.
PACKAGES = {
    "pl": ("pl_en-1_9", "07eda9edbd6ae5121df7c1d7bd847030423269b8c5056f1c222495c4a81e1721"),
    "zh": ("zh_en-1_9", "62e7af5a3a48b530e47b7b3e5c78c2de79073ecd815750d2bf3ab35b4a67da2d"),
    "ko": ("ko_en-1_1", "6da8f3db6ca40f42b1875570a1c06856f6e17c7ef62845d85de217ba548c1471"),
    "en-pl": ("en_pl-1_9", "85d865369326b6d8220876fbd7bc552fa5ec8b99e81161fab4a26f78187cedbc"),
    "en-zh": ("en_zh-1_9", "433e7c4f034d87fbe2353161e05f18646d7999452f801a4e1f0378522b9850ab"),
    "en-ko": ("en_ko-1_1", "e03d8e65e6d44525ec5808c3409fcf8728c76c2c76925372b6d3dc3278de17fc"),
}


def install(root, downloads=None):
    root.mkdir(exist_ok=True, parents=True)
    for lang, (name, digest) in PACKAGES.items():
        target = root / lang
        if target.is_dir():
            continue
        with TemporaryDirectory(dir=root) as stage:
            tmp = Path(stage)
            package = downloads / (name + ".argosmodel") if downloads else tmp / "package"
            if not downloads:
                urlretrieve(f"https://argos-net.com/v1/translate-{name}.argosmodel", package)
            with package.open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != digest:
                    raise ValueError(f"Unexpected checksum for {name}")
            dest = tmp / "install"
            with zipfile.ZipFile(package) as archive:
                meta = next(p for p in archive.namelist() if p.endswith("/metadata.json"))
                prefix = meta.removesuffix("metadata.json")
                info = json.loads(archive.read(meta))
                if [info["from_code"], info["to_code"]] != name.split("-")[0].split("_"):
                    raise ValueError(f"Unexpected languages for {name}")
                for member in archive.namelist():
                    relative = member.removeprefix(prefix)
                    if relative not in ("sentencepiece.model","bpe.model","model/config.json","model/model.bin",
                                        "model/shared_vocabulary.json","model/shared_vocabulary.txt","README.md"):
                        continue
                    path = dest / relative
                    path.parent.mkdir(exist_ok=True, parents=True)
                    with archive.open(member) as source, path.open("wb") as out:
                        shutil.copyfileobj(source, out)
            dest.rename(target)
        print(f"Installed {name}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("/opt/lio/translation-models"))
    parser.add_argument("--downloads", type=Path)
    args = parser.parse_args()
    install(args.root, args.downloads)
