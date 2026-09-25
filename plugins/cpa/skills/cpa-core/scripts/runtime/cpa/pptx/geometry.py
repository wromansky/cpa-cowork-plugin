"""Conservative slide geometry diagnostics, not rendered visual acceptance.

U06/U13: transformed group bounds, possible text collisions and unfinished placeholders.
FIXTURE - confirm against her file. No automatic restyling or text shrinking.
"""
import math
import re

_IDENTITY = (1, 0, 0, 1, 0, 0)
_PLACEHOLDER = re.compile(r"\{\{[^{}]+\}\}|\$\{[^{}]+\}|\b(?:TODO|TBD)\b|\[INSERT [^\]]+\]", re.I)


def _multiply(a, b):
    x, y, z, w, u, v = a
    p, q, r, s, t, k = b
    return (x*p + z*q, y*p + w*q, x*r + z*s, y*r + w*s, x*t + z*k + u, y*t + w*k + v)


def _point(matrix, x, y):
    a, b, c, d, e, f = matrix
    return a*x + c*y + e, b*x + d*y + f


def _rotation(shape, *, flip_h=False, flip_v=False):
    angle = math.radians(shape.rotation)
    c, s = math.cos(angle), math.sin(angle)
    cx, cy = shape.left + shape.width / 2, shape.top + shape.height / 2
    a, b = (-c, -s) if flip_h else (c, s)
    d, e = (s, -c) if flip_v else (-s, c)
    return (a, b, d, e, cx - a*cx - d*cy, cy - b*cx - e*cy)


def _bounds(shapes, matrix=_IDENTITY, parent=""):
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    for shape in shapes:
        identity = f"{parent}/{shape.shape_id}:{shape.name}"
        if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            xf = shape._element.grpSpPr.xfrm
            if xf is None or xf.chOff is None or xf.chExt is None or not xf.chExt.cx or not xf.chExt.cy:
                yield identity, shape, None
                continue
            sx, sy = shape.width / xf.chExt.cx, shape.height / xf.chExt.cy
            mapping = (sx, 0, 0, sy, shape.left - sx*xf.chOff.x, shape.top - sy*xf.chOff.y)
            transform = _multiply(matrix, _multiply(_rotation(shape, flip_h=bool(xf.flipH),
                                                             flip_v=bool(xf.flipV)), mapping))
            yield from _bounds(shape.shapes, transform, identity)
            continue
        transform = _multiply(matrix, _rotation(shape))
        points = [_point(transform, x, y) for x in (shape.left, shape.left + shape.width)
                  for y in (shape.top, shape.top + shape.height)]
        yield identity, shape, (min(p[0] for p in points), min(p[1] for p in points),
                                max(p[0] for p in points), max(p[1] for p in points))


def diagnostics(prs) -> list[tuple[str, str, str]]:
    """Return conservative geometry/placeholder findings using transformed bounding rectangles.

    Only text/text partial intersections are flagged; containment often means intentional
    backgrounds/labels. Rotated bounding boxes may overstate collisions and require review.
    Missing-data flags are not unfinished template placeholders.
    """
    findings = []
    tolerance = 12700  # one point of edge-rounding tolerance, not a rendered-text measurement
    for n, slide in enumerate(prs.slides, 1):
        texts = []
        identities = set()
        for identity, shape, bounds in _bounds(slide.shapes):
            loc = f"slide {n} shape {identity}"
            if shape.shape_id in identities:
                findings.append(("DUPLICATE_SHAPE_ID", loc, "ambiguous shape identity; confirm the template"))
            identities.add(shape.shape_id)
            if bounds is None:
                findings.append(("GEOMETRY_UNCHECKED", loc, "group transform is incomplete; visual review required"))
                continue
            l, t, r, b = bounds
            if l < -tolerance or t < -tolerance or r > prs.slide_width + tolerance or b > prs.slide_height + tolerance:
                findings.append(("OFF_SLIDE", loc, "transformed shape bounds extend outside the slide"))
            if shape.has_text_frame and shape.text_frame.text.strip():
                text = shape.text_frame.text
                if _PLACEHOLDER.search(text) or text.casefold().startswith("click to add "):
                    findings.append(("UNFINISHED_PLACEHOLDER", loc, "mapped template text still needs review"))
                texts.append((loc, bounds))
        # Bound pairwise work for pathological presentations; never claim an exhaustive scan then.
        if len(texts) > 500:
            findings.append(("GEOMETRY_UNCHECKED", f"slide {n}", "text collision comparison limit exceeded"))
            continue
        for i, (loc, a) in enumerate(texts):
            for other, b in texts[i + 1:]:
                width, height = min(a[2], b[2]) - max(a[0], b[0]), min(a[3], b[3]) - max(a[1], b[1])
                contained = (a[0] <= b[0] and a[1] <= b[1] and a[2] >= b[2] and a[3] >= b[3]) or (
                    b[0] <= a[0] and b[1] <= a[1] and b[2] >= a[2] and b[3] >= a[3])
                if width > tolerance and height > tolerance and not contained:
                    findings.append(("POSSIBLE_TEXT_OVERLAP", loc, f"bounding box intersects {other}; inspect visually"))
    return findings
