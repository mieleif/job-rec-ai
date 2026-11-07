"""HTML d'une annonce → Markdown qui garde sa structure (titres, listes, gras, liens).

`text.clean_html` aplatit l'annonce sur une ligne : parfait pour BM25, illisible pour un humain.
La page d'une offre dans DoxAI montre l'annonce telle que l'employeur l'a structurée ; elle la
reçoit en Markdown, un format texte que l'app sait afficher (et traduire) sans jamais injecter de
HTML étranger dans la page.

Sortie volontairement restreinte, quel que soit l'ATS :
- titres `##` (h1, h2) et `###` (h3 à h6), jamais `#` (le titre de la page est celui de l'offre) ;
- paragraphes, listes à puces et numérotées (l'imbrication est aplatie sur un niveau) ;
- gras (`**`) et italique (`*`) ;
- liens `[texte](url)` seulement vers http(s) ; sinon (mailto:, javascript:…) le texte seul ;
- tableaux aplatis en listes : une ligne du tableau = un élément, cellules séparées par « · » ;
- ni images, ni scripts, ni styles, ni iframes, ni HTML brut : tout caractère de la source qui
  a un sens en Markdown (`*`, `_`, `[`, `<`, `#` en début de ligne…) est échappé par `\\`.

Deux conventions d'ATS rattrapées, parce qu'elles sont la structure réelle de l'annonce :
- un paragraphe entièrement en gras et court (« **Vos missions** ») est un titre → `###` ;
- des lignes qui commencent par une puce typographique (« • Python<br>• SQL ») sont une liste.

Bibliothèque standard seulement (`html.parser`), comme `clean_html` : un HTML mal formé ne
fait jamais échouer la conversion, au pire la structure est moins riche.

Principe : le parseur range le texte dans des blocs (genre, texte), où le texte porte encore
des marqueurs internes (caractères de contrôle) pour le gras, l'italique et les retours à la
ligne ; le rendu final les traduit en Markdown une fois les blocs connus.
"""

import re
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urlsplit

# Marqueurs internes : des caractères de contrôle qu'aucune annonce ne contient
_B_OPEN, _B_CLOSE, _I_OPEN, _I_CLOSE, _BR = "\x01", "\x02", "\x03", "\x04", "\x05"
_MARKERS = re.compile("[\x01-\x05]")

# Contenu jamais montré (balises avec fermeture : les balises vides comme <img> sont ignorées)
_SKIPPED = {"script", "style", "noscript", "template", "iframe", "svg", "object", "video",
            "audio", "canvas", "select", "button", "head", "title", "math"}
_HEADINGS = {"h1": "h2", "h2": "h2", "h3": "h3", "h4": "h3", "h5": "h3", "h6": "h3"}
# Balises « bloc » : elles ferment le paragraphe en cours
_PARAGRAPHS = {"p", "div", "section", "article", "header", "footer", "main", "aside", "nav",
               "blockquote", "pre", "hr", "dl", "dt", "dd", "figure", "figcaption", "address",
               "center", "form", "fieldset", "details", "summary", "caption", "body", "html"}
_BOLD, _ITALIC = {"strong", "b"}, {"em", "i"}

# Caractères qui ont un sens en Markdown n'importe où dans une ligne (| : tableaux GFM ;
# ~ : barré GFM ; < > : HTML brut et liens automatiques)
_INLINE_SPECIAL = re.compile(r"([\\`*_\[\]<>|~])")
# Entité restée échappée après un premier décodage (« &amp;#160; » → « &#160; »)
_ENTITY = re.compile(r"&(#\d+|#x[0-9a-fA-F]+|[a-zA-Z]{2,8});")
# Puces typographiques en début de ligne : « • Python », « – SQL », « - dbt »
_BULLET_START = re.compile(r"^(?:[•▪●■◦►▸➢✓✔·–—-]|\\\*)\s+")
# Puces au fil du texte : « missions : • Analyser … • Rédiger … » (deux au moins pour y croire)
_BULLET_INLINE = re.compile(r"(?:^|\s)[•▪●■◦►▸➢]\s+")
# Une phrase collée à la suivante quand l'ATS a perdu le saut de paragraphe : « cantonal.Dans »
_GLUED_SENTENCE = re.compile(r"(?<=[a-zà-ÿ]{2}[.!?])(?=[A-ZÀ-Ý][a-zà-ÿ])")
# Débuts de ligne qui changeraient la ligne en titre, citation, liste ou séparateur
_LINE_START = re.compile(r"^([#>+=-])|^(\d{1,9})([.)])(?=\s|$)")

HEADING_MAX = 80  # caractères : au-delà, un paragraphe en gras est une phrase, pas un titre


def _escape(text: str) -> str:
    return _INLINE_SPECIAL.sub(r"\\\1", text)


def _escape_line_start(line: str) -> str:
    """« # 1 », « - x », « 2026. Une année » en début de ligne : échappés pour rester du texte."""
    return _LINE_START.sub(lambda m: f"\\{m.group(1)}" if m.group(1)
                           else f"{m.group(2)}\\{m.group(3)}", line, count=1)


def _url(href: str | None) -> str | None:
    """L'URL d'un lien si elle est http(s), prête à mettre entre parenthèses ; None sinon."""
    href = (href or "").strip()
    if urlsplit(href).scheme.lower() not in ("http", "https"):
        return None
    for char, code in ((" ", "%20"), ("(", "%28"), (")", "%29"), ("<", "%3C"), (">", "%3E")):
        href = href.replace(char, code)
    return href


def _balance(text: str, opening: str, closing: str) -> str:
    """Marqueurs appariés : un fermant orphelin est retiré, un ouvrant orphelin refermé (un gras
    coupé par un paragraphe ou un <br> ne doit pas déborder sur la suite)."""
    out, depth = [], 0
    for char in text:
        if char == opening:
            depth += 1
        elif char == closing:
            if not depth:
                continue
            depth -= 1
        out.append(char)
    return "".join(out) + closing * depth


def _tidy(text: str) -> str:
    """Espaces réduits, et sortis des marqueurs (« ** gras **» ne s'afficherait pas en gras)."""
    text = re.sub(r"\s+", " ", text)
    previous = None
    while previous != text:
        previous = text
        text = re.sub(f"([{_B_OPEN}{_I_OPEN}]) ", r" \1", text)
        text = re.sub(f" ([{_B_CLOSE}{_I_CLOSE}])", r"\1 ", text)
        text = re.sub(f" ?{_BR} ?", _BR, text).replace("  ", " ")
        for opening, closing in ((_B_OPEN, _B_CLOSE), (_I_OPEN, _I_CLOSE)):
            # Vide, ou deux passages qui se touchent (« <b>Inform</b><b>ation</b> ») : fusionnés
            text = text.replace(opening + closing, "").replace(closing + opening, "")
            text = text.replace(f"{closing} {opening}", " ")
    return text


def _inline(text: str) -> str:
    """Marqueurs restants → Markdown (texte d'une seule ligne, déjà équilibré)."""
    text = text.replace(_B_OPEN, "**").replace(_B_CLOSE, "**")
    return text.replace(_I_OPEN, "*").replace(_I_CLOSE, "*").strip()


def _bold_heading(line: str) -> str | None:
    """Le texte d'un titre si la ligne n'est qu'un court passage en gras, None sinon."""
    if not (line.startswith(_B_OPEN) and line.endswith(_B_CLOSE)):
        return None
    inner = line[1:-1]
    if _B_OPEN in inner or _B_CLOSE in inner:  # deux passages en gras, pas un seul
        return None
    inner = _MARKERS.sub("", inner).strip()
    if not inner or len(inner) > HEADING_MAX or inner.endswith((".", "!", "?", ";", ",")):
        return None
    return inner


def _balanced(text: str) -> str:
    return _balance(_balance(text, _B_OPEN, _B_CLOSE), _I_OPEN, _I_CLOSE)


def _line_blocks(line: str, first: bool) -> list[tuple[str, str]]:
    """Une ligne de paragraphe → blocs : titre en gras, éléments de liste à puces, texte.
    `first` : la ligne ouvre son paragraphe. Seule celle-là peut être un titre : plus bas,
    « **Taux**<br>80 % » est une étiquette, pas une section."""
    parts = _BULLET_INLINE.split(line)
    if len(parts) > 2 or _BULLET_START.match(line):
        if len(parts) <= 2:  # une seule puce, en tête de ligne
            parts = ["", _BULLET_START.sub("", line, count=1)]
        blocks = [("p", _balanced(parts[0]))] if _MARKERS.sub("", parts[0]).strip() else []
        return blocks + [("ul", _balanced(p)) for p in parts[1:] if _MARKERS.sub("", p).strip()]
    heading = _bold_heading(line) if first else None
    return [("h3", heading)] if heading else [("p", line)]


def _paragraph_blocks(text: str) -> list[tuple[str, str]]:
    """Le texte d'un bloc « paragraphe » : une ligne par <br>, chacune devient un bloc."""
    blocks: list[tuple[str, str]] = []
    first, carry = True, ""
    for line in _tidy(text).split(_BR):
        line = carry + line.strip()
        # Un gras (ou italique) ouvert qui continue à la ligne suivante y est rouvert : chaque
        # ligne devient un bloc, elle doit se suffire à elle-même
        carry = "".join(opening for opening, closing in ((_B_OPEN, _B_CLOSE), (_I_OPEN, _I_CLOSE))
                        if _balance(line, opening, closing).endswith(closing)
                        and not line.endswith(closing))
        if not _MARKERS.sub("", line).strip():
            first = True  # ligne vide (<br><br>) : un nouveau paragraphe commence
            continue
        blocks += _line_blocks(_balanced(line), first and not carry)
        first = False
    return blocks


class _MarkdownBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[tuple[str, str]] = []  # (genre, texte avec marqueurs)
        self.buf: list[str] = []
        self.kind = "p"  # genre du bloc en cours : p, h2, h3, ul, ol:<numéro>
        self.skip = 0
        self.lists: list[list] = []  # pile des listes ouvertes : [balise, prochain numéro]
        self.items = 0  # profondeur des <li> ouverts
        self.links: list[tuple[int, str | None]] = []  # (début du texte dans buf, url)
        self.row: list[str] | None = None  # cellules de la ligne de tableau en cours
        self.bold = self.italic = 0

    # --- blocs ---------------------------------------------------------------------------

    def _item_kind(self) -> str:
        if not self.lists:
            return "ul"
        tag, number = self.lists[-1]
        if tag == "ol":
            self.lists[-1][1] += 1
            return f"ol:{number}"
        return "ul"

    def _take(self) -> str:
        """Le texte en cours ; un gras ou un italique ouvert est refermé ici et rouvert après."""
        text = "".join(self.buf) + _B_CLOSE * bool(self.bold) + _I_CLOSE * bool(self.italic)
        self.buf = [_B_OPEN] * bool(self.bold) + [_I_OPEN] * bool(self.italic)
        self.links = [(-1, url) for _, url in self.links]  # un lien coupé par un bloc : texte
        return text

    def _flush(self, next_kind: str | None = None) -> None:
        text, kind = self._take(), self.kind
        self.kind = next_kind or ("ul" if self.items else "p")
        if kind == "p":
            self.blocks += _paragraph_blocks(text)
            return
        text = text.replace(_BR, " ")
        text = _tidy(_MARKERS.sub("", text) if kind in ("h2", "h3") else text).strip()
        if _MARKERS.sub("", text).strip():
            self.blocks.append((kind, _balanced(text)))

    def _end_row(self) -> None:
        """Une ligne de tableau → un élément de liste, ses cellules séparées par « · »."""
        if self.row is None:
            return
        cells = [_MARKERS.sub("", c).strip() for c in [*self.row, self._take()]]
        self.row = None
        text = " · ".join(c for c in cells if c)
        if text:
            self.blocks.append(("ul", _tidy(text).strip()))

    def _leave_row(self) -> None:
        """Un bloc dans une cellule : tableau de mise en page, pas de données. Ce qui précède
        devient un paragraphe et la suite est lue normalement."""
        if self.row is None:
            return
        cells = [*self.row, self._take()]
        self.row = None
        self.blocks += _paragraph_blocks(" ".join(cells))

    # --- événements du parseur -----------------------------------------------------------

    def handle_starttag(self, tag, attrs):
        if self.skip or tag in _SKIPPED:
            self.skip += tag in _SKIPPED
            return
        if tag in _HEADINGS:
            self._leave_row()
            self._flush(_HEADINGS[tag])
        elif tag in _PARAGRAPHS:
            if self.items:
                self.buf.append(" ")
            else:
                self._leave_row()
                self._flush()
        elif tag in ("ul", "ol", "menu"):
            self._leave_row()
            self._flush()
            start = dict(attrs).get("start") or "1"
            self.lists.append(["ol" if tag == "ol" else "ul",
                               int(start) if start.isdigit() else 1])
        elif tag == "li":
            self._leave_row()
            self._flush()
            self.items += 1
            self.kind = self._item_kind()
        elif tag == "tr":
            self._end_row()
            self._flush()
            self.row = []
        elif tag in ("td", "th"):
            if self.row is not None and (self.buf and "".join(self.buf).strip()):
                self.row.append(self._take())
        elif tag == "table":
            self._end_row()
            self._flush()
        elif tag == "br":
            self.buf.append(" " if self.row is not None else _BR)
        elif tag in _BOLD:
            self.bold += 1
            self.buf.append(_B_OPEN if self.bold == 1 else "")
        elif tag in _ITALIC:
            self.italic += 1
            self.buf.append(_I_OPEN if self.italic == 1 else "")
        elif tag == "a":
            self.links.append((len(self.buf), _url(dict(attrs).get("href"))))

    def handle_startendtag(self, tag, attrs):
        if tag in ("br", "hr"):  # <br/> : sans fermeture, rien d'autre à faire
            self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if self.skip:
            self.skip -= tag in _SKIPPED
            return
        if tag in _HEADINGS:
            self._flush()
        elif tag in _PARAGRAPHS:
            if self.items:
                self.buf.append(" ")
            elif self.row is None:
                self._flush()
        elif tag == "li":
            self._flush()
            self.items = max(0, self.items - 1)
            self.kind = self._item_kind() if self.items else "p"
        elif tag in ("ul", "ol", "menu"):
            self._flush()
            if self.lists:
                self.lists.pop()
            self.kind = "ul" if self.items else "p"
        elif tag == "tr":
            self._end_row()
        elif tag in ("td", "th"):
            if self.row is not None:
                self.row.append(self._take())
        elif tag == "table":
            self._end_row()
            self._flush()
        elif tag in _BOLD and self.bold:
            self.bold -= 1
            self.buf.append(_B_CLOSE if not self.bold else "")
        elif tag in _ITALIC and self.italic:
            self.italic -= 1
            self.buf.append(_I_CLOSE if not self.italic else "")
        elif tag == "a" and self.links:
            start, url = self.links.pop()
            label = "".join(self.buf[start:]).replace(_BR, " ") if start >= 0 else ""
            if url and _MARKERS.sub("", label).strip():
                inner = label.strip()
                before, after = label[:label.index(inner[0])], label[len(label.rstrip()):]
                self.buf[start:] = [before, "[", _balanced(inner), f"]({url})", after]

    def handle_data(self, data):
        if self.skip:
            return
        if _ENTITY.search(data):  # entités échappées deux fois (JSON-LD de certains sites)
            data = unescape(data)
        data = data.replace("\xa0", " ").replace("​", "").replace("﻿", "")
        self.buf.append(_escape(_MARKERS.sub("", data)))

    def close(self):
        super().close()
        self._end_row()
        self._flush()


def _render(blocks: list[tuple[str, str]]) -> str:
    lines: list[str] = []
    previous = None
    for kind, text in blocks:
        text = _inline(text)
        if not text:
            continue
        if kind in ("h2", "h3"):
            line = f"{'#' * int(kind[1])} {text}"
        elif kind == "ul":
            line = f"- {_escape_line_start(text)}"
        elif kind.startswith("ol:"):
            line = f"{kind[3:]}. {_escape_line_start(text)}"
        else:
            line = _escape_line_start(text)
        family = kind[:2]  # ul, ol, h2, h3, p
        if lines:  # éléments d'une même liste collés ; tout le reste séparé par une ligne vide
            lines.append("\n" if family in ("ul", "ol") and family == previous else "\n\n")
        lines.append(line)
        previous = family
    return "".join(lines)


def html_to_markdown(html: str | None) -> str:
    """HTML d'une annonce → Markdown structuré (voir le module). Sans balise : texte brut."""
    if not html:
        return ""
    # Certains ATS (Greenhouse) renvoient du HTML lui-même échappé : « &lt;p&gt; »
    if "<" not in html and "&lt;" in html:
        html = unescape(html)
    if not re.search(r"<[a-zA-Z!/]", html):
        return text_to_markdown(unescape(html))
    parser = _MarkdownBuilder()
    parser.feed(html)
    parser.close()
    return _render(parser.blocks)


def text_to_markdown(text: str | None) -> str:
    """Texte brut → paragraphes Markdown : un par ligne non vide (et par phrase recollée à la
    précédente, « cantonal.Dans »), les lignes à puce en liste, le tout échappé."""
    if not text:
        return ""
    for _ in range(2):  # entités parfois échappées deux fois (« &amp;#039; »)
        if _ENTITY.search(text):
            text = unescape(text)
    text = text.replace("\xa0", " ").replace("​", "").replace("﻿", "")
    lines = _GLUED_SENTENCE.sub("\n", _escape(_MARKERS.sub("", text)))
    return _render(_paragraph_blocks(lines.replace("\n", _BR)))


def join_markdown(parts) -> str:
    """Plusieurs champs d'une annonce (description, missions, profil…) → un seul Markdown."""
    return "\n\n".join(p for p in parts if p)
