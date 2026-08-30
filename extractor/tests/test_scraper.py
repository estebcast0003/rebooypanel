from extractor.services.scraper import parse_follower_count, parse_html


def test_parse_follower_count_standard():
    assert parse_follower_count("1,126") == 1126
    assert parse_follower_count("500") == 500
    assert parse_follower_count("1.126") == 1126
    assert parse_follower_count("15,400") == 15400


def test_parse_follower_count_suffixes():
    assert parse_follower_count("1.5K") == 1500
    assert parse_follower_count("2M") == 2_000_000
    assert parse_follower_count("10k") == 10000
    assert parse_follower_count("2.5M") == 2500000


def test_parse_follower_count_invalid():
    assert parse_follower_count("") == 0
    assert parse_follower_count("abc") == 0


def test_parse_html_spanish_description():
    sample_html = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta property="og:title" content="Crónicas Urbanas | Facebook" />
        <meta name="description"
              content="Crónicas Urbanas, Chicago. 1,126 likes · 5 talking about this." />
    </head>
    <body></body>
    </html>
    """
    name, followers, status = parse_html(sample_html)
    assert name == "Crónicas Urbanas"
    assert followers == 1126
    assert status == "Éxito"


def test_parse_html_english_seguidores():
    sample_html = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta property="og:title" content="Tech News Daily" />
        <meta property="og:description"
              content="Tech News Daily. 2.5M seguidores · Noticias de tecnología" />
    </head>
    <body></body>
    </html>
    """
    name, followers, status = parse_html(sample_html)
    assert name == "Tech News Daily"
    assert followers == 2_500_000
    assert status == "Éxito"


def test_parse_html_no_followers_found():
    sample_html = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta property="og:title" content="Private Profile | Facebook" />
    </head>
    <body><div>No metadata</div></body>
    </html>
    """
    name, followers, status = parse_html(sample_html)
    assert name == "Private Profile"
    assert followers == 0
    assert "No se encontraron seguidores" in status
