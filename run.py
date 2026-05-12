#!/usr/bin/env python3
"""
Agent Sandbox Security Scanner - Phase 3: 批量自动化评测与报告出具

Usage:
    python run.py [--reset each|category|none] [--output reports/]
    python run.py --dry-run              # 仅列出测试用例，不执行

Examples:
    python run.py                        # 默认：按类别重置沙箱
    python run.py --reset each           # 每个用例前重置沙箱
    python run.py --reset none           # 不重置沙箱
    python run.py --output my_reports/   # 指定输出目录
    python run.py --dry-run              # 打印测试计划
"""

import argparse
import os
import random
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

import yaml

from automation.config import RAW_CASES_DIR
from automation.sandbox import start_sandbox, restart_sandbox, check_running
from automation.client import AgentClient
from automation.validator import validate
from automation.reporter import generate_report


def parse_args():
    parser = argparse.ArgumentParser(
        description="Agent Sandbox Security Scanner - 批量自动化安全评测",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--reset", choices=["each", "category", "none"], default="category",
        help="沙箱重置策略: each=每个用例重置, category=每个类别重置, none=不重置 (default: category)",
    )
    parser.add_argument(
        "--output", default=None,
        help="报告输出目录 (default: reports/)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="仅列出测试用例，不实际执行",
    )
    parser.add_argument(
        "--seed", type=int, default=None,
        help="随机种子，用于可复现测试 (default: 随机)",
    )
    return parser.parse_args()


def load_test_cases() -> list[dict]:
    if not RAW_CASES_DIR.exists():
        print(f"[ERROR] 测试用例目录不存在: {RAW_CASES_DIR}")
        sys.exit(1)

    yaml_files = sorted(RAW_CASES_DIR.glob("*.yaml"))
    if not yaml_files:
        print(f"[ERROR] 未找到 YAML 测试用例: {RAW_CASES_DIR}")
        sys.exit(1)

    cases = []
    for f in yaml_files:
        try:
            with open(f, "r", encoding="utf-8") as fh:
                case = yaml.safe_load(fh)
            if case and "name" in case:
                cases.append(case)
        except Exception as e:
            print(f"[WARN] 无法解析 {f.name}: {e}")

    return cases


def group_by_category(cases: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    for c in cases:
        cat = c.get("category", "Unknown")
        groups.setdefault(cat, []).append(c)
    return groups


def run_single_case(client: AgentClient, case: dict, index: int, total: int) -> dict:
    name = case.get("name", "Unknown")
    cat = case.get("category", "Unknown")
    payload = case.get("payload", "").strip()
    validation_rules = case.get("validation", {})

    print(f"\n{'='*60}")
    print(f"[{index}/{total}] {name}")
    print(f"  类别: {cat}")
    print(f"  风险: {case.get('risk_level', 'N/A')}")
    print(f"  描述: {case.get('description', 'N/A')}")
    print(f"{'='*60}")

    print(f"  → 发送攻击载荷 ({len(payload)} 字符)...")
    api_result = client.send_message(payload)

    if not api_result["success"]:
        print(f"  ✗ API 调用失败: {api_result.get('error', 'Unknown')}")
        return {
            "name": name,
            "category": cat,
            "risk_level": case.get("risk_level", "N/A"),
            "description": case.get("description", ""),
            "payload": payload,
            "verdict": "error",
            "response_text": "",
            "error": api_result.get("error", "Unknown error"),
            "elapsed": api_result.get("elapsed", 0),
            "matched_keywords": [],
            "matched_forbidden": [],
        }

    response_text = api_result.get("response_text", "")

    print(f"  ← 收到响应 ({len(response_text)} 字符, {api_result.get('elapsed', 0)}s)")

    val_result = validate(response_text, validation_rules)
    verdict = val_result.severity
    icon = {"safe": "✅", "suspicious": "⚠️", "vulnerable": "🔴"}.get(verdict, "❓")

    print(f"  {icon} 判定: {verdict.upper()}")
    if val_result.matched_forbidden:
        print(f"     禁止内容命中: {val_result.matched_forbidden}")
    if val_result.matched_keywords:
        print(f"     敏感关键词: {val_result.matched_keywords}")

    return {
        "name": name,
        "category": cat,
        "risk_level": case.get("risk_level", "N/A"),
        "description": case.get("description", ""),
        "payload": payload,
        "verdict": verdict,
        "response_text": response_text,
        "error": None,
        "elapsed": api_result.get("elapsed", 0),
        "matched_keywords": val_result.matched_keywords,
        "matched_forbidden": val_result.matched_forbidden,
    }


def main():
    args = parse_args()

    if args.output:
        from automation import config
        config.REPORTS_DIR = Path(args.output)

    cases = load_test_cases()
    if not cases:
        print("[ERROR] 没有找到有效的测试用例。")
        sys.exit(1)

    random.seed(args.seed)
    random.shuffle(cases)

    print(f"\n{'='*60}")
    print(f"  Agent Sandbox Security Scanner")
    print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  用例数: {len(cases)}")
    print(f"  重置策略: {args.reset}")
    print(f"  随机种子: {args.seed or '随机'}")
    print(f"{'='*60}")

    if args.dry_run:
        print("\n[DRY RUN] 测试计划（随机顺序）:\n")
        for i, case in enumerate(cases, 1):
            print(f"  {i:2d}. [{case.get('category', 'N/A')}] {case.get('name', 'N/A')}")
        print(f"\n共 {len(cases)} 个测试用例。")
        return

    if not start_sandbox():
        print("[ERROR] 无法启动 Docker 沙箱。请检查 Docker 是否运行。")
        sys.exit(1)

    client = AgentClient()

    groups = group_by_category(cases)
    categories_order = list(groups.keys())

    results: list[dict] = []
    case_index = 0

    try:
        if args.reset == "each":
            for case in cases:
                restart_sandbox()
                time.sleep(3)
                case_index += 1
                result = run_single_case(client, case, case_index, len(cases))
                results.append(result)

        elif args.reset == "category":
            for cat in categories_order:
                print(f"\n{'#'*60}")
                print(f"  >>> 进入类别: {cat}")
                print(f"{'#'*60}")
                restart_sandbox()
                time.sleep(3)
                for case in groups[cat]:
                    case_index += 1
                    result = run_single_case(client, case, case_index, len(cases))
                    results.append(result)

        else:  # none
            for case in cases:
                case_index += 1
                result = run_single_case(client, case, case_index, len(cases))
                results.append(result)

    except KeyboardInterrupt:
        print("\n\n[INFO] 用户中断。正在生成已完成的评测报告...")
    except Exception as e:
        print(f"\n[ERROR] 执行过程中发生异常: {e}")
        traceback.print_exc()
    finally:
        if results:
            print(f"\n{'='*60}")
            print(f"  正在生成报告...")
            report_path = generate_report(results)
            print(f"  报告已保存至: {report_path}")
            print(f"{'='*60}")

            print_summary(results)
        else:
            print("\n[INFO] 没有测试结果可生成报告。")


def print_summary(results: list[dict]):
    safe = sum(1 for r in results if r["verdict"] == "safe")
    suspicious = sum(1 for r in results if r["verdict"] == "suspicious")
    vulnerable = sum(1 for r in results if r["verdict"] == "vulnerable")
    errors = sum(1 for r in results if r["verdict"] == "error")

    valid = len(results) - errors
    score = ((safe * 100 + suspicious * 40) / valid * 1.0) if valid > 0 else 0

    print(f"\n{'='*60}")
    print(f"  评测摘要")
    print(f"  {'─'*40}")
    print(f"  ✅ 安全通过:    {safe}/{len(results)}")
    print(f"  ⚠️  可疑:        {suspicious}/{len(results)}")
    print(f"  🔴 漏洞确认:    {vulnerable}/{len(results)}")
    print(f"  ❌ 执行失败:    {errors}/{len(results)}")
    print(f"  🛡️  安全得分:    {score:.1f}%")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
