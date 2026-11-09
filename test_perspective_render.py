#!/usr/bin/env python
"""Quick test: render 3 seconds with new perspective camera"""
import subprocess
import json
from pathlib import Path
from datetime import datetime

# Extract first 3 seconds for quick test
test_input = Path('output/input/test_perspective_3sec.mp4')
if not test_input.exists():
    print("Extracting 3-second test clip...")
    subprocess.run([
        'ffmpeg', '-i', 'output/input/344534535_EP1_分镜1_原片.mp4',
        '-t', '3', '-c:v', 'libx264', '-crf', '23',
        '-an', str(test_input)
    ], check=True)
    print(f"Created: {test_input}")

# Generate test project ID
test_id = f"perspective_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
print(f"\nTest project: {test_id}")
print("This will use the NEW template with:")
print("  - Perspective camera (65 deg FOV)")
print("  - Ground plane at Z=-1.6")
print("  - Improved depth range")
print("\nReady to run: python -m whiteblock.pipeline test_perspective_3sec.mp4")
