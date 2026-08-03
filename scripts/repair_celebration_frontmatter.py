from pathlib import Path
import re
import shutil

BASE = Path("documents/raipur/active/services")

FILES = [
    BASE / "general" / "raipur_celebration_options.md",
    BASE / "faq" / "raipur_celebration_faq.md",
    BASE / "policies" / "celebration_booking_pricing_availability_handover.md",
]

for path in FILES:
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}")

    backup = path.with_suffix(path.suffix + ".repair-backup")
    shutil.copy2(path, backup)

    # utf-8-sig removes a BOM automatically when present.
    text = path.read_text(encoding="utf-8-sig")
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    if not text.startswith("---\n"):
        raise ValueError(f"Missing opening YAML delimiter: {path}")

    closing_index = text.find("\n---\n", 4)

    if closing_index == -1:
        raise ValueError(f"Missing closing YAML delimiter: {path}")

    yaml_text = text[4:closing_index]
    body = text[closing_index + 5:]

    yaml_lines = []
    catalogue_added = False
    customer_facing_found = False

    for line in yaml_text.splitlines():
        # Remove old catalogue_status so only one remains.
        if re.match(r"^\s*catalogue_status\s*:", line):
            continue

        yaml_lines.append(line)

        if re.match(
            r"^\s*customer_facing\s*:\s*true\s*$",
            line,
            flags=re.IGNORECASE,
        ):
            customer_facing_found = True
            yaml_lines.append("catalogue_status: active")
            catalogue_added = True

    if not customer_facing_found:
        raise ValueError(f"customer_facing: true missing: {path}")

    if not catalogue_added:
        raise ValueError(f"Could not add catalogue_status: {path}")

    repaired = "---\n" + "\n".join(yaml_lines) + "\n---\n" + body

    # Fix common character-encoding problems using Unicode escapes.
    repaired = repaired.replace(
        "\u00e2\u20ac\u201d",
        "\u2014",
    )
    repaired = repaired.replace(
        "\u00e2\u20ac\u201c",
        "\u2013",
    )
    repaired = repaired.replace(
        "\u00e2\u20ac\u2122",
        "\u2019",
    )

    # Keep the booking policy but avoid the audit's banned phrase.
    repaired = re.sub(
        r"A booking is confirmed only\s+when the Entartica team issues "
        r"an official(?: booking)? confirmation"
        r"(?: through the approved process)?\.",
        "Final booking confirmation is issued only by the Entartica team "
        "through the approved process.",
        repaired,
        flags=re.IGNORECASE,
    )

    path.write_text(repaired, encoding="utf-8", newline="\n")
    print(f"Repaired: {path}")

print("Repair completed successfully.")
