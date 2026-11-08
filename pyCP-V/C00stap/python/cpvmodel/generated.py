"""The docs that are generated from the model. ``python -m cpvmodel docs`` rewrites them; a
test fails when one is out of date."""

from .diagrams import renderStateDiagram
from .glossary import REPO_ROOT, renderGlossary

GENERATED_DOCS = {
    REPO_ROOT / "docs" / "model" / "glossary.md": renderGlossary,
    REPO_ROOT / "docs" / "model" / "states.md": renderStateDiagram,
}


def writeGeneratedDocs():
    for path, render in GENERATED_DOCS.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render(), encoding="utf-8", newline="\n")
    return list(GENERATED_DOCS)


def staleDocs():
    stale = []
    for path, render in GENERATED_DOCS.items():
        if not path.exists() or path.read_text(encoding="utf-8") != render():
            stale.append(path.name)
    return stale
