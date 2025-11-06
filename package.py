#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
项目打包脚本
将项目打包成 tar.gz 文件
"""

import os
import tarfile
import shutil
from pathlib import Path
from datetime import datetime

# 项目根目录
PROJECT_ROOT = Path(__file__).parent
PACKAGE_NAME = "crypto-trading-system"
TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
OUTPUT_FILE = PROJECT_ROOT.parent / f"{PACKAGE_NAME}_{TIMESTAMP}.tar.gz"

# 排除的文件和目录模式
EXCLUDE_PATTERNS = [
    # Python 缓存
    "__pycache__",
    "*.pyc",
    "*.pyo",
    "*.pyd",
    ".Python",
    "*.so",
    
    # 虚拟环境
    "venv/",
    "env/",
    "ENV/",
    
    # IDE
    ".vscode/",
    ".idea/",
    "*.swp",
    "*.swo",
    
    # 日志文件
    "*.log",
    
    # 敏感文件
    ".env",
    "*.key",
    "*.pem",
    
    # 数据库文件
    "*.db",
    "*.sqlite",
    
    # 构建文件
    "build/",
    "dist/",
    "*.egg-info/",
    
    # 其他
    ".git/",
    ".gitignore",
    "*.tar.gz",
    "*.zip",
]

# 需要排除的具体文件
EXCLUDE_FILES = {
    ".env",
    ".gitignore",
}

# 需要排除的目录
EXCLUDE_DIRS = {
    "__pycache__",
    ".vscode",
    ".idea",
    "venv",
    "env",
    "ENV",
    ".git",
    "build",
    "dist",
    "__pycache__",
}


def should_exclude(path: Path) -> bool:
    """判断文件或目录是否应该被排除"""
    try:
        # 检查文件名
        if path.name in EXCLUDE_FILES:
            return True
        
        # 检查是否是排除的目录
        if path.is_dir() and path.name in EXCLUDE_DIRS:
            return True
        
        # 检查父目录
        for parent in path.parents:
            if parent.name in EXCLUDE_DIRS:
                return True
        
        # 检查日志文件
        if path.suffix == ".log":
            return True
        
        # 检查是否匹配排除模式
        try:
            path_str = str(path.relative_to(PROJECT_ROOT))
        except ValueError:
            # 如果路径不在项目目录内，跳过
            return False
        
        for pattern in EXCLUDE_PATTERNS:
            if pattern.endswith("/"):
                if path_str.startswith(pattern) or f"/{pattern}" in f"/{path_str}":
                    return True
            elif pattern.startswith("*"):
                if path.name.endswith(pattern[1:]) or path.name == pattern[1:]:
                    return True
            else:
                if pattern in path_str or path.name == pattern:
                    return True
        
        return False
    except Exception:
        # 如果检查出错，默认排除
        return True


def create_package():
    """创建 tar.gz 包"""
    print("=" * 60)
    print("项目打包工具")
    print("=" * 60)
    print()
    
    print(f"项目目录: {PROJECT_ROOT}")
    print(f"输出文件: {OUTPUT_FILE}")
    print()
    
    # 统计文件
    included_files = []
    excluded_files = []
    
    for root, dirs, files in os.walk(PROJECT_ROOT):
        root_path = Path(root)
        
        # 过滤排除的目录
        dirs[:] = [d for d in dirs if not should_exclude(root_path / d)]
        
        for file in files:
            file_path = root_path / file
            
            if should_exclude(file_path):
                excluded_files.append(file_path)
            else:
                included_files.append(file_path)
    
    print(f"包含文件: {len(included_files)} 个")
    print(f"排除文件: {len(excluded_files)} 个")
    print()
    
    # 创建 tar.gz 文件
    print("正在打包...")
    try:
        with tarfile.open(OUTPUT_FILE, "w:gz") as tar:
            for file_path in included_files:
                try:
                    # 使用相对于父目录的路径，保持目录结构
                    arcname = str(file_path.relative_to(PROJECT_ROOT.parent))
                    tar.add(file_path, arcname=arcname)
                    if len(included_files) <= 100:  # 文件不多时才打印详情
                        print(f"  添加: {arcname}")
                except Exception as e:
                    print(f"  跳过 {file_path}: {e}")
        
        file_size = OUTPUT_FILE.stat().st_size / (1024 * 1024)  # MB
        print()
        print("=" * 60)
        print("✓ 打包完成！")
        print("=" * 60)
        print(f"输出文件: {OUTPUT_FILE}")
        print(f"文件大小: {file_size:.2f} MB")
        print()
        
        return True
        
    except Exception as e:
        print()
        print("=" * 60)
        print("✗ 打包失败")
        print("=" * 60)
        print(f"错误: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = create_package()
    exit(0 if success else 1)

