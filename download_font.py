#!/usr/bin/env python3
"""从 lxgw/LxgwWenKai 下载最新版字体到仓库的 fonts/ 目录。"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT = BASE_DIR / "fonts" / "LXGWWenKai-Regular.ttf"
DEFAULT_ASSET = "LXGWWenKai-Regular.ttf"
API_URL = "https://api.github.com/repos/lxgw/LxgwWenKai/releases/latest"
LATEST_DOWNLOAD_URL = (
    "https://github.com/lxgw/LxgwWenKai/releases/latest/download/{asset}"
)
USER_AGENT = "splayer-status-overlay-font-downloader"
TTF_MAGIC = {b"\x00\x01\x00\x00", b"OTTO", b"true", b"typ1"}


def build_opener(proxy: Optional[str]) -> urllib.request.OpenerDirector:
    if proxy:
        handler = urllib.request.ProxyHandler({"http": proxy, "https": proxy})
        return urllib.request.build_opener(handler)
    return urllib.request.build_opener()


def request_json(opener: urllib.request.OpenerDirector, url: str, timeout: int):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/vnd.github+json",
        },
    )
    with opener.open(request, timeout=timeout) as response:
        return json.load(response)


def human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024 or unit == "GiB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


def download_file(
    opener: urllib.request.OpenerDirector,
    url: str,
    destination: Path,
    expected_size: int,
    timeout: int,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/octet-stream",
        },
    )

    fd, temp_name = tempfile.mkstemp(
        dir=destination.parent, prefix=f".{destination.name}.", suffix=".part"
    )
    try:
        with os.fdopen(fd, "wb") as temp_file:
            with opener.open(request, timeout=timeout) as response:
                total = expected_size or int(response.headers.get("Content-Length") or 0)
                downloaded = 0
                last_percent = -1

                while True:
                    chunk = response.read(1024 * 256)
                    if not chunk:
                        break
                    temp_file.write(chunk)
                    downloaded += len(chunk)
                    if total:
                        percent = min(100, int(downloaded * 100 / total))
                        if percent != last_percent:
                            print(
                                f"\r下载中：{percent}% "
                                f"({human_size(downloaded)} / {human_size(total)})",
                                end="",
                                file=sys.stderr,
                                flush=True,
                            )
                            last_percent = percent

                print(file=sys.stderr)

        actual_size = os.path.getsize(temp_name)
        if expected_size and actual_size != expected_size:
            raise RuntimeError(
                f"文件大小不一致：期望 {expected_size} 字节，实际 {actual_size} 字节"
            )
        if actual_size == 0:
            raise RuntimeError("下载结果为空文件")

        with open(temp_name, "rb") as font_file:
            magic = font_file.read(4)
        if magic not in TTF_MAGIC:
            raise RuntimeError("下载内容不是有效的 TTF/OTF 字体文件")

        os.replace(temp_name, destination)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="下载 lxgw/LxgwWenKai 最新 release 中的字体文件。"
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT),
        help="保存路径（默认：fonts/LXGWWenKai-Regular.ttf）",
    )
    parser.add_argument(
        "--asset",
        default=DEFAULT_ASSET,
        help=f"release 中的字体文件名（默认：{DEFAULT_ASSET}）",
    )
    parser.add_argument("--proxy", help="HTTP(S) 代理，例如 http://127.0.0.1:7890")
    parser.add_argument("--force", action="store_true", help="覆盖已存在的字体文件")
    parser.add_argument("--timeout", type=int, default=120, help="网络超时秒数（默认：120）")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    destination = Path(args.output).expanduser().resolve()

    if destination.exists() and not args.force:
        print(f"字体已存在：{destination}")
        print("如需重新下载，请加 --force。")
        return 0

    opener = build_opener(args.proxy)
    release_tag = "latest"
    asset_url = LATEST_DOWNLOAD_URL.format(asset=args.asset)
    expected_size = 0

    try:
        release = request_json(opener, API_URL, args.timeout)
        release_tag = release.get("tag_name", "latest")
        assets = release.get("assets", [])
        asset = next((item for item in assets if item.get("name") == args.asset), None)

        if asset is None:
            names = ", ".join(item.get("name", "?") for item in assets) or "无"
            print(
                f"最新 release {release_tag} 中没有找到 {args.asset}。\n"
                f"可用资产：{names}",
                file=sys.stderr,
            )
            return 1

        asset_url = asset["browser_download_url"]
        expected_size = int(asset.get("size") or 0)
        print(f"最新版本：{release_tag}")
    except (urllib.error.URLError, OSError, ValueError) as exc:
        print(f"GitHub API 请求失败：{exc}", file=sys.stderr)
        print("尝试使用 latest/download 直链。", file=sys.stderr)

    print(f"字体：{args.asset}")
    print(f"保存到：{destination}")

    try:
        download_file(opener, asset_url, destination, expected_size, args.timeout)
    except (urllib.error.URLError, OSError, RuntimeError) as exc:
        print(f"\n下载失败：{exc}", file=sys.stderr)
        return 1

    print(f"完成：{destination} ({human_size(destination.stat().st_size)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
