"""Guard: reader-facing methodology prose must not leak module code paths.

evidence_reason / conclusion strings surface in the 方法与附录 appendix a merchant
reads. Dotted module paths like ``analytics.benchmark.self_percentile`` are engineer
noise there. This scans the analysis package's string *literals* (import lines and
``#`` comments excluded — those are for developers) for an ``analytics.<mod>.<fn>``
path and fails if any survives, so a future edit can't silently reintroduce one.
"""
import re
from pathlib import Path

_ANALYSIS_DIR = Path(__file__).resolve().parent.parent / "xhs_ceramics_analytics" / "analysis"
# a dotted module reference (``analytics.text_mining`` or ``analytics.benchmark.fn``)
_CODE_PATH = re.compile(r"analytics\.[a-z_]+")


def _prose_lines(text: str):
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#") or stripped.startswith(("import ", "from ")):
            continue
        # drop trailing inline comments so a commented path doesn't false-positive
        code = line.split("#", 1)[0]
        yield code


def test_no_module_code_paths_in_analysis_prose():
    offenders = []
    for path in sorted(_ANALYSIS_DIR.glob("*.py")):
        for i, line in enumerate(_prose_lines(path.read_text(encoding="utf-8")), 1):
            if _CODE_PATH.search(line):
                offenders.append(f"{path.name}: {line.strip()}")
    assert not offenders, "module code paths leaked into reader prose:\n" + "\n".join(offenders)
