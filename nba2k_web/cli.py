from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

from nba2k_web.config import WebConfig, load_player_id, save_player_id
from nba2k_web.notify import notify
from nba2k_web.rewards import claim_all
from nba2k_web.runtime import ClaimLogger, write_report
from nba2k_web.session import ensure_logged_in, load_state, run_login, save_state


def _config(runtime_dir: Path) -> WebConfig:
    return WebConfig(runtime_dir=runtime_dir)


def _resolve_player_id(config: WebConfig, player_id: str | None) -> str | None:
    if player_id and player_id.strip():
        return player_id.strip()
    return load_player_id(config)


def run_claim(config: WebConfig, player_id: str | None) -> int:
    player_id = _resolve_player_id(config, player_id)
    logger = ClaimLogger(config)
    started_at = datetime.now().astimezone()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=config.headless)
        context = browser.new_context(storage_state=load_state(config))
        page = context.new_page()
        page.goto(f"{config.base_url}/dailystreak", wait_until="domcontentloaded")
        page.wait_for_timeout(4000)

        if not ensure_logged_in(page, player_id or "", config):
            message = "登录失败，缺少 Player ID 或验证未通过"
            print(message)
            notify("NBA 2K Web 领取失败", message)
            browser.close()
            return 2

        summary = claim_all(page, config)
        save_state(context, config)
        browser.close()

    ended_at = datetime.now().astimezone()
    for outcome in summary.outcomes:
        logger.write(
            {
                "timestamp": datetime.now().isoformat(),
                "source": outcome.source,
                "label": outcome.label,
                "claimed": outcome.claimed,
            }
        )
    report = {
        "started_at": started_at.isoformat(),
        "ended_at": ended_at.isoformat(),
        "claimed": summary.claimed,
        "failed": summary.failed,
        "outcomes": [
            {"source": o.source, "label": o.label, "claimed": o.claimed}
            for o in summary.outcomes
        ],
    }
    report_path = write_report(config, report)

    if summary.failed:
        message = f"领取完成，{summary.claimed} 项成功，{summary.failed} 项失败"
        print(message)
        notify("NBA 2K Web 领取部分失败", message)
    else:
        message = (
            f"今日领取完成：{summary.claimed} 项成功"
            if summary.claimed
            else "今日无可领取项（可能已全部领取）"
        )
        print(message)
    print(f"报告：{report_path.resolve()}")
    return 0


def run_doctor(config: WebConfig) -> int:
    print(f"base_url: {config.base_url}")
    player_id = load_player_id(config)
    print(f"player_id: {'已配置（' + player_id[:4] + '…）' if player_id else '未配置（首次请用 login 命令）'}")
    print(f"会话状态: {'存在' if config.state_path.exists() else '不存在'} "
          f"({config.state_path.resolve()})")
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            browser.close()
        print("浏览器内核: OK（可正常启动 Chromium）")
        return 0
    except Exception as exc:
        print(f"浏览器内核: 不可用，请运行 `python -m playwright install chromium`（{exc}）")
        return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nba2k-web",
        description="NBA 2K Mobile Webstore 每日奖励自动领取（本机运行）",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    login_parser = subparsers.add_parser("login", help="有头登录并保存会话")
    login_parser.add_argument("--player-id", help="Player ID（不填则读环境变量或本地配置）")

    claim_parser = subparsers.add_parser("claim", help="领取今日奖励")
    claim_parser.add_argument("--player-id", help="Player ID（不填则读环境变量或本地配置）")
    claim_parser.add_argument(
        "--headed", action="store_true", help="有头运行，便于观察"
    )

    subparsers.add_parser("doctor", help="检查环境与配置")

    for command_parser in (login_parser, claim_parser):
        command_parser.add_argument(
            "--runtime-dir",
            type=Path,
            default=Path("runtime") / "web",
            help="运行时数据目录（默认 runtime/web）",
        )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "doctor":
        return run_doctor(_config(Path("runtime") / "web"))
    if args.command == "login":
        config = _config(args.runtime_dir)
        player_id = _resolve_player_id(config, args.player_id)
        if not player_id:
            player_id = input("请输入 Player ID: ").strip()
            if not player_id:
                print("未提供 Player ID。")
                return 2
        save_player_id(config, player_id)
        return 0 if run_login(config, player_id) else 2
    if args.command == "claim":
        config = _config(args.runtime_dir)
        if args.headed:
            config = WebConfig(runtime_dir=config.runtime_dir, headless=False)
        return run_claim(config, args.player_id)
    return 2


if __name__ == "__main__":
    sys.exit(main())
