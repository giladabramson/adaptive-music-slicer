"""One-off: in the mixer's HTML, drop the separate <div class="dm-meter">
elements (the dancing bars sat there). Their job moves into the slider
track itself via the --energy CSS variable. Safe to delete after.
"""
from pathlib import Path
import re

HTML = Path(__file__).resolve().parents[1] / "index.html"
src = HTML.read_text(encoding="utf-8")

# Drop the four <div class="dm-meter" id="dm-meter-X"></div> lines inside .dm-stem
pattern = re.compile(r'\s*<div class="dm-meter" id="dm-meter-(drums|bass|other|vocals)"></div>')
new_src, n = pattern.subn("", src)
HTML.write_text(new_src, encoding="utf-8")
print(f"removed {n} dm-meter divs")
