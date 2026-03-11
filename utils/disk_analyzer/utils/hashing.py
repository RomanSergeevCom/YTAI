"""
File hashing utilities for duplicate detection
"""

import hashlib
import os
from typing import Optional, BinaryIO
from pathlib import Path


def hash_file_md5(filepath: str, chunk_size: int = 1024 * 1024) -> Optional[str]:
    """
    Calculate MD5 hash of entire file
    
    Args:
        filepath: Path to file
        chunk_size: Read chunk size (default 1MB)
    
    Returns:
        MD5 hash hex string or None on error
    """
    try:
        hasher = hashlib.md5()
        with open(filepath, 'rb') as f:
            while chunk := f.read(chunk_size):
                hasher.update(chunk)
        return hasher.hexdigest()
    except (IOError, OSError, PermissionError):
        return None


def hash_file_sha256(filepath: str, chunk_size: int = 1024 * 1024) -> Optional[str]:
    """
    Calculate SHA256 hash of entire file
    
    Args:
        filepath: Path to file
        chunk_size: Read chunk size (default 1MB)
    
    Returns:
        SHA256 hash hex string or None on error
    """
    try:
        hasher = hashlib.sha256()
        with open(filepath, 'rb') as f:
            while chunk := f.read(chunk_size):
                hasher.update(chunk)
        return hasher.hexdigest()
    except (IOError, OSError, PermissionError):
        return None


def hash_file_quick(filepath: str, sample_size: int = 64 * 1024) -> Optional[str]:
    """
    Quick partial hash: first + last + middle chunks
    Much faster for large files, good for initial duplicate grouping
    
    Args:
        filepath: Path to file
        sample_size: Size of each sample chunk (default 64KB)
    
    Returns:
        Composite hash hex string or None on error
    """
    try:
        file_size = os.path.getsize(filepath)
        
        if file_size <= sample_size * 3:
            # Small file - hash entire thing
            return hash_file_md5(filepath)
        
        hasher = hashlib.md5()
        
        with open(filepath, 'rb') as f:
            # Hash first chunk
            hasher.update(f.read(sample_size))
            
            # Hash middle chunk
            f.seek(file_size // 2)
            hasher.update(f.read(sample_size))
            
            # Hash last chunk
            f.seek(-sample_size, 2)  # 2 = SEEK_END
            hasher.update(f.read(sample_size))
        
        # Include file size in hash for extra safety
        hasher.update(str(file_size).encode())
        
        return hasher.hexdigest()
    
    except (IOError, OSError, PermissionError):
        return None


def hash_file_xxhash(filepath: str, chunk_size: int = 1024 * 1024) -> Optional[str]:
    """
    Calculate xxHash (very fast) if available, fallback to MD5
    
    Args:
        filepath: Path to file
        chunk_size: Read chunk size (default 1MB)
    
    Returns:
        Hash hex string or None on error
    """
    try:
        import xxhash
        hasher = xxhash.xxh64()
        with open(filepath, 'rb') as f:
            while chunk := f.read(chunk_size):
                hasher.update(chunk)
        return hasher.hexdigest()
    except ImportError:
        # xxhash not installed, fall back to MD5
        return hash_file_md5(filepath, chunk_size)
    except (IOError, OSError, PermissionError):
        return None


def get_file_signature(filepath: str, sig_size: int = 8192) -> Optional[bytes]:
    """
    Get file signature (magic bytes) for type detection
    
    Args:
        filepath: Path to file
        sig_size: Number of bytes to read (default 8KB)
    
    Returns:
        Bytes signature or None on error
    """
    try:
        with open(filepath, 'rb') as f:
            return f.read(sig_size)
    except (IOError, OSError, PermissionError):
        return None


def detect_file_type_by_signature(filepath: str) -> Optional[str]:
    """
    Detect file type by magic bytes signature
    
    Args:
        filepath: Path to file
    
    Returns:
        Detected file type or None
    """
    sig = get_file_signature(filepath, 32)
    if not sig:
        return None
    
    # Common file signatures
    signatures = {
        b'\x89PNG\r\n\x1a\n': 'png',
        b'\xff\xd8\xff': 'jpg',
        b'GIF87a': 'gif',
        b'GIF89a': 'gif',
        b'%PDF': 'pdf',
        b'PK\x03\x04': 'zip',  # Also docx, xlsx, etc
        b'Rar!\x1a\x07': 'rar',
        b'7z\xbc\xaf\x27\x1c': '7z',
        b'\x1f\x8b\x08': 'gz',
        b'BZh': 'bz2',
        b'\x00\x00\x00\x14ftyp': 'mp4',  # Or m4v, m4a
        b'\x00\x00\x00\x18ftyp': 'mp4',
        b'\x00\x00\x00\x1cftyp': 'mp4',
        b'\x00\x00\x00\x20ftyp': 'mp4',
        b'RIFF': 'avi',  # Or wav
        b'ID3': 'mp3',
        b'\xff\xfb': 'mp3',
        b'\xff\xfa': 'mp3',
        b'fLaC': 'flac',
        b'OggS': 'ogg',
        b'\x1aE\xdf\xa3': 'mkv',  # Or webm
        b'SQLite format 3': 'sqlite',
        b'bplist': 'plist',
        b'<?xml': 'xml',
        b'{\n': 'json',  # Rough guess
        b'[': 'json',    # Rough guess
    }
    
    for magic, filetype in signatures.items():
        if sig.startswith(magic):
            return filetype
    
    # Check for MOV (ftyp at offset 4)
    if len(sig) >= 12 and sig[4:8] == b'ftyp':
        brand = sig[8:12]
        if brand in (b'qt  ', b'MSNV'):
            return 'mov'
        elif brand in (b'isom', b'mp41', b'mp42', b'M4V ', b'M4A '):
            return 'mp4'
    
    return None


def compare_files_binary(filepath1: str, filepath2: str, 
                        chunk_size: int = 1024 * 1024) -> bool:
    """
    Compare two files byte-by-byte
    
    Args:
        filepath1: First file path
        filepath2: Second file path
        chunk_size: Comparison chunk size
    
    Returns:
        True if files are identical
    """
    try:
        # Quick size check first
        if os.path.getsize(filepath1) != os.path.getsize(filepath2):
            return False
        
        with open(filepath1, 'rb') as f1, open(filepath2, 'rb') as f2:
            while True:
                chunk1 = f1.read(chunk_size)
                chunk2 = f2.read(chunk_size)
                
                if chunk1 != chunk2:
                    return False
                
                if not chunk1:  # EOF
                    return True
    
    except (IOError, OSError, PermissionError):
        return False


def get_size_hash_key(size: int) -> str:
    """
    Create size-based grouping key for duplicate detection
    Files must have same size to be duplicates
    
    Args:
        size: File size in bytes
    
    Returns:
        String key for grouping
    """
    return f"size_{size}"
