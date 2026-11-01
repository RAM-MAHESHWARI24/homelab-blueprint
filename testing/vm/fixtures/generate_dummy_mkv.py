#!/usr/bin/env python3
"""
Homelab Blueprint - Deterministic Dummy MKV Video Generator
Generates a valid Matroska (.mkv) video file for offline E2E integration testing.
Uses ffmpeg if installed, or synthesizes a valid compliant EBML/Matroska container.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

# Ensure UTF-8 output on Windows cp1252 terminals
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def generate_with_ffmpeg(output_path: Path, target_size_bytes: int = 5 * 1024 * 1024) -> bool:
    """Attempts to generate a real 1080p MKV using ffmpeg"""
    ffmpeg_bin = shutil.which("ffmpeg")
    if not ffmpeg_bin:
        return False

    try:
        cmd = [
            ffmpeg_bin,
            "-y",
            "-f", "lavfi", "-i", "testsrc=duration=3:size=1920x1080:rate=24",
            "-f", "lavfi", "-i", "sine=frequency=1000:duration=3",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "28",
            "-c:a", "aac",
            "-b:a", "128k",
            str(output_path)
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=30)
        if result.returncode == 0 and output_path.exists():
            # Pad file to target_size_bytes if needed
            current_size = output_path.stat().st_size
            if current_size < target_size_bytes:
                with open(output_path, "ab") as f:
                    f.write(b"\x00" * (target_size_bytes - current_size))
            return True
    except Exception:
        pass
    return False


def _ebml_varint(val: int) -> bytes:
    """Encodes an integer into EBML variable length integer format"""
    if val < 0x7F:
        return bytes([0x80 | val])
    elif val < 0x3FFF:
        return bytes([0x40 | (val >> 8), val & 0xFF])
    elif val < 0x1FFFFF:
        return bytes([0x20 | (val >> 16), (val >> 8) & 0xFF, val & 0xFF])
    elif val < 0x0FFFFFFF:
        return bytes([0x10 | (val >> 24), (val >> 16) & 0xFF, (val >> 8) & 0xFF, val & 0xFF])
    else:
        # 8-byte varint
        return bytes([
            0x01,
            (val >> 48) & 0xFF, (val >> 40) & 0xFF, (val >> 32) & 0xFF,
            (val >> 24) & 0xFF, (val >> 16) & 0xFF, (val >> 8) & 0xFF, val & 0xFF
        ])


def _ebml_element(element_id: bytes, data: bytes) -> bytes:
    """Wraps data inside an EBML element with variable-length size"""
    return element_id + _ebml_varint(len(data)) + data


def _ebml_uint(element_id: bytes, val: int) -> bytes:
    """Encodes an unsigned integer EBML element"""
    if val == 0:
        return element_id + b"\x81\x00"
    b = []
    v = val
    while v > 0:
        b.append(v & 0xFF)
        v >>= 8
    b.reverse()
    return element_id + _ebml_varint(len(b)) + bytes(b)


def _ebml_string(element_id: bytes, text: str) -> bytes:
    """Encodes an ASCII/UTF-8 string EBML element"""
    b = text.encode("utf-8")
    return element_id + _ebml_varint(len(b)) + b


def generate_synthesized_mkv(output_path: Path, target_size_bytes: int = 5 * 1024 * 1024) -> None:
    """
    Synthesizes a valid Matroska (MKV) container with EBML header,
    Segment, Info, Video track (1080p AVC/H.264), Audio track (AAC),
    and Cluster blocks padded to the requested target size.
    """
    # 1. EBML Header (0x1A45DFA3)
    ebml_header_data = (
        _ebml_uint(b"\x42\x86", 1) +          # EBMLVersion = 1
        _ebml_uint(b"\x42\xF7", 1) +          # EBMLReadVersion = 1
        _ebml_uint(b"\x42\xF2", 4) +          # EBMLMaxIDLength = 4
        _ebml_uint(b"\x42\xF3", 8) +          # EBMLMaxSizeLength = 8
        _ebml_string(b"\x42\x82", "matroska") + # DocType = matroska
        _ebml_uint(b"\x42\x87", 4) +          # DocTypeVersion = 4
        _ebml_uint(b"\x42\x85", 2)            # DocTypeReadVersion = 2
    )
    ebml_header = _ebml_element(b"\x1A\x45\xDF\xA3", ebml_header_data)

    # 2. Segment -> Info (0x1549A966)
    info_data = (
        _ebml_uint(b"\x2A\xD7\xB1", 1000000) +  # TimecodeScale = 1ms
        _ebml_string(b"\x4D\x80", "HomelabE2EMock") + # MuxingApp
        _ebml_string(b"\x57\x41", "HomelabMediaTest")  # WritingApp
    )
    info_element = _ebml_element(b"\x15\x49\xA9\x66", info_data)

    # 3. Video Track (Track 1)
    video_settings = (
        _ebml_uint(b"\xB0", 1920) +             # PixelWidth = 1920
        _ebml_uint(b"\xBA", 1080)               # PixelHeight = 1080
    )
    video_track = (
        _ebml_uint(b"\xD7", 1) +                # TrackNumber = 1
        _ebml_uint(b"\x73\xC5", 1) +            # TrackUID = 1
        _ebml_uint(b"\x83", 1) +                # TrackType = 1 (video)
        _ebml_string(b"\x86", "V_MPEG4/ISO/AVC") + # CodecID = H.264
        _ebml_string(b"\x53\x6E", "1080p Video") + # Name
        _ebml_element(b"\xE0", video_settings)  # VideoSettings
    )

    # 4. Audio Track (Track 2)
    audio_settings = (
        _ebml_uint(b"\x9F", 2)                  # Channels = 2
    )
    audio_track = (
        _ebml_uint(b"\xD7", 2) +                # TrackNumber = 2
        _ebml_uint(b"\x73\xC5", 2) +            # TrackUID = 2
        _ebml_uint(b"\x83", 2) +                # TrackType = 2 (audio)
        _ebml_string(b"\x86", "A_AAC") +        # CodecID = AAC
        _ebml_string(b"\x53\x6E", "AAC 2.0 Audio") + # Name
        _ebml_element(b"\xE1", audio_settings)  # AudioSettings
    )

    # Tracks Element (0x1654AE6B)
    tracks_data = (
        _ebml_element(b"\xAE", video_track) +
        _ebml_element(b"\xAE", audio_track)
    )
    tracks_element = _ebml_element(b"\x16\x54\xAE\x6B", tracks_data)

    # 5. Cluster (0x1F43B675) with SimpleBlocks
    # SimpleBlock: Track 1, Timecode 0, Flags 0x80 (keyframe) + dummy H.264 slice
    dummy_nal = b"\x00\x00\x00\x01\x67\x42\x00\x1f\xda\x01\x40\x16\xe8"  # SPS
    dummy_nal += b"\x00\x00\x00\x01\x68\xce\x06\xe2"                    # PPS
    dummy_nal += b"\x00\x00\x00\x01\x65\x88\x84\x00\x10\xff"            # IDR slice
    simple_block_data = b"\x81\x00\x00\x80" + dummy_nal                  # Track 1, timecode 0, keyframe
    simple_block = _ebml_element(b"\xA3", simple_block_data)

    cluster_header = (
        _ebml_uint(b"\xE7", 0) +               # Timecode = 0
        simple_block
    )

    # Calculate padding needed to hit target_size_bytes exactly
    header_overhead = len(ebml_header) + 12     # 12 bytes for Segment ID + size header
    content_without_cluster = len(info_element) + len(tracks_element)
    cluster_overhead = 12 + len(cluster_header) # Cluster ID + size + header

    payload_size = target_size_bytes - (header_overhead + content_without_cluster + cluster_overhead)
    if payload_size < 1024:
        payload_size = 1024

    # Add dummy payload blocks inside cluster
    # Void element ID is 0xEC
    void_element = b"\xEC" + _ebml_varint(payload_size) + (b"\xAA" * payload_size)
    cluster_element = _ebml_element(b"\x1F\x43\xB6\x75", cluster_header + void_element)

    segment_data = info_element + tracks_element + cluster_element
    segment_element = _ebml_element(b"\x18\x53\x80\x67", segment_data)

    full_mkv = ebml_header + segment_element

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(full_mkv)


def main():
    dest = Path(__file__).resolve().parent / "dummy_movie.mkv"
    if len(sys.argv) > 1:
        dest = Path(sys.argv[1]).resolve()

    print(f"🎬 Generating test dummy MKV at '{dest}'...")
    if generate_with_ffmpeg(dest):
        print(f"✅ Generated via ffmpeg ({dest.stat().st_size} bytes)")
    else:
        generate_synthesized_mkv(dest)
        print(f"✅ Generated via EBML synthesizer ({dest.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
