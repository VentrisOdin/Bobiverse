#!/usr/bin/env python
import json
import sys
from pathlib import Path
from typing import Optional

from lxml import etree  # make sure lxml is installed in .venv


REPO_ROOT = Path(__file__).resolve().parents[1]
BRAIN_ROOT = REPO_ROOT / "data" / "brains" / "knowledge_bob"

PLOS_XML_DIR = BRAIN_ROOT / "sources" / "plos" / "xml"
OUT_DIR = BRAIN_ROOT / "cleaned" / "plos"
OUT_JSONL = OUT_DIR / "plos_articles.jsonl"

# For first test runs you can set this to e.g. 500
MAX_FILES: Optional[int] = None  # or 500 to test


def extract_text(tree: etree._ElementTree) -> dict:
    root = tree.getroot()

    def norm(text: str | None) -> str:
        if not text:
            return ""
        return " ".join(text.split())

    # Use local-name() to ignore namespaces
    title = norm(root.xpath("string(//*[local-name()='article-title'])"))
    abstract = norm(root.xpath("string(//*[local-name()='abstract'])"))
    body = norm(root.xpath("string(//*[local-name()='body'])"))
    journal = norm(root.xpath("string(//*[local-name()='journal-title'])"))
    year = norm(root.xpath("string(//*[local-name()='pub-date']/*[local-name()='year'])"))

    return {
        "title": title,
        "abstract": abstract,
        "body": body,
        "journal": journal,
        "year": year,
    }


def main() -> None:
    if not PLOS_XML_DIR.exists():
        print(f"[ERROR] PLOS XML directory not found: {PLOS_XML_DIR}", file=sys.stderr)
        sys.exit(1)

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    xml_files = sorted(PLOS_XML_DIR.glob("*.xml"))
    if not xml_files:
        print(f"[WARN] No XML files found in {PLOS_XML_DIR}")
        return

    total = len(xml_files)
    if MAX_FILES is not None:
        xml_files = xml_files[:MAX_FILES]

    print(f"[INFO] Found {total} PLOS XML files; processing {len(xml_files)}")

    count = 0
    with OUT_JSONL.open("w", encoding="utf-8") as out_f:
        for i, xml_path in enumerate(xml_files, start=1):
            try:
                tree = etree.parse(str(xml_path))
                fields = extract_text(tree)
            except Exception as e:
                print(f"[WARN] Failed to parse {xml_path.name}: {e}", file=sys.stderr)
                continue

            if not fields["title"] and not fields["body"]:
                continue

            record = {
                "id": xml_path.stem,
                "source": "PLOS",
                "tier": "A",
                **fields,
            }
            out_f.write(json.dumps(record, ensure_ascii=False) + "\n")
            count += 1

            if i % 500 == 0:
                print(f"[INFO] Processed {i} / {len(xml_files)} XML files...")

    print(f"[DONE] Wrote {count} cleaned PLOS articles to {OUT_JSONL}")


if __name__ == "__main__":
    main()

