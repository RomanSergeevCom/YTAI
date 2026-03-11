"""
Media file analyzer for Mac Disk Analyzer
Extracts metadata from video/audio files
"""

import os
import subprocess
import json
from typing import List, Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

from core.file_info import FileInfo
from config.settings import Settings
from utils.formatting import format_size, format_duration


class MediaAnalyzer:
    """
    Analyzes media files to extract metadata like:
    - Duration, resolution, codec for videos
    - Sample rate, channels for audio
    - Identifies proxies vs originals
    """
    
    def __init__(self, settings: Settings):
        """
        Initialize analyzer
        
        Args:
            settings: Application settings
        """
        self.settings = settings
        self.ffprobe_available = self._check_ffprobe()
        self.mdls_available = True  # Built into macOS
        
        # Video extensions
        self.video_exts = {
            '.mp4', '.mov', '.avi', '.mkv', '.m4v', '.webm', 
            '.mxf', '.r3d', '.braw', '.ari', '.prores'
        }
        
        # Audio extensions
        self.audio_exts = {
            '.mp3', '.wav', '.aiff', '.flac', '.aac', '.m4a', '.ogg'
        }
        
        # Image sequence extensions
        self.image_seq_exts = {
            '.dpx', '.exr', '.tiff', '.tif', '.png', '.jpg'
        }
    
    def _check_ffprobe(self) -> bool:
        """Check if ffprobe is available"""
        try:
            subprocess.run(
                ['ffprobe', '-version'],
                capture_output=True,
                timeout=5
            )
            return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False
    
    def analyze(self, files: List[FileInfo]) -> Dict[str, Any]:
        """
        Analyze all media files
        
        Args:
            files: List of FileInfo objects
        
        Returns:
            Dictionary with media analysis results
        """
        # Filter to media files
        video_files = []
        audio_files = []
        
        for f in files:
            ext = f.extension.lower()
            if ext in self.video_exts:
                video_files.append(f)
            elif ext in self.audio_exts:
                audio_files.append(f)
        
        results = {
            'videos': [],
            'audio': [],
            'total_video_size': sum(f.size for f in video_files),
            'total_audio_size': sum(f.size for f in audio_files),
            'total_video_duration': 0,
            'total_audio_duration': 0,
            'codec_breakdown': {},
            'resolution_breakdown': {},
            'potential_proxies': [],
            'potential_duplicates': [],
        }
        
        if not (video_files or audio_files):
            return results
        
        if self.settings.verbose:
            print(f"    Analyzing {len(video_files)} video and {len(audio_files)} audio files...")
        
        # Analyze videos (limit to prevent long scan times)
        max_analyze = 500
        for i, f in enumerate(video_files[:max_analyze]):
            if self.settings.verbose and i % 50 == 0:
                print(f"\r    Processing video {i+1}/{min(len(video_files), max_analyze)}", end='', flush=True)
            
            info = self._analyze_video(f)
            if info:
                f.media_info = info
                results['videos'].append({
                    'path': f.path,
                    'size': f.size,
                    **info
                })
                
                # Update totals
                if info.get('duration'):
                    results['total_video_duration'] += info['duration']
                
                # Update breakdowns
                codec = info.get('codec', 'unknown')
                results['codec_breakdown'][codec] = results['codec_breakdown'].get(codec, 0) + f.size
                
                res = info.get('resolution', 'unknown')
                results['resolution_breakdown'][res] = results['resolution_breakdown'].get(res, 0) + f.size
                
                # Check for proxies
                if self._is_likely_proxy(f, info):
                    results['potential_proxies'].append(f.path)
        
        # Analyze audio
        for i, f in enumerate(audio_files[:max_analyze]):
            if self.settings.verbose and i % 50 == 0:
                print(f"\r    Processing audio {i+1}/{min(len(audio_files), max_analyze)}", end='', flush=True)
            
            info = self._analyze_audio(f)
            if info:
                f.media_info = info
                results['audio'].append({
                    'path': f.path,
                    'size': f.size,
                    **info
                })
                
                if info.get('duration'):
                    results['total_audio_duration'] += info['duration']
        
        if self.settings.verbose:
            print()  # New line after progress
        
        return results
    
    def _analyze_video(self, file_info: FileInfo) -> Optional[Dict[str, Any]]:
        """
        Analyze a single video file
        
        Args:
            file_info: File to analyze
        
        Returns:
            Dictionary with video metadata or None
        """
        # Try ffprobe first (most accurate)
        if self.ffprobe_available:
            return self._ffprobe_video(file_info.path)
        
        # Fall back to macOS mdls
        return self._mdls_media(file_info.path)
    
    def _analyze_audio(self, file_info: FileInfo) -> Optional[Dict[str, Any]]:
        """
        Analyze a single audio file
        
        Args:
            file_info: File to analyze
        
        Returns:
            Dictionary with audio metadata or None
        """
        if self.ffprobe_available:
            return self._ffprobe_audio(file_info.path)
        
        return self._mdls_media(file_info.path)
    
    def _ffprobe_video(self, path: str) -> Optional[Dict[str, Any]]:
        """Get video info using ffprobe"""
        try:
            result = subprocess.run([
                'ffprobe',
                '-v', 'quiet',
                '-print_format', 'json',
                '-show_format',
                '-show_streams',
                path
            ], capture_output=True, text=True, timeout=30)
            
            if result.returncode != 0:
                return None
            
            data = json.loads(result.stdout)
            
            # Find video stream
            video_stream = None
            audio_stream = None
            
            for stream in data.get('streams', []):
                if stream.get('codec_type') == 'video' and not video_stream:
                    video_stream = stream
                elif stream.get('codec_type') == 'audio' and not audio_stream:
                    audio_stream = stream
            
            if not video_stream:
                return None
            
            # Extract info
            width = video_stream.get('width', 0)
            height = video_stream.get('height', 0)
            
            # Calculate duration
            duration = 0
            if 'duration' in video_stream:
                duration = float(video_stream['duration'])
            elif 'duration' in data.get('format', {}):
                duration = float(data['format']['duration'])
            
            # Get frame rate
            fps = 0
            if 'r_frame_rate' in video_stream:
                fps_parts = video_stream['r_frame_rate'].split('/')
                if len(fps_parts) == 2 and int(fps_parts[1]) > 0:
                    fps = round(int(fps_parts[0]) / int(fps_parts[1]), 2)
            
            # Get bitrate
            bitrate = 0
            if 'bit_rate' in data.get('format', {}):
                bitrate = int(data['format']['bit_rate'])
            
            return {
                'width': width,
                'height': height,
                'resolution': f"{width}x{height}",
                'duration': duration,
                'duration_formatted': format_duration(duration) if duration else None,
                'codec': video_stream.get('codec_name', 'unknown'),
                'codec_long': video_stream.get('codec_long_name', ''),
                'fps': fps,
                'bitrate': bitrate,
                'bitrate_formatted': format_size(bitrate) + '/s' if bitrate else None,
                'has_audio': audio_stream is not None,
                'audio_codec': audio_stream.get('codec_name') if audio_stream else None,
                'pixel_format': video_stream.get('pix_fmt', ''),
            }
        
        except (subprocess.TimeoutExpired, json.JSONDecodeError, KeyError, ValueError):
            return None
    
    def _ffprobe_audio(self, path: str) -> Optional[Dict[str, Any]]:
        """Get audio info using ffprobe"""
        try:
            result = subprocess.run([
                'ffprobe',
                '-v', 'quiet',
                '-print_format', 'json',
                '-show_format',
                '-show_streams',
                path
            ], capture_output=True, text=True, timeout=30)
            
            if result.returncode != 0:
                return None
            
            data = json.loads(result.stdout)
            
            # Find audio stream
            audio_stream = None
            for stream in data.get('streams', []):
                if stream.get('codec_type') == 'audio':
                    audio_stream = stream
                    break
            
            if not audio_stream:
                return None
            
            # Get duration
            duration = 0
            if 'duration' in audio_stream:
                duration = float(audio_stream['duration'])
            elif 'duration' in data.get('format', {}):
                duration = float(data['format']['duration'])
            
            return {
                'duration': duration,
                'duration_formatted': format_duration(duration) if duration else None,
                'codec': audio_stream.get('codec_name', 'unknown'),
                'sample_rate': int(audio_stream.get('sample_rate', 0)),
                'channels': audio_stream.get('channels', 0),
                'bit_depth': audio_stream.get('bits_per_sample', 0),
            }
        
        except (subprocess.TimeoutExpired, json.JSONDecodeError, KeyError, ValueError):
            return None
    
    def _mdls_media(self, path: str) -> Optional[Dict[str, Any]]:
        """Get media info using macOS mdls (Spotlight metadata)"""
        try:
            result = subprocess.run(
                ['mdls', '-plist', '-', path],
                capture_output=True,
                timeout=10
            )
            
            if result.returncode != 0:
                return None
            
            # Parse plist output
            import plistlib
            data = plistlib.loads(result.stdout)
            
            info = {}
            
            # Video dimensions
            if 'kMDItemPixelWidth' in data:
                info['width'] = data['kMDItemPixelWidth']
            if 'kMDItemPixelHeight' in data:
                info['height'] = data['kMDItemPixelHeight']
            if info.get('width') and info.get('height'):
                info['resolution'] = f"{info['width']}x{info['height']}"
            
            # Duration
            if 'kMDItemDurationSeconds' in data:
                info['duration'] = data['kMDItemDurationSeconds']
                info['duration_formatted'] = format_duration(info['duration'])
            
            # Codecs
            if 'kMDItemCodecs' in data:
                info['codecs'] = data['kMDItemCodecs']
                if data['kMDItemCodecs']:
                    info['codec'] = data['kMDItemCodecs'][0]
            
            # Audio
            if 'kMDItemAudioSampleRate' in data:
                info['sample_rate'] = data['kMDItemAudioSampleRate']
            if 'kMDItemAudioChannelCount' in data:
                info['channels'] = data['kMDItemAudioChannelCount']
            
            return info if info else None
        
        except Exception:
            return None
    
    def _is_likely_proxy(self, file_info: FileInfo, media_info: Dict[str, Any]) -> bool:
        """
        Check if a video file is likely a proxy
        
        Args:
            file_info: File info
            media_info: Media metadata
        
        Returns:
            True if file appears to be a proxy
        """
        path_lower = file_info.path.lower()
        
        # Check path for proxy indicators
        proxy_indicators = ['proxy', 'prox', 'lo-res', 'lowres', 'low_res', 'offline']
        if any(ind in path_lower for ind in proxy_indicators):
            return True
        
        # Check resolution (proxies are usually lower res)
        width = media_info.get('width', 0)
        height = media_info.get('height', 0)
        
        if width and height:
            # If it's a very low resolution compared to file size, likely proxy
            pixels = width * height
            if pixels < 1920 * 1080:  # Less than 1080p
                # Check if there are other files with same name but higher res
                return True
        
        # Check codec (common proxy codecs)
        codec = media_info.get('codec', '').lower()
        proxy_codecs = ['prores_proxy', 'h264', 'hevc']
        
        # ProRes Proxy specifically
        if 'prores' in codec and 'proxy' in codec:
            return True
        
        return False


def analyze_media_files(files: List[FileInfo]) -> Dict[str, Any]:
    """
    Quick utility to analyze media files
    
    Args:
        files: List of files
    
    Returns:
        Media analysis results
    """
    settings = Settings()
    settings.verbose = False
    analyzer = MediaAnalyzer(settings)
    return analyzer.analyze(files)
