#!/usr/bin/env python3
"""Backfill analysis for existing runs using Claude Opus with extended thinking."""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from run_games import generate_run_analysis


def main():
    parser = argparse.ArgumentParser(description="Generate analysis for existing runs")
    parser.add_argument("--run", required=True, help="Run ID to analyze (e.g., 2025-12-09_09-39-32)")
    parser.add_argument("--force", action="store_true", help="Regenerate existing analysis")
    args = parser.parse_args()

    # Change to project root
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.chdir(project_root)

    run_path = f"runs/{args.run}/run.json"
    if not os.path.exists(run_path):
        print(f"Run not found: {run_path}")
        return 1

    with open(run_path) as f:
        data = json.load(f)

    if data.get("analysis") and not args.force:
        print("Run already has analysis. Use --force to regenerate.")
        return 0

    print(f"Generating analysis for {args.run} using Claude Opus with extended thinking...")

    analysis = generate_run_analysis(data["stats"], data["contestant_stats"])
    data["analysis"] = analysis

    with open(run_path, "w") as f:
        json.dump(data, f, indent=2)

    print(f"Analysis saved to {run_path}")
    print(f"\nAnalysis preview:\n{analysis['content'][:500]}...")
    return 0


if __name__ == "__main__":
    exit(main())
