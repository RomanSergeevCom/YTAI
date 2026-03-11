"""
Developer and AI tools analyzer for Mac Disk Analyzer
Identifies development-related space usage
"""

import os
from typing import List, Dict, Any, Optional
from pathlib import Path

from core.file_info import FileInfo
from config.settings import Settings
from utils.formatting import format_size


class DevToolsAnalyzer:
    """
    Analyzes developer and AI/ML tools space usage:
    - Node modules
    - Python virtual environments
    - Docker images and volumes
    - Homebrew
    - Xcode derived data
    - AI/ML models (Ollama, LM Studio, Hugging Face)
    - Git repositories
    """
    
    def __init__(self, settings: Settings):
        """
        Initialize analyzer
        
        Args:
            settings: Application settings
        """
        self.settings = settings
        self.home = os.path.expanduser('~')
    
    def analyze(self, files: List[FileInfo]) -> Dict[str, Any]:
        """
        Analyze developer tools space usage
        
        Args:
            files: List of FileInfo objects
        
        Returns:
            Dictionary with dev tools analysis
        """
        results = {
            'node_modules': self._analyze_node_modules(files),
            'python_envs': self._analyze_python_envs(files),
            'docker': self._analyze_docker(files),
            'homebrew': self._analyze_homebrew(files),
            'xcode': self._analyze_xcode(files),
            'ai_models': self._analyze_ai_models(files),
            'git_repos': self._analyze_git_repos(files),
            'total_dev_size': 0,
            'cleanable_size': 0,
        }
        
        # Calculate totals
        for key in ['node_modules', 'python_envs', 'docker', 'homebrew', 'xcode', 'ai_models']:
            if isinstance(results[key], dict):
                results['total_dev_size'] += results[key].get('total_size', 0)
                results['cleanable_size'] += results[key].get('cleanable_size', 0)
        
        return results
    
    def _analyze_node_modules(self, files: List[FileInfo]) -> Dict[str, Any]:
        """Analyze node_modules directories"""
        node_files = [f for f in files if '/node_modules/' in f.path]
        
        # Group by project
        projects = {}
        for f in node_files:
            # Find the project root (parent of node_modules)
            path_parts = f.path.split('/node_modules/')
            if path_parts:
                project_root = path_parts[0]
                if project_root not in projects:
                    projects[project_root] = {'size': 0, 'count': 0}
                projects[project_root]['size'] += f.size
                projects[project_root]['count'] += 1
        
        total_size = sum(p['size'] for p in projects.values())
        
        return {
            'total_size': total_size,
            'cleanable_size': total_size,  # All node_modules can be reinstalled
            'project_count': len(projects),
            'file_count': len(node_files),
            'projects': sorted(
                [{'path': k, **v} for k, v in projects.items()],
                key=lambda x: x['size'],
                reverse=True
            )[:50],  # Top 50 projects
        }
    
    def _analyze_python_envs(self, files: List[FileInfo]) -> Dict[str, Any]:
        """Analyze Python virtual environments"""
        venv_patterns = ['/venv/', '/.venv/', '/virtualenv/', '/env/', '/.pyenv/']
        pip_cache = os.path.join(self.home, 'Library/Caches/pip')
        
        venv_files = [
            f for f in files
            if any(p in f.path for p in venv_patterns)
        ]
        
        pip_cache_files = [f for f in files if f.path.startswith(pip_cache)]
        
        # Group by environment
        envs = {}
        for f in venv_files:
            # Find env root
            for pattern in venv_patterns:
                if pattern in f.path:
                    idx = f.path.find(pattern)
                    env_root = f.path[:idx + len(pattern) - 1]
                    if env_root not in envs:
                        envs[env_root] = {'size': 0, 'count': 0}
                    envs[env_root]['size'] += f.size
                    envs[env_root]['count'] += 1
                    break
        
        venv_size = sum(e['size'] for e in envs.values())
        pip_size = sum(f.size for f in pip_cache_files)
        
        return {
            'total_size': venv_size + pip_size,
            'cleanable_size': pip_size,  # pip cache is safe to clean
            'venv_size': venv_size,
            'pip_cache_size': pip_size,
            'env_count': len(envs),
            'environments': sorted(
                [{'path': k, **v} for k, v in envs.items()],
                key=lambda x: x['size'],
                reverse=True
            )[:30],
        }
    
    def _analyze_docker(self, files: List[FileInfo]) -> Dict[str, Any]:
        """Analyze Docker space usage"""
        docker_paths = [
            os.path.join(self.home, 'Library/Containers/com.docker.docker'),
            os.path.join(self.home, '.docker'),
        ]
        
        docker_files = [
            f for f in files
            if any(f.path.startswith(p) for p in docker_paths)
        ]
        
        total_size = sum(f.size for f in docker_files)
        
        # Identify VM disk images
        vm_disk_size = sum(
            f.size for f in docker_files
            if 'Docker.raw' in f.path or 'vms/' in f.path
        )
        
        return {
            'total_size': total_size,
            'cleanable_size': 0,  # Docker cleanup should be done through Docker
            'vm_disk_size': vm_disk_size,
            'file_count': len(docker_files),
            'note': 'Use "docker system prune" to clean Docker data',
        }
    
    def _analyze_homebrew(self, files: List[FileInfo]) -> Dict[str, Any]:
        """Analyze Homebrew cache and old versions"""
        brew_cache = os.path.join(self.home, 'Library/Caches/Homebrew')
        brew_paths = ['/opt/homebrew', '/usr/local/Homebrew', brew_cache]
        
        brew_files = [
            f for f in files
            if any(f.path.startswith(p) for p in brew_paths)
        ]
        
        cache_files = [f for f in brew_files if f.path.startswith(brew_cache)]
        
        total_size = sum(f.size for f in brew_files)
        cache_size = sum(f.size for f in cache_files)
        
        return {
            'total_size': total_size,
            'cleanable_size': cache_size,  # Cache is safe to clean
            'cache_size': cache_size,
            'file_count': len(brew_files),
            'note': 'Run "brew cleanup" to remove old versions',
        }
    
    def _analyze_xcode(self, files: List[FileInfo]) -> Dict[str, Any]:
        """Analyze Xcode-related space usage"""
        xcode_paths = {
            'derived_data': os.path.join(self.home, 'Library/Developer/Xcode/DerivedData'),
            'archives': os.path.join(self.home, 'Library/Developer/Xcode/Archives'),
            'device_support': os.path.join(self.home, 'Library/Developer/Xcode/iOS DeviceSupport'),
            'simulators': os.path.join(self.home, 'Library/Developer/CoreSimulator'),
            'cache': os.path.join(self.home, 'Library/Caches/com.apple.dt.Xcode'),
        }
        
        breakdown = {}
        total_size = 0
        cleanable = 0
        
        for name, path in xcode_paths.items():
            path_files = [f for f in files if f.path.startswith(path)]
            size = sum(f.size for f in path_files)
            breakdown[name] = {
                'path': path,
                'size': size,
                'count': len(path_files),
            }
            total_size += size
            
            # Derived data and cache are safe to clean
            if name in ['derived_data', 'cache']:
                cleanable += size
        
        return {
            'total_size': total_size,
            'cleanable_size': cleanable,
            'breakdown': breakdown,
            'note': 'DerivedData is safe to delete, will rebuild on next compile',
        }
    
    def _analyze_ai_models(self, files: List[FileInfo]) -> Dict[str, Any]:
        """Analyze AI/ML model storage"""
        ai_paths = {
            'ollama': os.path.join(self.home, '.ollama'),
            'huggingface': os.path.join(self.home, '.cache/huggingface'),
            'lm_studio': os.path.join(self.home, '.lmstudio'),
            'torch': os.path.join(self.home, '.cache/torch'),
        }
        
        # Also find by extension
        model_exts = {'.gguf', '.bin', '.safetensors', '.ggml', '.pt', '.pth'}
        
        breakdown = {}
        total_size = 0
        
        for name, path in ai_paths.items():
            path_files = [f for f in files if f.path.startswith(path)]
            size = sum(f.size for f in path_files)
            
            if size > 0:
                breakdown[name] = {
                    'path': path,
                    'size': size,
                    'count': len(path_files),
                }
                total_size += size
        
        # Find model files by extension
        model_files = [
            f for f in files
            if f.extension.lower() in model_exts
            and not any(f.path.startswith(p) for p in ai_paths.values())
        ]
        
        if model_files:
            model_size = sum(f.size for f in model_files)
            breakdown['other_models'] = {
                'size': model_size,
                'count': len(model_files),
                'files': [
                    {'path': f.path, 'size': f.size}
                    for f in sorted(model_files, key=lambda x: x.size, reverse=True)[:20]
                ],
            }
            total_size += model_size
        
        return {
            'total_size': total_size,
            'cleanable_size': 0,  # Models are not auto-cleanable
            'breakdown': breakdown,
            'note': 'AI models can be re-downloaded if needed',
        }
    
    def _analyze_git_repos(self, files: List[FileInfo]) -> Dict[str, Any]:
        """Analyze Git repositories"""
        git_files = [f for f in files if '/.git/' in f.path]
        
        # Group by repo
        repos = {}
        for f in git_files:
            repo_root = f.path.split('/.git/')[0]
            if repo_root not in repos:
                repos[repo_root] = {'git_size': 0, 'count': 0}
            repos[repo_root]['git_size'] += f.size
            repos[repo_root]['count'] += 1
        
        total_git_size = sum(r['git_size'] for r in repos.values())
        
        return {
            'total_size': total_git_size,
            'cleanable_size': 0,  # Git objects shouldn't be auto-cleaned
            'repo_count': len(repos),
            'file_count': len(git_files),
            'largest_repos': sorted(
                [{'path': k, **v} for k, v in repos.items()],
                key=lambda x: x['git_size'],
                reverse=True
            )[:20],
            'note': 'Run "git gc" in repos to optimize git storage',
        }


def analyze_dev_tools(files: List[FileInfo]) -> Dict[str, Any]:
    """
    Quick utility to analyze dev tools
    
    Args:
        files: List of files
    
    Returns:
        Dev tools analysis results
    """
    settings = Settings()
    analyzer = DevToolsAnalyzer(settings)
    return analyzer.analyze(files)
