import os
import sys
from aml_pack import unpack_aml_image

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python aml_unpack.py <firmware.img> <output_directory>")
        sys.exit(1)
    img_path = sys.argv[1]
    out_dir = sys.argv[2]
    print(f"Unpacking {img_path} into {out_dir}...")
    unpack_aml_image(img_path, out_dir)
    print("Unpack completed successfully.")
