"""Build ETrade Trader.exe — branded launcher with embedded icon for the taskbar."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"
STUB = ROOT / "etrade_trader_stub.py"
ICON = ROOT / "etrade_trader.ico"
OUT_EXE = ROOT / "ETrade Trader.exe"


def main() -> int:
    if not VENV_PY.exists():
        print("Run Install ETrade Trader.bat first.")
        return 1
    if not STUB.exists() or not ICON.exists():
        print("Missing launcher stub or icon.")
        return 1

    subprocess.check_call([str(VENV_PY), "-m", "pip", "install", "pyinstaller", "-q"])
    dist = ROOT / "dist" / "ETrade Trader.exe"
    build = ROOT / "build"
    spec = ROOT / "ETrade Trader.spec"

    hidden = [
        "tkinter.filedialog",
        "tkinter.messagebox",
        "tkinter.ttk",
        "tzdata",
        "zoneinfo",
        "app_paths",
        "gui_theme",
        "gui_treekit",
        "finance_runners",
        "agent_report_status",
        "finance_agents_gui",
        "agent_report_formatter",
        "prediction_accuracy",
        "historical_simulation",
        "symbol_universe",
        "price_history",
        "agent_fusion",
        "agents.platform_catalog",
        "agents.enhancement",
        "agents.market_predictor",
        "etrade_market_enhancer",
        "portfolio_generator",
        "order_type_selector",
        "position_analysis",
        "position_chart",
        "account_growth_chart",
        "account_balance_penalty",
        "agent_personality",
        "agent_learning",
        "trade_history",
        "github_sync",
        "strategy_engine",
        "trade_guards",
        "trading_gate",
        "etrade_worker",
    ]
    cmd = [
        str(VENV_PY),
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--onefile",
        "--windowed",
        f"--icon={ICON}",
        "--name",
        "ETrade Trader",
        "--distpath",
        str(ROOT / "dist"),
        "--workpath",
        str(build),
        "--specpath",
        str(ROOT),
        *(f"--hidden-import={name}" for name in hidden),
        "--collect-submodules",
        "tzdata",
        str(STUB),
    ]
    subprocess.check_call(cmd, cwd=str(ROOT))

    if not dist.exists():
        print("Build failed — exe not found.")
        return 1

    try:
        if OUT_EXE.exists():
            OUT_EXE.unlink()
        dist.replace(OUT_EXE)
    except PermissionError:
        pending = ROOT / "ETrade Trader.new.exe"
        if pending.exists():
            pending.unlink()
        dist.replace(pending)
        print(
            f"Built {pending.name} — close the running app, then rename it to {OUT_EXE.name}"
        )
        return 0
    if dist.parent.exists() and not any(dist.parent.iterdir()):
        dist.parent.rmdir()
    if build.exists():
        import shutil

        shutil.rmtree(build, ignore_errors=True)
    if spec.exists():
        spec.unlink()

    print(f"Built {OUT_EXE.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())