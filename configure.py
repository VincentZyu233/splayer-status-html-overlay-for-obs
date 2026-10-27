#!/usr/bin/env python3
"""调整 index.html 中写死的 SPlayer API 地址、端口和字体。"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_HTML = BASE_DIR / "index.html"
DEFAULT_FONT = BASE_DIR / "fonts" / "LXGWWenKai-Regular.ttf"

HOST_RE = re.compile(r'(apiHost:\s*")[^"]*(")')
PORT_RE = re.compile(r"(apiPort:\s*)\d+")
HOST_VALUE_RE = re.compile(r'apiHost:\s*"([^"]*)"')
PORT_VALUE_RE = re.compile(r"apiPort:\s*(\d+)")
FONT_BLOCK_RE = re.compile(
    r"/\* FONT_CONFIG_START \*/.*?/\* FONT_CONFIG_END \*/", re.DOTALL
)
FONT_URL_RE = re.compile(r'url\("([^"]+)"\)')

FONT_FORMATS = {
    ".ttf": "truetype",
    ".otf": "opentype",
    ".woff": "woff",
    ".woff2": "woff2",
}


def css_font_url(font_path: Path, html_path: Path) -> str:
    """返回相对于 HTML 的路径；仓库外字体使用 file:// URI。"""
    try:
        relative = font_path.relative_to(html_path.parent.resolve())
    except ValueError:
        return font_path.as_uri()
    return urllib.parse.quote(relative.as_posix(), safe="/")


def render_font_block(font_path: Optional[Path], html_path: Path) -> str:
    if font_path is None:
        return (
            "/* FONT_CONFIG_START */\n"
            "    /* 未启用本地字体，使用系统 LXGW WenKai / 回退字体 */\n"
            "    /* FONT_CONFIG_END */"
        )

    font_format = FONT_FORMATS.get(font_path.suffix.lower())
    if not font_format:
        raise ValueError(f"不支持的字体格式：{font_path.suffix}")

    url = css_font_url(font_path, html_path)
    return (
        "/* FONT_CONFIG_START */\n"
        "    @font-face {\n"
        '      font-family: "LXGW WenKai Custom";\n'
        f'      src: url("{url}") format("{font_format}");\n'
        "      font-weight: normal;\n"
        "      font-display: swap;\n"
        "    }\n"
        "    /* FONT_CONFIG_END */"
    )


def current_font_path(html: str, html_path: Path) -> Optional[Path]:
    match = FONT_URL_RE.search(html)
    if not match:
        return None

    url = match.group(1)
    if url.startswith(("http://", "https://")):
        return None

    if url.startswith("file://"):
        parsed = urllib.parse.urlparse(url)
        path = Path(urllib.request.url2pathname(parsed.path))
    else:
        path = html_path.parent / urllib.parse.unquote(url)

    path = path.resolve()
    return path if path.is_file() else None


def resolve_font_path(value: str, html_path: Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        cwd_candidate = Path.cwd() / path
        path = cwd_candidate if cwd_candidate.exists() else html_path.parent / path
    return path.resolve()


def validate_host(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("host 不能为空")
    if re.search(r'["\\\s]', value):
        raise ValueError("host 不能包含引号、反斜杠或空白字符")
    return value


def validate_port(value: int) -> int:
    if not 1 <= value <= 65535:
        raise ValueError("port 必须在 1-65535 之间")
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="调整 SPlayer-Next OBS 挂件的 host、port 和字体配置。"
    )
    parser.add_argument(
        "--file",
        default=str(DEFAULT_HTML),
        help="要修改的 HTML 文件（默认：index.html）",
    )
    parser.add_argument("--host", help="SPlayer API 主机，例如 127.0.0.1 或局域网 IP")
    parser.add_argument("--port", type=int, help="SPlayer 外部 API 端口，默认 14558")
    font_group = parser.add_mutually_exclusive_group()
    font_group.add_argument("--font", help="字体文件路径，例如 fonts/LXGWWenKai-Regular.ttf")
    font_group.add_argument(
        "--system-font",
        action="store_true",
        help="不加载本地字体，使用系统已安装的 LXGW WenKai 或回退字体",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="不生成 index.html.bak 备份",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印将要修改的内容，不写入文件",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    html_path = Path(args.file).expanduser().resolve()

    if not html_path.is_file():
        print(f"找不到 HTML 文件：{html_path}", file=sys.stderr)
        return 1

    html = html_path.read_text(encoding="utf-8")

    host_match = HOST_VALUE_RE.search(html)
    port_match = PORT_VALUE_RE.search(html)
    if not host_match or not port_match:
        print("HTML 中找不到 apiHost / apiPort 配置。", file=sys.stderr)
        return 1
    if not FONT_BLOCK_RE.search(html):
        print(
            "HTML 中找不到 FONT_CONFIG_START / FONT_CONFIG_END 字体标记。",
            file=sys.stderr,
        )
        return 1

    current_host = host_match.group(1)
    current_port = int(port_match.group(1))
    detected_font = current_font_path(html, html_path)
    if detected_font is None and DEFAULT_FONT.is_file():
        detected_font = DEFAULT_FONT.resolve()

    has_cli_config = any(
        value is not None
        for value in (args.host, args.port, args.font, args.system_font)
    )
    interactive = sys.stdin.isatty() and not has_cli_config

    host = args.host
    port = args.port
    font_value = args.font
    system_font = args.system_font

    if interactive:
        print("直接回车保持当前值。\n")
        host_input = input(f"API host [{current_host}]: ").strip()
        host = host_input or current_host

        port_input = input(f"API port [{current_port}]: ").strip()
        port = int(port_input) if port_input else current_port

        default_font = (
            str(detected_font.relative_to(BASE_DIR))
            if detected_font and detected_font.is_relative_to(BASE_DIR)
            else str(detected_font) if detected_font else "system"
        )
        font_input = input(
            f"字体路径（输入 system 使用系统字体）[{default_font}]: "
        ).strip()
        if font_input:
            if font_input.lower() == "system":
                system_font = True
            else:
                font_value = font_input
                system_font = False
        else:
            font_value = None if default_font == "system" else default_font
            system_font = default_font == "system"

    try:
        host = validate_host(host if host is not None else current_host)
        port = validate_port(port if port is not None else current_port)
    except (TypeError, ValueError) as exc:
        print(f"配置错误：{exc}", file=sys.stderr)
        return 1

    if system_font:
        font_path = None
    elif font_value:
        font_path = resolve_font_path(font_value, html_path)
        if not font_path.is_file():
            print(f"字体文件不存在：{font_path}", file=sys.stderr)
            return 1
        if font_path.suffix.lower() not in FONT_FORMATS:
            print(
                f"不支持的字体格式：{font_path.suffix}（支持 .ttf/.otf/.woff/.woff2）",
                file=sys.stderr,
            )
            return 1
    else:
        font_path = detected_font

    new_html = HOST_RE.sub(
        lambda match: f'{match.group(1)}{host}{match.group(2)}', html, count=1
    )
    new_html = PORT_RE.sub(
        lambda match: f"{match.group(1)}{port}", new_html, count=1
    )
    new_html = FONT_BLOCK_RE.sub(
        render_font_block(font_path, html_path), new_html, count=1
    )

    print(f"文件：{html_path}")
    print(f"apiHost：{current_host} -> {host}")
    print(f"apiPort：{current_port} -> {port}")
    if font_path is None:
        print("字体：使用系统 LXGW WenKai / 回退字体")
    else:
        print(f"字体：{font_path}")

    if args.dry_run:
        print("\n--dry-run：未写入文件。")
        return 0

    if new_html == html:
        print("\n配置没有变化，无需写入。")
        return 0

    if not args.no_backup:
        backup_path = html_path.with_name(html_path.name + ".bak")
        shutil.copy2(html_path, backup_path)
        print(f"备份：{backup_path}")

    fd, temp_name = tempfile.mkstemp(
        dir=html_path.parent, prefix=f".{html_path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as temp_file:
            temp_file.write(new_html)
        os.replace(temp_name, html_path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise

    print("已更新。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
