import html
import json
import os
import re
from html.parser import HTMLParser

import markdown
from mkdocs.config import config_options
from mkdocs.plugins import BasePlugin
from mkdocs.structure.nav import Section
from mkdocs.structure.pages import Page
from mkdocs.utils import copy_file, get_relative_url, log

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
JS_FILENAME = "cheatsheet.js"
CSS_FILENAME = "cheatsheet.css"
ASSET_PREFIX = "assets/cheatsheet"
CONFIG_SCRIPT_ID = "md-cheatsheet-config"

# The attribute a heading's marker is rewritten to before attr_list sees it.
# Stripped again from the rendered page in on_page_content.
DATA_ATTR = "data-cheatsheet"
SKIP_VALUE = "\x00skip"

PLACEHOLDER_RE = re.compile(r"<!--\s*cheatsheet\b(?P<args>[^>]*?)-->")
PLACEHOLDER_ARG_RE = re.compile(r'(\w+)\s*=\s*"([^"]*)"')
PLACEHOLDER_ARGS = ("section", "exclude", "class")
VOID_TAGS = {"area", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
HEADING_RE = re.compile(r"^(?P<head>\s*#{1,6}\s.*?)\s*\{(?P<colon>:?)(?P<attrs>[^{}]*)\}\s*$")
ATTR_TOKEN_RE = re.compile(r"""[^\s="']+(?:=(?:"[^"]*"|'[^']*'|[^\s"']+))?""")
DATA_ATTR_STRIP_RE = re.compile(r'\s' + DATA_ATTR + r'="[^"]*"')


def _split_labels(value):
    """Split a marker value on commas; `\\,` keeps a literal comma."""
    parts = re.split(r"(?<!\\),", value)
    return [p.replace("\\,", ",").strip() for p in parts if p.strip()]


class _HeadingCollector(HTMLParser):
    """Collects every h1-h6 in rendered page HTML: level, attributes, text."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.headings = []
        self._current = None
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if self._current is None:
            if re.fullmatch(r"h[1-6]", tag):
                self._current = {"level": int(tag[1]), "attrs": dict(attrs), "text": "", "icon": ""}
            return
        attrs = dict(attrs)
        if tag in VOID_TAGS:
            return
        if self._skip_depth or (tag == "a" and "headerlink" in (attrs.get("class") or "")):
            self._skip_depth += 1

    def handle_endtag(self, tag):
        if self._current is None:
            return
        if tag == "h%d" % self._current["level"] and not self._skip_depth:
            self._current["text"] = " ".join(self._current["text"].split())
            self.headings.append(self._current)
            self._current = None
        elif self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data):
        if self._current is not None and not self._skip_depth:
            self._current["text"] += data


class CheatsheetPlugin(BasePlugin):
    config_scheme = (
        ("marker", config_options.Type(str, default="cs")),
        ("default", config_options.Choice(("exclude", "include"), default="exclude")),
        ("sort", config_options.Choice(("source", "alphabetical"), default="source")),
        ("code", config_options.Type(bool, default=True)),
        ("button", config_options.Type(bool, default=False)),
        ("button_label", config_options.Type(str, default="Cheatsheet")),
        ("group_titles", config_options.Type(dict, default={})),
        ("group_heading_level", config_options.Type(int, default=2)),
        ("container_class", config_options.Type(list, default=[])),
        ("group_class", config_options.Type(list, default=[])),
        ("summary_group_class", config_options.Type(list, default=[])),
        ("group_title_class", config_options.Type(list, default=[])),
        ("card_class", config_options.Type(list, default=[])),
    )

    # -- config / assets ------------------------------------------------------

    def on_config(self, config):
        marker = re.escape(self.config["marker"])
        self._marker_re = re.compile(r"^" + marker + r"(?:=(?P<value>.*))?$")
        self._skip_token = self.config["marker"] + "-skip"
        self._pages = {}
        self._placeholder_pages = set()
        self._md = None
        self._md_config = config
        self._warned_button = False
        self._homepage = None

        exts = [str(e) for e in config["markdown_extensions"]]
        if not any(e in ("attr_list", "markdown.extensions.attr_list") or e.endswith(".attr_list") for e in exts):
            log.warning(
                "cheatsheet: the attr_list markdown extension is not enabled, so {%s} "
                "markers will not be removed from headings. Add 'attr_list' to "
                "markdown_extensions." % self.config["marker"]
            )

        extra_css = list(config.get("extra_css", []))
        extra_js = list(config.get("extra_javascript", []))
        css_uri = f"{ASSET_PREFIX}/{CSS_FILENAME}"
        js_uri = f"{ASSET_PREFIX}/{JS_FILENAME}"
        if css_uri not in extra_css:
            extra_css.insert(0, css_uri)
        if self.config["button"] and js_uri not in extra_js:
            extra_js.append(js_uri)
        config["extra_css"] = extra_css
        config["extra_javascript"] = extra_js
        return config

    def on_post_build(self, config):
        for filename in (JS_FILENAME, CSS_FILENAME):
            copy_file(
                os.path.join(STATIC_DIR, filename),
                os.path.join(config["site_dir"], ASSET_PREFIX, filename),
            )

    # -- per-page collection --------------------------------------------------

    def on_nav(self, nav, config, files):
        self._homepage = nav.homepage.file.src_uri if nav.homepage else None
        return nav

    def on_page_markdown(self, markdown_src, page, config, files):
        return self._rewrite_markers(markdown_src)

    def _rewrite_markers(self, src):
        out = []
        fence = None
        for line in src.split("\n"):
            m = FENCE_RE.match(line)
            if m:
                token = m.group(1)
                if fence is None:
                    fence = token
                elif token[0] == fence[0] and len(token) >= len(fence):
                    fence = None
                out.append(line)
                continue
            if fence is None:
                line = self._rewrite_heading(line)
            out.append(line)
        return "\n".join(out)

    def _rewrite_heading(self, line):
        m = HEADING_RE.match(line)
        if not m:
            return line
        tokens = ATTR_TOKEN_RE.findall(m.group("attrs"))
        kept, value = [], None
        for token in tokens:
            if token == self._skip_token:
                value = SKIP_VALUE
                continue
            tm = self._marker_re.match(token)
            if tm:
                raw = tm.group("value") or ""
                if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
                    raw = raw[1:-1]
                value = raw
                continue
            kept.append(token)
        if value is None:
            return line
        kept.append('%s="%s"' % (DATA_ATTR, html.escape(value, quote=True)))
        return "%s {%s %s }" % (m.group("head"), m.group("colon"), " ".join(kept))

    def on_page_content(self, page_html, page, config, files):
        # Checked in the rendered HTML, not the markdown: a placeholder shown
        # inside a code block is escaped by then and no longer matches.
        placeholders = PLACEHOLDER_RE.findall(page_html)
        if placeholders:
            self._placeholder_pages.add(page.file.src_uri)
            for args in placeholders:
                for name, _ in PLACEHOLDER_ARG_RE.findall(args):
                    if name not in PLACEHOLDER_ARGS:
                        log.warning(
                            "cheatsheet: unknown placeholder argument %r in %s (expected one of: %s)"
                            % (name, page.file.src_uri, ", ".join(PLACEHOLDER_ARGS))
                        )
        else:
            self._placeholder_pages.discard(page.file.src_uri)

        parser = _HeadingCollector()
        parser.feed(page_html)
        include_all = self.config["default"] == "include"

        top, rows, current = [], [], None
        icon = ""
        h1_text = next((h["text"] for h in parser.headings if h["level"] == 1), None)
        for h in parser.headings:
            attrs = h["attrs"]
            flag = attrs.get(DATA_ATTR)
            if flag == SKIP_VALUE:
                flag = None
            elif flag is None and include_all and h["level"] >= 2:
                flag = ""
            if h["level"] == 1:
                if flag is not None and h.get("attrs", {}).get("id"):
                    labels = _split_labels(flag) if flag else [h["text"]]
                    top.extend(self._term(label, h) for label in labels)
                continue
            if h["level"] == 2:
                current = {"parent": None, "terms": [], "attrs": {}}
                rows.append(current)
                if flag is not None:
                    # First label is the bold parent; any others are terms
                    # that link back to this same h2.
                    labels = _split_labels(flag) if flag else [h["text"]]
                    current["parent"] = self._term(labels[0], h)
                    current["terms"].extend(self._term(label, h) for label in labels[1:])
                    current["attrs"] = self._carried(attrs)
                continue
            if flag is None or not attrs.get("id"):
                continue
            if current is None:
                current = {"parent": None, "terms": [], "attrs": {}}
                rows.append(current)
            labels = _split_labels(flag) if flag else [h["text"]]
            current["terms"].extend(self._term(label, h) for label in labels)

        rows = [r for r in rows if r["parent"] or r["terms"]]
        if self.config["sort"] == "alphabetical":
            top.sort(key=lambda t: t["label"].lower())
            for r in rows:
                r["terms"].sort(key=lambda t: t["label"].lower())

        h1_icon = re.search(r"<h1[^>]*>\s*(<span class=\"twemoji[^\"]*\">.*?</span>)", page_html, re.S)
        if h1_icon:
            icon = h1_icon.group(1)

        self._pages[page.file.src_uri] = {"top": top, "rows": rows, "h1_icon": icon, "h1_text": h1_text}
        return DATA_ATTR_STRIP_RE.sub("", page_html)

    @staticmethod
    def _carried(attrs):
        return {k: v for k, v in attrs.items() if k.startswith("data-") and k != DATA_ATTR}

    def _term(self, label, heading):
        return {"label": label, "anchor": heading["attrs"].get("id", ""), "attrs": self._carried(heading["attrs"])}

    # -- rendering ------------------------------------------------------------

    def on_page_context(self, context, page, config, nav):
        if page.content and page.file.src_uri in self._placeholder_pages:
            page.content = PLACEHOLDER_RE.sub(
                lambda m: self._render(page, nav, dict(PLACEHOLDER_ARG_RE.findall(m.group("args")))),
                page.content,
            )
        return context

    def _render_md(self, text):
        """Render a short inline markdown snippet (icon shortcode, description)
        with the site's own extensions, minus snippets (its auto_append would
        tack glossary files onto every fragment)."""
        if self._md is None:
            exts = [e for e in self._md_config["markdown_extensions"] if "snippets" not in str(e)]
            self._md = markdown.Markdown(extensions=exts, extension_configs=self._md_config["mdx_configs"])
        self._md.reset()
        out = self._md.convert(str(text)).strip()
        if out.startswith("<p>") and out.endswith("</p>") and out.count("<p>") == 1:
            out = out[3:-4]
        return out

    def _scope_pages(self, page, nav, args):
        """(page, section) pairs to render, in nav order."""
        def as_dir(prefix):
            prefix = prefix.strip().lstrip("/")
            return prefix if prefix.endswith((".md", "/")) else prefix + "/"

        prefix = args.get("section")
        if prefix is not None:
            prefix = as_dir(prefix)
        excludes = [as_dir(p) for p in args.get("exclude", "").split(",") if p.strip()]
        roots = nav.items
        if prefix is None and page.parent is not None:
            roots = page.parent.children

        result = []

        def walk(items, section):
            for item in items:
                if isinstance(item, Section):
                    walk(item.children, item)
                elif isinstance(item, Page):
                    result.append((item, section))

        walk(roots, page.parent if prefix is None else None)
        out = []
        for p, section in result:
            src = p.file.src_uri
            if prefix is not None and not src.startswith(prefix):
                continue
            if any(src.startswith(e) for e in excludes):
                continue
            if src in self._placeholder_pages:
                continue
            if p.meta.get("cheatsheet") is False:
                continue
            out.append((p, section))
        return out

    def _is_summarized(self, p, current):
        """True when some ancestor section of `p` has an index page with its
        own cheatsheet (other than the page being rendered)."""
        section = p.parent
        while section is not None:
            for child in section.children:
                if (
                    isinstance(child, Page)
                    and child is not current
                    and child.file.src_uri in self._placeholder_pages
                    and os.path.basename(child.file.src_uri) in ("index.md", "README.md")
                ):
                    return True
            section = section.parent
        return False

    def _render(self, page, nav, args):
        groups, order = {}, []
        for p, section in self._scope_pages(page, nav, args):
            key = id(p.parent) if p.parent is not None else None
            if key not in groups:
                groups[key] = {"section": p.parent, "cards": [], "summary": False}
                order.append(key)
            summary = self._is_summarized(p, page)
            groups[key]["summary"] = groups[key]["summary"] or summary
            groups[key]["cards"].append(self._render_card(p, page, summary))

        container = ["md-cheatsheet"] + self.config["container_class"] + args.get("class", "").split()
        parts = ['<div class="%s">' % " ".join(container)]
        level = self.config["group_heading_level"]
        for key in order:
            g = groups[key]
            n = len(g["cards"])
            classes = ["md-cheatsheet__group", "md-cheatsheet__group--cards-%d" % n] + self.config["group_class"]
            if g["summary"]:
                classes += ["md-cheatsheet__group--summary"] + self.config["summary_group_class"]
            shared = self._shared_attrs([c[1] for c in g["cards"]])
            parts.append('<div class="%s" data-cheatsheet-cards="%d"%s>' % (" ".join(classes), n, self._attr_str(shared)))
            if g["section"] is not None:
                title = g["section"].title
                title = self.config["group_titles"].get(title, title)
                tclasses = ["md-cheatsheet__group-title"] + self.config["group_title_class"]
                parts.append('<h%d class="%s">%s</h%d>' % (level, " ".join(tclasses), html.escape(title), level))
            parts.append('<div class="grid cards md-cheatsheet__grid"><ul>')
            parts.extend(c[0] for c in g["cards"])
            parts.append("</ul></div></div>")
        parts.append("</div>")
        return "\n".join(parts)

    @staticmethod
    def _shared_attrs(attr_dicts):
        if not attr_dicts:
            return {}
        first = attr_dicts[0]
        return {k: v for k, v in first.items() if all(d.get(k) == v for d in attr_dicts[1:])}

    @staticmethod
    def _attr_str(attrs):
        return "".join(' %s="%s"' % (k, html.escape(str(v), quote=True)) for k, v in attrs.items())

    def _label(self, label, strong=False):
        text = html.escape(label)
        if self.config["code"]:
            text = "<code>%s</code>" % text
        if strong:
            text = "<strong>%s</strong>" % text
        return text

    def _link(self, target, current, anchor=""):
        url = get_relative_url(target.url or ".", current.url or ".")
        if url in ("", "."):
            url = "./"
        return url + ("#" + anchor if anchor else "")

    def _term_html(self, term, target, current):
        link = '<a class="md-cheatsheet__term" href="%s">%s</a>' % (
            html.escape(self._link(target, current, term["anchor"]), quote=True),
            self._label(term["label"]),
        )
        if term["attrs"]:
            link = '<span class="md-cheatsheet__term-wrap"%s>%s</span>' % (self._attr_str(term["attrs"]), link)
        return link

    def _render_card(self, p, current, summary):
        meta = p.meta or {}
        data = self._pages.get(p.file.src_uri, {"top": [], "rows": [], "h1_icon": "", "h1_text": None})
        card_attrs = {str(k): v for k, v in (meta.get("cheatsheet_attrs") or {}).items()}
        classes = ["md-cheatsheet__card"] + self.config["card_class"]

        icon = meta.get("cheatsheet_icon")
        if icon:
            icon = str(icon)
            if not icon.startswith(":"):
                icon = ":%s:" % icon
            icon_html = self._render_md(icon)
        else:
            icon_html = data["h1_icon"]
        if icon_html:
            icon_html = icon_html.replace('class="twemoji', 'class="md-cheatsheet__icon twemoji', 1) + " "

        title = meta.get("cheatsheet_title") or data["h1_text"] or p.title
        suffix = meta.get("cheatsheet_title_suffix")
        suffix_html = " " + self._render_md(suffix) if suffix else ""

        out = ['<li class="%s"%s>' % (" ".join(classes), self._attr_str(card_attrs))]
        out.append(
            '<p class="md-cheatsheet__title">%s<a class="md-cheatsheet__title-link" href="%s"><strong>%s</strong></a>%s</p>'
            % (icon_html, html.escape(self._link(p, current), quote=True), html.escape(str(title)), suffix_html)
        )
        description = meta.get("cheatsheet_description") or meta.get("description")
        if description:
            out.append('<p class="md-cheatsheet__description">%s</p>' % self._render_md(description))
        if not summary:
            if data["top"]:
                out.append(
                    '<p class="md-cheatsheet__row md-cheatsheet__row--top">%s</p>'
                    % "\n".join(self._term_html(t, p, current) for t in data["top"])
                )
            for row in data["rows"]:
                bits = []
                if row["parent"]:
                    parent = '<a class="md-cheatsheet__parent" href="%s">%s</a>' % (
                        html.escape(self._link(p, current, row["parent"]["anchor"]), quote=True),
                        self._label(row["parent"]["label"], strong=True),
                    )
                    bits.append(parent + ('<span class="md-cheatsheet__colon">:</span>' if row["terms"] else ""))
                bits.extend(self._term_html(t, p, current) for t in row["terms"])
                cls = "md-cheatsheet__row" + ("" if row["parent"] else " md-cheatsheet__row--orphan")
                out.append('<p class="%s"%s>%s</p>' % (cls, self._attr_str(row["attrs"]), "\n".join(bits)))
        out.append("</li>")
        return "\n".join(out), card_attrs

    # -- header button --------------------------------------------------------

    def on_post_page(self, output, page, config):
        if not self.config["button"]:
            return output
        if self._homepage not in self._placeholder_pages:
            if not self._warned_button:
                log.warning(
                    "cheatsheet: 'button: true' needs a <!-- cheatsheet --> placeholder "
                    "on the homepage (%s); the button was not added." % (self._homepage or "index.md")
                )
                self._warned_button = True
            return output
        script = '<script id="%s" type="application/json">%s</script>' % (
            CONFIG_SCRIPT_ID,
            json.dumps({"label": self.config["button_label"]}),
        )
        if "</body>" in output:
            return output.replace("</body>", script + "</body>", 1)
        return output + script
