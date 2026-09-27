import os
import struct
import sys

SPARSE_HEADER_MAGIC = 0xED26FF3A
CHUNK_RAW = 0xCAC1
CHUNK_FILL = 0xCAC2
CHUNK_DONT_CARE = 0xCAC3
CHUNK_CRC32 = 0xCAC4

def sparse_to_raw(sparse_path: str, raw_path: str):
    """Converts an Android sparse image to a raw ext4 filesystem image."""
    print(f"Converting sparse image '{sparse_path}' -> raw '{raw_path}'...")
    with open(sparse_path, "rb") as fin, open(raw_path, "wb") as fout:
        header = fin.read(28)
        if len(header) < 28:
            raise ValueError("File too short for sparse header")
        
        magic, major, minor, file_hdr_sz, chunk_hdr_sz, blk_sz, total_blks, total_chunks, _ = struct.unpack(
            "<I4H4I", header
        )
        if magic != SPARSE_HEADER_MAGIC:
            raise ValueError(f"Invalid magic: {hex(magic)}, expected {hex(SPARSE_HEADER_MAGIC)}")

        for i in range(total_chunks):
            chunk_header = fin.read(12)
            if len(chunk_header) < 12:
                break
            c_type, _, chunk_sz, total_sz = struct.unpack("<2H2I", chunk_header)
            data_sz = total_sz - 12

            if c_type == CHUNK_RAW:
                chunk_data = fin.read(data_sz)
                fout.write(chunk_data)
            elif c_type == CHUNK_FILL:
                fill_val = fin.read(4)
                chunk_data = fill_val * (chunk_sz * blk_sz // 4)
                fout.write(chunk_data)
            elif c_type == CHUNK_DONT_CARE:
                fout.seek(chunk_sz * blk_sz, os.SEEK_CUR)
            elif c_type == CHUNK_CRC32:
                fin.read(4)
            else:
                raise ValueError(f"Unknown chunk type: {hex(c_type)} at chunk {i}")

    print(f"Sparse -> Raw conversion complete: {os.path.getsize(raw_path):,} bytes.")

def raw_to_sparse(raw_path: str, sparse_path: str, blk_sz: int = 4096):
    """Converts a raw ext4 filesystem image to an Android sparse image."""
    print(f"Converting raw image '{raw_path}' -> sparse '{sparse_path}'...")
    raw_size = os.path.getsize(raw_path)
    if raw_size % blk_sz != 0:
        raise ValueError(f"Raw image size ({raw_size}) is not a multiple of block size ({blk_sz})")

    total_blks = raw_size // blk_sz
    zero_block = b"\x00" * blk_sz
    chunks = []

    with open(raw_path, "rb") as fin:
        curr_type = None
        curr_blks = 0
        curr_data = bytearray()
        MAX_CHUNK_BLKS = 16384

        for blk_idx in range(total_blks):
            blk = fin.read(blk_sz)
            is_zero = (blk == zero_block)
            b_type = CHUNK_DONT_CARE if is_zero else CHUNK_RAW

            if curr_type is None:
                curr_type = b_type
                curr_blks = 1
                if b_type == CHUNK_RAW:
                    curr_data = bytearray(blk)
            elif curr_type == b_type and curr_blks < MAX_CHUNK_BLKS:
                curr_blks += 1
                if b_type == CHUNK_RAW:
                    curr_data.extend(blk)
            else:
                chunks.append((curr_type, curr_blks, bytes(curr_data) if curr_type == CHUNK_RAW else b""))
                curr_type = b_type
                curr_blks = 1
                curr_data = bytearray(blk) if b_type == CHUNK_RAW else bytearray()

        if curr_blks > 0:
            chunks.append((curr_type, curr_blks, bytes(curr_data) if curr_type == CHUNK_RAW else b""))

    total_chunks = len(chunks)
    print(f"Writing {total_chunks} sparse chunks ({total_blks} blocks)...")

    with open(sparse_path, "wb") as fout:
        file_header = struct.pack(
            "<I4H4I",
            SPARSE_HEADER_MAGIC,
            1,
            0,
            28,
            12,
            blk_sz,
            total_blks,
            total_chunks,
            0,
        )
        fout.write(file_header)

        for c_type, c_blks, c_data in chunks:
            total_sz = 12 + len(c_data)
            chunk_header = struct.pack("<2H2I", c_type, 0, c_blks, total_sz)
            fout.write(chunk_header)
            if c_data:
                fout.write(c_data)

    print(f"Raw -> Sparse conversion complete: {os.path.getsize(sparse_path):,} bytes.")

if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: sparse_tool.py [s2r|r2s] <src> <dst>")
        sys.exit(1)
    mode, src, dst = sys.argv[1], sys.argv[2], sys.argv[3]
    if mode == "s2r":
        sparse_to_raw(src, dst)
    elif mode == "r2s":
        raw_to_sparse(src, dst)
