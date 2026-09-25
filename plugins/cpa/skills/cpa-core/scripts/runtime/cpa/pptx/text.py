"""Run-preserving replacements for explicitly mapped presentation text slots.

U06/U13/U17: preserve template styling and hyperlinks; no guessed mixed-run restyling.
FIXTURE - confirm against her file.
"""
from difflib import SequenceMatcher

from cpa.office import OfficeSafetyError


def replace_text(text_frame, text: str) -> None:
    """Plan all replacements first, then edit run text only; refuse ambiguous style boundaries.

    Paragraph count, fields and soft breaks require a more precise template mapping. An insertion
    exactly between differently styled runs is ambiguous and is not assigned an invented style.
    """
    paragraphs = list(text_frame.paragraphs)
    lines = text.split("\n")
    if len(lines) != len(paragraphs):
        raise OfficeSafetyError("ambiguous paragraph replacement; confirm the template text slots")
    plans = []
    for paragraph, new_text in zip(paragraphs, lines):
        if paragraph.text == new_text:
            continue
        if any(e.tag.endswith(("}fld", "}br")) for e in paragraph._p):
            raise OfficeSafetyError("ambiguous field/soft-break replacement; confirm a plain text slot")
        runs = list(paragraph.runs)
        if not runs:
            plans.append((paragraph, None, [new_text]))
            continue
        old = "".join(run.text for run in runs)
        bounds = []
        offset = 0
        for run in runs:
            bounds.append((offset, offset + len(run.text)))
            offset += len(run.text)
        values = [run.text for run in runs]
        properties = [str(run._r.rPr.xml) if run._r.rPr is not None else None for run in runs]
        for op, start, end, new_start, new_end in reversed(SequenceMatcher(None, old, new_text, autojunk=False).get_opcodes()):
            if op == "equal":
                continue
            owners = [i for i, (lo, hi) in enumerate(bounds) if
                      (lo < end and hi > start) or (start == end and lo <= start <= hi)]
            if not owners:
                owners = [0]
            if len({properties[i] for i in owners}) > 1:
                raise OfficeSafetyError("ambiguous mixed-run replacement; confirm a narrower template text slot")
            first, last = owners[0], owners[-1]
            lo, hi = bounds[first][0], bounds[last][0]
            replacement = values[first][:start - lo] + new_text[new_start:new_end]
            suffix = values[last][end - hi:]
            if first == last:
                values[first] = replacement + suffix
            else:
                values[first] = replacement
                for index in owners[1:-1]:
                    values[index] = ""
                values[last] = suffix
        plans.append((paragraph, runs, values))
    for paragraph, runs, values in plans:
        if runs is None:
            paragraph.add_run().text = values[0]
        else:
            for run, value in zip(runs, values):
                run.text = value
