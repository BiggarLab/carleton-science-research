"""Live check of the patent lookups (counts only, never the key)."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import signals as SIG
ROOT = Path(__file__).resolve().parent.parent
people = json.loads((ROOT / "docs/data.json").read_text())["people"]
out = []
SIG.log = lambda *a: out.append(" ".join(str(x) for x in a))
pat = SIG.carleton_patents(people, 2016)
out.append(f"Science researchers with Carleton patents: {len(pat)}")
for i, v in list(pat.items())[:6]:
    out.append(f"  {people[i]['n']}: {len(v)} e.g. {v[0][:90]}")
for kw in (["Antimicrobial peptides"], ["Acoustic telemetry fish"], ["Atomic layer deposition precursors"]):
    out.append(f"landscape {kw}: {SIG.patent_landscape(kw)}")
(ROOT / "state/key_check.log").write_text("\n".join(out) + "\n")
print("\n".join(out))
