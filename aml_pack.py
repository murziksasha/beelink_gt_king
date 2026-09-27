import os
import struct
import hashlib
import zlib
import sys

AML_IMG_MAGIC = 0x27B51956
HEADER_SIZE = 64
ITEM_HEADER_SIZE = 576
MAX_ITEMS = 28

def unpack_aml_image(img_path: str, output_dir: str):
    """Unpacks all partitions from an Amlogic firmware image."""
    os.makedirs(output_dir, exist_ok=True)
    with open(img_path, 'rb') as fin:
        hdr = fin.read(HEADER_SIZE)
        crc, ver, magic, file_sz, _, _, item_num = struct.unpack('<IIIIIII', hdr[:28])
        if magic != AML_IMG_MAGIC:
            raise ValueError(f"Invalid magic: {hex(magic)}, expected {hex(AML_IMG_MAGIC)}")
        
        items = []
        for i in range(item_num):
            ih = fin.read(ITEM_HEADER_SIZE)
            off, sz = struct.unpack('<QQ', ih[16:32])
            ext = ih[32:64].split(b'\x00')[0].decode('ascii', errors='ignore')
            base = ih[288:320].split(b'\x00')[0].decode('ascii', errors='ignore')
            items.append((base, ext, off, sz))
            
        seen_files = set()
        for base, ext, off, sz in items:
            if ext == "VERIFY" or sz == 0 or not base:
                continue
            filename = f"{base}.{ext}"
            target_path = os.path.join(output_dir, filename)
            if filename in seen_files:
                continue
            seen_files.add(filename)
            fin.seek(off)
            data = fin.read(sz)
            with open(target_path, 'wb') as fout:
                fout.write(data)
            print(f"  Extracted: {filename} ({sz:,} bytes)")

def pack_aml_image(unpack_dir: str, output_img: str, template_img: str):
    """Packs all partitions from unpack_dir into a flashable Amlogic firmware image using template_img."""
    print(f"Packing partitions from '{unpack_dir}' into '{output_img}'...")
    with open(template_img, 'rb') as f_tpl:
        tpl_hdr = f_tpl.read(HEADER_SIZE)
        _, ver, magic, _, _, _, item_num = struct.unpack('<IIIIIII', tpl_hdr[:28])
        if magic != AML_IMG_MAGIC:
            raise ValueError(f"Template image invalid magic: {hex(magic)}")
        if item_num != MAX_ITEMS:
            raise ValueError(f"Template image item count {item_num} != {MAX_ITEMS}")
            
        tpl_items = []
        for i in range(item_num):
            ih = f_tpl.read(ITEM_HEADER_SIZE)
            off, sz = struct.unpack('<QQ', ih[16:32])
            ext = ih[32:64].split(b'\x00')[0].decode('ascii', errors='ignore')
            base = ih[288:320].split(b'\x00')[0].decode('ascii', errors='ignore')
            tpl_items.append({
                'idx': i,
                'raw_hdr': bytearray(ih),
                'base': base,
                'ext': ext,
                'tpl_off': off,
                'tpl_sz': sz
            })

    # Prepare payloads
    # Shared files mapping: key is (base, ext) -> payload bytes
    loaded_files = {}
    item_payloads = [None] * item_num
    
    # Pass 1: Load non-VERIFY partitions
    for item in tpl_items:
        i = item['idx']
        base = item['base']
        ext = item['ext']
        if ext == "VERIFY":
            continue
        fname = f"{base}.{ext}"
        fpath = os.path.join(unpack_dir, fname)
        if not os.path.exists(fpath):
            raise FileNotFoundError(f"Required partition file not found: {fpath}")
        if fname not in loaded_files:
            with open(fpath, 'rb') as f:
                loaded_files[fname] = f.read()
        item_payloads[i] = loaded_files[fname]

    # Pass 2: Calculate VERIFY blocks (sha1sum of preceding item)
    for item in tpl_items:
        i = item['idx']
        if item['ext'] == "VERIFY":
            prev_i = i - 1
            prev_payload = item_payloads[prev_i]
            sha1_hex = hashlib.sha1(prev_payload).hexdigest()
            verify_str = f"sha1sum {sha1_hex}".encode('ascii')
            assert len(verify_str) == 48
            item_payloads[i] = verify_str

    # Pass 3: Layout offsets
    # Items with identical template offsets share the same physical payload in the file
    # Map tpl_off -> assigned new offset
    tpl_off_to_new_off = {}
    current_off = HEADER_SIZE + item_num * ITEM_HEADER_SIZE # 16192
    
    item_new_offsets = [0] * item_num
    item_new_sizes = [0] * item_num
    
    # To preserve exact file layout order, we process unique offsets in order of tpl_off
    # But wait, let's process sequentially as appeared
    for item in tpl_items:
        i = item['idx']
        payload = item_payloads[i]
        item_new_sizes[i] = len(payload)
        t_off = item['tpl_off']
        
        if t_off in tpl_off_to_new_off:
            item_new_offsets[i] = tpl_off_to_new_off[t_off]
        else:
            # Align to 4 bytes if needed
            current_off = (current_off + 3) & ~3
            tpl_off_to_new_off[t_off] = current_off
            item_new_offsets[i] = current_off
            current_off += len(payload)

    total_file_size = current_off
    print(f"Total calculated image size: {total_file_size:,} bytes")

    # Pass 4: Build output file
    with open(output_img, 'wb') as fout:
        # Placeholder header
        main_hdr = bytearray(tpl_hdr)
        struct.pack_into('<IIIIIII', main_hdr, 0, 0, ver, AML_IMG_MAGIC, total_file_size, 0, 4, item_num)
        fout.write(main_hdr)
        
        # Write 28 item headers
        for item in tpl_items:
            i = item['idx']
            ih = item['raw_hdr']
            struct.pack_into('<QQ', ih, 16, item_new_offsets[i], item_new_sizes[i])
            fout.write(ih)
            
        # Write payloads in order of physical offsets
        written_offsets = set()
        for item in tpl_items:
            i = item['idx']
            off = item_new_offsets[i]
            if off in written_offsets:
                continue
            written_offsets.add(off)
            pad_needed = off - fout.tell()
            if pad_needed > 0:
                fout.write(b'\x00' * pad_needed)
            elif pad_needed < 0:
                raise ValueError(f"Offset collision at {off}, tell is {fout.tell()}")
            fout.write(item_payloads[i])
            
        pad_end = total_file_size - fout.tell()
        if pad_end > 0:
            fout.write(b'\x00' * pad_end)

    # Pass 5: Compute streaming inverted CRC32 and update header
    print("Computing streaming inverted CRC32...")
    with open(output_img, 'r+b') as f:
        f.seek(4)
        crc = 0
        while chunk := f.read(16 * 1024 * 1024):
            crc = zlib.crc32(chunk, crc)
        final_crc = (~crc) & 0xFFFFFFFF
        f.seek(0)
        f.write(struct.pack('<I', final_crc))
        
    print(f"Successfully packaged {output_img} (CRC: {hex(final_crc)})")
    verify_aml_image(output_img)

def verify_aml_image(img_path: str):
    """Validates an Amlogic image against strict Burning Tool integrity constraints."""
    print(f"Verifying Amlogic image: {img_path}...")
    with open(img_path, 'rb') as f:
        hdr = f.read(64)
        stored_crc, ver, magic, file_sz, _, _, item_num = struct.unpack('<IIIIIII', hdr[:28])
        assert magic == AML_IMG_MAGIC, f"Magic mismatch: {hex(magic)} != {hex(AML_IMG_MAGIC)}"
        assert item_num == MAX_ITEMS, f"Item count mismatch: {item_num} != {MAX_ITEMS}"
        actual_file_sz = os.path.getsize(img_path)
        assert actual_file_sz == file_sz, f"Size mismatch: actual {actual_file_sz} != header {file_sz}"
        
        f.seek(4)
        crc = 0
        while chunk := f.read(16 * 1024 * 1024):
            crc = zlib.crc32(chunk, crc)
        calc_crc = (~crc) & 0xFFFFFFFF
        assert stored_crc == calc_crc, f"CRC mismatch: stored {hex(stored_crc)} != calculated {hex(calc_crc)}"
        
    print("  [OK] Header Magic: 0x27B51956")
    print(f"  [OK] Item Count: {item_num} items")
    print(f"  [OK] Inverted CRC32: {hex(stored_crc)} matches data stream exactly")
    print("  [OK] Burning Tool Pre-flash Verification PASSED!")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python aml_pack.py <unpack_dir> <output_img> [template_img]")
        sys.exit(1)
    u_dir = sys.argv[1]
    o_img = sys.argv[2]
    t_img = sys.argv[3] if len(sys.argv) > 3 else "sbx_beelink_gtking_p0_aosp_9_20.img"
    pack_aml_image(u_dir, o_img, t_img)
