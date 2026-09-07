"""Regression guard for the category-pill attribute-injection fix.

static/index.html has no build step and no JS test harness (see CLAUDE.md —
it is one hand-written file by design), so this asserts the source pattern
directly rather than exercising a browser.

The category pill's onclick attribute used to embed a raw
`JSON.stringify(c)` of the (server-stored, admin-supplied but
publicly-rendered) category name straight into an HTML attribute value.
JSON.stringify only produces *JavaScript*-safe quoting (backslash-escaped
quotes); it does not HTML-escape, so a category name containing a `"`
could close the `onclick="..."` attribute early and inject arbitrary
markup/attributes into a page every anonymous visitor loads. Every other
piece of user-controlled text in this file goes through escHtml() before
being written into the DOM — this was the one spot that didn't.
"""
from pathlib import Path

INDEX_HTML = Path(__file__).resolve().parent.parent / "static" / "index.html"


def _source():
    return INDEX_HTML.read_text()


def test_category_pill_onclick_html_escapes_the_json_payload():
    src = _source()
    # The vulnerable pattern: JSON.stringify(c) spliced straight into the
    # attribute with no HTML-escaping.
    assert "onclick=\"setCategory(${JSON.stringify(c)})\"" not in src
    # The fix: the JSON string is HTML-escaped before it lands in the
    # attribute, so an embedded `"` becomes `&quot;` instead of closing the
    # attribute early.
    assert "onclick=\"setCategory(${escHtml(JSON.stringify(c))})\"" in src


def test_esc_html_escapes_both_quote_styles():
    # Sanity-check the helper itself still escapes what this fix relies on.
    src = _source()
    assert "replace(/\"/g,'&quot;')" in src
    assert "replace(/'/g,'&#39;')" in src
