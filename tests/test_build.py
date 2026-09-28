"""Checks the generated cheatsheet markup in the built fixture site."""

import re


def read(built_site, rel):
    return (built_site["site_dir"] / rel).read_text()


def cheatsheet(html):
    start = html.index('<div class="md-cheatsheet')
    return html[start : html.index("</article>", start)]


def home(built_site):
    return cheatsheet(read(built_site, "index.html"))


def test_top_items_come_from_h1_and_link_to_it(built_site):
    top = re.search(r'md-cheatsheet__row--top">(.*?)</p>', home(built_site), re.S).group(1)
    assert re.findall(r"<code>(.*?)</code>", top) == ["purr", "whiskers"]
    assert 'href="mammals/cats/#cats"' in top


def test_h2_parent_with_extra_labels_and_sorted_terms(built_site):
    row = re.search(r'href="mammals/cats/#big-cats"><strong><code>big cats</code>.*?</p>', home(built_site), re.S).group(0)
    labels = re.findall(r'md-cheatsheet__term" href="[^"]*"><code>(.*?)</code>', row)
    assert labels == ["Lion", "roar", "stripes", "tiger"]


def test_unflagged_and_fenced_headings_are_ignored(built_site):
    cs = home(built_site)
    assert "Breeds" not in cs
    assert "Not a heading" not in cs
    assert "#small-cats" not in cs  # unflagged h2: its flagged child renders without a parent


def test_escaped_comma_keeps_one_term(built_site):
    assert "<code>naps, lots of them</code>" in home(built_site)


def test_data_attributes_carry_over(built_site):
    cs = home(built_site)
    assert '<p class="md-cheatsheet__row" data-fcm-hide="essentials">' in cs
    assert '<span class="md-cheatsheet__term-wrap" data-fcm-hide="essentials">' in cs


def test_marker_is_stripped_from_page(built_site):
    page = read(built_site, "mammals/cats/index.html")
    assert "data-cheatsheet" not in page
    assert "Big cats {cs" not in page


def test_description_prefers_cheatsheet_description(built_site):
    cs = home(built_site)
    assert "Marine mammals. Nothing on this page is flagged." in cs
    assert "Search-engine description" not in cs


def test_group_titles_follow_nav_with_overrides(built_site):
    titles = re.findall(r'md-cheatsheet__group-title">(.*?)<', home(built_site))
    assert titles == ["Mammals", "Raptors"]


def test_section_with_own_cheatsheet_is_summarized_on_parent(built_site):
    cs = home(built_site)
    birds = cheatsheet(read(built_site, "birds/index.html"))
    assert "md-cheatsheet__group--summary" in cs
    assert "owls/#feathers" not in cs
    assert 'href="owls/#feathers"' in birds
    assert "Mammals" not in birds


def test_card_attrs_and_shared_group_attrs(built_site):
    birds = cheatsheet(read(built_site, "birds/index.html"))
    assert '<li class="md-cheatsheet__card" data-fcm-hide="essentials">' in birds
    assert re.search(r'md-cheatsheet__group [^"]*" data-cheatsheet-cards="1" data-fcm-hide="essentials"', birds)


def test_icon_from_front_matter_and_h1(built_site):
    assert home(built_site).count("md-cheatsheet__icon") == 2  # Cats (front matter) + Owls (h1)


def test_placeholder_pages_are_not_cards(built_site):
    cs = home(built_site)
    assert 'href="birds/"' not in cs
    assert 'href="./"' not in cs


def test_card_title_defaults_to_h1(built_site):
    titles = re.findall(r'md-cheatsheet__title-link"[^>]*><strong>(.*?)</strong>', home(built_site))
    assert titles == ["Cats", "Whales and dolphins", "Owls"]  # h1 text (nav says "Whales"), icon excluded


def test_placeholder_in_code_block_is_ignored(built_site):
    assert 'href="mammals/whales/"' in home(built_site)  # still a card, not treated as a cheatsheet page
    page = read(built_site, "mammals/whales/index.html")
    assert "&lt;!-- cheatsheet --&gt;" in page
    assert "md-cheatsheet__card" not in page
