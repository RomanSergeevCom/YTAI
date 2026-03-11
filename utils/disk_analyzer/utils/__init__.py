"""Utility modules"""
from .formatting import (
    format_size, format_size_short, parse_size,
    format_duration, format_date, format_number,
    format_percentage, truncate_path, truncate_string,
    make_safe_filename, generate_color_for_category,
    bar_chart_ascii, format_file_type
)
from .hashing import (
    hash_file_md5, hash_file_sha256, hash_file_quick,
    hash_file_xxhash, get_file_signature, 
    detect_file_type_by_signature, compare_files_binary,
    get_size_hash_key
)
from .permissions import (
    check_full_disk_access, check_path_readable,
    is_system_protected, is_symlink_loop,
    get_file_owner, get_file_permissions_string,
    can_delete_file, request_full_disk_access_instructions,
    get_sip_status, estimate_scannable_size
)
from .preflight import (
    PreflightCheck, CheckStatus, run_preflight_checks,
    print_preflight_report, quit_application, estimate_cleanup_time
)

__all__ = [
    'format_size', 'format_size_short', 'parse_size',
    'format_duration', 'format_date', 'format_number',
    'format_percentage', 'truncate_path', 'truncate_string',
    'make_safe_filename', 'generate_color_for_category',
    'bar_chart_ascii', 'format_file_type',
    'hash_file_md5', 'hash_file_sha256', 'hash_file_quick',
    'hash_file_xxhash', 'get_file_signature',
    'detect_file_type_by_signature', 'compare_files_binary',
    'get_size_hash_key',
    'check_full_disk_access', 'check_path_readable',
    'is_system_protected', 'is_symlink_loop',
    'get_file_owner', 'get_file_permissions_string',
    'can_delete_file', 'request_full_disk_access_instructions',
    'get_sip_status', 'estimate_scannable_size',
    'PreflightCheck', 'CheckStatus', 'run_preflight_checks',
    'print_preflight_report', 'quit_application', 'estimate_cleanup_time',
]
