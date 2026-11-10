#!/usr/bin/env python3
"""Set the master logo and all icons to the user's original image, as-is."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_from_reference as b
from PIL import Image

b.save_icons()
b.load_reference().resize((1024, 1024), Image.LANCZOS).save(
    os.path.join(b.OUT, "nspanel-core-logo.png"))
print("logo + icons = the user's original image, unchanged")
