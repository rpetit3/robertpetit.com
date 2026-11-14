"""Sort the cv.yml presentations block by date, newest first."""

import re
from pathlib import Path

path = Path("data/cv.yml")
lines = path.read_text(encoding="utf-8").splitlines()

start = next(i for i, line in enumerate(lines) if line.startswith("presentations:"))
end = next(i for i, line in enumerate(lines) if line.startswith("teaching:"))

body = lines[start + 1 : end]
chunks: list[list[str]] = []
for line in body:
    if not chunks or (line == "" and chunks[-1] and chunks[-1][-1] != ""):
        chunks.append([line])
    elif line == "" and chunks[-1][-1] == "":
        continue
    else:
        chunks[-1].append(line)
chunks = [[line for line in chunk if line != ""] for chunk in chunks]
chunks = [c for c in chunks if c]

assert chunks and all(c[0].startswith("  - title:") for c in chunks)

dates = []
for c in chunks:
    match = next(line for line in c if line.startswith("    date: "))
    dates.append(re.match(r"    date: (\S+)", match).group(1))
assert len(dates) == len(chunks)

order = sorted(range(len(chunks)), key=lambda i: dates[i], reverse=True)
new_body = []
for i in order:
    new_body.extend(chunks[i])
    new_body.append("")

out = "\n".join(lines[: start + 1] + new_body + lines[end:]) + "\n"
path.write_text(out, encoding="utf-8")
print("reordered", len(chunks), "entries; first", dates[order[0]], "last", dates[order[-1]])